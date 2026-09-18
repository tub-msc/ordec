# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Placement of the annotation blocks (instance name, cell name, parameters) of
schematic instances, run after wiring.

Each block is placed beside its instance without overlapping wires, ports,
tap points, drawn symbol geometry, pin labels or previously placed blocks.
The symbol's own annotation_pos hint is tried first. Else the block goes to
the spot nearest to the symbol's anchor (its center, shifted a bit towards
the preferred East and North sides, following the instance orientation) that
the empty regions around and inside the symbol's bounding box offer, keeping
away from other instances (see candidate_cost). Where this gets the block
closer, flatter arrangements with several entries per text row are used
instead of the default one entry per row (see arrangements, place_block).
Text is never rotated: blocks always read horizontally.
"""

import logging
import math

from ..core import *
from .render import Renderer, VAlign, annotation_lines, annotation_rows, annotation_row_chars

logger = logging.getLogger(__name__)

CLEARANCE = R(1)/4 #: Minimum spacing between a block and any other shape.
STEP = R(1)/8      #: Cell size of the grid on which empty regions are determined.
PUSH_MARGIN = 2    #: Maximum distance of a block from the symbol body.
#: Offset of the anchor from the body center in symbol directions: decides
#: between sides at equal distance (East over West, North over South).
ANCHOR_SHIFT = Vec2R(R(1)/2, R(1)/4)
CENTER_COST = 0.1  #: Cost per unit of offset between block center and anchor.
#: Cost per step from the default to a flatter arrangement. Well above STEP,
#: so that a block is only flattened for a gain beyond the grid resolution.
ARRANGE_COST = 0.5
AMBIGUITY_COST = 1 #: Cost per unit that a block is too near to a foreign body.
AMBIGUITY_MARGIN = 0.5 #: How much nearer a block should be to its own body.

# Obstacles are float (lx, ly, ux, uy) tuples: cheaper to compare than
# Rect4R in the candidate search.
FloatRect = tuple[float, float, float, float]

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
    arcs, shown pin arrows and pin labels, and fixed SymbolTexts. The outline itself
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
        if trans_local.d4.unflip() in (East, West):
            valign = VAlign.Top
        else:
            valign = VAlign.Bottom
        rects.append(Renderer.label_rect(trans_local, len(pin.full_path_label()), 1, valign=valign))
    for t in s.all(SymbolText):
        if t.kind == AnnotationKind.InstanceName:
            if inst is None:
                continue
            text = inst.full_path_label()
        else:
            text = t.text
        rects.append(Renderer.label_rect(trans * t.pos.transl() * t.align, len(text), 1))
    return rects

def schematic_obstacles(node: Schematic) -> list[Rect4R]:
    """Rectangles covering everything drawn in node except annotation blocks."""
    rects = []
    for wire in node.all(SchemWire):
        v = wire.vertices()
        for a, b in zip(v, v[1:]):
            rects.append(_bbox([a, b]))
    for port in node.all(SchemPort):
        trans = port.pos.transl() * port.align
        # Port arrow (see Renderer.draw_arrow, non-centered) and label.
        rects.append(trans * Rect4R(R(-0.25), R(-0.5), R(0.25), R(0)))
        label = port.ref.pin.full_path_label()
        rects.append(Renderer.label_rect(trans * R180, len(label), 1,
            valign=VAlign.Middle, space=Renderer.port_text_space))
    for tap in node.all(SchemTapPoint):
        trans = tap.loc_transform()
        # Tap glyph (supply/ground glyphs are the largest, up to 1 unit long).
        rects.append(trans * Rect4R(R(-0.375), R(0), R(0.375), R(1)))
        if tap.ref not in (node.default_supply, node.default_ground):
            label = tap.ref.full_path_label()
            rects.append(Renderer.label_rect(trans, len(label), 1,
                valign=VAlign.Middle, space=Renderer.port_text_space))
    for inst in node.all(SchemInstance):
        rects += symbol_obstacles(inst.symbol, inst.loc_transform(), inst)
    return rects

def block_size(rows: list[list]) -> tuple[R, R]:
    """(length, depth) of an annotation block with the given text rows."""
    length = R(Renderer.pin_text_space) + R(Renderer.label_char_width) * max(annotation_row_chars(row) for row in rows)
    depth = R(Renderer.pin_text_space) + R(Renderer.font_size_actual_grid_units) * len(rows)
    return length, depth

def arrangements(lines: list) -> list[tuple[int, R, R]]:
    """
    The arrangements worth trying for a block, as (wrap, length, depth), see
    annotation_rows: for each possible number of text rows the narrowest
    one, from the default (one entry per row) to a single row.
    """
    # Every distinct arrangement has a row of exactly wrap characters.
    wraps = {annotation_row_chars(lines[i:j]) for i in range(len(lines)) for j in range(i + 2, len(lines) + 1)}
    ret = [(0, *block_size(annotation_rows(lines, 0)))]
    n_rows = len(lines)
    for wrap in sorted(wraps):
        rows = annotation_rows(lines, wrap)
        if len(rows) < n_rows:
            n_rows = len(rows)
            ret.append((wrap, *block_size(rows)))
    return ret

def symbol_body(s: Symbol, trans: TD4R, inst: SchemInstance|None) -> Rect4R:
    """Bounding box of the drawn geometry of s under trans (outline if none)."""
    rects = symbol_obstacles(s, trans, inst)
    if not rects:
        return trans * s.outline
    return Rect4R(min(r.lx for r in rects), min(r.ly for r in rects),
        max(r.ux for r in rects), max(r.uy for r in rects))

def hint_rect(s: Symbol, trans: TD4R, length: R, depth: R) -> Rect4R | None:
    """
    Block rectangle for the symbol's annotation_pos hint. The block extends
    from the anchor in the annotation_align direction (East or West) and
    downwards; both directions follow trans, so the block stays on the same
    side of a rotated or mirrored instance, but the text stays horizontal.
    """
    if s.annotation_pos is None:
        return None
    p = trans * s.annotation_pos
    along = trans.d4 * (s.annotation_align * Vec2R(0, 1))
    down = trans.d4 * Vec2R(0, -1)
    if along.x != 0:
        dx, dy = along.x * length, down.y * depth
    else:
        # A 90 degree rotation swaps the roles of the two directions.
        dx, dy = down.x * length, along.y * depth
    return _bbox([p, p + Vec2R(dx, dy)])

def fits(rect: FloatRect, obstacles: list[FloatRect]) -> bool:
    c = float(CLEARANCE)
    lx, ly, ux, uy = rect[0] - c, rect[1] - c, rect[2] + c, rect[3] + c
    for olx, oly, oux, ouy in obstacles:
        if lx < oux and ux > olx and ly < ouy and uy > oly:
            return False
    return True

def rect_gap(a: FloatRect, b: FloatRect) -> float:
    """Manhattan distance between two rectangles, 0 if they touch or overlap."""
    return max(b[0] - a[2], a[0] - b[2], 0) + max(b[1] - a[3], a[1] - b[3], 0)

def candidate_cost(rect: FloatRect, anchor: tuple[float, float], body: FloatRect, foreign: list[FloatRect]) -> float:
    """
    Cost of placing the block at rect: its Manhattan distance from the
    anchor, plus CENTER_COST per unit of offset between its center and the
    anchor, which centers blocks that could slide along the anchor. Both
    terms only grow with the distance from the anchor on either axis, so
    within an empty region, the cheapest spot is the one nearest to the
    anchor on both axes (see place_block).

    On top comes the ambiguity cost: the block should be nearer to its own
    body (bounding box of the symbol) than to the foreign ones (bodies of
    other instances) by at least AMBIGUITY_MARGIN.
    """
    lx, ly, ux, uy = rect
    ax, ay = anchor
    cost = max(lx - ax, ax - ux, 0) + max(ly - ay, ay - uy, 0)
    cost += CENTER_COST * (abs((lx + ux)/2 - ax) + abs((ly + uy)/2 - ay))
    if foreign:
        d_other = min(rect_gap(rect, other) for other in foreign)
        cost += AMBIGUITY_COST * max(0, rect_gap(rect, body) + AMBIGUITY_MARGIN - d_other)
    return cost

def empty_regions(x0: int, y0: int, nx: int, ny: int, obstacles: list[FloatRect]) -> list[tuple[int, int, int, int]]:
    """
    Maximal empty rectangles among obstacles (each inflated by CLEARANCE), on
    a grid of nx x ny STEP-sized cells whose lower left corner is (x0, y0) in
    STEP units. Returned as (lx, ly, ux, uy) in STEP units. A cell counts as
    blocked as soon as an inflated obstacle reaches into it.
    """
    step, c = float(STEP), float(CLEARANCE)
    blocked = [[False]*nx for j in range(ny)]
    for olx, oly, oux, ouy in obstacles:
        i0 = max(math.floor((olx - c)/step) - x0, 0)
        i1 = min(math.ceil((oux + c)/step) - x0, nx)
        j0 = max(math.floor((oly - c)/step) - y0, 0)
        j1 = min(math.ceil((ouy + c)/step) - y0, ny)
        if i0 >= i1:
            continue
        for j in range(j0, j1):
            blocked[j][i0:i1] = [True]*(i1 - i0)

    # Largest-rectangle-in-histogram scan, one histogram per cell row j
    # (heights[i]: number of free cells ending in row j of column i). Each
    # popped stack entry is a rectangle that cannot grow to the left, right
    # or downwards; it is maximal if it cannot grow upwards either.
    regions = []
    heights = [0]*nx
    for j in range(ny):
        for i in range(nx):
            heights[i] = 0 if blocked[j][i] else heights[i] + 1
        stack = [] # (start column, height), heights strictly increasing
        for i in range(nx + 1):
            h = heights[i] if i < nx else 0
            start = i
            while stack and stack[-1][1] > h:
                start, sh = stack.pop()
                if j == ny - 1 or any(blocked[j + 1][start:i]):
                    regions.append((x0 + start, y0 + j + 1 - sh, x0 + i, y0 + j + 1))
            if h > 0 and (not stack or stack[-1][1] < h):
                stack.append((start, h))
    return regions

def clamp(v, lo, hi):
    return max(lo, min(v, hi))

def region_spot(region: tuple[int, int, int, int], length, depth, body, anchor, step, push_margin):
    """
    Lower left corner of a length x depth block at the spot of region (see
    empty_regions, clipped to push_margin around body) that is nearest to
    anchor on both axes: centered on it as far as the region allows. None if
    the block does not fit. Works on float and on R arguments alike.
    """
    lx = max(region[0]*step, body[0] - push_margin - length)
    ly = max(region[1]*step, body[1] - push_margin - depth)
    ux = min(region[2]*step, body[2] + push_margin + length) - length
    uy = min(region[3]*step, body[3] + push_margin + depth) - depth
    if ux < lx or uy < ly:
        return None
    return clamp(anchor[0] - length/2, lx, ux), clamp(anchor[1] - depth/2, ly, uy)

def place_block(s: Symbol, trans: TD4R, inst: SchemInstance|None, obstacles: list[FloatRect], foreign: list[FloatRect]=()) -> tuple[Rect4R, int] | None:
    """
    Block rectangle and arrangement (wrap, see annotation_rows) for symbol s
    drawn under trans (as instance inst or on its own), avoiding obstacles.
    Returns None if the block is empty.

    The hint is tried first, in the default arrangement. Else, the empty
    regions around the symbol body are determined (see empty_regions), and
    every arrangement is tried in every region it fits into, centered on the
    anchor as far as the region allows. The cheapest candidate wins, see
    candidate_cost; each step towards a flatter arrangement costs
    ARRANGE_COST, so the default line breaking is kept unless a flatter
    block gets closer to the symbol. With no fitting candidate at all, the
    default arrangement is put beside the body on the preferred side.
    """
    lines = annotation_lines(s, inst)
    if not lines:
        return None
    body = symbol_body(s, trans, inst)
    sizes = arrangements(lines)

    wrap, length, depth = sizes[0]
    hint = hint_rect(s, trans, length, depth)
    if hint is not None and fits(hint.tofloat(), obstacles):
        return hint, wrap

    # Grid window: the body plus the reach of the largest arrangement.
    reach_x = PUSH_MARGIN + CLEARANCE + max(length for wrap, length, depth in sizes)
    reach_y = PUSH_MARGIN + CLEARANCE + max(depth for wrap, length, depth in sizes)
    x0, y0 = math.floor((body.lx - reach_x)/STEP), math.floor((body.ly - reach_y)/STEP)
    x1, y1 = math.ceil((body.ux + reach_x)/STEP), math.ceil((body.uy + reach_y)/STEP)
    regions = empty_regions(x0, y0, x1 - x0, y1 - y0, obstacles)

    anchor = body.center + trans.d4 * ANCHOR_SHIFT
    # The search runs in floats for speed.
    body_f, anchor_f = body.tofloat(), anchor.tofloat()
    best = None
    for n, (wrap, length, depth) in enumerate(sizes):
        l, d = float(length), float(depth)
        for region in regions:
            pos = region_spot(region, l, d, body_f, anchor_f, float(STEP), float(PUSH_MARGIN))
            if pos is None:
                continue
            x, y = pos
            cost = candidate_cost((x, y, x + l, y + d), anchor_f, body_f, foreign) + ARRANGE_COST*n
            if best is None or cost < best[0]:
                best = cost, n, region

    pos = None
    if best is not None:
        cost, n, region = best
        wrap, length, depth = sizes[n]
        # Exact arithmetic for the result; None if float and exact disagree
        # on a block that barely fits.
        pos = region_spot(region, length, depth, tuple(body), tuple(anchor), STEP, PUSH_MARGIN)
    if pos is None:
        if inst is not None:
            logger.warning("No free spot for the annotation block of %s.", inst.full_path_label())
        wrap, length, depth = sizes[0]
        side = trans.d4 * Vec2R(1, 0)
        pos = (body.cx - length/2 + side.x*(body.width/2 + CLEARANCE + length/2),
            body.cy - depth/2 + side.y*(body.height/2 + CLEARANCE + depth/2))
    x, y = pos
    return Rect4R(x, y, x + length, y + depth), wrap

def rect_anchor(rect: Rect4R, body: Rect4R) -> TD4R:
    """
    Anchor (annotation_pos and annotation_align) that draws the block in
    rect. Blocks left of the center of the symbol body are right-aligned
    (West), so that their text ends at the symbol like the text of the other
    blocks starts at it.
    """
    if rect.cx < body.cx:
        return rect.northeast.transl() * West
    return rect.northwest.transl() * East

def block_rects(node: Schematic) -> dict[int, tuple[Rect4R, int]]:
    """
    Block rectangles and arrangements (wrap) of all instances of node with a
    non-empty block, by instance nid. Instances with an explicit
    annotation_pos keep it; the others are placed greedily in instance
    order, seeing the blocks placed before them as obstacles.
    """
    from .render import annotation_extent
    obstacles = [r.tofloat() for r in schematic_obstacles(node)]
    bodies = {inst.nid: symbol_body(inst.symbol, inst.loc_transform(), inst).tofloat()
        for inst in node.all(SchemInstance)}
    rects = {}
    for inst in node.all(SchemInstance):
        trans = inst.loc_transform()
        if inst.annotation_pos is None:
            foreign = [body for nid, body in bodies.items() if nid != inst.nid]
            placed = place_block(inst.symbol, trans, inst, obstacles, foreign)
        else:
            placed = annotation_extent(inst.symbol, trans, inst), inst.annotation_wrap
        if placed is None or placed[0] is None:
            continue
        rects[inst.nid] = placed
        obstacles.append(placed[0].tofloat())
    return rects

def place_annotations(node: Schematic):
    """
    Sets annotation_pos, annotation_align and annotation_wrap of every
    SchemInstance that has no annotation_pos, see block_rects, and extends
    node.outline over all blocks.
    """
    rects = block_rects(node)
    outline = node.outline
    for inst in node.all(SchemInstance):
        if inst.nid not in rects:
            continue
        rect, wrap = rects[inst.nid]
        if inst.annotation_pos is None:
            anchor = rect_anchor(rect, symbol_body(inst.symbol, inst.loc_transform(), inst))
            inst.annotation_pos = anchor.transl
            inst.annotation_align = anchor.d4
            inst.annotation_wrap = wrap
        if outline is not None:
            outline = outline.extend(rect.southwest).extend(rect.northeast)
    node.outline = outline
