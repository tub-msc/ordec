# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass, fields
from typing import Literal

from ..core import *

@dataclass(frozen=True, kw_only=True)
class NgspiceOptions:
    """
    ngspice simulator options, each set field is written as ".option" line
    into the netlist. Unset fields (None, False) keep ngspice's defaults
    (given in parentheses where well-known, see the ngspice manual for the
    rest). Real-valued fields accept anything R accepts, e.g. "1e-12",
    1e-4 or R("1n").
    """
    temp: R|None = None #: Simulation temperature in degrees C (27).

    # Tolerances
    reltol: R|None = None #: Relative error tolerance (1e-3).
    abstol: R|None = None #: Absolute current error tolerance in A (1e-12).
    vntol: R|None = None #: Absolute voltage error tolerance in V (1e-6).
    chgtol: R|None = None #: Charge tolerance in C (1e-14).
    trtol: R|None = None #: Transient truncation error overestimation factor (7).

    # Convergence aids
    gmin: R|None = None #: Minimum conductance across device junctions in S (1e-12).
    gshunt: R|None = None #: Conductance from every node to ground in S.
    rshunt: R|None = None #: Resistance from every node to ground in ohm.
    cshunt: R|None = None #: Capacitance from every node to ground in F.
    itl1: int|None = None #: Operating point iteration limit (100).
    itl2: int|None = None #: DC sweep iteration limit per point (50).
    itl4: int|None = None #: Transient iteration limit per timepoint (10).
    gminsteps: int|None = None #: Number of gmin steps, 0 disables gmin stepping.
    gminfactor: R|None = None #: Factor per gmin step.
    srcsteps: int|None = None #: Number of source steps, 0 disables source stepping.
    noopiter: bool = False #: Go directly to gmin stepping for the operating point.
    nodedamping: bool = False #: Limit node voltage changes between iterations.
    absdv: R|None = None #: Maximum absolute node voltage change between iterations in V.
    reldv: R|None = None #: Maximum relative node voltage change between iterations.
    pivtol: R|None = None #: Minimum acceptable matrix pivot (1e-13).
    pivrel: R|None = None #: Minimum acceptable ratio of pivot to largest column entry (1e-3).

    # Transient analysis
    method: Literal["trap", "gear"]|None = None #: Integration method ("trap").
    maxord: int|None = None #: Maximum order of the integration method (2).
    xmu: R|None = None #: Damping coefficient of the trapezoidal method (0.5).
    newtrunc: bool = False #: Timestep control based on node voltages, see ltereltol etc.
    ltereltol: R|None = None #: Relative tolerance of newtrunc.
    lteabstol: R|None = None #: Absolute tolerance of newtrunc.
    ltetrtol: R|None = None #: Truncation error overestimation factor of newtrunc.
    minbreak: R|None = None #: Minimum time between breakpoints in s.
    ramptime: R|None = None #: Ramp all sources up from 0 during this time in s.

    # Miscellaneous
    solver: Literal["klu", "sparse"]|None = None #: Matrix solver.
    noopac: bool = False #: Skip the operating point in AC analysis of linear circuits.
    keepopinfo: bool = False #: Keep operating point information during small-signal analyses.
    seed: int|None = None #: Seed of the random number generator.

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None:
                continue
            if f.type == R|None:
                # frozen dataclass: bypass the frozen __setattr__.
                object.__setattr__(self, f.name, R(value))
            elif f.type == int|None:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise TypeError(f"NgspiceOptions.{f.name} must be int, got {value!r}.")
            elif f.type == bool:
                if not isinstance(value, bool):
                    raise TypeError(f"NgspiceOptions.{f.name} must be bool, got {value!r}.")
        # ngspice accepts the following out-of-range values without any
        # message, so they cannot be detected in its output:
        for name in ("reltol", "abstol", "itl4"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"NgspiceOptions.{name} must be positive, got {value!r}.")
        for name in ("gmin", "pivtol", "gminsteps", "ramptime"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"NgspiceOptions.{name} must be non-negative, got {value!r}.")
        if self.xmu is not None and not 0 <= self.xmu <= R("0.5"):
            raise ValueError(f"NgspiceOptions.xmu must be between 0 and 0.5, got {self.xmu!r}.")
        if self.temp is not None and self.temp < R("-273.15"):
            raise ValueError(f"NgspiceOptions.temp must be at least -273.15, got {self.temp!r}.")
        if self.method not in (None, "trap", "gear"):
            raise ValueError(f"Invalid NgspiceOptions.method {self.method!r}.")
        if self.solver not in (None, "klu", "sparse"):
            raise ValueError(f"Invalid NgspiceOptions.solver {self.solver!r}.")

    def cards(self) -> list[str]:
        """Returns the arguments of the ".option" lines, in field order."""
        ret = []
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None or value is False:
                continue
            if f.name == "solver":
                ret.append(value)
            elif value is True:
                ret.append(f.name)
            elif isinstance(value, R):
                ret.append(f"{f.name}={value.compat_str()}")
            else:
                ret.append(f"{f.name}={value}")
        return ret

