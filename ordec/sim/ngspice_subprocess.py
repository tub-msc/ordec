# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
import re
import signal
import string
import sys
import tempfile
import shutil
import queue
import threading
import time
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from subprocess import Popen, PIPE, STDOUT
from typing import Iterator, Optional

import numpy as np
from ..core.rational import Rational as R

from .ngspice_common import (
    NgspiceValue,
    NgspiceError,
    NgspiceFatalError,
    NgspiceTransientResult,
    NgspiceAcResult,
    NgspiceResultBase,
    check_errors,
    NgspiceTable,
    SignalKind,
    SignalArray,
    NgspiceBase,
    NgspiceConfigError,
)

NgspiceVector = namedtuple(
    "NgspiceVector", ["name", "quantity", "dtype", "length", "rest"]
)

_DEBUG_PREFIX = "[ngspice-cli]"


def _debug(message: str) -> None:
    print(f"{_DEBUG_PREFIX} {message}")


class NgspiceSubprocess(NgspiceBase):
    @classmethod
    @contextmanager
    def launch(cls, debug: bool):
        # Choose the correct ngspice executable for the platform
        if sys.platform == "win32":
            # On Windows, prefer ngspice_con if available, fall back to ngspice
            ngspice_exe = "ngspice_con" if shutil.which("ngspice_con") else "ngspice"
        else:
            ngspice_exe = "ngspice"

        if debug:
            _debug(f"Using ngspice executable: {ngspice_exe}")
            _debug(f"Platform: {sys.platform}")

        with tempfile.TemporaryDirectory() as cwd_str:
            if debug:
                _debug(f"Starting ngspice with command: {[ngspice_exe, '-p']}")
                _debug(f"Working directory: {cwd_str}")

            p: Popen[bytes] = Popen(
                [ngspice_exe, "-p"], stdin=PIPE, stdout=PIPE, stderr=STDOUT, cwd=cwd_str
            )
            if debug:
                _debug(f"Process started with PID: {p.pid}")

            try:
                yield cls(p, debug=debug, cwd=Path(cwd_str))
            finally:
                if debug:
                    _debug(f"Cleaning up process {p.pid}")
                try:
                    p.send_signal(signal.SIGTERM)
                    if p.stdin:
                        p.stdin.close()
                    if p.stdout:
                        p.stdout.read()
                    p.wait(timeout=1.0)
                except (ProcessLookupError, BrokenPipeError, TimeoutError):
                    pass  # Process may have already terminated

    def __init__(self, p: Popen, debug: bool, cwd: Path):
        self.p: Popen[bytes] = p
        self.debug = debug
        self.cwd = cwd
        self._command_lock = threading.Lock()
        self._async_queue: Optional[queue.Queue] = None
        self._async_thread: Optional[threading.Thread] = None
        self._async_lock = threading.Lock()
        self._async_halt_requested = False
        self._async_halt_ack = threading.Event()
        self._async_resume_event = threading.Event()
        self._async_current_time = 0.0
        self._data_points_sent = 0
        self._last_vector_length = 0
        self._is_running = False
        self._wrdata_file: Optional[Path] = None
        self._wrdata_last_row = 0
        self._wrdata_vectors: list[str] = []

        self._configure_precision()

    def _configure_precision(self) -> None:
        """Configure ngspice numeric precision settings."""

        try:
            if self.debug:
                _debug("Configuring ngspice numeric precision")
            # Increase the number of digits printed in tabular outputs.
            self.command("set numdgt=16")
            # Ensure computed scalar values use the same precision.
            self.command("set csnumprec=16")
        except NgspiceError as exc:
            raise NgspiceConfigError("Failed to configure ngspice precision") from exc

    def _set_running_flag(self, running: bool) -> None:
        """Update the running flag under the async lock to keep state atomic."""
        with self._async_lock:
            self._is_running = running

    def _get_running_flag(self) -> bool:
        """Read the running flag under the async lock."""
        with self._async_lock:
            return self._is_running

    def _send_bg_halt_unlocked(self) -> None:
        """Send bg_halt without waiting for marker; assumes command lock is held."""
        if self.p.poll() is not None:
            return
        if self.p.stdin:
            if self.debug:
                _debug("Issuing bg_halt while a command is in flight")
            self.p.stdin.write(b"bg_halt\n")
            self.p.stdin.flush()

    def _run_command_locked(self, command: str, interruptible: bool = False) -> str:
        """Executes ngspice command and returns string output from ngspice process."""
        if self.p.poll() is not None:
            raise NgspiceFatalError("ngspice process has terminated unexpectedly.")
        if self.debug:
            _debug(f"Sending command to ngspice ({self.p.pid}): {command}")

        if self.p.stdin:
            # Send the command followed by echo marker on separate lines
            full_input = f"{command}\necho FINISHED\n"
            if self.debug:
                _debug(f"Writing to stdin: {repr(full_input)}")
            self.p.stdin.write(full_input.encode("ascii"))
            self.p.stdin.flush()
            if self.debug:
                _debug(f"Stdin flushed")

        out = []
        line_count = 0
        halt_sent = False
        while True:
            if self.debug:
                _debug(f"Waiting for line {line_count}...")
            l = self.p.stdout.readline()
            line_count += 1
            if self.debug:
                _debug(f"Received line {line_count} from ngspice: {repr(l)}")

            # Check for EOF first
            if l == b"":  # readline() returns the empty byte string only on EOF.
                out_flat = "".join(out)
                if self.debug:
                    _debug(f"EOF detected, ngspice terminated")
                raise NgspiceFatalError(
                    f"ngspice terminated abnormally:\n{out_flat}"
                )

            # Strip ALL occurrences of "ngspice 123 -> " from the line on all platforms
            # Preserve newlines when stripping prompts
            while True:
                m = re.match(rb"ngspice [0-9]+ -> (.*)", l)
                if not m:
                    break
                if self.debug:
                    _debug(
                        f"Stripping prompt from line: {repr(l)} -> {repr(m.group(1))}"
                    )
                stripped_content = m.group(1)
                # Preserve the newline if the original line had one
                if l.endswith(b"\n") and not stripped_content.endswith(b"\n"):
                    l = stripped_content + b"\n"
                else:
                    l = stripped_content

            # Check for our finish marker
            if l.rstrip() == b"FINISHED":
                if self.debug:
                    _debug(f"Found FINISHED marker, breaking")
                break

            if interruptible and self._async_halt_requested and not halt_sent:
                self._send_bg_halt_unlocked()
                halt_sent = True

            # Skip empty lines that are just prompts
            if l.strip() == b"":
                continue

            out.append(l.decode("ascii"))
            if self.debug:
                _debug(f"Added to output: {repr(l.decode('ascii'))}")

        out_flat = "".join(out)
        if self.debug:
            _debug(f"Received result from ngspice ({self.p.pid}): {repr(out_flat)}")

        check_errors(out_flat)
        return out_flat

    def command(self, command: str, *, interruptible: bool = False) -> str:
        """Executes ngspice command and returns string output from ngspice process."""
        with self._command_lock:
            return self._run_command_locked(command, interruptible=interruptible)

    def load_netlist(self, netlist: str, no_auto_gnd: bool = True):
        netlist_fn = self.cwd / "netlist.sp"
        netlist_fn.write_text(netlist)
        if self.debug:
            _debug(f"Written netlist: \n {netlist}")
        if no_auto_gnd:
            self.command("set no_auto_gnd")
        check_errors(self.command(f"source {netlist_fn}"))

    def print_all(self) -> Iterator[str]:
        """
        Tries "print all" first. If it fails due to zero-length vectors, emulate
        "print all" using display and print but skip zero-length vectors.
        """

        print_all_res = self.command("print all")
        # Check if the result contains the warning about zero-length vectors
        if "is not available or has zero length" in print_all_res:
            # get list of available vectors and print only valid ones
            display_output = self.command("display")

            # Parse vector list and print only vectors with length > 0
            for line in display_output.split("\n"):
                # Look for vector definitions like "name: type, real, N long"
                vector_match = re.match(
                    r"\s*([^:]+):\s*[^,]+,\s*[^,]+,\s*([0-9]+)\s+long", line
                )
                if vector_match:
                    vector_name = vector_match.group(1).strip()
                    vector_length = int(vector_match.group(2))

                    # Only print vectors that have data (length > 0)
                    if vector_length > 0:
                        yield self.command(f"print {vector_name}")
        else:
            yield from print_all_res.split("\n")

    def _parse_op_results(self) -> Iterator[str]:
        """
        Parse operating point results, extracting only the result lines
        from command output and skipping command echoes and FINISHED markers.
        """
        print_all_res = self.command("print all")
        # Check if the result contains the warning about zero-length vectors
        if "is not available or has zero length" in print_all_res:
            # Fallback: get list of available vectors and print only valid ones
            display_output = self.command("display")

            # Parse vector list and print only vectors with length > 0
            for line in display_output.split("\n"):
                # Look for vector definitions like "name: type, real, N long"
                vector_match = re.match(
                    r"\s*([^:]+):\s*[^,]+,\s*[^,]+,\s*([0-9]+)\s+long", line
                )
                if vector_match:
                    vector_name = vector_match.group(1).strip()
                    vector_length = int(vector_match.group(2))

                    # Only print vectors that have data (length > 0)
                    if vector_length > 0:
                        cmd_output = self.command(f"print {vector_name}")
                        # Extract just the result lines from command output
                        for output_line in cmd_output.split("\n"):
                            if re.match(
                                r"([0-9a-zA-Z_.#]+)\s*=\s*([0-9.\-+e]+)\s*", output_line
                            ):
                                yield output_line
        else:
            # Extract just the result lines from the print all output
            for line in print_all_res.split("\n"):
                if re.match(r"([0-9a-zA-Z_.#]+)\s*=\s*([0-9.\-+e]+)\s*", line):
                    yield line

    def op(self) -> Iterator[NgspiceValue]:
        self.command("op")

        for line in self._parse_op_results():
            if len(line) == 0:
                continue

            # Voltage result - updated regex to handle device names with special chars:
            res = re.match(r"([0-9a-zA-Z_.#]+)\s*=\s*([0-9.\-+e]+)\s*", line)
            if res:
                yield NgspiceValue(
                    type="voltage",
                    name=res.group(1),
                    subname=None,
                    value=float(res.group(2)),
                )

            # Current result like "vgnd#branch":
            res = re.match(r"([0-9a-zA-Z_.#]+)#branch\s*=\s*([0-9.\-+e]+)\s*", line)
            if res:
                yield NgspiceValue(
                    type="current",
                    name=res.group(1),
                    subname="branch",
                    value=float(res.group(2)),
                )

            # Current result like "@m.xdut.mm2[is]" from savecurrents:
            res = re.match(
                r"@([a-zA-Z]\.)?([0-9a-zA-Z_.#]+)\[([0-9a-zA-Z_]+)\]\s*=\s*([0-9.\-+e]+)\s*",
                line,
            )
            if res:
                yield NgspiceValue(
                    type="current",
                    name=res.group(2),
                    subname=res.group(3),
                    value=float(res.group(4)),
                )

    def tran(self, *args) -> NgspiceTransientResult:
        self.command(f"tran {' '.join(args)}")
        print_all_res = "\n".join(self.print_all())
        lines = print_all_res.split("\n")

        result = NgspiceTransientResult()
        tables = {}  # map from header tuple to list of data rows
        current_headers = None

        for line in lines:
            line = line.strip()
            if not line or re.match(r"^-+$", line) or "Transient Analysis" in line:
                continue

            potential_headers = line.split()
            is_header = any(
                h.lower() in ("time", "index") for h in potential_headers
            ) and not self._is_numeric_row(potential_headers)

            if is_header:
                current_headers = tuple(potential_headers)
                if current_headers not in tables:
                    tables[current_headers] = []
            elif current_headers:
                row_data = line.split()
                if self._is_numeric_row(row_data):
                    # Ensure data row has a compatible number of columns, pad if necessary
                    if len(row_data) <= len(current_headers):
                        tables[current_headers].append(row_data)

        for headers, data in tables.items():
            if data:
                table = NgspiceTable("transient")
                table.headers = list(headers)
                table.data = data
                result.add_table(table)

        self._update_signal_kinds_from_vector_info(result)

        return result

    def _update_signal_kinds_from_vector_info(self, result):
        vectors_info = self.vector_info()
        for vec_info in vectors_info:
            if vec_info.name in result.signals:
                if hasattr(vec_info, "quantity") and vec_info.quantity:
                    if vec_info.quantity.lower() in ("time", "index"):
                        result.signals[vec_info.name].kind = SignalKind.TIME
                    elif vec_info.quantity.lower() in ("voltage", "v"):
                        result.signals[vec_info.name].kind = SignalKind.VOLTAGE
                    elif vec_info.quantity.lower() in ("current", "i"):
                        result.signals[vec_info.name].kind = SignalKind.CURRENT

    def tran_async(
        self,
        tstep,
        tstop=None,
        *extra_args,
        throttle_interval: float = 0.1,
        buffer_size: int = 10,
        disable_buffering: bool = False,
        disable_throttling: bool = False,
        fallback_sampling_ratio: int = 100,
    ) -> "queue.Queue[dict]":
        """Run async transient simulation using chunked approach with stop after and step commands."""

        tstep_r = R(tstep)
        tstop_r = R(tstop) if tstop is not None else None

        tstep_val = float(tstep_r)
        tstop_val = float(tstop_r) if tstop_r is not None else None
        tstep_str = str(tstep_r)

        self._async_queue = queue.Queue()
        self._async_halt_requested = False
        self._async_resume_event = threading.Event()
        self._async_resume_event.set()
        self._async_current_time = 0.0
        self._data_points_sent = 0
        self._last_vector_length = 0
        self._async_halt_ack.clear()
        self._set_running_flag(False)
        self._wrdata_file = None
        self._wrdata_last_row = 0
        self._wrdata_vectors = []

        self._async_thread = threading.Thread(
            target=self._run_chunked_simulation,
            args=(tstep_val, tstop_val, tstep_str, throttle_interval),
            daemon=True,
        )
        self._async_thread.start()

        return self._async_queue

    def is_running(self) -> bool:
        """Check if simulation is running."""
        running_flag = self._get_running_flag()
        return running_flag and self._async_thread is not None and self._async_thread.is_alive()

    def safe_halt_simulation(
        self, max_attempts: int = 3, wait_time: float = 0.2
    ) -> bool:
        """Halt simulation by setting halt flag and clearing resume event."""
        if self._async_thread is None or not self._async_thread.is_alive():
            return True

        with self._async_lock:
            self._async_halt_requested = True
            self._async_resume_event.clear()
            self._async_halt_ack.clear()

        self._async_halt_ack.wait(timeout=wait_time)

        issued_directly = False
        if self._command_lock.acquire(blocking=False):
            try:
                self._run_command_locked("bg_halt")
                issued_directly = True
            finally:
                self._command_lock.release()

        if self.debug and not issued_directly:
            _debug("bg_halt will be issued by running step command")

        deadline = time.time() + (max_attempts * wait_time)
        poll_interval = min(0.05, wait_time / 5) if wait_time else 0.05

        while time.time() < deadline:
            if not self.is_running():
                return True
            time.sleep(poll_interval)

        if self.debug:
            _debug("safe_halt_simulation timed out waiting for async thread")

        return not self.is_running()

    def resume_simulation(self, timeout: float = 3.0) -> bool:
        """Resume simulation by clearing halt flag and setting resume event."""
        with self._async_lock:
            self._async_halt_requested = False
            self._async_resume_event.set()
            self._async_halt_ack.clear()

        if self.debug:
            _debug("Resume requested")

        return True

    def safe_resume_simulation(
        self, max_attempts: int = 3, wait_time: float = 2.0
    ) -> bool:
        """Resume simulation safely with retry logic."""
        for attempt in range(max_attempts):
            self.resume_simulation(timeout=wait_time)

            deadline = time.time() + wait_time
            poll_interval = min(0.05, wait_time / 5) if wait_time else 0.05
            while time.time() < deadline:
                if self.is_running():
                    return True
                time.sleep(poll_interval)
        return False

    def _is_header_line(self, line, expected_headers):
        """Check if a line looks like a header line."""
        if not line.strip():
            return False
        line_lower = line.lower()
        header_matches = 0
        for header in expected_headers:
            if header.lower() in line_lower:
                header_matches += 1
        return header_matches >= len(expected_headers) * 0.6

    _SLICE_SAFE_CHARS = set(string.ascii_letters + string.digits + "_.")

    def _quote_vector_name(self, vector_name: str) -> str:
        if not vector_name:
            return vector_name

        if all(ch in self._SLICE_SAFE_CHARS for ch in vector_name):
            return vector_name

        escaped = vector_name.replace('"', '\\"')
        return f'"{escaped}"'

    def _collect_active_vectors(self) -> list[str]:
        display_output = self.command("display")
        vectors: list[str] = []

        for line in display_output.split("\n"):
            vector_match = re.match(
                r"\s*([^:]+):\s*[^,]+,\s*[^,]+,\s*([0-9]+)\s+long",
                line,
            )
            if vector_match:
                vector_name = vector_match.group(1).strip()
                vector_length = int(vector_match.group(2))

                if vector_length == 0:
                    continue

                if vector_name in {
                    "current_len",
                    "old_len",
                    "new_len",
                    "start_idx",
                    "end_idx",
                }:
                    continue

                if vector_name.lower() in {"time", "index"}:
                    continue

                vectors.append(vector_name)

        return vectors

    def _fetch_new_samples_via_wrdata(self) -> list[dict[str, float | complex]]:
        vectors = self._collect_active_vectors()
        if not vectors:
            return []

        if self._wrdata_vectors != vectors:
            self._wrdata_last_row = 0
            self._wrdata_vectors = list(vectors)

        command_vectors = ["time"] + vectors

        if self._wrdata_file is None:
            self._wrdata_file = self.cwd / "ordec_async_wrdata.dat"

        quoted_vectors = " ".join(
            self._quote_vector_name(vec) for vec in command_vectors
        )

        self.command(f"wrdata {self._wrdata_file} {quoted_vectors}")

        try:
            data = np.loadtxt(self._wrdata_file)
        except OSError as e:
            if self.debug:
                _debug(
                    f"OSError loading '{self._wrdata_file}': {e}"
                )
            return []

        if data.size == 0:
            return []

        if data.ndim == 1:
            data = data.reshape(1, -1)

        total_rows = data.shape[0]
        if total_rows <= self._wrdata_last_row:
            return []

        new_rows = data[self._wrdata_last_row :]
        self._wrdata_last_row = total_rows

        columns_per_vector = data.shape[1] // len(command_vectors)
        if columns_per_vector == 0:
            return []

        samples: list[dict[str, float | complex]] = []

        for row in new_rows:
            sample: dict[str, float | complex] = {}

            for idx, vec in enumerate(command_vectors):
                start = idx * columns_per_vector
                real_val = float(row[start])
                imag_val = float(row[start + 1]) if columns_per_vector > 1 else 0.0

                if vec == "time":
                    sample["time"] = real_val
                    continue

                if columns_per_vector > 1 and abs(imag_val) > 1e-18:
                    sample[vec] = complex(real_val, imag_val)
                else:
                    sample[vec] = real_val

            samples.append(sample)

        return samples

    def _build_signal_kind_map(self) -> dict[str, SignalKind]:
        kinds: dict[str, SignalKind] = {"time": SignalKind.TIME}
        temp_result = NgspiceResultBase()

        for vec in self.vector_info():
            if vec.name.lower() == "time":
                kinds[vec.name] = SignalKind.TIME
                continue

            kinds[vec.name] = temp_result.categorize_signal(vec.name)

        return kinds

    def _emit_samples(
        self,
        samples: list[dict[str, float | complex]],
        tstop: float | None,
    ) -> None:
        signal_kinds = self._build_signal_kind_map()

        for sample in samples:
            time_val = float(sample.get("time", 0.0))

            with self._async_lock:
                if self._async_halt_requested:
                    if self.debug:
                        _debug("Halt requested before enqueuing samples")
                    break

            data_point = {
                "timestamp": time.time(),
                "data": {"time": time_val},
                "signal_kinds": {"time": SignalKind.TIME},
                "index": self._data_points_sent,
                "progress": min(1.0, time_val / tstop)
                if tstop is not None and tstop > 0
                else 0.0,
            }

            signal_count = 0
            for name, value in sample.items():
                if name == "time":
                    continue

                if isinstance(value, complex):
                    if abs(value.imag) > 1e-18 and self.debug:
                        _debug(
                            f"Dropping imaginary component for {name}: {value.imag}"
                        )
                    value = float(value.real)

                data_point["data"][name] = float(value)
                data_point["signal_kinds"][name] = signal_kinds.get(
                    name,
                    SignalKind.VOLTAGE,
                )
                signal_count += 1

            if signal_count == 0:
                continue

            if self._async_queue:
                self._async_queue.put(data_point)

            self._data_points_sent += 1
            self._async_current_time = time_val

    def _run_chunked_simulation(
        self,
        tstep: float,
        tstop: float | None,
        tstep_str: str,
        throttle_interval: float,
    ):
        """Run chunked transient simulation using stop after and step commands."""
        try:
            # Calculate chunk size (number of steps per chunk)
            if tstop is not None:
                # Aim for ~100 chunks across the simulation
                total_steps = int(tstop / tstep)
                chunk_steps = max(5, total_steps // 100)
            else:
                chunk_steps = 10

            try:
                self.command(f"stop after {chunk_steps}")
                tran_cmd = f"tran {tstep_str} {tstop if tstop else tstep * 1000}"
                self.command(tran_cmd)
                self._set_running_flag(True)
                self._async_halt_ack.clear()
                self._async_resume_event.set()  # Initially running
            except NgspiceError as e:
                error_data = {"error": f"Simulation failed to start: {str(e)}"}
                if self._async_queue:
                    self._async_queue.put(error_data)
                return

            simulation_complete = False
            while not simulation_complete:
                if self._async_halt_requested:
                    self._set_running_flag(False)
                    self._async_halt_ack.set()

                    if self.debug:
                        _debug(f"Simulation halted, waiting for resume...")

                    resumed = self._async_resume_event.wait(timeout=0.5)

                    if self._async_halt_requested and not resumed:
                        continue

                    if self._async_halt_requested:
                        if self.debug:
                            _debug(f"Exiting due to halt without resume")
                        break

                    self._async_halt_ack.clear()
                    self._set_running_flag(True)
                    if self.debug:
                        _debug(f"Simulation resumed")

                if self._async_halt_requested:
                    continue

                try:
                    samples = self._fetch_new_samples_via_wrdata()
                except NgspiceError as exc:
                    if self.debug:
                        _debug(f"wrdata command failed: {exc}")
                    samples = []

                current_time = self._async_current_time

                if samples:
                    current_time = max(current_time, max(s['time'] for s in samples))
                    self._emit_samples(samples, tstop)

                if not self._async_halt_requested:
                    try:
                        if self._async_halt_requested:
                            continue
                        step_output = self.command(f"step {chunk_steps}", interruptible=True)
                        if "simulation interrupted" not in step_output.lower():
                            if self.debug:
                                _debug("Simulation completed, getting final data")
                            try:
                                final_samples = self._fetch_new_samples_via_wrdata()
                                if final_samples:
                                    self._emit_samples(final_samples, tstop)
                            except Exception as e:
                                if self.debug:
                                    _debug(f"Error getting final data: {e}")
                            simulation_complete = True
                            break
                    except NgspiceError as e:
                        if self.debug:
                            _debug(f"Step command failed: {e}")
                        simulation_complete = True
                        break

                if tstop is not None and current_time >= tstop * 0.9999:
                    if self.debug:
                        _debug(f"Reached target time {current_time} >= {tstop}")
                    try:
                        final_samples = self._fetch_new_samples_via_wrdata()
                        if final_samples:
                            self._emit_samples(final_samples, tstop)
                    except Exception as e:
                        if self.debug:
                            _debug(f"Error getting final data: {e}")
                    simulation_complete = True
                    break

                time.sleep(min(throttle_interval, 0.05))

            self._set_running_flag(False)

            if not self._async_halt_requested:
                if self.debug:
                    _debug("Simulation completed normally")
                self._async_queue.put({"status": "completed"})
            else:
                if self.debug:
                    _debug("Simulation halted by request")
                self._async_queue.put({"status": "halted"})

        except Exception as e:
            self._set_running_flag(False)
            if self.debug:
                _debug(f"Exception in chunked simulation: {e}")
            error_data = {"error": f"Simulation error: {str(e)}"}
            if self._async_queue:
                self._async_queue.put(error_data)

    def _parse_ac_wrdata(self, file_path: str, vectors: list[str]) -> "NgspiceAcResult":
        """Parses the ASCII output of a wrdata command for AC analysis."""
        result = NgspiceAcResult()

        try:
            data = np.loadtxt(file_path)
        except (IOError, ValueError):
            return result

        if data.ndim == 1:
            # Handle case with only one row of data by reshaping it
            data = data.reshape(1, -1)

        if data.shape[0] == 0:
            return result

        result.freq = list(data[:, 0])

        # Subsequent columns are grouped in threes: freq, real, imag.
        for i, vec_name in enumerate(vectors):
            # The block for vector `i` starts at column i*3
            real_col_idx = i * 3 + 1
            imag_col_idx = i * 3 + 2

            if data.shape[1] > imag_col_idx:
                real_parts = data[:, real_col_idx]
                imag_parts = data[:, imag_col_idx]

                complex_data = [complex(r, i) for r, i in zip(real_parts, imag_parts)]
                kind = result.categorize_signal(vec_name)
                result.signals[vec_name] = SignalArray(kind=kind, values=complex_data)

        self._update_signal_kinds_from_vector_info(result)

        return result

    def ac(self, *args, wrdata_file: Optional[str] = None) -> "NgspiceAcResult":
        self.command(f"ac {' '.join(args)}")

        if wrdata_file is None:
            # Original logic using print all
            print_all_res = "".join(self.print_all())
            result = NgspiceAcResult()

            sections = re.split(r"AC Analysis\s+.*\n\s*-{60,}", print_all_res)

            for section in sections:
                if not section.strip():
                    continue

                lines = section.strip().split("\n")
                header_line = lines[0]
                data_lines = lines[1:]

                headers = header_line.split()
                if len(headers) < 2:
                    continue

                vector_name = headers[-1]

                if "frequency" in headers:
                    if not result.freq:
                        for line in data_lines:
                            match = re.match(r"\s*\d+\s+([\d.eE+-]+)", line)
                            if match:
                                result.freq.append(float(match.group(1)))

                signal_data = []
                for line in data_lines:
                    match = re.search(r"([\d.eE+-]+),\s*([\d.eE+-]+)", line)
                    if match:
                        real = float(match.group(1))
                        imag = float(match.group(2))
                        signal_data.append(complex(real, imag))

                if not signal_data:
                    continue

                kind = result.categorize_signal(vector_name)
                result.signals[vector_name] = SignalArray(kind=kind, values=signal_data)

            self._update_signal_kinds_from_vector_info(result)

            return result
        else:
            vectors_to_write = [
                v.name
                for v in self.vector_info()
                if v.name != "frequency" and v.length > 0
            ]
            if not vectors_to_write:
                return NgspiceAcResult()  # Return empty result if no vectors

            # Quote vector names to handle special characters
            vectors_quoted = [f'"{v}"' for v in vectors_to_write]
            self.command(f"wrdata {wrdata_file} {' '.join(vectors_quoted)}")
            return self._parse_ac_wrdata(wrdata_file, vectors_to_write)

    def vector_info(self) -> Iterator[NgspiceVector]:
        """Wrapper for ngspice's "display" command."""
        display_output = self.command("display")
        lines = display_output.split("\n")

        in_vectors_section = False
        for line in lines:
            if "Here are the vectors currently active:" in line:
                in_vectors_section = True
                continue

            if in_vectors_section:
                if (
                    len(line) == 0
                    or line.startswith("Title:")
                    or line.startswith("Name:")
                    or line.startswith("Date:")
                ):
                    continue
                res = re.match(
                    r"\s*([0-9a-zA-Z_.#@\[\]]*)\s*:\s*([a-zA-Z]+),\s*([a-zA-Z]+),\s*([0-9]+) long(.*)",
                    line,
                )
                if res:
                    name, vtype, dtype, length, rest = res.groups()
                    yield NgspiceVector(name, vtype, dtype, int(length), rest)

    def _is_numeric_row(self, row_data):
        """Check if a row contains mostly numeric data."""
        if not row_data:
            return False

        numeric_count = 0
        for item in row_data:
            try:
                float(item)
                numeric_count += 1
            except ValueError:
                # First column might be an index (integer)
                try:
                    int(item)
                    numeric_count += 1
                except ValueError:
                    pass

        # Consider it numeric if at least 80% of values are numbers
        return numeric_count >= len(row_data) * 0.8
