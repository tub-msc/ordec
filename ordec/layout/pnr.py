# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
A gridded standard-cell place-and-route engine.

It follows the structure of a modern detailed flow: row-based placement of
standard cells, then **negotiated-congestion maze routing** on a per-layer track
grid -- place cells in rows, then rip-up-and-reroute nets with A* until the
routing is congestion-free.

The engine is PDK-agnostic: every pitch and DRC dimension arrives through the
:class:`GridConfig`, so retargeting a PDK is a new profile, not an edit here. It
does make these structural assumptions about the standard-cell flow:

* Leaf cells are Metal1-only for signals (foundry GDS cells), so the metals above
  them are free for routing -- routing stays *within* the cell-row height instead
  of being pushed above it.
* The routing grid (track pitches, row height) comes from the supplied
  ``GridConfig``: vertical tracks on one routing metal, horizontal on the next,
  the lowest metal for pin access. Cells are an integer number of vertical tracks
  wide and ``tracks_per_row`` tracks tall.
* Power (vdd/vss) connects by rail abutment, like a real standard-cell row.

The geometry (wires, via stacks) is emitted directly as concrete grid
coordinates (``emit_net_direct``): routing everything through ORDeC's general
constraint solver does not scale to hundreds of nets, so this module decides the
paths *and* lays down the metal itself.

Standard-cell coverage: it routes most IHP sg13g2 logic/sequential cells (~60 of
~74; ``tests/test_pnr.ord`` checks a representative subset). The rest
fail *loudly* -- a clear exception or a sign-off DRC violation -- on one hard case:
a Via1 endcap landing that small or staircase pins (e.g. a21o, dlhrq, sdfbbp) can't
satisfy without an M1.b/V1.c1 violation, which would take a polygon-exact via-access
engine to fix. Non-logic cells (antenna, fill, decap) are out of scope.
"""

from collections import namedtuple
from dataclasses import dataclass, field, replace
import heapq
import math
import random

from ordec.core import *
from ordec.core.schema import SchemInstanceConn


# --- routing grid configuration -------------------------------------------

@dataclass
class GridConfig:
    """Routing grid + emitted-geometry parameters. PDK-agnostic: the engine reads
    every dimension from here, so retargeting a PDK is a new profile, not an edit
    to the engine. The grid and geometry fields have no defaults -- they come from
    a PDK profile (e.g. :func:`ordec.layout.ihp_pnr.sg13g2_grid`); only the flow
    knobs at the bottom carry universal defaults. All lengths are in nm.
    """
    # Routing grid, from the PDK tech LEF:
    x_pitch: int             # vertical (Metal2) track pitch
    y_pitch: int             # horizontal (Metal3) track pitch
    row_height: int          # standard-cell row height (= tracks_per_row * y_pitch)
    tracks_per_row: int      # y-tracks per row (row_height / y_pitch)
    via_half: int            # half the Via1..Via4 cut size (V*.a / 2)
    encl: int                # min metal enclosure of via on every side (V1.c)
    encl_endcap: int         # min metal enclosure on >= 1 side (V1.c1)
    manufacturing_grid: int  # layout quantum; off-track vias snap to it (MANUFACTURINGGRID)
    # Emitted geometry, sized to the PDK DRC rules:
    wire_width: int          # Mn routing-wire width (= Mn min width)
    wire_ext: int            # wire overhang past its last via (via half + endcap)
    strap_half_w: int        # half a wire / strap / via-landing width (= wire_width / 2)
    land_half_h: int         # half the long side of a min-area via landing
    m1_land_half_h: int      # half-height of the Metal1 endcap landing under a Via1
    min_area_tracks: int     # min wire span in track pitches to meet Mn min area
    port_pad_below: int      # port-pad extent below the top rail
    port_pad_above: int      # port-pad extent above the top rail
    strap_vdd_x: int         # VDD strap x (left margin; the right strap mirrors to die_w - x)
    strap_vss_x: int         # VSS strap x (just outside VDD)
    rail_ext: int            # Metal1 overlap of a strap onto the rail it taps
    # --- flow knobs (PDK-independent; universal defaults) ---------------------
    n_rows: int = 1          # number of abutted (flipped) standard-cell rows
    via_cost: float = 4.0    # A* cost of a layer change (in track units)
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
        # Tracks on a row boundary (multiples of tracks_per_row) sit on a rail.
        return 0 < yi < self.y_track_max and yi % self.tracks_per_row != 0


# --- netlist + placement extraction ---------------------------------------

@dataclass
class PlacedInst:
    """One leaf cell placed in a row: its absolute position, orientation, and
    pin rectangles in die coordinates."""
    name: str
    cell: object          # the leaf Cell instance
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

# One net's detailed route: its wire edges, the Via1 access nodes (term_m2), and
# the full set of grid nodes it occupies (for congestion bookkeeping).
_Route = namedtuple('_Route', 'edges term_m2 tree')


def _conns_of(sch, inst):
    """Map each pin of one instance to the net it connects to.

    Args:
        sch: the Schematic containing the instance.
        inst: the SchemInstance whose connections are read.

    Returns:
        ``{pin_name: net_name}`` for ``inst``.
    """
    out = {}
    for conn in sch.all(SchemInstanceConn):
        if conn.ref.nid == inst.nid:
            out[conn.there.full_path_str().split('.')[-1]] = \
                conn.here.full_path_str().split('.')[-1]
    return out


def flatten(cell, is_leaf):
    """Flatten a (possibly hierarchical) schematic to Metal1-only foundry leaf
    instances, the way a standard-cell flow flattens a netlist before detailed
    routing.

    Sub-cells for which ``is_leaf`` is true are leaves; any other instance is
    expanded into its own schematic, with internal nets uniquified by an instance
    prefix and port nets mapped to the parent's nets.

    Args:
        cell: the top cell whose ``schematic`` view is flattened.
        is_leaf: predicate ``cell -> bool``, true for a routing leaf cell.

    Returns:
        ``(leaf_insts, net_terminals)`` -- ``leaf_insts`` maps a flat instance
        name to its leaf Cell, and ``net_terminals`` maps a net name to a list of
        ``(flat_inst_name, pin_name)`` terminals.
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
            subcell = inst.symbol.cell
            pin_to_net = {pin: canon(net)
                for pin, net in _conns_of(sch, inst).items()}
            if is_leaf(subcell):
                leaf_insts[iname] = subcell
                for pin, net in pin_to_net.items():
                    net_terminals.setdefault(net, []).append((iname, pin))
            else:
                recurse(subcell.schematic, iname + '/', pin_to_net)

    recurse(cell.schematic, '', {})
    return leaf_insts, net_terminals