class Netlister:
    def __init__(self, directory: Directory, enable_savecurrents: bool = True,
                 lvs: bool = False, corner=None, options: NgspiceOptions|None = None):
        self.directory = directory
        # Process corner, interpreted by the PDK's netlist setup function
        # (e.g. ihp130.Corner selects .lib sections); None = PDK's typical.
        self.corner = corner
        self.options = NgspiceOptions() if options is None else options
        self.spice_cards = []
        self.cur_line = 0
        self.indent = 0
        # Lists (not sets) to preserve insertion order so setup functions
        # with ordering dependencies run deterministically. Deduplicated on
        # insert in require_netlist_setup / require_ngspice_setup.
        self.netlist_setup_funcs = []
        self.ngspice_setup_funcs = []
        self.enable_savecurrents = enable_savecurrents
        self.lvs = lvs
        self.joined = {}

    def name_obj(self, obj: Node, prefix: str = "") -> str:
        return self.directory.name_node(obj, prefix)

    def name_net(self, net: Net) -> str:
        return self.name_obj(self.joined.get(net, net))

    def join_shorted_nets(self, schematic: Schematic, port_nets: set):
        for inst in schematic.all(SchemInstance):
            cell = inst.symbol.cell
            if not (isinstance(cell, SimLeafCell) and cell.lvs_shorted_pins()):
                continue
            nets = []
            for name in cell.lvs_shorted_pins():
                conn = inst.subgraph.one(SchemInstanceConn.ref_pin_idx.query((inst, getattr(inst.symbol, name))))
                net = self.joined.get(conn.here, conn.here)
                if net not in nets:
                    nets.append(net)
            ports = [net for net in nets if net in port_nets]
            if len(ports) > 1:
                raise ValueError("An instance shorts two ports, which an LVS netlist cannot write.")
            target = ports[0] if ports else nets[0]
            for net, joined in list(self.joined.items()):
                if joined in nets:
                    self.joined[net] = target
            for net in nets:
                if net != target:
                    self.joined[net] = target

    def name_sense(self, inst: SchemInstance, pin: Pin) -> str:
        """
        Names a 0 V voltage source that a leaf cell adds to sense the
        current into pin of inst. The simulator stores the branch current
        of this source as current of the pin (see sense_of_name).
        """
        conn = inst.subgraph.one(SchemInstanceConn.ref_pin_idx.query((inst, pin)))
        basename = f"v{Directory.basename_of_node(inst)}_sense"
        return self.directory.unique_name(basename, conn, conn.root)

    def require_netlist_setup(self, func):
        if func not in self.netlist_setup_funcs:
            self.netlist_setup_funcs.append(func)

    def require_ngspice_setup(self, func):
        """Register a function that returns ngspice setup commands.

        The function takes no arguments and returns a list of command
        strings. These are used for PDK-specific setup (e.g. loading
        OSDI models) that cannot go in the netlist.
        """
        if func not in self.ngspice_setup_funcs:
            self.ngspice_setup_funcs.append(func)

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

    def name_hier_simobj(self, simobj: SimInstance|SimNet) -> str:
        if not isinstance(simobj, (SimInstance, SimNet)):
            raise TypeError("Expected SimInstance or SimNet.")

        node = simobj
        ret = []
        while node is not None:
            if isinstance(node.eref, Pin):
                ret.insert(0, self.directory.name_node(node.eref))
            else:
                ret.insert(0, self.directory.existing_name_node(node.eref))
            node = node.parent_inst

        return ".".join(ret)

    def hier_simobj_of_name(self, simhier: SimHierarchy, name: str) -> SimInstance|SimNet:
        cur_schematic_or_symbol = simhier.schematic
        cur_parent_inst = None
        must_be_end = False
        for part in name.split("."):
            if must_be_end:
                raise ValueError("Another path component found after terminal SimNet.")
            node = self.directory.node_of_name(cur_schematic_or_symbol, part)
            if isinstance(node, SchemInstance):
                simnode = simhier.one(SimInstance.parent_eref_idx.query(
                    (cur_parent_inst, node)))
                cur_parent_inst = simnode
                cur_schematic_or_symbol = simhier.schematic_or_symbol_at(simnode)
            elif isinstance(node, (Net, Pin)):
                simnode = simhier.one(SimNet.parent_eref_idx.query(
                    (cur_parent_inst, node)))
                must_be_end = True
            else:
                assert False, f"Unexpected node returned from lookup: {node!r}"

        return simnode

    def sense_of_name(self, simhier: SimHierarchy, name: str) -> tuple[SimInstance, Pin]|None:
        """
        Returns the SimInstance and Pin whose current the source of the
        given hierarchical name senses (see name_sense), or None if name
        does not refer to a sense source.
        """
        parent, _, last = name.rpartition(".")
        try:
            parent_inst = self.hier_simobj_of_name(simhier, parent) if parent else None
            conn = self.directory.node_of_name(simhier.schematic_or_symbol_at(parent_inst), last)
        except KeyError:
            return None
        if not isinstance(conn, SchemInstanceConn):
            return None
        inst = simhier.one(SimInstance.parent_eref_idx.query((parent_inst, conn.ref)))
        return inst, conn.there

    def pinlist(self, sym: Symbol):
        return list(sym.all(Pin))

    def portmap(self, inst, pins):
        ret = []
        for pin in pins:
            conn = inst.subgraph.one(
                SchemInstanceConn.ref_pin_idx.query((inst, pin))
            )
            ret.append(self.name_net(conn.here))
        return ret

    def netlist_schematic(self, s: Schematic):
        for net in s.all(Net):
            self.name_net(net)

        subckt_dep = set()
        for inst in s.all(SchemInstance):
            cell = inst.symbol.cell
            if isinstance(cell, SimLeafCell):
                # In LVS, a shorting instance is only its joined nets.
                if not (self.lvs and cell.lvs_shorted_pins()):
                    cell.ngspice_netlist(self, inst)
            else:
                pins = self.pinlist(inst.symbol)
                subckt_dep.add(inst.symbol)
                self.add(
                    self.name_obj(inst, prefix="x"),
                    self.portmap(inst, pins),
                    self.directory.name_subgraph(inst.symbol),
                )
        return subckt_dep

    def netlist_hier(self, top: Schematic):
        """For testbenches, top-level is outside SPICE subckt."""
        if not isinstance(top, Schematic):
            raise TypeError(f"netlist_hier requires Schematic, not {type(top)}.")

        self.add(".title", self.directory.name_subgraph(top))
        if self.enable_savecurrents:
            self.add('.probe', 'alli') 
            self.add(".option", "savecurrents")
        for card in self.options.cards():
            self.add(".option", card)
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
            if self.lvs:
                self.join_shorted_nets(schematic,
                    {schematic.one(Net.pin_idx.query(pin)) for pin in self.pinlist(symbol)})
            self.add(
                ".subckt",
                self.directory.name_subgraph(symbol),
                # For the .subckt line, the internal net names are used rather
                # than the external pin names. This is needed to make sure the
                # connections work even when there is a mismatch between the
                # pin and net names. Moreover, the pin names might even be
                # assigned to something else within the Schematic context.
                [self.name_net(schematic.one(Net.pin_idx.query(pin)))
                    for pin in self.pinlist(symbol)]
            )
            self.indent += 4
            subckt_dep |= self.netlist_schematic(schematic)
            self.indent -= 4
            self.add(".ends", self.directory.name_subgraph(symbol))
            subckt_done.add(symbol)
