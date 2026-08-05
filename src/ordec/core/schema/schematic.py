# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from enum import Enum
import math
from functools import partial
from public import public

from ..rational import R
from ..geoprim import *
from ..ordb import *
from ..cell import Cell
from ..constraints import *
from ..context import SymbolViewContext, SchematicViewContext
from .base import (
    coerce_tuple, SourceLocInfo, MixinPolygonalChain, GenericPolyR, PolyVec2R,
)

WIRE_DOMAIN = 3 << 16

# Enums
# -----

@public
class PinType(Enum):
    In = 'in'
    Out = 'out'
    Inout = 'inout'

    def __repr__(self):
        return f'{self.__class__.__name__}.{self.name}'

@public
class SchemErrorType(Enum):
    OverlappingTerminals = 'Overlapping terminals'
    MissingTerminalConnection = 'Missing terminal connection'
    IncorrectTerminalConnection = 'Incorrect terminal connection'
    GeometricShort = 'Geometric short'
    OverlappingWires = 'Overlapping wires'
    OverlappingSchemConnPoints = 'Overlapping connection points'
    IncorrectlyPlacedSchemConnPoint = 'Incorrectly placed connection point'
    UnconnectedPin = 'Unconnected pin'
    StrayPinsInPortmap = 'Stray pins in portmap'
    SchemConnPointOverlappingTerminal = 'Connection point overlapping terminal'
    TerminalMultipleConnections = 'Terminal with multiple connections'
    UnconnectedWiring = 'Unconnected wiring'
    StraySchemConnPoint = 'Stray connection point'
    MissingSchemConnPoint = 'Missing connection point'
    NetMissesWiring = 'Net misses wiring'
    OverlappingInstances = 'Overlapping instances'

    def __repr__(self):
        return f'{self.__class__.__name__}.{self.name}'

# Symbol
# ------

class MixinRenderable:
    """Mixin providing SVG rendering for Symbol and Schematic subgraphs."""
    __slots__ = ()

    def render(self, **kwargs) -> 'Renderer':
        from ...schematic.render import render
        return render(self, **kwargs)

    def _repr_svg_(self):
        return self.render().svg().decode('ascii'), {'isolated': False}

    def webdata_static(self):
        return self.render().webdata()


@public
class Symbol(MixinRenderable, SubgraphRoot):
    """A symbol of an individual cell."""
    view_context = SymbolViewContext
    wire_id = WIRE_DOMAIN | 1
    outline = Attr(Rect4R, factory=coerce_tuple(Rect4R, 4))
    caption = Attr(str)
    cell = LiveRef(Cell)

    def portmap(self, **kwargs):
        def inserter_func(main, sgu, primary_nid):
            main_nid = main.set(symbol=self.subgraph).insert_into(sgu, primary_nid)
            for k, v in kwargs.items():
                SchemInstanceConn(ref=main_nid, here=v.nid, there=self[k].nid).insert_into(sgu, sgu.nid_generate())
            return main_nid
        return inserter_func

    def place_pins(self, hpadding=3, vpadding=3):
        from ...schematic import symbol_place_pins
        symbol_place_pins(self, hpadding=hpadding, vpadding=vpadding)

@public
class Pin(Node):
    """Pins are single wire connections exposed through a symbol."""
    in_subgraphs = [Symbol]
    wire_id = WIRE_DOMAIN | 2

    pintype = Attr(PinType, default=PinType.Inout)
    pos     = Attr(Vec2R, factory=coerce_tuple(Vec2R, 2))
    align   = Attr(D4, default=D4.R0)

@public
class SymbolPoly(GenericPolyR, MixinPolygonalChain):
    """A drawn polygonal chain in Symbol. For visual purposes only."""
    in_subgraphs = [Symbol]
    wire_id = WIRE_DOMAIN | 3

