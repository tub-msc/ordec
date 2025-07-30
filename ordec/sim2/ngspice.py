# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from subprocess import Popen, PIPE, STDOUT
from typing import Iterator
from contextlib import contextmanager
import numpy as np
from collections import namedtuple
from pathlib import Path
import tempfile
import signal
import re
from ..core import *

NgspiceVector = namedtuple('NgspiceVector', ['name', 'quantity', 'dtype', 'rest'])
NgspiceValue = namedtuple('NgspiceValue', ['type', 'name', 'subname', 'value'])

class NgspiceError(Exception):
    pass

class NgspiceFatalError(NgspiceError):
    pass

def check_errors(ngspice_out):
    """Helper function to raise NgspiceError in Python from "Error: ..."
    messages in Ngspice's output."""
    for line in ngspice_out.split('\n'):
        m = re.match(r"Error:\s*(.*)", line)
        if m:
            raise NgspiceError(m.group(1))
class NgspiceTable:
    def __init__(self, name):
        self.name = name
        self.headers = []
        self.data = []

class NgspiceTransientResult:
    def __init__(self):
        self.time = []
        self.signals = {}
        self.tables = []  # Keep original tables for backward compatibility
        self.voltages = {}  # Node voltages
        self.currents = {}  # Device currents
        self.branches = {}  # Branch currents

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
            self.time = [float(row[time_idx]) for row in table.data if len(row) > time_idx]

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
                    except (ValueError, IndexError):
                        signal_data.append(0.0)

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
        """Allow backward compatibility with table indexing or signal access."""
        if isinstance(key, int):
            return self.tables[key]
        else:
            return self.get_signal(key)

    def __len__(self):
        """Return number of tables for backward compatibility."""
        return len(self.tables)

    def __iter__(self):
        """Allow iteration over tables for backward compatibility."""
        return iter(self.tables)

    def get_signal(self, signal_name):
        """Get signal data by name."""
        return self.signals.get(signal_name, [])

    def get_voltage(self, node_name):
        """Get voltage data for a node."""
        return self.voltages.get(node_name, [])

    def get_current(self, device_name, current_type='id'):
        """Get current data for a device (id, ig, is, ib)."""
        device_currents = self.currents.get(device_name, {})
        return device_currents.get(current_type, [])

    def get_branch_current(self, branch_name):
        """Get branch current data."""
        return self.branches.get(branch_name, [])

    def list_signals(self):
        """List all available signal names."""
        return list(self.signals.keys())

    def list_voltages(self):
        """List all available voltage node names."""
        return list(self.voltages.keys())

    def list_currents(self):
        """List all available device names with currents."""
        return list(self.currents.keys())

    def list_branches(self):
        """List all available branch current names."""
        return list(self.branches.keys())

    def plot_signals(self, *signal_names):
        """Helper method to get time and signal data for plotting."""
        result = {'time': self.time}
        for name in signal_names:
            result[name] = self.get_signal(name)
        return result

