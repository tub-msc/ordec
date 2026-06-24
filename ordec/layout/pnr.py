# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
A gridded standard-cell place-and-route engine.

It follows the structure of a modern detailed flow: row-based placement of
standard cells, then **negotiated-congestion maze routing** on a per-layer track
grid -- place cells in rows, then rip-up-and-reroute nets with A* until the
routing is congestion-free.

Assumptions / scope (matched to the IHP sg13g2 standard cells used here):

* Leaf cells are Metal1-only for signals (foundry GDS cells), so Metal2/Metal3
  over the cells is free for routing -- routing stays *within* the cell-row
  height instead of being pushed above it.
* Routing grid follows the PDK tech LEF: Metal2 vertical (pitch 0.48 um), Metal3
  horizontal (pitch 0.42 um), Metal1 for pin access. Cells are an integer number
  of vertical tracks wide and 9 horizontal tracks (3.78 um) tall.
* Power (vdd/vss) connects by rail abutment, like a real standard-cell row.

The geometry (wires, via stacks) is emitted directly as concrete grid
coordinates (``_emit_net_direct``): routing everything through ORDeC's general
constraint solver does not scale to hundreds of nets, so this module decides the
paths *and* lays down the metal itself.
"""

from collections import namedtuple
from dataclasses import dataclass, field
import heapq
import math
import random

from ordec.core import *
from ordec.core.schema import SchemInstanceConn


# --- routing grid configuration -------------------------------------------

@dataclass
class GridConfig:
    """Routing-grid parameters (defaults: IHP sg13g2 from the tech LEF)."""
    x_pitch: int = 480       # Metal2 vertical track pitch (nm)
    y_pitch: int = 420       # Metal3 horizontal track pitch (nm)
    row_height: int = 3780   # standard-cell row height (= 9 * y_pitch)
    tracks_per_row: int = 9  # y-tracks per row (row_height / y_pitch)
    n_rows: int = 1          # number of abutted (flipped) standard-cell rows
    via_cost: float = 4.0    # A* cost of a layer change (in track units)
    via_half: int = 95       # half the Via1/Via2 cut size (V1_a/2 = 0.19/2)
    encl: int = 10           # min metal enclosure of via on every side (V1.c)
    encl_endcap: int = 50    # min metal enclosure on >=1 side (V1.c1)
    min_area_pass: bool = True
    use_upper: bool = True   # allow routing on Metal4/Metal5 (else Metal2/3 only)
    # Floorplan controls: size a die from cell_area / utilization, shaped to the
    # target aspect, then legalize cells into it and pad every row's rail flush to
    # the die width.
    # Utilization is the AREA lever -- keep it high. This router runs *over* the
    # cells (M2-M5 above M1), so dense packing does not cause the planar
    # congestion a tracks-shared flow would; the routing budget is tracks/row *
    # rows, ~independent of cell density. Aspect is only a soft preference for
    # the row count (a sensible, non-degenerate shape), not enforced by padding.
    target_util: float = 0.9    # cell area / core area (area-efficiency lever)
    target_aspect: float = 1.0  # core height / width, soft row-count preference

    @property
    def y_track_max(self):
        return self.n_rows * self.tracks_per_row

    def is_signal_track(self, yi):
        # Tracks on a row boundary (multiples of 9) sit on a vdd/vss rail.
        return 0 < yi < self.y_track_max and yi % self.tracks_per_row != 0


# --- netlist + placement extraction ---------------------------------------

@dataclass
class PlacedInst:
    """One leaf cell placed in a row: its absolute position, orientation, and
    pin rectangles in die coordinates."""
    name: str
    cell: object          # the leaf Cell instance
    x: int                # placement x offset (nm)
    width: int            # cell width (nm)
    pos: tuple = (0, 0)   # LayoutInstance position
    orient: object = None # LayoutInstance orientation (D4.R0 or D4.MX)
    row: int = 0          # row index
    pins: dict = field(default_factory=dict)  # pin name -> [abs rects]


@dataclass
class NetInfo:
    """A net to route: its terminals (instance pin connections) and, if it is a
    top-level port, the symbol Pin it exposes."""
    name: str
    terminals: list = field(default_factory=list)  # (inst_name, pin_name)
    port_pin: object = None   # cell symbol Pin if this net is a top-level port


# One leaf cell before placement: the Cell, its Metal1 pin rects, and its width.
LeafCell = namedtuple('LeafCell', 'cell pins width')


def _conns_of(sch, inst):
    """{pin_name: net_name} for one instance in a schematic."""
    out = {}
    for conn in sch.all(SchemInstanceConn):
        if conn.ref.nid == inst.nid:
            out[conn.there.full_path_str().split('.')[-1]] = \
                conn.here.full_path_str().split('.')[-1]
    return out


def _flatten(cell, is_leaf):
    """
    Flatten a (possibly hierarchical) schematic down to Metal1-only foundry leaf
    instances, the way a standard-cell flow flattens a netlist before detailed
    routing. Sub-cells for which ``is_leaf`` is true are leaves; any other instance
    is expanded into its own schematic, with internal nets uniquified by an
    instance prefix and port nets mapped to the parent's nets.

    Returns ``(leaf_insts, net_terminals)`` where ``leaf_insts`` maps a flat
    instance name to its leaf Cell, and ``net_terminals`` maps a net name to a
    list of ``(flat_inst_name, pin_name)``.
    """
    leaf_insts = {}
    net_terminals = {}

    def recurse(sch, prefix, port_to_net):
        def canon(net_name):
            if net_name in port_to_net:
                return port_to_net[net_name]
            return prefix + net_name if prefix else net_name
        for inst in sch.all(SchemInstance):
            iname = prefix + inst.full_path_str().split('.')[-1]
            sub = inst.symbol.cell
            pinconn = {p: canon(n) for p, n in _conns_of(sch, inst).items()}
            if is_leaf(sub):
                leaf_insts[iname] = sub
                for pin, net in pinconn.items():
                    net_terminals.setdefault(net, []).append((iname, pin))
            else:
                recurse(sub.schematic, iname + '/', pinconn)

    recurse(cell.schematic, '', {})
    return leaf_insts, net_terminals


def extract(cell, pin_rects, is_leaf):
    """Return ``(cells, nets)`` for a cell's flattened schematic: cells maps each
    leaf instance name to a LeafCell, nets maps each net name to a NetInfo.
    ``pin_rects`` and ``is_leaf`` are the PDK hooks documented on
    :func:`place_and_route`."""
    leaf_insts, net_terminals = _flatten(cell, is_leaf)

    cells = {}
    for name, leaf in leaf_insts.items():
        rects = pin_rects(leaf.name)
        # Cell pitch = power-rail width (the rail rect spans the whole cell).
        width = max(r[2] - r[0] for r in rects['VDD'])
        cells[name] = LeafCell(leaf, rects, width)

    nets = {nname: NetInfo(nname, list(terms))
        for nname, terms in net_terminals.items()}

    # Mark top-level port nets (Net.pin references a symbol Pin).
    for net in cell.schematic.all(Net):
        if net.pin is not None:
            nname = net.full_path_str().split('.')[-1]
            if nname in nets:
                nets[nname].port_pin = net.pin

    return cells, nets


def order_cells(cells, nets, iters=30):
    """
    Order the cells in the row to keep nets short (low wirelength), which is what
    makes a single-row channel routable. Iterated barycenter placement: repeatedly
    move each cell toward the average position of the cells it shares a net with,
    then re-rank. Power nets (which touch every cell) are ignored.
    """
    order = sorted(cells)
    sig_nets = [n for n in nets.values()
        if n.name not in ('vdd', 'vss') and len(n.terminals) >= 2]
    for _ in range(iters):
        pos = {name: i for i, name in enumerate(order)}
        barycenter = {}
        for name in order:
            acc, cnt = 0.0, 0
            for net in sig_nets:
                net_insts = [t[0] for t in net.terminals]
                if name in net_insts:
                    for other in net_insts:
                        if other != name:
                            acc += pos[other]; cnt += 1
            barycenter[name] = acc / cnt if cnt else pos[name]
        order = sorted(order, key=lambda n: (barycenter[n], n))
    return order


def _cell_xy(cells, order, cfg):
    """Fast cell-center (x, y) lookup for a folded order -- used to score
    placements without building geometry."""
    rh = cfg.row_height
    row_target = sum(cells[n].width for n in order) / cfg.n_rows
    center = {}
    row, row_w, x = 0, 0, 0
    for name in order:
        w = cells[name].width
        if row < cfg.n_rows - 1 and row_w + w > row_target and row_w > 0:
            row += 1; row_w = 0; x = 0
        center[name] = (x + w // 2, row * rh + rh // 2)
        x += w; row_w += w
    return center


def order_cells_sa(cells, nets, cfg, iters=6000, seed=1):
    """
    Wirelength-driven placement by simulated annealing (the classic standard-cell
    placement method). Starts from the barycenter order and perturbs the cell
    sequence to minimize half-perimeter wirelength, weighting vertical span more
    (a net that stays within one row routes far more easily than one that crosses
    rows). Deterministic via a fixed seed.
    """
    sig_insts = [[t[0] for t in n.terminals] for n in nets.values()
        if n.name not in ('vdd', 'vss') and len(n.terminals) >= 2]
    if cfg.n_rows == 1 or not sig_insts:
        return order_cells(cells, nets)

    def hpwl(order):
        center = _cell_xy(cells, order, cfg)
        total = 0
        for insts in sig_insts:
            xs = [center[i][0] for i in insts]; ys = [center[i][1] for i in insts]
            total += (max(xs) - min(xs)) + 2 * (max(ys) - min(ys))
        return total

    rng = random.Random(seed)
    order = order_cells(cells, nets)
    cur_cost = hpwl(order)
    best_order, best_cost = order[:], cur_cost
    temp = max(cur_cost / max(len(order), 1), 1.0)
    for _ in range(iters):
        a, b = rng.randrange(len(order)), rng.randrange(len(order))
        if a == b:
            continue
        order[a], order[b] = order[b], order[a]
        new_cost = hpwl(order)
        if new_cost <= cur_cost or rng.random() < math.exp(-(new_cost - cur_cost) / temp):
            cur_cost = new_cost
            if new_cost < best_cost:
                best_cost, best_order = new_cost, order[:]
        else:
            order[a], order[b] = order[b], order[a]
        temp *= 0.9995
    return best_order


def _partition_width(widths, nrows):
    """
    Minimum achievable maximum row width when a cell *sequence* is split into at
    most ``nrows`` contiguous rows -- the classic "split array largest sum",
    solved by binary search on the width. This keeps the rows balanced so no
    single row blows up the die width (a fixed per-row target instead
    systematically under-fills and dumps the leftover into the last row).
    """
    if not widths:
        return 0
    lo, hi = max(widths), sum(widths)
    while lo < hi:
        mid = (lo + hi) // 2
        cnt, acc = 1, 0
        for w in widths:
            if acc + w > mid:
                cnt += 1; acc = 0
            acc += w
        if cnt <= nrows:
            hi = mid
        else:
            lo = mid + 1
    return lo


def place_rows(cells, order, cfg):
    """
    Fold the 1-D cell order into ``cfg.n_rows`` abutted standard-cell rows. Odd
    rows are mirrored (D4.MX) and their cell order reversed (a boustrophedon /
    snake), so power rails abut between rows and the dataflow stays adjacent
    across the turn -- exactly how standard-cell rows are built.
    """
    rh = cfg.row_height
    nrows = cfg.n_rows

    # Balanced fold: pack greedily to the minimum max-row-width (the optimal
    # contiguous partition), so the rows come out even.
    max_row_w = _partition_width([cells[n].width for n in order], nrows)
    rows = [[]]
    row_w = 0
    for name in order:
        w = cells[name].width
        if rows[-1] and row_w + w > max_row_w and len(rows) < nrows:
            rows.append([]); row_w = 0
        rows[-1].append(name); row_w += w
    while len(rows) < nrows:
        rows.append([])

    placed = {}
    max_w = 0
    for row, row_cells in enumerate(rows):
        mirror = (row % 2 == 1)
        if mirror:
            row_cells = row_cells[::-1]
        row_y = (row + 1) * rh if mirror else row * rh
        orient = D4.MX if mirror else D4.R0
        x = 0
        for name in row_cells:
            leaf, local_pins, width = cells[name]
            if mirror:   # MX: shift by x, flip y about row_y
                abs_pins = {pin: [(x0 + x, row_y - y1, x1 + x, row_y - y0)
                    for (x0, y0, x1, y1) in rects] for pin, rects in local_pins.items()}
            else:
                abs_pins = {pin: [(x0 + x, y0 + row_y, x1 + x, y1 + row_y)
                    for (x0, y0, x1, y1) in rects] for pin, rects in local_pins.items()}
            placed[name] = PlacedInst(name, leaf, x, width, (x, row_y), orient, row, abs_pins)
            x += width
        max_w = max(max_w, x)
    return placed, max_w


# --- routing grid + maze router -------------------------------------------

# Internal layer codes. Routing uses two vertical layers (Metal2, Metal4) and two
# horizontal layers (Metal3, Metal5); Metal1 is pin access only. Doubling the
# layers ~doubles routing capacity, which is what production routers do.
M2, M3, M1, M4, M5 = 0, 1, 2, 3, 4
VERT = (M2, M4)        # vertical routing layers (move in y)
HORIZ = (M3, M5)       # horizontal routing layers (move in x)

# Emitted geometry (nm), sized to the track grid and the IHP sg13g2 DRC rules
# (the relevant rule is noted per constant): wires keep their adjacent-track
# spacing while enclosing the via cut and giving it an endcap.
WIRE_WIDTH = 210       # Mn routing-wire width (= Mn min width)
WIRE_EXT = 150         # wire overhang past its last via (cut half 95 + 55 endcap): Mn.c1 / V*.c1
VIA_CUT = 190          # Via1..Via4 cut size (V1.a)
VIA_CUT_HALF = 95      # VIA_CUT / 2 (== GridConfig.via_half)
STRAP_HALF_W = 105     # half a wire / strap / via-landing width (= WIRE_WIDTH / 2)
LAND_HALF_H = 345      # half the long side of a min-area via landing (690 nm -> Mn min area)
M1_LAND_HALF_H = 145   # half-height of the Metal1 endcap landing under a Via1 (V1.c1 on short pins)
PORT_PAD_BELOW = 600   # Metal4 port-pad extent below the top rail
PORT_PAD_ABOVE = 360   # Metal4 port-pad extent above the top rail
# Power-ring straps, in the empty margins beside the rows:
STRAP_VDD_X = -520     # VDD strap x (left margin); the right strap mirrors to die_w+520
STRAP_VSS_X = -1080    # VSS strap x (just outside VDD)
RAIL_EXT = 150         # Metal1 overlap of a strap onto the rail it taps


def access_nodes(rects, cfg, allow_rail=False):
    """Candidate M2-grid access nodes (xi, yi) for a pin (list of Metal1 rects).

    A pin is reached by a Via1 at a vertical (Metal2) track inside its Metal1
    x-extent and a horizontal (Metal3) track inside its y-extent. Using the clean
    LEF rectangles (not a poly bbox) guarantees the access lands on this pin only.
    Signal pins use signal tracks only; power pins (allow_rail=True) may be reached
    on the rail track itself, where the wide rail easily encloses the via.
    """
    via_half, encl, encl_endcap = cfg.via_half, cfg.encl, cfg.encl_endcap
    pair, single = set(), set()   # access nodes with endcap on a pair / single side
    for (x0, y0, x1, y1) in rects:
        for xi in range(x0 // cfg.x_pitch, x1 // cfg.x_pitch + 2):
            xc = xi * cfg.x_pitch
            left, right = xc - via_half - x0, x1 - (xc + via_half)   # x via enclosures
            if left < encl or right < encl:
                continue
            ylo, yhi = (0, cfg.y_track_max) if allow_rail else (1, cfg.y_track_max - 1)
            for yi in range(ylo, yhi + 1):
                if not allow_rail and not cfg.is_signal_track(yi):
                    continue
                yc = yi * cfg.y_pitch
                bottom, top = yc - via_half - y0, y1 - (yc + via_half)   # y via enclosures
                if bottom < encl or top < encl:
                    continue
                # Via1 wants its endcap on a *pair* of opposite sides (V1.c1): tall
                # signal pins give it top/bottom, wide rails left/right. Prefer
                # those; fall back to a single endcap side for small pins so they
                # stay routable.
                if (bottom >= encl_endcap and top >= encl_endcap) or \
                        (left >= encl_endcap and right >= encl_endcap):
                    pair.add((xi, yi))
                elif max(left, right, bottom, top) >= encl_endcap:
                    single.add((xi, yi))
    return list(pair) if pair else list(single)


def _neighbors(node, cfg, xmax):
    """Yield ``(neighbor_node, move_cost)`` for a maze-router node. Vertical
    layers (M2, M4) step in y, horizontal layers (M3, M5) step in x; a layer
    change costs ``cfg.via_cost`` and is only allowed off the rail tracks."""
    xi, yi, lyr = node
    on_signal = cfg.is_signal_track(yi)
    via_cost = cfg.via_cost
    if lyr == M2:                      # vertical (move in y, rails pass through)
        if yi + 1 < cfg.y_track_max: yield (xi, yi + 1, M2), 1.0
        if yi - 1 > 0:               yield (xi, yi - 1, M2), 1.0
        if on_signal:                yield (xi, yi, M3), via_cost
    elif lyr == M3:                    # horizontal (move in x); via down to M2, up to M4
        if xi + 1 <= xmax: yield (xi + 1, yi, M3), 1.0
        if xi - 1 >= 0:    yield (xi - 1, yi, M3), 1.0
        yield (xi, yi, M2), via_cost
        if on_signal and cfg.use_upper: yield (xi, yi, M4), via_cost
    elif lyr == M4:                    # vertical (second vertical layer)
        if yi + 1 < cfg.y_track_max: yield (xi, yi + 1, M4), 1.0
        if yi - 1 > 0:               yield (xi, yi - 1, M4), 1.0
        if on_signal: yield (xi, yi, M3), via_cost
        if on_signal: yield (xi, yi, M5), via_cost
    elif lyr == M5:                    # horizontal (second horizontal layer)
        if xi + 1 <= xmax: yield (xi + 1, yi, M5), 1.0
        if xi - 1 >= 0:    yield (xi - 1, yi, M5), 1.0
        yield (xi, yi, M4), via_cost


def _astar(starts, goals, cfg, xmax, node_cost, allowed=None):
    """A* from any start (set) to any goal (set). node_cost(node)->float adds
    congestion. ``allowed(node)->bool`` restricts the search region (the net's
    global-routing corridor), keeping the maze search local on large layouts.
    Returns the path (list of nodes) or None."""
    goal_set = set(goals)
    goal_xs = [n[0] for n in goals]; goal_ys = [n[1] for n in goals]

    def heuristic(n):
        return (min(abs(n[0] - gx) for gx in goal_xs)
                + min(abs(n[1] - gy) for gy in goal_ys))

    frontier = []
    cost = {}            # node -> cheapest known cost to reach it
    came_from = {}
    for start in starts:
        cost[start] = node_cost(start)
        heapq.heappush(frontier, (cost[start] + heuristic(start), start))
    while frontier:
        _, cur = heapq.heappop(frontier)
        if cur in goal_set:
            path = [cur]
            while cur in came_from:
                cur = came_from[cur]; path.append(cur)
            return path[::-1]
        for nbr, step in _neighbors(cur, cfg, xmax):
            if allowed is not None and not allowed(nbr):
                continue
            new_cost = cost[cur] + step + node_cost(nbr)
            if nbr not in cost or new_cost < cost[nbr]:
                cost[nbr] = new_cost; came_from[nbr] = cur
                heapq.heappush(frontier, (new_cost + heuristic(nbr), nbr))
    return None


def _gcell_astar(starts, goal, gxmax, gymax, gcost):
    """A* on the coarse gcell grid (2-D, 4-connected), used by the global router.
    Returns the list of gcells on the cheapest path from any start to `goal`."""
    frontier = []
    cost = {}
    came_from = {}
    for start in starts:
        cost[start] = 0.0
        heapq.heappush(frontier, (abs(start[0] - goal[0]) + abs(start[1] - goal[1]), start))
    while frontier:
        _, cur = heapq.heappop(frontier)
        if cur == goal:
            path = [cur]
            while cur in came_from:
                cur = came_from[cur]; path.append(cur)
            return path
        cx, cy = cur
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if not (0 <= nx <= gxmax and 0 <= ny <= gymax):
                continue
            new_cost = cost[cur] + gcost((nx, ny))
            if (nx, ny) not in cost or new_cost < cost[(nx, ny)]:
                cost[(nx, ny)] = new_cost; came_from[(nx, ny)] = cur
                heapq.heappush(frontier, (new_cost + abs(nx - goal[0]) + abs(ny - goal[1]), (nx, ny)))
    return [goal]


def global_route(routed_nets, term_access, cfg, xmax, gw=5, gh=5):
    """
    Coarse global routing. The track grid is tiled into
    gcells; each net's terminals are connected by a cheap tree on the gcell grid
    with negotiated congestion on per-gcell demand, so nets spread off hotspots.
    Returns ``(corridors, gw, gh)`` where corridors[net] is the set of gcells the
    detailed router is then allowed to use for that net (plus a one-gcell halo).
    """
    def gcell_of(node):
        return (node[0] // gw, node[1] // gh)

    gxmax = xmax // gw + 1
    gymax = cfg.y_track_max // gh + 1
    net_gcells = {nn: list({gcell_of(n) for term in term_access[nn] for n in term})
        for nn in routed_nets}
    gcell_cap = gw + gh
    history = {}
    penalty = [0.5]
    demand = {}
    corridors = {}

    def gcell_cost(gc):
        return 1.0 + history.get(gc, 0.0) + penalty[0] * max(0, demand.get(gc, 0))

    def route(nn):
        gcells = net_gcells[nn]
        tree = {gcells[0]}
        for gc in gcells[1:]:
            if gc not in tree:
                tree.update(_gcell_astar(tree, gc, gxmax, gymax, gcell_cost))
        return tree

    for nn in routed_nets:
        corridors[nn] = route(nn)
        for gc in corridors[nn]:
            demand[gc] = demand.get(gc, 0) + 1

    for _ in range(400):
        congested = {gc for gc, d in demand.items() if d > gcell_cap}
        if not congested:
            break
        for gc in congested:
            history[gc] = history.get(gc, 0.0) + 1.0
        penalty[0] = min(penalty[0] * 1.3, 40.0)
        for nn in list(routed_nets):
            if not (corridors[nn] & congested):
                continue
            for gc in corridors[nn]:
                demand[gc] -= 1
            corridors[nn] = route(nn)
            for gc in corridors[nn]:
                demand[gc] = demand.get(gc, 0) + 1

    # Widen each corridor by a one-gcell halo so detailed routing has room.
    for nn in corridors:
        halo = set()
        for (gx, gy) in corridors[nn]:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    halo.add((gx + dx, gy + dy))
        corridors[nn] = halo
    return corridors, gw, gh


def _conflict_neighbors(node):
    """Same-layer grid nodes that would violate spacing against `node` if used by
    a *different* net. Only the same-track, facing-ends case matters: WIRE_EXT
    overhang puts two wire ends one step apart at ~180 nm (< 210 nm spacing).
    Adjacent-track parallels are a full pitch apart (legal) and must NOT be flagged
    -- doing so rejects legal routing and stalls convergence. 'One step' is along x
    for horizontal layers, along y for vertical."""
    xi, yi, lyr = node
    if lyr in HORIZ:
        return ((xi + 1, yi, lyr), (xi - 1, yi, lyr))
    if lyr in VERT:
        return ((xi, yi + 1, lyr), (xi, yi - 1, lyr))
    return ()


def route_nets(routed_nets, placed, cfg, xmax, port_nets=()):
    """
    Route the signal nets with negotiated-congestion maze routing,
    using *incremental* rip-up-and-reroute: after an initial pass, each iteration
    reroutes only the nets touching a conflict (a shared node, or two nets too
    close), raising the cost of the contested nodes each time, until the routing
    is legal. Rerouting a handful of nets per pass -- rather than all of them --
    plus bounded A* is what lets this scale to a few hundred cells.
    Returns {net_name: (edges, term_m2nodes)}.
    """
    # term_access[net] is, per terminal, the list of candidate (xi, yi, M2)
    # access nodes for that pin.
    term_access = {}
    for nn, net in routed_nets.items():
        # A power *pin* (vdd/vss) is reached on its wide rail track; key off the
        # pin name so a tie-off net's rail terminal also uses rail access.
        term_access[nn] = [[(xi, yi, M2)
            for (xi, yi) in access_nodes(placed[iname].pins[pname], cfg,
                pname in ('VDD', 'VSS'))]
            for iname, pname in net.terminals]

    # Global routing assigns each net a corridor of gcells; detailed routing
    # stays inside the corridor (cheap, congestion-balanced), falling back to the
    # whole grid only if a net can't be realized there.
    corridors, gw, gh = global_route(routed_nets, term_access, cfg, xmax)

    def corridor_of(nn):
        cor = corridors[nn]
        return lambda node: (node[0] // gw, node[1] // gh) in cor

    history = {}          # node -> accumulated historical-congestion cost
    occupancy = {}        # node -> number of nets currently using it
    node_nets = {}        # node -> set(net)
    routes = {}           # nn -> (edges, term_m2, nodes)
    port_escape = {}      # port net -> x track of its top-edge Metal4 pad (or None)
    penalty = [0.5]       # present-congestion penalty, raised each rip-up pass

    def route_one(nn, allowed):
        terms = term_access[nn]
        own = set()

        def node_cost(node):
            base = history.get(node, 0.0)
            if node in own:
                return base
            return base + penalty[0] * occupancy.get(node, 0)

        edges, term_m2, tree = [], [], set()
        if len(terms) == 1:
            # 1-terminal port: nothing to wire together, just seat the access
            # node so the escape stack below can lift it to Metal4.
            if not terms[0]:
                return None
            node = terms[0][0]
            tree.add(node); own = {node}; term_m2.append(node)
            path = [node]
        else:
            path = _astar(terms[0], terms[1], cfg, xmax, node_cost, allowed)
            if path is None:
                return None
            edges += list(zip(path, path[1:]))
            tree.update(path); own = set(tree)
            term_m2 += [path[0], path[-1]]
        for t in range(2, len(terms)):
            path = _astar(tree, terms[t], cfg, xmax, node_cost, allowed)
            if path is None:
                return None
            edges += list(zip(path, path[1:]))
            tree.update(path); own = set(tree)
            term_m2.append(path[-1])

        # Grow each per-track run to >= 2 grid steps so its wire meets Metal min
        # area. Doing it here (not at emit time) lets the rip-up loop negotiate any
        # conflict the extension causes, instead of silently shorting a neighbor.
        vert_runs, horiz_runs = {}, {}
        for (xi, yi, lyr) in tree:
            if lyr in VERT: vert_runs.setdefault((lyr, xi), set()).add(yi)
            elif lyr in HORIZ: horiz_runs.setdefault((lyr, yi), set()).add(xi)

        def grow(coords, make_node, lo_b, hi_b):
            run = sorted(coords)
            while run[-1] - run[0] < 2:
                hi, lo = run[-1] + 1, run[0] - 1
                hi_ok, lo_ok = hi <= hi_b, lo >= lo_b
                # When both sides are legal, grow toward the cheaper (less
                # congested) one so the extension is least likely to conflict.
                pick_hi = hi_ok and (not lo_ok or node_cost(make_node(hi)) <= node_cost(make_node(lo)))
                if pick_hi:
                    edges.append((make_node(run[-1]), make_node(hi)))
                    tree.add(make_node(hi)); run.append(hi)
                elif lo_ok:
                    edges.append((make_node(run[0]), make_node(lo)))
                    tree.add(make_node(lo)); run.insert(0, lo)
                else:
                    break

        # Default-arg capture (X/Y/L) freezes the loop vars into each lambda.
        for (lyr, xi), yis in list(vert_runs.items()):
            grow(yis, lambda p, X=xi, L=lyr: (X, p, L), 1, cfg.y_track_max - 1)
        for (lyr, yi), xis in list(horiz_runs.items()):
            grow(xis, lambda p, Y=yi, L=lyr: (p, Y, L), 0, xmax)

        # Port escape: route the net up to the block's TOP edge and lift it to
        # Metal4, so its pin sits in the channel above the rows -- the parent then
        # connects there, never over the interior. That edge interface is what
        # keeps the block composable (a placement change can't drop a parent wire
        # onto an internal net). vdd/vss go to the side straps instead.
        if nn in port_nets:
            ytop = cfg.y_track_max - 1
            epath = _astar(tree, [(x, ytop, M4) for x in range(xmax + 1)],
                           cfg, xmax, node_cost, None)
            if epath is not None:
                edges += list(zip(epath, epath[1:]))
                tree.update(epath)
                port_escape[nn] = epath[-1][0]   # x of the top-edge Metal4 pad
            else:   # fallback: lift the first terminal in place (interior pad)
                xi, yi, _ = term_m2[0]
                for a, b in (((xi, yi, M2), (xi, yi, M3)),
                             ((xi, yi, M3), (xi, yi, M4))):
                    edges.append((a, b)); tree.add(a); tree.add(b)
                port_escape[nn] = None
        return (edges, term_m2, tree)

    def add(nn, r):
        routes[nn] = r
        for node in r[2]:
            occupancy[node] = occupancy.get(node, 0) + 1
            node_nets.setdefault(node, set()).add(nn)

    def remove(nn):
        for node in routes.pop(nn)[2]:
            occupancy[node] -= 1
            node_nets[node].discard(nn)

    def conflicts():
        # A conflict is a node shared by >1 net, or two different nets on
        # spacing-violating neighbor nodes. Returns the offending nodes and the
        # set of nets touching them (the nets to rip up and reroute).
        nodes, bad_nets = set(), set()
        for node, count in occupancy.items():
            if count > 1:
                nodes.add(node); bad_nets |= node_nets[node]
        for node, here in node_nets.items():
            if not here:
                continue
            for adj in _conflict_neighbors(node):
                there = node_nets.get(adj)
                if there and there - here:
                    nodes.add(node); nodes.add(adj); bad_nets |= here | there
        return nodes, bad_nets

    # Initial pass: route every net once in its corridor (fall back to the grid).
    for nn in routed_nets:
        add(nn, route_one(nn, corridor_of(nn)) or route_one(nn, None))

    # Incremental negotiated-congestion rip-up.
    for it in range(3000):
        bad_nodes, bad_nets = conflicts()
        if not bad_nodes:
            return {nn: (r[0], r[1]) for nn, r in routes.items()}, port_escape
        for node in bad_nodes:
            history[node] = history.get(node, 0.0) + 1.0
        penalty[0] = min(penalty[0] * 1.05, 50.0)
        # Once congestion has built up, let stubborn nets leave their corridor.
        allow_escape = it > 200
        for nn in sorted(bad_nets):
            remove(nn)
            allowed = None if allow_escape else corridor_of(nn)
            add(nn, route_one(nn, allowed) or route_one(nn, None))
    raise RuntimeError(f"router did not converge: {len(bad_nodes)} conflict nodes")


# --- geometry emission + top-level orchestration --------------------------

def _emit_net_direct(l, layers, edges, term_m2, cfg):
    """
    Emit one routed net's geometry directly with concrete coordinates -- no
    constraint solver. (Routing everything through ORDeC's general solver, as
    SRouter does, does not scale: it is fast per cell but takes minutes for a
    few-hundred-net block.) Wire runs become Metal2/3/4/5 paths; each layer change
    is a via cut; the overlapping wires provide the via landings, and the router's
    via-access pass keeps every run >= 2 steps so it meets area + endcap.
    """
    xp, yp = cfg.x_pitch, cfg.y_pitch
    metal_layer = {M2: layers.Metal2, M3: layers.Metal3, M4: layers.Metal4, M5: layers.Metal5}
    via_layer = {frozenset((M1, M2)): layers.Via1, frozenset((M2, M3)): layers.Via2,
        frozenset((M3, M4)): layers.Via3, frozenset((M4, M5)): layers.Via4}
    vert_runs = {}    # (layer, xi) -> set(yi)   on vertical layers (M2, M4)
    horiz_runs = {}   # (layer, yi) -> set(xi)   on horizontal layers (M3, M5)
    vias = set()  # (xi, yi, frozenset(layer pair))

    def add_node(n):
        xi, yi, lyr = n
        if lyr in VERT: vert_runs.setdefault((lyr, xi), set()).add(yi)
        elif lyr in HORIZ: horiz_runs.setdefault((lyr, yi), set()).add(xi)

    for a, b in edges:
        # Add *both* endpoints of every edge -- including via edges -- so a layer
        # a net only passes through (a transit landing) still gets metal emitted.
        add_node(a); add_node(b)
        if a[2] != b[2]:
            vias.add((a[0], a[1], frozenset((a[2], b[2]))))

    def runs(positions):
        ps = sorted(positions); out = []; s = e = ps[0]
        for p in ps[1:]:
            if p == e + 1: e = p
            else: out.append((s, e)); s = e = p
        out.append((s, e)); return out

    def path(layer, p0, p1):
        l % LayoutPath(layer=layer, width=WIRE_WIDTH, endtype=PathEndType.Custom,
            ext_bgn=WIRE_EXT, ext_end=WIRE_EXT, vertices=[p0, p1])

    # A single-node run is a pass-through via landing (e.g. Metal3 in a
    # Metal2->Metal3->Metal4 stack). A zero-length path emits no metal, so lay a
    # min-area landing rect instead (2*LAND_HALF_H long, >= Mn min area). Multi-node
    # runs already met min area via the grow / _extend_min_area passes.
    for (lyr, xi), yis in vert_runs.items():
        for y0, y1 in runs(yis):
            if y0 != y1:
                path(metal_layer[lyr], Vec2I(xi * xp, y0 * yp), Vec2I(xi * xp, y1 * yp))
                continue
            l % LayoutRect(layer=metal_layer[lyr], rect=Rect4I(
                xi * xp - STRAP_HALF_W, y0 * yp - LAND_HALF_H,
                xi * xp + STRAP_HALF_W, y0 * yp + LAND_HALF_H))
    for (lyr, yi), xis in horiz_runs.items():
        for x0, x1 in runs(xis):
            if x0 != x1:
                path(metal_layer[lyr], Vec2I(x0 * xp, yi * yp), Vec2I(x1 * xp, yi * yp))
                continue
            l % LayoutRect(layer=metal_layer[lyr], rect=Rect4I(
                x0 * xp - LAND_HALF_H, yi * yp - STRAP_HALF_W,
                x0 * xp + LAND_HALF_H, yi * yp + STRAP_HALF_W))
    for xi, yi, layer_pair in vias:
        l % LayoutRect(layer=via_layer[layer_pair], rect=Rect4I(
            xi * xp - VIA_CUT_HALF, yi * yp - VIA_CUT_HALF,
            xi * xp + VIA_CUT_HALF, yi * yp + VIA_CUT_HALF))
    for xi, yi, _lyr in term_m2:    # Via1 from the Metal1 pin up to Metal2
        l % LayoutRect(layer=layers.Via1, rect=Rect4I(
            xi * xp - VIA_CUT_HALF, yi * yp - VIA_CUT_HALF,
            xi * xp + VIA_CUT_HALF, yi * yp + VIA_CUT_HALF))
        # Metal1 endcap landing (merges with the cell pin) so the via meets the
        # 50 nm endcap rule (V1.c1) even on short foundry pins.
        l % LayoutRect(layer=layers.Metal1, rect=Rect4I(
            xi * xp - STRAP_HALF_W, yi * yp - M1_LAND_HALF_H,
            xi * xp + STRAP_HALF_W, yi * yp + M1_LAND_HALF_H))


def place_and_route(cell, layers, pin_rects, is_leaf, cfg=None):
    """Place + route a cell whose schematic instantiates Metal1-only leaf cells.
    Returns a DRC/LVS-clean :class:`~ordec.core.schema.Layout`.

    The engine is PDK-agnostic; the standard-cell library is supplied through
    three hooks:

    Args:
        cell: the cell to lay out; its schematic is flattened to leaf cells.
        layers: the PDK layer set (e.g. ``SG13G2().layers``).
        pin_rects: callable ``name -> {pin: [(x0, y0, x1, y1), ...]}`` giving a
            leaf cell's per-pin Metal1 LEF rectangles, in nm.
        is_leaf: callable ``cell -> bool``, true for a routing leaf (a standard
            cell placed as-is) and false for a composite to flatten.
        cfg: routing-grid parameters (:class:`GridConfig`); defaults to the IHP
            sg13g2 grid.
    """
    cfg = cfg or GridConfig()
    cells, nets = extract(cell, pin_rects, is_leaf)
    sig = {nn: net for nn, net in nets.items()
        if len(net.terminals) >= 2 and nn not in ('vdd', 'vss')}
    # A signal pin tied to a supply (e.g. an inactive preset/clear input held
    # high) shows up as an extra terminal on the vdd/vss net. The rails carry
    # power by abutment, not routing, so connect each such pin to its own cell's
    # rail with a short routed net -- otherwise the input is left floating.
    for pn in ('vdd', 'vss'):
        net = nets.get(pn)
        if net is None:
            continue
        for iname, pname in net.terminals:
            if pname not in ('VDD', 'VSS'):
                tn = f'_tie_{pn}_{iname}_{pname}'
                sig[tn] = NetInfo(tn, [(iname, pname), (iname, pn.upper())])

    # A 1-terminal port (an output driven by one cell, or an input feeding one)
    # is not otherwise routed; add it so it gets a Metal4 escape too, otherwise
    # the parent would stack through this block's dense Metal2/Metal3 to reach it.
    for nn, net in nets.items():
        if net.port_pin is not None and nn not in sig and nn not in ('vdd', 'vss'):
            sig[nn] = net

    # Signal ports get a Metal4 escape (see route_nets) so the parent can land
    # on them without colliding with this block's internal Metal2/Metal3.
    port_nets = {nn for nn, net in sig.items() if net.port_pin is not None}

    # Floorplan: pick the row count from the target aspect over the core area
    # (cell_area / utilization), then add rows
    # until the channel routes. The die width is max(floorplan target, balanced
    # partition width), so the cells always fit and the die stays tight.
    # Utilization sets the area; the aspect sets the shape.
    total_w = sum(cells[n].width for n in cells)
    core_area = total_w * cfg.row_height / cfg.target_util
    rh, xp = cfg.row_height, cfg.x_pitch
    base = max(1, round((core_area * cfg.target_aspect) ** 0.5 / rh))
    for i, nrows in enumerate(range(base, base + 5)):
        cfg.n_rows = nrows
        order = order_cells_sa(cells, nets, cfg)
        placed, packed_w = place_rows(cells, order, cfg)
        die_w = -(-max(round(core_area / (nrows * rh)), packed_w) // xp) * xp
        xmax = die_w // xp
        try:
            routing, port_escape = route_nets(sig, placed, cfg, xmax, port_nets)
            break
        except RuntimeError:
            if i == 4:
                raise
    if cfg.min_area_pass:
        _extend_min_area(routing, cfg, xmax)

    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)
    for name, pi in placed.items():
        setattr(l, name, LayoutInstance(ref=pi.cell.layout,
            pos=Vec2I(*pi.pos), orientation=pi.orient))

    # Emit routing directly with concrete coordinates (no constraint solver, so
    # it scales to hundreds of nets).
    for nn, (edges, term_m2) in routing.items():
        _emit_net_direct(l, layers, edges, term_m2, cfg)

    # Pad every row's rail out to the die width so the block is a flush rectangle
    # (like filler cells) and the right power strap ties into every rail.
    _pad_rails(l, layers, placed, die_w)
    if cfg.n_rows >= 2:
        _emit_power_straps(l, layers, placed, cfg, die_w)

    # Ports. A signal port was escaped to the TOP edge (route_nets): expose its
    # pin on a Metal4 pad straddling the top rail, up in the channel above the
    # block, so the parent lands there without ever routing over the interior.
    # (Fallback: an interior Metal4 pad if the escape could not reach the edge.)
    # vdd/vss carry by rail abutment, so their port stays a Metal1 rail handle.
    xp, yp = cfg.x_pitch, cfg.y_pitch
    top_abs = cfg.n_rows * cfg.row_height        # absolute y of the top rail
    for nn, net in nets.items():
        if net.port_pin is None:
            continue
        if nn in routing:                        # signal port
            ex = port_escape.get(nn)
            if ex is not None:                   # top-edge pad, above the rows
                xc = ex * xp
                r = l % LayoutRect(layer=layers.Metal4, rect=Rect4I(
                    xc - STRAP_HALF_W, top_abs - PORT_PAD_BELOW,
                    xc + STRAP_HALF_W, top_abs + PORT_PAD_ABOVE))
            else:                                # interior fallback pad
                xi, yi, _ = routing[nn][1][0]
                r = l % LayoutRect(layer=layers.Metal4, rect=Rect4I(
                    xi * xp - STRAP_HALF_W, yi * yp - LAND_HALF_H,
                    xi * xp + STRAP_HALF_W, yi * yp + LAND_HALF_H))
        else:                                    # vdd/vss
            iname, pname = net.terminals[0]
            rail = _largest_rect(placed[iname].pins[pname])
            if len(_supply_rails(placed, pname)) >= 2:
                # This supply has its own side strap (>= 2 rails; see
                # _emit_power_straps). Expose it on the strap, lifted to Metal4, so
                # a parent lands in the margin and never stacks onto an interior
                # rail (which would touch a block-internal net). Tall (690 nm)
                # landings meet Metal min area; the strap is tall enough for the
                # via endcap (V.c1) on its long pair of sides.
                sx = STRAP_VDD_X if pname == 'VDD' else STRAP_VSS_X
                cy = (rail[1] + rail[3]) // 2
                vh, sw, lh = cfg.via_half, STRAP_HALF_W, LAND_HALF_H
                l % LayoutRect(layer=layers.Via2, rect=Rect4I(sx - vh, cy - vh, sx + vh, cy + vh))
                l % LayoutRect(layer=layers.Metal3, rect=Rect4I(sx - sw, cy - lh, sx + sw, cy + lh))
                l % LayoutRect(layer=layers.Via3, rect=Rect4I(sx - vh, cy - vh, sx + vh, cy + vh))
                r = l % LayoutRect(layer=layers.Metal4, rect=Rect4I(sx - sw, cy - lh, sx + sw, cy + lh))
            else:
                # Few rows: the boustrophedon shares this supply's single rail, so
                # that one rail already ties the whole supply -- expose it directly.
                r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(*rail))
        r.create_pin(net.port_pin)
    return l.freeze()


def _largest_rect(rects):
    """The largest-area rect among `rects` (a pin may have several; its rail/body
    is the big one)."""
    return max(rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))


def _supply_rails(placed, pname):
    """Sorted distinct ``(y0, y1)`` rail spans for supply ``pname`` -- one per
    row, deduplicated where the boustrophedon shares a rail between adjacent
    rows. A side strap is emitted only when there are >= 2 of them (a single
    shared rail already ties the whole supply together)."""
    rails = set()
    for pi in placed.values():
        if pname in pi.pins:
            r = _largest_rect(pi.pins[pname])
            rails.add((r[1], r[3]))
    return sorted(rails)


def _pad_rails(l, layers, placed, die_w):
    """
    Extend every row's VDD/VSS rail rightward to a common die-width edge, the way
    filler cells do, so the block is a flush rectangle (composes cleanly, hits
    the floorplan aspect ratio) and the right-side power strap can tap every row
    (rows come out at slightly different packed widths, so without this the
    shorter rows would not reach the strap).
    """
    rails = {}   # (row, supply) -> [x1, y0, y1]
    for pi in placed.values():
        for pn in ('VDD', 'VSS'):
            if pn not in pi.pins:
                continue
            rect = _largest_rect(pi.pins[pn])
            key = (pi.row, pn)
            cur = rails.get(key)
            if cur is None:
                rails[key] = [rect[2], rect[1], rect[3]]
            else:
                cur[0] = max(cur[0], rect[2])
    for (row, pn), (x1, y0, y1) in rails.items():
        if x1 < die_w:
            l % LayoutRect(layer=layers.Metal1, rect=Rect4I(x1, y0, die_w, y1))


def _emit_power_straps(l, layers, placed, cfg, die_w):
    """
    Form a power ring per supply: a vertical Metal2 strap on each side of the
    cell area, tapping every rail through short Metal1 extensions + a Via1. The
    boustrophedon shares a rail between adjacent rows, so with several rows the
    inner rails would otherwise float; the strap ties them. A ring (vs a single
    strap) roughly halves the rail IR drop and gives a parent supply access on
    both sides. Straps sit in the empty margins left of x=0 and right of die_w
    (the flush rail edge from _pad_rails). Skipped for a supply with one shared
    rail, which already ties itself.
    """
    vh = cfg.via_half
    for pname, sxl, sxr in (('VDD', STRAP_VDD_X, die_w - STRAP_VDD_X),
                            ('VSS', STRAP_VSS_X, die_w - STRAP_VSS_X)):
        rails = _supply_rails(placed, pname)
        if len(rails) < 2:
            continue
        ylo, yhi = rails[0][0], rails[-1][1]
        for sx, edge in ((sxl, 0), (sxr, die_w)):
            l % LayoutRect(layer=layers.Metal2, rect=Rect4I(sx - STRAP_HALF_W, ylo, sx + STRAP_HALF_W, yhi))
            for (y0, y1) in rails:
                yc = (y0 + y1) // 2
                x0e, x1e = (sx - RAIL_EXT, edge) if sx < edge else (edge, sx + RAIL_EXT)
                l % LayoutRect(layer=layers.Metal1, rect=Rect4I(x0e, y0, x1e, y1))
                l % LayoutRect(layer=layers.Via1, rect=Rect4I(sx - vh, yc - vh, sx + vh, yc + vh))


def _extend_min_area(result, cfg, xmax):
    """
    Post-pass: a 210 nm wire must be >= ~686 nm long to meet Metal2/Metal3 min
    area (0.144 um^2) and to give the via a 50 nm endcap. Extend every per-net,
    per-track wire span to at least 2 grid steps, growing into free tracks.
    """
    occ = {}   # (xi,yi,layer) -> net
    for nn, (edges, _t) in result.items():
        for a, b in edges:
            occ[a] = nn; occ[b] = nn

    def free(node, nn):
        o = occ.get(node)
        if o is not None and o != nn:
            return False
        # Don't grow into a same-layer spacing conflict with another net.
        for adj in _conflict_neighbors(node):
            a = occ.get(adj)
            if a is not None and a != nn:
                return False
        return True

    for nn, (edges, term_m2) in result.items():
        nodes = set()
        for a, b in edges:
            nodes.add(a); nodes.add(b)
        vert = {}    # (layer, xi) -> set(yi)   for the vertical layers
        horiz = {}   # (layer, yi) -> set(xi)   for the horizontal layers
        for (xi, yi, lyr) in nodes:
            if lyr in VERT: vert.setdefault((lyr, xi), set()).add(yi)
            elif lyr in HORIZ: horiz.setdefault((lyr, yi), set()).add(xi)

        def grow(fixed, coords, lo, hi, make_node):
            """Extend a 1-D run [min..max] of `coords` to span >= 2 steps."""
            run = sorted(coords)
            need = 2 - (run[-1] - run[0])
            while need > 0:
                lo_ok = run[0] - 1 >= lo and free(make_node(fixed, run[0] - 1), nn)
                hi_ok = run[-1] + 1 <= hi and free(make_node(fixed, run[-1] + 1), nn)
                if hi_ok:
                    nxt = run[-1] + 1
                    edges.append((make_node(fixed, run[-1]), make_node(fixed, nxt)))
                    occ[make_node(fixed, nxt)] = nn; run.append(nxt)
                elif lo_ok:
                    nxt = run[0] - 1
                    edges.append((make_node(fixed, run[0]), make_node(fixed, nxt)))
                    occ[make_node(fixed, nxt)] = nn; run.insert(0, nxt)
                else:
                    break
                need -= 1

        for (lyr, xi), yis in vert.items():
            grow(xi, yis, 1, cfg.y_track_max - 1,
                lambda xi, yi, L=lyr: (xi, yi, L))
        for (lyr, yi), xis in horiz.items():
            grow(yi, xis, 0, xmax,
                lambda yi, xi, L=lyr: (xi, yi, L))
    return result