@public
class SymbolArc(Node):
    """A drawn circle or circular segment in Symbol. For visual purposes only."""
    in_subgraphs = [Symbol]
    wire_id = WIRE_DOMAIN | 4

    pos         = Attr(Vec2R, factory=coerce_tuple(Vec2R, 2)) #: Center point
    radius      = Attr(R) #: Radius of the arc.
    angle_start = Attr(R, default=R(0)) #: Must be less than angle_end and between -1 and 1, with -1 representing -360° and 1 representing 360°.
    angle_end   = Attr(R, default=R(1)) #:Must be greater than angle_start and between -1 and 1, with -1 representing -360° and 1 representing 360°.
    
    def svg_path(arc) -> str:
        """
        Returns string representation of arc suitable for
        "d" attribute of SVG <path>.
        """
        def vec2r_on_circle(radius: R, angle: R) -> Vec2R:
            return Vec2R(
                x = radius * math.cos(2 * math.pi * angle),
                y = radius * math.sin(2 * math.pi * angle)
                )

        d = []
        x, y = arc.pos.tofloat()
        r = float(arc.radius)
        d.append(f"M{x} {y}")
        if arc.angle_start == 0 and arc.angle_end == 1:
            d.append(f"m{r} 0")
            d.append(f"a {r} {r} 0 0 0 {-2*r} 0")
            d.append(f"a {r} {r} 0 0 0 {2*r} 0")
        else:
            start = vec2r_on_circle(arc.radius, arc.angle_start)
            end = vec2r_on_circle(arc.radius, arc.angle_end)
            rel_end = end - start
            s_x, s_y = start.tofloat()
            e_dx, e_dy = rel_end.tofloat()

            large_arc_flag = 0 # my understanding is this has no effect when x and y radius are identical.
            sweep_flag = 1
            d.append(f"m{s_x} {s_y}")
            d.append(f"a {r} {r} 0 {large_arc_flag} {sweep_flag} {e_dx} {e_dy}")
        return ' '.join(d)

# Schematic
# ---------

@public
class Schematic(MixinRenderable, SubgraphRoot):
    """A schematic of an individual cell."""
    view_context = SchematicViewContext
    wire_id = WIRE_DOMAIN | 5
    symbol = SubgraphRef(Symbol)
    outline = Attr(Rect4R, factory=coerce_tuple(Rect4R, 4))
    cell = LiveRef(Cell)
    default_supply = LocalRef('Net', refcheck_custom=lambda val: issubclass(val, Net))
    default_ground = LocalRef('Net', refcheck_custom=lambda val: issubclass(val, Net))

    def resolve_instances(self):
        from ...schematic import resolve_instances
        resolve_instances(self)

    def auto_wire(self):
        from ...schematic import auto_wire
        auto_wire(self)

    def place_ports(self):
        from ...schematic.helpers import schem_place_ports
        schem_place_ports(self)

    def place_unplaced_instances(self):
        from ...schematic.helpers import place_unplaced_instances
        place_unplaced_instances(self)

    def check(self, add_conn_points=False, add_terminal_taps=False):
        from ...schematic import schem_check
        schem_check(self, add_conn_points=add_conn_points, add_terminal_taps=add_terminal_taps)

    def has_errors(self) -> bool:
        return any(True for _ in self.all(SchemErrorMarker))


class NegatedWireOperand:
    """Wrapper enabling the ``--`` pseudo-operator for schematic wiring.

    The ``--`` connection operator (e.g. ``inst.d -- vss``) is not a dedicated
    grammar rule but a combination of Python's subtraction and negation:
    ``a -- b`` is parsed as ``a.__sub__(b.__neg__())``.  Both operand orders
    are supported (pin -- net *and* net -- pin) so the operator is commutative.
    """
    __slots__ = ('wrapped',)
    def __init__(self, wrapped):
        self.wrapped = wrapped

    def __rsub__(self, other):
        # Supports net -- pin (i.e. net - (-pin))
        wire_op = getattr(self.wrapped, '__wire_op__', None)
        if wire_op is not None:
            return wire_op(other)
        return NotImplemented

