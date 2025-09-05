# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import multiprocessing
from multiprocessing import Process, Pipe, Queue
import pickle
from contextlib import contextmanager
import traceback
import queue # For queue.Empty exception

from .ngspice_common import NgspiceTransientResult

_ASYNC_SIM_SENTINEL = "---ASYNC_SIM_SENTINEL---"


try:
    if multiprocessing.get_start_method() != 'spawn':
        multiprocessing.set_start_method('spawn', force=True)
except (RuntimeError, AttributeError):
    pass

class FFIWorkerProcess:
    """
    This worker runs in a separate process. It creates a standard _FFIBackend
    and acts as a bridge, forwarding commands and results between the main
    process and the FFI backend.
    """
    #TODO performance

    def __init__(self, conn: Pipe, async_queue: Queue):
        self.conn = conn
        self.async_queue = async_queue
        self.backend = None

    def run(self):
        """Main worker loop. Waits for commands and dispatches them."""
        from .ngspice_ffi import _FFIBackend

        msg = self.conn.recv()
        if msg['type'] == 'init':
            try:
                self.backend = _FFIBackend(debug=msg.get('debug', False))
                self.conn.send({'type': 'init_success'})
            except Exception as e:
                self.conn.send({'type': 'error', 'data': pickle.dumps(e), 'traceback': traceback.format_exc()})
                return
        else:
            return

        while True:
            try:
                msg = self.conn.recv()
            except (EOFError, BrokenPipeError):
                break

            if msg['type'] == 'quit':
                if self.backend: self.backend.cleanup()
                break

            cmd = msg['type']
            args = msg.get('args', [])
            kwargs = msg.get('kwargs', {})

            try:
                method = getattr(self.backend, cmd)

                if cmd in ['tran_async', 'op_async']:
                    try:
                        self.conn.send({'type': 'result', 'data': pickle.dumps({'async_started': True})})
                        ffi_generator = method(*args, **kwargs)
                        for data_point in ffi_generator:
                            self.async_queue.put(data_point)
                    except Exception as e:
                        self.conn.send({'type': 'error', 'data': pickle.dumps(e), 'traceback': traceback.format_exc()})
                    finally:
                        self.async_queue.put(_ASYNC_SIM_SENTINEL)
                    continue

                result = method(*args, **kwargs)
                if hasattr(result, '__iter__') and not isinstance(result, (list, tuple, dict, str, NgspiceTransientResult)):
                    result = list(result)

                self.conn.send({'type': 'result', 'data': pickle.dumps(result)})
            except Exception as e:
                self.conn.send({'type': 'error', 'data': pickle.dumps(e), 'traceback': traceback.format_exc()})

class IsolatedFFIBackend:
    """
    A proxy that runs FFI calls in an isolated child process.
    """

    @staticmethod
    @contextmanager
    def launch(debug=False):
        parent_conn, child_conn = Pipe()
        async_queue = Queue()

        worker = FFIWorkerProcess(child_conn, async_queue)
        p = Process(target=worker.run)
        p.start()

        backend = None
        try:
            backend = IsolatedFFIBackend(parent_conn, p, async_queue)
            parent_conn.send({'type': 'init', 'debug': debug})
            response = parent_conn.recv()
            if response['type'] == 'error':
                 exc = pickle.loads(response['data'])
                 exc.args += (f"\n--- Traceback from worker process ---\n{response['traceback']}",)
                 raise exc
            yield backend
        finally:
            if backend:
                backend.close()
            if p.is_alive():
                p.join(timeout=1)
                if p.is_alive():
                    p.terminate()

    def __init__(self, conn, process, async_queue):
        self.conn = conn
        self.process = process
        self.async_queue = async_queue

    def close(self):
        try:
            if not self.conn.closed:
                self.conn.send({'type': 'quit'})
        except BrokenPipeError:
            pass
        finally:
            if not self.conn.closed:
                self.conn.close()

    def _call_worker(self, msg_type, *args, **kwargs):
        if self.conn.closed:
            raise RuntimeError("Connection to FFI worker process is closed.")
        self.conn.send({'type': msg_type, 'args': args, 'kwargs': kwargs})
        response = self.conn.recv()
        if response['type'] == 'result':
            return pickle.loads(response['data'])
        elif response['type'] == 'error':
            exc = pickle.loads(response['data'])
            exc.args += (f"\n--- Traceback from worker process ---\n{response['traceback']}",)
            raise exc
        else:
            raise RuntimeError(f"Unexpected response from worker: {response}")

    def _async_results_generator(self):
        while True:
            try:
                item = self.async_queue.get()
                if item == _ASYNC_SIM_SENTINEL:
                    break
                yield item
            except (queue.Empty, EOFError, BrokenPipeError):
                break

    def command(self, command: str) -> str: return self._call_worker('command', command)
    def load_netlist(self, netlist: str, no_auto_gnd: bool = True): return self._call_worker('load_netlist', netlist, no_auto_gnd=no_auto_gnd)
    def op(self): return self._call_worker('op')
    def tran(self, *args): return self._call_worker('tran', *args)
    def ac(self, *args, **kwargs): return self._call_worker('ac', *args, **kwargs)
    def is_running(self) -> bool: return self._call_worker('is_running')
    def stop_simulation(self): return self._call_worker('stop_simulation')
    def reset(self): return self._call_worker('reset')
    def cleanup(self): pass

    def _create_async_generator(self, cmd, *args, **kwargs):
        callback = kwargs.pop('callback', None)
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

    def tran_async(self, *args, **kwargs):
        return self._create_async_generator('tran_async', *args, **kwargs)

    def op_async(self, *args, **kwargs):
        return self._create_async_generator('op_async', *args, **kwargs)
