# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import ctypes

import re
import sys
import queue
import time
import threading
import concurrent.futures
import traceback
import logging
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
    SignalKind,
    SignalArray,
    NgspiceBase,
)

from ..core import R


_DEBUG_PREFIX = "[ngspice-ffi]"


def _debug(message: str) -> None:
    print(f"{_DEBUG_PREFIX} {message}")


class NgspiceFFI(NgspiceBase):
    _instance = None
    """FFI backend for ngspice shared library.

    - NEVER raise Python exceptions inside C callback functions (_send_char_handler, etc.)
    - C callbacks cannot propagate Python exceptions and will cause crashes/undefined behavior
    - Always store error states in instance variables and check them after C calls return
    - The ngspice FFI library is NOT thread-safe - use only from single thread
    """

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(NgspiceFFI, cls).__new__(cls)
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
        ("v_name", ctypes.c_char_p),
        ("v_type", ctypes.c_int),
        ("v_flags", ctypes.c_short),
        ("v_realdata", ctypes.POINTER(ctypes.c_double)),
        ("v_compdata", ctypes.POINTER(NgComplex)),
        ("v_length", ctypes.c_int),
    ]

    def __init__(self, debug: bool = False):
        self.debug = debug
        # The __init__ method is called every time, but we only initialize once.
        if hasattr(self, "_initialized") and self._initialized:
            return

        self.lib = self.find_library()
        self._setup_library_functions()
        self._output_lines = []
        self._error_message = None
        self._has_fatal_error = False

        # Async simulation state
        self._is_running = False
        self._async_callback = None
        self._async_data_queue = queue.Queue()
        self._buffer_enabled = True
        self._buffer_size = 10  # Number of data points to buffer before sending
        self._data_buffer = []  # Buffer to collect data points
        self._last_buffer_flush_time = 0.0
        self._simulation_start_time = 0.0
        self._simulation_info = None
        self._last_progress = 0.0
        self._sim_tstop = 0.0
        self._normal_callbacks_received = 0  # Initialize counter for normal callbacks

        # Keep references to callbacks
        self._send_char_cb = self._SendChar(self._send_char_handler)
        self._send_stat_cb = self._SendStat(self._send_stat_handler)
        self._exit_cb = self._ControlledExit(self._exit_handler)
        self._send_data_cb = self._SendData(self._send_data_handler)
        self._send_init_data_cb = self._SendInitData(self._send_init_data_handler)
        self._bg_thread_running_cb = self._BGThreadRunning(
            self._bg_thread_running_handler
        )

        init_result = self.lib.ngSpice_Init(
            self._send_char_cb,
            self._send_stat_cb,
            self._exit_cb,
            self._send_data_cb,
            self._send_init_data_cb,
            self._bg_thread_running_cb,
            None,
        )
        if init_result != 0:
            raise NgspiceConfigError(
                f"Failed to initialize NgSpice FFI library (error code: {init_result})."
            )
        self._initialized = True

    @classmethod
    @contextmanager
    def launch(cls, debug: bool):
        backend = None
        try:
            backend = cls(debug=debug)
            yield backend
        except NgspiceError as e:
            raise e
        finally:
            if backend:
                backend.cleanup()

    def cleanup(self):
        """Clean up async simulation resources."""
        if hasattr(self, '_is_running') and self._is_running:
            timeout = 2.0
            start_time = time.time()
            while self._is_running and (time.time() - start_time) < timeout:
                time.sleep(0.1)

        if hasattr(self, '_fallback_thread') and self._fallback_thread and self._fallback_thread.is_alive():
            self._fallback_thread.join(timeout=1.0)

        if hasattr(self, '_async_data_queue'):
            while not self._async_data_queue.empty():
                self._async_data_queue.get_nowait()

    def _send_char_handler(self, message: bytes, ident: int, user_data) -> int:
        if message:
            msg_str = message.decode("utf-8", errors="ignore").strip()
            self._output_lines.append(msg_str)
            if self.debug:
                _debug(f"Output: {msg_str}")

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
        try:
            current_time = time.time()
            self._normal_callbacks_received += 1
            if self.debug:
                _debug(
                    f"Normal callback received: count={self._normal_callbacks_received}, time={current_time}"
                )

            if self._buffer_enabled:
                data_point = self._process_data_point(vec_data, vec_count, current_time)
                if data_point:
                    self._data_buffer.append(data_point)

                    should_flush = (
                        len(self._data_buffer) >= self._buffer_size or
                        current_time - self._last_buffer_flush_time > 0.5
                    )

                    if should_flush:
                        self._flush_buffer()
                        self._last_buffer_flush_time = current_time
                        if self.debug:
                            self._debug_flush_count += 1
                            self._debug_points_flushed += len(self._data_buffer)
            else:
                data_point = self._process_data_point(vec_data, vec_count, current_time)
                if data_point:
                    self._send_data_point(data_point)

        except Exception:
            if self.debug:
                _debug(
                    f"Error in _send_data_handler: {traceback.format_exc()}"
                )

        return 0

    def _process_data_point(self, vec_data, vec_count, current_time):
        """Process raw vector data into a structured data point."""
        if vec_data and vec_count > 0:
            data_points = {}
            vec_data_content = vec_data.contents

            for i in range(vec_data_content.veccount):
                vec_ptr = vec_data_content.vecsa[i]
                if vec_ptr:
                    vec = vec_ptr.contents
                    name = vec.name.decode("utf-8") if vec.name else f"vec_{i}"

                    if vec.is_complex:
                        value = complex(vec.creal, vec.cimag)
                    else:
                        value = vec.creal

                    data_points[name] = value

            progress = 0.0
            if "time" in data_points and self._sim_tstop:
                sim_time = data_points["time"]
                progress = sim_time / self._sim_tstop
                self._last_progress = progress

            signal_kinds = {}
            for vec_name in data_points:
                if vec_name != "time":
                    kind = self._vector_kind_cache.get(vec_name)
                    if kind is None:
                        vec_info = self._get_vector_info(vec_name)
                        if vec_info:
                            kind = SignalKind.from_vtype(int(vec_info.v_type))
                            self._vector_kind_cache[vec_name] = kind
                    if kind:
                        signal_kinds[vec_name] = kind

            return {
                "timestamp": current_time,
                "data": data_points,
                "signal_kinds": signal_kinds,
                "index": vec_count,
                "progress": progress,
            }
        return None

    def _send_data_point(self, data_point):
        """Send a single data point to the async queue."""
        self._async_data_queue.put_nowait(data_point)


    def _flush_buffer(self):
        """Flush buffered data points to the async queue."""
        if not self._data_buffer:
            return

        if self.debug:
            _debug(f"Flushing buffer with {len(self._data_buffer)} data points")

        for data_point in self._data_buffer:
            self._send_data_point(data_point)

        if self.debug:
            self._debug_points_flushed += len(self._data_buffer)

        self._data_buffer.clear()

        return 0

    def _send_init_data_handler(self, vec_info, ident, user_data) -> int:
        try:
            if vec_info:
                vec_info_content = vec_info.contents

                simulation_info = {
                    "name": vec_info_content.name.decode("utf-8")
                    if vec_info_content.name
                    else "unknown",
                    "title": vec_info_content.title.decode("utf-8")
                    if vec_info_content.title
                    else "",
                    "date": vec_info_content.date.decode("utf-8")
                    if vec_info_content.date
                    else "",
                    "type": vec_info_content.type.decode("utf-8")
                    if vec_info_content.type
                    else "",
                    "veccount": vec_info_content.veccount,
                    "vectors": [],
                }

                # Extract vector information
                for i in range(vec_info_content.veccount):
                    vec_ptr = vec_info_content.vecs[i]
                    if vec_ptr:
                        vec = vec_ptr.contents
                        vector_info = {
                            "number": vec.number,
                            "name": vec.vecname.decode("utf-8")
                            if vec.vecname
                            else f"vec_{i}",
                            "is_real": bool(vec.is_real),
                        }
                        simulation_info["vectors"].append(vector_info)

                self._simulation_info = simulation_info

                if self.debug:
                    _debug(
                        f"Simulation initialized: {simulation_info['name']} with {simulation_info['veccount']} vectors"
                    )

        except Exception:
            # NEVER raise exceptions in C callbacks
            if self.debug:
                _debug(
                    f"Error in _send_init_data_handler: {traceback.format_exc()}"
                )

        return 0

    def _bg_thread_running_handler(self, is_not_running, ident, user_data) -> int:
        try:
            self._is_running = not bool(is_not_running)
            if self.debug:
                status = "stopped" if is_not_running else "started"
                _debug(f"Background thread {status}")

            if is_not_running and self._buffer_enabled:
                self._flush_buffer()
                if self.debug:
                    self._debug_flush_count += 1

        except Exception:
            if self.debug:
                _debug(
                    f"Error in _bg_thread_running_handler: {traceback.format_exc()}"
                )

        return 0

    def _send_stat_handler(self, status: bytes, ident: int, user_data) -> int:
        if self.debug and status:
            _debug(
                f"Status: {status.decode('utf-8', errors='ignore').strip()}"
            )
        return 0

    def _exit_handler(
        self, status: int, unload: bool, quit_upon_exit: bool, ident: int, user_data
    ) -> int:
        if status != 0 and self.debug:
            _debug(f"Exit code {status}")
        return status

    def command(self, command: str) -> str:
        self._output_lines.clear()
        self._error_message = None
        self._has_fatal_error = False
        ret = self.lib.ngSpice_Command(command.encode("utf-8"))

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
        self.command("remcirc")
        self.command("destroy all")

        self._output_lines.clear()
        self._error_message = None
        self._has_fatal_error = False

    def load_netlist(self, netlist: str, no_auto_gnd: bool = True):
        if no_auto_gnd:
            self.command("set no_auto_gnd")

        self._error_message = None
        self._has_fatal_error = False

        circuit_lines = [
            line.encode("utf-8") for line in netlist.split("\n") if line.strip()
        ]
        c_circuit = (ctypes.c_char_p * len(circuit_lines))()
        c_circuit[:] = circuit_lines

        circ_result = self.lib.ngSpice_Circ(c_circuit)

        # Check for errors stored by callbacks first (safe to raise exceptions here)
        if self._error_message:
            if self._has_fatal_error:
                raise NgspiceFatalError(self._error_message)
            else:
                raise NgspiceError(self._error_message)

        output = "\n".join(self._output_lines)
        check_errors(output)

        if circ_result != 0:
            raise NgspiceFatalError(
                f"Failed to load circuit into FFI backend. Full output:\n{output}"
            )

    def op(self) -> Iterator[NgspiceValue]:
        self.command("op")
        all_vectors = self._get_all_vectors()

        for vec_name in all_vectors:
            vec_info = self._get_vector_info(vec_name)
            if not vec_info or vec_info.v_length == 0:
                continue

            value = vec_info.v_realdata[0]

            # Match naming conventions from subprocess backend
            if vec_name.startswith("@") and "[" in vec_name:
                match = re.match(
                    r"@([a-zA-Z]\.)?([0-9a-zA-Z_.#]+)\[([0-9a-zA-Z_]+)\]", vec_name
                )
                if match:
                    yield NgspiceValue("current", match.group(2), match.group(3), value)
            elif vec_name.endswith("#branch"):
                yield NgspiceValue(
                    "current", vec_name.replace("#branch", ""), "branch", value
                )
            else:
                yield NgspiceValue("voltage", vec_name, None, value)

    def tran(self, *args) -> NgspiceTransientResult:
        self.command(f"tran {' '.join(args)}")
        result = NgspiceTransientResult()

        all_vectors = self._get_all_vectors()

        for vec_name in all_vectors:
            vec_info = self._get_vector_info(vec_name)
            if vec_info and vec_info.v_length > 0:
                data_list = [vec_info.v_realdata[i] for i in range(vec_info.v_length)]

                kind = SignalKind.from_vtype(int(vec_info.v_type))

                result.signals[vec_name] = SignalArray(kind=kind, values=data_list)

                if vec_name.lower() == "time":
                    result.time = data_list

        return result

    def ac(self, *args, **kwargs) -> "NgspiceAcResult":
        self.command(f"ac {' '.join(args)}")
        result = NgspiceAcResult()

        all_vectors = self._get_all_vectors()

        for vec_name in all_vectors:
            vec_info = self._get_vector_info(vec_name)
            if vec_info and vec_info.v_length > 0:
                if vec_info.v_compdata:
                    data_list = [
                        complex(
                            vec_info.v_compdata[i].cx_real,
                            vec_info.v_compdata[i].cx_imag,
                        )
                        for i in range(vec_info.v_length)
                    ]
                else:
                    data_list = [
                        vec_info.v_realdata[i] for i in range(vec_info.v_length)
                    ]

                kind = SignalKind.from_vtype(int(vec_info.v_type))

                result.signals[vec_name] = SignalArray(kind=kind, values=data_list)

                if vec_name.lower() in ("frequency", "freq"):
                    result.freq = data_list

        return result

    def _setup_async_parameters(self, buffer_size: int = 10, disable_buffering: bool = True):
        self._buffer_size = buffer_size
        self._buffer_enabled = not disable_buffering
        self._data_buffer = []
        self._last_buffer_flush_time = time.time()
        self._sim_tstop = None
        self._last_progress = 0.0
        self._fallback_executed = False
        self._normal_callbacks_received = 0
        self._simulation_start_time = time.time()
        # Debug counters to observe async behavior; reset per run.
        self._debug_flush_count = 0
        self._debug_points_flushed = 0
        # Cache vector kinds to avoid repeated ngspice queries per sample.
        self._vector_kind_cache: dict[str, SignalKind] = {}

    def _parse_tstop_parameter(self, tstop):
        if tstop is not None:
            self._sim_tstop = float(R(str(tstop)))

    def _clear_async_queue(self):
        while not self._async_data_queue.empty():
            self._async_data_queue.get_nowait()

    def _build_tran_command(self, tstep, tstop, extra_args):
        cmd_args_list = [str(tstep)]
        if tstop is not None:
            cmd_args_list.append(str(tstop))
        if extra_args:
            cmd_args_list += [str(a) for a in extra_args]
        return " ".join(cmd_args_list)

    def tran_async(
        self, tstep, tstop=None, *extra_args, buffer_size: int = 10, disable_buffering: bool = True, fallback_sampling_ratio: int = 100
    ) -> "queue.Queue[dict]":
        self._setup_async_parameters(buffer_size, disable_buffering)
        self._fallback_sampling_ratio = fallback_sampling_ratio
        self._parse_tstop_parameter(tstop)
        self._clear_async_queue()

        cmd_args = self._build_tran_command(tstep, tstop, extra_args)
        self.command(f"bg_tran {cmd_args}")

        simulation_started = self._wait_for_simulation_start(timeout=10.0)
        if not simulation_started:
            raise NgspiceError("Background simulation failed to start")

        # Some complex models (like SKY130) don't trigger data callbacks during bg_tran
        self._fallback_thread = threading.Thread(
            target=self._data_fallback_handler, daemon=True
        )
        self._fallback_thread.start()
        if self.debug:
            _debug("Fallback thread started")

        return self._async_data_queue

    def _data_fallback_handler(self):
        """Handle data retrieval when callbacks don't work (e.g.,Complex models like SKY130 with savecurrents option)"""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as fallback_executor:

            def check_completion_status():
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

        if self._normal_callbacks_received > 0:
            if self.debug:
                _debug(
                    f"Fallback handler skipped (normal callbacks received: {self._normal_callbacks_received})"
                )
            return

        self._fallback_executed = True
        if self.debug:
            _debug("Fallback handler executing (no normal callbacks received)")

            try:
                vector_names = self._get_all_vectors()
                if vector_names and "time" in vector_names:
                    vector_data_map = {}
                    num_points = 0

                    for vec_name in vector_names:
                        vec_info = self._get_vector_info(vec_name)
                        if vec_info and vec_info.v_length > 0:
                            num_points = max(num_points, vec_info.v_length)
                            data_list = [
                                vec_info.v_realdata[i] for i in range(vec_info.v_length)
                            ]
                            vector_data_map[vec_name] = data_list

                    if num_points > 0 and "time" in vector_data_map:
                        sample_indices = range(num_points)

                        sample_list = list(sample_indices)
                        sample_count = len(sample_list) if sample_list else 1

                        for pos, i in enumerate(sample_list):
                            data_points = {}
                            for name, values in vector_data_map.items():
                                if i < len(values):
                                    data_points[name] = values[i]

                            if not data_points:
                                continue

                            progress = None
                            if "time" in vector_data_map and self._sim_tstop:
                                sim_time = vector_data_map["time"][i]
                                progress = sim_time / self._sim_tstop

                            if progress is not None:
                                self._last_progress = progress

                            self._async_data_queue.put_nowait(
                                {
                                    "timestamp": time.time(),
                                    "data": data_points,
                                    "index": i,
                                    "progress": progress,
                                }
                            )

                        if self.debug:
                            _debug(
                                f"Fallback retrieved {len(sample_indices)} data points from {num_points} total points"
                            )

            except (OSError, RuntimeError, AttributeError) as e:
                logging.error("Exception in data_fallback_handler: %s", e)
                if self.debug:
                    logging.debug("Fallback traceback: %s", traceback.format_exc())
        else:
            if self.debug:
                _debug(
                    f"Fallback handler skipped (normal callbacks received: {self._normal_callbacks_received})"
                )

            def check_completion_status():
                return not self._is_running

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as completion_executor:
                while True:
                    completion_future = completion_executor.submit(check_completion_status)
                    try:
                        if completion_future.result(timeout=0.05):
                            break
                    except concurrent.futures.TimeoutError:
                        pass
                    finally:
                        if not completion_future.done():
                            completion_future.cancel()

        if self._async_data_queue.empty():
            try:
                vector_names = self._get_all_vectors()
                if vector_names and "time" in vector_names:
                    vector_data_map = {}
                    num_points = 0

                    for vec_name in vector_names:
                        vec_info = self._get_vector_info(vec_name)
                        if vec_info and vec_info.v_length > 0:
                            num_points = max(num_points, vec_info.v_length)
                            data_list = [
                                vec_info.v_realdata[i] for i in range(vec_info.v_length)
                            ]
                            vector_data_map[vec_name] = data_list

                    if num_points > 0 and "time" in vector_data_map:
                        # Sample every 10th point to avoid overwhelming the queue
                        sample_indices = range(0, num_points, max(1, num_points // 100))

                        # Build a list of sample indices so we can compute ordinal progress
                        sample_list = list(sample_indices)
                        sample_count = len(sample_list) if sample_list else 1

                        for pos, i in enumerate(sample_list):
                            data_points = {}
                            for name, values in vector_data_map.items():
                                if i < len(values):
                                    data_points[name] = values[i]

                            if not data_points:
                                continue

                            progress = None
                            if "time" in vector_data_map and self._sim_tstop:
                                sim_time = vector_data_map["time"][i]
                                progress = sim_time / self._sim_tstop

                            if progress is not None:
                                self._last_progress = progress

                            self._async_data_queue.put_nowait(
                                {
                                    "timestamp": time.time(),
                                    "data": data_points,
                                    "index": i,
                                    "progress": progress,
                                }
                            )

                        if self.debug:
                            _debug(
                                f"Fallback retrieved {len(sample_indices)} data points from {num_points} total points"
                            )

            except (OSError, RuntimeError, AttributeError) as e:
                logging.error("Exception in data_fallback_handler: %s", e)
                if self.debug:
                    logging.debug("Fallback traceback: %s", traceback.format_exc())
            except Exception as e:
                logging.error("Unexpected exception in data_fallback_handler: %s", e)
                if self.debug:
                    logging.debug("Fallback traceback: %s", traceback.format_exc())
                raise

    def _wait_for_simulation_start(self, timeout: float = 10.0) -> bool:
        timeout_time = time.time() + timeout
        simulation_started = False

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:

            def check_running_status():
                return self._is_running

            def check_queue_activity():
                return not self._async_data_queue.empty()

            while time.time() < timeout_time:
                # Race between status check and queue activity
                status_future = executor.submit(check_running_status)
                queue_future = executor.submit(check_queue_activity)

                try:
                    done_futures = concurrent.futures.as_completed(
                        [status_future, queue_future], timeout=0.05
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
                    pass

                # Clean up futures
                if not status_future.done():
                    status_future.cancel()
                if not queue_future.done():
                    queue_future.cancel()

        return simulation_started

    def op_async(
        self, callback: Optional[Callable[[dict], None]] = None
    ) -> Generator[dict, None, None]:
        self._async_callback = callback
        while not self._async_data_queue.empty():
            self._async_data_queue.get_nowait()

        # Start background simulation - set up analysis first, then run
        self.command("op")
        self.command("bg_run")

        timeout = time.time() + 5.0

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

        while self._is_running:
            try:
                data_point = self._async_data_queue.get(timeout=0.1)
                if callback:
                    callback(data_point)

                yield data_point

            except queue.Empty:
                if hasattr(self.lib, "ngSpice_running"):
                    if not self.lib.ngSpice_running():
                        self._is_running = False
                        break

        while not self._async_data_queue.empty():
            data_point = self._async_data_queue.get_nowait()
            if callback:
                callback(data_point)
            yield data_point

    def is_running(self) -> bool:
        return self._is_running

    def get_async_data_queue(self) -> "queue.Queue[dict]":
        return self._async_data_queue

    def fallback_handler_executed(self) -> bool:
        """Check if the fallback handler was executed during async simulation."""
        return self._fallback_executed

    def get_normal_callback_count(self) -> int:
        """Get the number of normal callbacks received during async simulation."""
        return self._normal_callbacks_received

    def stop_simulation(self):
        if self._is_running:
            self.command("bg_halt")
            self._is_running = False
            timeout = time.time() + 2.0

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

            return not self._is_running
        else:
            return True

    def _read_running_state(self) -> Optional[bool]:
        try:
            return bool(self.lib.ngSpice_running())
        except AttributeError:
            if self.debug:
                _debug("ngSpice_running unavailable; assuming simulation halted")
            return None
        except Exception as exc:  # pragma: no cover - defensive fallback
            if self.debug:
                _debug(f"ngSpice_running check failed: {exc}")
            return bool(self._is_running)

    def safe_halt_simulation(
        self, max_attempts: int = 3, wait_time: float = 0.2
    ) -> bool:
        if not self._is_running:
            return True

        for _ in range(max_attempts):
            self.command("bg_halt")
            deadline = time.time() + wait_time

            while time.time() < deadline:
                is_running = self._read_running_state()

                if is_running is False:
                    self._is_running = False
                    return True

                if is_running is None:
                    self._is_running = False
                    return True

                time.sleep(min(0.05, wait_time / 5))

        final_state = self._read_running_state()

        if final_state is False or final_state is None:
            self._is_running = False
            return True

        return False

    def halt_simulation(self, timeout: float = 2.0) -> bool:
        result = self.safe_halt_simulation(
            max_attempts=int(timeout / 0.2), wait_time=0.2
        )
        return result

    def safe_resume_simulation(
        self, max_attempts: int = 3, wait_time: float = 2.0
    ) -> bool:
        if self._is_running:
            return True  # Already running

        for attempt in range(max_attempts):
            # Send bg_resume command
            result = self.command("bg_resume")

            # Check if ngspice is actually running using the library function
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:

                def check_resume_status():
                    try:
                        is_running = self.lib.ngSpice_running()
                        if is_running:
                            self._is_running = True  # Update our state
                        return is_running
                    except Exception:
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
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:

            def check_resume_status():
                try:
                    is_running = self.lib.ngSpice_running()
                    if is_running:
                        self._is_running = True  # Update our state
                    return is_running
                except Exception:
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
            vectors.append(vecs_ptr[i].decode("utf-8"))
            i += 1
        return vectors

    def _get_vector_info(self, vector_name: str) -> Optional[VectorInfo]:
        vec_info_ptr = self.lib.ngGet_Vec_Info(vector_name.encode("utf-8"))
        return vec_info_ptr.contents if vec_info_ptr else None

    @staticmethod
    def find_library() -> ctypes.CDLL:
        if sys.platform == "win32":
            return ctypes.CDLL("libngspice-0.dll")
        elif sys.platform == "darwin":
            return ctypes.CDLL("libngspice.0.dylib")
        else:
            return ctypes.CDLL("libngspice.so.0")

    def _setup_library_functions(self):
        # Define callback function prototypes
        self._SendChar = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p
        )
        self._SendStat = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p
        )
        self._ControlledExit = ctypes.CFUNCTYPE(
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_bool,
            ctypes.c_bool,
            ctypes.c_int,
            ctypes.c_void_p,
        )
        self._SendData = ctypes.CFUNCTYPE(
            ctypes.c_int,
            ctypes.POINTER(self.VecValuesAll),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
        )
        self._SendInitData = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.POINTER(self.VecInfoAll), ctypes.c_int, ctypes.c_void_p
        )
        self._BGThreadRunning = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p
        )

        # Core functions
        self.lib.ngSpice_Init.restype = ctypes.c_int
        self.lib.ngSpice_Init.argtypes = [
            self._SendChar,
            self._SendStat,
            self._ControlledExit,
            self._SendData,
            self._SendInitData,
            self._BGThreadRunning,
            ctypes.c_void_p,
        ]

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
