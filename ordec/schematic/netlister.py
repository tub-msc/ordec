# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..core import *

class Netlister:
    def __init__(self, directory: Directory, enable_savecurrents: bool = True, lvs: bool = False):
        self.directory = directory
        self.spice_cards = []
        self.cur_line = 0
        self.indent = 0
        self.netlist_setup_funcs = set()
        self.ngspice_setup_funcs = set()
        self.enable_savecurrents = enable_savecurrents
        self.lvs = lvs

    def name_obj(self, obj: Node, prefix: str = "") -> str:
        return self.directory.name_node(obj, prefix)

    def require_netlist_setup(self, func):
        self.netlist_setup_funcs.add(func)

    def require_ngspice_setup(self, func):
        """
        Register a function to be called during simulation setup.

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

    def name_hier_simobj(self, sn):
        c = sn
        if not isinstance(c, SimInstance):
            ret = [self.directory.name_node(sn.eref)]
        else:
            ret = []

        while not isinstance(c, SimHierarchy):
            if isinstance(c, SimInstance):
                ret.insert(0, self.directory.existing_name_node(c.eref))
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
            ret.append(self.name_obj(conn.here))
        return ret

    def netlist_schematic(self, s: Schematic):
        for net in s.all(Net):
            self.name_obj(net)

        subckt_dep = set()
        for inst in s.all(SchemInstance):
            try:
                f = inst.symbol.cell.netlist_ngspice
            except AttributeError:  # subckt
                pins = self.pinlist(inst.symbol)
                subckt_dep.add(inst.symbol)
                self.add(
                    self.name_obj(inst, prefix="x"),
                    self.portmap(inst, pins),
                    self.directory.name_subgraph(inst.symbol),
                )
            else:
                f(self, inst, s)
        return subckt_dep

    def netlist_hier(self, top: Schematic):
        """For testbenches, top-level is outside SPICE subckt."""
        if not isinstance(top, Schematic):
            raise TypeError(f"netlist_hier requires Schematic, not {type(top)}.")

        self.add(".title", self.directory.name_subgraph(top))
        if self.enable_savecurrents:
            self.add(".option", "savecurrents")
        subckt_dep = self.netlist_schematic(top)
        self.netlist_hier_deps(subckt_dep)
        self.add_setup()

    def netlist_hier_symbol(self, top: Symbol):
        """For LVS, top-level is just another SPICE subckt, no circuit outside a SPICE subckt."""

        if not isinstance(top, Symbol):
            raise TypeError(f"netlist_hier requires Symbol, not {type(top)}.")

        self.add(".title", self.directory.name_subgraph(top))
        self.netlist_hier_deps({top})
        self.add_setup()
         

    def add_setup(self):
        self.cur_line = 1
        for setup_func in self.netlist_setup_funcs:
            setup_func(self)

    def netlist_hier_deps(self, subckt_dep):
        subckt_done = set()
        while len(subckt_dep - subckt_done) > 0:
            symbol = next(iter(subckt_dep - subckt_done))
            schematic = symbol.cell.schematic
            self.add(
                ".subckt",
                self.directory.name_subgraph(symbol),
                [self.name_obj(pin) for pin in self.pinlist(symbol)],
            )
            self.indent += 4
            subckt_dep |= self.netlist_schematic(schematic)
            self.indent -= 4
            self.add(".ends", self.directory.name_subgraph(symbol))
            subckt_done.add(symbol)
