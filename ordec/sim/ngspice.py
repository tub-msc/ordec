# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
from collections import namedtuple
from contextlib import contextmanager
from enum import Enum
from typing import Iterator, Optional, Callable, Generator

import numpy as np

from ..core import *
from .ngspice_ffi import NgspiceFFI
from .ngspice_subprocess import NgspiceSubprocess
from .ngspice_mp import NgspiceIsolatedFFI

class NgspiceBackend(Enum):
    """Available NgSpice backend types."""

    SUBPROCESS = "subprocess"
    FFI = "ffi"
    MP = "mp"


class Ngspice:
    @staticmethod
    def launch(debug: bool=False, backend: NgspiceBackend = NgspiceBackend.SUBPROCESS):
        if isinstance(backend, str):
            backend = NgspiceBackend(backend.lower())

        if debug:
            print(f"[Ngspice] Using backend: {backend.value}")

        backend_class = {
            NgspiceBackend.FFI: NgspiceFFI,
            NgspiceBackend.SUBPROCESS: NgspiceSubprocess,
            NgspiceBackend.MP: NgspiceIsolatedFFI,
        }[backend]

        return backend_class.launch(debug=debug)

    def __init__(self):
        raise TypeError("Please call Ngspice.launch(), instantiation of Ngspice is not supported!")


RawVariable = namedtuple("RawVariable", ["name", "unit"])

def parse_raw(fn):
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

        dtype = np.dtype(
            {
                "names": [v.name for v in info_vars],
                "formats": [np.float64] * len(info_vars),
            }
        )

        np.set_printoptions(precision=5)

        data = np.fromfile(f, dtype=dtype, count=no_points)
    return data


def basename_escape(obj):
    if isinstance(obj, Cell):
        return obj.escaped_name().lower()
    else:
        basename = "_".join(obj.full_path_list())
        return re.sub(r"[^a-zA-Z0-9]", "_", basename).lower()


class Netlister:
    def __init__(self, enable_savecurrents: bool = True):
        self.obj_of_name = {}
        self.name_of_obj = {}
        self.spice_cards = []
        self.cur_line = 0
        self.indent = 0
        self.netlist_setup_funcs = set()
        self.ngspice_setup_funcs = set()
        self.enable_savecurrents = enable_savecurrents

    def require_netlist_setup(self, func):
        self.netlist_setup_funcs.add(func)

    def require_ngspice_setup(self, func):
        """Register a function to be called during simulation setup.

        The function should accept a single argument: the Ngspice instance.
        This is useful for PDK-specific setup commands that need to be
        executed on the simulator instance rather than in the netlist.
        """
        self.ngspice_setup_funcs.add(func)

    def out(self):
        return "\n".join(self.spice_cards) + "\n.end\n"

    def add(self, *args):
        args_flat = []
        for arg in args:
            if isinstance(arg, list):
                args_flat += arg
            else:
                args_flat.append(arg)
        self.spice_cards.insert(self.cur_line, " " * self.indent + " ".join(args_flat))
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
            conn = inst.subgraph.one(
                SchemInstanceConn.ref_pin_idx.query((inst.nid, pin.nid))
            )
            ret.append(self.name_of_obj[conn.here])
        return ret

    def netlist_schematic(self, s: Schematic):
        for net in s.all(Net):
            self.name_obj(net, s)

        subckt_dep = set()
        for inst in s.all(SchemInstance):
            try:
                f = inst.symbol.cell.netlist_ngspice
            except AttributeError:  # subckt
                pins = self.pinlist(inst.symbol)
                subckt_dep.add(inst.symbol)
                self.add(
                    self.name_obj(inst, s, prefix="x"),
                    self.portmap(inst, pins),
                    self.name_obj(inst.symbol.cell),
                )
            else:
                f(self, inst, s)
        return subckt_dep

    def netlist_hier(self, top: Schematic):
        self.add(".title", self.name_obj(top.cell))
        if self.enable_savecurrents:
            self.add(".option", "savecurrents")

        subckt_dep = self.netlist_schematic(top)
        subckt_done = set()
        while len(subckt_dep - subckt_done) > 0:
            symbol = next(iter(subckt_dep - subckt_done))
            schematic = symbol.cell.schematic
            self.add(
                ".subckt",
                self.name_obj(symbol.cell),
                [self.name_obj(pin, symbol) for pin in self.pinlist(symbol)],
            )
            self.indent += 4
            subckt_dep |= self.netlist_schematic(schematic)
            self.indent -= 4
            self.add(".ends", self.name_obj(symbol.cell))
            subckt_done.add(symbol)

        self.cur_line = 1
        for setup_func in self.netlist_setup_funcs:
            setup_func(self)
