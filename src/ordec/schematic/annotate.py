# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Placement of the annotation blocks (instance name, cell name, parameters) of
schematic instances, run after wiring.

Each block is placed beside its instance without overlapping wires, ports,
tap points, drawn symbol geometry, pin labels or previously placed blocks.
The block goes to the most preferred side of the symbol that has room for
it (see preferred_sides): for drawn symbols East before North, West and
South, for box symbols North first. There, it aims at the spot nearest to
the symbol's center that the empty regions offer, except for box symbols on
the North side: above the top left corner, flush with the left edge, like
the reference designators of ICs in common schematic conventions. Keeping
away from other instances takes precedence over the side (see
candidate_cost). Where this gets the block closer, flatter arrangements
with several entries per text row are used instead of the default one entry
per row (see arrangements, place_block). Text is never rotated: blocks
always read horizontally.
"""

import logging
import math

from ..core import *
from .render import Renderer, SchematicRenderer, annotation_lines, annotation_rows, annotation_row_chars, stack_label_frame, annotation_extent

logger = logging.getLogger(__name__)

#: Minimum horizontal and vertical spacing between a block and any other
#: shape. Less is needed vertically, where the line height of the text
#: already leaves room above and below the glyphs.
CLEARANCE_X = R(1)/4
CLEARANCE_Y = R(1)/8
STEP = R(1)/8      #: Cell size of the grid on which empty regions are determined.
PUSH_MARGIN = 2    #: Maximum distance of a block from the symbol body.
#: Offset of the anchor from the body center towards the East and North
#: sides (see preferred_sides), except for the corner of box symbols.
ANCHOR_SHIFT = Vec2R(R(1)/2, R(1)/4)
#: Cost per rank of the side of the body a block is on (see preferred_sides).
#: Well above any distance within the search window, so that a block only
#: moves to a less preferred side if the preferred one has no room.
SIDE_COST = 20
CENTER_COST = 0.1  #: Cost per unit of offset between block center and anchor.
#: Cost per step from the default to a flatter arrangement. Well above STEP,
#: so that a block is only flattened for a gain beyond the grid resolution.
ARRANGE_COST = 0.5
#: Cost per unit that a block is too near to a foreign body. Well above
#: SIDE_COST: a block rather goes to a less preferred side than where it
#: could be taken for another instance's.
AMBIGUITY_COST = 100
AMBIGUITY_MARGIN = 0.5 #: How much nearer a block should be to its own body.
#: Cost per unit of area that a block without empty spot covers of other
#: shapes (see least_covered_spot).
COVER_COST = 10
FALLBACK_STEP = R(1)/2 #: Grid of the candidates of least_covered_spot.

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

def pin_obstacles(pin: Pin, trans: TD4R) -> list[Rect4R]:
    """Rectangles covering the shown arrow and label of pin under trans."""
    # Same frame as Renderer.draw_pin: the stub is a 0.4 x 0.4 arrow
    # centered on the pin, the label hangs off it.
    trans_local = trans * pin.pos.transl() * R180 * pin.orient
    rects = []
    if pin.show_arrow:
        rects.append(trans_local * Rect4R(R(-0.2), R(-0.2), R(0.2), R(0.2)))
    if pin.show_label:
        label_trans, halign, valign, space = SchematicRenderer.pin_label_frame(pin, trans_local)
        rects.append(Renderer.label_rect(label_trans, len(pin.full_path_label()), 1, halign=halign, valign=valign, space=space))
    return rects

def symbol_obstacles(s: Symbol, trans: TD4R, inst: SchemInstance|None = None) -> list[Rect4R]:
    """
    Rectangles covering the drawn geometry of symbol s under trans: polygons,
    arcs, shown pin arrows and pin labels, and fixed annotation stacks. The
    outline itself is not an obstacle, so blocks may use empty outline space.
    """
    rects = []
    for poly in s.all(SymbolPoly):
        rects.append(trans * _bbox(poly.vertices()))
    for arc in s.all(SymbolArc):
        rects.append(trans * arc_bbox(arc))
    for pin in s.all(Pin):
        rects += pin_obstacles(pin, trans)
    for stack in s.all(SymbolAnnotationStack):
        lines = annotation_lines(s, inst, stack)
        if lines:
            frame, halign, valign = stack_label_frame(stack, trans)
            rects.append(Renderer.label_rect(frame, max(len(text) for text, svg_class in lines),
                len(lines), halign=halign, valign=valign))
    return rects

def schematic_obstacles(node: Schematic) -> list[Rect4R]:
    """Rectangles covering everything drawn in node except annotation blocks."""
    rects = []
    for wire in node.all(SchemWire):
        v = wire.vertices()
        for a, b in zip(v, v[1:]):
            rects.append(_bbox([a, b]))
    for port in node.all(SchemPort):
        trans = port.pos.transl() * port.orient
        # Port arrow (see SchematicRenderer.draw_schem_port) and label.
        overlap = SchematicRenderer.port_overlap(port.ref.pin.pintype)
        rects.append(trans * Rect4R(R(-0.25), R(-0.5) + overlap, R(0.25), overlap))
        label = port.ref.pin.full_path_label()
        rects.append(Renderer.label_rect(trans * R180, len(label), 1,
            valign=VAlign.Middle, space=Renderer.port_text_space - float(overlap)))
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
    """
    (length, depth) of an annotation block with the given text rows. The
    text fills the block (see annotation_anchor), CLEARANCE_X and
    CLEARANCE_Y keep it apart from other shapes.
    """
    length = R(Renderer.label_char_width) * max(annotation_row_chars(row) for row in rows)
    depth = R(Renderer.font_size_actual_grid_units) * len(rows)
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

def fits(rect: FloatRect, obstacles: list[FloatRect]) -> bool:
    cx, cy = float(CLEARANCE_X), float(CLEARANCE_Y)
    lx, ly, ux, uy = rect[0] - cx, rect[1] - cy, rect[2] + cx, rect[3] + cy
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

def covered_area(rect: FloatRect, obstacles: list[FloatRect]) -> float:
    """
    Area of rect covered by obstacles inflated by CLEARANCE_X and
    CLEARANCE_Y, counted once per obstacle. Wires (zero-width obstacles)
    cover little, labels and symbol drawings much.
    """
    cx, cy = float(CLEARANCE_X), float(CLEARANCE_Y)
    lx, ly, ux, uy = rect
    area = 0.0
    for olx, oly, oux, ouy in obstacles:
        w = min(ux, oux + cx) - max(lx, olx - cx)
        h = min(uy, ouy + cy) - max(ly, oly - cy)
        if w > 0 and h > 0:
            area += w*h
    return area

def least_covered_spot(sizes: list[tuple[int, R, R]], body: Rect4R, anchor: Vec2R, obstacles: list[FloatRect], foreign: list[FloatRect]) -> tuple[int, tuple[R, R]]:
    """
    Fallback of place_block for blocks without empty spot: the arrangement
    (index into sizes) and lower left corner, on a FALLBACK_STEP grid within
    PUSH_MARGIN around body, that cover the least of the obstacles (see
    covered_area, COVER_COST), with candidate_cost on top.
    """
    # Only obstacles reaching into the window of all candidates matter.
    reach_x = PUSH_MARGIN + float(CLEARANCE_X) + float(max(l for w, l, d in sizes))
    reach_y = PUSH_MARGIN + float(CLEARANCE_Y) + float(max(d for w, l, d in sizes))
    wlx, wly, wux, wuy = float(body.lx) - reach_x, float(body.ly) - reach_y, \
        float(body.ux) + reach_x, float(body.uy) + reach_y
    near = [o for o in obstacles if o[0] < wux and o[2] > wlx and o[1] < wuy and o[3] > wly]
    body_f, anchor_f = body.tofloat(), anchor.tofloat()
    best = None
    for n, (wrap, length, depth) in enumerate(sizes):
        nx = math.floor((body.width + 2*PUSH_MARGIN + length) / FALLBACK_STEP)
        ny = math.floor((body.height + 2*PUSH_MARGIN + depth) / FALLBACK_STEP)
        for i in range(nx + 1):
            for j in range(ny + 1):
                x = body.lx - PUSH_MARGIN - length + i*FALLBACK_STEP
                y = body.ly - PUSH_MARGIN - depth + j*FALLBACK_STEP
                rect = (float(x), float(y), float(x + length), float(y + depth))
                cost = COVER_COST*covered_area(rect, near) \
                    + candidate_cost(rect, anchor_f, body_f, foreign) + ARRANGE_COST*n
                if best is None or cost < best[0]:
                    best = cost, n, (x, y)
    cost, n, pos = best
    return n, pos

def empty_regions(x0: int, y0: int, nx: int, ny: int, obstacles: list[FloatRect]) -> list[tuple[int, int, int, int]]:
    """
    Maximal empty rectangles among obstacles (each inflated by CLEARANCE_X
    and CLEARANCE_Y), on
    a grid of nx x ny STEP-sized cells whose lower left corner is (x0, y0) in
    STEP units. Returned as (lx, ly, ux, uy) in STEP units. A cell counts as
    blocked as soon as an inflated obstacle reaches into it.
    """
    step, cx, cy = float(STEP), float(CLEARANCE_X), float(CLEARANCE_Y)
    blocked = [[False]*nx for j in range(ny)]
    for olx, oly, oux, ouy in obstacles:
        i0 = max(math.floor((olx - cx)/step) - x0, 0)
        i1 = min(math.ceil((oux + cx)/step) - x0, nx)
        j0 = max(math.floor((oly - cy)/step) - y0, 0)
        j1 = min(math.ceil((ouy + cy)/step) - y0, ny)
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

def preferred_sides(d4: D4, box: bool) -> list[tuple[int, int]]:
    """
    Sides of the body as unit vectors, in the order in which blocks prefer
    them: East, North, West, South, or for box symbols North, East, West,
    South. Where the instance turns the symbol's x axis to the West
    (mirrored or rotated by 180 degrees), East and West swap, so that e.g.
    mirrored transistors keep their blocks on the outer side and the North
    blocks of box symbols are flush with the right edge; North and South
    likewise for the y axis. Rotations by 90 degrees keep the default order.
    """
    x = -1 if (d4 * Vec2R(1, 0)).x < 0 else 1
    y = -1 if (d4 * Vec2R(0, 1)).y < 0 else 1
    if box:
        return [(0, y), (x, 0), (-x, 0), (0, -y)]
    return [(x, 0), (0, y), (-x, 0), (0, -y)]

def region_spot(region: tuple[int, int, int, int], length, depth, body, anchor, step, push_margin, side=None):
    """
    Lower left corner of a length x depth block at the spot of region (see
    empty_regions, clipped to push_margin around body and, if given, to the
    side of body, see preferred_sides) that is nearest to anchor on both
    axes: centered on it as far as the region allows. A block on a side is
    beyond the center line of body and level with it: e.g. on the East
    side, it is right of the center and its own center is within the height
    of body. This includes empty space within the bounding box of body. None
    if the block does not fit. Works on float and on R arguments alike.
    """
    lx = max(region[0]*step, body[0] - push_margin - length)
    ly = max(region[1]*step, body[1] - push_margin - depth)
    ux = min(region[2]*step, body[2] + push_margin + length) - length
    uy = min(region[3]*step, body[3] + push_margin + depth) - depth
    cx, cy = (body[0] + body[2])/2, (body[1] + body[3])/2
    if side in ((1, 0), (-1, 0)):
        if side == (1, 0):
            lx = max(lx, cx)
        else:
            ux = min(ux, cx - length)
        ly = max(ly, body[1] - depth/2)
        uy = min(uy, body[3] - depth/2)
    elif side in ((0, 1), (0, -1)):
        if side == (0, 1):
            ly = max(ly, cy)
        else:
            uy = min(uy, cy - depth)
        lx = max(lx, body[0] - length/2)
        ux = min(ux, body[2] - length/2)
    if ux < lx or uy < ly:
        return None
    return clamp(anchor[0] - length/2, lx, ux), clamp(anchor[1] - depth/2, ly, uy)

def place_block(s: Symbol, trans: TD4R, inst: SchemInstance|None, obstacles: list[FloatRect], foreign: list[FloatRect]=()) -> tuple[Rect4R, int, HAlign] | None:
    """
    Block rectangle and arrangement (wrap, see annotation_rows) for symbol s
    drawn under trans (as instance inst or on its own), avoiding obstacles.
    Returns None if the block is empty, else the block rectangle, the
    arrangement and the alignment of the text in it.

    The empty regions around the symbol body are determined (see
    empty_regions), and every arrangement is tried in every region it fits
    into, on each side of the body (see preferred_sides) and, as a last
    resort, anywhere in the region, centered on the anchor as far as the
    region allows. The cheapest candidate wins: SIDE_COST per rank of the
    side plus candidate_cost; each step towards a flatter arrangement costs
    ARRANGE_COST, so the default line breaking is kept unless a flatter
    block gets closer to the symbol. With no fitting candidate at all, the
    block goes where it covers the least of other shapes, see
    least_covered_spot.
    """
    lines = annotation_lines(s, inst)
    if not lines:
        return None
    body = symbol_body(s, trans, inst)
    sizes = arrangements(lines)

    # Grid window: the body plus the reach of the largest arrangement.
    reach_x = PUSH_MARGIN + CLEARANCE_X + max(length for wrap, length, depth in sizes)
    reach_y = PUSH_MARGIN + CLEARANCE_Y + max(depth for wrap, length, depth in sizes)
    x0, y0 = math.floor((body.lx - reach_x)/STEP), math.floor((body.ly - reach_y)/STEP)
    x1, y1 = math.ceil((body.ux + reach_x)/STEP), math.ceil((body.uy + reach_y)/STEP)
    regions = empty_regions(x0, y0, x1 - x0, y1 - y0, obstacles)

    sides = preferred_sides(trans.d4, s.is_box)
    # Directions of East and North, the first two sides in either order.
    sx, sy = sides[0][0] + sides[1][0], sides[0][1] + sides[1][1]
    center_anchor = body.center + Vec2R(ANCHOR_SHIFT.x*sx, ANCHOR_SHIFT.y*sy)

    def anchor(side, length, depth) -> Vec2R:
        """Center that a block aims at on side, see the module docstring."""
        if not (s.is_box and side == sides[0]):
            return center_anchor
        # Above the top left corner, flush with the left edge.
        return Vec2R((body.lx if sx > 0 else body.ux) + sx*length/2,
            (body.uy if sy > 0 else body.ly) + sy*depth/2)

    # The search runs in floats for speed.
    body_f = body.tofloat()
    best = None
    for n, (wrap, length, depth) in enumerate(sizes):
        l, d = float(length), float(depth)
        anchors = [anchor(side, length, depth).tofloat() for side in sides + [None]]
        for region in regions:
            for rank, side in enumerate(sides + [None]):
                pos = region_spot(region, l, d, body_f, anchors[rank], float(STEP), float(PUSH_MARGIN), side)
                if pos is None:
                    continue
                x, y = pos
                cost = SIDE_COST*rank + candidate_cost((x, y, x + l, y + d), anchors[rank], body_f, foreign) \
                    + ARRANGE_COST*n
                if best is None or cost < best[0]:
                    best = cost, n, region, side

    pos = None
    if best is not None:
        cost, n, region, side = best
        wrap, length, depth = sizes[n]
        # Exact arithmetic for the result; None if float and exact disagree
        # on a block that barely fits.
        pos = region_spot(region, length, depth, tuple(body), tuple(anchor(side, length, depth)),
            STEP, PUSH_MARGIN, side)
    if pos is None:
        if inst is not None:
            logger.warning("No free spot for the annotation block of %s.", inst.full_path_label())
        n, pos = least_covered_spot(sizes, body, center_anchor, obstacles, foreign)
        wrap, length, depth = sizes[n]
        side = None
    x, y = pos
    rect = Rect4R(x, y, x + length, y + depth)
    # Blocks left of the body are right-aligned, so that their text ends at
    # the symbol like the text of blocks right of it starts at it. Blocks
    # above or below box symbols are aligned like the corner block (see
    # anchor).
    if side is not None and side[0] != 0:
        right = side[0] < 0
    elif side is not None and s.is_box:
        right = sx < 0
    else:
        right = rect.cx < body.cx
    return rect, wrap, HAlign.Right if right else HAlign.Left

def block_rects(node: Schematic) -> dict[int, tuple[Rect4R, int, HAlign]]:
    """
    Block rectangles, arrangements (wrap) and alignments of all instances of
    node with a non-empty block, by instance nid. Instances with an explicit
    annotation_pos keep it, and their blocks are obstacles for all others;
    the others are placed greedily in instance order, seeing the blocks
    placed before them as obstacles.
    """
    obstacles = [r.tofloat() for r in schematic_obstacles(node)]
    bodies = {inst.nid: symbol_body(inst.symbol, inst.loc_transform(), inst).tofloat()
        for inst in node.all(SchemInstance)}
    rects = {}
    for inst in node.all(SchemInstance):
        if inst.annotation_pos is not None:
            rect = annotation_extent(inst.symbol, inst.loc_transform(), inst)
            if rect is not None:
                rects[inst.nid] = rect, inst.annotation_wrap, inst.annotation_halign
                obstacles.append(rect.tofloat())
    for inst in node.all(SchemInstance):
        if inst.annotation_pos is not None:
            continue
        foreign = [body for nid, body in bodies.items() if nid != inst.nid]
        placed = place_block(inst.symbol, inst.loc_transform(), inst, obstacles, foreign)
        if placed is None:
            continue
        rects[inst.nid] = placed
        obstacles.append(placed[0].tofloat())
    return rects

def place_annotations(node: Schematic):
    """
    Sets annotation_pos, annotation_halign and annotation_wrap of every
    SchemInstance that has no annotation_pos, see block_rects, and extends
    node.outline over all blocks.
    """
    rects = block_rects(node)
    outline = node.outline
    for inst in node.all(SchemInstance):
        if inst.nid not in rects:
            continue
        rect, wrap, halign = rects[inst.nid]
        if inst.annotation_pos is None:
            inst.annotation_pos = rect.northeast if halign == HAlign.Right else rect.northwest
            inst.annotation_halign = halign
            inst.annotation_wrap = wrap
        if outline is not None:
            outline = outline.extend(rect.southwest).extend(rect.northeast)
    node.outline = outline
