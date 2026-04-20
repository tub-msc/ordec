# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from enum import Enum
import math
from functools import partial
from typing import NamedTuple, Optional
import re
from public import public

from .rational import R
from .geoprim import *
from .ordb import *
from .cell import Cell
from .constraints import *
from .context import ViewContext, SymbolViewContext, SchematicViewContext, LayoutViewContext
from .simarray import SimArray

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
class PathEndType(Enum):
    """
    Could also be named 'linecap'.
    """
    Flush = 0 #: Path begins/ends right at the vertex
    Square = 2 #: Path extended by half width beyond start/end vertex
    Custom = 4 #: Path extended by custom lengths beyond start/end vertex

    def __repr__(self):
        return f'{self.__class__.__name__}.{self.name}'

@public
class RectDirection(Enum):
    """Used by :class:`LayoutRectPoly` and :class:`LayoutRectPath`."""
    Vertical = 0 #: Indicates that shape is encoded with vertical edge first, horizontal edge second.
    Horizontal = 1  #: Indicates that shape is encoded with horizontal edge first, vertical edge second.

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

# Attribute proxy
# ---------------

class AttrProxy:
    """Descriptor that delegates reads to a sub-attribute of another attribute.

    Carries metadata (source_attr, name) so that LayoutInstanceSubcursor
    can retrieve the full source object for coordinate transformation
    before extracting the sub-attribute.
    """
    def __init__(self, source_attr, name):
        self.source_attr = source_attr
        self.name = name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return getattr(getattr(obj, self.source_attr), self.name)

def _rect_proxy(name):
    return AttrProxy('rect', name)

# NamedTuples
# -----------

@public
class GdsLayer(NamedTuple):
    layer: int #: GDS layer number (0...65535)
    data_type: int #: GDS data type number (0...65535)

@public
class RGBColor(NamedTuple):
    r: int #: red component (0...255)
    g: int #: red green (0...255)
    b: int #: red blue (0...255)

    def __str__(self):
        return f"#{self.r:02X}{self.g:02X}{self.b:02X}"

@public
def rgb_color(s) -> RGBColor:
    if not re.match("#[0-9a-fA-F]{6}", s):
        raise ValueError("rgb_color expects string like '#0012EF'.")
    return RGBColor(int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))

def coerce_tuple(target_type, tuple_length):
    def func(val):
        # Not using isinstance(val, tuple) here, since Vec2I/Vec2R is are
        # subclasses of tuple.
        if type(val) == tuple:
            if len(val) != tuple_length:
                raise ValueError(f"Expected tuple with {tuple_length} elements, got {val!r}.")
            return target_type(*val)
        return val
    return func

# Symbol
# ------

class MixinRenderable:
    """Mixin providing SVG rendering for Symbol and Schematic subgraphs."""
    __slots__ = ()

    def render(self, **kwargs) -> 'Renderer':
        from ..schematic.render import render
        return render(self, **kwargs)

    def _repr_svg_(self):
        return self.render().svg().decode('ascii'), {'isolated': False}

    def webdata(self):
        return self.render().webdata()


@public
class Symbol(MixinRenderable, SubgraphRoot):
    """A symbol of an individual cell."""
    view_context = SymbolViewContext
    outline = Attr(Rect4R, factory=coerce_tuple(Rect4R, 4))
    caption = Attr(str)
    cell = Attr(Cell)

    def portmap(self, **kwargs):
        def inserter_func(main, sgu, primary_nid):
            main_nid = main.set(symbol=self.subgraph).insert_into(sgu, primary_nid)
            for k, v in kwargs.items():
                SchemInstanceConn(ref=main_nid, here=v.nid, there=self[k].nid).insert_into(sgu, sgu.nid_generate())
            return main_nid
        return inserter_func

    def place_pins(self, hpadding=3, vpadding=3):
        from ..schematic import symbol_place_pins
        symbol_place_pins(self, hpadding=hpadding, vpadding=vpadding)