@public
class Net(Node):
    in_subgraphs = [Schematic]
    wire_id = WIRE_DOMAIN | 6
    pin = ExternalRef(Pin, of_subgraph=lambda c: c.root.symbol)
    auto_wire = Attr(bool, default=True) #: Controls whether the Net is auto-wired

    pin_idx = Index(pin)

    def __neg__(self):
        return NegatedWireOperand(self)

    @property
    def port(self):
        return self.root.one(SchemPort.ref_idx.query(self))

    @property
    def pos(self):
        return self.port.pos

    @pos.setter
    def pos(self, value):
        self.port.pos = value

    @property
    def align(self):
        return self.port.align

    @align.setter
    def align(self, value):
        self.port.align = value

@public
class SchemPort(Node):
    """
    Port of a Schematic, corresponding to a Pin of the schematic's Symbol.
    """
    in_subgraphs = [Schematic]
    wire_id = WIRE_DOMAIN | 7

    ref = LocalRef(Net, optional=False)
    ref_idx = Index(ref, unique=True)
    pos = ConstrainableAttr(Vec2R, placeholder=Vec2LinearTerm,
        factory=coerce_tuple(Vec2R, 2))
    pos_idx = Index(pos)
    align = Attr(D4, default=D4.R0)

@public
class SchemWire(GenericPolyR, MixinPolygonalChain):
    """A drawn schematic wire representing an electrical connection."""
    in_subgraphs = [Schematic]
    wire_id = WIRE_DOMAIN | 8

    ref = LocalRef(Net, optional=False)
    ref_idx = Index(ref)

class SchemInstanceSubcursor(tuple):
    """
    Cursor providing transformed access to Symbol contents from SchemInstance.
    Transforms Symbol-space coordinates (Vec2R, Rect4R) to Schematic-space
    based on the instance's position and orientation; directions (D4, e.g.
    Pin.align) are composed with the instance's orientation.
    """
    def __repr__(self):
        return f"{type(self).__name__}{tuple.__repr__(self)}"

    def inst(self):
        """Returns the SchemInstance."""
        return tuple.__getitem__(self, 0)

    def node(self):
        """Returns the current symbol-space node."""
        return tuple.__getitem__(self, 1)

    def transform(self):
        """Returns the instance's loc_transform (TD4R or TD4LinearTerm)."""
        return self.inst().loc_transform()

    def __getitem__(self, key):
        """Support indexing into pin hierarchies (e.g., inst['d'][0].pos)."""
        return SchemInstanceSubcursor((self.inst(), self.node()[key]))

    def __neg__(self):
        return NegatedWireOperand(self)

    def __wire_op__(self, here):
        conn = self.inst() % SchemInstanceConn(here=here, there=self.node())
        return conn

    def __sub__(self, other):
        if isinstance(other, NegatedWireOperand):
            return self.__wire_op__(other.wrapped)
        return NotImplemented

    def __getattr__(self, name):
        inner_ret = getattr(self.node(), name)
        if isinstance(inner_ret, (Rect4R, Vec2R)):
            # Transform symbol-space coordinates to schematic-space
            # Returns Rect4LinearTerm/Vec2LinearTerm if inst.pos is None,
            # or Rect4R/Vec2R if inst.pos is defined
            return self.transform() * inner_ret
        elif isinstance(inner_ret, D4):
            # Directions rotate/mirror with the instance, like coordinates do.
            return self.inst().orientation * inner_ret
        elif isinstance(inner_ret, Node):
            return SchemInstanceSubcursor((self.inst(), inner_ret))
        else:
            return inner_ret


class MixinSourceLoc:
    """
    Provides src_loc attribute for Nodes that support back link to source.
    This enables click-to-source for ORD code in the web UI. Currently, src_loc
    is None for nodes not built from ORD code.
    """
    __slots__=()
    src_loc = Attr(SourceLocInfo)


