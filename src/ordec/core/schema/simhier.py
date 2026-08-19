# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from enum import Enum
from typing import Optional
from public import public

from ..ordb import *
from ..cell import Cell
from ..context import SimulationViewBuilder
from ..simarray import Quantity, SimColumn
from .schematic import Symbol, Schematic, Pin, Net, SchemPort, SchemInstance

WIRE_DOMAIN = 5 << 16

@public
class SimType(Enum):
    OP = 'op'
    TRAN = 'tran'
    AC = 'ac'
    DCSWEEP = 'dcsweep'

def parent_siminstance(c: Node) -> Node:
    while not isinstance(c, (SimInstance, SimHierarchy)):
        c = c.parent
    return c


class SimHierarchySubcursor(tuple):
    """
    Cursor to intuitively traverse Schematics and Symbols in a SimHierarchy.

    This is a 3-tuple (simhierarchy, siminst, node). simhierarchy references
    the SimHierarchy in which we are navigating. At the top-level schematic,
    siminst is None, elsewhere it points to the current SimInstance. node
    is where we are in the current inst.
    """
    def __repr__(self):
        return f"{type(self).__name__}{tuple.__repr__(self)}"

    @property
    def simhierarchy(self):
        return tuple.__getitem__(self, 0)

    @property
    def siminst(self):
        return tuple.__getitem__(self, 1)
    
    @property
    def node(self):
        return tuple.__getitem__(self, 2)

    def child(self, inner_child): # lol
        """
        Converts the inner (= node's) child to a contextually meaningful return
        value.
        """
        if isinstance(inner_child, SchemInstance):
            return self.simhierarchy.one(SimInstance.parent_eref_idx.query(
                (self.siminst, inner_child)))
        elif isinstance(inner_child, (Pin, Net, SchemPort)):
            # Coerce SchemPort to Net:
            if isinstance(inner_child, SchemPort):
                inner_child = inner_child.ref
            if isinstance(inner_child, Pin) and self.siminst is not None:
                if self.siminst.schematic is not None:
                    # Symbol subcursor is used, but Schematic is available.
                    # We need the nid from the Schematic!
                    inner_child = self.siminst.schematic.one(Net.pin_idx.query(inner_child))
                else:
                    # Leaf device: return SimPin (branch current) if one exists.
                    try:
                        return self.simhierarchy.one(
                            SimPin.instance_eref_idx.query(
                                (self.siminst, inner_child)))
                    except QueryException:
                        # TODO: Maybe in this case we should return something that acts as a SimPin that
                        # derives its current from known currents.
                        pass
            return self.simhierarchy.one(SimNet.parent_eref_idx.query(
                (self.siminst, inner_child)))
        elif isinstance(inner_child, Node) and inner_child.root == self.node.root:
            # inner_child is likely a PathNode.
            return SimHierarchySubcursor((self.simhierarchy, self.siminst, inner_child))
        else:
            # Oh, it looks like we have just read an attribute!
            return inner_child

    def __getitem__(self, name):
        return self.child(self.node[name])
    
    def __getattr__(self, name):
        return self.child(getattr(self.node, name))

