# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from enum import Enum
from typing import NamedTuple
import re
from public import public

from ..geoprim import *
from ..ordb import *
from ..constraints import *

# Enums
# -----

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
    """Parse a hex color string like '#0012EF' into an RGBColor."""
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

# Source location
# ---------------

@public
class SourceLocInfo(NamedTuple):
    """Source location of the ORD/Python statement that created a node."""
    filename: str
    line: int
    column: int

# Generic polygon machinery
# -------------------------

class MixinPolygonalChain:
    __slots__ = ()

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
    __slots__ = ()

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

WIRE_DOMAIN = 2 << 16

class GenericPoly(Node):
    # Concrete subclasses declare their own in_subgraphs.
    in_subgraphs = []

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
class PolyVec2R(Node):
    """One vertex of a Vec2R polygonal chain or polygon."""
    in_subgraphs = [] # Consuming schema modules append their subgraph roots.
    wire_id = WIRE_DOMAIN | 1
    ref    = LocalRef(GenericPolyR, optional=False)
    order   = Attr(int, optional=False) #: Order of the point in the polygonal chain
    pos     = Attr(Vec2R, factory=coerce_tuple(Vec2R, 2))

    ref_idx = Index(ref, sortkey=lambda node: node.order)
    pos_idx = Index(pos)

@public
class PolyVec2I(Node):
    """One vertex of a Vec2I polygonal chain or polygon."""
    in_subgraphs = [] # Consuming schema modules append their subgraph roots.
    wire_id = WIRE_DOMAIN | 2
    ref    = LocalRef(GenericPolyI, optional=False)
    order   = Attr(int, optional=False) #: Order of the point in the polygonal chain
    pos     = ConstrainableAttr(Vec2I, factory=coerce_tuple(Vec2I, 2),
        placeholder=Vec2LinearTerm)

    ref_idx = Index(ref, sortkey=lambda node: node.order)

GenericPolyR.vertex_cls = PolyVec2R
GenericPolyI.vertex_cls = PolyVec2I
