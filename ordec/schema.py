# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
This file defines the common schema for IC design data.
"""
from .base import View, Node, Cell, attr, IntegrityError, PathNode, PathArray, PathStruct
from pyrsistent import CheckedPMap, CheckedPVector
from .rational import Rational as R
from .geoprim import TD4, Vec2R, Rect4R, Orientation
from enum import Enum
from collections.abc import Mapping
from .parser.prelim_schem_instance import PrelimSchemInstance
from warnings import warn

# Everything needed for the Symbol view
# -------------------------------------

class PolyVec2R(CheckedPVector):
    """
    A list of Vec2R points representing a polygonal chain, which can be
    open or closed. A polygonal chain is closed if the last and first element
    are equivalent.
    """
    __type__ = Vec2R

    def closed(self) -> bool:
        return self[-1] == self[0]

class PinType(Enum):
    In = 'in'
    Out = 'out'
    Inout = 'inout'

class SchemPoly(Node):
    """A polygonal chain in a schematic or symbol."""
    vertices = attr(type=PolyVec2R, freezer=PolyVec2R)

class SchemConnPoint(Node):
    """A schematic point to indicate a connection at a 3- or 4-way junction of wires."""
    pos = attr(type=Vec2R)

class SchemTapPoint(Node):
    """A schematic tap point for connecting points by label, typically visualized using the net's name."""

    pos = attr(type=Vec2R)
    align = attr(type=Orientation)

    def check_integrity(self):
        if self.align.value.det() != 1:
            raise IntegrityError('SchemTapPoint cannot have mirrored orientation.')

class SchemRect(Node):
    """A schematic rectangle, currently only used for Symbol and Schematic onlines."""
    pos = attr(type=Rect4R)

class SchemArc(Node):
    """A drawn circle or circular segment for use in Symbol."""
    pos = attr(type=Vec2R, help="Center point")
    radius = attr(type=R, help="Radius of the arc")
    angle_start = attr(type=R, default=R(0), help="Must be less than angle_end and between -1 and 1, with -1 representing -360° and 1 representing 360°.")
    angle_end = attr(type=R, default=R(1), help="Must be greater than angle_start and between -1 and 1, with -1 representing -360° and 1 representing 360°.")

    def check_integrity(self):
        if self.radius <= R(0):
            raise IntegrityError("SchemArc radius must be greater than 0.")
        if self.angle_start >= self.angle_end:
            raise IntegrityError("SchemArc angle_start must be less than angle_end.")
        for a in self.angle_start, self.angle_end:
            if a < R(-1) or a > R(1):
                raise IntegrityError("angle_start and angle_end must be between -1 and 1.")

class Pin(Node):
    """
    Pins are single wire connections exposed through a symbol.
    In the future, a second Pin-like node might be added to support
    struct / array (bus) connections through single schematic connectors.
    """
    pos = attr(type=Vec2R)
    pintype = attr(type=PinType)
    align = attr(type=Orientation)

    def check_integrity(self):
        if self.align.value.det() != 1:
            raise IntegrityError('Pin cannot have mirrored orientation.')

class PinArray(PathArray):
    children: Mapping[int, "inherit"]
    def __init__(self, parent, name, **kwargs):
        warn(f"Use PathArray instead of PinArray.", DeprecationWarning, stacklevel=4)
        super().__init__(parent, name, **kwargs)

class PinStruct(PathArray):
    children: Mapping[str, "inherit"]
    def __init__(self, parent, name, **kwargs):
        warn(f"Use PathStruct instead of PinStruct.", DeprecationWarning, stacklevel=4)
        super().__init__(parent, name, **kwargs)

class Symbol(View):
    """
    A symbol of an individual cell.
    """
    children: Mapping[str, Pin|SchemPoly|SchemArc|SchemRect|PathNode]
    
    outline = attr(type=SchemRect)

    def _repr_html_(self):
        from .render import render_svg
        return render_svg(self).as_html()

# Everything needed for the Schematic view
# ----------------------------------------

class Net(Node):
    """
    Pins are single wire connections exposed through a symbol.
    In the future, a second Pin-like node might be added to support
    struct / array (bus) connections through single schematic connectors.
    """

    children: Mapping[str, SchemPoly|SchemConnPoint|SchemTapPoint]

