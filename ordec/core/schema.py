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

@public
class PinType(Enum):
    In = 'in'
    Out = 'out'
    Inout = 'inout'

    def __repr__(self):
        return f'{self.__class__.__name__}.{self.name}'

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

@public
class PathEndType(Enum):
    """
    Could also be named 'linecap'.
    Custom end sizes (GDS code 1) are not supported at the moment.
    """
    FLUSH = 0 #: 
    SQUARE = 2

@public
class RectDirection(Enum):
    """Used by :class:`LayoutRectPoly` and :class:`LayoutRectPath`."""
    VERTICAL = 0 #: Indicates that shape is encoded with vertical edge first, horizontal edge second.
    HORIZONTAL = 1  #: Indicates that shape is encoded with horizontal edge first, vertical edge second.

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

@public
class Symbol(SubgraphRoot):
    """A symbol of an individual cell."""
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

    def _repr_svg_(self):
        from ..render import render
        return render(self).svg().decode('ascii'), {'isolated': False}

    def webdata(self):
        from ..render import render
        return render(self).webdata()

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


class GenericPoly(Node):
    in_subgraphs = [Symbol]

    def __new__(cls, vertices:list[Vec2R]=None, **kwargs):
        main = super().__new__(cls, **kwargs)
        if vertices is None:
            return main
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
class Schematic(SubgraphRoot):
    """A schematic of an individual cell."""
    symbol = SubgraphRef(Symbol)
    outline = Attr(Rect4R, factory=coerce_tuple(Rect4R, 4))
    cell = Attr(Cell)
    default_supply = LocalRef('Net', refcheck_custom=lambda val: issubclass(val, Net))
    default_ground = LocalRef('Net', refcheck_custom=lambda val: issubclass(val, Net))

    def _repr_svg_(self):
        from ..render import render
        return render(self).svg().decode('ascii'), {'isolated': False}

    def webdata(self):
        from ..render import render
        return render(self).webdata() 

@public
class Net(Node):
    in_subgraphs = [Schematic]
    pin = ExternalRef(Pin, of_subgraph=lambda c: c.root.symbol)
    route = Attr(bool, default=True) #: Controls whether the Net is routed by schematic_routing

    pin_idx = Index(pin)

@public
class SchemPort(Node):
    """
    Port of a Schematic, corresponding to a Pin of the schematic's Symbol.
    """
    in_subgraphs = [Schematic]

    ref = LocalRef(Net, optional=False)
    ref_idx = Index(ref)
    pos = ConstrainableAttr(Vec2R, placeholder=Vec2LinearTerm,
        factory=coerce_tuple(Vec2R, 2))
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

    def __wire_op__(self, here):
        conn = self.instanceunresolved % \
            SchemInstanceUnresolvedConn(here=here, there=self.instancepath)
        return conn
    
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

# Simulation hierarchy
# --------------------

@public
class SimType(Enum):
    DC = 'dc'
    TRAN = 'tran'
    AC = 'ac'

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
            if isinstance(inner_child, Pin) \
                and self.siminst is not None \
                and self.siminst.schematic is not None:
                # Special case: Symbol subcursor is used, but Schematic is
                # available. In this case, we need the nid from the Schematic!
                inner_child = self.siminst.schematic.one(Net.pin_idx.query(inner_child))
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
    time = Attr(tuple)
    freq = Attr(tuple)

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

    def _get_sim_data(self, voltage_attr, current_attr):
        """Helper to extract voltage and current data for different simulation types."""
        voltages = {}
        for sn in self.all(SimNet):
            if (voltage_val := getattr(sn, voltage_attr, None)) is not None:
                voltages[sn.full_path_str()] = voltage_val
        currents = {}
        for si in self.all(SimInstance):
            if (current_val := getattr(si, current_attr, None)) is not None:
                currents[si.full_path_str()] = current_val
        return voltages, currents

    def webdata(self):
        if self.sim_type == SimType.TRAN:
            voltages, currents = self._get_sim_data('trans_voltage', 'trans_current')
            return 'transim', {'time': self.time, 'voltages': voltages, 'currents': currents}
        elif self.sim_type == SimType.AC:
            voltages, currents = self._get_sim_data('ac_voltage', 'ac_current')
            return 'acsim', {'freq': self.freq, 'voltages': voltages, 'currents': currents}
        elif self.sim_type == SimType.DC:
            def fmt_float(val, unit):
                x=str(R(f"{val:.03e}"))+unit
                x=re.sub(r"([0-9])([a-zA-Z])", r"\1 \2", x)
                x=x.replace("u", "μ")
                x=re.sub(r"e([+-]?[0-9]+)", r"×10<sup>\1</sup>", x)
                return x

            dc_voltages = []
            for sn in self.all(SimNet):
                if sn.dc_voltage is None:
                    continue
                dc_voltages.append([sn.full_path_str(), fmt_float(sn.dc_voltage, "V")])
            dc_currents = []
            for si in self.all(SimInstance):
                if si.dc_current is None:
                    continue
                dc_currents.append([si.full_path_str(), fmt_float(si.dc_current, "A")])
            return 'dcsim', {'dc_voltages': dc_voltages, 'dc_currents': dc_currents}
        else:
            return 'nosim', {}

