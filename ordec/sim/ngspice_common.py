# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
import struct
from abc import ABC, abstractmethod

from ..core.simarray import SimArray, SimArrayField


class NgspiceBase(ABC):
    @classmethod
    @abstractmethod
    def launch(cls, debug: bool):
        pass


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
      Convert an ngspice print-style signal name to rawfile-style.

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


def parse_signal_name(name):
    """Parse a rawfile-style ngspice signal name into (node_name, subname).

    Returns (node_name, subname) where subname is None for voltage nodes,
    or a string like "branch" / "is" for currents and device parameters.

    Use name_print_to_raw() first to convert print-style names.

    Examples:
        v(a)                -> ("a", None)
        i(vgnd)             -> ("vgnd", "branch")
        i(@m.xdut.mm2[is]) -> ("xdut.mm2", "is")
        @m.xdut.mm2[is]    -> ("xdut.mm2", "is")
    """
    def strip_type_prefix(s):
        """Strip single-letter SPICE device type prefix (e.g. 'm.' for
        MOSFET, 'r.' for resistor) if present."""
        if len(s) > 2 and s[1] == '.' and s[0].isalpha():
            return s[2:]
        return s

    if name.startswith("v(") and name.endswith(")"):
        return (name[2:-1], None)
    if name.startswith("i(") and name.endswith(")"):
        inner = name[2:-1]
        if inner.startswith("@") and "[" in inner:
            bracket = inner.index("[")
            return (strip_type_prefix(inner[1:bracket]),
                    inner[bracket+1:-1])
        return (inner, "branch")
    if name.startswith("@") and "[" in name:
        bracket = name.index("[")
        return (strip_type_prefix(name[1:bracket]),
                name[bracket+1:-1])
    return (name, None)


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
                if len(parts) != 4:
                    raise ValueError(f"Malformed variable line in rawfile: {l!r}")
                _, var_idx, var_name, var_unit = parts
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
