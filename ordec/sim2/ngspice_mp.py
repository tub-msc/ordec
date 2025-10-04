# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import multiprocessing
from multiprocessing import Process, Pipe, Queue
import pickle
from contextlib import contextmanager
import traceback
import queue  # For queue.Empty exception
import threading
import time

from .ngspice_common import NgspiceTransientResult

_ASYNC_SIM_SENTINEL = "---ASYNC_SIM_SENTINEL---"


try:
    if multiprocessing.get_start_method() != "spawn":
        multiprocessing.set_start_method("spawn", force=True)
except (RuntimeError, AttributeError):
    pass


class FFIWorkerProcess:
    """
    This worker runs in a separate process. It creates an FFI backend
    instance and acts as a bridge, forwarding commands and results between the
    worker process and the FFI backend implementation.
    """

    # TODO performance

    def __init__(self, conn: Pipe, async_queue: Queue, debug: bool = False):
        self.conn = conn
        self.async_queue = async_queue
        self._shutdown_event = None
        self._relay_thread = None
        self.backend = None
        self._progress_lock = None
        self._last_progress = 0.0
        self.debug = debug

    def _handle_data_fallback(self):
        """Handle data retrieval fallback when normal callbacks don't work"""
        try:
            import time

            # Small delay to ensure simulation is fully complete
            time.sleep(0.1)

            # Check if we need fallback (no data received but simulation completed)
            if self.async_queue.empty():
                # Get current vectors from ngspice via backend
                vector_names = self.backend._get_all_vectors()
                if vector_names and "time" in vector_names:
                    # Extract actual vector data
                    vector_data_map = {}
                    num_points = 0

                    for vec_name in vector_names:
                        vec_info = self.backend._get_vector_info(vec_name)
                        if vec_info and vec_info.v_length > 0:
                            num_points = max(num_points, vec_info.v_length)
                            data_list = [
                                vec_info.v_realdata[i] for i in range(vec_info.v_length)
                            ]
                            vector_data_map[vec_name] = data_list

                    if num_points > 0 and "time" in vector_data_map:
                        # Sample every 10th point to avoid overwhelming the queue
                        sample_indices = range(0, num_points, max(1, num_points // 100))

                        for i, sample_idx in enumerate(sample_indices):
                            data_points = {}
                            for name, values in vector_data_map.items():
                                if sample_idx < len(values):
                                    data_points[name] = values[sample_idx]

                            if data_points:
                                progress = min((i + 1) / len(sample_indices), 1.0)
                                self.async_queue.put(
                                    {
                                        "timestamp": time.time(),
                                        "data": data_points,
                                        "index": sample_idx,
                                        "progress": progress,
                                    }
                                )

        except Exception as e:
            # Log fallback errors but don't crash the simulation
            import logging

            logging.error("Exception in _handle_data_fallback: %s", e)
            if self.debug:
                import traceback

                logging.debug("Fallback traceback: %s", traceback.format_exc())

    def run(self):
        """Main worker loop. Waits for commands and dispatches them."""
        from .ngspice_ffi import NgspiceFFI
        import traceback  # Ensure traceback is available in worker process

        # Initialize thread synchronization objects (can't pickle these)
        self._shutdown_event = threading.Event()
        self._progress_lock = threading.Lock()
        self._command_queue = queue.Queue()
        self._response_queue = queue.Queue()
        self._async_active = threading.Event()

        msg = self.conn.recv()
        if msg["type"] == "init":
            try:
                self.backend = NgspiceFFI(debug=msg.get("debug", False))
                self.conn.send({"type": "init_success"})
            except Exception as e:
                self.conn.send(
                    {
                        "type": "error",
                        "data": pickle.dumps(e),
                        "traceback": traceback.format_exc(),
                    }
                )
                return
        else:
            return

        # Start command handler thread
        command_thread = threading.Thread(target=self._command_handler, daemon=True)
        command_thread.start()

        # Main communication loop
        while True:
            try:
                msg = self.conn.recv()
            except (EOFError, BrokenPipeError):
                break
            except Exception as e:
                if (
                    hasattr(self, "backend")
                    and self.backend
                    and hasattr(self.backend, "debug")
                    and self.backend.debug
                ):
                    import traceback

                    print(
                        f"[ngspice-mp] Worker recv error: {e}\n{traceback.format_exc()}"
                    )
                break

            if msg["type"] == "quit":
                self._shutdown_event.set()
                if self.backend:
                    self.backend.cleanup()
                break

            # Put command in queue for handler thread
            self._command_queue.put(msg)

            # Wait for response from handler thread
            try:
                response = self._response_queue.get(timeout=60)
                self.conn.send(response)
            except queue.Empty:
                self.conn.send(
                    {
                        "type": "error",
                        "data": pickle.dumps(RuntimeError("Command timeout")),
                    }
                )
            except (BrokenPipeError, EOFError):
                break

    def _command_handler(self):
        """Handle commands in separate thread to allow concurrent async simulation"""
        import traceback

        while not self._shutdown_event.is_set():
            try:
                msg = self._command_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            cmd = msg["type"]
            args = msg.get("args", [])
            kwargs = msg.get("kwargs", {})

            try:
                method = getattr(self.backend, cmd)

                if cmd in ["tran_async", "op_async"]:
                    try:
                        # Start async simulation
                        self._async_active.set()
                        ffi_queue = method(*args, **kwargs)

                        # Start relay thread
                        self._start_relay_thread(ffi_queue)

                        # Send immediate acknowledgment
                        self._response_queue.put(
                            {
                                "type": "result",
                                "data": pickle.dumps({"async_started": True}),
                            }
                        )

                    except Exception as e:
                        self._response_queue.put(
                            {
                                "type": "error",
                                "data": pickle.dumps(e),
                                "traceback": traceback.format_exc(),
                            }
                        )

                elif cmd == "stop_simulation" and self._async_active.is_set():
                    # Handle halt during async simulation
                    try:
                        result = method(*args, **kwargs)
                        self._async_active.clear()
                        self._response_queue.put(
                            {"type": "result", "data": pickle.dumps(result)}
                        )
                    except Exception as e:
                        self._response_queue.put(
                            {
                                "type": "error",
                                "data": pickle.dumps(e),
                                "traceback": traceback.format_exc(),
                            }
                        )

                elif cmd == "resume_simulation" and not self._async_active.is_set():
                    # Handle resume after halt
                    try:
                        result = method(*args, **kwargs)
                        self._async_active.set()
                        self._response_queue.put(
                            {"type": "result", "data": pickle.dumps(result)}
                        )
                    except Exception as e:
                        self._response_queue.put(
                            {
                                "type": "error",
                                "data": pickle.dumps(e),
                                "traceback": traceback.format_exc(),
                            }
                        )

                else:
                    # Handle regular commands
                    try:
                        result = method(*args, **kwargs)
                        if hasattr(result, "__iter__") and not isinstance(
                            result, (list, tuple, dict, str, NgspiceTransientResult)
                        ):
                            result = list(result)
                        self._response_queue.put(
                            {"type": "result", "data": pickle.dumps(result)}
                        )
                    except Exception as e:
                        self._response_queue.put(
                            {
                                "type": "error",
                                "data": pickle.dumps(e),
                                "traceback": traceback.format_exc(),
                            }
                        )

            except Exception as e:
                self._response_queue.put(
                    {
                        "type": "error",
                        "data": pickle.dumps(e),
                        "traceback": traceback.format_exc(),
                    }
                )

    def _start_relay_thread(self, ffi_queue):
        """Start a relay thread with proper synchronization"""

        def relay_data():
            """Relay data from FFI queue to multiprocess queue with proper synchronization"""
            import queue as queue_module

            progress_counter = 0
            start_time = time.time()

            try:
                while not self._shutdown_event.is_set() and self._async_active.is_set():
                    try:
                        # Block until data is available with timeout
                        data_point = ffi_queue.get(timeout=0.5)

                        # Add progress tracking with thread safety
                        if isinstance(data_point, dict):
                            if self._progress_lock:
                                self._progress_lock.acquire()
                            try:
                                if "progress" not in data_point:
                                    progress_counter += 1
                                    # More conservative progress estimation
                                    data_point["progress"] = min(
                                        progress_counter * 0.02, 0.95
                                    )

                                # Ensure progress is monotonic and bounded
                                current_progress = data_point.get("progress", 0)
                                data_point["progress"] = max(
                                    min(current_progress, 1.0), self._last_progress
                                )
                                self._last_progress = data_point["progress"]
                            finally:
                                if self._progress_lock:
                                    self._progress_lock.release()

                        # Put data in queue with timeout to avoid blocking
                        try:
                            self.async_queue.put(data_point, timeout=1.0)
                        except queue_module.Full:
                            # Skip this data point if queue is full
                            continue

                    except queue_module.Empty:
                        # Check if simulation finished
                        if not self.backend.is_running():
                            self._async_active.clear()
                            # Implement data fallback mechanism
                            self._handle_data_fallback()

                            # Drain any remaining data
                            remaining_count = 0
                            while (
                                remaining_count < 100
                            ):  # Limit to prevent infinite loop
                                try:
                                    data_point = ffi_queue.get_nowait()
                                    if isinstance(data_point, dict):
                                        if self._progress_lock:
                                            self._progress_lock.acquire()
                                        try:
                                            if "progress" not in data_point:
                                                data_point["progress"] = 1.0
                                            else:
                                                # Ensure final progress doesn't go backwards
                                                data_point["progress"] = max(
                                                    data_point["progress"],
                                                    self._last_progress,
                                                    1.0,
                                                )
                                            self._last_progress = data_point["progress"]
                                        finally:
                                            if self._progress_lock:
                                                self._progress_lock.release()

                                    try:
                                        self.async_queue.put(data_point, timeout=0.1)
                                    except queue_module.Full:
                                        break  # Queue full, stop draining
                                    remaining_count += 1
                                except queue_module.Empty:
                                    break
                            break
                        # Continue waiting for data
                        continue
            except Exception as e:
                # Log errors if debug is enabled
                if (
                    hasattr(self, "backend")
                    and self.backend
                    and hasattr(self.backend, "debug")
                    and self.backend.debug
                ):
                    print(
                        f"[ngspice-mp] Relay thread error: {e}\n{traceback.format_exc()}"
                    )

        # Initialize progress tracking
        if self._progress_lock:
            self._progress_lock.acquire()
            try:
                self._last_progress = 0.0
            finally:
                self._progress_lock.release()

        self._relay_thread = threading.Thread(target=relay_data, daemon=True)
        self._relay_thread.start()


class NgspiceIsolatedFFI:
    """
    A proxy that runs FFI calls in an isolated child process.
    """

    @staticmethod
    @contextmanager
    def launch(debug=False):
        parent_conn, child_conn = Pipe()
        async_queue = Queue()

        worker = FFIWorkerProcess(child_conn, async_queue, debug=debug)
        p = Process(target=worker.run)
        p.start()

        backend = NgspiceIsolatedFFI(parent_conn, p, async_queue)
        try:
            parent_conn.send({"type": "init", "debug": debug})
            response = parent_conn.recv()
            if response["type"] == "error":
                exc = pickle.loads(response["data"])
                exc.args += (f"\n{response['traceback']}",)
                raise exc
            yield backend
        finally:
            if backend:
                try:
                    backend.close()
                except Exception:
                    pass
            if p.is_alive():
                p.join(timeout=2)
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=1)
                    if p.is_alive():
                        p.kill()

    def __init__(self, conn, process, async_queue):
        self.conn = conn
        self.process = process
        self.async_queue = async_queue
        self._async_simulation_running = False

    def close(self):
        try:
            if not self.conn.closed:
                self.conn.send({"type": "quit"})
        except BrokenPipeError:
            pass
        finally:
            if not self.conn.closed:
                self.conn.close()

    def _call_worker(self, msg_type, *args, **kwargs):
        if self.conn.closed:
            raise RuntimeError("Connection to FFI worker process is closed.")

        # Use a lock to ensure atomic send/receive operations
        if not hasattr(self, "_comm_lock"):
            self._comm_lock = threading.Lock()

        with self._comm_lock:
            try:
                # Send command with retry logic
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        self.conn.send(
                            {"type": msg_type, "args": args, "kwargs": kwargs}
                        )
                        break
                    except (BrokenPipeError, EOFError) as e:
                        if attempt == max_retries - 1:
                            raise RuntimeError(
                                f"Failed to send command to worker process after {max_retries} attempts: {e}"
                            )
                        time.sleep(0.01)  # Brief delay before retry

                # Wait for response with proper timeout handling
                response = None
                timeout_seconds = 30
                poll_interval = 0.1
                elapsed = 0

                while elapsed < timeout_seconds:
                    if self.conn.poll(timeout=poll_interval):
                        try:
                            response = self.conn.recv()
                            break
                        except (EOFError, BrokenPipeError) as e:
                            raise RuntimeError(
                                f"Worker process communication failed: {e}"
                            )
                        except Exception as e:
                            if "invalid load key" in str(e) or "unpickling" in str(e):
                                # Pickle corruption - likely a race condition
                                raise RuntimeError(
                                    f"Data corruption in worker communication: {e}"
                                )
                            raise RuntimeError(
                                f"Worker process communication error: {e}"
                            )
                    elapsed += poll_interval

                    # Check if worker process is still alive (but allow some time for error handling)
                    if not self.process.is_alive() and elapsed > 5:
                        raise RuntimeError("Worker process died during communication")

                if response is None:
                    raise RuntimeError(
                        f"Timeout waiting for worker process response ({timeout_seconds}s)"
                    )

                # Process response
                if response["type"] == "result":
                    try:
                        return pickle.loads(response["data"])
                    except Exception as e:
                        raise RuntimeError(
                            f"Failed to deserialize worker response: {e}"
                        )
                elif response["type"] == "error":
                    try:
                        exc = pickle.loads(response["data"])
                        # Re-raise the original exception type
                        raise exc
                    except (pickle.PickleError, TypeError, ImportError):
                        # If deserialization fails, create a generic RuntimeError
                        traceback_info = response.get(
                            "traceback", "No traceback available"
                        )
                        raise RuntimeError(
                            f"Worker process error: Failed to deserialize exception\n--- Traceback from worker process ---\n{traceback_info}"
                        )
                else:
                    raise RuntimeError(
                        f"Unknown response type from worker: {response['type']}"
                    )
            except Exception as e:
                # Re-raise exceptions, but don't wrap them unnecessarily
                raise

    def _async_results_generator(self):
        """Generate results from async queue with proper error handling"""
        timeout_count = 0
        max_timeouts = 100  # Allow some timeouts before giving up

        while True:
            try:
                # Use timeout to prevent hanging forever
                item = self.async_queue.get(timeout=0.5)
                timeout_count = 0  # Reset timeout counter on successful get

                if item == _ASYNC_SIM_SENTINEL:
                    self._async_simulation_running = False
                    break
                yield item
            except queue.Empty:
                timeout_count += 1
                if timeout_count > max_timeouts:
                    # Been waiting too long, check if worker is still alive
                    if not self.process.is_alive():
                        self._async_simulation_running = False
                        break
                    # Reset counter and continue waiting
                    timeout_count = 0
                continue
            except (EOFError, BrokenPipeError):
                self._async_simulation_running = False
                break
            except Exception as e:
                # Log unexpected errors but continue
                if hasattr(self, "_debug") and self._debug:
                    print(f"[ngspice-mp] Async generator error: {e}")
                break

    def command(self, command: str) -> str:
        return self._call_worker("command", command)

    def load_netlist(self, netlist: str, no_auto_gnd: bool = True):
        return self._call_worker("load_netlist", netlist, no_auto_gnd=no_auto_gnd)

    def op(self):
        return self._call_worker("op")

    def tran(self, *args):
        return self._call_worker("tran", *args)

    def ac(self, *args, **kwargs):
        return self._call_worker("ac", *args, **kwargs)

    def is_running(self) -> bool:
        try:
            return self._call_worker("is_running")
        except RuntimeError:
            # If worker communication fails, assume not running
            return False

    def stop_simulation(self):
        return self._call_worker("stop_simulation")

    def resume_simulation(self, timeout=2.0):
        return self._call_worker("resume_simulation", timeout=timeout)

    def reset(self):
        return self._call_worker("reset")

    def cleanup(self):
        pass

    def _create_async_generator(self, cmd, *args, callback=None, **kwargs):
        # callback is now an explicit parameter and must NOT be forwarded to the worker
        self._call_worker(cmd, *args, **kwargs)

        def generator_with_callback():
            for item in self._async_results_generator():
                if callback:
                    try:
                        callback(item)
                    except Exception as e:
                        print(f"Error in async callback: {e}")
                yield item

        return generator_with_callback()

    def tran_async(
        self, tstep, tstop=None, *extra_args, throttle_interval: float = 0.1
    ):
        self._call_worker(
            "tran_async", tstep, tstop, *extra_args, throttle_interval=throttle_interval
        )
        return self.async_queue

    def safe_halt_simulation(self, max_attempts: int = 3, wait_time: float = 1.0):
        import time
        import concurrent.futures

        if not self.is_running():
            return True

        for attempt in range(max_attempts):
            try:
                result = self._call_worker("stop_simulation")
                self._async_simulation_running = False
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:

                    def check_halt_status():
                        return not self.is_running()

                    timeout = time.time() + wait_time
                    while time.time() < timeout:
                        halt_future = executor.submit(check_halt_status)
                        try:
                            if halt_future.result(timeout=min(0.01, wait_time)):
                                return result
                        except concurrent.futures.TimeoutError:
                            pass
                        finally:
                            if not halt_future.done():
                                halt_future.cancel()

            except Exception:
                pass

            # Wait before retry (except on last attempt)
            if attempt < max_attempts - 1:
                time.sleep(wait_time)

        # use actual worker state, not our flag
        try:
            return self._call_worker("is_running") == False
        except:
            return False

    def safe_resume_simulation(self, max_attempts: int = 3, wait_time: float = 2.0):
        import time
        import concurrent.futures

        if self.is_running():
            return True

        for attempt in range(max_attempts):
            try:
                # Send resume command to worker
                result = self._call_worker("resume_simulation", timeout=wait_time)
                if result:
                    self._async_simulation_running = True
                    return True

                # Verify resume succeeded
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:

                    def check_resume_status():
                        """Check if simulation has resumed"""
                        return self.is_running()

                    timeout = time.time() + wait_time
                    while time.time() < timeout:
                        resume_future = executor.submit(check_resume_status)
                        try:
                            if resume_future.result(timeout=min(0.01, wait_time)):
                                self._async_simulation_running = True
                                return True
                        except concurrent.futures.TimeoutError:
                            pass
                        finally:
                            if not resume_future.done():
                                resume_future.cancel()

            except Exception:
                pass

            # Wait before retry (except on last attempt)
            if attempt < max_attempts - 1:
                time.sleep(wait_time)

        return False

    def tran_async(self, tstep, tstop=None, *extra_args, **kwargs):
        self._async_simulation_running = True
        self._call_worker("tran_async", tstep, tstop, *extra_args, **kwargs)
        return self.async_queue

    def op_async(self, *args, **kwargs):
        self._async_simulation_running = True
        self._call_worker("op_async", *args, **kwargs)
        return self.async_queue