class Ngspice:
    @staticmethod
    @contextmanager
    def launch(debug=False):
        with tempfile.TemporaryDirectory() as cwd_str:
            p = Popen(['ngspice', '-p'], stdin=PIPE, stdout=PIPE, stderr=STDOUT, cwd=cwd_str)
            try:
                yield Ngspice(p, debug=debug, cwd=Path(cwd_str))
            finally:
                # SIGTERM was not needed for ngspice-39, but then needed for ngspice-44.
                # Possibly, this is due to different libedit/libreadline configurations, not due to the Ngspice version.
                p.send_signal(signal.SIGTERM)
                p.stdin.close()
                p.stdout.read()
                p.wait()

    def __init__(self, p, debug: bool, cwd: Path):
        self.p = p
        self.debug = debug
        self.cwd = cwd

    def command(self, command: str) -> str:
        """Executes ngspice command and returns string output from ngspice process."""
        if self.debug:
            print(f"[debug] sending command to ngspice ({self.p.pid}): {command}")
        self.p.stdin.write(f"{command}; echo FINISHED\n".encode("ascii"))
        self.p.stdin.flush()
        out = []
        while True:
            l=self.p.stdout.readline()
            #print(f"[debug] received line from ngspice: {l}")

            # Ignore echo in case of ngspice build with libreadline:
            if re.match(rb"ngspice [0-9]+ -> .*; echo FINISHED\n", l):
                continue

            # Strip "ngspice 123 -> " from line in case of ngspice build with neither libreadline nor libedit:
            m = re.match(rb"ngspice [0-9]+ -> (.*\n)", l)
            if m:
                l = m.group(1)

            if l == b'FINISHED\n':
                break
            elif l == b'': # readline() returns the empty byte string only on EOF.
                out_flat = "".join(out)
                raise NgspiceFatalError(f"ngspice terminated abnormally:\n{out_flat}")
            out.append(l.decode('ascii'))
        out_flat = "".join(out)
        if self.debug:
            print(f"[debug] received result from ngspice ({self.p.pid}): {repr(out_flat)}")
        return out_flat

    def vector_info(self) -> Iterator[NgspiceVector]:
        """Wrapper for ngspice's "display" command."""
        for line in self.command("display").split("\n\n")[2].split('\n'):
            if len(line) == 0:
                continue
            res = re.match(r"\s*([0-9a-zA-Z_.#]*)\s*:\s*([a-zA-Z]+),\s*([a-zA-Z]+),\s*(.*)", line)
            yield NgspiceVector(*res.groups())

    def load_netlist(self, netlist: str, no_auto_gnd:bool=True):
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
        print_all_res = self.command("print all")
        lines = print_all_res.split('\n')

        result = NgspiceTransientResult()
        i = 0

        while i < len(lines):
            line = lines[i]

            if len(line) == 0:
                i += 1
                continue

            # Look for NGspice table pattern:
            # Line i: Table title (non-empty, not dashes)
            # Line i+1: Optional description line
            # Line i+2: Separator (all dashes)
            # Line i+3: Headers
            # Line i+4: Separator (all dashes)
            # Line i+5+: Data rows until separator or end

            # Check if this could be start of a table
            if (not re.match(r"^-+$", line.strip()) and  # Not a separator line
                line.strip() and  # Not empty
                i + 4 < len(lines)):  # Enough lines ahead

                # Look for the pattern ahead
                desc_offset = 1

                # Check if next line is description or separator
                if re.match(r"^-+$", lines[i + 1].strip()):
                    # Next line is separator, no description
                    desc_offset = 0
                elif (i + 2 < len(lines) and
                      re.match(r"^-+$", lines[i + 2].strip())):
                    # Line after next is separator, so next line is description
                    desc_offset = 1
                else:
                    # Not a table pattern
                    i += 1
                    continue

                separator1_idx = i + 1 + desc_offset
                headers_idx = separator1_idx + 1
                separator2_idx = headers_idx + 1

                if (separator2_idx < len(lines) and
                    re.match(r"^-+$", lines[separator1_idx].strip()) and
                    re.match(r"^-+$", lines[separator2_idx].strip())):

                    table = NgspiceTable(line.strip())
                    table.headers = lines[headers_idx].split()

                    # Skip to data section
                    i = separator2_idx + 1

                    # Read data rows
                    while i < len(lines):
                        data_line = lines[i]
                        i += 1

                        # Check for table end
                        if (re.match(r"^-+$", data_line.strip()) or
                            data_line == '\x0c' or
                            not data_line.strip()):
                            break

                        # Add data row
                        table.data.append(data_line.split())

                    result.add_table(table)
                    continue

            # Not a table, move to next line
            i += 1

        return result


RawVariable = namedtuple('RawVariable', ['name', 'unit'])

def parse_raw(fn):
    info = {}
    info_vars = []

    with open(fn, 'rb') as f:
        for i in range(100):
            l = f.readline()[:-1].decode('ascii')

            if l.startswith('\t'):
                _, var_idx, var_name, var_unit = l.split('\t')
                assert int(var_idx) == len(info_vars)
                info_vars.append(RawVariable(var_name, var_unit))
            else:
                lhs, rhs = l.split(':', 1)
                info[lhs] = rhs.strip()
                if lhs == "Binary":
                    break
        #print(info)
        #print(info_vars)
        assert len(info_vars) == int(info['No. Variables'])
        no_points = int(info['No. Points'])

        dtype = np.dtype({
            "names": [v.name for v in info_vars],
            "formats": [np.float64]*len(info_vars)
            })

        np.set_printoptions(precision=5)

        data=np.fromfile(f, dtype=dtype, count=no_points)
    return data

