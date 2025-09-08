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

                # Store in queue for safe retrieval
                if data_points:
                    try:
                        self._async_data_queue.put_nowait({
                            'timestamp': current_time,
                            'data': data_points,
                            'index': vec_count
                        })
                    except queue.Full:
                        # Drop oldest data if queue is full
                        try:
                            self._async_data_queue.get_nowait()
                            self._async_data_queue.put_nowait({
                                'timestamp': current_time,
                                'data': data_points,
                                'index': vec_count
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

    def _bg_thread_running_handler(self, is_running, ident, user_data) -> int:
        """Handle background thread status updates (NEVER raise exceptions!)"""
        try:
            self._is_running = bool(is_running)
            if self.debug:
                status = "started" if is_running else "stopped"
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

    def tran_async(self, *args, callback: Optional[Callable] = None, throttle_interval: float = 0.1) -> Generator:
        self._async_callback = callback
        self._async_throttle_interval = throttle_interval
        self._last_callback_time = 0.0

        # Clear any existing data
        while not self._async_data_queue.empty():
            try:
                self._async_data_queue.get_nowait()
            except queue.Empty:
                break

        # Start background simulation using bg_tran
        self.command(f"bg_tran {' '.join(args)}")

        # Wait for simulation to start
        timeout = time.time() + 5.0  # 5 second timeout
        while not self._is_running and time.time() < timeout:
            time.sleep(0.01)

        if not self._is_running:
            raise NgspiceError("Background simulation failed to start")

        # Try streaming first - if no data comes within reasonable time, fall back to polling
        streaming_timeout = time.time() + 0.5  # 500ms to wait for streaming data
        got_streaming_data = False

        # Stream data as it becomes available
        while self._is_running:


            try:
                # Check for data with short timeout
                data_point = self._async_data_queue.get(timeout=0.01)

                got_streaming_data = True
                if callback:
                    callback(data_point)

                yield data_point

            except queue.Empty:
                # Check if simulation is still running
                if hasattr(self.lib, 'ngSpice_running'):
                    is_ngspice_running = self.lib.ngSpice_running()
                    if not is_ngspice_running:
                        self._is_running = False
                        # Don't break yet - handle polling fallback below

                # If no streaming data after timeout OR simulation completed, fall back to polling
                if not got_streaming_data and (time.time() > streaming_timeout or not self._is_running):

                    # Get final results from completed simulation
                    try:
                        # Build result from current simulation vectors
                        all_vectors = self._get_all_vectors()

                        final_data = {}

                        for vec_name in all_vectors:
                            vec_info = self._get_vector_info(vec_name)
                            if vec_info and vec_info.v_length > 0:
                                # Get last value from vector
                                final_data[vec_name] = vec_info.v_realdata[vec_info.v_length - 1]



                        if final_data:
                            final_data_point = {
                                'timestamp': time.time(),
                                'data': final_data,
                                'progress': 1.0
                            }

                            if callback:
                                callback(final_data_point)
                            yield final_data_point
                    except Exception as e:
                        if self.debug:
                            print(f"[ngspice-ffi] Error in polling fallback: {e}")

                    break

                if not self._is_running:
                    break

                # Small sleep to prevent busy waiting
                time.sleep(0.001)

        # Drain any remaining data
        while not self._async_data_queue.empty():
            try:
                data_point = self._async_data_queue.get_nowait()
                if callback:
                    callback(data_point)
                yield data_point
            except queue.Empty:
                break

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

       # Wait for simulation to start
       timeout = time.time() + 5.0
       while not self._is_running and time.time() < timeout:
           time.sleep(0.01)

       if not self._is_running:
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

    def stop_simulation(self):
        if self._is_running:
            self.command("bg_halt")
            self._is_running = False
            # Wait for simulation to stop
            timeout = time.time() + 2.0
            while self._is_running and time.time() < timeout:
                time.sleep(0.01)

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
