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


# Internal layer codes. These are abstract routing-stack positions, not PDK
# layers. The engine routes on two vertical layers (codes M2, M4) and two
# horizontal (M3, M5), with M1 reserved for pin access. Doubling the routing
# layers roughly doubles capacity, as production routers do. A RoutingStack from
# the PDK binding maps these codes to concrete PDK layers, so no PDK layer name
# is baked into the engine.
M2, M3, M1, M4, M5 = 0, 1, 2, 3, 4
VERT = (M2, M4)        # vertical routing layers (move in y)
HORIZ = (M3, M5)       # horizontal routing layers (move in x)


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
            port_escape: ``{net: x_track}``, the top-edge column each escaped port
                net's Metal4 pad sits on.
            term_via: ``{net: {node: (via_x, via_y)}}`` for off-track terminals,
                whose Via1 sits beside the access node rather than on it.
            term_land: ``{net: {node: rect}}``, the Metal1 landing an off-track or
                short pin needs under its Via1.
            reserved: nodes shadowed by an off-track access bridge. No later wire
                growth may take them, not even the bridge's own net.
        """
    nets: dict
    port_escape: dict
    term_via: dict
    term_land: dict
    reserved: frozenset


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


def access_nodes(rects, cfg, allow_rail=False):
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
    via_half, encl, encl_endcap = cfg.via_half, cfg.encl, cfg.encl_endcap
    half_w, endcap = cfg.strap_half_w, cfg.m1_land_half_h
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    found = {}   # (xi, yi) -> (track_x, track_y, land, tier); tier 0 = pair-of-sides endcap
    for (x0, y0, x1, y1) in rects:
        for xi in range(x0 // x_pitch, x1 // x_pitch + 2):
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
    union = union_access(rects, cfg)
    if union:
        return union
    return [(xi, yi, via_x, via_y, None)
        for (xi, yi, via_x, via_y) in offtrack_access(rects, cfg)]



def offtrack_access(rects, cfg):
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
    via_half, encl, mgrid = cfg.via_half, cfg.encl, cfg.manufacturing_grid
    encl_endcap = cfg.encl_endcap
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
            # Snap to the in-rect manufacturing-grid x nearest a track (short jog).
            xi = round(((xlo + xhi) / 2) / x_pitch)
            via_x = max(xlo, min(xhi, round(xi * x_pitch / mgrid) * mgrid))
            left, right = via_x - via_half - x0, x1 - (via_x + via_half)
            # The pin's own metal must give the Via1 its endcap (>= encl_endcap on
            # one side), since off-track vias add no Metal1 landing.
            if max(left, right, bottom, top) < encl_endcap:
                continue
            out.append((xi, yi, via_x, track_y))
    return out



def union_access(rects, cfg):
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
    via_half, encl, encl_endcap = cfg.via_half, cfg.encl, cfg.encl_endcap
    half_w, endcap = cfg.strap_half_w, cfg.m1_land_half_h
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
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
    # Vertical moves span the full track range 0..y_track_max INCLUSIVE: the
    # outermost tracks sit on the die-edge rails, and a terminal on such a rail
    # (a tie-off to a rail-only supply pin) must be reachable as a goal.
    if layer == M2:                      # vertical (move in y, rails pass through)
        if yi + 1 <= cfg.y_track_max: yield (xi, yi + 1, M2), 1.0
        if yi - 1 >= 0:               yield (xi, yi - 1, M2), 1.0
        if on_signal:                 yield (xi, yi, M3), via_cost
    elif layer == M3:                    # horizontal (move in x); via down to M2, up to M4
        if xi + 1 <= xmax: yield (xi + 1, yi, M3), 1.0
        if xi - 1 >= 0:    yield (xi - 1, yi, M3), 1.0
        yield (xi, yi, M2), via_cost
        if on_signal and cfg.use_upper: yield (xi, yi, M4), via_cost
    elif layer == M4:                    # vertical (second vertical layer)
        if yi + 1 <= cfg.y_track_max: yield (xi, yi + 1, M4), 1.0
        if yi - 1 >= 0:               yield (xi, yi - 1, M4), 1.0
        if on_signal:
            yield (xi, yi, M3), via_cost
            yield (xi, yi, M5), via_cost
    elif layer == M5:                    # horizontal (second horizontal layer)
        if xi + 1 <= xmax: yield (xi + 1, yi, M5), 1.0
        if xi - 1 >= 0:    yield (xi - 1, yi, M5), 1.0
        yield (xi, yi, M4), via_cost



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

    Nodes in ``blocked`` (reserved for the power mesh) are dropped from every
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



def spacing_neighbors(node):
    """Same-layer grid nodes that would violate metal spacing against ``node`` if
        used by a *different* net.

        Only the same-track, facing-ends case matters. The wire-end overhang
        (``cfg.wire_ext``) puts two facing ends one grid step apart, closer than the
        min metal spacing. Adjacent-track parallels are a full pitch apart and legal,
        and must not be flagged, since doing so rejects legal routing and stalls
        convergence. One step is along x for horizontal layers, along y for vertical.

        Args:
            node: the grid node ``(xi, yi, layer)`` to check around.

        Returns:
            The conflicting same-layer neighbors, possibly empty.
        """
    xi, yi, layer = node
    if layer in HORIZ:
        return ((xi + 1, yi, layer), (xi - 1, yi, layer))
    if layer in VERT:
        return ((xi, yi + 1, layer), (xi, yi - 1, layer))
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

    def __init__(self):
        self.history = {}     # node -> accumulated historical-congestion cost
        self.occupancy = {}   # node -> number of owners currently using it
        self.node_nets = {}   # node -> set(owner)
        self.routes = {}      # net -> {segment key: RouteSeg}
        self.net_use = {}     # owner -> {node: segments of that owner on it}
        self.overused = set()
        self.spacing_bad = set()   # canonical (lower, upper) node pairs

    def update_spacing(self, node):
        here = self.node_nets.get(node)
        for neighbor in spacing_neighbors(node):
            there = self.node_nets.get(neighbor)
            pair = (node, neighbor) if node < neighbor else (neighbor, node)
            if here and there and here != there:
                self.spacing_bad.add(pair)
            else:
                self.spacing_bad.discard(pair)

    def add_nodes(self, owner, nodes):
        use = self.net_use.setdefault(owner, {})
        for node in nodes:
            count = use.get(node, 0)
            use[node] = count + 1
            if count == 0:   # first segment of this owner on the node
                occ = self.occupancy.get(node, 0) + 1
                self.occupancy[node] = occ
                if occ > 1:
                    self.overused.add(node)
                self.node_nets.setdefault(node, set()).add(owner)
                self.update_spacing(node)

    def remove_nodes(self, owner, nodes):
        use = self.net_use[owner]
        for node in nodes:
            count = use[node] - 1
            if count:
                use[node] = count
            else:
                del use[node]
                occ = self.occupancy[node] - 1
                self.occupancy[node] = occ
                if occ <= 1:
                    self.overused.discard(node)
                self.node_nets[node].discard(owner)
                self.update_spacing(node)

    def add_seg(self, net_name, key, seg):
        self.routes[net_name][key] = seg
        self.add_nodes(net_name, seg.nodes)
        if seg.shadows:
            self.add_nodes(('bridge', net_name), seg.shadows)

    def remove_seg(self, net_name, key):
        seg = self.routes[net_name].pop(key)
        self.remove_nodes(net_name, seg.nodes)
        if seg.shadows:
            self.remove_nodes(('bridge', net_name), seg.shadows)

    def conflicts(self):
        """The contested nodes and the real nets to rip up, as a pair."""
        nodes = set(self.overused)
        for pair in self.spacing_bad:
            nodes.update(pair)
        owners = set()
        for node in nodes:
            owners.update(self.node_nets.get(node, ()))
        return nodes, {net for net in owners if net in self.routes}


def route_nets(routed_nets, placed, cfg, xmax, port_nets=(), blocked=frozenset(),
        taps=(), port_edges=None):
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
            placed: ``{name: PlacedInst}`` from :func:`place_rows`, for the pin rects.
            cfg: the routing grid + DRC geometry (:class:`GridConfig`).
            xmax: the maximum x track index, the right die edge.
            port_nets: the nets needing a top-edge Metal4 escape.
            blocked: nodes reserved for the power mesh
                (:func:`mesh_blocked_nodes`). No route, terminal access or escape
                column may use them.
            taps: the tap columns behind ``blocked`` (:func:`mesh_tap_columns`),
                whose rail landings stay clear of off-track access bridges.

        Returns:
            The :class:`RoutingResult` for the whole block.

        Raises:
            PinAccessError: a terminal is unreachable on the grid. This is
                permanent, so the caller re-raises instead of retrying.
            RuntimeError: the rip-up loop did not converge, after which the caller
                grows the floorplan and retries.
        """
    # term_access[net] holds each terminal's candidate (xi, yi, M2) access
    # nodes. term_via and term_land hold the off-track Via1 positions and the
    # pin-aware Metal1 landings. Both key on (net, terminal, node): different
    # pins may share a candidate node, so a node-only key could attribute one
    # pin's via geometry to another.
    term_access = {}
    term_via = {}
    term_land = {}
    sole = {}   # node -> (net, inst, pin) for terminals with a single candidate
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch

    # An off-track terminal's Metal2 bridge is an off-grid rect the node-based
    # conflict model cannot see, and the power-mesh tap landings are off-grid
    # too.
    # Reject any off-track candidate whose bridge would come within the metal
    # spacing of a tap landing (rects mutually expanded, so conservative).
    spacing = cfg.y_pitch - cfg.wire_width
    tap_landings = [(tap_xi * x_pitch, rail_row * cfg.row_height)
        for tap_xi in taps
        for rail_row in range(cfg.n_rows + 1)]

    def bridge_clear(xi, via_x, via_y):
        x_lo = min(via_x, xi * x_pitch) - cfg.strap_half_w - spacing
        x_hi = max(via_x, xi * x_pitch) + cfg.strap_half_w + spacing
        y_lo = via_y - cfg.land_half_h - spacing
        y_hi = via_y + cfg.land_half_h + spacing
        for tap_x, tap_y in tap_landings:
            if (x_lo < tap_x + cfg.strap_half_w and x_hi > tap_x - cfg.strap_half_w
                    and y_lo < tap_y + cfg.land_half_h
                    and y_hi > tap_y - cfg.land_half_h):
                return False
        return True

    for net_name, net in routed_nets.items():
        # A power *pin* (vdd/vss) is reached on its wide rail track. Key off
        # the pin name so a tie-off net's rail terminal also uses rail access.
        cands = []
        for ti, (iname, pname) in enumerate(net.terminals):
            term = []
            for (xi, yi, via_x, via_y, land) in access_nodes(
                    placed[iname].pins[pname], cfg,
                    pname in cfg.supply_pin_names):
                node = (xi, yi, M2)
                if node in blocked:   # reserved for the power mesh
                    continue
                off_track = (via_x, via_y) != (xi * x_pitch, yi * y_pitch)
                if off_track and not bridge_clear(xi, via_x, via_y):
                    continue
                term.append(node)
                if off_track:
                    term_via[(net_name, ti, node)] = (via_x, via_y)
                elif land is not None:
                    term_land[(net_name, ti, node)] = land
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
                        "grid access node; both nets cannot be routed")
                sole[term[0]] = (net_name, iname, pname)
            cands.append(term)
        term_access[net_name] = cands

    # Global routing assigns each net a corridor of gcells. Detailed routing
    # stays inside the corridor (cheap, congestion-balanced), falling back to the
    # whole grid only if a net can't be realized there.
    corridors = global_route(routed_nets, term_access, cfg, xmax)

    # Every port net gets a unique escape column on its edge, near the mean x
    # of its pin candidates. Uniqueness removes pad contention by construction
    # and keeps each escape a directed single-goal search. A shared full-width
    # goal row converges too but pays a fan-out search per escape, and per-net
    # goal windows do not converge at all. The two edges allocate
    # independently, since a top and a bottom pad in one column never meet.
    # Columns whose edge-row Metal4 node is blocked by a mesh tap cannot host
    # a pad.
    def mean_x(port_name):
        xs = [n[0] for term in term_access[port_name] for n in term]
        return sum(xs) / len(xs)

    def chosen_edge(port_name):
        if port_edges and port_name in port_edges:
            return port_edges[port_name]
        # Escape to whichever edge the net's terminals sit nearer, so a port
        # driven from the bottom row does not climb the whole block to leave
        # it and come straight back down at the parent.
        ys = [n[1] for term in term_access[port_name] for n in term]
        mean_y = sum(ys) / len(ys)
        return 'top' if 2 * mean_y >= cfg.y_track_max else 'bottom'

    escape_col = {}   # port net -> (x track, edge)
    by_edge = {}
    for port_name in sorted(port_nets):
        by_edge.setdefault(chosen_edge(port_name), []).append(port_name)
    for edge, names in by_edge.items():
        yrow = escape_row(cfg, edge)
        usable = [x for x in range(xmax + 1) if (x, yrow, M4) not in blocked]
        if len(names) > len(usable):
            raise PinAccessError(f"{len(names)} {edge}-edge port escapes need "
                f"more columns than the die has free ({len(usable)})")
        prefs = sorted((mean_x(name), name) for name in names)
        prev = -1
        for k, (pref, port_name) in enumerate(prefs):
            hi = len(usable) - (len(prefs) - k)   # room for the ports right of us
            prev = min(max(prev + 1, bisect.bisect_left(usable, round(pref))), hi)
            escape_col[port_name] = (usable[prev], edge)

    cong = Congestion()
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

    def jog_reserved(net_name, ti, node):
        # An off-track terminal's Metal2 bridge (emit_net_direct) reaches from
        # the on-pin via to its track, ending closer to the neighboring track
        # than the metal spacing allows. Reserving that neighbor node for the
        # net keeps every other net (and this net's own min-area growth) off
        # the bridge's shadow.
        via = term_via.get((net_name, ti, node))
        if via is None:
            return ()
        xi, yi, _layer = node
        track_x = xi * x_pitch
        if via[0] > track_x and xi + 1 <= xmax:
            return ((xi + 1, yi, M2),)
        if via[0] < track_x and xi - 1 >= 0:
            return ((xi - 1, yi, M2),)
        return ()

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
            for neighbor in spacing_neighbors(node):
                there = node_nets.get(neighbor)
                if there and there - own:
                    return False
            return True

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
                if cfg.is_signal_track(y2):
                    cands.append(m2_run(x1, y1, y2)
                        + m3_run(y2, x1, x2) + [(x2, y2, M2)])
                if cfg.is_signal_track(y1):
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
                if not cfg.is_signal_track(y_bend):
                    continue
                path = (m2_run(x1, y1, y_bend) + m3_run(y_bend, x1, x2)
                    + m2_run(x2, y_bend, y2))
                if all(map(free, path)):
                    return path
            # Horizontal-vertical-horizontal Z, which costs two more vias.
            # Sample the bend columns so a die-wide net stays a bounded check.
            if cfg.is_signal_track(y1) and cfg.is_signal_track(y2):
                x_lo, x_hi = sorted((x1, x2))
                for x_bend in range(x_lo + 1, x_hi, max((x_hi - x_lo) // 16, 1)):
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
            # Port escape: lift the net to its reserved Metal4 column on its
            # edge, so its pin sits in the channel outside the rows. The parent
            # then connects there, never over the interior. That edge interface
            # is what keeps the block composable (a placement change can't drop
            # a parent wire onto an internal net). vdd/vss go to the side
            # straps.
            tree = set(own_use)
            col, edge = escape_col[net_name]
            yrow = escape_row(cfg, edge)
            path = astar(tree, [(col, yrow, M4)],
                cfg, xmax, history, occupancy, own_use, penalty[0], None, adj)
            if path is None:   # blocked column: any node on that row will do
                path = astar(tree, [(x, yrow, M4) for x in range(xmax + 1)],
                    cfg, xmax, history, occupancy, own_use, penalty[0], None, adj)
            if path is None:   # last resort: interior pad on the first terminal
                _ti, node = next(p for seg in routes[net_name].values()
                    for p in seg.pairs)
                xi, yi, _layer = node
                stack = ((xi, yi, M2), (xi, yi, M3), (xi, yi, M4))
                port_escape[net_name] = None
                return RouteSeg(tuple(zip(stack, stack[1:])), frozenset(stack), ())
            port_escape[net_name] = (path[-1][0], edge)
            return RouteSeg(tuple(zip(path, path[1:])), frozenset(path), ())

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

        def grow(coords, make_node, lo_b, hi_b):
            run = sorted(coords)
            while run[-1] - run[0] < cfg.min_area_tracks:
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
            grow(y_tracks, lambda p, X=xi, L=layer: (X, p, L), 1, cfg.y_track_max - 1)
        for (layer, yi), x_tracks in horiz_runs.items():
            grow(x_tracks, lambda p, Y=yi, L=layer: (p, Y, L), 0, xmax)
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
            else:
                land = term_land.get((net_name, ti, node))
                if land is not None:
                    tl[node] = land
    return RoutingResult(nets=routing, port_escape=port_escape,
        term_via=net_via, term_land=net_land, reserved=frozenset(reserved))



def tap_avoid_columns(routed_nets, placed, cfg):
    """Find the track columns where a power-mesh tap could strand a pin access.

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
            placed: ``{name: PlacedInst}`` from :func:`place_rows`, for the pin rects.
            cfg: the routing grid + geometry (:class:`GridConfig`).

        Returns:
            The tap-hostile column indices as a set.
        """
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    mat, half_w, land_half = cfg.min_area_tracks, cfg.strap_half_w, cfg.land_half_h
    spacing = y_pitch - cfg.wire_width
    rail_zones = [(r * cfg.tracks_per_row - 1, r * cfg.tracks_per_row + 1)
        for r in range(1, cfg.n_rows)]

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
                abs(via_y - r * cfg.row_height) < 2 * land_half + spacing
                for r in range(cfg.n_rows + 1))
            if near_rail:
                for xc in range(max(x_lo // x_pitch, 0), x_hi // x_pitch + 2):
                    if x_lo < xc * x_pitch + half_w and x_hi > xc * x_pitch - half_w:
                        cols.add(xc)
        return cols

    avoid = set()
    for net in routed_nets.values():
        for iname, pname in net.terminals:
            fatal = None   # columns that invalidate EVERY candidate so far
            for (xi, yi, via_x, via_y, _land) in access_nodes(
                    placed[iname].pins[pname], cfg,
                    pname in cfg.supply_pin_names):
                cols = killer_columns(xi, yi, via_x, via_y)
                fatal = cols if fatal is None else fatal & cols
                if not fatal:
                    break
            if fatal:
                avoid |= fatal
    return avoid



def mesh_tap_columns(cfg, xmax, avoid=frozenset()):
    """Track columns where the power mesh stitches down to the rails.

        Nominally every ``cfg.mesh_tap_pitch`` tracks. A nominal column in ``avoid``
        is nudged to the nearest free one, so no tap blocks a pin access that cannot
        negotiate away. The die-edge columns are excluded, since the mesh ends
        stitch into the side straps right there and an edge landing would sit closer
        to the ring-end via stack than the metal spacing allows. A tap with no free
        column in reach is dropped, since the strap still stitches at every other
        tap while a hostile column can deadlock the router.

        Args:
            cfg: the routing grid (:class:`GridConfig`).
            xmax: the maximum x track index.
            avoid: columns no tap may use (:func:`tap_avoid_columns`).

        Returns:
            The tap column indices, in increasing order.
        """
    reach = cfg.mesh_tap_pitch // 2   # stay closer to this tap than its neighbors
    taps = []
    for nominal in range(reach, xmax, cfg.mesh_tap_pitch):
        prev = taps[-1] if taps else 0
        for delta in sorted(range(1 - reach, reach), key=abs):
            xc = nominal + delta
            if prev < xc < xmax and xc not in avoid:
                taps.append(xc)
                break
    return taps



def mesh_blocked_nodes(cfg, xmax, taps):
    """Grid nodes the power mesh (:func:`emit_power_mesh`) makes unusable.

        Only the *interior* rails carry straps, so only their surroundings are
        reserved, in two kinds:

        * At each tap column, the via stack down to the rail occupies the vertical
          layers where they cross the rail track. Its min-area landings reach one
          track beyond the rail on either side, so those neighbors are unusable too,
          since a wire end there would violate metal spacing.
        * The strap is wider than a routing wire, so the horizontal top-metal tracks
          adjacent to a strapped rail sit closer to it than the metal spacing allows
          and are blocked across the whole die width.

        Metal3 and Metal5 *on* a rail track need no entry here, since a layer change
        is never allowed on rail tracks and the router cannot reach them.

        Args:
            cfg: the routing grid (:class:`GridConfig`).
            xmax: the maximum x track index.
            taps: the tap column indices (:func:`mesh_tap_columns`).

        Returns:
            The blocked nodes as a frozenset.
        """
    blocked = set()
    for rail_row in range(1, cfg.n_rows):
        rail_yi = rail_row * cfg.tracks_per_row
        for xi in taps:
            for yi in (rail_yi - 1, rail_yi, rail_yi + 1):
                blocked.add((xi, yi, M2))
                blocked.add((xi, yi, M4))
        for yi in (rail_yi - 1, rail_yi + 1):
            for xi in range(xmax + 1):
                blocked.add((xi, yi, M5))
    return frozenset(blocked)



def extend_min_area(result, cfg, xmax, keepout=frozenset()):
    """Post-pass: lengthen any too-short wire so it meets the metal min-area rule.

        A min-width wire must span enough tracks to meet min area and give its
        end-via the required endcap, so each per-net, per-track run grows into free
        tracks until it spans ``cfg.min_area_tracks`` steps.

        Args:
            result: the routing ``{net: (edges, term_m2)}`` to extend in place.
            cfg: the routing grid + geometry (:class:`GridConfig`).
            xmax: the maximum x track index.
            keepout: nodes no extension may grow into, the power-mesh blockages and
                the off-track access-bridge shadows.

        Returns:
            The same ``result`` mapping, mutated in place.
        """
    node_net = {}   # (xi, yi, layer) -> net_name
    for net_name, (edges, _term_m2) in result.items():
        for a, b in edges:
            node_net[a] = net_name; node_net[b] = net_name

    def free(node, net_name):
        if node in keepout:
            return False
        owner = node_net.get(node)
        if owner is not None and owner != net_name:
            return False
        # Don't grow into a same-layer spacing conflict with another net.
        for adj in spacing_neighbors(node):
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

        def grow(fixed, coords, lo, hi, make_node):
            """Extend a 1-D run of ``coords`` to span ``cfg.min_area_tracks`` steps."""
            run = sorted(coords)
            need = cfg.min_area_tracks - (run[-1] - run[0])
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
                lambda xi, yi, L=layer: (xi, yi, L))
        for (layer, yi), x_tracks in horiz.items():
            grow(yi, x_tracks, 0, xmax,
                lambda yi, xi, L=layer: (xi, yi, L))
    return result