def basename_escape(obj):
    if isinstance(obj, Cell):
        basename = f"{type(obj).__name__}_{'_'.join(obj.params_list())}"
    else:
        basename = "_".join(obj.full_path_list())
    return re.sub(r'[^a-zA-Z0-9]', '_', basename).lower()

class Netlister:
    def __init__(self):
        self.obj_of_name = {}
        self.name_of_obj = {}
        self.spice_cards = []
        self.cur_line = 0
        self.indent = 0
        self.setup_funcs = set()

    def require_setup(self, setup_func):
        self.setup_funcs.add(setup_func)

    def out(self):
        return "\n".join(self.spice_cards)+"\n.end\n"

    def add(self, *args):
        args_flat = []
        for arg in args:
            if isinstance(arg, list):
                args_flat += arg
            else:
                args_flat.append(arg)
        self.spice_cards.insert(self.cur_line, " "*self.indent + " ".join(args_flat))
        self.cur_line += 1

    def name_obj(self, obj, domain=None, prefix=""):
        try:
            return self.name_of_obj[obj]
        except KeyError:
            basename = prefix + basename_escape(obj)
            name = basename
            suffix = 0
            while (domain, name) in self.obj_of_name:
                name = f"{basename}{suffix}"
                suffix += 1
            self.obj_of_name[domain, name] = obj
            self.name_of_obj[obj] = name
            return name

    def name_hier_simobj(self, sn):
        c = sn
        if not isinstance(c, SimInstance):
            ret = [self.name_obj(sn.eref, sn.eref.subgraph)]
        else:
            ret = []

        while not isinstance(c, SimHierarchy):
            if isinstance(c, SimInstance):
                ret.insert(0, self.name_obj(c.eref, c.eref.subgraph))
            c = c.parent
        return ".".join(ret)

    def pinlist(self, sym: Symbol):
        return list(sym.all(Pin))

    def portmap(self, inst, pins):
        ret = []
        for pin in pins:
            conn = inst.subgraph.one(SchemInstanceConn.ref_pin_idx.query((inst.nid, pin.nid)))
            ret.append(self.name_of_obj[conn.here])
        return ret

    def netlist_schematic(self, s: Schematic):
        for net in s.all(Net):
            self.name_obj(net, s)

        subckt_dep = set()
        for inst in s.all(SchemInstance):
            try:
                f = inst.symbol.cell.netlist_ngspice
            except AttributeError: # subckt
                pins = self.pinlist(inst.symbol)
                subckt_dep.add(inst.symbol)
                self.add(self.name_obj(inst, s, prefix="x"), self.portmap(inst, pins), self.name_obj(inst.symbol.cell))
            else:
                f(self, inst, s)
        return subckt_dep

    def netlist_hier(self, top: Schematic):
        self.add('.title', self.name_obj(top.cell))
        #self.add('.probe', 'alli') # This seems to be needed to see currents of subcircuits
        self.add('.option', 'savecurrents') # This seems to be needed to see currents of devices (R, M)

        subckt_dep = self.netlist_schematic(top)
        subckt_done = set()
        while len(subckt_dep - subckt_done) > 0:
            symbol = next(iter(subckt_dep - subckt_done))
            schematic = symbol.cell.schematic
            self.add('.subckt', self.name_obj(symbol.cell), [self.name_obj(pin, symbol) for pin in self.pinlist(symbol)])
            self.indent += 4
            subckt_dep |= self.netlist_schematic(schematic)
            self.indent -= 4
            self.add(".ends", self.name_obj(symbol.cell))
            subckt_done.add(symbol)

        # Add model setup lines at top:
        self.cur_line = 1
        for setup_func in self.setup_funcs:
            setup_func(self)