@public
class SimHierarchy(SubgraphRoot):
    view_builder = SimulationViewBuilder
    wire_id = WIRE_DOMAIN | 1

    schematic = SubgraphRef(Schematic)
    cell = LiveRef(Cell)
    sim_type = Attr(SimType)

    @property
    def scales(self):
        """Scale columns (independent axes) of the recorded result,
        outermost first, taken from the SimScale nodes: () for op, one
        column for tran/ac/dc sweep, one per swept variable for nested
        sweeps. Scales are identified by their Quantity, never by name.
        """
        return tuple(s.column for s in
            sorted(self.all(SimScale), key=lambda s: s.pos))

    @property
    def time(self):
        """Time scale column of a transient result, or None."""
        for scale in self.scales:
            if scale.quantity == Quantity.TIME:
                return scale
        return None

    @property
    def freq(self):
        """Frequency scale column of an AC result, or None."""
        for scale in self.scales:
            if scale.quantity == Quantity.FREQUENCY:
                return scale
        return None

    @property
    def sweep(self):
        """Primary sweep scale column of a DC sweep result, or None.

        The first scale that is neither time nor frequency; for nested
        sweeps this is the outermost swept variable.
        """
        for scale in self.scales:
            if scale.quantity not in (Quantity.TIME, Quantity.FREQUENCY):
                return scale
        return None

    def __setitem__(self, k, v):
        raise TypeError("Insert with path not supported in SimHierarchy.")

    def __delitem__(self, k):
        raise TypeError("Deletion of path not supported in SimHierarchy.")

    # No need to override setattr__ and __delattr__. The ones in SubgraphRoot
    # will play nicely with the __setitem__ and __delitem__ methods defined here.

    def __getitem__(self, name):
        return self.subcursor()[name]

    def __getattr__(self, name):
        return getattr(self.subcursor(), name)

    def subcursor(self):
        return SimHierarchySubcursor((self, None, self.schematic))

    def simulate(self, enable_savecurrents: bool = True):
        from ...sim import Simulator
        return Simulator(self, enable_savecurrents=enable_savecurrents)

    def schematic_or_symbol_at(self, inst: Optional['SimInstance']):
        """Helper function for of_subgraph of SimNet.eref and SimInstance.eref."""
        if inst is None:
            return self.schematic
        elif inst.schematic is None:
            # When SimInstance has no schematic, the eref nids point to the Symbol.
            return inst.eref.symbol
        else:
            return inst.schematic

    @classmethod
    def from_schematic(cls, schematic: Schematic):
        """
        Create a simulation hierarchy from a schematic. The returned
        SimHierarchy can be used to run simulations with Simulator.
        """
        simhier = cls()
        simhier.schematic = schematic
        simhier.cell = schematic.cell

        def add_sym(sym: Symbol, parent: 'SimInstance'):
            for pin in sym.all(Pin):
                simhier % SimNet(eref=pin, parent_inst=parent)

        def add_sch(sch: Schematic, parent: Optional['SimInstance']):
            for net in sch.all(Net):
                simhier % SimNet(eref=net, parent_inst=parent)

            for scheminst in sch.all(SchemInstance):
                inst = simhier % SimInstance(eref=scheminst, parent_inst=parent)
                try:
                    subsch = scheminst.symbol.cell.schematic
                except AttributeError:
                    add_sym(scheminst.symbol, inst)
                else:
                    inst.schematic = subsch
                    add_sch(subsch, inst)

        add_sch(schematic, None)
        return simhier

    def webdata_static(self):
        from ...sim.webdata import webdata
        return webdata(self)

    def _export_columns(self, include, translate_names):
        """Collect (name, column) pairs to export, scales first.

        Args:
            include: None for all node-mapped signals, or an iterable of
                SimNet/SimPin/SimParam nodes to include.
            translate_names: True for ORDB-style paths ('time',
                'r1.voltage'), False for the raw ngspice names carried
                by the columns ('v(r1)'; hand-assigned columns without a
                name fall back to the translated name).

        Returns:
            List of (name, SimColumn) pairs; the independent variables
            (scale columns) always come first.
        """
        pairs = []
        for scale in self.scales:
            if scale.quantity == Quantity.TIME:
                tname = 'time'
            elif scale.quantity == Quantity.FREQUENCY:
                tname = 'frequency'
            else:
                # Swept variables have no ORDB-side name; they keep
                # their raw column name (e.g. 'v(v-sweep)') even when
                # translating.
                tname = scale.name
            pairs.append((tname, scale))

        if include is None:
            include = [*self.all(SimNet), *self.all(SimPin),
                *self.all(SimParam)]
        for node in include:
            if isinstance(node, SimNet):
                col, tname = node.voltage, \
                    f"{node.full_path_str()}.voltage"
            elif isinstance(node, SimPin):
                col, tname = node.current, \
                    f"{node.full_path_str()}.current"
            elif isinstance(node, SimParam):
                col, tname = node.value, \
                    f"{node.instance.full_path_str()}" \
                    f".params[{node.name!r}].value"
            else:
                raise TypeError(
                    "include must contain SimNet, SimPin, or SimParam"
                    f" nodes, got {type(node).__name__}")
            if col is None:
                continue
            pairs.append((tname, col))

        if not translate_names:
            pairs = [(col.name if col.name is not None else name, col)
                for name, col in pairs]
        return pairs

    def to_numpy(self, include=None, translate_names=True):
        """Convert simulation data to a numpy structured array.

        Args:
            include: None to include all node-mapped signals, or an
                iterable of SimNet/SimPin/SimParam nodes. The independent
                variables (time/freq/sweep) are always included first.
            translate_names: If True (default), use ORDB-style path names.
                If False, keep the raw ngspice names.

        Returns:
            numpy structured array with requested fields.
        """
        import numpy as np

        pairs = self._export_columns(include, translate_names)
        if not pairs:
            raise ValueError("No simulation data available")

        dtype_to_np = {'f8': np.float64, 'c16': np.complex128}
        dtype = np.dtype({
            'names': [name for name, _ in pairs],
            'formats': [dtype_to_np[col.dtype] for _, col in pairs],
        })

        arr = np.empty(len(pairs[0][1]), dtype=dtype)
        for name, col in pairs:
            arr[name] = list(col)
        return arr

    def write_csv(self, filename, include=None, translate_names=True):
        """Write simulation data to a CSV file.

        Args:
            filename: Path to the output CSV file.
            include: None to include all node-mapped signals, or an
                iterable of SimNet/SimPin/SimParam nodes. The independent
                variables (time/freq/sweep) are always included first.
            translate_names: If True (default), use ORDB-style path names.
                If False, keep the raw ngspice names.
        """
        import csv

        pairs = self._export_columns(include, translate_names)
        if not pairs:
            raise ValueError("No simulation data available")

        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([name for name, _ in pairs])
            columns = [col for _, col in pairs]
            for i in range(len(columns[0])):
                writer.writerow([col[i] for col in columns])

