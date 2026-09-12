# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Track-grid routing: pin access, pattern and maze search, and the
negotiated-congestion rip-up loop that resolves them into a legal routing.

The most self-contained part of the engine: it works purely on integer grid
nodes ``(x_track, y_track, layer_code)`` and imports nothing from ORDeC, so a
routing problem is a dict of terminals and a routing result is a set of edges.
"""

import bisect
from collections import namedtuple
from dataclasses import dataclass
import heapq

from public import public


# Internal layer codes. These are abstract routing-stack positions, not PDK
# layers. The engine routes on two vertical layers (codes M2, M4) and two
# horizontal (M3, M5), with M1 reserved for pin access. Doubling the routing
# layers roughly doubles capacity, as production routers do. The flow binds
# these codes to concrete PDK layers from the PDK's RoutingSpec
# (flow.stack_from_spec), so no PDK layer name is baked into the engine.
M2, M3, M1, M4, M5 = 0, 1, 2, 3, 4
VERT = (M2, M4)        # vertical routing layers (move in y)
HORIZ = (M3, M5)       # horizontal routing layers (move in x)

# Index of a routing layer / via in GridConfig's per-layer geometry tuples,
# which run (Metal2, Metal3, Metal4, Metal5) and (Via1, Via2, Via3, Via4).
LIDX = {M2: 0, M3: 1, M4: 2, M5: 3}
VIDX = {frozenset((M1, M2)): 0, frozenset((M2, M3)): 1,
    frozenset((M3, M4)): 2, frozenset((M4, M5)): 3}


@public
class EscapeCapacityError(RuntimeError):
    """An edge has fewer free escape columns than ports to place.

    Unlike a pin-access failure this is not permanent: a wider die frees
    more columns, so :func:`~.flow.place_and_route` widens and retries.
    """

    def __init__(self, message, deficit, edge):
        super().__init__(message)
        self.deficit = deficit   # missing escape tracks on that edge
        self.edge = edge         # more width frees columns, more rows frees
                                 # side rows


@public
class PinAccessError(RuntimeError):
    """A terminal cannot be connected on the routing grid.

    Unlike congestion, this is permanent: growing the floorplan and retrying
    cannot make a pin reachable, so :func:`place_and_route` re-raises it
    immediately instead of burning retries.
    """


# One routed *segment* of a net (a 2-pin MST edge, the min-area extensions, or
# the port escape): its wire edges, the grid nodes it occupies (congestion
# bookkeeping), its terminal endpoints as (terminal index, node) pairs, and the
# nodes shadowed by an off-track access bridge (kept clear of every net,
# including this one, since the bridge metal ends too close to them).
RouteSeg = namedtuple('RouteSeg', 'edges nodes pairs shadows', defaults=((),))


@dataclass(frozen=True)
class RoutingResult:
    """A whole block's routing, as :func:`route_nets` resolved it.

    Every field is keyed by net name, so one record replaces the five parallel
    dicts a caller would otherwise keep in step.

    Args:
        nets: ``{net: (edges, term_m2)}``, the routed edges and the Via1 access
            nodes where the net meets its terminals.
        port_escape: ``{net: (track, edge)}`` for each escaped port net's
            edge pad: the reserved x-track and 'top' or 'bottom' for a
            Metal4 pad, or the reserved y-track and 'left' or 'right' for a
            Metal3 one.
        term_via: ``{net: {node: (via_x, via_y)}}`` for off-track terminals,
            whose Via1 sits beside the access node rather than on it.
        term_land: ``{net: {node: rect}}``, the Metal1 landing an off-track or
            short pin needs under its Via1.
        reserved: nodes shadowed by an off-track access bridge. No later wire
            growth may take them, not even the bridge's own net.
        sub_nodes: ``{net: {node}}`` reached through a pin-access sub-via, so
            the emitter drops the sub-via cut there (an ordinary Via1
            terminal elsewhere).
    """
    nets: dict
    port_escape: dict
    term_via: dict
    term_land: dict
    reserved: frozenset
    sub_nodes: dict


def escape_row(cfg, edge):
    """The signal y-track a port escapes on, just inside the given edge rail.

    Args:
        cfg: the routing grid (:class:`GridConfig`).
        edge: ``'top'`` or ``'bottom'``.

    Returns:
        The y-track index.
    """
    if edge == 'top':
        return cfg.y_track_max - 1
    if edge == 'bottom':
        return 1
    raise ValueError(f"port edge must be 'top' or 'bottom', not {edge!r}")


def escape_col(xmax, edge):
    """The x-track a port escapes on, just inside the given side edge.

    Args:
        xmax: the maximum x track index.
        edge: ``'left'`` or ``'right'``.

    Returns:
        The x-track index.
    """
    if edge == 'left':
        return 1
    if edge == 'right':
        return xmax - 1
    raise ValueError(f"port edge must be 'left' or 'right', not {edge!r}")


PORT_EDGES = ('top', 'bottom', 'left', 'right')


def access_via_dims(cfg, rail, direct=False):
    """Via and enclosure dims for pin access.

    A stack with a pin-access sub-layer (``cfg.sub_via_half``) reaches signal
    pins through the sub-via. Supply rails and pins the library routed up to
    Metal1 (``direct``) stay on Metal1 and use Via1, as does every pin
    without a sub-layer.
    """
    if rail or direct or cfg.sub_via_half is None:
        return cfg.via_half[0], cfg.encl, cfg.encl_endcap
    return cfg.sub_via_half, cfg.sub_encl, cfg.sub_encl_endcap


def bridge_footprint(cfg, xi, via_x, via_y):
    """The off-grid Metal2 rect an off-track access occupies.

    The union of the bridge to the track, the landing at the via and the
    via pad, which the node-based conflict model cannot see. Footprints of
    different nets closer than the metal spacing are a conflict
    (:class:`Congestion`).
    """
    m2_half = cfg.wire_width[0] // 2
    land_half = cfg.land_half_h[0]
    pad_cross, pad_along = (cfg.via_land[0][1]
        if cfg.via_land is not None else (0, 0))
    tx = xi * cfg.x_pitch
    return (min(via_x - pad_cross, min(via_x, tx) - m2_half),
        via_y - max(land_half, pad_along),
        max(via_x + pad_cross, max(via_x, tx) + m2_half),
        via_y + max(land_half, pad_along))


def tap_m2_land(cfg):
    """Half-extents of a rail tap's Metal2 landing.

    Matches the emitted landing, which grows past the wire width where the
    via landing pads (``cfg.via_land``) demand it, so the off-track access
    clearance tests measure against the real geometry.
    """
    half_w = cfg.wire_width[0] // 2
    half_h = cfg.land_half_h[0]
    if cfg.via_land is not None:
        half_w = max(half_w, cfg.via_land[0][1][0], cfg.via_land[1][0][0])
        half_h = max(half_h, cfg.via_land[0][1][1], cfg.via_land[1][0][1])
    return half_w, half_h


def landing_access(rects, cfg):
    """Via positions for a pin accessed by an emitted landing.

    A pin on the sub-layer (li1) or a thin Metal1 routing strip cannot
    enclose a via on its own; the access emits a landing
    (:func:`sub_land_rect`) that provides the enclosure and merges with the
    pin, so a via position only has to be *covered* by the pin metal. On-grid
    intersections come first (no Metal2 jog), then off-grid via positions on
    the Metal2 lattice columns.

    Args:
        rects: the pin's rectangles ``[Rect4I, ...]`` in nm.
        cfg: the routing grid + DRC geometry (:class:`GridConfig`).

    Returns:
        ``[(xi, yi, via_x, via_y), ...]``, the access track node and the via
        position (on the node for on-grid, beside it otherwise).
    """
    if not rects:
        return []
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    m2_mult, m2_off = cfg.track_mult[LIDX[M2]], cfg.track_off[LIDX[M2]]
    mg = cfg.manufacturing_grid

    def covered(px, py):
        return any(r.lx <= px <= r.ux and r.ly <= py <= r.uy for r in rects)

    xlo = min(r.lx for r in rects); xhi = max(r.ux for r in rects)
    on, off = [], []
    for yi in range(1, cfg.y_track_max):
        if not cfg.is_signal_track(yi):
            continue
        ty = yi * y_pitch
        for xi in range(xlo // x_pitch, xhi // x_pitch + 2):
            if (xi - m2_off) % m2_mult:
                continue
            tx = xi * x_pitch
            if covered(tx, ty):
                on.append((xi, yi, tx, ty))
                continue
            # Off-grid: a via on the pin at the mfg-grid x nearest this
            # column, bridged back to the column on Metal2.
            row = [r for r in rects if r.ly <= ty <= r.uy]
            if not row:
                continue
            lo = min(r.lx for r in row); hi = max(r.ux for r in row)
            vx = max(lo, min(hi, round(tx / mg) * mg))
            if covered(vx, ty):
                off.append((xi, yi, vx, ty))
    return on + off


def sub_land_rect(cfg, via_x, via_y, pin_rects):
    """Metal1 landing over a sub-via at (via_x, via_y), grown along x.

    Thin in y (``sub_land_half_h``, just the sub-via enclosure) so a landing
    near a rail clears it, and wide enough in x to meet Metal1 min area,
    clamped to the pin's x-extent so it never protrudes past the cell's own
    metal. Returns None when the pin is too narrow to hold a min-area
    landing at this via.
    """
    half_h = cfg.sub_land_half_h
    mg = cfg.manufacturing_grid
    # Min total width for the area, at least the sub-via enclosure. Metal1
    # may extend past the li1 pin (a different layer), so the landing is
    # centered on the via and grown symmetrically; land_clear rejects it if
    # it actually reaches foreign metal or a rail.
    need_w = -(-cfg.sub_land_min_area // (2 * half_h))
    half_w = max(-(-need_w // 2), cfg.sub_land_half_w_min)
    half_w = -(-half_w // mg) * mg
    return (via_x - half_w, via_y - half_h, via_x + half_w, via_y + half_h)


def access_nodes(rects, cfg, allow_rail=False, direct=False):
    """Find candidate Via1 access points for a pin from its Metal1 rectangles.

    A pin is reached at the intersection of a vertical track inside its Metal1
    x-extent and a horizontal track inside its y-extent. Using the clean LEF
    rects rather than a polygon bbox guarantees the access lands on this pin
    only. A pin whose metal falls *between* vertical tracks (xor2's Y) has no
    on-track via and falls back to :func:`union_access`, then
    :func:`offtrack_access`.

    Args:
        rects: the pin's Metal1 rectangles ``[(x0, y0, x1, y1), ...]`` in nm.
        cfg: the routing grid + DRC geometry (:class:`GridConfig`).
        allow_rail: true for a power pin, whose wide rail encloses a via
            anywhere. Signal pins use signal tracks only.

    Returns:
        ``[(xi, yi, via_x, via_y, land), ...]``, the track node the router
        connects to, the Via1 position in nm, and its Metal1 endcap landing.
        ``land`` grows along the axis the pin encloses as a pair so it stays on
        the pin's metal, and is ``None`` for an off-track via, which takes its
        endcap from the pin itself.
    """
    if not rects:
        return []
    via_half, encl, encl_endcap = access_via_dims(cfg, allow_rail, direct)
    half_w, endcap = cfg.m1_land_half_w, cfg.m1_land_half_h
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    m2_mult, m2_off = cfg.track_mult[LIDX[M2]], cfg.track_off[LIDX[M2]]
    found = {}   # (xi, yi) -> (track_x, track_y, land, tier); tier 0 = pair-of-sides endcap
    for (x0, y0, x1, y1) in rects:
        for xi in range(x0 // x_pitch, x1 // x_pitch + 2):
            if (xi - m2_off) % m2_mult:
                continue
            track_x = xi * x_pitch
            # x via enclosures (metal margin left/right of the via):
            left, right = track_x - via_half - x0, x1 - (track_x + via_half)
            if left < encl or right < encl:
                continue
            ylo, yhi = (0, cfg.y_track_max) if allow_rail else (1, cfg.y_track_max - 1)
            for yi in range(ylo, yhi + 1):
                if not allow_rail and not cfg.is_signal_track(yi):
                    continue
                track_y = yi * y_pitch
                # y via enclosures (metal margin below/above the via):
                bottom, top = track_y - via_half - y0, y1 - (track_y + via_half)
                if bottom < encl or top < encl:
                    continue
                # Via1 wants its Metal1 endcap on a *pair* of opposite sides
                # (V1.c1): a tall pin encloses top/bottom, a wide one left/right. The
                # landing grows the full height on that axis so it stays inside
                # the pin. A single-endcap pin (no pair) still routes, with the
                # vertical landing reaching past it to make the pair.
                pair_x = left >= encl_endcap and right >= encl_endcap
                pair_y = bottom >= encl_endcap and top >= encl_endcap
                pair = pair_x or pair_y
                if not (pair or max(left, right, bottom, top) >= encl_endcap):
                    continue
                if pair_x and not pair_y:
                    land = (track_x - endcap, track_y - half_w,
                            track_x + endcap, track_y + half_w)
                else:
                    land = (track_x - half_w, track_y - endcap,
                            track_x + half_w, track_y + endcap)
                key, tier = (xi, yi), 0 if pair else 1
                if key not in found or tier < found[key][3]:
                    found[key] = (track_x, track_y, land, tier)
    if found:
        # Keep only the best-tier candidates (all pair-enclosed, else all single),
        # so the router sees one consistent set of access nodes for this pin.
        best = min(v[3] for v in found.values())
        return [(xi, yi, v[0], v[1], v[2])
            for (xi, yi), v in found.items() if v[3] == best]
    if allow_rail:
        return []
    # Per-rect found nothing. Try an on-track via enclosed by the *union* of the
    # pin's rects (a staircase pin), then fall back to an off-track via.
    union = union_access(rects, cfg, direct)
    if union:
        return union
    return [(xi, yi, via_x, via_y, None)
        for (xi, yi, via_x, via_y) in offtrack_access(rects, cfg, direct)]



def offtrack_access(rects, cfg, direct=False):
    """Access a pin with no on-track via point, dropping the Via1 on the pin.

    The via goes on the pin at a manufacturing-grid x on a signal y-track, and
    the emitter bridges to the reported vertical track with a short Metal2
    segment, which is free over the Metal1-only leaf cells. The pin's own metal
    must give the via its endcap, since off-track vias add no Metal1 landing.

    Args:
        rects: the pin's Metal1 rectangles ``[(x0, y0, x1, y1), ...]`` in nm.
        cfg: the routing grid + DRC geometry (:class:`GridConfig`).

    Returns:
        ``[(xi, yi, via_x, via_y), ...]``, the nearest vertical track and signal
        y-track, and the on-pin Via1 position in nm.
    """
    if not rects:
        return []
    via_half, encl, encl_endcap = access_via_dims(cfg, False, direct)
    mgrid = cfg.manufacturing_grid
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    out = []
    for (x0, y0, x1, y1) in rects:
        xlo, xhi = x0 + via_half + encl, x1 - via_half - encl   # via-x range in rect
        if xhi < xlo:
            continue
        for yi in range(1, cfg.y_track_max):
            if not cfg.is_signal_track(yi):
                continue
            track_y = yi * y_pitch
            # y enclosures (metal margin below/above the via):
            bottom, top = track_y - via_half - y0, y1 - (track_y + via_half)
            if bottom < encl or top < encl:
                continue
            # Snap to the in-rect manufacturing-grid x nearest a Metal2
            # track (short jog). The next track on the other side is a
            # second candidate, so the negotiation can bridge away from a
            # crowded neighborhood.
            m2_mult = cfg.track_mult[LIDX[M2]]
            m2_off = cfg.track_off[LIDX[M2]]
            mid = (xlo + xhi) / 2
            near = round((mid / x_pitch - m2_off) / m2_mult) * m2_mult \
                + m2_off
            other = near - m2_mult if near * x_pitch >= mid \
                else near + m2_mult
            # The pin's own metal must give the via its endcap enclosure
            # on a pair of opposite sides, since off-track vias add no
            # Metal1 landing. If the rows cannot give the vertical pair,
            # the via shifts within the pin until the horizontal one holds.
            pair_y = bottom >= encl_endcap and top >= encl_endcap
            for xi in (near, other):
                if xi < m2_off:
                    continue
                via_x = max(xlo, min(xhi, round(xi * x_pitch / mgrid) * mgrid))
                if not pair_y:
                    lo_x = x0 + via_half + encl_endcap
                    hi_x = x1 - via_half - encl_endcap
                    if hi_x < lo_x:
                        continue
                    via_x = max(lo_x, min(hi_x,
                        -(-via_x // mgrid) * mgrid))
                    via_x = min(hi_x // mgrid * mgrid,
                        max(-(-lo_x // mgrid) * mgrid, via_x))
                left, right = via_x - via_half - x0, x1 - (via_x + via_half)
                if not (pair_y or (left >= encl_endcap
                        and right >= encl_endcap)):
                    continue
                out.append((xi, yi, via_x, track_y))
    return out



def union_access(rects, cfg, direct=False):
    """On-track access for a staircase pin, enclosed only by its merged rects.

    A pin like nand4's A is enclosed by no single LEF rect, so
    :func:`access_nodes`'s per-rect test misses it. Center-line ray casts
    measure how far the merged metal reaches around a track via, and the landing
    grows along the axis it reaches furthest on, so it stays on real metal.

    Args:
        rects: the pin's Metal1 rectangles ``[(x0, y0, x1, y1), ...]`` in nm.
        cfg: the routing grid + DRC geometry (:class:`GridConfig`).

    Returns:
        Candidates in the same form as the on-track branch of
        :func:`access_nodes`.
    """
    if not rects:
        return []
    via_half, encl, encl_endcap = access_via_dims(cfg, False, direct)
    half_w, endcap = cfg.m1_land_half_w, cfg.m1_land_half_h
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    m2_mult, m2_off = cfg.track_mult[LIDX[M2]], cfg.track_off[LIDX[M2]]
    mgrid = cfg.manufacturing_grid

    def covered(px, py):
        return any(rect.lx <= px <= rect.ux and rect.ly <= py <= rect.uy
            for rect in rects)

    def reach(cx, cy, dx, dy):   # contiguous Metal1 extent from the via centre
        d = 0
        while covered(cx + dx * (d + mgrid), cy + dy * (d + mgrid)):
            d += mgrid
        return d

    xlo, xhi = min(r.lx for r in rects), max(r.ux for r in rects)
    out = {}
    for xi in range(xlo // x_pitch, xhi // x_pitch + 2):
        if (xi - m2_off) % m2_mult:
            continue
        track_x = xi * x_pitch
        for yi in range(1, cfg.y_track_max):
            if not cfg.is_signal_track(yi) or not covered(track_x, yi * y_pitch):
                continue
            track_y = yi * y_pitch
            left = reach(track_x, track_y, -1, 0) - via_half
            right = reach(track_x, track_y, 1, 0) - via_half
            bottom = reach(track_x, track_y, 0, -1) - via_half
            top = reach(track_x, track_y, 0, 1) - via_half
            if min(left, right, bottom, top) < encl or max(left, right, bottom, top) < encl_endcap:
                continue
            pair_x = left >= encl_endcap and right >= encl_endcap
            pair_y = bottom >= encl_endcap and top >= encl_endcap
            if pair_x and not pair_y:
                land = (track_x - endcap, track_y - half_w,
                        track_x + endcap, track_y + half_w)
            else:
                land = (track_x - half_w, track_y - endcap,
                        track_x + half_w, track_y + endcap)
            out[(xi, yi)] = (track_x, track_y, land)
    return [(xi, yi, v[0], v[1], v[2]) for (xi, yi), v in out.items()]



def grid_moves(node, cfg, xmax):
    """Yield the maze-router moves out of one grid node.

    Vertical layers (M2, M4) step in y, horizontal layers (M3, M5) step in x. A
    layer change costs ``cfg.via_cost`` and is only allowed off the rail tracks.

    Args:
        node: the current grid node ``(xi, yi, layer)``.
        cfg: the routing grid + cost knobs (:class:`GridConfig`).
        xmax: the maximum x track index, the right die edge.

    Yields:
        ``(neighbor_node, move_cost)`` for each legal move.
    """
    xi, yi, layer = node
    on_signal = cfg.is_signal_track(yi)
    via_cost = cfg.via_cost
    # A layer with a track multiple exists only on every mult-th track of its
    # own axis, so a layer change must land on such a track. Wire moves along
    # the run axis stay at base-grid granularity on every layer.
    mult, off = cfg.track_mult, cfg.track_off

    def on_layer(to_layer):
        i = LIDX[to_layer]
        c = xi if to_layer in VERT else yi
        return (c - off[i]) % mult[i] == 0
    # Vertical moves span the full track range 0..y_track_max INCLUSIVE: the
    # outermost tracks sit on the die-edge rails, and a terminal on such a rail
    # (a tie-off to a rail-only supply pin) must be reachable as a goal.
    if layer == M2:                      # vertical (move in y, rails pass through)
        if yi + 1 <= cfg.y_track_max: yield (xi, yi + 1, M2), 1.0
        if yi - 1 >= 0:               yield (xi, yi - 1, M2), 1.0
        if on_signal and on_layer(M3): yield (xi, yi, M3), via_cost
    elif layer == M3:                    # horizontal (move in x); via down to M2, up to M4
        if xi + 1 <= xmax: yield (xi + 1, yi, M3), 1.0
        if xi - 1 >= 0:    yield (xi - 1, yi, M3), 1.0
        if on_layer(M2): yield (xi, yi, M2), via_cost
        if on_signal and cfg.use_upper and on_layer(M4):
            yield (xi, yi, M4), via_cost
    elif layer == M4:                    # vertical (second vertical layer)
        if yi + 1 <= cfg.y_track_max: yield (xi, yi + 1, M4), 1.0
        if yi - 1 >= 0:               yield (xi, yi - 1, M4), 1.0
        if on_signal:
            if on_layer(M3): yield (xi, yi, M3), via_cost
            if cfg.use_m5 and on_layer(M5): yield (xi, yi, M5), via_cost
    elif layer == M5:                    # horizontal (second horizontal layer)
        if xi + 1 <= xmax: yield (xi + 1, yi, M5), 1.0
        if xi - 1 >= 0:    yield (xi - 1, yi, M5), 1.0
        if on_layer(M4): yield (xi, yi, M4), via_cost



class GridAdjacency(dict):
    """Per-node ``((neighbor, cost), ...)`` move table, built lazily.

    The move set (:func:`grid_moves`) depends only on the grid and the blocked
    nodes, not on the nets, so each node's moves are computed once per
    :func:`route_nets` run and then served as a plain dict hit. That takes the
    generator, the signal-track test and the property lookups out of the maze
    router's inner loop. It is filled on first touch rather than precomputed:
    the pattern-routing fast path keeps the maze searches to a small fraction
    of the grid, so eagerly tabulating every node (grids run to hundreds of
    thousands of nodes) costs more than all the lookups it serves.

    Nodes in ``blocked`` (reserved for the stripes' rail taps) are dropped from every
    move list, so the maze router can never enter them. They are a hard
    blockage rather than a congestion penalty.
    """

    def __init__(self, cfg, xmax, blocked=frozenset()):
        super().__init__()
        self.cfg = cfg
        self.xmax = xmax
        self.blocked = blocked

    def __missing__(self, node):
        moves = tuple(move for move in grid_moves(node, self.cfg, self.xmax)
            if move[0] not in self.blocked)
        self[node] = moves
        return moves



def astar(starts, goals, cfg, xmax, history, occupancy, own_use, penalty,
        allowed=None, adj=None):
    """Route one connection by A* from any start node to any goal node.

    The congestion cost is inlined rather than taken from a callback, since
    these lookups run once per expanded edge, the engine's innermost loop.

    Args:
        starts: the start nodes, a terminal's access nodes or the tree so far.
        goals: the goal nodes, the next terminal's access nodes.
        cfg: the routing grid + cost knobs (:class:`GridConfig`).
        xmax: the maximum x track index.
        history: ``{node: accumulated congestion cost}``.
        occupancy: ``{node: number of nets on it}``.
        own_use: the nodes this net already uses, which cost history only, so
            its segments share track.
        penalty: the present-congestion penalty per foreign occupant.
        allowed: optional ``(xi, yi)`` corridor from global routing, keeping the
            search local on large layouts.
        adj: optional :class:`GridAdjacency` move table. Falls back to
            generating moves per expansion.

    Returns:
        The path from a start to a goal, or ``None`` if none exists within
        ``allowed``.
    """
    goal_set = set(goals)
    # Bounding-box heuristic: distance to the goals' bbox is a lower bound on the
    # distance to any goal (admissible) and is O(1) per node. Scanning the goal
    # list per expansion instead dominated the whole engine's runtime on searches
    # with large goal sets (a port escape targets every top-row track).
    gx_lo = min(n[0] for n in goals); gx_hi = max(n[0] for n in goals)
    gy_lo = min(n[1] for n in goals); gy_hi = max(n[1] for n in goals)
    # Via-aware term: a vertical layer only moves in y and a horizontal one only
    # in x, so covering a nonzero dx and/or dy and finishing on the goals' layer
    # class needs a provable minimum number of layer changes (each >= via_cost).
    # Tightening h with it prunes most off-layer exploration (via_cost dominates
    # short in-channel hops). All goal layers agree in practice (terminal
    # goals are M2, escapes M4). A mixed set drops the finishing constraint.
    goal_classes = {n[2] in VERT for n in goals}
    goal_vert = goal_classes.pop() if len(goal_classes) == 1 else None
    via_cost = cfg.via_cost

    def heuristic(node):
        xi, yi = node[0], node[1]
        dx = gx_lo - xi if xi < gx_lo else (xi - gx_hi if xi > gx_hi else 0)
        dy = gy_lo - yi if yi < gy_lo else (yi - gy_hi if yi > gy_hi else 0)
        vert = node[2] in VERT
        if dx and dy:            # needs both classes: 1 change, 2 if it must return
            changes = 1 if goal_vert is None else (2 if vert == goal_vert else 1)
        elif dx:                 # needs a horizontal layer at some point
            changes = vert + (1 if goal_vert else 0)
        elif dy:                 # needs a vertical layer at some point
            changes = (not vert) + (0 if goal_vert or goal_vert is None else 1)
        else:
            changes = 0 if goal_vert is None or vert == goal_vert else 1
        return dx + dy + changes * via_cost

    frontier = []
    cost = {}            # node -> cheapest known cost to reach it
    came_from = {}
    hist_cost, occupants = history.get, occupancy.get
    for start in starts:
        start_cost = hist_cost(start, 0.0)
        if start not in own_use:
            start_cost += penalty * occupants(start, 0)
        cost[start] = start_cost
        heapq.heappush(frontier, (start_cost + heuristic(start), 0.0, start))
    heappush, heappop = heapq.heappush, heapq.heappop
    while frontier:
        _, _, current = heappop(frontier)
        if current in goal_set:
            path = [current]
            while current in came_from:
                current = came_from[current]; path.append(current)
            return path[::-1]
        moves = adj[current] if adj is not None else grid_moves(current, cfg, xmax)
        cur_cost = cost[current]
        for neighbor, step in moves:
            if allowed is not None and (neighbor[0], neighbor[1]) not in allowed:
                continue
            new_cost = cur_cost + step + hist_cost(neighbor, 0.0)
            if neighbor not in own_use:
                new_cost += penalty * occupants(neighbor, 0)
            if neighbor not in cost or new_cost < cost[neighbor]:
                cost[neighbor] = new_cost; came_from[neighbor] = current
                # Tie-break equal f toward the deeper node (-g): on the plateaus
                # of equal-cost Manhattan paths this walks one path to the goal
                # instead of flooding the whole equal-f diamond.
                heappush(frontier,
                    (new_cost + heuristic(neighbor), -new_cost, neighbor))
    return None



def gcell_astar(starts, goal, gcell_xmax, gcell_ymax, gcell_cost):
    """Route on the coarse gcell grid (2-D, 4-connected) for the global router.

    Args:
        starts: the start gcells, the net's tree so far.
        goal: the gcell to reach.
        gcell_xmax: the maximum gcell x index.
        gcell_ymax: the maximum gcell y index.
        gcell_cost: callable ``gcell -> float`` giving per-gcell congestion cost.

    Returns:
        The gcells on the cheapest path from any start to ``goal``.
    """
    frontier = []
    cost = {}
    came_from = {}
    for start in starts:
        cost[start] = 0.0
        heapq.heappush(frontier, (abs(start[0] - goal[0]) + abs(start[1] - goal[1]), start))
    while frontier:
        _, current = heapq.heappop(frontier)
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]; path.append(current)
            return path
        cur_x, cur_y = current
        for nbr_x, nbr_y in ((cur_x + 1, cur_y), (cur_x - 1, cur_y),
                             (cur_x, cur_y + 1), (cur_x, cur_y - 1)):
            if not (0 <= nbr_x <= gcell_xmax and 0 <= nbr_y <= gcell_ymax):
                continue
            nbr = (nbr_x, nbr_y)
            new_cost = cost[current] + gcell_cost(nbr)
            if nbr not in cost or new_cost < cost[nbr]:
                cost[nbr] = new_cost; came_from[nbr] = current
                heapq.heappush(frontier,
                    (new_cost + abs(nbr_x - goal[0]) + abs(nbr_y - goal[1]), nbr))
    return [goal]



def global_route(routed_nets, term_access, cfg, xmax, gcell_w=5, gcell_h=5):
    """Assign each net a coarse corridor by negotiated-congestion global routing.

    The track grid is tiled into gcells. Each net's terminals are connected by a
    cheap tree on the gcell grid, with a congestion penalty on per-gcell demand
    so nets spread off hotspots.

    Args:
        routed_nets: the nets to route, ``{name: NetInfo}``.
        term_access: per net, the per-terminal candidate access nodes from
            :func:`route_nets`.
        cfg: the routing grid (:class:`GridConfig`).
        xmax: the maximum x track index.
        gcell_w: gcell width in tracks.
        gcell_h: gcell height in tracks.

    Returns:
        Per net, the frozenset of ``(xi, yi)`` track positions its detailed
        routing may use: its gcell tree plus a one-gcell halo, expanded to track
        positions so the maze router tests membership with a set probe.
    """
    def gcell_of(node):
        return (node[0] // gcell_w, node[1] // gcell_h)

    gcell_xmax = xmax // gcell_w + 1
    gcell_ymax = cfg.y_track_max // gcell_h + 1
    net_gcells = {}
    for net_name in routed_nets:
        net_gcells[net_name] = list({gcell_of(node)
            for term in term_access[net_name] for node in term})
    gcell_cap = gcell_w + gcell_h
    history = {}
    penalty = [0.5]
    demand = {}
    corridors = {}

    def gcell_cost(gcell):
        return (1.0 + history.get(gcell, 0.0)
            + penalty[0] * max(0, demand.get(gcell, 0)))

    def route(net_name):
        gcells = net_gcells[net_name]
        if not gcells:
            raise PinAccessError(f"net {net_name!r} has no routable pin access "
                "(a terminal pin could not be reached on or off the track grid)")
        tree = {gcells[0]}
        for gcell in gcells[1:]:
            if gcell not in tree:
                tree.update(gcell_astar(tree, gcell,
                    gcell_xmax, gcell_ymax, gcell_cost))
        return tree

    for net_name in routed_nets:
        corridors[net_name] = route(net_name)
        for gcell in corridors[net_name]:
            demand[gcell] = demand.get(gcell, 0) + 1

    for _ in range(400):
        congested = {gcell for gcell, d in demand.items() if d > gcell_cap}
        if not congested:
            break
        for gcell in congested:
            history[gcell] = history.get(gcell, 0.0) + 1.0
        penalty[0] = min(penalty[0] * 1.3, 40.0)
        for net_name in list(routed_nets):
            if not (corridors[net_name] & congested):
                continue
            for gcell in corridors[net_name]:
                demand[gcell] -= 1
            corridors[net_name] = route(net_name)
            for gcell in corridors[net_name]:
                demand[gcell] = demand.get(gcell, 0) + 1

    # Widen each corridor by a one-gcell halo so detailed routing has room, then
    # expand the gcells to track positions.
    for net_name in corridors:
        halo = set()
        for (gcell_x, gcell_y) in corridors[net_name]:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    halo.add((gcell_x + dx, gcell_y + dy))
        corridors[net_name] = frozenset(
            (gcell_x * gcell_w + dx, gcell_y * gcell_h + dy)
            for (gcell_x, gcell_y) in halo
            for dx in range(gcell_w) for dy in range(gcell_h))
    return corridors



def mst_edges(points):
    """Prim's minimum spanning tree over terminal positions (Manhattan metric).

    The MST fixes each multi-terminal net's 2-pin decomposition, since every
    edge becomes an independently rip-up-able segment. That is what lets the
    negotiation loop reroute one broken connection of a high-fan-out net instead
    of the whole tree.

    Args:
        points: the terminals' proxy positions ``[(xi, yi), ...]``.

    Returns:
        The MST as ``[(i, j), ...]`` index pairs into ``points``.
    """
    n = len(points)
    if n <= 1:
        return []
    INF = float('inf')
    dist = [INF] * n
    near = [0] * n
    in_tree = [False] * n
    dist[0] = 0
    edges = []
    for _ in range(n):
        best, bi = INF, -1
        for i in range(n):
            if not in_tree[i] and dist[i] < best:
                best, bi = dist[i], i
        in_tree[bi] = True
        if bi != 0:
            edges.append((near[bi], bi))
        bx, by = points[bi]
        for j in range(n):
            if not in_tree[j]:
                d = abs(points[j][0] - bx) + abs(points[j][1] - by)
                if d < dist[j]:
                    dist[j] = d
                    near[j] = bi
    return edges



def spacing_reach(cfg):
    """Facing-end conflict reach per layer, in run-axis grid steps.

    Two same-track wire ends ``d`` steps apart conflict while
    ``d * step < 2 * wire_ext + wire_space``. A uniform stack yields 1 on
    every layer.

    Args:
        cfg: the routing grid + geometry (:class:`GridConfig`).

    Returns:
        ``{layer code: reach}`` for the four routing layers.
    """
    reach = {}
    for layer in (M2, M3, M4, M5):
        i = LIDX[layer]
        step = cfg.y_pitch if layer in VERT else cfg.x_pitch
        reach[layer] = max(1,
            -(-(2 * cfg.wire_ext[i] + cfg.wire_space[i]) // step) - 1)
    return reach


def spacing_neighbors(node, reach):
    """Same-layer grid nodes that would violate metal spacing against ``node`` if
    used by a *different* net.

    Only the same-track, facing-ends case matters. The wire-end overhang
    (``cfg.wire_ext``) puts two facing ends within ``reach`` grid steps closer
    than the min metal spacing. Adjacent-track parallels are a full pitch
    apart and legal, and must not be flagged, since doing so rejects legal
    routing and stalls convergence. Steps run along x for horizontal layers,
    along y for vertical.

    Args:
        node: the grid node ``(xi, yi, layer)`` to check around.
        reach: ``{layer code: steps}`` from :func:`spacing_reach`.

    Returns:
        The conflicting same-layer neighbors, possibly empty.
    """
    xi, yi, layer = node
    r = reach[layer]
    if layer in HORIZ:
        return tuple((xi + d, yi, layer)
            for d in range(-r, r + 1) if d)
    if layer in VERT:
        return tuple((xi, yi + d, layer)
            for d in range(-r, r + 1) if d)
    return ()



class Congestion:
    """The rip-up loop's bookkeeping: who occupies which node, and where that
    conflicts.

    Kept incrementally, since rescanning every occupied node per negotiation
    pass scales with the total wirelength routed so far and dominated large
    runs. ``overused`` and ``spacing_bad`` change only when a node gains its
    first or loses its last net, so :meth:`add_seg` and :meth:`remove_seg`
    maintain them right there.

    An owner is a net name, or ``('bridge', net)`` for the shadow of an
    off-track access bridge. Shadows take part in every conflict so that no
    net can use them, but :meth:`conflicts` never rips one up on its own,
    since a shadow moves with its terminal.
    """

    def __init__(self, reach, foot_rects=None):
        self.reach = reach    # spacing_reach(cfg), for update_spacing
        # key -> (rect, kind, spacing): off-grid access shapes the node model
        # cannot see (Metal2 bridges, Metal1 access landings). Two shapes of
        # different nets, the SAME kind, within their spacing are a conflict.
        self.foot_rects = foot_rects or {}
        self.foot = {}        # key -> refcount of chosen accesses
        self.foot_bad = set() # frozenset of two conflicting foot keys
        self.history = {}     # node -> accumulated historical-congestion cost
        self.occupancy = {}   # node -> number of owners currently using it
        self.node_nets = {}   # node -> set(owner)
        self.routes = {}      # net -> {segment key: RouteSeg}
        self.net_use = {}     # owner -> {node: segments of that owner on it}
        self.overused = set()
        self.spacing_bad = set()   # canonical (lower, upper) node pairs

    def update_spacing(self, node):
        # Re-evaluate every same-track pair whose status this node can
        # change: the pairs it is a member of and, beyond one step, the
        # pairs it lies between (a same-net pair with an unowned gap is a
        # notch: two disjoint pieces of one net closer than the metal
        # spacing, which merging cannot fix).
        xi, yi, layer = node
        r = self.reach.get(layer)
        if r is None:
            return
        if layer in HORIZ:
            line = [(xi + d, yi, layer) for d in range(-r, r + 1)]
        else:
            line = [(xi, yi + d, layer) for d in range(-r, r + 1)]
        occ = [self.node_nets.get(n) and {o for o in self.node_nets[n]
            if not isinstance(o, tuple)} for n in line]
        for i in range(len(line)):
            for j in range(i + 1, min(i + r + 1, len(line))):
                if not i <= r <= j:
                    continue
                a, b = line[i], line[j]
                pair = (a, b) if a < b else (b, a)
                here, there = occ[i], occ[j]
                bad = False
                if here and there:
                    shared = here & there
                    if not shared:
                        bad = True
                    elif j - i >= 2:
                        bad = not any(
                            all(k_occ and o in k_occ
                                for k_occ in occ[i + 1:j])
                            for o in shared)
                if bad:
                    self.spacing_bad.add(pair)
                else:
                    self.spacing_bad.discard(pair)

    def add_nodes(self, owner, nodes):
        use = self.net_use.setdefault(owner, {})
        for node in nodes:
            count = use.get(node, 0)
            use[node] = count + 1
            if count == 0:   # first segment of this owner on the node
                self.occupancy[node] = self.occupancy.get(node, 0) + 1
                self.node_nets.setdefault(node, set()).add(owner)
                self.update_overuse(node)
                self.update_spacing(node)

    def remove_nodes(self, owner, nodes):
        use = self.net_use[owner]
        for node in nodes:
            count = use[node] - 1
            if count:
                use[node] = count
            else:
                del use[node]
                self.occupancy[node] = self.occupancy[node] - 1
                self.node_nets[node].discard(owner)
                self.update_overuse(node)
                self.update_spacing(node)

    def update_overuse(self, node):
        # Sharing among shadows alone is no conflict: two footprints near
        # one track are legal as long as the footprints themselves keep
        # their spacing, which the footprint pairs check. A node is overused
        # once a real net shares it with anyone.
        owners = self.node_nets.get(node, ())
        real = sum(1 for o in owners if not isinstance(o, tuple))
        if real >= 1 and len(owners) >= 2 or real >= 2:
            self.overused.add(node)
        else:
            self.overused.discard(node)

    def add_seg(self, net_name, key, seg):
        self.routes[net_name][key] = seg
        self.add_nodes(net_name, seg.nodes)
        if seg.shadows:
            self.add_nodes(('bridge', net_name), seg.shadows)
        for ti, node in seg.pairs:
            for kind in ('m2', 'm1', 'via', 'mcon'):
                self.add_foot((net_name, ti, node, kind))

    def remove_seg(self, net_name, key):
        seg = self.routes[net_name].pop(key)
        self.remove_nodes(net_name, seg.nodes)
        if seg.shadows:
            self.remove_nodes(('bridge', net_name), seg.shadows)
        for ti, node in seg.pairs:
            for kind in ('m2', 'm1', 'via', 'mcon'):
                self.remove_foot((net_name, ti, node, kind))

    def add_foot(self, key):
        entry = self.foot_rects.get(key)
        if entry is None:
            return
        count = self.foot.get(key, 0)
        self.foot[key] = count + 1
        if count:
            return
        (x0, y0, x1, y1), kind, sp = entry
        for other in self.foot:
            if other is key:
                continue
            (ox0, oy0, ox1, oy1), okind, _ = self.foot_rects[other]
            if okind != kind:   # different layers do not conflict
                continue
            if not (x0 - sp < ox1 and x1 + sp > ox0
                    and y0 - sp < oy1 and y1 + sp > oy0):
                continue
            # A same-net landing that overlaps merges cleanly; one that only
            # comes within spacing without touching is a notch. Cut layers
            # never merge, so any two distinct cuts within spacing conflict.
            if kind == 'm1' and other[0] == key[0]:
                overlap = (x0 < ox1 and x1 > ox0 and y0 < oy1 and y1 > oy0)
                if overlap:
                    continue
            self.foot_bad.add(frozenset((key, other)))

    def remove_foot(self, key):
        if key not in self.foot:
            return
        count = self.foot[key] - 1
        if count:
            self.foot[key] = count
            return
        del self.foot[key]
        self.foot_bad = {pair for pair in self.foot_bad if key not in pair}

    def conflicts(self):
        """The contested nodes and the real nets to rip up, as a pair."""
        nodes = set(self.overused)
        for pair in self.spacing_bad:
            nodes.update(pair)
        owners = set()
        for node in nodes:
            for owner in self.node_nets.get(node, ()):
                owners.add(owner)
                if isinstance(owner, tuple):
                    # A shadow conflict can also resolve by moving the
                    # shadowing terminal, so its net negotiates too.
                    owners.add(owner[1])
        for pair in self.foot_bad:
            for key in pair:
                owners.add(key[0])
                nodes.add(key[2])
        return nodes, {net for net in owners if net in self.routes}


def route_nets(routed_nets, pins, cfg, xmax, port_nets=(), blocked=frozenset(),
        tap_landings=(), port_edges=None, m1_shapes=(), direct_pins=frozenset()):
    """Route the signal nets with negotiated-congestion maze routing.

    Each net is decomposed into 2-pin *segments* along an MST over its
    terminals, plus min-area-extension and port-escape segments, and
    rip-up-and-reroute runs at segment granularity. After an initial pass, each
    iteration reroutes only the segments touching a conflict, raising the cost
    of the contested nodes until the routing is legal. Two things let this scale
    to a few hundred cells: rerouting single 2-pin connections rather than whole
    trees, and a pattern-routing fast path (L then Z shapes) that reserves the
    corridor-bounded maze search for contested segments.

    Args:
        routed_nets: the signal nets to route, ``{name: NetInfo}``.
        pins: ``{inst: {pin: [Rect4I]}}`` die-coordinate pin rectangles.
        cfg: the routing grid + DRC geometry (:class:`GridConfig`).
        xmax: the maximum x track index, the right die edge.
        port_nets: the nets needing a Metal4 escape to an edge.
        blocked: nodes reserved for the power stripes' rail taps
            (:func:`~.flow.plan_pdn`). No route, terminal access or escape
            column may use them.
        tap_landings: ``(x, y)`` centers of the taps' Metal2 landings behind
            ``blocked``, which off-track access bridges must keep metal
            spacing from.
        m1_shapes: ``((rect, net or None), ...)`` die-coordinate pin-layer
            metal of the placed cells (every pin rect with its net, and the
            cells' obstruction rects), which access landings must merge
            with or keep metal spacing from.
        port_edges: ``{port net: edge}`` naming the die edge ('top',
            'bottom', 'left' or 'right') each port leaves by, which is
            normally the parent's decision. A net left out falls back to its
            nearest edge, which is blind to the parent's connectivity. A key
            naming no port of this block is rejected rather than ignored.
            Supply names are accepted and ignored, since the supplies leave
            on their stripes.

    Returns:
        The :class:`RoutingResult` for the whole block.

    Raises:
        PinAccessError: a terminal is unreachable on the grid. This is
            permanent, so the caller re-raises instead of retrying.
        RuntimeError: the rip-up loop did not converge, after which the caller
            grows the floorplan and retries.
    """
    if port_edges:
        # A key that names nothing is a typo or a stale port name, and left
        # unchecked it would silently fall back to the nearest edge. Supply
        # names are accepted and ignored, since the natural thing to pass is
        # every pin of the symbol and the supplies leave on their stripes.
        known = set(port_nets) | set(cfg.supply_net_names)
        unknown = sorted(set(port_edges) - known)
        if unknown:
            raise ValueError(
                f"port_edges names {unknown}, which are no escaped ports of "
                f"this block. Its ports are {sorted(port_nets)}")
        bad = sorted(set(port_edges.values()) - set(PORT_EDGES))
        if bad:
            raise ValueError(
                f"port_edges values must be one of {PORT_EDGES}, not {bad}")
        if not cfg.use_upper:
            vertical = sorted(name for name, edge in port_edges.items()
                if edge in ('top', 'bottom'))
            if vertical:
                raise ValueError(
                    f"ports {vertical} name a top or bottom edge, whose "
                    "Metal4 pads are unreachable with use_upper disabled")

    # term_access[net] holds each terminal's candidate (xi, yi, M2) access
    # nodes. term_via and term_land hold the off-track Via1 positions and the
    # pin-aware Metal1 landings. Both key on (net, terminal, node): different
    # pins may share a candidate node, so a node-only key could attribute one
    # pin's via geometry to another.
    term_access = {}
    term_via = {}
    term_land = {}
    foot_rects = {}   # (net, ti, node) -> off-grid Metal2 footprint
    sub_nodes = set()  # (net, node) reached through a pin-access sub-via
    sole = {}   # node -> (net, inst, pin) for terminals with a single candidate
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch

    # An off-track terminal's Metal2 bridge is an off-grid rect the node-based
    # conflict model cannot see, and the rail-tap landings are off-grid too.
    # Reject any off-track candidate whose bridge would come within the metal
    # spacing of a tap landing (rects mutually expanded, so conservative).
    spacing = cfg.wire_space[0]
    m2_half_w, m2_land_half = cfg.wire_width[0] // 2, cfg.land_half_h[0]
    tap_half_w, tap_half_h = tap_m2_land(cfg)

    # Cell metal on the pin layer, bucketed by x so a landing checks only
    # its neighborhood.
    m1_buckets = {}
    for rect, snet in m1_shapes:
        for bx in range(rect.lx // 10000, rect.ux // 10000 + 1):
            m1_buckets.setdefault(bx, []).append((rect, snet))

    def land_clear(own_nets, land):
        # The landing must keep metal spacing from foreign metal, and from
        # same-net metal too unless it merges into it, since two disjoint
        # same-net pieces within spacing are a notch. A same-net pin is a
        # merged group of rects, so overlapping any of them counts as
        # merging with all. Cell-internal geometry is DRC-clean on its own,
        # so only the landing is checked.
        x0, y0, x1, y1 = land
        merged = False
        near_own = False
        for bx in range((x0 - spacing) // 10000, (x1 + spacing) // 10000 + 1):
            for rect, snet in m1_buckets.get(bx, ()):
                if (x0 - spacing < rect.ux and x1 + spacing > rect.lx
                        and y0 - spacing < rect.uy and y1 + spacing > rect.ly):
                    if snet not in own_nets:
                        return False
                    near_own = True
                    if (x0 <= rect.ux and x1 >= rect.lx
                            and y0 <= rect.uy and y1 >= rect.ly):
                        merged = True
        return merged or not near_own

    def bridge_clear(xi, via_x, via_y):
        x_lo = min(via_x, xi * x_pitch) - m2_half_w - spacing
        x_hi = max(via_x, xi * x_pitch) + m2_half_w + spacing
        y_lo = via_y - m2_land_half - spacing
        y_hi = via_y + m2_land_half + spacing
        for tap_x, tap_y in tap_landings:
            if (x_lo < tap_x + tap_half_w and x_hi > tap_x - tap_half_w
                    and y_lo < tap_y + tap_half_h
                    and y_hi > tap_y - tap_half_h):
                return False
        return True

    for net_name, net in routed_nets.items():
        # A power *pin* (vdd/vss) is reached on its wide rail track. Key off
        # the pin name so a tie-off net's rail terminal also uses rail access.
        cands = []
        for ti, (iname, pname) in enumerate(net.terminals):
            term = []
            # A tie net reaches a supply pin, whose metal is tagged with
            # the rail's net, so both names count as this terminal's own.
            own_nets = {net_name}
            if pname == cfg.vdd_pin:
                own_nets.add(cfg.vdd_net)
            elif pname == cfg.vss_pin:
                own_nets.add(cfg.vss_net)
            rail = pname in cfg.supply_pin_names
            # On a stack with an access sub-layer, every signal pin (whether
            # on the sub-layer or a thin Metal1 strip the library routed to)
            # is reached by an emitted landing that encloses the via and
            # merges with the pin. A sub-layer pin additionally gets the
            # sub-via rung; a Metal1 pin (direct_pins) does not.
            direct = (iname, pname) in direct_pins
            landing_based = cfg.sub_via_half is not None and not rail
            is_sub = landing_based and not direct

            def try_candidates(candidates):
                for (xi, yi, via_x, via_y, land) in candidates:
                    node = (xi, yi, M2)
                    if node in blocked:   # reserved for a stripe's rail tap
                        continue
                    if not 0 <= xi <= xmax:   # an alternative beyond the die
                        continue
                    off_track = (via_x, via_y) != (xi * x_pitch,
                        yi * y_pitch)
                    if off_track and not bridge_clear(xi, via_x, via_y):
                        continue
                    if landing_based:
                        # The access emits a Metal1 landing enclosing the
                        # via, grown along x for min area, clearing foreign
                        # metal and the rails (which near-rail pins sit
                        # close to). A sub-layer pin adds the sub-via rung.
                        land_rect = sub_land_rect(cfg, via_x, via_y,
                            pins[iname][pname])
                        if land_rect is None or not land_clear(own_nets,
                                land_rect):
                            continue
                        if node in term:
                            continue
                        term.append(node)
                        if is_sub:
                            sub_nodes.add((net_name, node))
                        term_land[(net_name, ti, node)] = land_rect
                        # The Metal1 access landing extends past the pin, so
                        # a different net's landing within Metal1 spacing is
                        # a conflict the node model cannot see, as are the
                        # via cuts under it against any other distinct cut.
                        foot_rects[(net_name, ti, node, 'm1')] = (
                            land_rect, 'm1', cfg.m1_space)
                        vh = cfg.via_half[0]
                        foot_rects[(net_name, ti, node, 'via')] = (
                            (via_x - vh, via_y - vh, via_x + vh, via_y + vh),
                            'via', cfg.via1_space)
                        if is_sub:
                            sh = cfg.sub_via_half
                            foot_rects[(net_name, ti, node, 'mcon')] = (
                                (via_x - sh, via_y - sh,
                                    via_x + sh, via_y + sh),
                                'mcon', cfg.sub_via_space)
                        if off_track:
                            term_via[(net_name, ti, node)] = (via_x, via_y)
                            foot_rects[(net_name, ti, node, 'm2')] = (
                                bridge_footprint(cfg, xi, via_x, via_y),
                                'm2', cfg.wire_space[0])
                        continue
                    if not off_track:
                        # Via1 lands on the pin's own Metal1. A landing
                        # inside its pin adds no metal and needs no
                        # clearance; a protruding one is checked.
                        land_rect = land if land is not None else (
                            xi * x_pitch - cfg.m1_land_half_w,
                            yi * y_pitch - cfg.m1_land_half_h,
                            xi * x_pitch + cfg.m1_land_half_w,
                            yi * y_pitch + cfg.m1_land_half_h)
                        x0, y0, x1, y1 = land_rect
                        inside = any(r.lx <= x0 and r.ly <= y0
                                and r.ux >= x1 and r.uy >= y1
                            for r in pins[iname][pname])
                        if not inside and not land_clear(own_nets,
                                land_rect):
                            continue
                    if node in term:
                        continue
                    term.append(node)
                    vh = cfg.via_half[0]
                    foot_rects[(net_name, ti, node, 'via')] = (
                        (via_x - vh, via_y - vh, via_x + vh, via_y + vh),
                        'via', cfg.via1_space)
                    if off_track:
                        term_via[(net_name, ti, node)] = (via_x, via_y)
                        foot_rects[(net_name, ti, node, 'm2')] = (
                            bridge_footprint(cfg, xi, via_x, via_y),
                            'm2', cfg.wire_space[0])
                    elif land is not None:
                        term_land[(net_name, ti, node)] = land

            if direct:
                # A thin Metal1 strip cannot enclose the via, so the via
                # only has to be covered by the pin; the landing encloses it.
                try_candidates((xi, yi, via_x, via_y, None)
                    for (xi, yi, via_x, via_y)
                    in landing_access(pins[iname][pname], cfg))
            else:
                # A sub-layer pin must enclose the sub-via itself
                # (li1 enclosure of the mcon), so the enclosure-based
                # candidates apply, with the landing added above them.
                try_candidates(access_nodes(pins[iname][pname], cfg, rail,
                    False))
                if not term and not rail:
                    # Every on-track landing collided with cell metal, but
                    # an off-track via takes its enclosure from the pin.
                    try_candidates((xi, yi, via_x, via_y, None)
                        for (xi, yi, via_x, via_y)
                        in offtrack_access(pins[iname][pname], cfg))
            if not term:
                raise PinAccessError(f"pin {iname}.{pname} (net {net_name!r}) "
                    "has no routable access point on or off the track grid")
            # Two pins on different nets whose *only* candidate is the same node
            # can never both be routed. Fail with the pin names now instead of
            # after a full non-converging rip-up run.
            if len(term) == 1:
                other = sole.get(term[0])
                if other is not None and other[0] != net_name:
                    raise PinAccessError(
                        f"pins {other[1]}.{other[2]} (net {other[0]!r}) and "
                        f"{iname}.{pname} (net {net_name!r}) share their only "
                        "grid access node, so both nets cannot be routed")
                sole[term[0]] = (net_name, iname, pname)
            cands.append(term)
        term_access[net_name] = cands

    # Global routing assigns each net a corridor of gcells. Detailed routing
    # stays inside the corridor (cheap, congestion-balanced), falling back to the
    # whole grid only if a net can't be realized there.
    corridors = global_route(routed_nets, term_access, cfg, xmax)

    # Every port net gets a unique escape track on its edge, near the mean
    # position of its pin candidates: a Metal4 column for the top and bottom
    # edges, a Metal3 row for the left and right ones. Uniqueness removes pad
    # contention by construction and keeps each escape a directed single-goal
    # search. A shared full-edge goal line converges too but pays a fan-out
    # search per escape, and per-net goal windows do not converge at all. The
    # edges allocate independently. Tracks whose edge node is blocked by a
    # stripe's rail tap cannot host a pad.
    def mean_pos(port_name, axis):
        cs = [n[axis] for term in term_access[port_name] for n in term]
        return sum(cs) / len(cs)

    def chosen_edge(port_name):
        if port_edges and port_name in port_edges:
            return port_edges[port_name]
        # Escape to the nearest edge, so a port driven from deep inside the
        # block does not cross it, only for the parent to bring the wire
        # straight back.
        x = mean_pos(port_name, 0) * x_pitch
        y = mean_pos(port_name, 1) * y_pitch
        dists = {'left': x, 'right': xmax * x_pitch - x,
            'bottom': y, 'top': cfg.y_track_max * y_pitch - y}
        if not cfg.use_upper:
            # Top and bottom pads sit on Metal4, which is off limits.
            dists.pop('top'), dists.pop('bottom')
        return min(dists, key=dists.get)

    escape_at = {}   # port net -> (track index, edge)
    by_edge = {}
    for port_name in sorted(port_nets):
        by_edge.setdefault(chosen_edge(port_name), []).append(port_name)
    m4_mult = cfg.track_mult[LIDX[M4]]
    m4_off = cfg.track_off[LIDX[M4]]
    m3_mult_e = cfg.track_mult[LIDX[M3]]
    m3_off_e = cfg.track_off[LIDX[M3]]
    for edge, names in by_edge.items():
        if edge in ('top', 'bottom'):
            yrow = escape_row(cfg, edge)
            usable = [x for x in range(m4_off, xmax + 1, m4_mult)
                if (x, yrow, M4) not in blocked]
            axis = 0
        else:
            xcol = escape_col(xmax, edge)
            usable = [y for y in range(m3_off_e, cfg.y_track_max + 1,
                    m3_mult_e)
                if cfg.is_signal_track(y) and (xcol, y, M3) not in blocked]
            axis = 1
        if len(names) > len(usable):
            raise EscapeCapacityError(f"{len(names)} {edge}-edge port "
                f"escapes need more tracks than the die has free "
                f"({len(usable)})", len(names) - len(usable), edge)
        prefs = sorted((mean_pos(name, axis), name) for name in names)
        prev = -1
        for k, (pref, port_name) in enumerate(prefs):
            hi = len(usable) - (len(prefs) - k)   # room for the ports after us
            prev = min(max(prev + 1, bisect.bisect_left(usable, round(pref))), hi)
            escape_at[port_name] = (usable[prev], edge)

    reach = spacing_reach(cfg)
    cong = Congestion(reach, foot_rects)
    # Local aliases for the read-only lookups in the routing closures below.
    history, occupancy = cong.history, cong.occupancy
    node_nets, routes, net_use = cong.node_nets, cong.routes, cong.net_use
    port_escape = {}      # port net -> (x track, edge) of its Metal4 pad, or None
    penalty = [0.5]       # present-congestion penalty, raised each rip-up pass
    adj = GridAdjacency(cfg, xmax, blocked)   # lazy per-run move table for A*

    # Fixed 2-pin decomposition: each net's terminals are spanned by an MST
    # (over first-candidate positions), and every MST edge is an independently
    # routable and independently rip-up-able segment. Segment keys per net:
    # ('t', k) for MST edge k, 'seat' for a 1-terminal net's access node, 'ext'
    # for the min-area extensions, 'esc' for the port escape.
    topo = {net_name: mst_edges([term[0][:2] for term in term_access[net_name]])
        for net_name in routed_nets}

    def make_node_cost(net_name):
        # A node used by this net's *other* segments costs only history, so
        # segments share track (Steiner-like reuse). Foreign occupancy pays
        # the present-congestion penalty. (The maze router inlines the same
        # cost. This closure serves the min-area growth decisions.)
        own = net_use[net_name]
        def node_cost(node, _hist=history.get, _occ=occupancy.get, _own=own):
            base = _hist(node, 0.0)
            if node in _own:
                return base
            return base + penalty[0] * _occ(node, 0)
        return node_cost

    m2_mult = cfg.track_mult[LIDX[M2]]
    m2_half_w = cfg.wire_width[0] // 2
    m2_ext = cfg.wire_ext[0]

    def jog_reserved(net_name, ti, node):
        # An off-track terminal's footprint (bridge, pads and landing,
        # bridge_footprint) is off-grid metal the node model cannot see.
        # Reserve the neighboring-track nodes on the footprint's rows where
        # a wire would come within the metal spacing of it, for this net
        # too, so wires detour around the footprint instead of grazing it.
        if (net_name, ti, node) not in term_via:
            return ()
        rect = foot_rects[(net_name, ti, node, 'm2')][0]
        xi, yi, _layer = node
        # A node's metal can protrude past it by its wire ext or a landing
        # half, so the shadow rows cover the footprint plus that margin.
        margin = max(m2_ext, cfg.land_half_h[0]) + spacing
        shadows = []
        for nxi in (xi - m2_mult, xi + m2_mult):
            if not 0 <= nxi <= xmax:
                continue
            tx = nxi * x_pitch
            if (rect[0] - spacing >= tx + m2_half_w
                    or rect[2] + spacing <= tx - m2_half_w):
                continue
            for nyi in range(max(0, (rect[1] - margin) // y_pitch + 1),
                    min(cfg.y_track_max, (rect[3] + margin) // y_pitch) + 1):
                shadows.append((nxi, nyi, M2))
        return tuple(shadows)

    def pattern_route(net_name, starts, goals):
        # Pattern-routing fast path: try the 1-bend L shapes, then the 2-bend
        # Z shapes, between the closest access-node pairs, taking one whose
        # nodes are all conflict-free. That is a few dict probes per node where
        # a maze search is a heap expansion over a region, and in the initial
        # pass almost every segment is a clean L. Contested nodes are left to
        # A*, which negotiates.
        own = {net_name}

        def free(node):
            if node in blocked or history.get(node):
                return False
            here = node_nets.get(node)
            if here and here != own:
                return False
            for neighbor in spacing_neighbors(node, reach):
                there = node_nets.get(neighbor)
                if there and there - own:
                    return False
            return True

        m3_mult = cfg.track_mult[LIDX[M3]]
        m3_off = cfg.track_off[LIDX[M3]]

        def bendable(y):
            # A bend is a via between M2 and M3, so the row must be a signal
            # track that exists on M3.
            return cfg.is_signal_track(y) and (y - m3_off) % m3_mult == 0

        def m2_run(xi, y0, y1):
            step = 1 if y1 >= y0 else -1
            return [(xi, y, M2) for y in range(y0, y1 + step, step)]

        def m3_run(yi, x0, x1):
            step = 1 if x1 >= x0 else -1
            return [(x, yi, M3) for x in range(x0, x1 + step, step)]

        # Try the closest few start/goal combinations only: a pin with many
        # access candidates must not turn the fast path into a pair sweep.
        pairs = sorted(((s, g) for s in starts for g in goals),
            key=lambda sg: abs(sg[0][0] - sg[1][0]) + abs(sg[0][1] - sg[1][1]))
        for s, g in pairs[:8]:
            if s[2] != M2 or g[2] != M2:
                continue
            (x1, y1, _layer), (x2, y2, _layer) = s, g
            cands = []
            if x1 == x2:
                cands.append(m2_run(x1, y1, y2))
            else:
                # Vias sit on the bend tracks, so both must allow a layer
                # change.
                if bendable(y2):
                    cands.append(m2_run(x1, y1, y2)
                        + m3_run(y2, x1, x2) + [(x2, y2, M2)])
                if bendable(y1):
                    cands.append([(x1, y1, M2)] + m3_run(y1, x1, x2)
                        + m2_run(x2, y1, y2))
            for path in cands:
                if all(map(free, path)):
                    return path
        # Z patterns: both L corners were contested, so sweep the crossover
        # track between the endpoints. Same wirelength as an L, and the
        # vertical-horizontal-vertical shape has the same via count too.
        for s, g in pairs[:4]:
            if s[2] != M2 or g[2] != M2:
                continue
            (x1, y1, _layer), (x2, y2, _layer) = s, g
            if x1 == x2 or y1 == y2:
                continue
            y_lo, y_hi = sorted((y1, y2))
            for y_bend in range(y_lo + 1, y_hi):
                if not bendable(y_bend):
                    continue
                path = (m2_run(x1, y1, y_bend) + m3_run(y_bend, x1, x2)
                    + m2_run(x2, y_bend, y2))
                if all(map(free, path)):
                    return path
            # Horizontal-vertical-horizontal Z, which costs two more vias.
            # Sample the bend columns so a die-wide net stays a bounded check.
            if bendable(y1) and bendable(y2):
                m2_mult = cfg.track_mult[LIDX[M2]]
                m2_off = cfg.track_off[LIDX[M2]]
                x_lo, x_hi = sorted((x1, x2))
                for x_bend in range(x_lo + 1, x_hi, max((x_hi - x_lo) // 16, 1)):
                    if (x_bend - m2_off) % m2_mult:
                        continue
                    path = ([(x1, y1, M2)] + m3_run(y1, x1, x_bend)
                        + m2_run(x_bend, y1, y2) + m3_run(y2, x_bend, x2)
                        + [(x2, y2, M2)])
                    if all(map(free, path)):
                        return path
        return None

    def route_seg(net_name, key, allowed):
        node_cost = make_node_cost(net_name)
        terms = term_access[net_name]
        own_use = net_use[net_name]

        if key == 'seat':
            # 1-terminal port: seat the access node so 'esc' can lift it.
            node = terms[0][0]
            return RouteSeg((), frozenset((node,)), ((0, node),),
                jog_reserved(net_name, 0, node))

        if isinstance(key, tuple):        # ('t', k): one MST edge, 2-pin A*
            ti, tj = topo[net_name][key[1]]
            path = (pattern_route(net_name, terms[ti], terms[tj])
                or astar(terms[ti], terms[tj], cfg, xmax, history, occupancy,
                    own_use, penalty[0], allowed, adj)
                or astar(terms[ti], terms[tj], cfg, xmax, history, occupancy,
                    own_use, penalty[0], None, adj))
            if path is None:
                # The full grid is connected and congestion only adds cost, so
                # this means a terminal is unreachable, which is permanent.
                raise PinAccessError(f"net {net_name!r} could not be routed: a "
                    "terminal is unreachable on the routing grid")
            shadows = (jog_reserved(net_name, ti, path[0])
                + jog_reserved(net_name, tj, path[-1]))
            return RouteSeg(tuple(zip(path, path[1:])), frozenset(path),
                ((ti, path[0]), (tj, path[-1])), shadows)

        if key == 'esc':
            # Port escape: lift the net to its reserved edge track (a Metal4
            # column on the top and bottom edges, a Metal3 row on the sides),
            # so its pin sits flush at the die edge. The parent then connects
            # there, never over the interior. That edge interface is what
            # keeps the block composable (a placement change can't drop a
            # parent wire onto an internal net). vdd/vss go to their stripes.
            tree = set(own_use)
            track, edge = escape_at[net_name]
            if edge in ('top', 'bottom'):
                yrow = escape_row(cfg, edge)
                goal = [(track, yrow, M4)]
                fallback = [(x, yrow, M4)
                    for x in range(m4_off, xmax + 1, m4_mult)]
            else:
                xcol = escape_col(xmax, edge)
                goal = [(xcol, track, M3)]
                fallback = [(xcol, y, M3)
                    for y in range(m3_off_e, cfg.y_track_max + 1, m3_mult_e)
                    if cfg.is_signal_track(y)]
            path = astar(tree, goal, cfg, xmax, history, occupancy, own_use,
                penalty[0], None, adj)
            if path is None:   # blocked track: any node on that edge will do
                path = astar(tree, fallback, cfg, xmax, history, occupancy,
                    own_use, penalty[0], None, adj)
            if path is None:
                # The full grid is connected, so an unreachable edge is
                # permanent, and a port without its edge pad would leave the
                # parent to route over the block interior.
                raise PinAccessError(
                    f"port {net_name!r} cannot reach its {edge} edge")
            axis = 0 if edge in ('top', 'bottom') else 1
            port_escape[net_name] = (path[-1][axis], edge)
            shadows = ()
            if edge in ('left', 'right'):
                # The side pad reaches port_pad_inner into the block along
                # its Metal3 row, over columns the path does not occupy, so
                # those nodes are reserved like a bridge's shadow.
                row = path[-1][1]
                reach = (cfg.port_pad_inner + cfg.wire_space[LIDX[M3]]
                    + cfg.wire_ext[LIDX[M3]]) // x_pitch
                cols = (range(0, reach + 1) if edge == 'left'
                    else range(xmax - reach, xmax + 1))
                on_path = frozenset(path)
                shadows = tuple((x, row, M3) for x in cols
                    if 0 <= x <= xmax and (x, row, M3) not in on_path)
            return RouteSeg(tuple(zip(path, path[1:])), frozenset(path), (),
                shadows)

        # key == 'ext': grow each per-track run of the net to the min-area
        # span (the escape, routed after this, is covered by the
        # extend_min_area post-pass instead). Doing it inside the negotiation
        # lets a conflicting extension be rerouted rather than silently
        # shorting a neighbor.
        vert_runs, horiz_runs = {}, {}
        for (xi, yi, layer) in own_use:
            if layer in VERT: vert_runs.setdefault((layer, xi), set()).add(yi)
            elif layer in HORIZ: horiz_runs.setdefault((layer, yi), set()).add(xi)
        ext_edges, ext_nodes = [], set()

        def grow(coords, make_node, lo_b, hi_b, mat):
            run = sorted(coords)
            while run[-1] - run[0] < mat:
                hi, lo = run[-1] + 1, run[0] - 1
                hi_ok = hi <= hi_b and make_node(hi) not in blocked
                lo_ok = lo >= lo_b and make_node(lo) not in blocked
                # When both sides are legal, grow toward the cheaper (less
                # congested) one so the extension is least likely to conflict.
                pick_hi = hi_ok and (not lo_ok
                    or node_cost(make_node(hi)) <= node_cost(make_node(lo)))
                if pick_hi:
                    ext_edges.append((make_node(run[-1]), make_node(hi)))
                    ext_nodes.add(make_node(hi)); run.append(hi)
                elif lo_ok:
                    ext_edges.append((make_node(run[0]), make_node(lo)))
                    ext_nodes.add(make_node(lo)); run.insert(0, lo)
                else:
                    break

        # Default-arg capture (X/Y/L) freezes the loop vars into each lambda.
        for (layer, xi), y_tracks in vert_runs.items():
            grow(y_tracks, lambda p, X=xi, L=layer: (X, p, L), 1,
                cfg.y_track_max - 1, cfg.min_area_tracks[LIDX[layer]])
        for (layer, yi), x_tracks in horiz_runs.items():
            grow(x_tracks, lambda p, Y=yi, L=layer: (p, Y, L), 0, xmax,
                cfg.min_area_tracks[LIDX[layer]])
        return RouteSeg(tuple(ext_edges), frozenset(ext_nodes), ())

    add_seg, remove_seg, conflicts = cong.add_seg, cong.remove_seg, cong.conflicts

    # Initial pass: route every net's segments once in its corridor (each
    # segment falls back to the full grid if the corridor is blocked).
    for net_name in routed_nets:
        routes[net_name] = {}
        net_use[net_name] = {}
        allowed = corridors[net_name]
        if len(term_access[net_name]) == 1:
            add_seg(net_name, 'seat', route_seg(net_name, 'seat', allowed))
        for k in range(len(topo[net_name])):
            add_seg(net_name, ('t', k), route_seg(net_name, ('t', k), allowed))
        add_seg(net_name, 'ext', route_seg(net_name, 'ext', allowed))
        if net_name in port_nets:
            add_seg(net_name, 'esc', route_seg(net_name, 'esc', allowed))

    # Incremental negotiated-congestion rip-up at SEGMENT granularity: only the
    # segments whose nodes touch a conflict are rerouted, so a conflict on a
    # high-fan-out net redoes one 2-pin connection, not the whole tree. A moved
    # segment invalidates the net's min-area extensions and the escape's
    # attachment point, so those are recomputed with it (cheap: 'ext' needs no
    # search, 'esc' one directed search).
    for iteration in range(3000):
        bad_nodes, bad_nets = conflicts()
        if not bad_nodes:
            break
        for node in bad_nodes:
            history[node] = history.get(node, 0.0) + 1.0
        penalty[0] = min(penalty[0] * 1.05, 50.0)
        # Once congestion has built up, let stubborn nets leave their corridor.
        allow_escape = iteration > 200
        for net_name in sorted(bad_nets):
            segs = routes[net_name]
            redo = {key for key, seg in segs.items()
                if not bad_nodes.isdisjoint(seg.nodes)}
            if redo - {'esc'}:   # net structure moved: ext + esc must follow
                redo |= {'ext', 'esc'} & segs.keys()
            order = [key for key in segs if key in redo]   # seat/topo, ext, esc
            for key in order:
                remove_seg(net_name, key)
            allowed = None if allow_escape else corridors[net_name]
            for key in order:
                add_seg(net_name, key, route_seg(net_name, key, allowed))
    else:
        raise RuntimeError(
            f"router did not converge: {len(bad_nodes)} conflict nodes")

    # Consolidate the per-(net, terminal) via/landing overrides down to the
    # access nodes the router actually picked (the segments' terminal pairs),
    # per net. Two terminals of one net may land on the same node only if they
    # agree on the via geometry, otherwise the emitter could realise one pin's
    # access but not the other's.
    routing, net_via, net_land = {}, {}, {}
    reserved = set()   # bridge-shadow nodes, kept clear of later wire growth
    for net_name, segs in routes.items():
        edges, pairs = [], []
        for seg in segs.values():
            edges.extend(seg.edges)
            pairs.extend(seg.pairs)
            reserved.update(seg.shadows)
        routing[net_name] = (edges, [node for _ti, node in pairs])
        tv = net_via.setdefault(net_name, {})
        tl = net_land.setdefault(net_name, {})
        seen = {}   # node -> terminal index that claimed it
        for ti, node in pairs:
            via = term_via.get((net_name, ti, node))
            if node in seen:
                if (seen[node] != ti
                        and via != term_via.get((net_name, seen[node], node))):
                    terms = routed_nets[net_name].terminals
                    a, b = terms[seen[node]], terms[ti]
                    raise PinAccessError(
                        f"net {net_name!r}: pins {a[0]}.{a[1]} and "
                        f"{b[0]}.{b[1]} landed on one grid node with "
                        "different via geometry")
                continue
            seen[node] = ti
            if via is not None:
                tv[node] = via
            # A sub-access terminal carries both an off-track via and its
            # Metal1 landing, so the landing is recorded regardless of via.
            land = term_land.get((net_name, ti, node))
            if land is not None:
                tl[node] = land
    net_sub = {}
    for net_name, node in sub_nodes:
        net_sub.setdefault(net_name, set()).add(node)
    return RoutingResult(nets=routing, port_escape=port_escape,
        term_via=net_via, term_land=net_land, reserved=frozenset(reserved),
        sub_nodes=net_sub)



def tap_avoid_columns(routed_nets, pins, cfg):
    """Find the track columns where a stripe's rail tap could strand a pin
    access.

    A terminal negotiates congestion by retreating to another of its access
    candidates. A terminal all of whose candidates one tap column would
    invalidate has no retreat, so a conflict there can never resolve and the
    rip-up loop deadlocks. A tap invalidates a candidate in two ways:

    * its blocked rail-adjacent Metal2 nodes fall within the candidate's
      min-area growth window (only the candidate's own column), pinning the
      access stub against whatever holds the tracks on its other side,
    * its rail landing lies within metal spacing of an off-track candidate's
      access bridge, so route_nets' bridge_clear filter drops the candidate.

    The growth-window test is deliberately conservative, testing window overlap
    rather than exact strangulation. A false positive only nudges a tap
    sideways, while a false negative stalls the router.

    Args:
        routed_nets: the signal nets that will be routed, ``{name: NetInfo}``.
        pins: ``{inst: {pin: [Rect4I]}}`` die-coordinate pin rectangles.
        cfg: the routing grid + geometry (:class:`GridConfig`).

    Returns:
        The tap-hostile column indices as a set.
    """
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    mat, half_w, land_half = cfg.min_area_tracks[0], cfg.wire_width[0] // 2, cfg.land_half_h[0]
    tap_half_w, tap_half_h = tap_m2_land(cfg)
    spacing = cfg.wire_space[0]
    # Taps sit on every rail of a stripe's net, the edge rails included.
    rail_zones = [(r * cfg.tracks_per_row - 1, r * cfg.tracks_per_row + 1)
        for r in range(cfg.n_rows + 1)]

    def killer_columns(xi, yi, via_x, via_y):
        # The columns whose tap would invalidate this one candidate.
        cols = set()
        if any(yi - mat <= hi and yi + mat >= lo for lo, hi in rail_zones):
            cols.add(xi)
        if (via_x, via_y) != (xi * x_pitch, yi * y_pitch):   # off-track bridge
            # The same mutually-expanded-rect test as route_nets' bridge_clear.
            x_lo = min(via_x, xi * x_pitch) - half_w - spacing
            x_hi = max(via_x, xi * x_pitch) + half_w + spacing
            near_rail = any(
                abs(via_y - r * cfg.row_height) < land_half + tap_half_h
                    + spacing
                for r in range(cfg.n_rows + 1))
            if near_rail:
                for xc in range(max(x_lo // x_pitch, 0), x_hi // x_pitch + 2):
                    if (x_lo < xc * x_pitch + tap_half_w
                            and x_hi > xc * x_pitch - tap_half_w):
                        cols.add(xc)
        return cols

    avoid = set()
    for net in routed_nets.values():
        for iname, pname in net.terminals:
            fatal = None   # columns that invalidate EVERY candidate so far
            for (xi, yi, via_x, via_y, _land) in access_nodes(
                    pins[iname][pname], cfg,
                    pname in cfg.supply_pin_names):
                cols = killer_columns(xi, yi, via_x, via_y)
                fatal = cols if fatal is None else fatal & cols
                if not fatal:
                    break
            if fatal:
                avoid |= fatal
    return avoid



def extend_min_area(result, cfg, xmax, keepout=frozenset()):
    """Post-pass: lengthen any too-short wire so it meets the metal min-area rule.

    A min-width wire must span enough tracks to meet min area and give its
    end-via the required endcap, so each per-net, per-track run grows into free
    tracks until it spans its layer's ``cfg.min_area_tracks`` steps.

    Args:
        result: the routing ``{net: (edges, term_m2)}`` to extend in place.
        cfg: the routing grid + geometry (:class:`GridConfig`).
        xmax: the maximum x track index.
        keepout: nodes no extension may grow into, the rail-tap blockages and
            the off-track access-bridge shadows.

    Returns:
        The same ``result`` mapping, mutated in place.
    """
    node_net = {}   # (xi, yi, layer) -> net_name
    for net_name, (edges, _term_m2) in result.items():
        for a, b in edges:
            node_net[a] = net_name; node_net[b] = net_name

    reach = spacing_reach(cfg)

    def free(node, net_name):
        if node in keepout:
            return False
        owner = node_net.get(node)
        if owner is not None and owner != net_name:
            return False
        # Don't grow into a same-layer spacing conflict with another net.
        for adj in spacing_neighbors(node, reach):
            adj_owner = node_net.get(adj)
            if adj_owner is not None and adj_owner != net_name:
                return False
        return True

    for net_name, (edges, term_m2) in result.items():
        nodes = set()
        for a, b in edges:
            nodes.add(a); nodes.add(b)
        vert = {}    # (layer, xi) -> set(yi)   for the vertical layers
        horiz = {}   # (layer, yi) -> set(xi)   for the horizontal layers
        for (xi, yi, layer) in nodes:
            if layer in VERT: vert.setdefault((layer, xi), set()).add(yi)
            elif layer in HORIZ: horiz.setdefault((layer, yi), set()).add(xi)

        def grow(fixed, coords, lo, hi, make_node, mat):
            """Extend a 1-D run of ``coords`` to span ``mat`` grid steps."""
            run = sorted(coords)
            need = mat - (run[-1] - run[0])
            while need > 0:
                lo_ok = run[0] - 1 >= lo and free(make_node(fixed, run[0] - 1), net_name)
                hi_ok = run[-1] + 1 <= hi and free(make_node(fixed, run[-1] + 1), net_name)
                if hi_ok:
                    next_t = run[-1] + 1
                    edges.append((make_node(fixed, run[-1]), make_node(fixed, next_t)))
                    node_net[make_node(fixed, next_t)] = net_name; run.append(next_t)
                elif lo_ok:
                    next_t = run[0] - 1
                    edges.append((make_node(fixed, run[0]), make_node(fixed, next_t)))
                    node_net[make_node(fixed, next_t)] = net_name; run.insert(0, next_t)
                else:
                    break
                need -= 1

        for (layer, xi), y_tracks in vert.items():
            grow(xi, y_tracks, 1, cfg.y_track_max - 1,
                lambda xi, yi, L=layer: (xi, yi, L),
                cfg.min_area_tracks[LIDX[layer]])
        for (layer, yi), x_tracks in horiz.items():
            grow(yi, x_tracks, 0, xmax,
                lambda yi, xi, L=layer: (xi, yi, L),
                cfg.min_area_tracks[LIDX[layer]])
    return result
