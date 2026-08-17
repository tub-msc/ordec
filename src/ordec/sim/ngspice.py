# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""Pure ngspice subprocess wrapper with no ORDB knowledge.

Provides ngspice_batch() for running ngspice in batch mode and parsing
binary rawfiles into SimArray results."""

import mmap
import os
import re
import struct
import sys
import shutil
import tempfile
import threading
import logging
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import Optional

from ..core import R, Quantity, SimArray, SimArrayField
from ..core.genrun import progress, checkpoint, cancelable_subprocess

logger = logging.getLogger(__name__)


class NgspiceError(Exception):
    pass


@dataclass
class NgspiceSetup:
    """Return type for ngspice setup functions.

    Bundles the spiceinit commands with optional subprocess environment
    variables needed by the PDK (e.g. PDK_ROOT).
    """
    commands: list[str]
    env: dict[str, str] = field(default_factory=dict)




def check_errors(ngspice_out):
    """Helper function to raise NgspiceError in Python from "Error: ..."
    messages in Ngspice's output."""
    first_error_msg = None

    for line in ngspice_out.split("\n"):
        if "no such vector" in line:
            continue
        m = re.match(r"(?:stderr )?Error:\s*(.*)", line)
        if m and first_error_msg is None:
            first_error_msg = "Error: " + m.group(1)

    if first_error_msg:
        raise NgspiceError(first_error_msg)

def name_print_to_raw(name: str) -> str:
      """
      Convert an ngspice print-style signal name to rawfile-style. (Not
      currently used anywhere, because op() now also uses rawfile output instead
      of 'print all').

      Examples:
          a                   -> v(a)
          vgnd#branch         -> i(gnd)
          @m.xdut.mm2[is]     -> @m.xdut.mm2[is]
          i(@m.xdut.mm2[is])  -> i(@m.xdut.mm2[is])   # already raw-style
          v(a)                -> v(a)                 # already raw-style
      """
      s = name.strip()
      if not s:
          return s

      # Already raw-style.
      if re.fullmatch(r'[vViI]\(.*\)', s):
          return s

      # Internal/device parameter vectors stay as-is.
      if s.startswith('@'):
          return s

      # print-style branch current: "foo#branch" -> "i(foo)"
      if s.endswith('#branch'):
          return f"i({s[:-7]})"

      # Otherwise treat it as a node voltage: "a" -> "v(a)"
      return f"v({s})"


# Quantities for the vector types that ngspice defines with a unit
# (typesdef.c); used to tag SimArray fields when parsing rawfiles. The
# unit-less types (notype, pole, zero, s-param) stay untagged, as does
# phase, whose unit is not recorded in the rawfile (see Quantity).
RAW_TYPE_QUANTITIES = {
    'time': Quantity.TIME,
    'frequency': Quantity.FREQUENCY,
    'voltage': Quantity.VOLTAGE,
    'current': Quantity.CURRENT,
    'voltage-density': Quantity.VOLTAGE_DENSITY,
    'current-density': Quantity.CURRENT_DENSITY,
    'voltage^2-density': Quantity.VOLTAGE_SQUARED_DENSITY,
    'current^2-density': Quantity.CURRENT_SQUARED_DENSITY,
    'voltage^2': Quantity.VOLTAGE_SQUARED,
    'current^2': Quantity.CURRENT_SQUARED,
    'temp-sweep': Quantity.TEMPERATURE,
    'res-sweep': Quantity.RESISTANCE,
    'impedance': Quantity.IMPEDANCE,
    'admittance': Quantity.ADMITTANCE,
    'power': Quantity.POWER,
    'decibel': Quantity.DECIBEL,
    'capacitance': Quantity.CAPACITANCE,
    'charge': Quantity.CHARGE,
    'temperature': Quantity.TEMPERATURE,
}

