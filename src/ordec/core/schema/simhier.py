# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from enum import Enum
from typing import Optional
from public import public

from ..ordb import *
from ..cell import Cell
from ..context import SimulationViewBuilder
from ..simarray import SimArray
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
    sim_data = Attr(SimArray) #: Packed simulation result data shared by all SimNet/SimInstance nodes.
    time_field = Attr(str) #: Column name in sim_data for the time axis (transient), or None.
    freq_field = Attr(str) #: Column name in sim_data for the frequency axis (AC), or None.
    sweep_field = Attr(str) #: Column name in sim_data for the DC sweep axis, or None.

    @property
    def time(self):
        if self.sim_data is None or self.time_field is None:
            return None
        return self.sim_data.column(self.time_field)

    @property
    def freq(self):
        if self.sim_data is None or self.freq_field is None:
            return None
        # AC rawfiles store frequency as complex with zero imaginary part;
        # return a real view for consumer convenience.
        return self.sim_data.column(self.freq_field).real

    @property
    def sweep(self):
        if self.sim_data is None or self.sweep_field is None:
            return None
        return self.sim_data.column(self.sweep_field)

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

    def simulate(self, enable_savecurrents: bool = True, batch: bool = True):
        from ...sim import Simulator
        return Simulator(self, enable_savecurrents=enable_savecurrents, batch=batch)

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

    def _collect_fields(self, include):
        """Collect field names to export, starting with the independent variable.

        Args:
            include: None to include all fields, or an iterable of
                SimNet/SimPin/SimParam nodes to include.

        Returns:
            List of field names (strings) to export.
        """
        fields = []
        for axis in (self.time_field, self.freq_field, self.sweep_field):
            if axis is not None:
                fields.append(axis)

        if include is None:
            for f in self.sim_data.fields:
                if f.fid not in fields:
                    fields.append(f.fid)
        else:
            for node in include:
                if isinstance(node, SimNet):
                    if node.voltage_field is not None:
                        fields.append(node.voltage_field)
                elif isinstance(node, SimPin):
                    if node.current_field is not None:
                        fields.append(node.current_field)
                elif isinstance(node, SimParam):
                    if node.field is not None:
                        fields.append(node.field)
                else:
                    raise TypeError(
                        f"include must contain SimNet, SimPin, or SimParam nodes, got {type(node).__name__}"
                    )
        return fields

    def _build_field_translation_map(self):
        """Build mapping from ngspice field names to ORDB-style paths."""
        field_map = {}

        if self.time_field:
            field_map[self.time_field] = 'time'
        if self.freq_field:
            field_map[self.freq_field] = 'frequency'
        if self.sweep_field:
            field_map[self.sweep_field] = 'sweep'

        for simnet in self.all(SimNet):
            if simnet.voltage_field:
                path = simnet.full_path_str()
                field_map[simnet.voltage_field] = f'{path}.voltage'

        for simpin in self.all(SimPin):
            if simpin.current_field:
                path_list = simpin.instance.full_path_list() + simpin.eref.full_path_list()
                path = Node.format_path_list(path_list)
                field_map[simpin.current_field] = f'{path}.current'

        for simparam in self.all(SimParam):
            if simparam.field:
                path = simparam.instance.full_path_str()
                field_map[simparam.field] = f"{path}.params[{simparam.name!r}].value"

        return field_map

    def _translate_fields(self, fields, translate):
        """Optionally translate field names to ORDB-style paths.

        When translate=True, fields without ORDB mappings (e.g., internal
        model nodes) are filtered out.
        """
        if not translate:
            return fields, fields
        field_map = self._build_field_translation_map()
        raw = [f for f in fields if f in field_map]
        translated = [field_map[f] for f in raw]
        return raw, translated

    def to_numpy(self, include=None, translate_names=True):
        """Convert simulation data to a numpy structured array.

        Args:
            include: None to include all fields, or an iterable of
                SimNet/SimPin/SimParam nodes. The independent variable
                (time/freq/sweep) is always included first.
            translate_names: If True (default), translate ngspice field names
                to ORDB-style paths. If False, keep raw ngspice names.

        Returns:
            numpy structured array with requested fields.
        """
        import numpy as np

        if self.sim_data is None:
            raise ValueError("No simulation data available")

        fields = self._collect_fields(include)
        fields, names = self._translate_fields(fields, translate_names)

        dtype_to_np = {'f8': np.float64, 'c16': np.complex128}
        field_info = {f.fid: f for f in self.sim_data.fields}

        dtype = np.dtype({
            'names': names,
            'formats': [dtype_to_np[field_info[fid].dtype] for fid in fields],
        })

        n = len(self.sim_data)
        arr = np.empty(n, dtype=dtype)
        for fid, name in zip(fields, names):
            arr[name] = list(self.sim_data.column(fid))
        return arr

    def write_csv(self, filename, include=None, translate_names=True):
        """Write simulation data to a CSV file.

        Args:
            filename: Path to the output CSV file.
            include: None to include all fields, or an iterable of
                SimNet/SimPin/SimParam nodes. The independent variable
                (time/freq/sweep) is always included first.
            translate_names: If True (default), translate ngspice field names
                to ORDB-style paths. If False, keep raw ngspice names.
        """
        import csv

        if self.sim_data is None:
            raise ValueError("No simulation data available")

        fields = self._collect_fields(include)
        fields, names = self._translate_fields(fields, translate_names)
        n = len(self.sim_data)

        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(names)
            columns = [self.sim_data.column(fid) for fid in fields]
            for i in range(n):
                writer.writerow([col[i] for col in columns])

@public
class SimNet(Node):
    in_subgraphs = [SimHierarchy]
    wire_id = WIRE_DOMAIN | 2

    parent_inst = LocalRef('SimInstance', optional=True,
        refcheck_custom=lambda val: issubclass(val, SimInstance))

    voltage_field = Attr(str) #: Column name in root sim_data for voltage.

    @property
    def voltage(self):
        sd = self.root.sim_data
        if sd is None or self.voltage_field is None:
            return None
        return sd.column(self.voltage_field)

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

    current_field = Attr(str) #: Column name in root sim_data for current.

    @property
    def current(self):
        sd = self.root.sim_data
        if sd is None or self.current_field is None:
            return None
        return sd.column(self.current_field)

    instance_eref_idx = CombinedIndex([instance, eref], unique=True)

@public
class SimParam(Node):
    in_subgraphs = [SimHierarchy]
    wire_id = WIRE_DOMAIN | 4

    instance = LocalRef('SimInstance', optional=False,
        refcheck_custom=lambda val: issubclass(val, SimInstance))

    name = Attr(str) #: Parameter name: "gm", "gds", "vth", "region", etc.
    field = Attr(str) #: Column name in root sim_data.

    @property
    def value(self):
        sd = self.root.sim_data
        if sd is None or self.field is None:
            return None
        return sd.column(self.field)

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

    def full_path_str(self) -> str:
        return '.'.join(str(x) for x in self.full_path_list())

public(Simulation = SimHierarchy)