@public
class SimNet(Node):
    in_subgraphs = [SimHierarchy]
    
    parent_inst = LocalRef('SimInstance', optional=True,
        refcheck_custom=lambda val: issubclass(val, SimInstance))

    trans_voltage = Attr(tuple)
    trans_current = Attr(tuple)
    ac_voltage = Attr(tuple)
    ac_current = Attr(tuple)
    dc_voltage = Attr(float)

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
class SimInstance(Node):
    in_subgraphs = [SimHierarchy]

    parent_inst = LocalRef('SimInstance', optional=True,
        refcheck_custom=lambda val: issubclass(val, SimInstance))

    trans_current = Attr(tuple)
    ac_current = Attr(tuple)
    dc_current = Attr(float)

    schematic = SubgraphRef(Schematic,
        typecheck_custom=lambda v: isinstance(v, (Symbol, Schematic)),
        optional=True,
        )
    eref = ExternalRef(SchemInstance,
        of_subgraph=lambda c: c.root.schematic_or_symbol_at(c.parent_inst),
        optional=False,
        )

    parent_eref_idx = CombinedIndex([parent_inst, eref], unique=True)

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

# Layout
# ------

@public
class Layout(SubgraphRoot):
    """
    Subgraph containing integrated circuit layout elements, possibly including
    hierarchical instances of other Layout subgraphs.
    """

    cell = Attr(Cell)
    symbol = SubgraphRef(Symbol) #: All LayoutPins in this subgraph reference this symbol.
    ref_layers = SubgraphRef(LayerStack, optional=False) #: All .layer attributes of nodes in this subgraph reference this LayerStack.

    def webdata(self):
        from ..layout import webdata
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

    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers, optional=False)
    pos = ConstrainableAttr(Vec2I, factory=coerce_tuple(Vec2I, 2),
        placeholder=Vec2LinearTerm)
    text = Attr(str)

@public
class LayoutPoly(GenericPolyI, MixinClosedPolygon):
    """
    Simple (no self intersection, no holes) polygon with CCW orientation.
    (LayoutPoly cannot represent an open polygonal chain. Thus, the first and
    last vertex should not be identical.)

    At GDS import, the "simple" property is currently assumed, and CW polygons
    are flipped automatically to CCW orientation.
    """
    in_subgraphs = [Layout]

    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers, optional=False)

@public
class LayoutPath(GenericPolyI, MixinPolygonalChain):
    """Layout path (polygonal chain with width)."""
    in_subgraphs = [Layout]

    endtype = Attr(PathEndType, default=PathEndType.FLUSH, optional=False)
    width = Attr(int)
    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers, optional=False)

@public
class LayoutRectPoly(GenericPolyI):
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

    start_direction = Attr(RectDirection, default=RectDirection.HORIZONTAL)
    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers, optional=False)

@public
class LayoutRectPath(GenericPolyI):
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

    start_direction = Attr(RectDirection, default=RectDirection.HORIZONTAL)
    endtype = Attr(PathEndType, default=PathEndType.FLUSH)
    width = Attr(int)
    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers, optional=False)

@public
class LayoutRect(Node):
    """Layout rectangle."""
    in_subgraphs = [Layout]

    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers, optional=False)
    rect = ConstrainableAttr(Rect4I, factory=coerce_tuple(Rect4I, 4),
        placeholder=Rect4LinearTerm)

@public
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
        inner_ret = getattr(self.node(), name)
        if self.needs_instancearray_index():
            raise AttributeError("Missing index [] for LayoutInstanceArray.")
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

    Currently, the associated shape must be a LayoutPoly, LayoutRectPoly or
    LayoutRect. LayoutPath or LayoutRectPath are not supported.
    """
    in_subgraphs = [Layout]

    ref = LocalRef(LayoutPoly|LayoutRectPoly|LayoutPath,
        refcheck_custom=lambda val: issubclass(val, (LayoutPoly, LayoutRectPoly, LayoutRect)),
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
    pos     = Attr(Vec2R, optional=False, factory=coerce_tuple(Vec2R, 2))

    ref_idx = Index(ref, sortkey=lambda node: node.order)

@public
class PolyVec2I(Node):
    """One vertex of a Vec2I polygonal chain or polygon."""
    in_subgraphs = [Layout]
    ref    = LocalRef(GenericPolyI, optional=False)
    order   = Attr(int, optional=False) #: Order of the point in the polygonal chain
    pos     = Attr(Vec2I, optional=False, factory=coerce_tuple(Vec2I, 2))

    ref_idx = Index(ref, sortkey=lambda node: node.order)

GenericPolyR.vertex_cls = PolyVec2R
GenericPolyI.vertex_cls = PolyVec2I
