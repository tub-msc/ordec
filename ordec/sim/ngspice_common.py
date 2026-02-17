# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
from collections import namedtuple
from enum import Enum
from dataclasses import dataclass
from typing import Dict
from abc import ABC, abstractmethod
import numpy as np

NgspiceValue = namedtuple("NgspiceValue", ["type", "name", "subname", "value"])
RawVariable = namedtuple("RawVariable", ["name", "unit"])

class NgspiceBase(ABC):
    @classmethod
    @abstractmethod
    def launch(cls, debug: bool):
        pass

    # More abstractmethod could be added here to document (and minimally
    # enforce) the interface compatilibity between different NgspiceBase
    # subclasses.

class SignalKind(Enum):
    TIME = (1, "time")
    FREQUENCY = (2, "frequency")
    VOLTAGE = (3, "voltage")
    CURRENT = (4, "current")
    OTHER = (99, "other")

    def __init__(self, vtype_value: int, description: str):
        self.vtype_value = vtype_value
        self.description = description


@dataclass
class SignalArray:
    kind: SignalKind
    values: list


class NgspiceError(Exception):
    pass


class NgspiceFatalError(NgspiceError):
    pass


class NgspiceTable:
    def __init__(self, name):
        self.name = name
        self.headers = []
        self.data = []


class NgspiceResultBase:
    def __init__(self):
        # Map signal name -> SignalArray
        self.signals: Dict[str, SignalArray] = {}

    def categorize_signal(self, signal_name) -> SignalKind:
        if not signal_name:
            return SignalKind.OTHER
        if signal_name.startswith("@") and "[" in signal_name:
            return SignalKind.CURRENT
        if signal_name.endswith("#branch"):
            return SignalKind.CURRENT
        # Treat as node voltage
        return SignalKind.VOLTAGE

    def __getitem__(self, key):
        """Allow signal access."""
        return self.get_signal(key)

    def get_signal(self, signal_name):
        return self.signals.get(signal_name, [])

    def list_signals(self):
        return list(self.signals.keys())


class NgspiceTransientResult(NgspiceResultBase):
    def __init__(self):
        super().__init__()
        self.time: list = []
        self.tables: list = []

    def add_table(self, table):
        """Add a table and extract signals into the signals dictionary."""
        self.tables.append(table)

        if not table.headers or not table.data:
            return

        # Find time column (usually index 1, but could be elsewhere)
        time_idx = None
        for i, header in enumerate(table.headers):
            if header.lower() == "time":
                time_idx = i
                break

        if time_idx is None:
            return

        # Extract time data if we don't have it yet
        if not self.time and table.data:
            # Filter out any rows that might contain header strings
            valid_time_data = []
            for row in table.data:
                if len(row) > time_idx:
                    try:
                        time_val = float(row[time_idx])
                        valid_time_data.append(time_val)
                    except (ValueError, TypeError):
                        # Skip rows that can't be converted to float (likely headers)
                        continue
            self.time = valid_time_data

        # Extract signal data
        for i, header in enumerate(table.headers):
            if header.lower() in ["index", "time"]:
                continue

            signal_name = header
            signal_data = []

            for row in table.data:
                if len(row) > i:
                    try:
                        signal_data.append(float(row[i]))
                    except (ValueError, TypeError, IndexError):
                        # Skip rows that can't be converted to float or are malformed
                        continue

            if signal_data:
                kind = self.categorize_signal(signal_name)
                self.signals[signal_name] = SignalArray(kind=kind, values=signal_data)

    def categorize_signal(self, signal_name) -> SignalKind:
        if not signal_name:
            return SignalKind.OTHER
        name = signal_name.lower()
        if name in ("time", "index"):
            return SignalKind.TIME
        return super().categorize_signal(signal_name)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self.tables[key]
        else:
            return self.get_signal(key)

    def __len__(self):
        return len(self.tables)

    def __iter__(self):
        return iter(self.tables)

    def plot_signals(self, *signal_names):
        result = {"time": self.time}
        for name in signal_names:
            result[name] = self.get_signal(name)
        return result


class NgspiceAcResult(NgspiceResultBase):
    def __init__(self):
        super().__init__()
        self.freq = []

    def categorize_signal(self, signal_name) -> SignalKind:
        if not signal_name:
            return SignalKind.OTHER
        name = signal_name.lower()
        if name in ("frequency", "freq"):
            return SignalKind.FREQUENCY
        return super().categorize_signal(signal_name)

    def plot_signals(self, *signal_names):
        result = {"frequency": self.freq}
        for name in signal_names:
            result[name] = self.get_signal(name)
        return result


def check_errors(ngspice_out):
    """Helper function to raise NgspiceError in Python from "Error: ..."
    messages in Ngspice's output."""
    first_error_msg = None
    has_fatal_indicator = False

    for line in ngspice_out.split("\n"):
        if "no such vector" in line:
            # This error can occur when a simulation (like 'op') is run that doesn't
            # produce any plot output. It's not a fatal error, so we ignore it.
            continue
        # Handle both "Error: ..." and "stderr Error: ..." formats
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


def signal_kind_from_unit(unit: str, name: str = "") -> "SignalKind":
    """Determine SignalKind from a rawfile variable unit string,
    with name-based fallback heuristics."""
    unit_lower = unit.lower().strip()
    if unit_lower in ("time", "index"):
        return SignalKind.TIME
    # "frequency grid=3" is how ngspice writes the frequency unit in AC rawfiles.
    if unit_lower.startswith("frequency") or unit_lower in ("hz", "hertz"):
        return SignalKind.FREQUENCY
    if unit_lower in ("voltage", "v"):
        return SignalKind.VOLTAGE
    if unit_lower in ("current", "i", "a"):
        return SignalKind.CURRENT
    # Fall back to name-based heuristics
    if name.endswith("#branch") or (name.startswith("@") and "[" in name):
        return SignalKind.CURRENT
    return SignalKind.OTHER


def parse_raw(fn):
    """Parse a ngspice binary rawfile.

    Returns (data, info_vars) where data is a numpy structured array
    and info_vars is a list of RawVariable namedtuples with .name and .unit.
    Real simulations (tran, op) yield float64 values; AC simulations yield
    complex128 values.
    """
    info = {}
    info_vars = []

    with open(fn, "rb") as f:
        for i in range(100):
            l = f.readline()[:-1].decode("ascii")

            if l.startswith("\t"):
                _, var_idx, var_name, var_unit = l.split("\t")
                assert int(var_idx) == len(info_vars)
                info_vars.append(RawVariable(var_name, var_unit))
            else:
                lhs, rhs = l.split(":", 1)
                info[lhs] = rhs.strip()
                if lhs == "Binary":
                    break
        assert len(info_vars) == int(info["No. Variables"])
        no_points = int(info["No. Points"])

        # AC simulations store complex-valued vectors; transient/op use real.
        is_complex = "complex" in info.get("Flags", "").lower()
        scalar_type = np.complex128 if is_complex else np.float64

        dtype = np.dtype(
            {
                "names": [v.name for v in info_vars],
                "formats": [scalar_type] * len(info_vars),
            }
        )

        data = np.fromfile(f, dtype=dtype, count=no_points)
    return data, info_vars
