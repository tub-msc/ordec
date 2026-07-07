# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
A gridded standard-cell place-and-route engine.

It follows the structure of a modern detailed flow: row-based placement of
standard cells, then **negotiated-congestion maze routing** on a per-layer track
grid -- place cells in rows, then rip-up-and-reroute nets (an L/Z-pattern fast
path first, A* where contested) until the routing is congestion-free.

The engine is PDK-agnostic: every pitch and DRC dimension arrives through the
:class:`GridConfig` and every layer through the :class:`RoutingStack`, so
retargeting a PDK is a new profile, not an edit here. It does make these
structural assumptions about the standard-cell flow:

* Leaf cells are Metal1-only for signals (foundry GDS cells), so the metals above
  them are free for routing -- routing stays *within* the cell-row height instead
  of being pushed above it.
* The routing grid (track pitches, row height) comes from the supplied
  ``GridConfig``: vertical tracks on one routing metal, horizontal on the next,
  the lowest metal for pin access. Cells are an integer number of vertical tracks
  wide and ``tracks_per_row`` tracks tall.
* Power connects by rail abutment, like a real standard-cell row; multi-row
  blocks add a ring of side straps plus a top-metal mesh over the rails. The
  supply pin and net names are part of the ``GridConfig`` profile.

The geometry (wires, via stacks) is emitted directly as concrete grid
coordinates (``emit_net_direct``): routing everything through ORDeC's general
constraint solver does not scale to hundreds of nets, so this module decides the
paths *and* lays down the metal itself.

