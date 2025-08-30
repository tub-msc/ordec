# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
import signal
import sys
import tempfile
import shutil
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from subprocess import Popen, PIPE, STDOUT
from typing import Iterator, Optional

import numpy as np

from .ngspice_common import (
    NgspiceValue,
    NgspiceFatalError,
    NgspiceTransientResult,
    NgspiceAcResult,
    check_errors,
    NgspiceTable,
)

NgspiceVector = namedtuple('NgspiceVector', ['name', 'quantity', 'dtype', 'length', 'rest'])

class _SubprocessBackend:
    @staticmethod
    @contextmanager
    def launch(debug=False):
        # Choose the correct ngspice executable for the platform
        if sys.platform == 'win32':
            # On Windows, prefer ngspice_con if available, fall back to ngspice
            ngspice_exe = 'ngspice_con' if shutil.which('ngspice_con') else 'ngspice'
        else:
            ngspice_exe = 'ngspice'

        if debug:
            print(f"[debug] Using ngspice executable: {ngspice_exe}")
            print(f"[debug] Platform: {sys.platform}")

        with tempfile.TemporaryDirectory() as cwd_str:
            if debug:
                print(f"[debug] Starting ngspice with command: {[ngspice_exe, '-p']}")
                print(f"[debug] Working directory: {cwd_str}")

            p = Popen([ngspice_exe, '-p'], stdin=PIPE, stdout=PIPE, stderr=STDOUT, cwd=cwd_str)
            if debug:
                print(f"[debug] Process started with PID: {p.pid}")

            try:
                yield _SubprocessBackend(p, debug=debug, cwd=Path(cwd_str))
            finally:
                if debug:
                    print(f"[debug] Cleaning up process {p.pid}")
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
        self.p = p
        self.debug = debug
        self.cwd = cwd

    def command(self, command: str) -> str:
        """Executes ngspice command and returns string output from ngspice process."""
        if self.p.poll() is not None:
            raise NgspiceFatalError("ngspice process has terminated unexpectedly.")
        if self.debug:
            print(f"[debug] sending command to ngspice ({self.p.pid}): {command}")

        if self.p.stdin:
            # Send the command followed by echo marker on separate lines
            full_input = f"{command}\necho FINISHED\n"
            if self.debug:
                print(f"[debug] Writing to stdin: {repr(full_input)}")
            self.p.stdin.write(full_input.encode("ascii"))
            self.p.stdin.flush()
            if self.debug:
                print(f"[debug] Stdin flushed")

        out = []
        line_count = 0
        while True:
            if self.debug:
                print(f"[debug] Waiting for line {line_count}...")
            l = self.p.stdout.readline()
            line_count += 1
            if self.debug:
                print(f"[debug] received line {line_count} from ngspice: {repr(l)}")

            # Check for EOF first
            if l == b'': # readline() returns the empty byte string only on EOF.
                out_flat = "".join(out)
                if self.debug:
                    print(f"[debug] EOF detected, ngspice terminated")
                raise NgspiceFatalError(f"ngspice terminated abnormally:\n{out_flat}")

            # Strip ALL occurrences of "ngspice 123 -> " from the line on all platforms
            # Preserve newlines when stripping prompts
            while True:
                m = re.match(rb"ngspice [0-9]+ -> (.*)", l)
                if not m:
                    break
                if self.debug:
                    print(f"[debug] Stripping prompt from line: {repr(l)} -> {repr(m.group(1))}")
                stripped_content = m.group(1)
                # Preserve the newline if the original line had one
                if l.endswith(b'\n') and not stripped_content.endswith(b'\n'):
                    l = stripped_content + b'\n'
                else:
                    l = stripped_content

            # Check for our finish marker
            if l.rstrip() == b'FINISHED':
                if self.debug:
                    print(f"[debug] Found FINISHED marker, breaking")
                break

            # Skip empty lines that are just prompts
            if l.strip() == b'':
                continue

            out.append(l.decode('ascii'))
            if self.debug:
                print(f"[debug] Added to output: {repr(l.decode('ascii'))}")

        out_flat = "".join(out)
        if self.debug:
            print(f"[debug] received result from ngspice ({self.p.pid}): {repr(out_flat)}")

        check_errors(out_flat)
        return out_flat

    def load_netlist(self, netlist: str, no_auto_gnd: bool = True):
        netlist_fn = self.cwd / 'netlist.sp'
        netlist_fn.write_text(netlist)
        if self.debug:
            print(f"Written netlist: \n {netlist}")
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
            # Fallback: get list of available vectors and print only valid ones
            display_output = self.command("display")

            # Parse vector list and print only vectors with length > 0
            for line in display_output.split('\n'):
                # Look for vector definitions like "name: type, real, N long"
                vector_match = re.match(r'\s*([^:]+):\s*[^,]+,\s*[^,]+,\s*([0-9]+)\s+long', line)
                if vector_match:
                    vector_name = vector_match.group(1).strip()
                    vector_length = int(vector_match.group(2))

                    # Only print vectors that have data (length > 0)
                    if vector_length > 0:
                        yield self.command(f"print {vector_name}")
        else:
            yield from print_all_res.split('\n')

    def op(self) -> Iterator[NgspiceValue]:
        self.command("op")

        for line in self.print_all():
            if len(line) == 0:
                continue

            # Voltage result - updated regex to handle device names with special chars:
            res = re.match(r"([0-9a-zA-Z_.#]+)\s*=\s*([0-9.\-+e]+)\s*", line)
            if res:
                yield NgspiceValue(type='voltage', name=res.group(1), subname=None, value=float(res.group(2)))

            # Current result like "vgnd#branch":
            res = re.match(r"([0-9a-zA-Z_.#]+)#branch\s*=\s*([0-9.\-+e]+)\s*", line)
            if res:
                yield NgspiceValue(type='current', name=res.group(1), subname='branch', value=float(res.group(2)))

            # Current result like "@m.xdut.mm2[is]" from savecurrents:
            res = re.match(r"@([a-zA-Z]\.)?([0-9a-zA-Z_.#]+)\[([0-9a-zA-Z_]+)\]\s*=\s*([0-9.\-+e]+)\s*", line)
            if res:
                yield NgspiceValue(type='current', name=res.group(2), subname=res.group(3), value=float(res.group(4)))

    def tran(self, *args) -> NgspiceTransientResult:
        self.command(f"tran {' '.join(args)}")
        print_all_res = "\n".join(self.print_all())
        lines = print_all_res.split('\n')

        result = NgspiceTransientResult()
        tables = {} # map from header tuple to list of data rows
        current_headers = None

        for line in lines:
            line = line.strip()
            if not line or re.match(r"^-+$", line) or "Transient Analysis" in line:
                continue

            potential_headers = line.split()
            is_header = ('time' in [h.lower() for h in potential_headers] or 'index' in [h.lower() for h in potential_headers]) and not self._is_numeric_row(potential_headers)

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

        return result

    def _is_header_line(self, line, expected_headers):
        """Check if a line looks like a header line."""
        if not line.strip():
            return False

        # Check if line contains column names from the expected headers
        line_lower = line.lower()
        header_matches = 0
        for header in expected_headers:
            if header.lower() in line_lower:
                header_matches += 1

        # If most headers are found in this line, it's likely a header
        return header_matches >= len(expected_headers) * 0.6

    def _parse_ac_wrdata(self, file_path: str, vectors: list[str]) -> 'NgspiceAcResult':
        """Parses the ASCII output of a wrdata command for AC analysis."""
        result = NgspiceAcResult()

        # Use numpy to load the text file, which is much more robust
        try:
            data = np.loadtxt(file_path)
        except (IOError, ValueError):
            # Return an empty result if the file is empty or malformed
            return result

        if data.ndim == 1:
            # Handle case with only one row of data by reshaping it
            data = data.reshape(1, -1)

        if data.shape[0] == 0:
            return result

        # The `wrdata` command repeats the scale (frequency) for each vector.
        # The first column is the definitive frequency scale.
        result.freq = tuple(data[:, 0])

        # Subsequent columns are grouped in threes: freq, real, imag.
        for i, vec_name in enumerate(vectors):
            # The block for vector `i` starts at column i*3
            real_col_idx = i * 3 + 1
            imag_col_idx = i * 3 + 2

            if data.shape[1] > imag_col_idx:
                real_parts = data[:, real_col_idx]
                imag_parts = data[:, imag_col_idx]

                complex_data = [complex(r, i) for r, i in zip(real_parts, imag_parts)]
                result._categorize_signal(vec_name, complex_data)

        return result

    def ac(self, *args, wrdata_file: Optional[str] = None) -> 'NgspiceAcResult':
        self.command(f"ac {' '.join(args)}")

        if wrdata_file is None:
            # Original logic using print all
            print_all_res = "".join(self.print_all())
            result = NgspiceAcResult()

            sections = re.split(r'AC Analysis\s+.*\n\s*-{60,}', print_all_res)

            for section in sections:
                if not section.strip():
                    continue

                lines = section.strip().split('\n')
                header_line = lines[0]
                data_lines = lines[1:]

                headers = header_line.split()
                if len(headers) < 2:
                    continue

                vector_name = headers[-1]

                if 'frequency' in headers:
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

                result._categorize_signal(vector_name, signal_data)

            result.freq = tuple(result.freq)
            return result
        else:
            # New logic using wrdata
            vectors_to_write = [v.name for v in self.vector_info() if v.name != 'frequency' and v.length > 0]
            if not vectors_to_write:
                return NgspiceAcResult() # Return empty result if no vectors

            # Quote vector names to handle special characters
            vectors_quoted = [f'"{v}"' for v in vectors_to_write]
            self.command(f"wrdata {wrdata_file} {' '.join(vectors_quoted)}")
            return self._parse_ac_wrdata(wrdata_file, vectors_to_write)

    def vector_info(self) -> Iterator[NgspiceVector]:
        """Wrapper for ngspice's "display" command."""
        display_output = self.command("display")
        lines = display_output.split('\n')

        in_vectors_section = False
        for line in lines:
            if 'Here are the vectors currently active:' in line:
                in_vectors_section = True
                continue

            if in_vectors_section:
                if len(line) == 0 or line.startswith('Title:') or line.startswith('Name:') or line.startswith('Date:'):
                    continue
                res = re.match(r"\s*([0-9a-zA-Z_.#@\[\]]*)\s*:\s*([a-zA-Z]+),\s*([a-zA-Z]+),\s*([0-9]+) long(.*)", line)
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
