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

    The array is centered in rect, so margin is a lower bound on the
    clearance to the rect edges, not the resulting clearance itself: only
    whole vias fit, and the leftover space is split between both sides.
    To place vias flush with an edge, pass a margin of 0 for that axis.

    Either give both rows and cols (fixed array, margin unused), or give
    neither (both derived from margin). Specifying only one is rejected,
    because the margin component of the other axis would then be silently
    ignored.

    Args:
        layout: Layout to which the vias are added.
        rect: Area in which the via array is generated.
        layer: Layer of generated via array.
        size: Dimensions of individual vias.
        spacing: Spacing between individual vias.
        margin: Minimum clearance between the outmost vias and the rect
            edges. Only used to derive rows and cols; it does not constrain
            counts that are given explicitly. Required if rows and cols are
            not given, and rejected if they are.
        rows: Number of rows. If not specified (None), its value is
            automatically determined based on rect, size, spacing and margin.
        cols: Number of columns. If not specified (None), its value is
            automatically determined based on rect, size, spacing and margin.
    """
    if (rows is None) != (cols is None):
        raise ValueError(
            "rows and cols must be given together or not at all: with only "
            "one of them given, the margin of the other axis would be "
            "silently ignored.")

    if rows is None: # ... and cols is None, per the check above.
        if margin is None:
            raise ValueError("margin must be set if rows and cols are not.")
        cols = floor((rect.width - 2*margin.x + spacing.x) / (size.x + spacing.x))
        rows = floor((rect.height - 2*margin.y + spacing.y) / (size.y + spacing.y))
        if rows < 1 or cols < 1:
            raise ValueError(
                f"{rect} (w={rect.width}, h={rect.height}) is too small for "
                f"a single {size.x}x{size.y} via at margin {margin}: "
                f"cols={cols}, rows={rows}.")
    else:
        if margin is not None:
            raise ValueError("margin is unused if both rows and cols are given.")
        if rows < 1 or cols < 1:
            raise ValueError(
                f"rows and cols must be at least 1, got cols={cols}, "
                f"rows={rows}.")

    width = cols*size.x + (cols-1)*spacing.x
    height = rows*size.y + (rows-1)*spacing.y

    x_start = (rect.lx + rect.ux - width) // 2
    y_start = (rect.ly + rect.uy - height) // 2

    for col in range(cols):
        x = x_start + (size.x+spacing.x)*col
        for row in range(rows):
            y = y_start + (size.y+spacing.y)*row
            via = layout % LayoutRect(layer=layer, rect=Rect4I(x, y, x+size.x, y+size.y))

    return Rect4I(x_start, y_start, via.ux, via.uy)
