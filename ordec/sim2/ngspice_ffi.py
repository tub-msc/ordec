# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import ctypes
import os
import re
import sys
import queue
import time
from contextlib import contextmanager
from typing import Iterator, List, Optional, Callable, Generator

from .ngspice_common import (
    NgspiceValue,
    NgspiceError,
    NgspiceFatalError,
    NgspiceConfigError,
    NgspiceTransientResult,
    NgspiceAcResult,
    check_errors,
    NgspiceTable,
)


class _FFIBackend:
    _instance = None
    """FFI backend for ngspice shared library.

    - NEVER raise Python exceptions inside C callback functions (_send_char_handler, etc.)
    - C callbacks cannot propagate Python exceptions and will cause crashes/undefined behavior
    - Always store error states in instance variables and check them after C calls return
    - The ngspice FFI library is NOT thread-safe - use only from single thread
    - Memory management issues exist in ngspice cleanup - avoid calling quit command
    """

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(_FFIBackend, cls).__new__(cls)
        return cls._instance

    class NgComplex(ctypes.Structure):
        _fields_ = [("cx_real", ctypes.c_double), ("cx_imag", ctypes.c_double)]

    class VecValues(ctypes.Structure):
        pass

    class VecValuesAll(ctypes.Structure):
        pass

    class VecInfo(ctypes.Structure):
        pass

    class VecInfoAll(ctypes.Structure):
        pass

    # Define fields after forward declarations
    VecValues._fields_ = [
        ("name", ctypes.c_char_p),
        ("creal", ctypes.c_double),
        ("cimag", ctypes.c_double),
        ("is_scale", ctypes.c_bool),
        ("is_complex", ctypes.c_bool),
    ]

    VecValuesAll._fields_ = [
        ("veccount", ctypes.c_int),
        ("vecindex", ctypes.c_int),
        ("vecsa", ctypes.POINTER(ctypes.POINTER(VecValues))),
    ]

    VecInfo._fields_ = [
        ("number", ctypes.c_int),
        ("vecname", ctypes.c_char_p),
        ("is_real", ctypes.c_bool),
        ("pdvec", ctypes.c_void_p),
        ("pdvecscale", ctypes.c_void_p),
    ]

    VecInfoAll._fields_ = [
        ("name", ctypes.c_char_p),
        ("title", ctypes.c_char_p),
        ("date", ctypes.c_char_p),
        ("type", ctypes.c_char_p),
        ("veccount", ctypes.c_int),
        ("vecs", ctypes.POINTER(ctypes.POINTER(VecInfo))),
    ]

    class VectorInfo(ctypes.Structure):
        pass
    PVectorInfo = ctypes.POINTER(VectorInfo)
    VectorInfo._fields_ = [
        ("v_name", ctypes.c_char_p), ("v_type", ctypes.c_int),
        ("v_flags", ctypes.c_short), ("v_realdata", ctypes.POINTER(ctypes.c_double)),
        ("v_compdata", ctypes.POINTER(NgComplex)), ("v_length", ctypes.c_int),
    ]

    def __init__(self, debug: bool = False):
        self.debug = debug
        # The __init__ method is called every time, but we only initialize once.
        if hasattr(self, '_initialized') and self._initialized:
            return

        self.lib = self.find_library()
        self._setup_library_functions()
        self._output_lines = []
        self._error_message = None
        self._has_fatal_error = False

        # Async simulation state
        self._is_running = False
        self._async_callback = None
        self._async_throttle_interval = 0.1  # Default 100ms throttle
        self._last_callback_time = 0.0
        self._async_data_queue = queue.Queue()
        self._simulation_info = None

        # Keep references to callbacks
        self._send_char_cb = self._SendChar(self._send_char_handler)
        self._send_stat_cb = self._SendStat(self._send_stat_handler)
        self._exit_cb = self._ControlledExit(self._exit_handler)
        self._send_data_cb = self._SendData(self._send_data_handler)
        self._send_init_data_cb = self._SendInitData(self._send_init_data_handler)
        self._bg_thread_running_cb = self._BGThreadRunning(self._bg_thread_running_handler)

        init_result = self.lib.ngSpice_Init(
            self._send_char_cb,
            self._send_stat_cb,
            self._exit_cb,
            self._send_data_cb,
            self._send_init_data_cb,
            self._bg_thread_running_cb,
            None
        )
        if init_result != 0:
            raise NgspiceConfigError(f"Failed to initialize NgSpice FFI library (error code: {init_result}).")
        self._initialized = True

    @staticmethod
    @contextmanager
    def launch(debug=False):
        backend = None
        try:
            backend = _FFIBackend(debug=debug)
            yield backend
        except NgspiceError as e:
            raise e
        finally:
            if backend:
                try:
                    backend.cleanup()
                except:
                    pass  # Ignore cleanup errors to prevent segfaults



    def cleanup(self):
        # Skip calling quit to avoid memory corruption issues in ngspice FFI
        # The shared library will be cleaned up when the process exits
        pass

    def _send_char_handler(self, message: bytes, ident: int, user_data) -> int:
        if message:
            msg_str = message.decode('utf-8', errors='ignore').strip()
            self._output_lines.append(msg_str)
            if self.debug:
                print(f"[ngspice-ffi-out] {msg_str}")

            # Store error information safely (NEVER raise exceptions in C callbacks!)
            # Exceptions in C callbacks cause undefined behavior and crashes
            if msg_str.startswith("stderr Error:"):
                error_text = msg_str[7:]  # Remove "stderr " prefix
                if not self._error_message:  # Keep first error
                    self._error_message = "Error: " + error_text

            # Check for fatal error indicators
            if "cannot recover" in msg_str or "awaits to be reset" in msg_str:
                self._has_fatal_error = True
        return 0

    def _send_data_handler(self, vec_data, vec_count, ident, user_data) -> int:
        """Handle data from background simulations (NEVER raise exceptions!)"""
        try:
            current_time = time.time()

            # Throttle callbacks to prevent overwhelming Python
            if current_time - self._last_callback_time < self._async_throttle_interval:
                return 0

            self._last_callback_time = current_time

            if vec_data and vec_count > 0:
                # Extract data from C structures safely
                data_points = {}
                vec_data_content = vec_data.contents

                for i in range(vec_data_content.veccount):
                    vec_ptr = vec_data_content.vecsa[i]
                    if vec_ptr:
                        vec = vec_ptr.contents
                        name = vec.name.decode('utf-8') if vec.name else f"vec_{i}"

                        if vec.is_complex:
                            value = complex(vec.creal, vec.cimag)
                        else:
                            value = vec.creal

                        data_points[name] = value

                # Calculate progress based on simulation time if available
                progress = 0.0
                if 'time' in data_points and self._sim_tstop:
                    sim_time = data_points['time']
                    progress = min(max(sim_time / self._sim_tstop, 0.0), 1.0)
                    # Ensure progress is monotonic
                    progress = max(progress, self._last_progress)
                    self._last_progress = progress
                else:
                    # Fallback: increment progress based on data points
                    self._data_points_sent += 1
                    progress = min(self._data_points_sent * 0.05, 0.95)
                    progress = max(progress, self._last_progress)
                    self._last_progress = progress

                # Store in queue for safe retrieval
                if data_points:
                    try:
                        self._async_data_queue.put_nowait({
                            'timestamp': current_time,
                            'data': data_points,
                            'index': vec_count,
                            'progress': progress
                        })
                    except queue.Full:
                        # Drop oldest data if queue is full
                        try:
                            self._async_data_queue.get_nowait()
                            self._async_data_queue.put_nowait({
                                'timestamp': current_time,
                                'data': data_points,
                                'index': vec_count,
                                'progress': progress
                            })
                        except queue.Empty:
                            pass

        except Exception:
            # NEVER raise exceptions in C callbacks - just log if debug is on
            if self.debug:
                import traceback
                print(f"[ngspice-ffi] Error in _send_data_handler: {traceback.format_exc()}")

        return 0

    def _send_init_data_handler(self, vec_info, ident, user_data) -> int:
        """Handle initialization data from background simulations (NEVER raise exceptions!)"""
        try:
            if vec_info:
                vec_info_content = vec_info.contents

                simulation_info = {
                    'name': vec_info_content.name.decode('utf-8') if vec_info_content.name else 'unknown',
                    'title': vec_info_content.title.decode('utf-8') if vec_info_content.title else '',
                    'date': vec_info_content.date.decode('utf-8') if vec_info_content.date else '',
                    'type': vec_info_content.type.decode('utf-8') if vec_info_content.type else '',
                    'veccount': vec_info_content.veccount,
                    'vectors': []
                }

                # Extract vector information
                for i in range(vec_info_content.veccount):
                    vec_ptr = vec_info_content.vecs[i]
                    if vec_ptr:
                        vec = vec_ptr.contents
                        simulation_info['vectors'].append({
                            'number': vec.number,
                            'name': vec.vecname.decode('utf-8') if vec.vecname else f'vec_{i}',
                            'is_real': bool(vec.is_real)
                        })

                self._simulation_info = simulation_info

                if self.debug:
                    print(f"[ngspice-ffi] Simulation initialized: {simulation_info['name']} with {simulation_info['veccount']} vectors")

        except Exception:
            # NEVER raise exceptions in C callbacks
            if self.debug:
                import traceback
                print(f"[ngspice-ffi] Error in _send_init_data_handler: {traceback.format_exc()}")

        return 0

    def _bg_thread_running_handler(self, is_not_running, ident, user_data) -> int:
        """Handle background thread status updates (NEVER raise exceptions!)"""
        try:
            self._is_running = not bool(is_not_running)
            if self.debug:
                status = "stopped" if is_not_running else "started"
                print(f"[ngspice-ffi] Background thread {status}")

        except Exception:
            # NEVER raise exceptions in C callbacks
            if self.debug:
                import traceback
                print(f"[ngspice-ffi] Error in _bg_thread_running_handler: {traceback.format_exc()}")

        return 0

    def _send_stat_handler(self, status: bytes, ident: int, user_data) -> int:
        if self.debug and status:
            print(f"[ngspice-ffi-stat] {status.decode('utf-8', errors='ignore').strip()}")
        return 0

    def _exit_handler(self, status: int, unload: bool, quit_upon_exit: bool, ident: int, user_data) -> int:
        if status != 0 and self.debug:
            print(f"[ngspice-ffi-exit] code {status}")
        return status

    def command(self, command: str) -> str:
        self._output_lines.clear()
        self._error_message = None
        self._has_fatal_error = False
        ret = self.lib.ngSpice_Command(command.encode('utf-8'))

        # Check for errors stored by callbacks (safe to raise exceptions here)
        if self._error_message:
            if self._has_fatal_error:
                raise NgspiceFatalError(self._error_message)
            else:
                raise NgspiceError(self._error_message)

        output = "\n".join(self._output_lines)
        check_errors(output)
        return output

    def reset(self):
        """Reset the ngspice state to clear any previous circuit and analysis results."""
        try:
            # Try to remove any existing circuit
            self.command("remcirc")
        except:
            # Ignore errors if no circuit is loaded
            pass

        try:
            # Destroy all plots and data
            self.command("destroy all")
        except:
            # Ignore errors if no data exists
            pass

        # Clear internal state
        self._output_lines.clear()
        self._error_message = None
        self._has_fatal_error = False

    def load_netlist(self, netlist: str, no_auto_gnd: bool = True):
        # FFI backend loads circuit from an array of strings
        if no_auto_gnd:
            self.command("set no_auto_gnd")

        # Clear error state before circuit loading
        self._error_message = None
        self._has_fatal_error = False

        circuit_lines = [line.encode('utf-8') for line in netlist.split('\n') if line.strip()]
        c_circuit = (ctypes.c_char_p * len(circuit_lines))()
        c_circuit[:] = circuit_lines

        circ_result = self.lib.ngSpice_Circ(c_circuit)

        # Check for errors stored by callbacks first (safe to raise exceptions here)
        if self._error_message:
            if self._has_fatal_error:
                raise NgspiceFatalError(self._error_message)
            else:
                raise NgspiceError(self._error_message)

        # Fallback to traditional error checking for non-callback errors
        output = "\n".join(self._output_lines)
        check_errors(output)

        if circ_result != 0:
            raise NgspiceFatalError(f"Failed to load circuit into FFI backend. Full output:\n{output}")

    def op(self) -> Iterator[NgspiceValue]:
        self.command("op")
        all_vectors = self._get_all_vectors()

        for vec_name in all_vectors:
            vec_info = self._get_vector_info(vec_name)
            if not vec_info or vec_info.v_length == 0:
                continue

            value = vec_info.v_realdata[0]

            # Match naming conventions from subprocess backend
            if vec_name.startswith('@') and '[' in vec_name:
                match = re.match(r"@([a-zA-Z]\.)?([0-9a-zA-Z_.#]+)\[([0-9a-zA-Z_]+)\]", vec_name)
                if match:
                    yield NgspiceValue('current', match.group(2), match.group(3), value)
            elif vec_name.endswith('#branch'):
                yield NgspiceValue('current', vec_name.replace('#branch', ''), 'branch', value)
            else:
                yield NgspiceValue('voltage', vec_name, None, value)

    def tran(self, *args) -> NgspiceTransientResult:
        self.command(f"tran {' '.join(args)}")
        result = NgspiceTransientResult()
        table = NgspiceTable("transient_analysis")

        all_vectors = self._get_all_vectors()

        num_points = 0

        # Get all vector data and structure it by column, filtering out zero-length vectors
        vector_data_map = {}
        valid_headers = []
        for vec_name in all_vectors:
            vec_info = self._get_vector_info(vec_name)
            if vec_info and vec_info.v_length > 0:
                num_points = max(num_points, vec_info.v_length)
                data_list = [vec_info.v_realdata[i] for i in range(vec_info.v_length)]
                vector_data_map[vec_name] = data_list
                valid_headers.append(vec_name)

        table.headers = valid_headers

        # Transpose columns into rows
        for i in range(num_points):
            row = [vector_data_map[h][i] for h in table.headers]
            table.data.append(row)

        result.add_table(table)
        return result

    def ac(self, *args, **kwargs) -> 'NgspiceAcResult':
        self.command(f"ac {' '.join(args)}")
        result = NgspiceAcResult()

        all_vectors = self._get_all_vectors()

        num_points = 0
        vector_data_map = {}
        valid_headers = []

        for vec_name in all_vectors:
            vec_info = self._get_vector_info(vec_name)
            if vec_info and vec_info.v_length > 0:
                num_points = max(num_points, vec_info.v_length)
                if vec_info.v_compdata:
                    data_list = [complex(vec_info.v_compdata[i].cx_real, vec_info.v_compdata[i].cx_imag) for i in range(vec_info.v_length)]
                else:
                    data_list = [vec_info.v_realdata[i] for i in range(vec_info.v_length)]
                vector_data_map[vec_name] = data_list
                valid_headers.append(vec_name)

        if 'frequency' in vector_data_map:
            result.freq = tuple(vector_data_map['frequency'])

        for name, value in vector_data_map.items():
            if name != 'frequency':
                result._categorize_signal(name, value)

        return result

    def tran_async(self, *args, throttle_interval: float = 0.1) -> 'queue.Queue':
        self._async_throttle_interval = throttle_interval
        self._last_callback_time = 0.0
        self._data_points_sent = 0

        # Store simulation parameters for progress calculation
        self._sim_tstop = None
        self._last_progress = 0.0
        if len(args) >= 2:
            # Parse tstop from second argument (tstep, tstop)
            try:
                tstop_str = str(args[1])
                # Convert units (u = micro, n = nano, m = milli, etc.)
                if tstop_str.endswith('u'):
                    self._sim_tstop = float(tstop_str[:-1]) * 1e-6
                elif tstop_str.endswith('n'):
                    self._sim_tstop = float(tstop_str[:-1]) * 1e-9
                elif tstop_str.endswith('m'):
                    self._sim_tstop = float(tstop_str[:-1]) * 1e-3
                else:
                    self._sim_tstop = float(tstop_str)
            except (ValueError, IndexError):
                self._sim_tstop = None

        # Clear any existing data
        while not self._async_data_queue.empty():
            try:
                self._async_data_queue.get_nowait()
            except queue.Empty:
                break

        # Start background simulation using bg_tran
        cmd_args = ' '.join(str(arg) for arg in args)
        self.command(f"bg_tran {cmd_args}")

        # Wait for simulation to start or complete (handles fast simulations)
        timeout = time.time() + 5.0  # 5 second timeout
        simulation_started = False

        # Use race condition approach instead of polling
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:

            def check_running_status():
                """Check if simulation is running"""
                return self._is_running

            def check_queue_activity():
                """Check if data queue has activity (fast simulations)"""
                return not self._async_data_queue.empty()

            while time.time() < timeout:
                # Race between status check and queue activity
                status_future = executor.submit(check_running_status)
                queue_future = executor.submit(check_queue_activity)

                try:
                    done_futures = concurrent.futures.as_completed(
                        [status_future, queue_future],
                        timeout=0.05
                    )

                    for future in done_futures:
                        if future == status_future and future.result():
                            simulation_started = True
                            break
                        elif future == queue_future and future.result():
                            simulation_started = True
                            break

                    if simulation_started:
                        break

                except concurrent.futures.TimeoutError:
                    # Continue checking until main timeout
                    pass

                # Clean up futures
                if not status_future.done():
                    status_future.cancel()
                if not queue_future.done():
                    queue_future.cancel()

        if not simulation_started:
            raise NgspiceError("Background simulation failed to start")

        # Start a thread to handle data retrieval fallback for complex simulations
        # Some complex models (like SKY130) don't trigger data callbacks during bg_tran
        import threading
        def data_fallback_handler():
            """Handle data retrieval when callbacks don't work (e.g.,Complex models like SKY130 with savecurrents option)"""
            # Wait for simulation to complete using race condition approach
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as fallback_executor:

                def check_completion_status():
                    """Check if simulation has completed"""
                    return not self._is_running

                while True:
                    completion_future = fallback_executor.submit(check_completion_status)
                    try:
                        if completion_future.result(timeout=0.05):
                            break
                    except concurrent.futures.TimeoutError:
                        pass
                    finally:
                        if not completion_future.done():
                            completion_future.cancel()

            # Small delay to ensure simulation is fully complete
            time.sleep(0.1)

            # If no data received via callbacks but simulation completed, manually retrieve data
            if self._async_data_queue.empty():
                try:
                    # Get current vectors from ngspice
                    vector_names = self._get_all_vectors()
                    if vector_names and 'time' in vector_names:
                        # Extract actual vector data using _get_vector_info
                        vector_data_map = {}
                        num_points = 0

                        for vec_name in vector_names:
                            vec_info = self._get_vector_info(vec_name)
                            if vec_info and vec_info.v_length > 0:
                                num_points = max(num_points, vec_info.v_length)
                                data_list = [vec_info.v_realdata[i] for i in range(vec_info.v_length)]
                                vector_data_map[vec_name] = data_list

                        if num_points > 0 and 'time' in vector_data_map:
                            # Sample every 10th point to avoid overwhelming the queue
                            sample_indices = range(0, num_points, max(1, num_points // 100))

                            for i in sample_indices:
                                data_points = {}
                                for name, values in vector_data_map.items():
                                    if i < len(values):
                                        data_points[name] = values[i]

                                if data_points:
                                    self._async_data_queue.put_nowait({
                                        'timestamp': time.time(),
                                        'data': data_points,
                                        'index': i
                                    })

                            if self.debug:
                                print(f"[ngspice-ffi] Fallback retrieved {len(sample_indices)} data points from {num_points} total points")

                except Exception as e:
                    # Fallback failed, but don't crash - log errors for diagnostics
                    import logging
                    logging.error("Exception in data_fallback_handler: %s", e)
                    if self.debug:
                        import traceback
                        logging.debug("Fallback traceback: %s", traceback.format_exc())

        fallback_thread = threading.Thread(target=data_fallback_handler, daemon=True)
        fallback_thread.start()

        # Return the queue for direct access
        return self._async_data_queue

    def op_async(self, callback: Optional[Callable] = None) -> Generator:
       self._async_callback = callback
       while not self._async_data_queue.empty():
           try:
               self._async_data_queue.get_nowait()
           except queue.Empty:
               break

       # Start background simulation - set up analysis first, then run
       self.command("op")
       self.command("bg_run")

       # Wait for simulation to start using race condition approach
       timeout = time.time() + 5.0

       import concurrent.futures
       startup_detected = False
       with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:

           def check_op_startup():
               """Check if OP analysis has started"""
               return self._is_running

           while time.time() < timeout:
               startup_future = executor.submit(check_op_startup)
               try:
                   if startup_future.result(timeout=0.05):
                       startup_detected = True
                       break
               except concurrent.futures.TimeoutError:
                   pass
               finally:
                   if not startup_future.done():
                       startup_future.cancel()

       if not startup_detected:
           raise NgspiceError("Background operating point analysis failed to start")

       # Stream data as it becomes available
       while self._is_running:
           try:
               data_point = self._async_data_queue.get(timeout=0.1)
               if callback:
                   callback(data_point)

               yield data_point

           except queue.Empty:
               # Check if simulation is still running
               if hasattr(self.lib, 'ngSpice_running'):
                   if not self.lib.ngSpice_running():
                       self._is_running = False
                       break

       # Drain any remaining data
       while not self._async_data_queue.empty():
           try:
               data_point = self._async_data_queue.get_nowait()
               if callback:
                   callback(data_point)
               yield data_point
           except queue.Empty:
               break

    def is_running(self) -> bool:
        return self._is_running

    def get_async_data_queue(self) -> 'queue.Queue':
        """Get direct access to the async data queue"""
        return self._async_data_queue

    def stop_simulation(self):
        if self._is_running:
            self.command("bg_halt")
            self._is_running = False
            # Wait for simulation to stop using race condition approach
            timeout = time.time() + 2.0

            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:

                def check_stop_status():
                    """Check if simulation has stopped"""
                    return not self._is_running

                # Race condition approach: check status with timeout
                while time.time() < timeout:
                    stop_future = executor.submit(check_stop_status)
                    try:
                        if stop_future.result(timeout=0.05):
                            return True  # Successfully stopped
                    except concurrent.futures.TimeoutError:
                        pass
                    finally:
                        if not stop_future.done():
                            stop_future.cancel()

            # If we reach here, stopping timed out but we tried
            return not self._is_running
        else:
            # Already stopped
            return True

    def safe_halt_simulation(self, max_attempts: int = 3, wait_time: float = 0.2) -> bool:
        """Halt async simulation safely."""
        if not self._is_running:
            return True

        for attempt in range(max_attempts):
            self.command("bg_halt")
            self._is_running = False

            # Check if simulation has stopped
            time.sleep(wait_time)
            if not self._is_running:
                return True

        # If we reach here, stopping timed out but we tried
        return not self._is_running

    def halt_simulation(self, timeout: float = 2.0) -> bool:
        """Halt async simulation (alias for safe_halt_simulation for API compatibility)."""
        result = self.safe_halt_simulation(max_attempts=int(timeout / 0.2), wait_time=0.2)
        return result

    def safe_resume_simulation(self, max_attempts: int = 3, wait_time: float = 2.0) -> bool:
        """Resume a halted simulation safely."""
        if self._is_running:
            return True  # Already running

        for attempt in range(max_attempts):
            # Send bg_resume command
            result = self.command("bg_resume")

            # Check if ngspice is actually running using the library function
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:

                def check_resume_status():
                    """Check if simulation has resumed using ngspice library"""
                    try:
                        is_running = self.lib.ngSpice_running()
                        if is_running:
                            self._is_running = True  # Update our state
                        return is_running
                    except:
                        return False

                # Wait for resume to complete
                start_time = time.time()
                while time.time() - start_time < wait_time:
                    resume_future = executor.submit(check_resume_status)
                    try:
                        if resume_future.result(timeout=0.05):
                            return True
                    except concurrent.futures.TimeoutError:
                        pass
                    finally:
                        if not resume_future.done():
                            resume_future.cancel()

            # Wait before retry (except on last attempt)
            if attempt < max_attempts - 1:
                time.sleep(wait_time / 2)

        return False  # Resume failed or timed out after all attempts

    def resume_simulation(self, timeout=2.0):
        if self._is_running:
            return True  # Already running

        # Send bg_resume command
        result = self.command("bg_resume")

        # Check if ngspice is actually running using the library function
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:

            def check_resume_status():
                """Check if simulation has resumed using ngspice library"""
                try:
                    is_running = self.lib.ngSpice_running()
                    if is_running:
                        self._is_running = True  # Update our state
                    return is_running
                except:
                    return False

            # Wait for resume to complete
            start_time = time.time()
            while time.time() - start_time < timeout:
                resume_future = executor.submit(check_resume_status)
                try:
                    if resume_future.result(timeout=0.05):
                        return True
                except concurrent.futures.TimeoutError:
                    pass
                finally:
                    if not resume_future.done():
                        resume_future.cancel()

        return False  # Resume failed or timed out

    def _get_all_vectors(self) -> List[str]:
        plot_name = self.lib.ngSpice_CurPlot()
        if not plot_name:
            return []

        vecs_ptr = self.lib.ngSpice_AllVecs(plot_name)
        vectors = []
        i = 0
        while vecs_ptr and vecs_ptr[i]:
            vectors.append(vecs_ptr[i].decode('utf-8'))
            i += 1
        return vectors

    def _get_vector_info(self, vector_name: str) -> Optional[VectorInfo]:
        vec_info_ptr = self.lib.ngGet_Vec_Info(vector_name.encode('utf-8'))
        return vec_info_ptr.contents if vec_info_ptr else None

    @staticmethod
    def find_library() -> ctypes.CDLL:
        if sys.platform == 'win32':
            return ctypes.CDLL('libngspice-0.dll')
        elif sys.platform == 'darwin':
            return ctypes.CDLL('libngspice.0.dylib')
        else:
            return ctypes.CDLL('libngspice.so.0')

    def _setup_library_functions(self):
        # Define callback function prototypes
        self._SendChar = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
        self._SendStat = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
        self._ControlledExit = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)
        self._SendData = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(self.VecValuesAll), ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
        self._SendInitData = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(self.VecInfoAll), ctypes.c_int, ctypes.c_void_p)
        self._BGThreadRunning = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)

        # Core functions
        self.lib.ngSpice_Init.restype = ctypes.c_int
        self.lib.ngSpice_Init.argtypes = [self._SendChar, self._SendStat, self._ControlledExit, self._SendData, self._SendInitData, self._BGThreadRunning, ctypes.c_void_p]

        self.lib.ngSpice_Command.restype = ctypes.c_int
        self.lib.ngSpice_Command.argtypes = [ctypes.c_char_p]

        self.lib.ngSpice_Circ.restype = ctypes.c_int
        self.lib.ngSpice_Circ.argtypes = [ctypes.POINTER(ctypes.c_char_p)]

        self.lib.ngGet_Vec_Info.restype = self.PVectorInfo
        self.lib.ngGet_Vec_Info.argtypes = [ctypes.c_char_p]

        self.lib.ngSpice_CurPlot.restype = ctypes.c_char_p
        self.lib.ngSpice_AllVecs.restype = ctypes.POINTER(ctypes.c_char_p)
        self.lib.ngSpice_AllVecs.argtypes = [ctypes.c_char_p]

        # Background simulation functions
        try:
            self.lib.ngSpice_running.restype = ctypes.c_bool
            self.lib.ngSpice_running.argtypes = []
        except AttributeError:
            # Some ngspice versions might not have this function
            pass