def parse_raw(fn, use_mmap=True) -> SimArray:
    """Parse a ngspice binary rawfile.

    Returns a SimArray whose fields carry name, dtype and quantity metadata.
    Real simulations (tran, op) yield float64 values; AC simulations yield
    complex128 values.

    Args:
        fn: Path to the rawfile.
        use_mmap: If True (default), back the data with an mmap so the
            OS pages in only the columns actually accessed. Falls back
            to a plain read when False or when the file is empty.
    """
    info = {}
    var_names = []
    var_quantities = []

    with open(fn, "rb") as f:
        while True:
            line = f.readline()
            if not line:
                raise ValueError("Unexpected EOF while reading rawfile header")
            l = line.rstrip(b"\n").decode("ascii")

            if l.startswith("\t"):
                parts = l.split("\t")
                if len(parts) < 4:
                    raise ValueError(f"Malformed variable line in rawfile: {l!r}")
                _, var_idx, var_name, var_type = parts[:4]
                assert int(var_idx) == len(var_names)
                var_names.append(var_name)
                # The AC frequency scale is typed "frequency grid=3",
                # hence the split.
                var_quantities.append(
                    RAW_TYPE_QUANTITIES.get(var_type.split(' ', 1)[0]))
            else:
                if ":" not in l:
                    raise ValueError(f"Malformed header line in rawfile: {l!r}")
                lhs, rhs = l.split(":", 1)
                info[lhs] = rhs.strip()
                if lhs == "Binary":
                    break

        if "No. Variables" not in info or "No. Points" not in info:
            raise ValueError("Missing required rawfile header fields")
        if len(var_names) != int(info["No. Variables"]):
            raise ValueError(
                f"Rawfile variable count mismatch: parsed {len(var_names)}, "
                f"header says {info['No. Variables']}"
            )
        no_points = int(info["No. Points"])

        # AC simulations store complex-valued vectors; transient/op use real.
        is_complex = "complex" in info.get("Flags", "").lower()
        dtype = 'c16' if is_complex else 'f8'

        fields = tuple(
            SimArrayField(name, dtype, quantity)
            for name, quantity in zip(var_names, var_quantities)
        )

        # Calculate expected bytes per record
        field_size = 16 if is_complex else 8
        record_size = field_size * len(var_names)
        expected_bytes = record_size * no_points

        if use_mmap and expected_bytes > 0:
            data_offset = f.tell()
            # mmap holds its own reference to the underlying fd, so it
            # remains valid after the `with` closes the Python file object.
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            # Slicing mmap directly copies into bytes; memoryview gives
            # a zero-copy slice that still references the mmap.
            mv = memoryview(mm)[data_offset : data_offset + expected_bytes]
            if len(mv) != expected_bytes:
                raise ValueError(
                    f"Expected {expected_bytes} bytes, got {len(mv)}"
                )
            return SimArray(fields, mv)
        else:
            data = f.read(expected_bytes)
            if len(data) != expected_bytes:
                raise ValueError(
                    f"Expected {expected_bytes} bytes, got {len(data)}"
                )
            return SimArray(fields, data)


def format_time(t: float) -> str:
    """
    Format a time in seconds for display, e.g. 0.0012345 -> "1.235ms".
    Rounds to 4 significant digits and reuses R's SI suffixes; the
    trailing "." that R appends to suffix-less numbers is dropped.
    """
    return str(R(float(f"{t:.4g}"))).rstrip('.') + 's'


class RawfileMonitor:
    """Progress monitor for a binary rawfile that ngspice batch mode is
    still writing.

    Batch mode streams the rawfile during simulation: header first (with
    "No. Points: 0", patched on completion), then data rows appended
    continuously. The first variable of each row is the independent
    variable (time for tran), so the last complete row tells how far the
    simulation has come.
    """
    def __init__(self, fn, tstop: R):
        self.fn = Path(fn)
        self.tstop = float(R(tstop))
        self.data_offset = None
        self.row_size = None

    def _parse_header(self) -> bool:
        """Try to parse the rawfile header; returns True once complete."""
        try:
            with open(self.fn, "rb") as f:
                head = f.read(65536)
        except OSError:
            return False
        m = re.search(rb"^Binary:\n", head, re.MULTILINE)
        if not m:
            return False
        header = head[:m.end()]
        m_nvars = re.search(rb"No\. Variables:\s*(\d+)", header)
        if not m_nvars:
            return False
        n_vars = int(m_nvars.group(1))
        m_flags = re.search(rb"Flags:\s*([^\n]*)", header)
        is_complex = m_flags and (b"complex" in m_flags.group(1))
        self.row_size = n_vars * (16 if is_complex else 8)
        self.data_offset = m.end()
        return True

    def poll(self) -> Optional[tuple[float, float]]:
        """
        Simulation progress as (fraction of tstop, simulated time in
        seconds), or None if not known yet.
        """
        if self.data_offset is None and not self._parse_header():
            return None
        if self.tstop <= 0:
            return None
        try:
            file_size = os.path.getsize(self.fn)
            n_rows = (file_size - self.data_offset) // self.row_size
            if n_rows <= 0:
                return None
            with open(self.fn, "rb") as f:
                f.seek(self.data_offset + (n_rows - 1) * self.row_size)
                buf = f.read(8)
        except OSError:
            return None
        if len(buf) < 8:
            return None
        t_last = struct.unpack("<d", buf)[0]
        return min(t_last / self.tstop, 1.0), t_last



