# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from enum import Enum
import math
from functools import partial
from typing import NamedTuple
import re
from public import public

from .rational import R
from .geoprim import *
from .ordb import *
from .cell import Cell

@public
class PinType(Enum):
    In = 'in'
    Out = 'out'
    Inout = 'inout'

    def __repr__(self):
        return f'{self.__class__.__name__}.{self.name}'

@public
class GdsLayer(NamedTuple):
    layer: int
    data_type: int

@public
class RGBColor(NamedTuple):
    r: int
    g: int
    b: int

    def __str__(self):
        return f"#{self.r:02X}{self.g:02X}{self.b:02X}"

@public
def rgb_color(s) -> RGBColor:
    if not re.match("#[0-9a-fA-F]{6}", s):
        raise ValueError("rgb_color expects string like '#0012EF'.")
    return RGBColor(int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))

@public
class PathEndType(Enum):
    """Could also be named 'linecap'."""
    FLUSH = 0
    SQUARE = 2

@public
class RectDirection(Enum):
    VERTICAL = 0
    HORIZONTAL = 1
# Symbol
# ------

@public
class Symbol(SubgraphRoot):
    """A symbol of an individual cell."""
    outline = Attr(Rect4R)
    caption = Attr(str)
    cell = Attr(Cell)

    def portmap(self, **kwargs):
        def inserter_func(main, sgu):
            main_nid = main.set(symbol=self.subgraph).insert_into(sgu)
            for k, v in kwargs.items():
                SchemInstanceConn(ref=main_nid, here=v.nid, there=self[k].nid).insert_into(sgu)
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
    """
    Pins are single wire connections exposed through a symbol.
    """
    in_subgraphs = [Symbol]

    pintype = Attr(PinType, default=PinType.Inout)
    pos     = Attr(Vec2R)
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
        if vertices == None:
            return main
        else:
            def inserter_func(sgu):
                main_nid = main.insert_into(sgu)
                for i, v in enumerate(vertices):
                    cls.vertex_cls(ref=main_nid, order=i, pos=v).insert_into(sgu)
                return main_nid
            return FuncInserter(inserter_func)

    def vertices(self) -> 'list[Vec2R | Vec2I]':
        polyvecs = self.subgraph.all(self.vertex_cls.ref_idx.query(self.nid))
        return [polyvec.pos for polyvec in polyvecs]

    def remove_node(self):
        for vertex in self.subgraph.all(self.vertex_cls.ref_idx.query(self.nid)):
            vertex.remove()
        return super().remove_node()

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

    pos         = Attr(Vec2R) #: Center point
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
    outline = Attr(Rect4R)
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

@public
class SchemPort(Node):
    """
    Port of a Schematic, corresponding to a Pin of the schematic's Symbol.
    """
    in_subgraphs = [Schematic]

    ref = LocalRef(Net, optional=False)
    ref_idx = Index(ref)
    pos = Attr(Vec2R)
    align = Attr(D4, default=D4.R0)

@public
class SchemWire(GenericPolyR, MixinPolygonalChain):
    """A drawn schematic wire representing an electrical connection."""
    in_subgraphs = [Schematic]

    ref = LocalRef(Net, optional=False)
    ref_idx = Index(ref)

@public
class SchemInstance(Node):
    """
    An instance of a Symbol in a Schematic (foundation for schematic hierarchy).
    """
    in_subgraphs = [Schematic]

    pos = Attr(Vec2R)
    orientation = Attr(D4, default=D4.R0)
    symbol = SubgraphRef(Symbol, optional=False)

    def __new__(cls, connect=None, **kwargs):
        main = super().__new__(cls, **kwargs)
        if connect == None:
            return main
        else:
            return FuncInserter(partial(connect, main))

    def loc_transform(self):
        return self.pos.transl() * self.orientation

    @property
    def conns(self):
        return self.subgraph.all(SchemInstanceConn.ref_idx.query(self.nid))

@public
class SchemInstanceConn(Node):
    """Maps Pins of a SchemInstance to Nets of its Schematic."""
    in_subgraphs = [Schematic]

    ref = LocalRef(SchemInstance, optional=False)
    ref_idx = Index(ref)

    here = LocalRef(Net, optional=False)
    there = ExternalRef(Pin, of_subgraph=lambda c: c.ref.symbol, optional=False) # ExternalRef to Pin in SchemInstance.symbol

    ref_pin_idx = CombinedIndex([ref, there], unique=True)

