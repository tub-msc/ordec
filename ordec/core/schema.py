# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from enum import Enum
import math
from functools import partial
from public import populate_all

from .rational import R
from .geoprim import *
from .ordb import *

class PinType(Enum):
    In = 'in'
    Out = 'out'
    Inout = 'inout'

    def __repr__(self):
        return f'{self.__class__.__name__}.{self.name}'

# Misc
# ----

class PolyVec2R(Cursor):
    """
    One element/point of a Vec2R polygonal chain, which can be open or closed.
    A polygonal chain is closed if the last and first element are equivalent.
    """
    ref    = LocalRef('SymbolPoly|SchemWire')
    order   = Attr(int)
    """Order of the point in the polygonal chain"""
    pos     = Attr(Vec2R)

    ref_idx = Index(ref, sortkey=lambda Cursor: Cursor.order)

# Symbol
# ------

class Symbol(SubgraphHead):
    """A symbol of an individual cell."""
    outline = Attr(Rect4R)
    caption = Attr(str)
    cell = Attr('Cell')

    def portmap(cursor, **kwargs):
        def inserter_func(main, sgu):
            main_nid = main.set(symbol=cursor.subgraph).insert(sgu)
            for k, v in kwargs.items():
                SchemInstanceConn(ref=main_nid, here=v.nid, there=cursor[k].nid).insert(sgu)
            return main_nid
        return inserter_func

    def _repr_svg_(cursor):
        from ..render import render
        return render(cursor).svg().decode('ascii'), {'isolated': False}

class Pin(Cursor):
    """
    Pins are single wire connections exposed through a symbol.
    """
    pintype = Attr(PinType, default=PinType.Inout)
    pos     = Attr(Vec2R)
    align   = Attr(D4, default=D4.R0)
 
class SymbolPoly(Cursor):
    def __new__(cls, vertices:list[Vec2R]=None, **kwargs):
        main = super().__new__(cls, **kwargs)
        if vertices == None:
            return main
        else:
            def inserter_func(sgu):
                main_nid = main.insert(sgu)
                for i, v in enumerate(vertices):
                    PolyVec2R(ref=main_nid, order=i, pos=v).insert(sgu)
                return main_nid
            return FuncInserter(inserter_func)

    @property
    def vertices(cursor):
        return cursor.subgraph.all(PolyVec2R.ref_idx.query(cursor.nid))

    def svg_path(cursor) -> str:
        """
        Returns string representation of polygon suitable for
        "d" attribute of SVG <path>.
        """
        d = []
        vertices = [c.pos for c in cursor.vertices]
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


class SymbolArc(Cursor):
    """A drawn circle or circular segment for use in Symbol."""
    pos         = Attr(Vec2R)
    "Center point"
    radius      = Attr(R)
    "Radius of the arc."
    angle_start = Attr(R, default=R(0))
    "Must be less than angle_end and between -1 and 1, with -1 representing -360° and 1 representing 360°."
    angle_end   = Attr(R, default=R(1))
    "Must be greater than angle_start and between -1 and 1, with -1 representing -360° and 1 representing 360°."
    
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

class Net(Cursor):
    pin = ExternalRef(Pin, of_subgraph=lambda c: c.root.symbol)

class Schematic(SubgraphHead):
    """
    A schematic of an individual cell.
    """
    symbol = SubgraphRef(Symbol)
    outline = Attr(Rect4R)
    cell = Attr('Cell')
    default_supply = LocalRef(Net)
    default_ground = LocalRef(Net)

    def _repr_svg_(cursor):
        from ..render import render
        return render(cursor).svg().decode('ascii'), {'isolated': False}

class SchemPort(Cursor):
    """
    Port of a Schematic, corresponding to a Pin of the schematic's Symbol.
    """
    ref = LocalRef(Net)
    ref_idx = Index(ref)
    pos = Attr(Vec2R)
    align = Attr(D4, default=D4.R0)

class SchemWire(SymbolPoly):
    """A drawn schematic wire representing an electrical connection."""
    ref = LocalRef(Net)
    ref_idx = Index(ref)

class SchemInstance(Cursor):
    """
    An instance of a Symbol in a Schematic (foundation for schematic hierarchy).
    """
    pos = Attr(Vec2R)
    orientation = Attr(D4, default=D4.R0)
    symbol = SubgraphRef(Symbol)

    def __new__(cls, connect=None, **kwargs):
        main = super().__new__(cls, **kwargs)
        if connect == None:
            return main
        else:
            return FuncInserter(partial(connect, main))

    def loc_transform(cursor):
        return cursor.pos.transl() * cursor.orientation

    @property
    def conns(cursor):
        return cursor.subgraph.all(SchemInstanceConn.ref_idx.query(cursor.nid))

class SchemInstanceConn(Cursor):
    """
    Maps Pins of a SchemInstance to Nets of its Schematic.
    """
    ref = LocalRef(SchemInstance)
    ref_idx = Index(ref)

    here = LocalRef(Net)
    there = ExternalRef(Pin, of_subgraph=lambda c: c.ref.symbol) # ExternalRef to Pin in SchemInstance.symbol

    ref_pin_idx = CombinedIndex([ref, there], unique=True)

class SchemTapPoint(Cursor):
    """A schematic tap point for connecting points by label, typically visualized using the net's name."""
    ref = LocalRef(Net)
    ref_idx = Index(ref)

    pos = Attr(Vec2R)
    align = Attr(D4, default=D4.R0)

    def loc_transform(cursor):
        return cursor.pos.transl() * cursor.align

class SchemConnPoint(Cursor):
    """A schematic point to indicate a connection at a 3- or 4-way junction of wires."""
    ref = LocalRef(Net)
    ref_idx = Index(ref)

    pos = Attr(Vec2R)

# Simulation hierarchy
# --------------------

def parent_siminstance(c: Cursor) -> Cursor:
    while not isinstance(c, (SimInstance, SimHierarchy)):
        c = c.parent
    return c

class SimNet(Cursor):
    trans_voltage = Attr(list[float])
    trans_current = Attr(list[float])
    dc_voltage = Attr(float)

    eref = ExternalRef(type=Net|Pin, of_subgraph=lambda c: parent_siminstance(c).schematic)

class SimInstance(Cursor):
    dc_current = Attr(float)

    is_leaf = False
    schematic = SubgraphRef(Schematic)
    eref = ExternalRef(SchemInstance, of_subgraph=lambda c: parent_siminstance(c.parent).schematic)

class SimHierarchy(SubgraphHead):
    schematic = SubgraphRef(Schematic)
    cell = Attr('Cell')

# Every class defined in this file is public:
populate_all()