@public
class Pin(Node):
    """Pins are single wire connections exposed through a symbol."""
    in_subgraphs = [Symbol]

    pintype = Attr(PinType, default=PinType.Inout)
    pos     = Attr(Vec2R, factory=coerce_tuple(Vec2R, 2))
    align   = Attr(D4, default=D4.R0)

class MixinPolygonalChain:
    def svg_path(self) -> str:
        """Returns SVG path string of polygon."""
        d = []
        vertices = self.vertices()
        x, y = vertices[0].tofloat()
        d.append(f"M{x} {y}")
        for point in vertices[1:-1]:
            x, y = point.tofloat()
            d.append(f"L{x} {y}")
        if vertices[-1] == vertices[0]:
            d.append("Z")
        else:
            x, y = vertices[-1].tofloat()
            d.append(f"L{x} {y}")
        return ' '.join(d)

class MixinClosedPolygon:
    def svg_path(self) -> str:
        """Returns SVG path string of polygon."""
        d = []
        vertices = self.vertices()
        x, y = vertices[0].tofloat()
        d.append(f"M{x} {y}")    
        for point in vertices[1:]:
            x, y = point.tofloat()
            d.append(f"L{x} {y}")
        d.append("Z")
        return ' '.join(d)


class MixinLayoutPinnable:
    """Mixin for layout shapes that can have LayoutPin associations."""
    def create_pin(self, pin):
        """Create a LayoutPin associating this shape with a symbol pin.

        Args:
            pin: Reference to a Pin in the layout's symbol.

        Returns:
            Cursor to the newly created LayoutPin node.
        """
        return self % LayoutPin(pin=pin)


class GenericPoly(Node):
    in_subgraphs = [Symbol]

    def __new__(cls, vertices:list[Vec2R|Vec2I]|int=None, **kwargs):
        """
        Construct a polygon or polygonal chain node, optionally with vertices.

        Args:
            vertices: Vertex specification, one of three forms:
                - ``None``: create the poly node only, no vertex nodes (add
                    vertices later via attribute assignment or constraints).
                - ``list[Vec2R|Vec2I]``: create the poly node and insert one
                    vertex node per list element with positions set.
                - ``int``: create the poly node and insert that many vertex
                    nodes with no positions set, for constraint-based layout.
            **kwargs: Additional attributes passed to the underlying Node.
        """
        main = super().__new__(cls, **kwargs)
        if vertices is None:
            return main
        elif isinstance(vertices, int):
            def inserter_func(sgu, primary_nid):
                main_nid = main.insert_into(sgu, primary_nid)
                for i in range(vertices):
                    cls.vertex_cls(ref=main_nid, order=i).insert_into(sgu, sgu.nid_generate())
                return main_nid
            return FuncInserter(inserter_func)
        else:
            def inserter_func(sgu, primary_nid):
                main_nid = main.insert_into(sgu, primary_nid)
                for i, v in enumerate(vertices):
                    cls.vertex_cls(ref=main_nid, order=i, pos=v).insert_into(sgu, sgu.nid_generate())
                return main_nid
            return FuncInserter(inserter_func)

    def vertices(self) -> 'list[Vec2R | Vec2I]':
        polyvecs = self.subgraph.all(self.vertex_cls.ref_idx.query(self))
        return [polyvec.pos for polyvec in polyvecs]

    def remove_node(self, sgu: 'SubgraphUpdater'):
        for vertex_nid in self.subgraph.all(self.vertex_cls.ref_idx.query(self), wrap_cursor=False):
            sgu.remove_nid(vertex_nid)
        return super().remove_node(sgu)

    def __getitem__(self, idx: int):
        return self.vertices()[idx]


class GenericPolyR(GenericPoly):
    """Base class for polygon or polygonal chain classes (rational numbers)."""

class GenericPolyI(GenericPoly):
    """Base class for polygon or polygonal chain classes (integer numbers)."""

@public
class SymbolPoly(GenericPolyR, MixinPolygonalChain):
    """A drawn polygonal chain in Symbol. For visual purposes only."""

@public
class SymbolArc(Node):
    """A drawn circle or circular segment in Symbol. For visual purposes only."""
    in_subgraphs = [Symbol]

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

# # Schematic
# # ---------