class PortMap(CheckedPMap):
    """
    Maps Pins of a SchemInstance to Nets of its Schematic.
    "PinMap" would be a more fitting name, but PortMap seems catchier due to its use in VHDL.
    """
    __key_type__ = (Pin,)
    __value_type__ = (Net,)


class SchemInstance(Node):
    """
    An instance of a Symbol in a Schematic (foundation for schematic hierarchy).
    """
    pos = attr(type=Vec2R)
    orientation = attr(type=Orientation, default=Orientation.R0)
    ref = attr(type=Symbol)
    portmap = attr(type=PortMap, freezer=PortMap)

    def loc_transform(self):
        return self.orientation.value.set(transl=self.pos)

class SchemPort(Node):
    """
    Port of a Schematic, corresponding to a Pin of the schematic's Symbol.
    """
    pos = attr(type=Vec2R)
    ref = attr(type=Pin)
    align = attr(type=Orientation)
    net = attr(type=Net)

    def check_integrity(self):
        if self.align.value.det() != 1:
            raise IntegrityError('SchemPort cannot have mirrored orientation.')

class NetArray(PathArray):
    children: Mapping[int, "inherit"]
    def __init__(self, parent, name, **kwargs):
        warn(f"Use PathArray instead of NetArray.", DeprecationWarning, stacklevel=4)
        super().__init__(parent, name, **kwargs)

class NetStruct(PathArray):
    children: Mapping[str, "inherit"]
    def __init__(self, parent, name, **kwargs):
        warn(f"Use PathStruct instead of NetStruct.", DeprecationWarning, stacklevel=4)
        super().__init__(parent, name, **kwargs)
class Schematic(View):
    """
    A schematic of an individual cell.
    """
    children: Mapping[str, Net|SchemInstance|PrelimSchemInstance|SchemRect|SchemPort|PathNode]
    outline = attr(type=SchemRect)
    default_supply = attr(type=Net|type(None), help="SchemTapPoints of referenced net are visually shown as main supply net (arrow without text), optional.")
    default_ground = attr(type=Net|type(None), help="SchemTapPoints of referenced net are visually shown as main ground net (three bars without text), optional.")
    ref = attr(type=Symbol|type(None), help="If SchemPorts are present in the Schematic, this attribute must reference the corresponding Symbol.")

    def _repr_html_(self):
        from .render import render_svg
        return render_svg(self).as_html()

    def check_integrity(self):
        first = True

        if self.ref:
            pins_expected = {pin for pin in self.ref.traverse(Pin)}
        else:
            pins_expected = set()
        ports_found = {port for port in self.traverse(SchemPort)}
        pins_found = {port.ref for port in ports_found}
        assert len(pins_found) <= len(ports_found)
        if len(pins_found) < len(ports_found):
            raise IntegrityError("Schematic with multiple SchemPorts referencing same Pin.")

        if pins_expected != pins_found:
            if self.ref == None:
                raise IntegrityError("Schematic with SchemPorts must reference its symbol (attribute 'ref').")
            else:
                raise IntegrityError("SchemPort/Pin mismatch between schematic and reference symbol.")

# Simulation hierarchy + results
# ------------------------------

class FloatVect(CheckedPVector):
    __type__ = float

class SimNet(Node):
    """
    SimNet is the place to measure a voltage.
    """
    trans_voltage = attr(type=FloatVect|type(None))
    trans_current = attr(type=FloatVect|type(None))
    dc_voltage = attr(type=float|type(None))
    dc_current = attr(type=float|type(None))

    ref = attr(type=Net|Pin)

# class SimPin(Node):
#     """
#     SimPin is the place to measure a current.
#     """
#     current_trans = attr(type=FloatVect|type(None))

#     ref = attr(type=Pin)

class SimInstance(Node):
    """
    Each unique SchemInstance become a SimInstance for simulation. SimInstances
    should be created for each unique used cell in the simulation hierarchy,
    irrespective of whether a corresponding schematic exists or not.

    For the top-level testbench, the SimHierarchy view itself assumes the role
    of the SimInstance.
    """
    ref = attr(type=SchemInstance)

SimInstance.__annotations__['children'] = Mapping[str, SimInstance|SimNet|PathNode] # Outside of class due to self-reference

class SimHierarchy(View):
    children: Mapping[str, SimInstance|SimNet|PathNode]

    ref = attr(type=Schematic)