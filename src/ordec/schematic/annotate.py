# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Geometry of the annotation blocks (instance name, cell name, parameters) of
schematic instances: the extent of a drawn symbol and the rectangle of a
block at a given anchor.
"""

import math

from ..core import *
from .render import Renderer, SchematicRenderer, annotation_lines, annotation_row_chars, stack_label_frame, transform_align

def _bbox(points) -> Rect4R:
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return Rect4R(min(xs), min(ys), max(xs), max(ys))

def arc_bbox(arc: SymbolArc) -> Rect4R:
    """
    Bounding box of the drawn part of arc (start, end and the axis crossings
    in between). Symbols like OR gates draw short segments of large circles,
    whose full circle would block far more than what is visible.
    """
    angles = [arc.angle_start, arc.angle_end]
    k = math.ceil(arc.angle_start * 4)
    while k / 4 < arc.angle_end:
        angles.append(k / 4)
        k += 1
    points = [arc.pos + Vec2R(arc.radius * math.cos(2*math.pi*a), arc.radius * math.sin(2*math.pi*a))
        for a in angles]
    return _bbox(points)

def symbol_obstacles(s: Symbol, trans: TD4R, inst: SchemInstance|None = None) -> list[Rect4R]:
    """
    Rectangles covering the drawn geometry of symbol s under trans: polygons,
    arcs, shown pin arrows and pin labels, and fixed annotation stacks. The outline itself
    is not an obstacle, so blocks may use empty outline space.
    """
    rects = []
    for poly in s.all(SymbolPoly):
        rects.append(trans * _bbox(poly.vertices()))
    for arc in s.all(SymbolArc):
        rects.append(trans * arc_bbox(arc))
    for pin in s.all(Pin):
        # Same frame as Renderer.draw_pin: the stub is a 0.4 x 0.4 arrow
        # centered on the pin, the label hangs off it.
        trans_local = trans * pin.pos.transl() * R180 * pin.align
        if pin.show_arrow:
            rects.append(trans_local * Rect4R(R(-0.2), R(-0.2), R(0.2), R(0.2)))
        if not pin.show_label:
            continue
        label_trans, halign, valign, space = SchematicRenderer.pin_label_frame(pin, trans_local)
        rects.append(Renderer.label_rect(label_trans, len(pin.full_path_label()), 1, halign=halign, valign=valign, space=space))
    for stack in s.all(SymbolAnnotationStack):
        lines = annotation_lines(s, inst, stack)
        if lines:
            frame, halign, valign = stack_label_frame(stack, trans)
            rects.append(Renderer.label_rect(frame, max(len(text) for text, kind in lines),
                len(lines), halign=halign, valign=valign))
    return rects

def block_size(rows: list[list]) -> tuple[R, R]:
    """(length, depth) of an annotation block with the given text rows."""
    length = R(Renderer.pin_text_space) + R(Renderer.label_char_width) * max(annotation_row_chars(row) for row in rows)
    depth = R(Renderer.pin_text_space) + R(Renderer.font_size_actual_grid_units) * len(rows)
    return length, depth

def symbol_body(s: Symbol, trans: TD4R, inst: SchemInstance|None) -> Rect4R:
    """Bounding box of the drawn geometry of s under trans (outline if none)."""
    rects = symbol_obstacles(s, trans, inst)
    if not rects:
        return trans * s.outline
    return Rect4R(min(r.lx for r in rects), min(r.ly for r in rects),
        max(r.ux for r in rects), max(r.uy for r in rects))

def hint_rect(trans: TD4R, length: R, depth: R, pos: Vec2R, halign: HAlign) -> Rect4R:
    """
    Block rectangle for an anchor at pos (in symbol coordinates). The block
    extends from pos to the side given by halign and downwards; both follow
    trans (see transform_align), so the block stays on the same side of a
    rotated or mirrored instance, but the text stays horizontal.
    """
    halign, valign = transform_align(halign, VAlign.Top, trans)
    x = {HAlign.Left: 0, HAlign.Center: -length/2, HAlign.Right: -length}[halign]
    y = {VAlign.Bottom: 0, VAlign.Middle: -depth/2, VAlign.Top: -depth}[valign]
    p = trans * pos + Vec2R(x, y)
    return Rect4R(p.x, p.y, p.x + length, p.y + depth)

def rect_anchor(rect: Rect4R, body: Rect4R) -> tuple[Vec2R, HAlign]:
    """
    Anchor (annotation_pos and annotation_halign) that draws the block in
    rect. Blocks left of the center of the symbol body are right-aligned, so
    that their text ends at the symbol like the text of the other blocks
    starts at it.
    """
    if rect.cx < body.cx:
        return rect.northeast, HAlign.Right
    return rect.northwest, HAlign.Left