@public
class Schematic(MixinRenderable, SubgraphRoot):
    """A schematic of an individual cell."""
    view_context = SchematicViewContext
    symbol = SubgraphRef(Symbol)
    outline = Attr(Rect4R, factory=coerce_tuple(Rect4R, 4))
    cell = Attr(Cell)
    default_supply = LocalRef('Net', refcheck_custom=lambda val: issubclass(val, Net))
    default_ground = LocalRef('Net', refcheck_custom=lambda val: issubclass(val, Net))

    def resolve_instances(self):
        from ..schematic import resolve_instances
        resolve_instances(self)

    def auto_wire(self):
        from ..schematic import auto_wire
        auto_wire(self)

    def check(self, add_conn_points=False, add_terminal_taps=False):
        from ..schematic import schem_check
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

    ref = LocalRef(Net, optional=False)
    ref_idx = Index(ref)

class SchemInstanceSubcursor(tuple):
    """
    Cursor providing transformed access to Symbol contents from SchemInstance.
    Transforms Symbol-space coordinates to Schematic-space based on the
    instance's position and orientation.
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
        elif isinstance(inner_ret, Node):
            return SchemInstanceSubcursor((self.inst(), inner_ret))
        else:
            return inner_ret


@public
class SchemInstance(Node):
    """
    An instance of a Symbol in a Schematic (foundation for schematic hierarchy).
    """
    in_subgraphs = [Schematic]

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
    
    def __getattribute__(self, name):
        # Upgrade cursor on failed attribute access
        try:
            return super().__getattribute__(name)
        except AttributeError:
            upgraded_cursor = self._upgrade_cursor()
            return getattr(upgraded_cursor, name)

    def _upgrade_cursor(self):
        # Convert this unresolved cursor into a resolved SchemInstanceSubcursor
        node = self.instanceunresolved.resolver()
        for step in self.instancepath:
            if isinstance(step, int):
                node = node[step]
            else:
                node = getattr(node, step)
        return SchemInstanceSubcursor((self.instanceunresolved, node))

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
class SchemInstanceUnresolved(Node):
    """An instance of a Symbol that is not determined yet."""

    class ParamWrapper:
        def __init__(self, inst):
            self._inst = inst

        def __setattr__(self, name, value):
            if name.startswith("_"):
                return super().__setattr__(name, value)
            self._inst % SchemInstanceUnresolvedParameter(name=name, value=value)

    in_subgraphs = [Schematic]

    pos = ConstrainableAttr(Vec2R, placeholder=Vec2LinearTerm,
        factory=coerce_tuple(Vec2R, 2))
    orientation = Attr(D4, default=D4.R0)

    resolver = Attr(object) # closure?

    @property
    def params(self):
        return self.ParamWrapper(self)

    def loc_transform(self):
        return self.pos.transl() * self.orientation

    def __getitem__(self, name):
        return self.__getattr__(name)

    def __getattr__(self, name):
        return SchemInstanceUnresolvedSubcursor((self, name))

@public
class SchemInstanceUnresolvedConn(Node):
    """Unresolved SchemInstanceConn."""
    in_subgraphs = [Schematic]

    ref = LocalRef(SchemInstanceUnresolved, optional=False)
    ref_idx = Index(ref)

    here = LocalRef(Net, optional=False,
        factory=lambda v: v.ref if isinstance(v, SchemPort) else v)
    there = Attr(tuple, optional=False) #: Tuple of str or int = requested path in future symbol

@public
class SchemInstanceUnresolvedParameter(Node):
    in_subgraphs = [Schematic]

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
    ref = LocalRef(Net, optional=False)
    ref_idx = Index(ref)

    pos = Attr(Vec2R, factory=coerce_tuple(Vec2R, 2))
    pos_idx = Index(pos)

@public
class SchemErrorMarker(Node):
    """An error marker indicating a schematic check failure."""
    in_subgraphs = [Schematic]
    ref = LocalRef(Schematic)
    pos = Attr(Vec2R, factory=coerce_tuple(Vec2R, 2))
    align = Attr(D4, default=D4.R0)
    error_type = Attr(SchemErrorType)

# Simulation hierarchy
# --------------------

@public
class SimType(Enum):
    DC = 'dc'
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
    schematic = SubgraphRef(Schematic)
    cell = Attr(Cell)
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
        col = self.sim_data.column(self.freq_field)
        # AC rawfiles store frequency as complex with zero imaginary part;
        # return real values for consumer convenience.
        if col and isinstance(col[0], complex):
            return tuple(v.real for v in col)
        return col

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

    def webdata(self):
        from ..sim.webdata import webdata
        return webdata(self)

@public
class SimNet(Node):
    in_subgraphs = [SimHierarchy]

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

# LayerStack
# ----------

@public
class LayerStack(SubgraphRoot):
    cell = Attr(Cell)
    unit = Attr(R)

@public
class Layer(NonLeafNode):
    in_subgraphs = [LayerStack]
    gdslayer_text = Attr(GdsLayer)
    gdslayer_shapes = Attr(GdsLayer)

    style_fill = Attr(RGBColor)
    style_stroke = Attr(RGBColor)
    style_crossrect = Attr(bool, optional=False, default=False)

    #: Indicates whether the present layer is suitable for pin shapes / text.
    #: This flag affects the behavior of the pinlayer() method.
    is_pinlayer = Attr(bool, optional=False, default=False) 

    def pinlayer(self) -> 'Layer':
        """
        Returns the layer on which pin shapes corresponding to the current
        layer should be placed. This could be the layer itself, or its .pin
        child (e.g. Metal1.pin).
        """
        if self.is_pinlayer:
            return self
        else:
            l = self.pin
            if not l.is_pinlayer:
                raise Exception(f"{l} is found at 'pin' path but does not have is_pinlayer set.")
            return l

    gdslayer_text_index = Index(gdslayer_text, unique=True)
    gdslayer_shapes_index = Index(gdslayer_shapes, unique=True)

    def inline_css(self) -> str:
         return f"fill:{self.style_fill};stroke:{self.style_stroke};"

# RoutingSpec
# -----------

@public
class RoutingSpec(SubgraphRoot):
    """Routing specification for SRouter, decoupled from LayerStack."""
    ref_layers = SubgraphRef(LayerStack, optional=False)

@public
class RoutingSpecLayer(Node):
    """Per-layer routing parameters for SRouter."""
    in_subgraphs = [RoutingSpec]

    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers, optional=False)

    #: route_id determines the routing order. To route from layer n to layer m
    #: (m > n), all layers with route_ids x where m > x > n must be traversed.
    #: route_ids should alternate between metal (even) and vias (odd).
    route_id = Attr(int)

    route_via_width = Attr(int)
    route_via_height = Attr(int)
    route_wire_width = Attr(int)
    route_wire_ext = Attr(int)

    route_id_index = Index(route_id, unique=True)
    layer_index = Index(layer, unique=True)

# Layout
# ------

@public
class Layout(SubgraphRoot):
    """
    Subgraph containing integrated circuit layout elements, possibly including
    hierarchical instances of other Layout subgraphs.
    """
    view_context = LayoutViewContext

    cell = Attr(Cell)
    symbol = SubgraphRef(Symbol) #: All LayoutPins in this subgraph reference this symbol.
    ref_layers = SubgraphRef(LayerStack) #: All .layer attributes of nodes in this subgraph reference this LayerStack.

    def webdata(self):
        from ..layout.webdata import webdata
        return webdata(self)
        #from ..render import render
        #return render(self).webdata()

@public
class LayoutLabel(Node):
    """
    Arbitrary text label, equivalent to GDS TEXT element. When entering layouts,
    prefer :class:`LayoutPin` to raw LayoutLabels.
    """
    in_subgraphs = [Layout]

    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers)
    pos = ConstrainableAttr(Vec2I, factory=coerce_tuple(Vec2I, 2),
        placeholder=Vec2LinearTerm)
    text = Attr(str)

@public
class LayoutPoly(GenericPolyI, MixinClosedPolygon, MixinLayoutPinnable):
    """
    Simple (no self intersection, no holes) polygon with CCW orientation.
    (LayoutPoly cannot represent an open polygonal chain. Thus, the first and
    last vertex should not be identical.)

    At GDS import, the "simple" property is currently assumed, and CW polygons
    are flipped automatically to CCW orientation.
    """
    in_subgraphs = [Layout]

    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers)

class LayoutPathBase(GenericPolyI):
    endtype = Attr(PathEndType, default=PathEndType.Flush, optional=False)
    ext_bgn = Attr(int) #: Mandatory if endtype is PathEndType.Custom, else ignored.
    ext_end = Attr(int) #: Mandatory if endtype is PathEndType.Custom, else ignored.
    width = Attr(int)
    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers, optional=False)

    def __new__(cls, *args, **kwargs):
        if (kwargs.get('ext_bgn') is not None) or (kwargs.get('ext_end') is not None):
            try:
                if kwargs['endtype'] != PathEndType.Custom:
                    raise ValueError("When ext_bgn or ext_end is specified,"
                        " PathEndType must be Custom.")
            except KeyError:
                # Inferred PathEndType:
                kwargs['endtype'] = PathEndType.Custom
        return super().__new__(cls, *args, **kwargs)

@public
class LayoutPath(LayoutPathBase, MixinPolygonalChain, MixinLayoutPinnable):
    """Layout path (polygonal chain with width)."""
    in_subgraphs = [Layout]


@public
class LayoutRectPoly(GenericPolyI, MixinLayoutPinnable):
    """
    Compact rectilinear polygon. Each vertex is connected to its successor
    through two segments. The first segment in start_direction, the second
    segment perpendicular to the first. Each vertex has to differ in both x
    and y coordiante from its successor. The successor of the last vertex is the
    first vertex.

    This representation of a rectilinear polygon requires half the vertices as
    an equivalent LayoutPoly.

    One use case is for rectangles, which this class can represent using just
    two corner vertices.
    """
    in_subgraphs = [Layout]

    start_direction = Attr(RectDirection, default=RectDirection.Horizontal)
    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers)

@public
class LayoutRectPath(LayoutPathBase, MixinLayoutPinnable):
    """
    Compact rectilinear path. Each vertex is connected to its successor
    through two segments. The first segment in start_direction, the second
    segment perpendicular to the first. Each vertex has to differ in both x
    and y coordiante from its successor. The last vertex has no successor
    (i.e. open path).

    This representation of a rectilinear path requires half the vertices as
    an equivalent LayoutPath.
    """
    in_subgraphs = [Layout]

    start_direction = Attr(RectDirection, default=RectDirection.Horizontal)

@public
class LayoutRect(Node, MixinLayoutPinnable):
    """Layout rectangle."""
    in_subgraphs = [Layout]

    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers)
    rect = ConstrainableAttr(Rect4I, factory=coerce_tuple(Rect4I, 4),
        placeholder=Rect4LinearTerm)

    # Delegate Rect4Generic properties:
    lx = _rect_proxy('lx')
    ly = _rect_proxy('ly')
    ux = _rect_proxy('ux')
    uy = _rect_proxy('uy')
    cx = _rect_proxy('cx')
    cy = _rect_proxy('cy')
    width = _rect_proxy('width')
    height = _rect_proxy('height')
    size = _rect_proxy('size')
    center = _rect_proxy('center')
    north = _rect_proxy('north')
    south = _rect_proxy('south')
    east = _rect_proxy('east')
    west = _rect_proxy('west')
    northwest = _rect_proxy('northwest')
    northeast = _rect_proxy('northeast')
    southwest = _rect_proxy('southwest')
    southeast = _rect_proxy('southeast')
    x_extent = _rect_proxy('x_extent')
    y_extent = _rect_proxy('y_extent')

    def contains(self, other):
        if isinstance(other, LayoutRect):
            return self.rect.contains(other.rect)
        return self.rect.contains(other)

class LayoutInstanceSubcursor(tuple):
    """Cursor to go through layout instances, transforming coordinates."""
    def __repr__(self):
        return f"{type(self).__name__}{tuple.__repr__(self)}"

    def hierarchy(self):
        return tuple.__getitem__(self, slice(0, -1))

    def transform_stack(self):
        tran = TD4I()
        for elem in self.hierarchy():
            if isinstance(elem, TD4I):
                tran *= elem
            elif isinstance(elem, LayoutInstance):
                tran *= elem.loc_transform()
            else:
                raise TypeError(f"Unexpected element {elem!r} found in LayoutInstanceSubcursor hierarchy.")
        return tran

    def node(self):
        return tuple.__getitem__(self, -1)

    def needs_instancearray_index(self) -> bool:
        h = self.hierarchy()
        # If there is a LayoutInstanceArray in the hierarchy without a preceding
        # TD4I, we lack an index to the LayoutInstanceArray.
        return isinstance(h[-1], LayoutInstanceArray) \
            and (len(h) < 2 or not isinstance(h[-2], TD4I))

    def add_instancearray_index(self, key) -> 'LayoutInstanceSubcursor':
        array = self.hierarchy()[-1]
        if isinstance(key, tuple):
            if (array.cols is None) or (array.rows is None):
                raise IndexError("Got 2D index to 1D LayoutInstanceArray.")
            col, row = key
        elif isinstance(key, int):
            if (array.cols is None) and (array.rows is None):
                raise ValueError("LayoutInstanceArray has both cols and rows set to None.")
            elif array.cols is None:
                col = None
                row = key
            elif array.rows is None:
                col = key
                row = None
            else:
                raise IndexError("LayoutInstanceArray expected [i, j] index.")
        else:
            raise IndexError("LayoutInstanceArray expected [i] or [i, j] index.")

        # This is written in a weird way to make it supposedly work with
        # LinearTerm-based classes.
        trans = []
        if col is not None:
            # This neat trick gives us the range checking + negative-index logic:
            col = range(array.cols)[col]
            #if col not in range(array.cols):
            #    raise IndexError(f"col = {col} out of {range(array.cols)!r}.")
            trans.append((array.vec_col * col).transl())
        if row is not None:
            row = range(array.rows)[row]
            #if row not in range(array.rows):
            #    raise IndexError(f"row = {row} out of {range(array.rows)!r}.")
            trans.append((array.vec_row * row).transl())
        if len(trans) == 2:
            tran = trans[0] * trans[1]
        else:
            (tran, ) = trans

        # We insert the array element transformation (tran: TD4I) _before_
        # the LayoutInstanceArray element, because it needs to be applied
        # before the LayoutInstanceArray's loc_transform() transformation.
        # (The difference only shows up when the LayoutInstanceArray has
        # an orientation other than R0.)
        return LayoutInstanceSubcursor(self.hierarchy()[:-1]
            + (tran, self.hierarchy()[-1], self.node()))

    def __getitem__(self, key):
        if self.needs_instancearray_index():
            return self.add_instancearray_index(key)
        
        inner_ret = self.node()[key]
        if isinstance(inner_ret, LayoutInstanceSubcursor):
            return LayoutInstanceSubcursor(self.hierarchy() + inner_ret)
        else:
            return LayoutInstanceSubcursor(self.hierarchy() + (inner_ret, ))

    @property
    def parent(self):
        node = self.node()

        if node == node.subgraph.root_cursor:
            hier = self.hierarchy()
            if len(hier) == 1:
                # Leave the subcursor if we are at the first hierarchy level:
                return hier[0]
            else:
                # Otherwise, just drop the last part of the hierarchy:
                return LayoutInstanceSubcursor(hier)
        else:
            return self.__getattr('parent')

    def __getattr__(self, name):
        node = self.node()
        if self.needs_instancearray_index():
            raise AttributeError("Missing index [] for LayoutInstanceArray.")
        # Detect AttrProxy descriptors: delegate through self so transformation
        # happens automatically via the existing __getattr__ path.
        descriptor = getattr(type(node), name, None)
        if isinstance(descriptor, AttrProxy):
            return getattr(getattr(self, descriptor.source_attr), descriptor.name)
        inner_ret = getattr(node, name)
        if isinstance(inner_ret, (Rect4I, Vec2I)):
            return self.transform_stack() * inner_ret
        elif isinstance(inner_ret, Node):
            return LayoutInstanceSubcursor(self.hierarchy() + (inner_ret, ))
        elif isinstance(inner_ret, LayoutInstanceSubcursor):
            return LayoutInstanceSubcursor(self.hierarchy() + inner_ret)
        else:
            return inner_ret

@public
class LayoutInstance(Node):
    """Hierarchical layout instance, equivalent to GDS SRef."""
    in_subgraphs = [Layout]

    pos = ConstrainableAttr(Vec2I, factory=coerce_tuple(Vec2I, 2),
        placeholder=Vec2LinearTerm)
    orientation = Attr(D4, default=D4.R0)
    ref = SubgraphRef(Layout, optional=False) #: Can be a Layout or a frame (which is also a Layout)...

    def subcursor(self):
        return LayoutInstanceSubcursor((self, self.ref))

    def __getitem__(self, name):
        return self.subcursor()[name]

    def __getattr__(self, name):
        return getattr(self.subcursor(), name)

    def loc_transform(self):
        return self.pos.transl() * self.orientation

@public
class LayoutInstanceArray(LayoutInstance):
    """Hierarchical layout instance array, equivalent to GDS ARef."""

    in_subgraphs = [Layout]

    #: Number of columns or None (=1 column). If None, LayoutInstanceSubcursor
    #:  indices are collaposed to row-only.
    cols = Attr(int)

    #: Number of rows or None (=1 row). If None, LayoutInstanceSubcursor
    #: indices are collaposed to column-only.
    rows = Attr(int)

    #: Vector separating instances in adjacent columns. None value is permitted
    #: only if cols is None, too.
    vec_col = Attr(Vec2I, factory=coerce_tuple(Vec2I, 2))

    #: Vector separating instances in adjacent rows. None value is permitted
    #: only if cols is None, too.
    vec_row = Attr(Vec2I, factory=coerce_tuple(Vec2I, 2))

@public
class LayoutPin(Node):
    """
    A LayoutPin associates a particular shape with a Pin of the layout's symbol.
    The advantages to a plain LayoutLabel are: (a) the LayoutPin maintains a
    semantic connection to the symbol, and (b) the LayoutPin can be added to
    a non-pin layer, and a corresponding pin layer shape is created
    automatically by expand_pins (in write_gds or the web viewer).

    The associated shape can be a LayoutPoly, LayoutRectPoly, LayoutRect,
    LayoutPath or LayoutRectPath.
    """
    in_subgraphs = [Layout]

    ref = LocalRef(LayoutPoly|LayoutRectPoly|LayoutPath,
        refcheck_custom=lambda val: issubclass(val, (LayoutPoly, LayoutRectPoly, LayoutRect, LayoutPath, LayoutRectPath)),
        )
    pin = ExternalRef(Pin,
        of_subgraph=lambda c: c.root.symbol,
        optional=False,
        )

# Misc
# ----

@public
class PolyVec2R(Node):
    """One vertex of a Vec2R polygonal chain or polygon."""
    in_subgraphs = [Symbol, Schematic]
    ref    = LocalRef(GenericPolyR, optional=False)
    order   = Attr(int, optional=False) #: Order of the point in the polygonal chain
    pos     = Attr(Vec2R, factory=coerce_tuple(Vec2R, 2))

    ref_idx = Index(ref, sortkey=lambda node: node.order)
    pos_idx = Index(pos)

@public
class PolyVec2I(Node):
    """One vertex of a Vec2I polygonal chain or polygon."""
    in_subgraphs = [Layout]
    ref    = LocalRef(GenericPolyI, optional=False)
    order   = Attr(int, optional=False) #: Order of the point in the polygonal chain
    pos     = ConstrainableAttr(Vec2I, factory=coerce_tuple(Vec2I, 2),
        placeholder=Vec2LinearTerm)

    ref_idx = Index(ref, sortkey=lambda node: node.order)

GenericPolyR.vertex_cls = PolyVec2R
GenericPolyI.vertex_cls = PolyVec2I
