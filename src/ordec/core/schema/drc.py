# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from public import public

from ..geoprim import *
from ..ordb import *
from ..context import ViewBuilder
from .base import coerce_tuple, PathEndType, GenericPolyI, PolyVec2I
from .layout import Layout

WIRE_DOMAIN = 6 << 16

@public
class DrcReport(SubgraphRoot):
    """DRC report containing design rule check results."""
    view_builder = ViewBuilder
    wire_id = WIRE_DOMAIN | 1

    ref_layout = SubgraphRef(Layout)
    top_cell_name = Attr(str)

    def nresults(self) -> int:
        """Count total DrcItems."""
        return sum(1 for _ in self.all(DrcItem))

    def summary(self) -> dict[str, int]:
        """Category name -> count mapping."""
        counts = {}
        for item in self.all(DrcItem):
            name = item.category.name
            counts[name] = counts.get(name, 0) + 1
        return counts

    def webdata(self, ept):
        from ...layout.drc import webdata
        return webdata(self, ept)


@public
class DrcCategory(Node):
    """Category of DRC violations (e.g., 'Minimum spacing', 'Minimum width')."""
    in_subgraphs = [DrcReport]
    wire_id = WIRE_DOMAIN | 2

    name = Attr(str)
    description = Attr(str, default='')
    parent = LocalRef('DrcCategory', optional=True,
        refcheck_custom=lambda val: issubclass(val, DrcCategory))

    parent_idx = Index(parent)


@public
class DrcCell(Node):
    """Cell of the checked layout hierarchy that DRC violations attach to.

    Analogous to LvsCircuitPair for LVS reports. KLayout deep-mode DRC
    reports each violation once, attached to the cell it occurs in, with
    coordinates in that cell's local space. ref_layout resolves the cell
    name back to its Layout subgraph; None if the name is unresolvable
    (e.g. KLayout variant cells like 'sub$VAR1').
    """
    in_subgraphs = [DrcReport]
    wire_id = WIRE_DOMAIN | 3

    name = Attr(str)
    ref_layout = SubgraphRef(Layout, optional=True)


@public
class DrcItem(Node):
    """Individual DRC violation item within a category."""
    in_subgraphs = [DrcReport]
    wire_id = WIRE_DOMAIN | 4

    category = LocalRef(DrcCategory, optional=False)
    category_idx = Index(category)

    cell = LocalRef(DrcCell, optional=True)
    cell_idx = Index(cell)


@public
class DrcBox(Node):
    """Box geometry in a DRC item."""
    in_subgraphs = [DrcReport]
    wire_id = WIRE_DOMAIN | 5

    item = LocalRef(DrcItem, optional=False)
    item_idx = Index(item, sortkey=lambda node: node.order)

    order = Attr(int, default=0)
    tag = Attr(str, default='')
    rect = Attr(Rect4I, factory=coerce_tuple(Rect4I, 4))


@public
class DrcEdge(Node):
    """Edge geometry in a DRC item."""
    in_subgraphs = [DrcReport]
    wire_id = WIRE_DOMAIN | 6

    item = LocalRef(DrcItem, optional=False)
    item_idx = Index(item, sortkey=lambda node: node.order)

    order = Attr(int, default=0)
    tag = Attr(str, default='')
    p1 = Attr(Vec2I, factory=coerce_tuple(Vec2I, 2))
    p2 = Attr(Vec2I, factory=coerce_tuple(Vec2I, 2))


@public
class DrcEdgePair(Node):
    """Edge pair geometry in a DRC item (e.g., for spacing violations)."""
    in_subgraphs = [DrcReport]
    wire_id = WIRE_DOMAIN | 7

    item = LocalRef(DrcItem, optional=False)
    item_idx = Index(item, sortkey=lambda node: node.order)

    order = Attr(int, default=0)
    tag = Attr(str, default='')
    edge1_p1 = Attr(Vec2I, factory=coerce_tuple(Vec2I, 2))
    edge1_p2 = Attr(Vec2I, factory=coerce_tuple(Vec2I, 2))
    edge2_p1 = Attr(Vec2I, factory=coerce_tuple(Vec2I, 2))
    edge2_p2 = Attr(Vec2I, factory=coerce_tuple(Vec2I, 2))


class DrcPolyBase(GenericPolyI):
    """Base class for DRC polygon nodes."""

    tag = Attr(str, default='')


@public
class DrcPoly(DrcPolyBase):
    """Polygon geometry in a DRC item."""
    in_subgraphs = [DrcReport]
    wire_id = WIRE_DOMAIN | 8
    vertex_cls = PolyVec2I

    item = LocalRef(DrcItem, optional=False)
    item_idx = Index(item, sortkey=lambda node: node.order)

    order = Attr(int, default=0)


class DrcPathBase(GenericPolyI):
    """Base class for DRC path nodes."""

    tag = Attr(str, default='')
    width = Attr(int)
    endtype = Attr(PathEndType, default=PathEndType.Flush)


@public
class DrcPath(DrcPathBase):
    """Path geometry in a DRC item."""
    in_subgraphs = [DrcReport]
    wire_id = WIRE_DOMAIN | 9
    vertex_cls = PolyVec2I

    item = LocalRef(DrcItem, optional=False)
    item_idx = Index(item, sortkey=lambda node: node.order)

    order = Attr(int, default=0)


@public
class DrcText(Node):
    """Text geometry in a DRC item."""
    in_subgraphs = [DrcReport]
    wire_id = WIRE_DOMAIN | 10

    item = LocalRef(DrcItem, optional=False)
    item_idx = Index(item, sortkey=lambda node: node.order)

    order = Attr(int, default=0)
    tag = Attr(str, default='')
    pos = Attr(Vec2I, factory=coerce_tuple(Vec2I, 2))
    text = Attr(str)


@public
class DrcValue(Node):
    """Arbitrary string value in a DRC item."""
    in_subgraphs = [DrcReport]
    wire_id = WIRE_DOMAIN | 11

    item = LocalRef(DrcItem, optional=False)
    item_idx = Index(item, sortkey=lambda node: node.order)

    order = Attr(int, default=0)
    tag = Attr(str, default='')
    value = Attr(str)


# PolyVec2I vertex nodes (defined in .base) may appear in DrcReport subgraphs:
PolyVec2I.in_subgraphs.append(DrcReport)