def extract(cell, pin_rects, is_leaf):
    """Build the placement + net data for a cell's flattened schematic.

    Args:
        cell: the top cell to lay out.
        pin_rects: callable ``cell_name -> {pin: [(x0, y0, x1, y1), ...]}`` giving a
            leaf cell's per-pin Metal1 rectangles (a PDK hook; see
            :func:`place_and_route`).
        is_leaf: predicate ``cell -> bool``, true for a routing leaf (a PDK hook).

    Returns:
        ``(cells, nets)`` -- ``cells`` maps each leaf instance name to a
        :class:`LeafCell`, ``nets`` maps each net name to a :class:`NetInfo`.
    """
    leaf_insts, net_terminals = flatten(cell, is_leaf)

    cells = {}
    for name, leaf in leaf_insts.items():
        rects = pin_rects(leaf.name)
        # Cell pitch = power-rail width (the rail rect spans the whole cell).
        width = max(r[2] - r[0] for r in rects['VDD'])
        cells[name] = LeafCell(leaf, rects, width)

    nets = {net_name: NetInfo(net_name, list(terms))
        for net_name, terms in net_terminals.items()}

    # Mark top-level port nets (Net.pin references a symbol Pin).
    for net in cell.schematic.all(Net):
        if net.pin is not None:
            net_name = net.full_path_str().split('.')[-1]
            if net_name in nets:
                nets[net_name].port_pin = net.pin

    return cells, nets


def order_cells(cells, nets, iters=30):
    """Order the row's cells to keep nets short (low wirelength), which is what
    makes a single-row channel routable.

    Uses iterated barycenter placement: repeatedly move each cell toward the mean
    position of the cells it shares a net with, then re-rank. Power nets (which
    touch every cell) are ignored.

    Args:
        cells: ``{name: LeafCell}`` for the cells to order.
        nets: ``{name: NetInfo}`` giving the connectivity.
        iters: number of barycenter refinement passes.

    Returns:
        The cell names as a wirelength-ordered list.
    """
    order = sorted(cells)
    sig_insts = [[t[0] for t in n.terminals] for n in nets.values()
        if n.name not in ('vdd', 'vss') and len(n.terminals) >= 2]
    for _ in range(iters):
        pos = {name: i for i, name in enumerate(order)}
        barycenter = {}
        for name in order:
            total, count = 0.0, 0
            for insts in sig_insts:
                if name in insts:
                    for other in insts:
                        if other != name:
                            total += pos[other]; count += 1
            barycenter[name] = total / count if count else pos[name]
        order = sorted(order, key=lambda n: (barycenter[n], n))
    return order


