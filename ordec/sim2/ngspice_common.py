# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
from collections import namedtuple

NgspiceValue = namedtuple('NgspiceValue', ['type', 'name', 'subname', 'value'])

class NgspiceError(Exception):
    pass

class NgspiceFatalError(NgspiceError):
    pass

class NgspiceConfigError(NgspiceError):
    """Raised when backend configuration fails."""
    pass

class NgspiceTable:
    def __init__(self, name):
        self.name = name
        self.headers = []
        self.data = []

class NgspiceTransientResult:
    def __init__(self):
        self.time = []
        self.signals = {}
        self.tables = []
        self.voltages = {}
        self.currents = {}
        self.branches = {}

    def add_table(self, table):
        """Add a table and extract signals into the signals dictionary."""
        self.tables.append(table)

        if not table.headers or not table.data:
            return

        # Find time column (usually index 1, but could be elsewhere)
        time_idx = None
        for i, header in enumerate(table.headers):
            if header.lower() == 'time':
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
            if header.lower() in ['index', 'time']:
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

            # Only add signal if we got valid data
            if signal_data:
                self.signals[signal_name] = signal_data
                # Categorize signals for easier access
                self._categorize_signal(signal_name, signal_data)

    def _categorize_signal(self, signal_name, signal_data):
        """Categorize signals into voltages, currents, and branches."""
        if signal_name.startswith('@') and '[' in signal_name:
            # Device current like "@m.xi0.mpd[id]"
            device_part = signal_name.split('[')[0][1:]  # Remove @ and get device part
            current_type = signal_name.split('[')[1].rstrip(']')  # Get current type
            if device_part not in self.currents:
                self.currents[device_part] = {}
            self.currents[device_part][current_type] = signal_data
        elif signal_name.endswith('#branch'):
            # Branch current like "vi3#branch"
            branch_name = signal_name.replace('#branch', '')
            self.branches[branch_name] = signal_data
        else:
            # Regular node voltage
            self.voltages[signal_name] = signal_data

    def __getitem__(self, key):
        """Allow table indexing or signal access."""
        if isinstance(key, int):
            return self.tables[key]
        else:
            return self.get_signal(key)

    def __len__(self):
        return len(self.tables)

    def __iter__(self):
        return iter(self.tables)

    def get_signal(self, signal_name):
        return self.signals.get(signal_name, [])

    def get_voltage(self, node_name):
        return self.voltages.get(node_name, [])

    def get_current(self, device_name, current_type='id'):
        device_currents = self.currents.get(device_name, {})
        return device_currents.get(current_type, [])

    def get_branch_current(self, branch_name):
        return self.branches.get(branch_name, [])

    def list_signals(self):
        return list(self.signals.keys())

    def list_voltages(self):
        return list(self.voltages.keys())

    def list_currents(self):
        return list(self.currents.keys())

    def list_branches(self):
        return list(self.branches.keys())

    def plot_signals(self, *signal_names):
        result = {'time': self.time}
        for name in signal_names:
            result[name] = self.get_signal(name)
        return result

class NgspiceAcResult:
    def __init__(self):
        self.freq = []
        self.voltages = {}
        self.currents = {}
        self.branches = {}

    def _categorize_signal(self, signal_name, signal_data):
        """Categorize signals into voltages, currents, and branches."""
        if signal_name.startswith('@') and '[' in signal_name:
            device_part = signal_name.split('[')[0][1:]
            current_type = signal_name.split('[')[1].rstrip(']')
            if device_part not in self.currents:
                self.currents[device_part] = {}
            self.currents[device_part][current_type] = signal_data
        elif signal_name.endswith('#branch'):
            branch_name = signal_name.replace('#branch', '')
            self.branches[branch_name] = signal_data
        else:
            self.voltages[signal_name] = signal_data

def check_errors(ngspice_out):
    """Helper function to raise NgspiceError in Python from "Error: ..."
    messages in Ngspice's output."""
    first_error_msg = None
    has_fatal_indicator = False

    for line in ngspice_out.split('\n'):
        if "no such vector" in line:
            # This error can occur when a simulation (like 'op') is run that doesn't
            # produce any plot output. It's not a fatal error, so we ignore it.
            continue
        # Handle both "Error: ..." and "stderr Error: ..." formats
        m = re.match(r"(?:stderr )?Error:\s*(.*)", line)
        if m and first_error_msg is None:
            first_error_msg = "Error: " + m.group(1)

        # Check if this line indicates a fatal error
        if "cannot recover" in line or "awaits to be reset" in line:
            has_fatal_indicator = True

    # Raise appropriate exception if we found an error
    if first_error_msg:
        if has_fatal_indicator:
            raise NgspiceFatalError(first_error_msg)
        else:
            raise NgspiceError(first_error_msg)