@public
class SchemInstance(Node, MixinSourceLoc):
    """
    An instance of a Symbol in a Schematic (foundation for schematic hierarchy).
    """
    in_subgraphs = [Schematic]
    wire_id = WIRE_DOMAIN | 9

    pos = ConstrainableAttr(Vec2R, placeholder=Vec2LinearTerm,
        factory=coerce_tuple(Vec2R, 2))
    orientation = Attr(D4, default=D4.R0)
    symbol = SubgraphRef(Symbol, optional=False)

    def __new__(cls, connect=None, **kwargs):
        main = super().__new__(cls, **kwargs)
        if connect is None:
            return main
        else:
            return FuncInserter(partial(connect, main))

    def loc_transform(self):
        pos = self.pos
        if isinstance(pos, Vec2LinearTerm):
            return TD4LinearTerm(transl=pos, d4=self.orientation)
        else:
            return pos.transl() * self.orientation

    def subcursor(self):
        return SchemInstanceSubcursor((self, self.symbol))

    def __getitem__(self, name):
        return self.subcursor()[name]

    def __getattr__(self, name):
        return getattr(self.subcursor(), name)

    def conns(self):
        return self.subgraph.all(SchemInstanceConn.ref_idx.query(self))

@public
class SchemInstanceConn(Node):
    """Maps one Pin of a SchemInstance to a Net of its Schematic."""
    in_subgraphs = [Schematic]
    wire_id = WIRE_DOMAIN | 10

    ref = LocalRef(SchemInstance, optional=False)
    ref_idx = Index(ref)

    here = LocalRef(Net, optional=False)
    there = ExternalRef(Pin, of_subgraph=lambda c: c.ref.symbol, optional=False) # ExternalRef to Pin in SchemInstance.symbol

    ref_pin_idx = CombinedIndex([ref, there], unique=True)


class SchemInstanceUnresolvedSubcursor(tuple):
    """Cursor to go through connections of a unresolved schem instance"""
    def __repr__(self):
        return f"{type(self).__name__}{tuple.__repr__(self)}"

    def __eq__(self, other):
        return type(self) == type(other) and super().__eq__(other)

    def __getitem__(self, name):
        return SchemInstanceUnresolvedSubcursor(self+(name,))
    
    def __getattr__(self, name):
        # Upgrade cursor on failed attribute access
        return getattr(self._upgrade_cursor(), name)

    def _upgrade_cursor(self):
        """
        Convert this unresolved cursor into a resolved SchemInstanceSubcursor.
        Recorded parameters are passed to the resolver so that geometry
        matches the symbol that resolve_instances() will produce.
        """
        ui = self.instanceunresolved
        cursor = SchemInstanceSubcursor((ui, ui.resolve_symbol()))

        # Walking the path through a SchemInstanceSubcursor transforms
        # geometry values to schematic space, as on resolved instances.
        for step in self.instancepath:
            if isinstance(step, int):
                cursor = cursor[step]
            else:
                cursor = getattr(cursor, step)
        return cursor

    @property
    def instanceunresolved(self):
        # self[0], but wihtout calling SchemInstanceUnresolvedCursor.__getitem__
        return tuple.__getitem__(self, 0)

    @property
    def instancepath(self):
        # self[1:], but without calling SchemInstanceUnresolvedCursor.__getitem__
        return tuple.__getitem__(self, slice(1,None))

    def __neg__(self):
        return NegatedWireOperand(self)

    def __wire_op__(self, here):
        conn = self.instanceunresolved % \
            SchemInstanceUnresolvedConn(here=here, there=self.instancepath)
        return conn

    def __sub__(self, other):
        if isinstance(other, NegatedWireOperand):
            return self.__wire_op__(other.wrapped)
        return NotImplemented
    
