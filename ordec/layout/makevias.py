# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..core import *
from math import floor
from public import public

@public
def makevias(layout: Layout,
        rect: Rect4I,
        layer: Layer,
        size: Vec2I,
        spacing: Vec2I,
        margin: Vec2I=None,
        rows: int=None,
        cols: int=None) -> Rect4I:
    """
    Generates via array in given rectangle area.

    Args:
        layout: Layout to which the vias are added.
        rect: Area in which the via array is generated.
        layer: Layer of generated via array.
        size: Dimensions of individual vias.
        spacing: Spacing between individual vias.
        margin: Spacing between the outmost vias to the rectangle (only relevant
            when rows or cols is not specified).
        rows: Number of rows. If not specified (None), its value is
            automatically determined based on rect, size, spacing and margin.
        cols: Number of columns. If not specified (None), its value is
            automatically determined based on rect, size, spacing and margin.
    """

    if (margin is None) and ((rows is None) or (cols is None)):
        raise ValueError("margin must be set if rows or cols is None.")

    if cols is None:
        cols = floor((rect.width - 2*margin.x + spacing.x) / (size.x + spacing.x))

    if rows is None:
        rows = floor((rect.height - 2*margin.y + spacing.y) / (size.y + spacing.y))

    width = cols*size.x + (cols-1)*spacing.x
    height = rows*size.y + (rows-1)*spacing.y

    x_start = (rect.lx + rect.ux - width) // 2
    y_start = (rect.ly + rect.uy - height) // 2

    for col in range(cols):
        x = x_start + (size.x+spacing.x)*col
        for row in range(rows):
            y = y_start + (size.y+spacing.y)*row
            via = layout % LayoutRect(layer=layer, rect=Rect4I(x, y, x+size.x, y+size.y))

    return Rect4I(x_start, y_start, via.rect.ux, via.rect.uy)
