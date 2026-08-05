# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from public import public

from ..rational import R
from ..geoprim import *
from ..ordb import *
from ..cell import Cell
from ..constraints import *
from ..context import LayoutViewBuilder
from .base import (
    coerce_tuple, AttrProxy, _rect_proxy, GdsLayer, RGBColor, PathEndType,
    MixinPolygonalChain, MixinClosedPolygon, GenericPolyI, PolyVec2I,
)
from .schematic import Symbol, Pin

WIRE_DOMAIN = 4 << 16

class MixinLayoutPinnable:
    """Mixin for layout shapes that can have LayoutPin associations."""
    __slots__ = ()

    def create_pin(self, pin):
        """Create a LayoutPin associating this shape with a symbol pin.

        Args:
            pin: Reference to a Pin in the layout's symbol.

        Returns:
            Cursor to the newly created LayoutPin node.
        """
        return self % LayoutPin(pin=pin)

# LayerStack
# ----------

@public
class LayerStack(SubgraphRoot):
    wire_id = WIRE_DOMAIN | 1
    cell = LiveRef(Cell)
    unit = Attr(R)

@public
class Layer(NonLeafNode):
    in_subgraphs = [LayerStack]
    wire_id = WIRE_DOMAIN | 2
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
    wire_id = WIRE_DOMAIN | 3
    ref_layers = SubgraphRef(LayerStack, optional=False)

@public
class RoutingSpecLayer(Node):
    """Per-layer routing parameters for SRouter."""
    in_subgraphs = [RoutingSpec]
    wire_id = WIRE_DOMAIN | 4

    layer = ExternalRef(Layer, of_subgraph=lambda c: c.root.ref_layers, optional=False)

    #: route_id determines the routing order. To route from layer n to layer m
    #: (m > n), all layers with route_ids x where m > x > n must be traversed.
    #: route_ids should alternate between metal (even) and vias (odd).
    route_id = Attr(int)

    route_via_width = Attr(int)
    route_via_height = Attr(int)

    #: Size of a landing pad that a wire of this layer runs into: it only has
    #: to cover the via enclosure required on all sides, as the wire supplies
    #: the larger endcap enclosure. Unset falls back to route_via_width and
    #: route_via_height, which is what a pad standing on its own requires.
    route_pad_width = Attr(int)
    route_pad_height = Attr(int)

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
    view_builder = LayoutViewBuilder
    wire_id = WIRE_DOMAIN | 5

    cell = LiveRef(Cell)
    symbol = SubgraphRef(Symbol) #: All LayoutPins in this subgraph reference this symbol.
    ref_layers = SubgraphRef(LayerStack) #: All .layer attributes of nodes in this subgraph reference this LayerStack.

    def webdata_static(self):
        from ...layout.webdata import webdata
        return webdata(self)

@public
class LayoutLabel(Node):
    """
    Arbitrary text label, equivalent to GDS TEXT element. When entering layouts,
    prefer :class:`LayoutPin` to raw LayoutLabels.
    """
    in_subgraphs = [Layout]
    wire_id = WIRE_DOMAIN | 6

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
    wire_id = WIRE_DOMAIN | 7

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
    wire_id = WIRE_DOMAIN | 8


@public
class LayoutRect(Node, MixinLayoutPinnable):
    """Layout rectangle."""
    in_subgraphs = [Layout]
    wire_id = WIRE_DOMAIN | 9

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
    wire_id = WIRE_DOMAIN | 10

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
    wire_id = WIRE_DOMAIN | 11

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

    The associated shape can be a LayoutPoly, LayoutRect, or LayoutPath.
    """
    in_subgraphs = [Layout]
    wire_id = WIRE_DOMAIN | 12

    ref = LocalRef(LayoutPoly|LayoutPath,
        refcheck_custom=lambda val: issubclass(val, (LayoutPoly, LayoutRect, LayoutPath)),
        )
    pin = ExternalRef(Pin,
        of_subgraph=lambda c: c.root.symbol,
        optional=False,
        )

# PolyVec2I vertex nodes (defined in .base) may appear in Layout subgraphs:
PolyVec2I.in_subgraphs.append(Layout)