@public
class SchemInstanceUnresolved(Node, MixinSourceLoc):
    """An instance of a Symbol that is not determined yet."""

    class ParamWrapper:
        def __init__(self, inst):
            self._inst = inst

        def __setattr__(self, name, value):
            if name.startswith("_"):
                return super().__setattr__(name, value)
            self._inst % SchemInstanceUnresolvedParameter(name=name, value=value)

    in_subgraphs = [Schematic]
    wire_id = WIRE_DOMAIN | 11

    pos = ConstrainableAttr(Vec2R, placeholder=Vec2LinearTerm,
        factory=coerce_tuple(Vec2R, 2))
    orientation = Attr(D4, default=D4.R0)

    resolver = LiveRef(object)

    @property
    def params(self):
        return self.ParamWrapper(self)

    def loc_transform(self):
        return self.pos.transl() * self.orientation

    def __getitem__(self, name):
        return self.__getattr__(name)

    def __getattr__(self, name):
        return SchemInstanceUnresolvedSubcursor((self, name))

    def resolve_symbol(self, remove_params_sgu: 'SubgraphUpdater'=None) -> Symbol:
        param_dict = {}
        for param in self.root.all(SchemInstanceUnresolvedParameter.ref_idx.query(self)):
            param_dict[param.name] = param.value
            if remove_params_sgu:
                remove_params_sgu.remove_nid(param.nid)

        return self.resolver(**param_dict)

@public
class SchemInstanceUnresolvedConn(Node):
    """Unresolved SchemInstanceConn."""
    in_subgraphs = [Schematic]
    wire_id = WIRE_DOMAIN | 12

    ref = LocalRef(SchemInstanceUnresolved, optional=False)
    ref_idx = Index(ref)

    here = LocalRef(Net, optional=False,
        factory=lambda v: v.ref if isinstance(v, SchemPort) else v)
    there = Attr(tuple, optional=False) #: Tuple of str or int = requested path in future symbol

@public
class SchemInstanceUnresolvedParameter(Node):
    in_subgraphs = [Schematic]
    wire_id = WIRE_DOMAIN | 13

    ref = LocalRef(SchemInstanceUnresolved, optional=False)
    ref_idx = Index(ref)

    name = Attr(str, optional=False)
    value = Attr(object, optional=False) #: TODO - should be immutable.

@public
class SchemTapPoint(Node):
    """
    A schematic tap point for connecting points by label, typically visualized
    using the net's name.
    """
    in_subgraphs = [Schematic]
    wire_id = WIRE_DOMAIN | 14

    ref = LocalRef(Net, optional=False)
    ref_idx = Index(ref)

    pos = Attr(Vec2R, factory=coerce_tuple(Vec2R, 2))
    pos_idx = Index(pos)
    align = Attr(D4, default=D4.R0)

    def loc_transform(self):
        return self.pos.transl() * self.align

@public
class SchemConnPoint(Node):
    """A schematic point to indicate a connection at a 3- or 4-way junction of wires."""
    in_subgraphs = [Schematic]
    wire_id = WIRE_DOMAIN | 15
    ref = LocalRef(Net, optional=False)
    ref_idx = Index(ref)

    pos = Attr(Vec2R, factory=coerce_tuple(Vec2R, 2))
    pos_idx = Index(pos)

@public
class SchemErrorMarker(Node):
    """An error marker indicating a schematic check failure."""
    in_subgraphs = [Schematic]
    wire_id = WIRE_DOMAIN | 16
    ref = LocalRef(Schematic)
    pos = Attr(Vec2R, factory=coerce_tuple(Vec2R, 2))
    align = Attr(D4, default=D4.R0)
    error_type = Attr(SchemErrorType)

# PolyVec2R vertex nodes (defined in .base) may appear in Symbol and Schematic
# subgraphs:
PolyVec2R.in_subgraphs.append(Symbol)
PolyVec2R.in_subgraphs.append(Schematic)
