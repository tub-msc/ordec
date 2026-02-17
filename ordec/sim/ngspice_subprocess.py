# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
import signal
import sys
import shutil
import tempfile
import logging
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from subprocess import Popen, PIPE, STDOUT
from typing import Iterator, Optional

from ..core.rational import Rational as R

logger = logging.getLogger(__name__)

from .ngspice_common import (
    NgspiceValue,
    NgspiceError,
    NgspiceFatalError,
    check_errors,
    NgspiceBase,
    parse_raw,
)
from ..core.simarray import SimArray

NgspiceVector = namedtuple(
    "NgspiceVector", ["name", "quantity", "dtype", "length", "rest"]
)


class NgspiceSubprocess(NgspiceBase):
    @classmethod
    @contextmanager
    def launch(cls):
        # Choose the correct ngspice executable for the platform
        if sys.platform == "win32" and shutil.which("ngspice_con"):
            # On Windows, prefer ngspice_con if available, fall back to ngspice
            ngspice_exe = "ngspice_con"
        else:
            ngspice_exe = "ngspice"

        logger.debug(f"Using ngspice executable: {ngspice_exe}")

        with tempfile.TemporaryDirectory() as cwd_str:
            p: Popen[bytes] = Popen(
                [ngspice_exe, "-p"], stdin=PIPE, stdout=PIPE, stderr=STDOUT, cwd=cwd_str
            )
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

    def __init__(self, p: Popen, cwd: Path):
        self.p: Popen[bytes] = p
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

        if self.p.stdin:
            # Send the command followed by echo marker on separate lines
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

            # Strip ALL occurrences of "ngspice 123 -> " from the line on all platforms
            # Preserve newlines when stripping prompts
            while True:
                m = re.match(rb"ngspice [0-9]+ -> (.*)", l)
                if not m:
                    break
                logger.debug(f"Stripping prompt from line: {repr(l)} -> {repr(m.group(1))}")
                stripped_content = m.group(1)
                # Preserve the newline if the original line had one
                if l.endswith(b"\n") and not stripped_content.endswith(b"\n"):
                    l = stripped_content + b"\n"
                else:
                    l = stripped_content

            # Check for our finish marker
            if l.rstrip() == b"FINISHED":
                logger.debug("Found FINISHED marker, breaking")
                break

            # Skip empty lines that are just prompts
            if l.strip() == b"":
                continue

            out.append(l.decode("ascii"))
            logger.debug(f"Added to output: {repr(l.decode('ascii'))}")

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

    def _write_raw(self):
        """Write current simulation plot to sim.raw.

        Uses explicit non-zero-length vector names to avoid ngspice refusing
        to write when zero-length vectors (e.g. from .option savecurrents)
        are present in the current plot.

        Returns (data, info_vars) from parse_raw().
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
        sim_array, info_vars = self._write_raw()
        return sim_array, info_vars

    def ac(self, *args):
        self.command(f"ac {' '.join(args)}")
        sim_array, info_vars = self._write_raw()
        return sim_array, info_vars

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
