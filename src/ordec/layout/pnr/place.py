# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Row-based standard-cell placement: order the cells to minimise wirelength, then
fold that order into abutted, alternately mirrored rows.

Works on grid coordinates and pin rectangles only. No Schematic and no Layout
reach this module, so a placement can be built and checked from plain values.
"""

from collections import namedtuple
import math
import random

from ordec.core import *


# One cell's slot in the row fold, the placement decision place_rows makes.
# The flow applies it to the layout's LayoutInstance, which is the engine's
# placement representation.
RowSlot = namedtuple('RowSlot', 'pos orient row')


def order_cells(cells, nets, supply_nets=(), iters=30):
    """Order the cells by iterated barycenter placement.

    Each pass moves every cell toward the mean position of the cells it shares a
    net with, then re-ranks. Short nets are what make a single-row channel
    routable.

    Args:
        cells: ``{name: LeafCell}`` for the cells to order.
        nets: ``{name: NetInfo}`` giving the connectivity.
        supply_nets: power net names to ignore, since they touch every cell.
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
    # once) rather than a membership scan of every net per cell. That costs
    # O(sum of net degrees) instead of O(cells * nets * degree).
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
    """Fold the 1-D cell order into ``cfg.n_rows`` rows of minimal max width.

    Both :func:`cell_centers` (scoring an order) and :func:`place_rows`
    (building the placement) fold here, so the annealer optimises exactly the
    geometry that gets built.

    Args:
        cells: ``{name: LeafCell}``, for the cell widths.
        order: the 1-D cell order to fold.
        cfg: the routing/floorplan :class:`GridConfig`.

    Returns:
        The rows as lists of cell names, padded with empty rows up to
        ``cfg.n_rows``. Odd-row mirroring is the caller's concern.
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
    """Estimate each cell's center for a folded order, to score it cheaply.

    Reuses the fold *and* the odd-row reversal of :func:`place_rows`, since a
    mirrored row is placed right-to-left. Without mirroring the scored x too,
    the annealer would mis-score every net touching an odd row.

    Args:
        cells: ``{name: LeafCell}``, for the cell widths.
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
    """Order cells by wirelength using simulated annealing.

    Starts from the barycenter order (:func:`order_cells`) and perturbs the
    sequence to minimise half-perimeter wirelength, weighting vertical span 2x
    since a net crossing rows is far harder to route. A single row, or a netlist
    with no multi-terminal signal nets, returns the barycenter order directly.

    A swap is scored incrementally: it exchanges the two cells' positions and
    re-derives only the bboxes of the nets touching them, so a move costs
    O(degree) rather than a full fold. Unequal cell widths make the slot
    positions drift from the true fold, so every ``resync`` accepted moves the
    fold and the bboxes are recomputed exactly.

    Args:
        cells: ``{name: LeafCell}`` for the cells to order.
        nets: ``{name: NetInfo}`` giving the connectivity.
        cfg: the routing/floorplan :class:`GridConfig`, whose ``n_rows`` sets
            the fold.
        iters: number of annealing moves.
        seed: RNG seed, fixed so the result is deterministic.
        resync: accepted moves between exact re-folds, bounding the drift.

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
        # One member of net ni moves off box to new_pos. A growing move only
        # extends the box. Only a cell leaving the boundary forces an
        # O(degree) rescan.
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
        # swap, so its bbox cannot change and only the one-sided nets rescore.
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

    This is the classic "split array largest sum", solved by binary search on
    the width. Balancing this way stops one row from blowing up the die width,
    where a fixed per-row target under-fills and dumps the leftover into the
    last row.

    Args:
        widths: the cell widths in placement order, in nm.
        nrows: the maximum number of rows.

    Returns:
        The minimised maximum row width, in nm.
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



def transform_pins(local_pins, pos, orient):
    """Transform a leaf's local pin rects into die coordinates.

    The same placement transform a LayoutInstance applies to its ref: R0
    shifts by ``pos``, MX shifts x and flips y about the position's y. The
    flow derives the pin geometry from the placed LayoutInstances with this,
    so the layout is the sole holder of the placement.

    Args:
        local_pins: ``{pin: [Rect4I]}`` in cell-local coordinates.
        pos: the instance position ``(x, y)`` in nm.
        orient: the instance orientation, D4.R0 or D4.MX.

    Returns:
        ``{pin: [Rect4I]}`` in die coordinates.
    """
    x, y = pos
    if orient == D4.MX:
        return {pin: [Rect4I(r.lx + x, y - r.uy, r.ux + x, y - r.ly)
            for r in rects] for pin, rects in local_pins.items()}
    return {pin: [Rect4I(r.lx + x, r.ly + y, r.ux + x, r.uy + y)
        for r in rects] for pin, rects in local_pins.items()}


def place_rows(cells, order, cfg):
    """Fold the 1-D cell order into ``cfg.n_rows`` abutted standard-cell rows.

    Odd rows are mirrored (D4.MX) and reversed, a boustrophedon, so power rails
    abut between rows and the dataflow stays adjacent across the turn. That is
    how standard-cell rows are built.

    Args:
        cells: ``{name: LeafCell}`` for the cells to place.
        order: the wirelength-ordered names from :func:`order_cells_sa`.
        cfg: the routing/floorplan :class:`GridConfig`.

    Returns:
        ``(slots, max_width)``, mapping each name to a :class:`RowSlot` and
        giving the widest packed row in nm.
    """
    row_height = cfg.row_height

    # Balanced fold: pack greedily to the minimum max-row-width (the optimal
    # contiguous partition), so the rows come out even.
    rows = fold_rows(cells, order, cfg)

    slots = {}
    max_w = 0
    for row, row_cells in enumerate(rows):
        mirror = (row % 2 == 1)
        if mirror:
            row_cells = row_cells[::-1]
        row_y = (row + 1) * row_height if mirror else row * row_height
        orient = D4.MX if mirror else D4.R0
        x = 0
        for name in row_cells:
            slots[name] = RowSlot((x, row_y), orient, row)
            x += cells[name].width
        max_w = max(max_w, x)
    return slots, max_w