def _ngspice_executable() -> str:
    """Return the ngspice executable name for the current platform."""
    if sys.platform == "win32" and shutil.which("ngspice_con"):
        return "ngspice_con"
    return "ngspice"


def ngspice_batch(netlist: str, spiceinit_commands: list[str] | None = None,
    no_auto_gnd: bool = True, env: dict[str, str] | None = None,
    tran_tstop: Optional[R] = None,
) -> SimArray:
    """Run ngspice in batch mode and return simulation results.

    Batch mode streams data to disk during simulation, keeping memory
    usage constant regardless of result size. The netlist must contain
    embedded analysis directives (.tran, .ac, .dc, .op).

    Runs are cancellable via view-generation cancellation (the ngspice
    process is killed) and report progress while running. If tran_tstop
    is given, a progress fraction is derived from the growing rawfile;
    otherwise only a status message is reported.

    Args:
        netlist: Complete SPICE netlist with analysis directives.
        spiceinit_commands: Extra commands for .spiceinit (from PDK
            setup funcs).
        no_auto_gnd: Disable ngspice auto-grounding of 'gnd' net.
        tran_tstop: Stop time of the netlist's .tran directive, enabling
            a progress fraction (simulated time / tstop).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Write .spiceinit — ngspice reads it from the working directory.
        init_lines = ["set filetype=binary"]
        if no_auto_gnd:
            init_lines.append("set no_auto_gnd")
        if spiceinit_commands:
            init_lines.extend(spiceinit_commands)
        (tmppath / ".spiceinit").write_text("\n".join(init_lines) + "\n")

        # Write netlist.
        (tmppath / "netlist.sp").write_text(netlist)

        rawfile = tmppath / "sim.raw"
        if tran_tstop is not None:
            monitor = RawfileMonitor(rawfile, tran_tstop)
        else:
            monitor = None
            progress("Running ngspice")

        exe = _ngspice_executable()
        logger.debug("Running ngspice batch: %s", exe)
        p = subprocess.Popen(
            [exe, "-b", "-r", "sim.raw", "netlist.sp"],
            cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env or None)

        # Drain stdout on a side thread: reading here would block the
        # progress-poll loop, not reading at all could stall ngspice on a
        # full pipe buffer.
        stdout_chunks = []
        def drain_stdout():
            for chunk in iter(lambda: p.stdout.read(65536), b""):
                stdout_chunks.append(chunk)
        reader = threading.Thread(target=drain_stdout, daemon=True)
        reader.start()

        try:
            with cancelable_subprocess(p):
                while True:
                    try:
                        p.wait(timeout=0.25)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    checkpoint()
                    if monitor is not None:
                        polled = monitor.poll()
                        if polled is not None:
                            frac, t_now = polled
                            progress("Transient simulation", frac,
                                detail=f"{format_time(t_now)} / "
                                    f"{format_time(monitor.tstop)}")
        finally:
            # On cancellation, make sure ngspice is dead before the
            # temp dir is cleaned up.
            if p.poll() is None:
                p.kill()
                p.wait()
            reader.join()

        stdout_text = b"".join(stdout_chunks).decode("ascii", errors="replace")
        logger.debug("ngspice batch stdout:\n%s", stdout_text)

        check_errors(stdout_text)
        if p.returncode != 0:
            raise NgspiceError(
                f"ngspice exited with code {p.returncode}:\n{stdout_text}")

        if not rawfile.exists():
            raise NgspiceError(
                f"ngspice did not produce a rawfile:\n{stdout_text}")

        return parse_raw(rawfile)

