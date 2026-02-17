# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
import struct
from typing import NamedTuple
from abc import ABC, abstractmethod

from ..core.simarray import SimArray, SimArrayField, Quantity


def quantity_from_str(s: str, name: str = "") -> Quantity:
    """Determine Quantity from a rawfile variable unit string,
    with name-based fallback."""
    s = s.lower().strip()
    if s in ("time", "index"):
        return Quantity.TIME
    # "frequency grid=3" is how ngspice writes the frequency unit in AC rawfiles.
    if s.startswith("frequency") or s in ("hz", "hertz"):
        return Quantity.FREQUENCY
    if s in ("voltage", "v"):
        return Quantity.VOLTAGE
    if s in ("current", "i", "a"):
        return Quantity.CURRENT
    # Fall back to name-based heuristics
    if name.endswith("#branch") or (name.startswith("@") and "[" in name):
        return Quantity.CURRENT
    return Quantity.OTHER


class NgspiceScalar(NamedTuple):
    quantity: Quantity
    name: str
    subname: str
    value: float

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


def strip_raw_name(raw_name: str) -> str:
    """Normalize a rawfile variable name to the plain node/device name.

    ngspice wraps names in rawfiles: v(node) for voltages, i(device) for
    currents. The netlister and hierarchy lookup expect bare names.
    """
    if raw_name.startswith("v(") and raw_name.endswith(")"):
        return raw_name[2:-1]
    if raw_name.startswith("i(") and raw_name.endswith(")"):
        inner = raw_name[2:-1]
        if inner.startswith("@"):
            return inner  # device current: i(@r1[i]) -> @r1[i]
        return inner + "#branch"  # branch current: i(vi0) -> vi0#branch
    return raw_name


def parse_raw(fn) -> SimArray:
    """Parse a ngspice binary rawfile.

    Returns a SimArray whose fields carry name, dtype and quantity metadata.
    Real simulations (tran, op) yield float64 values; AC simulations yield
    complex128 values.
    """
    info = {}
    var_names = []
    var_quantities = []

    with open(fn, "rb") as f:
        for i in range(100):
            l = f.readline()[:-1].decode("ascii")

            if l.startswith("\t"):
                _, var_idx, var_name, var_unit = l.split("\t")
                assert int(var_idx) == len(var_names)
                var_names.append(var_name)
                var_quantities.append(quantity_from_str(var_unit, var_name))
            else:
                lhs, rhs = l.split(":", 1)
                info[lhs] = rhs.strip()
                if lhs == "Binary":
                    break
        assert len(var_names) == int(info["No. Variables"])
        no_points = int(info["No. Points"])

        # AC simulations store complex-valued vectors; transient/op use real.
        is_complex = "complex" in info.get("Flags", "").lower()
        dtype = 'c16' if is_complex else 'f8'

        fields = tuple(
            SimArrayField(name, dtype, qty)
            for name, qty in zip(var_names, var_quantities)
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