def _cell_centers(cells, order, cfg):
    """Estimate each cell's ``(x, y)`` center for a folded order, to score a
    placement without building geometry.

    Args:
        cells: ``{name: LeafCell}`` (used for cell widths).
        order: the 1-D cell order to fold into rows.
        cfg: the routing/floorplan :class:`GridConfig`.

    Returns:
        ``{name: (x_center, y_center)}`` in nm.
    """
    row_height = cfg.row_height
    row_target = sum(cells[n].width for n in order) / cfg.n_rows
    center = {}
    row, row_w, x = 0, 0, 0
    for name in order:
        w = cells[name].width
        if row < cfg.n_rows - 1 and row_w + w > row_target and row_w > 0:
            row += 1; row_w = 0; x = 0
        center[name] = (x + w // 2, row * row_height + row_height // 2)
        x += w; row_w += w
    return center


def order_cells_sa(cells, nets, cfg, iters=6000, seed=1):
    """Order cells by wirelength using simulated annealing -- the classic
    standard-cell placement method.

    Starts from the barycenter order (:func:`order_cells`) and perturbs the cell
    sequence to minimise half-perimeter wirelength, weighting vertical span 2x (a
    net that stays within one row routes far more easily than one crossing rows). A
    single row, or a netlist with no multi-terminal signal nets, skips annealing
    and returns the barycenter order directly.

    Args:
        cells: ``{name: LeafCell}`` for the cells to order.
        nets: ``{name: NetInfo}`` giving the connectivity.
        cfg: the routing/floorplan :class:`GridConfig` (``n_rows`` sets the fold).
        iters: number of annealing moves.
        seed: RNG seed; fixed so the result is deterministic.

    Returns:
        The cell names as a wirelength-ordered list.
    """
    sig_insts = [[t[0] for t in n.terminals] for n in nets.values()
        if n.name not in ('vdd', 'vss') and len(n.terminals) >= 2]
    if cfg.n_rows == 1 or not sig_insts:
        return order_cells(cells, nets)

    def hpwl(order):
        center = _cell_centers(cells, order, cfg)
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


def partition_width(widths, nrows):
    """Smallest achievable maximum row width when a cell *sequence* is split into
    at most ``nrows`` contiguous rows.

    This is the classic "split array largest sum", solved by binary search on the
    width. Balancing the rows this way stops any single row from blowing up the die
    width (a fixed per-row target instead under-fills and dumps the leftover into
    the last row).

    Args:
        widths: the cell widths in placement order (nm).
        nrows: the maximum number of rows.

    Returns:
        The minimised maximum row width (nm).
    """
    if not widths:
        return 0
    lo, hi = max(widths), sum(widths)
    while lo < hi:
        mid = (lo + hi) // 2
        count, total = 1, 0
        for w in widths:
            if total + w > mid:
                count += 1; total = 0
            total += w
        if count <= nrows:
            hi = mid
        else:
            lo = mid + 1
    return lo


def place_rows(cells, order, cfg):
    """Fold the 1-D cell order into ``cfg.n_rows`` abutted standard-cell rows.

    Odd rows are mirrored (D4.MX) and their cell order reversed (a boustrophedon /
    snake), so power rails abut between rows and the dataflow stays adjacent across
    the turn -- exactly how standard-cell rows are built.

    Args:
        cells: ``{name: LeafCell}`` for the cells to place.
        order: the wirelength-ordered cell names from :func:`order_cells_sa`.
        cfg: the routing/floorplan :class:`GridConfig`.

    Returns:
        ``(placed, max_width)`` -- ``placed`` maps each name to a
        :class:`PlacedInst` (absolute position, orientation, pin rects), and
        ``max_width`` is the widest packed row (nm).
    """
    row_height = cfg.row_height
    nrows = cfg.n_rows

    # Balanced fold: pack greedily to the minimum max-row-width (the optimal
    # contiguous partition), so the rows come out even.
    max_row_w = partition_width([cells[n].width for n in order], nrows)
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
        row_y = (row + 1) * row_height if mirror else row * row_height
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
            placed[name] = PlacedInst(name, leaf, width, (x, row_y), orient, row, abs_pins)
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


def access_nodes(rects, cfg, allow_rail=False):
    """Find candidate Via1 access points for a pin from its Metal1 rectangles.

    A pin is normally reached by a Via1 at a vertical (Metal2) track inside its
    Metal1 x-extent and a horizontal (Metal3) track inside its y-extent, so the via
    sits on the track intersection. Using the clean LEF rectangles (not a polygon
    bbox) guarantees the access lands on this pin only. A pin whose metal lands
    *between* vertical tracks (e.g. xor2's Y) has no on-track via, so this falls
    back to :func:`union_access` and then :func:`offtrack_access`.

    Args:
        rects: the pin's Metal1 rectangles ``[(x0, y0, x1, y1), ...]`` in nm.
        cfg: the routing grid + DRC geometry (:class:`GridConfig`).
        allow_rail: if true (a power pin), the via may sit on a rail track, where
            the wide rail easily encloses it; signal pins use signal tracks only.

    Returns:
        A list of ``(xi, yi, via_x, via_y, land)`` candidates: the routing track
        node ``(xi, yi)`` the router connects to, the Via1 position
        ``(via_x, via_y)`` in nm, and ``land`` -- the via's Metal1 endcap-landing
        rect (grown along the axis the pin encloses as a pair so it stays within
        the pin's own metal), or ``None`` for an off-track via, which takes its
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
                # landing grows the full height on that axis so it stays inside the
                # pin; a single-endcap pin (no pair) still routes, the vertical
                # landing reaching past it to make the pair.
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
        # Keep the all-pair-or-all-single set the simple version returned, so the
        # router sees the same candidate nodes (placement/routing unchanged).
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
    """Access a pin that has no on-track via point: drop the Via1 on the pin and
    bridge to the nearest track.

    The via goes on the pin at a manufacturing-grid x on a signal y-track, with full
    via metal enclosure; the emitter then bridges across to the reported vertical
    track with a short Metal2 segment (Metal2 is free over the Metal1-only leaf
    cells). The pin's own metal must give the via its endcap, since off-track vias
    add no Metal1 landing.

    Args:
        rects: the pin's Metal1 rectangles ``[(x0, y0, x1, y1), ...]`` in nm.
        cfg: the routing grid + DRC geometry (:class:`GridConfig`).

    Returns:
        A list of ``(xi, yi, via_x, via_y)`` candidates: the nearest vertical track
        ``xi`` and signal y-track ``yi``, and the on-pin Via1 position
        ``(via_x, via_y)`` in nm.
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
    """On-track access for a staircase pin whose via enclosure comes from the
    *union* of its Metal1 rects.

    A pin like nand4's A is enclosed by no single LEF rect, so
    :func:`access_nodes`'s per-rect test misses it. Center-line ray casts measure
    how far the merged metal reaches around a track via, and the landing grows along
    the axis the merged metal reaches furthest on, so it stays on real metal.

    Args:
        rects: the pin's Metal1 rectangles ``[(x0, y0, x1, y1), ...]`` in nm.
        cfg: the routing grid + DRC geometry (:class:`GridConfig`).

    Returns:
        A list of ``(xi, yi, via_x, via_y, land)`` candidates, in the same form as
        the on-track branch of :func:`access_nodes`.
    """
    via_half, encl, encl_endcap = cfg.via_half, cfg.encl, cfg.encl_endcap
    half_w, endcap = cfg.strap_half_w, cfg.m1_land_half_h
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    mgrid = cfg.manufacturing_grid

    def covered(px, py):
        return any(x0 <= px <= x1 and y0 <= py <= y1 for (x0, y0, x1, y1) in rects)

    def reach(cx, cy, dx, dy):   # contiguous Metal1 extent from the via centre
        d = 0
        while covered(cx + dx * (d + mgrid), cy + dy * (d + mgrid)):
            d += mgrid
        return d

    xlo, xhi = min(r[0] for r in rects), max(r[2] for r in rects)
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


def _neighbors(node, cfg, xmax):
    """Yield the maze-router moves out of one grid node.

    Vertical layers (Metal2, Metal4) step in y, horizontal layers (Metal3, Metal5)
    step in x; a layer change costs ``cfg.via_cost`` and is only allowed off the
    rail tracks.

    Args:
        node: the current grid node ``(xi, yi, layer)``.
        cfg: the routing grid + cost knobs (:class:`GridConfig`).
        xmax: the maximum x track index (the right die edge).

    Yields:
        ``(neighbor_node, move_cost)`` for each legal move.
    """
    xi, yi, layer = node
    on_signal = cfg.is_signal_track(yi)
    via_cost = cfg.via_cost
    if layer == M2:                      # vertical (move in y, rails pass through)
        if yi + 1 < cfg.y_track_max: yield (xi, yi + 1, M2), 1.0
        if yi - 1 > 0:               yield (xi, yi - 1, M2), 1.0
        if on_signal:                yield (xi, yi, M3), via_cost
    elif layer == M3:                    # horizontal (move in x); via down to M2, up to M4
        if xi + 1 <= xmax: yield (xi + 1, yi, M3), 1.0
        if xi - 1 >= 0:    yield (xi - 1, yi, M3), 1.0
        yield (xi, yi, M2), via_cost
        if on_signal and cfg.use_upper: yield (xi, yi, M4), via_cost
    elif layer == M4:                    # vertical (second vertical layer)
        if yi + 1 < cfg.y_track_max: yield (xi, yi + 1, M4), 1.0
        if yi - 1 > 0:               yield (xi, yi - 1, M4), 1.0
        if on_signal:
            yield (xi, yi, M3), via_cost
            yield (xi, yi, M5), via_cost
    elif layer == M5:                    # horizontal (second horizontal layer)
        if xi + 1 <= xmax: yield (xi + 1, yi, M5), 1.0
        if xi - 1 >= 0:    yield (xi - 1, yi, M5), 1.0
        yield (xi, yi, M4), via_cost


def _astar(starts, goals, cfg, xmax, node_cost, allowed=None):
    """Route one connection by A* from any start node to any goal node.

    Args:
        starts: the set of start nodes (a terminal's access nodes, or the tree
            built so far).
        goals: the set of goal nodes (the next terminal's access nodes).
        cfg: the routing grid + cost knobs (:class:`GridConfig`).
        xmax: the maximum x track index.
        node_cost: callable ``node -> float`` adding congestion cost.
        allowed: optional predicate ``node -> bool`` restricting the search to the
            net's global-routing corridor, keeping the maze search local on large
            layouts.

    Returns:
        The path as a list of nodes from a start to a goal, or ``None`` if no path
        exists within ``allowed``.
    """
    goal_set = set(goals)
    goal_xs = [n[0] for n in goals]; goal_ys = [n[1] for n in goals]

    def heuristic(node):
        return (min(abs(node[0] - goal_x) for goal_x in goal_xs)
                + min(abs(node[1] - goal_y) for goal_y in goal_ys))

    frontier = []
    cost = {}            # node -> cheapest known cost to reach it
    came_from = {}
    for start in starts:
        cost[start] = node_cost(start)
        heapq.heappush(frontier, (cost[start] + heuristic(start), start))
    while frontier:
        _, current = heapq.heappop(frontier)
        if current in goal_set:
            path = [current]
            while current in came_from:
                current = came_from[current]; path.append(current)
            return path[::-1]
        for neighbor, step in _neighbors(current, cfg, xmax):
            if allowed is not None and not allowed(neighbor):
                continue
            new_cost = cost[current] + step + node_cost(neighbor)
            if neighbor not in cost or new_cost < cost[neighbor]:
                cost[neighbor] = new_cost; came_from[neighbor] = current
                heapq.heappush(frontier, (new_cost + heuristic(neighbor), neighbor))
    return None


def _gcell_astar(starts, goal, gcell_xmax, gcell_ymax, gcell_cost):
    """Route on the coarse gcell grid (2-D, 4-connected) for the global router.

    Args:
        starts: the set of start gcells (the net's tree so far).
        goal: the gcell to reach.
        gcell_xmax: the maximum gcell x index.
        gcell_ymax: the maximum gcell y index.
        gcell_cost: callable ``gcell -> float`` giving per-gcell congestion cost.

    Returns:
        The list of gcells on the cheapest path from any start to ``goal``.
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
    """Assign each net a coarse routing corridor by negotiated-congestion global
    routing.

    The track grid is tiled into gcells; each net's terminals are connected by a
    cheap tree on the gcell grid, with a congestion penalty on per-gcell demand so
    nets spread off hotspots. Detailed routing is then confined to each net's
    corridor (plus a one-gcell halo), which keeps the maze search local.

    Args:
        routed_nets: the nets to route, ``{name: NetInfo}``.
        term_access: per net, the list of per-terminal candidate access nodes
            (from :func:`route_nets`).
        cfg: the routing grid (:class:`GridConfig`).
        xmax: the maximum x track index.
        gcell_w: gcell width in tracks.
        gcell_h: gcell height in tracks.

    Returns:
        ``(corridors, gcell_w, gcell_h)`` -- ``corridors`` maps each net to the set
        of gcells its detailed routing may use (its tree plus a one-gcell halo).
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
            raise RuntimeError(f"net {net_name!r} has no routable pin access "
                "(a terminal pin could not be reached on or off the track grid)")
        tree = {gcells[0]}
        for gcell in gcells[1:]:
            if gcell not in tree:
                tree.update(_gcell_astar(tree, gcell,
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

    # Widen each corridor by a one-gcell halo so detailed routing has room.
    for net_name in corridors:
        halo = set()
        for (gcell_x, gcell_y) in corridors[net_name]:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    halo.add((gcell_x + dx, gcell_y + dy))
        corridors[net_name] = halo
    return corridors, gcell_w, gcell_h


def _conflict_neighbors(node):
    """Same-layer grid nodes that would violate metal spacing against ``node`` if
    used by a *different* net.

    Only the same-track, facing-ends case matters: the wire-end overhang
    (``cfg.wire_ext``) puts two facing wire ends one grid step apart, closer than
    the min metal spacing. Adjacent-track parallels are a full pitch apart (legal)
    and must NOT be flagged -- doing so rejects legal routing and stalls
    convergence. "One step" is along x for horizontal layers, along y for vertical.

    Args:
        node: the grid node ``(xi, yi, layer)`` to check around.

    Returns:
        The conflicting same-layer neighbor nodes (a tuple, possibly empty).
    """
    xi, yi, layer = node
    if layer in HORIZ:
        return ((xi + 1, yi, layer), (xi - 1, yi, layer))
    if layer in VERT:
        return ((xi, yi + 1, layer), (xi, yi - 1, layer))
    return ()


def route_nets(routed_nets, placed, cfg, xmax, port_nets=()):
    """Route the signal nets with negotiated-congestion maze routing.

    Uses *incremental* rip-up-and-reroute: after an initial pass, each iteration
    reroutes only the nets touching a conflict (a shared node, or two nets too
    close), raising the cost of the contested nodes each time, until the routing is
    legal. Rerouting a handful of nets per pass -- rather than all of them -- plus
    bounded A* is what lets this scale to a few hundred cells.

    Args:
        routed_nets: the signal nets to route, ``{name: NetInfo}``.
        placed: ``{name: PlacedInst}`` from :func:`place_rows` (for pin rects).
        cfg: the routing grid + DRC geometry (:class:`GridConfig`).
        xmax: the maximum x track index (the right die edge).
        port_nets: the names of nets that need a top-edge Metal4 escape.

    Returns:
        ``(routing, port_escape, term_via, term_land)`` -- ``routing`` maps each net
        to its ``(edges, term_m2)``; the rest are per-net overrides the emitter
        needs (port-escape x, off-track Via1 positions, Metal1 landings).

    Raises:
        RuntimeError: if a net cannot be routed or the rip-up loop does not
            converge (the caller then grows the floorplan and retries).
    """
    # term_access[net] is, per terminal, the list of candidate (xi, yi, M2)
    # access nodes for that pin. term_via maps an off-track access node to the
    # actual on-pin Via1 position (via_x, via_y); the emitter jogs it back to the
    # track. term_land maps an on-track access node to its pin-aware Metal1 landing.
    term_access = {}
    term_via = {}
    term_land = {}
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    for net_name, net in routed_nets.items():
        # A power *pin* (vdd/vss) is reached on its wide rail track; key off the
        # pin name so a tie-off net's rail terminal also uses rail access.
        cands = []
        for iname, pname in net.terminals:
            term = []
            for (xi, yi, via_x, via_y, land) in access_nodes(
                    placed[iname].pins[pname], cfg, pname in ('VDD', 'VSS')):
                node = (xi, yi, M2)
                term.append(node)
                if (via_x, via_y) != (xi * x_pitch, yi * y_pitch):
                    term_via[node] = (via_x, via_y)
                elif land is not None:
                    term_land[node] = land
            cands.append(term)
        term_access[net_name] = cands

    # Global routing assigns each net a corridor of gcells; detailed routing
    # stays inside the corridor (cheap, congestion-balanced), falling back to the
    # whole grid only if a net can't be realized there.
    corridors, gcell_w, gcell_h = global_route(routed_nets, term_access, cfg, xmax)

    def corridor_of(net_name):
        corridor = corridors[net_name]
        return lambda node: (node[0] // gcell_w, node[1] // gcell_h) in corridor

    history = {}          # node -> accumulated historical-congestion cost
    occupancy = {}        # node -> number of nets currently using it
    node_nets = {}        # node -> set(net)
    routes = {}           # net_name -> _Route
    port_escape = {}      # port net -> x track of its top-edge Metal4 pad (or None)
    penalty = [0.5]       # present-congestion penalty, raised each rip-up pass

    def route_one(net_name, allowed):
        terms = term_access[net_name]
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
        for term_idx in range(2, len(terms)):
            path = _astar(tree, terms[term_idx], cfg, xmax, node_cost, allowed)
            if path is None:
                return None
            edges += list(zip(path, path[1:]))
            tree.update(path); own = set(tree)
            term_m2.append(path[-1])

        # Grow each per-track run to the min-area track span so its wire meets Metal
        # min area. Doing it here (not at emit time) lets the rip-up loop negotiate
        # any conflict the extension causes, instead of silently shorting a neighbor.
        vert_runs, horiz_runs = {}, {}
        for (xi, yi, layer) in tree:
            if layer in VERT: vert_runs.setdefault((layer, xi), set()).add(yi)
            elif layer in HORIZ: horiz_runs.setdefault((layer, yi), set()).add(xi)

        def grow(coords, make_node, lo_b, hi_b):
            run = sorted(coords)
            while run[-1] - run[0] < cfg.min_area_tracks:
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
        for (layer, xi), y_tracks in list(vert_runs.items()):
            grow(y_tracks, lambda p, X=xi, L=layer: (X, p, L), 1, cfg.y_track_max - 1)
        for (layer, yi), x_tracks in list(horiz_runs.items()):
            grow(x_tracks, lambda p, Y=yi, L=layer: (p, Y, L), 0, xmax)

        # Port escape: route the net up to the block's TOP edge and lift it to
        # Metal4, so its pin sits in the channel above the rows -- the parent then
        # connects there, never over the interior. That edge interface is what
        # keeps the block composable (a placement change can't drop a parent wire
        # onto an internal net). vdd/vss go to the side straps instead.
        if net_name in port_nets:
            ytop = cfg.y_track_max - 1
            escape_path = _astar(tree, [(x, ytop, M4) for x in range(xmax + 1)],
                                 cfg, xmax, node_cost, None)
            if escape_path is not None:
                edges += list(zip(escape_path, escape_path[1:]))
                tree.update(escape_path)
                port_escape[net_name] = escape_path[-1][0]   # x of top-edge M4 pad
            else:   # fallback: lift the first terminal in place (interior pad)
                xi, yi, _ = term_m2[0]
                for a, b in (((xi, yi, M2), (xi, yi, M3)),
                             ((xi, yi, M3), (xi, yi, M4))):
                    edges.append((a, b)); tree.add(a); tree.add(b)
                port_escape[net_name] = None
        return _Route(edges, term_m2, tree)

    def add(net_name, route):
        routes[net_name] = route
        for node in route.tree:
            occupancy[node] = occupancy.get(node, 0) + 1
            node_nets.setdefault(node, set()).add(net_name)

    def remove(net_name):
        for node in routes.pop(net_name).tree:
            occupancy[node] -= 1
            node_nets[node].discard(net_name)

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

    def routed(net_name, allowed):
        # route_one returns None when a net can't be realised in the corridor or on
        # the full grid. Surface that as a convergence failure so place_and_route
        # grows the floorplan and retries, instead of crashing in add() on a None.
        route = route_one(net_name, allowed) or route_one(net_name, None)
        if route is None:
            raise RuntimeError(f"net {net_name!r} could not be routed")
        return route

    # Initial pass: route every net once in its corridor (fall back to the grid).
    for net_name in routed_nets:
        add(net_name, routed(net_name, corridor_of(net_name)))

    # Incremental negotiated-congestion rip-up.
    for iteration in range(3000):
        bad_nodes, bad_nets = conflicts()
        if not bad_nodes:
            routing = {net_name: (route.edges, route.term_m2)
                for net_name, route in routes.items()}
            return routing, port_escape, term_via, term_land
        for node in bad_nodes:
            history[node] = history.get(node, 0.0) + 1.0
        penalty[0] = min(penalty[0] * 1.05, 50.0)
        # Once congestion has built up, let stubborn nets leave their corridor.
        allow_escape = iteration > 200
        for net_name in sorted(bad_nets):
            remove(net_name)
            allowed = None if allow_escape else corridor_of(net_name)
            add(net_name, routed(net_name, allowed))
    raise RuntimeError(f"router did not converge: {len(bad_nodes)} conflict nodes")


# --- geometry emission + top-level orchestration --------------------------

def emit_net_direct(layout, layers, edges, term_m2, cfg,
        term_via=None, term_land=None):
    """Emit one routed net's geometry directly with concrete coordinates.

    No constraint solver is used (routing everything through ORDeC's general solver
    does not scale: it is fast per cell but takes minutes for a few-hundred-net
    block). Wire runs become Metal2/3/4/5 paths; each layer change is a via cut; the
    overlapping wires provide the via landings, and the router's via-access pass
    keeps every run long enough to meet min area + endcap.

    Args:
        layout: the mutable :class:`~ordec.core.schema.Layout` to emit into.
        layers: the PDK layer set.
        edges: the net's routed edges, each a pair of grid nodes.
        term_m2: the net's Via1 access nodes (terminal landings on Metal2).
        cfg: the routing grid + DRC geometry (:class:`GridConfig`).
        term_via: ``{node: (via_x, via_y)}`` overriding off-track terminals to an
            on-pin Via1 position the emitter jogs back to the track.
        term_land: ``{node: rect}`` giving the pin-aware Metal1 landing for an
            on-track terminal.
    """
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    metal_layer = {M2: layers.Metal2, M3: layers.Metal3, M4: layers.Metal4, M5: layers.Metal5}
    via_layer = {frozenset((M1, M2)): layers.Via1, frozenset((M2, M3)): layers.Via2,
        frozenset((M3, M4)): layers.Via3, frozenset((M4, M5)): layers.Via4}
    vert_runs = {}    # (layer, xi) -> set(yi)   on vertical layers (M2, M4)
    horiz_runs = {}   # (layer, yi) -> set(xi)   on horizontal layers (M3, M5)
    vias = set()  # (xi, yi, frozenset(layer pair))

    def add_node(node):
        xi, yi, layer = node
        if layer in VERT: vert_runs.setdefault((layer, xi), set()).add(yi)
        elif layer in HORIZ: horiz_runs.setdefault((layer, yi), set()).add(xi)

    for a, b in edges:
        # Add *both* endpoints of every edge -- including via edges -- so a layer
        # a net only passes through (a transit landing) still gets metal emitted.
        add_node(a); add_node(b)
        if a[2] != b[2]:
            vias.add((a[0], a[1], frozenset((a[2], b[2]))))

    def runs(positions):
        sorted_pos = sorted(positions); out = []; start = end = sorted_pos[0]
        for pos in sorted_pos[1:]:
            if pos == end + 1: end = pos
            else: out.append((start, end)); start = end = pos
        out.append((start, end)); return out

    def path(layer, p0, p1):
        layout % LayoutPath(layer=layer, width=cfg.wire_width,
            endtype=PathEndType.Custom, ext_bgn=cfg.wire_ext, ext_end=cfg.wire_ext,
            vertices=[p0, p1])

    # A single-node run is a pass-through via landing (e.g. Metal3 in a
    # Metal2->Metal3->Metal4 stack). A zero-length path emits no metal, so lay a
    # min-area landing rect instead; multi-node runs already meet min area via the
    # grow / extend_min_area passes.
    for (layer, xi), y_tracks in vert_runs.items():
        for y0, y1 in runs(y_tracks):
            if y0 != y1:
                path(metal_layer[layer], Vec2I(xi * x_pitch, y0 * y_pitch),
                    Vec2I(xi * x_pitch, y1 * y_pitch))
                continue
            layout % LayoutRect(layer=metal_layer[layer], rect=Rect4I(
                xi * x_pitch - cfg.strap_half_w, y0 * y_pitch - cfg.land_half_h,
                xi * x_pitch + cfg.strap_half_w, y0 * y_pitch + cfg.land_half_h))
    for (layer, yi), x_tracks in horiz_runs.items():
        for x0, x1 in runs(x_tracks):
            if x0 != x1:
                path(metal_layer[layer], Vec2I(x0 * x_pitch, yi * y_pitch),
                    Vec2I(x1 * x_pitch, yi * y_pitch))
                continue
            layout % LayoutRect(layer=metal_layer[layer], rect=Rect4I(
                x0 * x_pitch - cfg.land_half_h, yi * y_pitch - cfg.strap_half_w,
                x0 * x_pitch + cfg.land_half_h, yi * y_pitch + cfg.strap_half_w))
    for xi, yi, layer_pair in vias:
        layout % LayoutRect(layer=via_layer[layer_pair], rect=Rect4I(
            xi * x_pitch - cfg.via_half, yi * y_pitch - cfg.via_half,
            xi * x_pitch + cfg.via_half, yi * y_pitch + cfg.via_half))
    term_via = term_via or {}
    for node in term_m2:            # Via1 from the Metal1 pin up to Metal2
        xi, yi, _layer = node
        if node in term_via:
            # Off-track pin (no track lands inside it): drop the via on the pin at
            # via_x and jog to track xi with a short Metal2 segment. The pin's own
            # metal gives the Via1 endcap, so no Metal1 landing is added (it would
            # notch the pin and break Metal1 spacing).
            via_x, via_y = term_via[node]
            layout % LayoutRect(layer=layers.Via1, rect=Rect4I(
                via_x - cfg.via_half, via_y - cfg.via_half,
                via_x + cfg.via_half, via_y + cfg.via_half))
            lo, hi = min(via_x, xi * x_pitch), max(via_x, xi * x_pitch)
            layout % LayoutRect(layer=layers.Metal2, rect=Rect4I(
                lo - cfg.strap_half_w, via_y - cfg.land_half_h,
                hi + cfg.strap_half_w, via_y + cfg.land_half_h))
        else:
            via_x, via_y = xi * x_pitch, yi * y_pitch
            layout % LayoutRect(layer=layers.Via1, rect=Rect4I(
                via_x - cfg.via_half, via_y - cfg.via_half,
                via_x + cfg.via_half, via_y + cfg.via_half))
            # Metal1 endcap landing (merges with the cell pin) so the via meets the
            # 50 nm endcap rule (V1.c1) even on short foundry pins. access_nodes
            # shapes it along the pin's enclosing axis so it never notches a
            # neighbouring cell pin.
            land = (term_land or {}).get(node, (
                via_x - cfg.strap_half_w, via_y - cfg.m1_land_half_h,
                via_x + cfg.strap_half_w, via_y + cfg.m1_land_half_h))
            layout % LayoutRect(layer=layers.Metal1, rect=Rect4I(*land))


def place_and_route(cell, layers, pin_rects, is_leaf, cfg):
    """Place + route a cell whose schematic instantiates Metal1-only leaf cells.
    Returns a DRC/LVS-clean :class:`~ordec.core.schema.Layout`.

    The engine is PDK-agnostic: every PDK-specific input is supplied by the
    caller -- no layer, pitch or DRC dimension is baked into this module.

    Args:
        cell: the cell to lay out; its schematic is flattened to leaf cells.
        layers: the PDK layer set (e.g. ``SG13G2().layers``).
        pin_rects: callable ``name -> {pin: [(x0, y0, x1, y1), ...]}`` giving a
            leaf cell's per-pin Metal1 LEF rectangles, in nm.
        is_leaf: callable ``cell -> bool``, true for a routing leaf (a standard
            cell placed as-is) and false for a composite to flatten.
        cfg: the routing grid + DRC geometry for this PDK (:class:`GridConfig`);
            build one per PDK, e.g. :func:`ordec.layout.ihp_pnr.sg13g2_grid`.

    Returns:
        A frozen, DRC/LVS-clean :class:`~ordec.core.schema.Layout` for ``cell``.
    """
    cfg = replace(cfg)   # private copy: the floorplan loop below mutates cfg.n_rows
    cells, nets = extract(cell, pin_rects, is_leaf)
    signal_nets = {net_name: net for net_name, net in nets.items()
        if len(net.terminals) >= 2 and net_name not in ('vdd', 'vss')}
    # A signal pin tied to a supply (e.g. an inactive preset/clear input held
    # high) shows up as an extra terminal on the vdd/vss net. The rails carry
    # power by abutment, not routing, so connect each such pin to its own cell's
    # rail with a short routed net -- otherwise the input is left floating.
    for supply in ('vdd', 'vss'):
        net = nets.get(supply)
        if net is None:
            continue
        for iname, pname in net.terminals:
            if pname not in ('VDD', 'VSS'):
                tie_name = f'_tie_{supply}_{iname}_{pname}'
                signal_nets[tie_name] = NetInfo(tie_name,
                    [(iname, pname), (iname, supply.upper())])

    # A 1-terminal port (an output driven by one cell, or an input feeding one)
    # is not otherwise routed; add it so it gets a Metal4 escape too, otherwise
    # the parent would stack through this block's dense Metal2/Metal3 to reach it.
    for net_name, net in nets.items():
        if (net.port_pin is not None and net_name not in signal_nets
                and net_name not in ('vdd', 'vss')):
            signal_nets[net_name] = net

    # Signal ports get a Metal4 escape (see route_nets) so the parent can land
    # on them without colliding with this block's internal Metal2/Metal3.
    port_nets = {net_name for net_name, net in signal_nets.items()
        if net.port_pin is not None}

    # Floorplan: pick the row count from the target aspect over the core area
    # (cell_area / utilization), then add rows until the channel routes. The die
    # width is max(floorplan target, balanced partition width), so the cells always
    # fit and the die stays tight. Utilization sets the area; the aspect, the shape.
    total_w = sum(cells[n].width for n in cells)
    core_area = total_w * cfg.row_height / cfg.target_util
    row_height, x_pitch = cfg.row_height, cfg.x_pitch
    base = max(1, round((core_area * cfg.target_aspect) ** 0.5 / row_height))
    for i, nrows in enumerate(range(base, base + 5)):
        cfg.n_rows = nrows
        order = order_cells_sa(cells, nets, cfg)
        placed, packed_w = place_rows(cells, order, cfg)
        die_w = -(-max(round(core_area / (nrows * row_height)), packed_w) // x_pitch) * x_pitch
        xmax = die_w // x_pitch
        try:
            routing, port_escape, term_via, term_land = route_nets(
                signal_nets, placed, cfg, xmax, port_nets)
            break
        except RuntimeError:
            if i == 4:
                raise
    if cfg.min_area_pass:
        extend_min_area(routing, cfg, xmax)

    layout = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)
    for name, inst in placed.items():
        setattr(layout, name, LayoutInstance(ref=inst.cell.layout,
            pos=Vec2I(*inst.pos), orientation=inst.orient))

    # Emit routing directly with concrete coordinates (no constraint solver, so
    # it scales to hundreds of nets).
    for net_name, (edges, term_m2) in routing.items():
        emit_net_direct(layout, layers, edges, term_m2, cfg, term_via, term_land)

    # Pad every row's rail out to the die width so the block is a flush rectangle
    # (like filler cells) and the right power strap ties into every rail.
    pad_rails(layout, layers, placed, die_w)
    if cfg.n_rows >= 2:
        emit_power_straps(layout, layers, placed, cfg, die_w)

    # Ports. A signal port was escaped to the TOP edge (route_nets): expose its
    # pin on a Metal4 pad straddling the top rail, up in the channel above the
    # block, so the parent lands there without ever routing over the interior.
    # (Fallback: an interior Metal4 pad if the escape could not reach the edge.)
    # vdd/vss carry by rail abutment, so their port stays a Metal1 rail handle.
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    top_abs = cfg.n_rows * cfg.row_height        # absolute y of the top rail
    for net_name, net in nets.items():
        if net.port_pin is None:
            continue
        if net_name in routing:                  # signal port
            escape_x = port_escape.get(net_name)
            if escape_x is not None:                   # top-edge pad, above the rows
                track_x = escape_x * x_pitch
                port_rect = layout % LayoutRect(layer=layers.Metal4, rect=Rect4I(
                    track_x - cfg.strap_half_w, top_abs - cfg.port_pad_below,
                    track_x + cfg.strap_half_w, top_abs + cfg.port_pad_above))
            else:                                # interior fallback pad
                xi, yi, _ = routing[net_name][1][0]
                port_rect = layout % LayoutRect(layer=layers.Metal4, rect=Rect4I(
                    xi * x_pitch - cfg.strap_half_w, yi * y_pitch - cfg.land_half_h,
                    xi * x_pitch + cfg.strap_half_w, yi * y_pitch + cfg.land_half_h))
        else:                                    # vdd/vss
            # Expose on an actual supply pin: a signal pin tied to this rail (e.g. a
            # held-high RESET_B on the vdd net) is also a terminal here, but the port
            # belongs on the VDD/VSS rail, not on that tied pin (which would put the
            # pad off-grid and on the wrong net).
            iname, pname = next((i, p) for i, p in net.terminals
                if p in ('VDD', 'VSS'))
            rail = _largest_rect(placed[iname].pins[pname])
            if len(_supply_rails(placed, pname)) >= 2:
                # Supply with its own side strap (see emit_power_straps): expose it
                # on the strap, lifted to Metal4, so a parent lands in the margin and
                # never stacks onto an interior rail (which carries a block net).
                strap_x = cfg.strap_vdd_x if pname == 'VDD' else cfg.strap_vss_x
                rail_y_center = (rail[1] + rail[3]) // 2
                via_half, half_w, land_half = (
                    cfg.via_half, cfg.strap_half_w, cfg.land_half_h)
                layout % LayoutRect(layer=layers.Via2, rect=Rect4I(
                    strap_x - via_half, rail_y_center - via_half,
                    strap_x + via_half, rail_y_center + via_half))
                layout % LayoutRect(layer=layers.Metal3, rect=Rect4I(
                    strap_x - half_w, rail_y_center - land_half,
                    strap_x + half_w, rail_y_center + land_half))
                layout % LayoutRect(layer=layers.Via3, rect=Rect4I(
                    strap_x - via_half, rail_y_center - via_half,
                    strap_x + via_half, rail_y_center + via_half))
                port_rect = layout % LayoutRect(layer=layers.Metal4, rect=Rect4I(
                    strap_x - half_w, rail_y_center - land_half,
                    strap_x + half_w, rail_y_center + land_half))
            else:
                # Few rows: the boustrophedon shares this supply's single rail, so
                # that one rail already ties the whole supply -- expose it directly.
                port_rect = layout % LayoutRect(layer=layers.Metal1,
                    rect=Rect4I(*rail))
        port_rect.create_pin(net.port_pin)
    return layout.freeze()


def _largest_rect(rects):
    """Return the largest-area rect among ``rects``.

    Args:
        rects: ``(x0, y0, x1, y1)`` rectangles (a pin may have several).

    Returns:
        The biggest one -- a pin's rail/body rect.
    """
    return max(rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))


def _supply_rails(placed, pname):
    """Distinct rail spans for one supply, sorted bottom-to-top.

    Rails are deduplicated where the boustrophedon shares one between adjacent rows;
    a side strap is emitted only when there are >= 2 of them (a single shared rail
    already ties the whole supply together).

    Args:
        placed: ``{name: PlacedInst}`` from :func:`place_rows`.
        pname: the supply pin name (``'VDD'`` or ``'VSS'``).

    Returns:
        The sorted distinct ``(y0, y1)`` rail spans (nm).
    """
    rails = set()
    for inst in placed.values():
        if pname in inst.pins:
            rail = _largest_rect(inst.pins[pname])
            rails.add((rail[1], rail[3]))
    return sorted(rails)


def pad_rails(layout, layers, placed, die_w):
    """Extend every row's VDD/VSS rail rightward to a common die-width edge.

    Like filler cells, this makes the block a flush rectangle (composes cleanly,
    hits the floorplan aspect ratio) and lets the right-side power strap tap every
    row -- rows come out at slightly different packed widths, so without this the
    shorter rows would not reach the strap.

    Args:
        layout: the mutable :class:`~ordec.core.schema.Layout` to emit into.
        layers: the PDK layer set.
        placed: ``{name: PlacedInst}`` from :func:`place_rows`.
        die_w: the die width to pad each rail out to (nm).
    """
    rails = {}   # (row, supply) -> [x1, y0, y1]
    for inst in placed.values():
        for supply in ('VDD', 'VSS'):
            if supply not in inst.pins:
                continue
            rect = _largest_rect(inst.pins[supply])
            key = (inst.row, supply)
            existing = rails.get(key)
            if existing is None:
                rails[key] = [rect[2], rect[1], rect[3]]
            else:
                existing[0] = max(existing[0], rect[2])
    for (row, supply), (x1, y0, y1) in rails.items():
        if x1 < die_w:
            layout % LayoutRect(layer=layers.Metal1, rect=Rect4I(x1, y0, die_w, y1))


def emit_power_straps(layout, layers, placed, cfg, die_w):
    """Form a power ring per supply: a vertical Metal2 strap in the empty margin on
    each side of the cell area, tapping every rail through a short Metal1 extension
    + Via1.

    The boustrophedon shares a rail between adjacent rows, so the inner rails would
    otherwise float; the ring ties them and halves rail IR drop. Skipped for a
    supply with one shared rail (it already ties itself).

    Args:
        layout: the mutable :class:`~ordec.core.schema.Layout` to emit into.
        layers: the PDK layer set.
        placed: ``{name: PlacedInst}`` from :func:`place_rows`.
        cfg: the routing grid + geometry (:class:`GridConfig`).
        die_w: the die width (nm); the right strap mirrors to it.
    """
    via_half = cfg.via_half
    for pname, strap_left_x, strap_right_x in (
            ('VDD', cfg.strap_vdd_x, die_w - cfg.strap_vdd_x),
            ('VSS', cfg.strap_vss_x, die_w - cfg.strap_vss_x)):
        rails = _supply_rails(placed, pname)
        if len(rails) < 2:
            continue
        strap_y0, strap_y1 = rails[0][0], rails[-1][1]
        for strap_x, edge in ((strap_left_x, 0), (strap_right_x, die_w)):
            layout % LayoutRect(layer=layers.Metal2, rect=Rect4I(
                strap_x - cfg.strap_half_w, strap_y0,
                strap_x + cfg.strap_half_w, strap_y1))
            for (rail_y0, rail_y1) in rails:
                rail_y_center = (rail_y0 + rail_y1) // 2
                # Metal1 tap from the strap across to the rail edge.
                tap_x0, tap_x1 = ((strap_x - cfg.rail_ext, edge) if strap_x < edge
                    else (edge, strap_x + cfg.rail_ext))
                layout % LayoutRect(layer=layers.Metal1,
                    rect=Rect4I(tap_x0, rail_y0, tap_x1, rail_y1))
                layout % LayoutRect(layer=layers.Via1, rect=Rect4I(
                    strap_x - via_half, rail_y_center - via_half,
                    strap_x + via_half, rail_y_center + via_half))


def extend_min_area(result, cfg, xmax):
    """Post-pass: lengthen any too-short wire so it meets the metal min-area rule.

    A min-width wire must span enough tracks to meet min area and give its end-via
    the required endcap. Each per-net, per-track wire run is extended to at least
    ``cfg.min_area_tracks`` grid steps, growing into free tracks.

    Args:
        result: the routing ``{net: (edges, term_m2)}`` to extend in place.
        cfg: the routing grid + geometry (:class:`GridConfig`).
        xmax: the maximum x track index.

    Returns:
        The same ``result`` mapping (mutated in place).
    """
    node_net = {}   # (xi, yi, layer) -> net_name
    for net_name, (edges, _term_m2) in result.items():
        for a, b in edges:
            node_net[a] = net_name; node_net[b] = net_name

    def free(node, net_name):
        owner = node_net.get(node)
        if owner is not None and owner != net_name:
            return False
        # Don't grow into a same-layer spacing conflict with another net.
        for adj in _conflict_neighbors(node):
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
