# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""Pure ngspice subprocess wrapper with no ORDB knowledge.

Provides the Ngspice class for launching and controlling an ngspice process,
running simulations (op, tran, ac, dc), and parsing binary rawfiles into
SimArray results."""

import re
import signal
import struct
import sys
import shutil
import tempfile
import logging
from contextlib import contextmanager
from pathlib import Path
import subprocess
from typing import Iterator, NamedTuple, Optional, Literal

from ..core.rational import Rational as R
from ..core.simarray import SimArray, SimArrayField

logger = logging.getLogger(__name__)


class NgspiceError(Exception):
    pass


class NgspiceFatalError(NgspiceError):
    pass


def check_errors(ngspice_out):
    """Helper function to raise NgspiceError in Python from "Error: ..."
    messages in Ngspice's output."""
    first_error_msg = None
    has_fatal_indicator = False

    for line in ngspice_out.split("\n"):
        if "no such vector" in line:
            continue
        m = re.match(r"(?:stderr )?Error:\s*(.*)", line)
        if m and first_error_msg is None:
            first_error_msg = "Error: " + m.group(1)

        if "cannot recover" in line or "awaits to be reset" in line:
            has_fatal_indicator = True

    if first_error_msg:
        if has_fatal_indicator:
            raise NgspiceFatalError(first_error_msg)
        else:
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


def parse_raw(fn) -> SimArray:
    """Parse a ngspice binary rawfile.

    Returns a SimArray whose fields carry name, dtype and quantity metadata.
    Real simulations (tran, op) yield float64 values; AC simulations yield
    complex128 values.
    """
    info = {}
    var_names = []

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
                _, var_idx, var_name = parts[0], parts[1], parts[2]
                assert int(var_idx) == len(var_names)
                var_names.append(var_name)
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
            SimArrayField(name, dtype)
            for name in var_names
        )

        # Calculate expected bytes per record
        field_size = 16 if is_complex else 8
        record_size = field_size * len(var_names)
        expected_bytes = record_size * no_points

        data = f.read(expected_bytes)
        if len(data) != expected_bytes:
            raise ValueError(
                f"Expected {expected_bytes} bytes, got {len(data)}"
            )

    return SimArray(fields, data)


class NgspiceVector(NamedTuple):
    name: str
    dtype: str
    length: int
    rest: str



def _ngspice_executable() -> str:
    """Return the ngspice executable name for the current platform."""
    if sys.platform == "win32" and shutil.which("ngspice_con"):
        return "ngspice_con"
    return "ngspice"


