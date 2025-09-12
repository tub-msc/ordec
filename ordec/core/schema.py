# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from enum import Enum
import math
from functools import partial
from typing import NamedTuple
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
                    PolyVec2R(ref=main_nid, order=i, pos=v).insert_into(sgu)
                return main_nid
            return FuncInserter(inserter_func)

    @property
    def vertices(self):
        return self.subgraph.all(PolyVec2R.ref_idx.query(self.nid))

    def svg_path(self) -> str:
        """
        Returns string representation of polygon suitable for
        "d" attribute of SVG <path>.
        """
        d = []
        vertices = [c.pos for c in self.vertices]
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

@public
class SymbolPoly(GenericPoly):
    pass

@public
class SymbolArc(Node):
    """A drawn circle or circular segment for use in Symbol."""
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
    """
    A schematic of an individual cell.
    """
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

    ref = LocalRef(Net)
    ref_idx = Index(ref)
    pos = Attr(Vec2R)
    align = Attr(D4, default=D4.R0)

@public
class SchemWire(GenericPoly):
    """A drawn schematic wire representing an electrical connection."""
    in_subgraphs = [Schematic]

    ref = LocalRef(Net)
    ref_idx = Index(ref)

@public
class SchemInstance(Node):
    """
    An instance of a Symbol in a Schematic (foundation for schematic hierarchy).
    """
    in_subgraphs = [Schematic]

    pos = Attr(Vec2R)
    orientation = Attr(D4, default=D4.R0)
    symbol = SubgraphRef(Symbol)

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
    """
    Maps Pins of a SchemInstance to Nets of its Schematic.
    """
    in_subgraphs = [Schematic]

    ref = LocalRef(SchemInstance)
    ref_idx = Index(ref)

    here = LocalRef(Net)
    there = ExternalRef(Pin, of_subgraph=lambda c: c.ref.symbol) # ExternalRef to Pin in SchemInstance.symbol

    ref_pin_idx = CombinedIndex([ref, there], unique=True)

@public
class SchemTapPoint(Node):
    """A schematic tap point for connecting points by label, typically visualized using the net's name."""
    in_subgraphs = [Schematic]

    ref = LocalRef(Net)
    ref_idx = Index(ref)

    pos = Attr(Vec2R)
    align = Attr(D4, default=D4.R0)

    def loc_transform(self):
        return self.pos.transl() * self.align

@public
class SchemConnPoint(Node):
    """A schematic point to indicate a connection at a 3- or 4-way junction of wires."""
    in_subgraphs = [Schematic]
    ref = LocalRef(Net)
    ref_idx = Index(ref)

    pos = Attr(Vec2R)

# Simulation hierarchy
# --------------------

def parent_siminstance(c: Node) -> Node:
    while not isinstance(c, (SimInstance, SimHierarchy)):
        c = c.parent
    return c

@public
class SimHierarchy(SubgraphRoot):
    schematic = SubgraphRef(Schematic)
    cell = Attr(Cell)

    def webdata(self):
        def fmt_float(val, unit):
            import re
            x=str(R(f"{val:.03e}"))+unit
            x=re.sub(r"([0-9])([a-zA-Z])", r"\1 \2", x)
            x=x.replace("u", "μ")
            x=re.sub(r"e([+-]?[0-9]+)", r"×10<sup>\1</sup>", x)
            return x

        dc_voltages = []
        for sn in self.all(SimNet):
            if not sn.dc_voltage:
                continue
            dc_voltages.append([sn.full_path_str(), fmt_float(sn.dc_voltage, "V")])
        dc_currents = []
        for si in self.all(SimInstance):
            if not si.dc_current:
                continue
            dc_currents.append([si.full_path_str(), fmt_float(si.dc_current, "A")])
        return 'dcsim', {'dc_voltages': dc_voltages, 'dc_currents': dc_currents}

@public
class SimNet(Node):
    in_subgraphs = [SimHierarchy]
    trans_voltage = Attr(tuple)
    trans_current = Attr(tuple)
    dc_voltage = Attr(float)

    eref = ExternalRef(Net|Pin, of_subgraph=lambda c: parent_siminstance(c).schematic)

@public
class SimInstance(NonLeafNode):
    in_subgraphs = [SimHierarchy]
    dc_current = Attr(float)

    schematic = SubgraphRef(Symbol|Schematic, typecheck_custom=lambda v: isinstance(v, (Symbol, Schematic)))
    eref = ExternalRef(SchemInstance, of_subgraph=lambda c: parent_siminstance(c.parent).schematic)

# LayerStack
# ----------

@public
class LayerStack(SubgraphRoot):
    cell = Attr(Cell)

@public
class Layer(NonLeafNode):
    in_subgraphs = [LayerStack]
    gdslayer_text = Attr(GdsLayer)
    gdslayer_shapes = Attr(GdsLayer)

    style_color = Attr(str, default="#ffffff")

    gdslayer_text_index = Index(gdslayer_text, unique=True)
    gdslayer_shapes_index = Index(gdslayer_shapes, unique=True)

    def inline_css(self):
         return f"fill:{self.style_color};"

# Layout
# ------

@public
class Layout(SubgraphRoot):
    cell = Attr(Cell)
    ref_layers = SubgraphRef(LayerStack)

    def webdata(self):
        from ..layout import layout_webdata
        return layout_webdata(self)
        #from ..render import render
        #return render(self).webdata()

@public
class Label(Node):
    in_subgraphs = [Layout]

    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers)
    pos = Attr(Vec2R)
    text = Attr(str)

@public
class LayoutPoly(GenericPoly):
    """
    Simple polygon with CCW orientation.

    At GDS import, simplicity is assumed currently assuemed, and CW polygons are
    flipped automatically.
    """
    in_subgraphs = [Layout]

    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers)


# Misc
# ----

@public
class PolyVec2R(Node):
    """
    One element/point of a Vec2R polygonal chain, which can be open or closed.
    A polygonal chain is closed if the last and first element are equivalent.
    """
    in_subgraphs = [Symbol, Schematic, Layout]
    ref    = LocalRef(SymbolPoly, refcheck_custom=lambda v:True)
    order   = Attr(int) #: Order of the point in the polygonal chain
    pos     = Attr(Vec2R)

    ref_idx = Index(ref, sortkey=lambda node: node.order)