Standard-cell coverage: it routes most IHP sg13g2 logic/sequential cells (~60 of
~74; ``tests/test_pnr.ord`` checks a representative subset). The rest fail
*loudly*: a cell with LEF geometry above Metal1 (sdfbbp) is rejected with a clear
exception by the PDK binding, and a few cells with very small or staircase pins
(e.g. a21o, dlhrq) can hit a Via1 endcap landing that cannot be satisfied without
an M1.b/V1.c1 violation, which would take a polygon-exact via-access engine to
fix. Non-logic cells (antenna, fill, decap) are out of scope.
"""

# Standard imports
import bisect
from collections import namedtuple
from dataclasses import dataclass, field, replace
import heapq
import math
import random

# ORDeC imports
from ordec.core import *


class PinAccessError(RuntimeError):
    """A terminal cannot be connected on the routing grid.

    Unlike congestion, this is permanent: growing the floorplan and retrying
    cannot make a pin reachable, so :func:`place_and_route` re-raises it
    immediately instead of burning retries.
    """


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
    # Supply naming, from the cell library / netlist conventions of the PDK
    # binding. Rail abutment shorts all like-named rails, so the engine supports
    # exactly one net per supply pin and validates these names loudly.
    vdd_pin: str             # supply pin name on the leaf cells (e.g. 'VDD')
    vss_pin: str             # ground pin name on the leaf cells (e.g. 'VSS')
    vdd_net: str             # required schematic net name for the supply
    vss_net: str             # required schematic net name for ground
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
    mesh_half_w: int         # half-width of a horizontal power-mesh strap (Metal5)
    # --- flow knobs (PDK-independent; universal defaults) ---------------------
    n_rows: int = 1          # number of abutted (flipped) standard-cell rows
    via_cost: float = 4.0    # A* cost of a layer change (in track units)
    min_area_pass: bool = True
    use_upper: bool = True   # allow routing on Metal4/Metal5 (else Metal2/3 only)
    power_mesh: bool = True  # Metal5 straps over the rails, stitched down to them
    mesh_tap_pitch: int = 8  # track columns between mesh-to-rail via stacks
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

    @property
    def supply_pin_names(self):
        return (self.vdd_pin, self.vss_pin)

    @property
    def supply_net_names(self):
        return (self.vdd_net, self.vss_net)

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

# One routed *segment* of a net (a 2-pin MST edge, the min-area extensions, or
# the port escape): its wire edges, the grid nodes it occupies (congestion
# bookkeeping), its terminal endpoints as (terminal index, node) pairs, and the
# nodes shadowed by an off-track access bridge (kept clear of every net,
# including this one -- the bridge metal ends too close to them).
RouteSeg = namedtuple('RouteSeg', 'edges nodes pairs shadows', defaults=((),))


def pin_nets(inst):
    """Map each pin of one instance to the net it connects to.

    Args:
        inst: the SchemInstance whose connections are read (via the
            ``SchemInstanceConn.ref_idx`` index, not a full-schematic scan).

    Returns:
        ``{pin_name: net_name}`` for ``inst``.
    """
    out = {}
    for conn in inst.conns():
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
                for pin, net in pin_nets(inst).items()}
            if is_leaf(subcell):
                leaf_insts[iname] = subcell
                for pin, net in pin_to_net.items():
                    net_terminals.setdefault(net, []).append((iname, pin))
            else:
                recurse(subcell.schematic, iname + '/', pin_to_net)

    recurse(cell.schematic, '', {})
    return leaf_insts, net_terminals


def extract(cell, pin_rects, is_leaf, cfg):
    """Build the placement + net data for a cell's flattened schematic.

    Args:
        cell: the top cell to lay out.
        pin_rects: callable ``cell_name -> {pin: [(x0, y0, x1, y1), ...]}`` giving a
            leaf cell's per-pin Metal1 rectangles (a PDK hook; see
            :func:`place_and_route`).
        is_leaf: predicate ``cell -> bool``, true for a routing leaf (a PDK hook).
        cfg: the :class:`GridConfig` (for the supply pin naming).

    Returns:
        ``(cells, nets)`` -- ``cells`` maps each leaf instance name to a
        :class:`LeafCell`, ``nets`` maps each net name to a :class:`NetInfo`.
    """
    leaf_insts, net_terminals = flatten(cell, is_leaf)

    cells = {}
    for name, leaf in leaf_insts.items():
        # Wrap the PDK hook's raw nm tuples as Rect4I, so the rest of the engine
        # works with named geometry (rect.lx / .cx / .width, vertex-in-rect) rather
        # than positional indexing.
        rects = {pin: [Rect4I(*r) for r in raw]
            for pin, raw in pin_rects(leaf.name).items()}
        # Cell pitch = power-rail width (the rail rect spans the whole cell).
        width = max(r.width for r in rects[cfg.vdd_pin])
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


def order_cells(cells, nets, supply_nets=(), iters=30):
    """Order the row's cells to keep nets short (low wirelength), which is what
    makes a single-row channel routable.

    Uses iterated barycenter placement: repeatedly move each cell toward the mean
    position of the cells it shares a net with, then re-rank. Power nets (which
    touch every cell) are ignored.

    Args:
        cells: ``{name: LeafCell}`` for the cells to order.
        nets: ``{name: NetInfo}`` giving the connectivity.
        supply_nets: the power net names to ignore.
        iters: number of barycenter refinement passes.

    Returns:
        The cell names as a wirelength-ordered list.
    """
    order = sorted(cells)
    sig_insts = [[t[0] for t in n.terminals] for n in nets.values()
        if n.name not in supply_nets and len(n.terminals) >= 2]
    # Inverted index: per cell, (net id, occurrences) for the nets it is on.
    # The sum over a cell's co-members is the net's position sum minus the
    # cell's own contribution, so a pass needs only the per-net sums (computed
    # once) rather than a membership scan of every net per cell -- O(sum of
    # net degrees) instead of O(cells * nets * degree).
    cell_nets = {name: [] for name in order}
    for ni, insts in enumerate(sig_insts):
        occurrences = {}
        for inst in insts:
            occurrences[inst] = occurrences.get(inst, 0) + 1
        for inst, occ in occurrences.items():
            cell_nets[inst].append((ni, occ))
    net_len = [len(insts) for insts in sig_insts]
    for _ in range(iters):
        pos = {name: i for i, name in enumerate(order)}
        net_sum = [sum(pos[inst] for inst in insts) for insts in sig_insts]
        barycenter = {}
        for name in order:
            total, count = 0.0, 0
            for ni, occ in cell_nets[name]:
                total += net_sum[ni] - occ * pos[name]
                count += net_len[ni] - occ
            barycenter[name] = total / count if count else pos[name]
        order = sorted(order, key=lambda n: (barycenter[n], n))
    return order


def fold_rows(cells, order, cfg):
    """Fold the 1-D cell order into ``cfg.n_rows`` contiguous rows, balanced to
    the minimal max-row-width (:func:`partition_width`).

    This is the single fold used both to score a candidate order
    (:func:`cell_centers`) and to build the placement (:func:`place_rows`), so
    the annealer optimises exactly the geometry that gets built.

    Args:
        cells: ``{name: LeafCell}`` (used for cell widths).
        order: the 1-D cell order to fold.
        cfg: the routing/floorplan :class:`GridConfig`.

    Returns:
        The rows as lists of cell names, still in order (odd-row mirroring is
        the caller's concern); padded with empty rows up to ``cfg.n_rows``.
    """
    max_row_w = partition_width([cells[n].width for n in order], cfg.n_rows)
    rows = [[]]
    row_w = 0
    for name in order:
        w = cells[name].width
        if rows[-1] and row_w + w > max_row_w and len(rows) < cfg.n_rows:
            rows.append([]); row_w = 0
        rows[-1].append(name); row_w += w
    while len(rows) < cfg.n_rows:
        rows.append([])
    return rows


def cell_centers(cells, order, cfg):
    """Estimate each cell's ``(x, y)`` center for a folded order, to score a
    placement without building geometry.

    Uses the same balanced fold *and* odd-row (boustrophedon) reversal as
    :func:`place_rows`: a mirrored row is placed right-to-left, so a cell's
    scored x must mirror too, or the annealer would systematically mis-score
    every net that touches an odd row.

    Args:
        cells: ``{name: LeafCell}`` (used for cell widths).
        order: the 1-D cell order to fold into rows.
        cfg: the routing/floorplan :class:`GridConfig`.

    Returns:
        ``{name: (x_center, y_center)}`` in nm.
    """
    row_height = cfg.row_height
    center = {}
    for row, row_cells in enumerate(fold_rows(cells, order, cfg)):
        if row % 2 == 1:
            row_cells = row_cells[::-1]
        x = 0
        y = row * row_height + row_height // 2
        for name in row_cells:
            w = cells[name].width
            center[name] = (x + w // 2, y)
            x += w
    return center


def order_cells_sa(cells, nets, cfg, iters=6000, seed=1, resync=500):
    """Order cells by wirelength using simulated annealing -- the classic
    standard-cell placement method.

    Starts from the barycenter order (:func:`order_cells`) and perturbs the cell
    sequence to minimise half-perimeter wirelength, weighting vertical span 2x (a
    net that stays within one row routes far more easily than one crossing rows). A
    single row, or a netlist with no multi-terminal signal nets, skips annealing
    and returns the barycenter order directly.

    A move is scored *incrementally*, as production annealers do: a swap
    exchanges the two cells' scored positions and re-derives the bounding boxes
    of just the nets touching them (a net holding both cells is unchanged), so
    a move costs O(degree) instead of a full fold + every-net HPWL pass. Slot
    positions drift from the true fold when unequal-width cells swap, so every
    ``resync`` accepted moves the fold and every bbox are recomputed exactly and
    the incumbent is re-scored against the best -- bounding the drift while
    keeping the amortised move cost constant.

    Args:
        cells: ``{name: LeafCell}`` for the cells to order.
        nets: ``{name: NetInfo}`` giving the connectivity.
        cfg: the routing/floorplan :class:`GridConfig` (``n_rows`` sets the fold).
        iters: number of annealing moves.
        seed: RNG seed; fixed so the result is deterministic.
        resync: accepted moves between exact re-folds (drift bound).

    Returns:
        The cell names as a wirelength-ordered list.
    """
    net_members = [sorted({t[0] for t in n.terminals}) for n in nets.values()
        if n.name not in cfg.supply_net_names and len(n.terminals) >= 2]
    net_members = [members for members in net_members if len(members) >= 2]
    if cfg.n_rows == 1 or not net_members:
        return order_cells(cells, nets, cfg.supply_net_names)
    membership = [frozenset(members) for members in net_members]
    nets_of = {name: [] for name in cells}
    for ni, members in enumerate(net_members):
        for name in members:
            nets_of[name].append(ni)

    def half_perim(box):
        return (box[1] - box[0]) + 2 * (box[3] - box[2])

    def full_state(order):
        center = cell_centers(cells, order, cfg)
        bbox = []
        for members in net_members:
            xs = [center[m][0] for m in members]
            ys = [center[m][1] for m in members]
            bbox.append((min(xs), max(xs), min(ys), max(ys)))
        return center, bbox, sum(half_perim(box) for box in bbox)

    def moved_bbox(ni, box, moved, new_pos):
        # One member of net ni moves off box to new_pos: extend for a growing
        # move; only a cell leaving the boundary forces an O(degree) rescan.
        old = center[moved]
        if (old[0] <= box[0] or old[0] >= box[1]
                or old[1] <= box[2] or old[1] >= box[3]):
            xs = [new_pos[0] if m == moved else center[m][0]
                for m in net_members[ni]]
            ys = [new_pos[1] if m == moved else center[m][1]
                for m in net_members[ni]]
            return (min(xs), max(xs), min(ys), max(ys))
        return (min(box[0], new_pos[0]), max(box[1], new_pos[0]),
                min(box[2], new_pos[1]), max(box[3], new_pos[1]))

    rng = random.Random(seed)
    order = order_cells(cells, nets, cfg.supply_net_names)
    center, bbox, cur_cost = full_state(order)
    best_order, best_cost = order[:], cur_cost
    temp = max(cur_cost / max(len(order), 1), 1.0)
    accepted = 0
    for _ in range(iters):
        a, b = rng.randrange(len(order)), rng.randrange(len(order))
        if a == b:
            continue
        cell_a, cell_b = order[a], order[b]
        pos_a, pos_b = center[cell_a], center[cell_b]
        # A net holding both cells sees the same position multiset after the
        # swap -- its bbox cannot change, so only the one-sided nets rescore.
        touched = ([(ni, cell_a, pos_b) for ni in nets_of[cell_a]
                if cell_b not in membership[ni]]
            + [(ni, cell_b, pos_a) for ni in nets_of[cell_b]
                if cell_a not in membership[ni]])
        delta = 0.0
        new_boxes = []
        for ni, moved, new_pos in touched:
            box = moved_bbox(ni, bbox[ni], moved, new_pos)
            new_boxes.append((ni, box))
            delta += half_perim(box) - half_perim(bbox[ni])
        if delta <= 0 or rng.random() < math.exp(-delta / temp):
            order[a], order[b] = order[b], order[a]
            center[cell_a], center[cell_b] = pos_b, pos_a
            for ni, box in new_boxes:
                bbox[ni] = box
            cur_cost += delta
            accepted += 1
            if accepted % resync == 0:   # exact re-fold: cancel slot drift
                center, bbox, cur_cost = full_state(order)
                if cur_cost < best_cost:
                    best_cost, best_order = cur_cost, order[:]
        temp *= 0.9995
    _, _, final_cost = full_state(order)
    if final_cost < best_cost:
        best_cost, best_order = final_cost, order[:]
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

    # Balanced fold: pack greedily to the minimum max-row-width (the optimal
    # contiguous partition), so the rows come out even.
    rows = fold_rows(cells, order, cfg)

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
                abs_pins = {pin: [Rect4I(r.lx + x, row_y - r.uy, r.ux + x, row_y - r.ly)
                    for r in rects] for pin, rects in local_pins.items()}
            else:
                abs_pins = {pin: [Rect4I(r.lx + x, r.ly + row_y, r.ux + x, r.uy + row_y)
                    for r in rects] for pin, rects in local_pins.items()}
            placed[name] = PlacedInst(name, leaf, width, (x, row_y), orient, row, abs_pins)
            x += width
        max_w = max(max_w, x)
    return placed, max_w


# --- routing grid + maze router -------------------------------------------

# Internal layer codes -- abstract routing-stack positions, NOT PDK layers. The
# engine routes on two vertical layers (codes M2, M4) and two horizontal (M3, M5),
# with M1 reserved for pin access; doubling the routing layers ~doubles capacity,
# as production routers do. A RoutingStack from the PDK binding maps these abstract
# codes to concrete PDK layers, so no PDK layer name is baked into the engine.
M2, M3, M1, M4, M5 = 0, 1, 2, 3, 4
VERT = (M2, M4)        # vertical routing layers (move in y)
HORIZ = (M3, M5)       # horizontal routing layers (move in x)


@dataclass
class RoutingStack:
    """Maps the engine's abstract routing stack onto concrete PDK layers.

    PDK-agnostic hook, the layer counterpart of :class:`GridConfig`: the binding
    supplies the layer objects, so no PDK layer name is baked into the engine
    (retargeting a PDK is a new profile, not an edit here). The engine assumes a
    Metal1-only pin-access layer plus four routing metals -- two vertical (``m2``,
    ``m4``), two horizontal (``m3``, ``m5``) -- stacked with four vias (``via1``
    bridges the pin metal up to ``m2``, then one via between each routing metal).

    Every field is a concrete layer object from the caller's PDK layer set; ``m1``
    .. ``m5`` and ``via1`` .. ``via4`` mirror the like-named internal codes.
    """
    layer_set: object   # full PDK layer set, passed through as Layout.ref_layers
    m1: object          # pin-access metal (code M1)
    m2: object          # first vertical routing metal (code M2)
    m3: object          # first horizontal routing metal (code M3)
    m4: object          # second vertical routing metal (code M4)
    m5: object          # second horizontal routing metal (code M5)
    via1: object        # pin metal <-> m2
    via2: object        # m2 <-> m3
    via3: object        # m3 <-> m4
    via4: object        # m4 <-> m5


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

    Vertical layers (codes M2, M4) step in y, horizontal layers (M3, M5) step in
    x; a layer change costs ``cfg.via_cost`` and is only allowed off the
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
    :func:`route_nets` run and then served as a plain dict hit -- taking the
    generator, the signal-track test and the property lookups out of the maze
    router's inner loop. It is filled on first touch rather than precomputed:
    the pattern-routing fast path keeps the maze searches to a small fraction
    of the grid, so eagerly tabulating every node (grids run to hundreds of
    thousands of nodes) costs more than all the lookups it serves.

    Nodes in ``blocked`` (reserved for the power mesh) are dropped from every
    move list, so the maze router can never enter them -- a hard blockage, not
    a congestion penalty.
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

    The congestion cost is inlined rather than taken from a callback: a node
    costs its accumulated history, plus the present-congestion penalty per
    foreign net on it (a node the net already uses is history-only, so segments
    share track). The cost lookups run once per expanded edge -- the engine's
    innermost loop -- which is why they are plain dict probes here.

    Args:
        starts: the set of start nodes (a terminal's access nodes, or the tree
            built so far).
        goals: the set of goal nodes (the next terminal's access nodes).
        cfg: the routing grid + cost knobs (:class:`GridConfig`).
        xmax: the maximum x track index.
        history: ``{node: accumulated congestion cost}``.
        occupancy: ``{node: number of nets on it}``.
        own_use: ``{node: ...}`` for the nodes this net already uses.
        penalty: the present-congestion penalty per foreign occupant.
        allowed: optional set of ``(xi, yi)`` track positions restricting the
            search to the net's global-routing corridor, keeping the maze
            search local on large layouts.
        adj: optional :class:`GridAdjacency` move table; falls back to
            generating moves per expansion.

    Returns:
        The path as a list of nodes from a start to a goal, or ``None`` if no path
        exists within ``allowed``.
    """
    goal_set = set(goals)
    # Bounding-box heuristic: distance to the goals' bbox is a lower bound on the
    # distance to any goal (admissible) and is O(1) per node -- scanning the goal
    # list per expansion instead dominated the whole engine's runtime on searches
    # with large goal sets (a port escape targets every top-row track).
    gx_lo = min(n[0] for n in goals); gx_hi = max(n[0] for n in goals)
    gy_lo = min(n[1] for n in goals); gy_hi = max(n[1] for n in goals)
    # Via-aware term: a vertical layer only moves in y and a horizontal one only
    # in x, so covering a nonzero dx and/or dy and finishing on the goals' layer
    # class needs a provable minimum number of layer changes (each >= via_cost).
    # Tightening h with it prunes most off-layer exploration (via_cost dominates
    # short in-channel hops). All goal layers agree in practice (terminal
    # goals are M2, escapes M4); a mixed set drops the finishing constraint.
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
        ``corridors`` -- per net, the frozenset of ``(xi, yi)`` track positions
        its detailed routing may use (its gcell tree plus a one-gcell halo,
        expanded to track positions so the maze router tests membership with a
        plain set probe).
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

    The MST fixes each multi-terminal net's 2-pin decomposition: every edge
    becomes an independently routable (and independently rip-up-able) segment,
    which is what lets the negotiation loop reroute one broken connection of a
    high-fan-out net instead of the whole tree.

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


def route_nets(routed_nets, placed, cfg, xmax, port_nets=(), blocked=frozenset(),
        taps=()):
    """Route the signal nets with negotiated-congestion maze routing.

    Each net is decomposed into 2-pin *segments* along an MST over its terminals
    (plus min-area-extension and port-escape segments), and rip-up-and-reroute
    runs at segment granularity: after an initial pass, each iteration reroutes
    only the segments touching a conflict (a shared node, or two nets too
    close), raising the cost of the contested nodes each time, until the routing
    is legal. Rerouting single 2-pin connections per pass -- rather than whole
    multi-terminal trees -- plus a pattern-routing fast path (L then Z shapes)
    that reserves the corridor-bounded maze search for contested segments is
    what lets this scale to a few hundred cells.

    Args:
        routed_nets: the signal nets to route, ``{name: NetInfo}``.
        placed: ``{name: PlacedInst}`` from :func:`place_rows` (for pin rects).
        cfg: the routing grid + DRC geometry (:class:`GridConfig`).
        xmax: the maximum x track index (the right die edge).
        port_nets: the names of nets that need a top-edge Metal4 escape.
        blocked: grid nodes reserved for the power mesh
            (:func:`mesh_blocked_nodes`); no route, terminal access or escape
            column may use them.
        taps: the power-mesh tap columns behind ``blocked``
            (:func:`mesh_tap_columns`); their rail landings are kept clear of
            off-track access bridges.

    Returns:
        ``(routing, port_escape, net_via, net_land, reserved)`` -- ``routing``
        maps each net to its ``(edges, term_m2)``; ``port_escape`` maps a port
        net to its top-edge pad x; ``net_via``/``net_land`` map each net to the
        ``{node: ...}`` off-track Via1 / Metal1-landing overrides its emitter
        call needs; ``reserved`` is the set of nodes shadowed by off-track
        access bridges (kept clear of any later wire growth).

    Raises:
        PinAccessError: if a terminal is unreachable on the grid (permanent --
            the caller re-raises instead of retrying).
        RuntimeError: if the rip-up loop does not converge (the caller then
            grows the floorplan and retries).
    """
    # term_access[net] is, per terminal, the list of candidate (xi, yi, M2)
    # access nodes for that pin. term_via maps an off-track terminal candidate to
    # the actual on-pin Via1 position (via_x, via_y); the emitter jogs it back to
    # the track. term_land maps an on-track candidate to its pin-aware Metal1
    # landing. Both are keyed per (net, terminal index, node): different pins may
    # legitimately share a *candidate* node, so a node-only key could silently
    # attribute one pin's via geometry to another.
    term_access = {}
    term_via = {}
    term_land = {}
    sole = {}   # node -> (net, inst, pin) for terminals with a single candidate
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch

    # An off-track terminal's Metal2 bridge is an off-grid rect the node-based
    # conflict model cannot see; the power-mesh tap landings are off-grid too.
    # Reject any off-track candidate whose bridge would come within the metal
    # spacing of a tap landing (rects mutually expanded -- conservative).
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
        # A power *pin* (vdd/vss) is reached on its wide rail track; key off the
        # pin name so a tie-off net's rail terminal also uses rail access.
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
            # can never both be routed; fail with the pin names now instead of
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

    # Global routing assigns each net a corridor of gcells; detailed routing
    # stays inside the corridor (cheap, congestion-balanced), falling back to the
    # whole grid only if a net can't be realized there.
    corridors = global_route(routed_nets, term_access, cfg, xmax)

    # Every port net gets a unique top-row escape column near the mean x of its
    # pin candidates. Uniqueness removes pad contention by construction, and a
    # single-goal escape search is directed (cheap). A shared full-width goal
    # row also converges but pays a fan-out search per escape; per-net goal
    # *windows* do not converge at all (overlapping nets fight for the same few
    # top-row tracks instead of spreading). Columns whose top-row Metal4 node is
    # blocked (a power-mesh tap) cannot host a pad.
    escape_col = {}
    if port_nets:
        ytop = cfg.y_track_max - 1
        usable = [x for x in range(xmax + 1) if (x, ytop, M4) not in blocked]
        if len(port_nets) > len(usable):
            raise PinAccessError(f"{len(port_nets)} port escapes need more "
                f"top-row columns than the die has free ({len(usable)})")
        prefs = []
        for port_name in sorted(port_nets):
            xs = [n[0] for term in term_access[port_name] for n in term]
            prefs.append((sum(xs) / len(xs), port_name))
        prefs.sort()
        prev = -1
        for k, (pref, port_name) in enumerate(prefs):
            hi = len(usable) - (len(prefs) - k)   # room for the ports right of us
            prev = min(max(prev + 1, bisect.bisect_left(usable, round(pref))), hi)
            escape_col[port_name] = usable[prev]

    history = {}          # node -> accumulated historical-congestion cost
    occupancy = {}        # node -> number of nets currently using it
    node_nets = {}        # node -> set(net)
    routes = {}           # net -> {segment key: RouteSeg}
    net_use = {}          # net -> {node: number of the net's segments using it}
    port_escape = {}      # port net -> x track of its top-edge Metal4 pad (or None)
    penalty = [0.5]       # present-congestion penalty, raised each rip-up pass
    adj = GridAdjacency(cfg, xmax, blocked)   # lazy per-run move table for A*

    # Fixed 2-pin decomposition: each net's terminals are spanned by an MST
    # (over first-candidate positions), and every MST edge is an independently
    # routable -- and independently rip-up-able -- segment. Segment keys per
    # net: ('t', k) for MST edge k, 'seat' for a 1-terminal net's access node,
    # 'ext' for the min-area extensions, 'esc' for the port escape.
    topo = {net_name: mst_edges([term[0][:2] for term in term_access[net_name]])
        for net_name in routed_nets}

    def make_node_cost(net_name):
        # A node used by this net's *other* segments costs only history, so
        # segments share track (Steiner-like reuse); foreign occupancy pays
        # the present-congestion penalty. (The maze router inlines the same
        # cost; this closure serves the min-area growth decisions.)
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
        # Pattern-routing fast path: before the maze search, try the 1-bend
        # L shapes, then the 2-bend Z shapes, between the closest access-node
        # pairs, and take one whose nodes are all conflict-free. Checking a
        # path is a few dict probes per node; a maze search is a heap
        # expansion over a whole region -- and in the initial pass almost
        # every segment is a clean L. Contested nodes (history) are left to
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
                # Vias sit on the bend tracks; both must allow a layer change.
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
        # track between the endpoints. Same wirelength as an L; the
        # vertical-horizontal-vertical shape also has the same via count.
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
            # Horizontal-vertical-horizontal Z (two more vias); sample the
            # bend columns so a die-wide net stays a bounded check.
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
                # this means a terminal is unreachable -- permanent.
                raise PinAccessError(f"net {net_name!r} could not be routed: a "
                    "terminal is unreachable on the routing grid")
            shadows = (jog_reserved(net_name, ti, path[0])
                + jog_reserved(net_name, tj, path[-1]))
            return RouteSeg(tuple(zip(path, path[1:])), frozenset(path),
                ((ti, path[0]), (tj, path[-1])), shadows)

        if key == 'esc':
            # Port escape: lift the net to its reserved top-row Metal4 column,
            # so its pin sits in the channel above the rows -- the parent then
            # connects there, never over the interior. That edge interface is
            # what keeps the block composable (a placement change can't drop a
            # parent wire onto an internal net). vdd/vss go to the side straps.
            tree = set(own_use)
            ytop = cfg.y_track_max - 1
            path = astar(tree, [(escape_col[net_name], ytop, M4)],
                cfg, xmax, history, occupancy, own_use, penalty[0], None, adj)
            if path is None:   # blocked column: any top-row node will do
                path = astar(tree, [(x, ytop, M4) for x in range(xmax + 1)],
                    cfg, xmax, history, occupancy, own_use, penalty[0], None, adj)
            if path is None:   # last resort: interior pad on the first terminal
                _ti, node = next(p for seg in routes[net_name].values()
                    for p in seg.pairs)
                xi, yi, _layer = node
                stack = ((xi, yi, M2), (xi, yi, M3), (xi, yi, M4))
                port_escape[net_name] = None
                return RouteSeg(tuple(zip(stack, stack[1:])), frozenset(stack), ())
            port_escape[net_name] = path[-1][0]   # x of the top-edge M4 pad
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

    # Conflicts are tracked INCREMENTALLY: scanning every occupied node per
    # negotiation pass instead scales with the total wirelength routed so far
    # and dominated large runs. overused holds the nodes shared by >1 net;
    # spacing_bad the same-layer neighbor pairs owned by different nets. Both
    # only change when a node gains its first or loses its last net, so they
    # are maintained right there, in add_seg/remove_seg.
    overused = set()
    spacing_bad = set()   # canonical (min(node, nbr), max(node, nbr)) pairs

    def update_spacing(node):
        here = node_nets.get(node)
        for neighbor in spacing_neighbors(node):
            there = node_nets.get(neighbor)
            pair = (node, neighbor) if node < neighbor else (neighbor, node)
            if here and there and here != there:
                spacing_bad.add(pair)
            else:
                spacing_bad.discard(pair)

    def add_nodes(owner, nodes):
        use = net_use.setdefault(owner, {})
        for node in nodes:
            count = use.get(node, 0)
            use[node] = count + 1
            if count == 0:   # first segment of this owner on the node
                occ = occupancy.get(node, 0) + 1
                occupancy[node] = occ
                if occ > 1:
                    overused.add(node)
                node_nets.setdefault(node, set()).add(owner)
                update_spacing(node)

    def remove_nodes(owner, nodes):
        use = net_use[owner]
        for node in nodes:
            count = use[node] - 1
            if count:
                use[node] = count
            else:
                del use[node]
                occ = occupancy[node] - 1
                occupancy[node] = occ
                if occ <= 1:
                    overused.discard(node)
                node_nets[node].discard(owner)
                update_spacing(node)

    def add_seg(net_name, key, seg):
        routes[net_name][key] = seg
        add_nodes(net_name, seg.nodes)
        if seg.shadows:
            # Bridge shadows are owned by a pseudo-net, so the conflict
            # machinery keeps every real net -- including this one -- off them;
            # conflicts() rips up only real nets, never the shadow itself.
            add_nodes(('bridge', net_name), seg.shadows)

    def remove_seg(net_name, key):
        seg = routes[net_name].pop(key)
        remove_nodes(net_name, seg.nodes)
        if seg.shadows:
            remove_nodes(('bridge', net_name), seg.shadows)

    def conflicts():
        # A conflict is a node shared by >1 net, or two different nets on
        # spacing-violating neighbor nodes. Returns the offending nodes and the
        # set of real nets touching them (whose segments are then ripped up --
        # bridge-shadow pseudo-nets move with their terminal, not on their own).
        nodes = set(overused)
        for pair in spacing_bad:
            nodes.update(pair)
        bad_nets = set()
        for node in nodes:
            bad_nets.update(node_nets.get(node, ()))
        return nodes, {net for net in bad_nets if net in routes}

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
    # agree on the via geometry -- otherwise the emitter could realise one
    # pin's access but not the other's.
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
    return routing, port_escape, net_via, net_land, reserved


# --- geometry emission + top-level orchestration --------------------------

def emit_net_direct(layout, stack, edges, term_m2, cfg,
        term_via=None, term_land=None):
    """Emit one routed net's geometry directly with concrete coordinates.

    No constraint solver is used (routing everything through ORDeC's general solver
    does not scale: it is fast per cell but takes minutes for a few-hundred-net
    block). Wire runs become Metal2/3/4/5 paths; each layer change is a via cut; the
    overlapping wires provide the via landings, and the router's via-access pass
    keeps every run long enough to meet min area + endcap.

    Args:
        layout: the mutable :class:`Layout` to emit into.
        stack: the :class:`RoutingStack` mapping routing codes to PDK layers.
        edges: the net's routed edges, each a pair of grid nodes.
        term_m2: the net's Via1 access nodes (terminal landings on Metal2).
        cfg: the routing grid + DRC geometry (:class:`GridConfig`).
        term_via: this net's ``{node: (via_x, via_y)}`` overrides (from
            :func:`route_nets`), moving an off-track terminal's Via1 onto the pin;
            the emitter jogs it back to the track.
        term_land: this net's ``{node: rect}`` pin-aware Metal1 landings for
            on-track terminals.
    """
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    metal_layer = {M2: stack.m2, M3: stack.m3, M4: stack.m4, M5: stack.m5}
    via_layer = {frozenset((M1, M2)): stack.via1, frozenset((M2, M3)): stack.via2,
        frozenset((M3, M4)): stack.via3, frozenset((M4, M5)): stack.via4}
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
    # dict.fromkeys: two terminals of one net may share an access node; emit its
    # via stack once.
    for node in dict.fromkeys(term_m2):   # Via1 from the Metal1 pin up to Metal2
        xi, yi, _layer = node
        if node in term_via:
            # Off-track pin (no track lands inside it): drop the via on the pin at
            # via_x and jog to track xi with a short Metal2 segment. The pin's own
            # metal gives the Via1 endcap, so no Metal1 landing is added (it would
            # notch the pin and break Metal1 spacing).
            via_x, via_y = term_via[node]
            layout % LayoutRect(layer=stack.via1, rect=Rect4I(
                via_x - cfg.via_half, via_y - cfg.via_half,
                via_x + cfg.via_half, via_y + cfg.via_half))
            lo, hi = min(via_x, xi * x_pitch), max(via_x, xi * x_pitch)
            layout % LayoutRect(layer=stack.m2, rect=Rect4I(
                lo - cfg.strap_half_w, via_y - cfg.land_half_h,
                hi + cfg.strap_half_w, via_y + cfg.land_half_h))
        else:
            via_x, via_y = xi * x_pitch, yi * y_pitch
            layout % LayoutRect(layer=stack.via1, rect=Rect4I(
                via_x - cfg.via_half, via_y - cfg.via_half,
                via_x + cfg.via_half, via_y + cfg.via_half))
            # Metal1 endcap landing (merges with the cell pin) so the via meets the
            # 50 nm endcap rule (V1.c1) even on short foundry pins. access_nodes
            # shapes it along the pin's enclosing axis so it never notches a
            # neighbouring cell pin.
            land = (term_land or {}).get(node, (
                via_x - cfg.strap_half_w, via_y - cfg.m1_land_half_h,
                via_x + cfg.strap_half_w, via_y + cfg.m1_land_half_h))
            layout % LayoutRect(layer=stack.m1, rect=Rect4I(*land))


def place_and_route(cell, stack, pin_rects, is_leaf, cfg):
    """Place + route a cell whose schematic instantiates Metal1-only leaf cells.
    Returns a DRC/LVS-clean :class:`Layout`.

    The engine is PDK-agnostic: every PDK-specific input is supplied by the
    caller -- no layer, pitch or DRC dimension is baked into this module.

    Args:
        cell: the cell to lay out; its schematic is flattened to leaf cells.
        stack: the :class:`RoutingStack` binding routing codes to this PDK's layers.
        pin_rects: callable ``name -> {pin: [(x0, y0, x1, y1), ...]}`` giving a
            leaf cell's per-pin Metal1 LEF rectangles, in nm.
        is_leaf: callable ``cell -> bool``, true for a routing leaf (a standard
            cell placed as-is) and false for a composite to flatten.
        cfg: the routing grid + DRC geometry for this PDK (:class:`GridConfig`);
            build one per PDK, e.g. :func:`ordec.layout.ihp_pnr.sg13g2_grid`.

    Returns:
        A frozen, DRC/LVS-clean :class:`Layout` for ``cell``.
    """
    cfg = replace(cfg)   # private copy: the floorplan loop below mutates cfg.n_rows
    cells, nets = extract(cell, pin_rects, is_leaf, cfg)

    # Rail abutment shorts every VDD rail in the block together (likewise VSS),
    # so the engine supports exactly one net per supply pin -- and it must carry
    # the profile's conventional name, since supply handling is keyed off it.
    # Anything else would produce a layout that silently merges nets.
    for pname, expected in ((cfg.vdd_pin, cfg.vdd_net), (cfg.vss_pin, cfg.vss_net)):
        domains = sorted({net_name for net_name, net in nets.items()
            if any(p == pname for _i, p in net.terminals)})
        if len(domains) > 1:
            raise ValueError(f"nets {domains} all drive {pname} pins: rail "
                "abutment would short them together; the engine supports only "
                "one supply domain")
        if domains and domains[0] != expected:
            raise ValueError(f"the net on the {pname} pins is named "
                f"{domains[0]!r}; the engine requires it to be {expected!r}")

    signal_nets = {net_name: net for net_name, net in nets.items()
        if len(net.terminals) >= 2 and net_name not in cfg.supply_net_names}
    # A signal pin tied to a supply (e.g. an inactive preset/clear input held
    # high) shows up as an extra terminal on the supply net. The rails carry
    # power by abutment, not routing, so connect each such pin to its own cell's
    # rail with a short routed net -- otherwise the input is left floating.
    for supply_net, supply_pin in ((cfg.vdd_net, cfg.vdd_pin),
            (cfg.vss_net, cfg.vss_pin)):
        net = nets.get(supply_net)
        if net is None:
            continue
        for iname, pname in net.terminals:
            if pname not in cfg.supply_pin_names:
                tie_name = f'_tie_{supply_net}_{iname}_{pname}'
                signal_nets[tie_name] = NetInfo(tie_name,
                    [(iname, pname), (iname, supply_pin)])

    # A 1-terminal port (an output driven by one cell, or an input feeding one)
    # is not otherwise routed; add it so it gets a Metal4 escape too, otherwise
    # the parent would stack through this block's dense Metal2/Metal3 to reach it.
    for net_name, net in nets.items():
        if (net.port_pin is not None and net_name not in signal_nets
                and net_name not in cfg.supply_net_names):
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
    # Mesh tap columns cannot host port escapes, so a pad-limited die needs
    # proportionally more columns.
    escape_cols = len(port_nets)
    if cfg.power_mesh:
        escape_cols = escape_cols * cfg.mesh_tap_pitch // (cfg.mesh_tap_pitch - 1) + 1
    for i, nrows in enumerate(range(base, base + 5)):
        cfg.n_rows = nrows
        order = order_cells_sa(cells, nets, cfg)
        placed, packed_w = place_rows(cells, order, cfg)
        # Die width: the floorplan target or the widest packed row -- or, like a
        # pad-limited chip, the top-edge port pads (one escape column each).
        die_w = -(-max(round(core_area / (nrows * row_height)), packed_w,
            (escape_cols - 1) * x_pitch) // x_pitch) * x_pitch
        xmax = die_w // x_pitch
        # The power mesh needs >= 2 rails per supply to stitch (like the side
        # straps); a single-row block keeps its one shared rail per supply.
        # Its tap columns are chosen around the pin accesses this placement
        # forces: a tap that invalidates a terminal's every access candidate
        # deadlocks the rip-up loop (the terminal cannot negotiate away).
        mesh = cfg.power_mesh and nrows >= 2
        if mesh:
            taps = mesh_tap_columns(cfg, xmax,
                tap_avoid_columns(signal_nets, placed, cfg))
            blocked = mesh_blocked_nodes(cfg, xmax, taps)
        else:
            taps, blocked = (), frozenset()
        try:
            routing, port_escape, term_via, term_land, reserved = route_nets(
                signal_nets, placed, cfg, xmax, port_nets, blocked, taps)
            break
        except PinAccessError:
            raise   # permanent: more rows cannot make a pin reachable
        except RuntimeError:
            if i == 4:
                raise
    if cfg.min_area_pass:
        extend_min_area(routing, cfg, xmax, blocked | reserved)

    layout = Layout(ref_layers=stack.layer_set, cell=cell, symbol=cell.symbol)
    for name, inst in placed.items():
        setattr(layout, name, LayoutInstance(ref=inst.cell.layout,
            pos=Vec2I(*inst.pos), orientation=inst.orient))

    # Emit routing directly with concrete coordinates (no constraint solver, so
    # it scales to hundreds of nets).
    for net_name, (edges, term_m2) in routing.items():
        emit_net_direct(layout, stack, edges, term_m2, cfg,
            term_via.get(net_name), term_land.get(net_name))

    # Pad every row's rail out to the die width so the block is a flush rectangle
    # (like filler cells) and the right power strap ties into every rail.
    pad_rails(layout, stack, placed, die_w, cfg.supply_pin_names)
    if cfg.n_rows >= 2:
        emit_power_straps(layout, stack, placed, cfg, die_w)
    if mesh:
        emit_power_mesh(layout, stack, placed, cfg, die_w, taps)

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
                port_rect = layout % LayoutRect(layer=stack.m4, rect=Rect4I(
                    track_x - cfg.strap_half_w, top_abs - cfg.port_pad_below,
                    track_x + cfg.strap_half_w, top_abs + cfg.port_pad_above))
            else:                                # interior fallback pad
                xi, yi, _ = routing[net_name][1][0]
                port_rect = layout % LayoutRect(layer=stack.m4, rect=Rect4I(
                    xi * x_pitch - cfg.strap_half_w, yi * y_pitch - cfg.land_half_h,
                    xi * x_pitch + cfg.strap_half_w, yi * y_pitch + cfg.land_half_h))
        else:                                    # vdd/vss
            # Expose on an actual supply pin: a signal pin tied to this rail (e.g. a
            # held-high RESET_B on the vdd net) is also a terminal here, but the port
            # belongs on the VDD/VSS rail, not on that tied pin (which would put the
            # pad off-grid and on the wrong net).
            iname, pname = next((i, p) for i, p in net.terminals
                if p in cfg.supply_pin_names)
            rail = largest_rect(placed[iname].pins[pname])
            if len(supply_rails(placed, pname)) >= 2:
                # Supply with its own side strap (see emit_power_straps): expose it
                # on the strap, lifted to Metal4, so a parent lands in the margin and
                # never stacks onto an interior rail (which carries a block net).
                strap_x = cfg.strap_vdd_x if pname == cfg.vdd_pin else cfg.strap_vss_x
                rail_y_center = (rail.ly + rail.uy) // 2
                via_half, half_w, land_half = (
                    cfg.via_half, cfg.strap_half_w, cfg.land_half_h)
                layout % LayoutRect(layer=stack.via2, rect=Rect4I(
                    strap_x - via_half, rail_y_center - via_half,
                    strap_x + via_half, rail_y_center + via_half))
                layout % LayoutRect(layer=stack.m3, rect=Rect4I(
                    strap_x - half_w, rail_y_center - land_half,
                    strap_x + half_w, rail_y_center + land_half))
                layout % LayoutRect(layer=stack.via3, rect=Rect4I(
                    strap_x - via_half, rail_y_center - via_half,
                    strap_x + via_half, rail_y_center + via_half))
                port_rect = layout % LayoutRect(layer=stack.m4, rect=Rect4I(
                    strap_x - half_w, rail_y_center - land_half,
                    strap_x + half_w, rail_y_center + land_half))
            else:
                # Few rows: the boustrophedon shares this supply's single rail, so
                # that one rail already ties the whole supply -- expose it directly.
                port_rect = layout % LayoutRect(layer=stack.m1, rect=rail)
        port_rect.create_pin(net.port_pin)
    return layout.freeze()


def largest_rect(rects):
    """Return the largest-area rect among ``rects``.

    Args:
        rects: ``(x0, y0, x1, y1)`` rectangles (a pin may have several).

    Returns:
        The biggest one -- a pin's rail/body rect.
    """
    return max(rects, key=lambda r: r.width * r.height)


def supply_rails(placed, pname):
    """Distinct rail spans for one supply, sorted bottom-to-top.

    Rails are deduplicated where the boustrophedon shares one between adjacent rows;
    a side strap is emitted only when there are >= 2 of them (a single shared rail
    already ties the whole supply together).

    Args:
        placed: ``{name: PlacedInst}`` from :func:`place_rows`.
        pname: the supply pin name (e.g. ``'VDD'``).

    Returns:
        The sorted distinct ``(y0, y1)`` rail spans (nm).
    """
    rails = set()
    for inst in placed.values():
        if pname in inst.pins:
            rail = largest_rect(inst.pins[pname])
            rails.add((rail.ly, rail.uy))
    return sorted(rails)


def pad_rails(layout, stack, placed, die_w, supply_pins):
    """Extend every row's supply rail rightward to a common die-width edge.

    Like filler cells, this makes the block a flush rectangle (composes cleanly,
    hits the floorplan aspect ratio) and lets the right-side power strap tap every
    row -- rows come out at slightly different packed widths, so without this the
    shorter rows would not reach the strap.

    Args:
        layout: the mutable :class:`Layout` to emit into.
        stack: the :class:`RoutingStack` mapping routing codes to PDK layers.
        placed: ``{name: PlacedInst}`` from :func:`place_rows`.
        die_w: the die width to pad each rail out to (nm).
        supply_pins: the supply pin names (``cfg.supply_pin_names``).
    """
    rails = {}   # (row, supply) -> [x1, y0, y1]
    for inst in placed.values():
        for supply in supply_pins:
            if supply not in inst.pins:
                continue
            rect = largest_rect(inst.pins[supply])
            key = (inst.row, supply)
            existing = rails.get(key)
            if existing is None:
                rails[key] = [rect.ux, rect.ly, rect.uy]
            else:
                existing[0] = max(existing[0], rect.ux)
    for (row, supply), (x1, y0, y1) in rails.items():
        if x1 < die_w:
            layout % LayoutRect(layer=stack.m1, rect=Rect4I(x1, y0, die_w, y1))


def emit_power_straps(layout, stack, placed, cfg, die_w):
    """Form a power ring per supply: a vertical Metal2 strap in the empty margin on
    each side of the cell area, tapping every rail through a short Metal1 extension
    + Via1.

    The boustrophedon shares a rail between adjacent rows, so the inner rails would
    otherwise float; the ring ties them and halves rail IR drop. Skipped for a
    supply with one shared rail (it already ties itself).

    Args:
        layout: the mutable :class:`Layout` to emit into.
        stack: the :class:`RoutingStack` mapping routing codes to PDK layers.
        placed: ``{name: PlacedInst}`` from :func:`place_rows`.
        cfg: the routing grid + geometry (:class:`GridConfig`).
        die_w: the die width (nm); the right strap mirrors to it.
    """
    via_half = cfg.via_half
    for pname, strap_left_x, strap_right_x in (
            (cfg.vdd_pin, cfg.strap_vdd_x, die_w - cfg.strap_vdd_x),
            (cfg.vss_pin, cfg.strap_vss_x, die_w - cfg.strap_vss_x)):
        rails = supply_rails(placed, pname)
        if len(rails) < 2:
            continue
        strap_y0, strap_y1 = rails[0][0], rails[-1][1]
        for strap_x, edge in ((strap_left_x, 0), (strap_right_x, die_w)):
            layout % LayoutRect(layer=stack.m2, rect=Rect4I(
                strap_x - cfg.strap_half_w, strap_y0,
                strap_x + cfg.strap_half_w, strap_y1))
            for (rail_y0, rail_y1) in rails:
                rail_y_center = (rail_y0 + rail_y1) // 2
                # Metal1 tap from the strap across to the rail edge.
                tap_x0, tap_x1 = ((strap_x - cfg.rail_ext, edge) if strap_x < edge
                    else (edge, strap_x + cfg.rail_ext))
                layout % LayoutRect(layer=stack.m1,
                    rect=Rect4I(tap_x0, rail_y0, tap_x1, rail_y1))
                layout % LayoutRect(layer=stack.via1, rect=Rect4I(
                    strap_x - via_half, rail_y_center - via_half,
                    strap_x + via_half, rail_y_center + via_half))


def tap_avoid_columns(routed_nets, placed, cfg):
    """Find the track columns where a power-mesh tap could strand a pin access.

    A terminal negotiates congestion by retreating to another of its access
    candidates; a terminal ALL of whose candidates one tap column would
    invalidate has no retreat, so a conflict there can never resolve and the
    rip-up loop deadlocks (or the pin becomes outright unroutable). A tap
    invalidates a candidate in two ways:

    * its blocked rail-adjacent Metal2 nodes fall within the candidate's
      min-area growth window (only the candidate's own column), pinning the
      access stub against whatever holds the tracks on its other side;
    * its rail landing lies within metal spacing of an off-track candidate's
      access bridge, so route_nets' bridge_clear filter drops the candidate.

    The growth-window test is deliberately conservative (window overlap, not
    exact strangulation): a false positive only nudges a tap sideways, while
    a false negative stalls the router.

    Args:
        routed_nets: the signal nets that will be routed, ``{name: NetInfo}``.
        placed: ``{name: PlacedInst}`` from :func:`place_rows` (for pin rects).
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

    Nominally every ``cfg.mesh_tap_pitch`` tracks; a nominal column in
    ``avoid`` is nudged to the nearest free column, so no tap blocks a pin
    access that cannot negotiate away (:func:`tap_avoid_columns`). The
    die-edge columns are excluded: the mesh ends stitch into the side
    straps right there, and a tap landing at the edge would sit closer to the
    ring-end via stack than the metal spacing. A tap with no free column in
    reach is dropped -- the strap still stitches at every other tap, while a
    hostile tap column can deadlock the router.

    Args:
        cfg: the routing grid (:class:`GridConfig`).
        xmax: the maximum x track index.
        avoid: column indices no tap may use (:func:`tap_avoid_columns`).

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

    Only the *interior* rails carry mesh straps, so only their surroundings
    are reserved. Two kinds of reservation:

    * At each tap column, the via stack down to the rail occupies the vertical
      layers where they cross the rail track -- and its min-area landings reach
      one track beyond the rail on either side, so those neighbor nodes are
      unusable too (a wire end there would violate metal spacing).
    * The mesh strap is wider than a routing wire, so the horizontal top-metal
      tracks adjacent to a strapped rail sit closer to it than the metal
      spacing -- blocked across the whole die width.

    Metal3 and Metal5 *on* a rail track need no entry here: a layer change is
    never allowed on rail tracks, so the router cannot reach them.

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


def emit_power_mesh(layout, stack, placed, cfg, die_w, taps):
    """Emit a horizontal Metal5 strap over every *interior* power rail,
    stitched down to the rail by via stacks at regular tap columns.

    Together with the side straps (:func:`emit_power_straps`) this forms a
    supply mesh: rail current no longer has to flow the full row length on
    thin Metal1 to reach a side strap, which is what bounds IR drop as blocks
    grow wider. The interior rails are the ones shared between two abutted
    rows -- the highest-current rails -- and the strap sits on the rail line,
    where no signal can route (see :func:`mesh_blocked_nodes`), so the mesh
    costs almost no routing capacity.

    The straps stay strictly within the die: the margins beyond it and the
    strip above the top rail belong to the block's interface (the parent's
    risers to the edge pads run there), and the outermost rails are already
    tied at both ends by the side straps. The mesh reaches those straps
    through the rails themselves.

    Args:
        layout: the mutable :class:`Layout` to emit into.
        stack: the :class:`RoutingStack` mapping routing codes to PDK layers.
        placed: ``{name: PlacedInst}`` from :func:`place_rows`.
        cfg: the routing grid + geometry (:class:`GridConfig`).
        die_w: the die width (nm).
        taps: the tap column indices (:func:`mesh_tap_columns`).
    """
    via_half, half_w, land_half = cfg.via_half, cfg.strap_half_w, cfg.land_half_h
    x_pitch = cfg.x_pitch
    core_top = cfg.n_rows * cfg.row_height

    def via_stack(x, y):
        # Via stack from the Metal1 rail up to the Metal5 strap. The
        # vertical-layer landings (Metal2/Metal4) stand upright, staying
        # within the tap column that mesh_blocked_nodes reserves. The Metal3
        # landing must lie FLAT instead: upright it would reach into the
        # horizontal tracks beside the rail and short any wire crossing the
        # column there.
        cut = Rect4I(x - via_half, y - via_half, x + via_half, y + via_half)
        upright = Rect4I(x - half_w, y - land_half, x + half_w, y + land_half)
        flat = Rect4I(x - land_half, y - half_w, x + land_half, y + half_w)
        layout % LayoutRect(layer=stack.via1, rect=cut)
        layout % LayoutRect(layer=stack.m2, rect=upright)
        layout % LayoutRect(layer=stack.via2, rect=cut)
        layout % LayoutRect(layer=stack.m3, rect=flat)
        layout % LayoutRect(layer=stack.via3, rect=cut)
        layout % LayoutRect(layer=stack.m4, rect=upright)
        layout % LayoutRect(layer=stack.via4, rect=cut)

    for pname in cfg.supply_pin_names:
        for rail_y0, rail_y1 in supply_rails(placed, pname):
            rail_y_center = (rail_y0 + rail_y1) // 2
            if not 0 < rail_y_center < core_top:   # interior rails only
                continue
            layout % LayoutRect(layer=stack.m5, rect=Rect4I(
                0, rail_y_center - cfg.mesh_half_w,
                die_w, rail_y_center + cfg.mesh_half_w))
            for xi in taps:
                via_stack(xi * x_pitch, rail_y_center)


def extend_min_area(result, cfg, xmax, keepout=frozenset()):
    """Post-pass: lengthen any too-short wire so it meets the metal min-area rule.

    A min-width wire must span enough tracks to meet min area and give its end-via
    the required endcap. Each per-net, per-track wire run is extended to at least
    ``cfg.min_area_tracks`` grid steps, growing into free tracks.

    Args:
        result: the routing ``{net: (edges, term_m2)}`` to extend in place.
        cfg: the routing grid + geometry (:class:`GridConfig`).
        xmax: the maximum x track index.
        keepout: nodes no extension may grow into (power-mesh blockages and
            off-track access-bridge shadows).

    Returns:
        The same ``result`` mapping (mutated in place).
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