def ngspice_batch(netlist: str, spiceinit_commands: list[str] | None = None,
    no_auto_gnd: bool = True) -> SimArray:
    """Run ngspice in batch mode and return simulation results.

    Batch mode streams data to disk during simulation, keeping memory
    usage constant regardless of result size. The netlist must contain
    embedded analysis directives (.tran, .ac, .dc, .op).

    Args:
        netlist: Complete SPICE netlist with analysis directives.
        spiceinit_commands: Extra commands for .spiceinit (from PDK
            setup funcs).
        no_auto_gnd: Disable ngspice auto-grounding of 'gnd' net.
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

        exe = _ngspice_executable()
        logger.debug("Running ngspice batch: %s", exe)
        result = subprocess.run(
            [exe, "-b", "-r", "sim.raw", "netlist.sp"],
            cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        stdout_text = result.stdout.decode("ascii", errors="replace")
        logger.debug("ngspice batch stdout:\n%s", stdout_text)

        check_errors(stdout_text)
        if result.returncode != 0:
            raise NgspiceError(
                f"ngspice exited with code {result.returncode}:\n{stdout_text}")

        rawfile = tmppath / "sim.raw"
        if not rawfile.exists():
            raise NgspiceError(
                f"ngspice did not produce a rawfile:\n{stdout_text}")

        return parse_raw(rawfile)


class Ngspice:
    """Interactive piped-mode ngspice wrapper.

    Uses ``ngspice -p`` to keep a persistent process. All simulation
    data accumulates in RAM, so this is not suitable for simulations
    with very large results. For those, use ``ngspice_batch()`` instead.
    """
    @classmethod
    @contextmanager
    def launch(cls):
        exe = _ngspice_executable()
        logger.debug(f"Using ngspice executable: {exe}")

        with tempfile.TemporaryDirectory() as cwd_str:
            p = subprocess.Popen([exe, "-p"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd_str)
            logger.debug(f"Process started with PID: {p.pid}")

            try:
                yield cls(p, cwd=Path(cwd_str))
            finally:
                logger.debug(f"Cleaning up process {p.pid}")
                try:
                    p.send_signal(signal.SIGTERM)
                    if p.stdin:
                        p.stdin.close()
                    if p.stdout:
                        p.stdout.read()
                    p.wait(timeout=1.0)
                except (ProcessLookupError, BrokenPipeError, TimeoutError):
                    pass  # Process may have already terminated

    def __init__(self, p: subprocess.Popen, cwd: Path):
        self.p: subprocess.Popen[bytes] = p
        self.cwd = cwd

        self._configure_precision()

    def _configure_precision(self) -> None:
        """Configure ngspice numeric precision settings."""

        logger.debug("Configuring ngspice numeric precision")
        # Increase the number of digits printed in tabular outputs.
        self.command("set numdgt=16")
        # Ensure computed scalar values use the same precision.
        self.command("set csnumprec=16")
        # Use binary rawfiles for reliable machine-readable data passing.
        self.command("set filetype=binary")
    
    def command(self, command: str) -> str:
        """Executes ngspice command and returns string output from ngspice process."""
        logger.debug(f"Sending command to ngspice ({self.p.pid}): {command}")

        # Send the command followed by echo marker on separate lines.
        full_input = f"{command}\necho FINISHED\n"
        logger.debug(f"Writing to stdin: {repr(full_input)}")
        self.p.stdin.write(full_input.encode("ascii"))
        self.p.stdin.flush()

        out = []
        while True:
            l = self.p.stdout.readline()
            logger.debug(f"Received line from ngspice: {repr(l)}")

            # Check for EOF first
            if l == b"":  # readline() returns the empty byte string only on EOF.
                out_flat = "".join(out)
                logger.debug("EOF detected, ngspice terminated")
                raise NgspiceFatalError(f"ngspice terminated abnormally:\n{out_flat}")

            # Strip "ngspice 123 -> " prompt prefix(es).
            m = re.match(rb"(ngspice [0-9]+ -> )+(.*)$", l, flags=re.DOTALL)
            if m:
                l = m.group(2)

            # Check for our finish marker
            if l.rstrip() == b"FINISHED":
                logger.debug("Found FINISHED marker, breaking")
                break

            # Skip empty lines that are just prompts
            if l.strip() == b"":
                continue

            line = l.decode("ascii")
            out.append(line)
            logger.debug(f"Added to output: {repr(line)}")

            # Some parser errors trigger an interactive ngspice prompt, which
            # would otherwise hang this reader waiting for FINISHED forever.
            if l.endswith(b"Run Spice anyway? y/n ?\n"):
                self.p.stdin.write(b"n\n")
                self.p.stdin.flush()
                out_flat = "".join(out)
                raise NgspiceError(
                    "ngspice requested interactive input after netlist error:\n"
                    + out_flat)


        out_flat = "".join(out)
        logger.debug(f"Received result from ngspice ({self.p.pid}): {repr(out_flat)}")

        check_errors(out_flat)
        return out_flat

    def load_netlist(self, netlist: str, no_auto_gnd: bool = True):
        netlist_fn = self.cwd / "netlist.sp"
        netlist_fn.write_text(netlist)
        logger.debug(f"Written netlist: \n {netlist}")
        if no_auto_gnd:
            self.command("set no_auto_gnd")
        check_errors(self.command(f"source {netlist_fn}"))

    def op(self) -> SimArray:
        self.command("op")
        return self._write_raw()

    def _write_raw(self) -> SimArray:
        """Write current simulation plot to sim.raw.

        Uses explicit non-zero-length vector names to avoid ngspice refusing
        to write when zero-length vectors (e.g. from .option savecurrents)
        are present in the current plot.
        """
        valid = [v.name for v in self.vector_info() if v.length > 0]
        if not valid:
            raise NgspiceError("No simulation data: no non-zero-length vectors found")
        self.command("write sim.raw " + " ".join(valid))
        return parse_raw(self.cwd / "sim.raw")

    def tran(self, tstep: R, tstop: R, tstart: R = R(0), tmax: Optional[R] = None, uic: bool = False) -> SimArray:
        cmd = ['tran',
            R(tstep).compat_str(),
            R(tstop).compat_str(),
            R(tstart).compat_str()]
        if tmax is not None:
            cmd.append(R(tmax).compat_str())
        if uic:
            cmd.append('uic')
        self.command(' '.join(cmd))
        return self._write_raw()

    def ac(self, scheme: Literal["dec", "oct", "lin"], n: int, fstart: R, fstop: R) -> SimArray:
        """Runs Ngspice's 'ac' command for AC small-signal analysis."""
        if scheme not in ('dec', 'oct', 'lin'):
            raise TypeError("scheme must be 'dec', 'oct' or 'lin'.1`")
        self.command(" ".join([
            'ac',
            scheme,
            str(n),
            R(fstart).compat_str(),
            R(fstop).compat_str(),
            ]))
        return self._write_raw()

    def dc(self, source_name: str, vstart: R, vstop: R, vstep: R) -> SimArray:
        """Runs Ngspice's 'dc' command for a DC voltage sweep. For a
        single-point DC simulation, use the op() method (operating point)."""
        self.command(" ".join([
            'dc',
            source_name,
            R(vstart).compat_str(),
            R(vstop).compat_str(),
            R(vstep).compat_str(),
            ]))
        return self._write_raw()

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
                    yield NgspiceVector(name, dtype, int(length), rest)