@public
class SimScale(Node):
    """One independent axis (scale) of the recorded result: a time,
    frequency or swept-variable column shared by all result columns of
    the run. An op result has no SimScale nodes, tran/ac/dc sweep
    results have one, nested sweeps one per swept variable. Scales are
    identified by their column's Quantity, never by name.
    """
    in_subgraphs = [SimHierarchy]
    wire_id = WIRE_DOMAIN | 6

    pos = Attr(int, optional=False) #: axis order, 0 = outermost
    column = Attr(SimColumn, optional=False, factory=SimColumn.coerce)

    pos_idx = Index(pos, unique=True)

@public
class SimNet(Node):
    in_subgraphs = [SimHierarchy]
    wire_id = WIRE_DOMAIN | 2

    parent_inst = LocalRef('SimInstance', optional=True,
        refcheck_custom=lambda val: issubclass(val, SimInstance))

    #: Simulated voltage as a SimColumn, or None if not recorded. All
    #: result columns of a run share the root's scale columns
    #: (SimScale); op results have a single-element column.
    voltage = Attr(SimColumn, factory=SimColumn.coerce)

    eref = ExternalRef(Net|Pin,
        of_subgraph=lambda c: c.root.schematic_or_symbol_at(c.parent_inst),
        optional=False,
        )

    def full_path_list(self) -> list[str|int]:
        if self.parent_inst is None:
            parent_path = []
        else:
            parent_path = self.parent_inst.full_path_list()
        return parent_path + self.eref.full_path_list()

    parent_eref_idx = CombinedIndex([parent_inst, eref], unique=True)

@public
class SimPin(Node):
    in_subgraphs = [SimHierarchy]
    wire_id = WIRE_DOMAIN | 3

    instance = LocalRef('SimInstance', optional=False,
        refcheck_custom=lambda val: issubclass(val, SimInstance))

    eref = ExternalRef(Pin,
        of_subgraph=lambda c: c.instance.eref.symbol,
        optional=False)

    #: Simulated pin current as a SimColumn, or None if not recorded.
    current = Attr(SimColumn, factory=SimColumn.coerce)

    def full_path_list(self) -> list[str|int]:
        return self.instance.full_path_list() + self.eref.full_path_list()

    instance_eref_idx = CombinedIndex([instance, eref], unique=True)

@public
class SimParam(Node):
    in_subgraphs = [SimHierarchy]
    wire_id = WIRE_DOMAIN | 4

    instance = LocalRef('SimInstance', optional=False,
        refcheck_custom=lambda val: issubclass(val, SimInstance))

    name = Attr(str) #: Parameter name: "gm", "gds", "vth", "region", etc.
    #: Simulated parameter value as a SimColumn, or None if not recorded.
    value = Attr(SimColumn, factory=SimColumn.coerce)

    def full_path_list(self) -> list[str|int]:
        return self.instance.full_path_list() + [self.name]

    instance_name_idx = CombinedIndex([instance, name], unique=True)

class SimInstanceParamCursor(tuple):
    """Cursor for accessing SimParam nodes of a SimInstance by name.

    Usage: ``instance.params['gm']`` returns the SimParam node.
    """
    @property
    def _instance(self):
        return tuple.__getitem__(self, 0)

    def __getitem__(self, name):
        return self._instance.root.one(
            SimParam.instance_name_idx.query((self._instance, name)))

    def __getattr__(self, name):
        return self[name]

    def __repr__(self):
        return f"{type(self).__name__}({self._instance!r})"

@public
class SimInstance(Node):
    in_subgraphs = [SimHierarchy]
    wire_id = WIRE_DOMAIN | 5

    parent_inst = LocalRef('SimInstance', optional=True,
        refcheck_custom=lambda val: issubclass(val, SimInstance))

    schematic = SubgraphRef(Schematic,
        typecheck_custom=lambda v: isinstance(v, (Symbol, Schematic)),
        optional=True,
        )
    eref = ExternalRef(SchemInstance,
        of_subgraph=lambda c: c.root.schematic_or_symbol_at(c.parent_inst),
        optional=False,
        )

    parent_eref_idx = CombinedIndex([parent_inst, eref], unique=True)

    @property
    def params(self) -> SimInstanceParamCursor:
        return SimInstanceParamCursor((self,))

    def subcursor(self):
        if self.schematic is None:
            return self.subcursor_symbol()
        else:
            return self.subcursor_schematic()

    def subcursor_schematic(self):
        return SimHierarchySubcursor((self.root, self, self.schematic))

    def subcursor_symbol(self):
        return SimHierarchySubcursor((self.root, self, self.eref.symbol))

    def __getitem__(self, name):
        return self.subcursor()[name]

    def __getattr__(self, name):
        return getattr(self.subcursor(), name)

    def full_path_list(self) -> list[str|int]:
        if self.parent_inst is None:
            parent_path = []
        else:
            parent_path = self.parent_inst.full_path_list()
        return parent_path + self.eref.full_path_list()

public(Simulation = SimHierarchy)