@public
class SchemTapPoint(Node):
    """
    A schematic tap point for connecting points by label, typically visualized
    using the net's name.
    """
    in_subgraphs = [Schematic]

    ref = LocalRef(Net, optional=False)
    ref_idx = Index(ref)

    pos = Attr(Vec2R)
    align = Attr(D4, default=D4.R0)

    def loc_transform(self):
        return self.pos.transl() * self.align

@public
class SchemConnPoint(Node):
    """A schematic point to indicate a connection at a 3- or 4-way junction of wires."""
    in_subgraphs = [Schematic]
    ref = LocalRef(Net, optional=False)
    ref_idx = Index(ref)

    pos = Attr(Vec2R)

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

@public
class SimHierarchy(SubgraphRoot):
    schematic = SubgraphRef(Schematic)
    cell = Attr(Cell)
    sim_type = Attr(SimType)
    time = Attr(tuple)
    freq = Attr(tuple)

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
    trans_voltage = Attr(tuple)
    trans_current = Attr(tuple)
    ac_voltage = Attr(tuple)
    ac_current = Attr(tuple)
    dc_voltage = Attr(float)

    eref = ExternalRef(Net|Pin,
        of_subgraph=lambda c: parent_siminstance(c).schematic,
        optional=False,
        )

@public
class SimInstance(NonLeafNode):
    in_subgraphs = [SimHierarchy]
    trans_current = Attr(tuple)
    ac_current = Attr(tuple)
    dc_current = Attr(float)

    schematic = SubgraphRef(Symbol|Schematic,
        typecheck_custom=lambda v: isinstance(v, (Symbol, Schematic)),
        )
    eref = ExternalRef(SchemInstance,
        of_subgraph=lambda c: parent_siminstance(c.parent).schematic,
        optional=False,
        )

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
    style_crossrect = Attr(bool, default=False)

    gdslayer_text_index = Index(gdslayer_text, unique=True)
    gdslayer_shapes_index = Index(gdslayer_shapes, unique=True)

    def inline_css(self):

         return f"fill:{self.style_fill};stroke:{self.style_stroke};"

# Layout
# ------

@public
class Layout(SubgraphRoot):
    cell = Attr(Cell)
    ref_layers = SubgraphRef(LayerStack, optional=False)

    def webdata(self):
        from ..layout import layout_webdata
        return layout_webdata(self)
        #from ..render import render
        #return render(self).webdata()

@public
class LayoutLabel(Node):
    in_subgraphs = [Layout]

    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers, optional=False)
    pos = Attr(Vec2I)
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
    """
    Layout path (polygonal chain with width).
    """
    in_subgraphs = [Layout]

    endtype = Attr(PathEndType, default=PathEndType.FLUSH)
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
    rect = Attr(Rect4I)

@public
class LayoutInstance(Node):
    """Hierarchical layout  instance, equivalent to GDS SRef."""

    in_subgraphs = [Layout]

    pos = Attr(Vec2I)
    orientation = Attr(D4, default=D4.R0)
    ref = SubgraphRef(Layout, optional=False) #: Can be a Layout or a frame (which is also a Layout)...

    def loc_transform(self):
        return self.pos.transl() * self.orientation

# Misc
# ----

@public
class PolyVec2R(Node):
    """One vertex of a Vec2R polygonal chain or polygon."""
    in_subgraphs = [Symbol, Schematic]
    ref    = LocalRef(GenericPolyR, optional=False)
    order   = Attr(int, optional=False) #: Order of the point in the polygonal chain
    pos     = Attr(Vec2R, optional=False)

    ref_idx = Index(ref, sortkey=lambda node: node.order)

@public
class PolyVec2I(Node):
    """One vertex of a Vec2I polygonal chain or polygon."""
    in_subgraphs = [Layout]
    ref    = LocalRef(GenericPolyI, optional=False)
    order   = Attr(int, optional=False) #: Order of the point in the polygonal chain
    pos     = Attr(Vec2I, optional=False)

    ref_idx = Index(ref, sortkey=lambda node: node.order)

GenericPolyR.vertex_cls = PolyVec2R
GenericPolyI.vertex_cls = PolyVec2I
