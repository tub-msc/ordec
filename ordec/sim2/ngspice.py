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
from ordec import Cell, Vec2R, Rect4R, Pin, Symbol, Schematic, PinType, Rational as R, SchemPoly, SchemArc, SchemRect, SchemInstance, SchemPort, Net, Orientation, SchemConnPoint, SchemTapPoint, PathArray, PathStruct, generate, lib, helpers, SimNet, SimHierarchy, SimInstance

NgspiceVector = namedtuple('NgspiceVector', ['name', 'quantity', 'dtype', 'rest'])
NgspiceValue = namedtuple('NgspiceValue', ['name', 'value'])

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
        if no_auto_gnd:
            self.command("set no_auto_gnd")
        check_errors(self.command(f"source {netlist_fn}"))

    def op(self) -> Iterator[NgspiceValue]:
        self.command("op")
        for line in self.command("print all").split('\n'):
            if len(line) == 0:
                continue
            res = re.match(r"([0-9a-zA-Z_.#]*)\s*=\s*([0-9.\-+e]+)\s*", line)
            yield NgspiceValue(res.group(1), float(res.group(2)))

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
        basename = "_".join(obj.path()[2:])
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
    
    def name_simnet(self, sn):
        ret = [self.name_obj(sn.ref, sn.ref.root_view)]
        node = sn
        while not isinstance(node, SimHierarchy):
            if isinstance(node, SimInstance):
                ret.insert(0, self.name_obj(node.ref, node.ref.root_view))
            node = node.parent
        return ".".join(ret)

    def pinlist(self, sym: Symbol):
        return list(sym.traverse(Pin))

    def portmap(self, inst, pins):
        return [self.name_of_obj[inst.portmap[pin]] for pin in pins]

    def netlist_schematic(self, s: Schematic):    
        for net in s.traverse(Net):
            self.name_obj(net, s)
        
        subckt_dep = set()
        for inst in s.traverse(SchemInstance):
            try:
                f = inst.ref.parent.netlist_ngspice
            except AttributeError: # subckt
                pins = self.pinlist(inst.ref)
                subckt_dep.add(inst.ref)
                self.add(self.name_obj(inst, s, prefix="x"), self.portmap(inst, pins), self.name_obj(inst.ref.parent))
            else:
                f(self, inst, s)
        return subckt_dep

    def netlist_hier(self, top: Schematic):
        self.add('.title', self.name_obj(top.parent))
        #self.add('.probe', 'alli')
        #self.add('.option', 'savecurrents')

        subckt_dep = self.netlist_schematic(top)
        subckt_done = set()
        while len(subckt_dep - subckt_done) > 0:
            symbol = next(iter(subckt_dep - subckt_done))
            schematic = symbol.parent.schematic
            self.add('.subckt', self.name_obj(symbol.parent), [self.name_obj(pin, symbol) for pin in self.pinlist(symbol)])
            self.indent += 4
            subckt_dep |= self.netlist_schematic(schematic)
            self.indent -= 4
            self.add(".ends", self.name_obj(symbol.parent))
            subckt_done.add(symbol)

        # Add model setup lines at top:
        self.cur_line = 1
        for setup_func in self.setup_funcs:
            setup_func(self)