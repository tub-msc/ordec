# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
The ORDeC boundary and the flow that runs between its two halves: read a
Schematic into the engine's records, place and route on the grid, write the
result back out as Layout geometry.

Every ORDB access in the package lives here. :func:`extract` is the only code
that reads a Schematic and the ``emit_*`` functions are the only code that
writes a Layout, which is what keeps :mod:`.place` and :mod:`.route` free of the
data model.
"""

from collections import namedtuple
from dataclasses import dataclass, field, replace

from ordec.core import *

from . import place, route
from .route import HORIZ, M1, M2, M3, M4, M5, PinAccessError, VERT


@dataclass(frozen=True)
class GridConfig:
    """Routing grid and emitted-geometry parameters.

        The engine reads every dimension from here, so retargeting a PDK is a new
        profile rather than an edit to the engine. The grid and geometry fields have
        no defaults, since they come from a PDK profile such as
        :func:`ordec.lib.ihp130_pnr.sg13g2_grid`. Only the flow knobs at the bottom
        carry universal defaults. All lengths are in nm.

        Frozen, so a profile is a value the binding can cache and share. The
        floorplan loop derives one variant per attempt with
        ``dataclasses.replace(cfg, n_rows=...)``, and a caller overrides a flow knob
        the same way.
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
    # --- flow knobs, PDK-independent, with universal defaults -----------------
    n_rows: int = 1          # number of abutted (flipped) standard-cell rows
    via_cost: float = 4.0    # A* cost of a layer change (in track units)
    min_area_pass: bool = True
    use_upper: bool = True   # allow routing on Metal4/Metal5 (else Metal2/3 only)
    power_mesh: bool = True  # Metal5 straps over the rails, stitched down to them
    mesh_tap_pitch: int = 8  # track columns between mesh-to-rail via stacks
    # Floorplan: size a die from cell_area / utilization, shaped to the target
    # aspect, then legalize cells into it. Utilization is the area lever and
    # should stay high, since this router runs over the cells and the routing
    # budget is tracks/row * rows, roughly independent of cell density. Aspect
    # is only a soft preference for the row count.
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


@dataclass(frozen=True)
class RoutingStack:
    """Maps the engine's abstract routing stack onto concrete PDK layers.

        The layer counterpart of :class:`GridConfig`. The binding supplies the layer
        objects, so no PDK layer name is baked into the engine. ``m1`` to ``m5`` and
        ``via1`` to ``via4`` mirror the like-named internal codes: a Metal1-only
        pin-access layer, two vertical routing metals (``m2``, ``m4``), two
        horizontal (``m3``, ``m5``), and a via between each pair.
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


@dataclass(frozen=True)
class PnrTarget:
    """Everything a PDK must supply for the engine to lay a cell out.

        The four inputs always come from the same binding module, so they travel as
        one value rather than a calling convention.

        Args:
            stack: the :class:`RoutingStack` for this PDK's layers.
            grid: the routing grid + emitted geometry (:class:`GridConfig`).
            pin_rects: callable ``cell_name -> {pin: [(x0, y0, x1, y1), ...]}``
                giving a leaf cell's per-pin Metal1 rectangles, in nm.
            is_leaf: callable ``cell -> bool``, true for a routing leaf placed
                as-is, false for a composite the engine flattens.
        """
    stack: RoutingStack
    grid: GridConfig
    pin_rects: object
    is_leaf: object


@dataclass
class NetInfo:
    """A net to route: its terminals (instance pin connections) and, if it is a
    top-level port, the symbol Pin it exposes."""
    name: str
    terminals: list = field(default_factory=list)  # (inst_name, pin_name)
    port_pin: object = None   # cell symbol Pin if this net is a top-level port


# One leaf cell before placement: the Cell, its Metal1 pin rects, and its width.
LeafCell = namedtuple('LeafCell', 'cell pins width')


def leaf_name(node):
    """Return the last component of an ORDB node's path.

    The engine keys everything on flat, local names (``a`` rather than
    ``top.a``), so every path that crosses into it comes through here.

    Args:
        node: a named ORDB node (a Net, Pin or SchemInstance).

    Returns:
        str: its name within its parent.
    """
    return node.full_path_str().split('.')[-1]


def pin_nets(inst):
    """Map each pin of one instance to the net it connects to.

    Args:
        inst: the SchemInstance whose connections are read (via the
            ``SchemInstanceConn.ref_idx`` index, not a full-schematic scan).

    Returns:
        ``{pin_name: net_name}`` for ``inst``.
    """
    return {leaf_name(conn.there): leaf_name(conn.here)
        for conn in inst.conns()}



def flatten_schematic(cell, is_leaf):
    """Flatten a hierarchical schematic to its foundry leaf instances.

        Sub-cells for which ``is_leaf`` is true are leaves. Any other instance is
        expanded into its own schematic, with internal nets uniquified by an
        instance prefix and port nets mapped to the parent's nets.

        Args:
            cell: the top cell whose ``schematic`` view is flattened.
            is_leaf: predicate ``cell -> bool``, true for a routing leaf cell.

        Returns:
            ``(leaf_insts, net_terminals)``, mapping a flat instance name to its
            leaf Cell and a net name to its ``(flat_inst_name, pin_name)``
            terminals.
        """
    leaf_insts = {}
    net_terminals = {}

    def recurse(sch, prefix, port_to_net):
        def canon(net_name):
            if net_name in port_to_net:
                return port_to_net[net_name]
            return prefix + net_name if prefix else net_name
        for inst in sch.all(SchemInstance):
            iname = prefix + leaf_name(inst)
            subcell = inst.symbol.cell
            pin_to_net = {pin: canon(net)
                for pin, net in pin_nets(inst).items()}
            if is_leaf(subcell):
                leaf_insts[iname] = subcell
                for pin, net in pin_to_net.items():
                    net_terminals.setdefault(net, []).append((iname, pin))
            else:
                # Check the class rather than the instance, so a schematic
                # viewgen that exists but raises is not mistaken for a
                # missing one.
                if not hasattr(type(subcell), 'schematic'):
                    raise ValueError(
                        f"instance {iname!r} is a {type(subcell).__name__}, "
                        "which is neither a routing leaf nor a composite with "
                        "a schematic to flatten. The engine places standard "
                        "cells, so a device-level cell has to be laid out by "
                        "hand and composed with the placed block at the "
                        "parent level")
                recurse(subcell.schematic, iname + '/', pin_to_net)

    recurse(cell.schematic, '', {})
    return leaf_insts, net_terminals



def extract(cell, pin_rects, is_leaf, cfg):
    """Build the placement and net data for a cell's flattened schematic.

        Args:
            cell: the top cell to lay out.
            pin_rects: the PDK's pin-rectangle hook (see :class:`PnrTarget`).
            is_leaf: the PDK's routing-leaf predicate (see :class:`PnrTarget`).
            cfg: the :class:`GridConfig`, for the supply pin naming.

        Returns:
            ``(cells, nets)``, mapping each leaf instance name to a
            :class:`LeafCell` and each net name to a :class:`NetInfo`.
        """
    leaf_insts, net_terminals = flatten_schematic(cell, is_leaf)

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
            net_name = leaf_name(net)
            if net_name in nets:
                nets[net_name].port_pin = net.pin

    return cells, nets


# --- geometry emission + top-level orchestration --------------------------

def emit_net_direct(layout, stack, edges, term_m2, cfg,
        term_via=None, term_land=None):
    """Emit one routed net's geometry directly with concrete coordinates.

        No constraint solver is used, since ORDeC's general solver is fast per cell
        but takes minutes for a few-hundred-net block. Wire runs become
        Metal2/3/4/5 paths and each layer change is a via cut. The overlapping wires
        provide the via landings, and the router's via-access pass keeps every run
        long enough to meet min area and endcap.

        Args:
            layout: the mutable :class:`Layout` to emit into.
            stack: the :class:`RoutingStack` for this PDK's layers.
            edges: the net's routed edges, each a pair of grid nodes.
            term_m2: the net's Via1 access nodes, its terminal landings on Metal2.
            cfg: the routing grid + DRC geometry (:class:`GridConfig`).
            term_via: this net's ``{node: (via_x, via_y)}`` overrides, moving an
                off-track terminal's Via1 onto the pin. The emitter jogs it back to
                the track.
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
        # Add *both* endpoints of every edge, via edges included, so a layer a
        # net only passes through (a transit landing) still gets metal emitted.
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
    # min-area landing rect instead. Multi-node runs already meet min area via
    # the grow and extend_min_area passes.
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
    # dict.fromkeys: two terminals of one net may share an access node, so its
    # via stack is emitted once.
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



def viewgen_layout_root(cell):
    """Return the Layout root of an enclosing ``viewgen layout`` for ``cell``.

        An ORD viewgen body populates a root the view context owns rather than
        returning one, so the engine emits into that root. :class:`SRouter
        <ordec.layout.SRouter>` picks up its layout the same way.

        Args:
            cell: the cell being laid out.

        Returns:
            The view context's Layout root, or None when there is no enclosing
            layout viewgen, including when the active viewgen belongs to another
            cell. Emitting into that parent's root would corrupt it.
        """
    from ordec.ord.context import view_context

    view_ctx = view_context()
    if view_ctx is None:
        return None
    root = view_ctx.root
    if isinstance(root, Layout) and root.cell == cell:
        return root
    return None



@dataclass(frozen=True)
class PnrResult:
    """Everything one place-and-route run decided, not just the geometry.

        :func:`place_and_route` hands back the layout alone, which is all a design
        needs. A test or a report wants the decisions behind it.

        Args:
            layout: the emitted :class:`Layout`, frozen as :func:`run_pnr` describes.
            cfg: the :class:`GridConfig` variant the floorplan settled on, with the
                ``n_rows`` that finally routed.
            placed: ``{name: PlacedInst}``, every leaf cell's row, position,
                orientation and absolute pin rectangles.
            routing: the :class:`~.route.RoutingResult` for the signal nets.
            die_w: the die width in nm, which the rails are padded flush to.
            taps: the power-mesh tap columns, empty when no mesh was emitted.
        """
    layout: object
    cfg: GridConfig
    placed: dict
    routing: object
    die_w: int
    taps: tuple


def run_pnr(cell, target, layout=None):
    """Place + route a cell whose schematic instantiates Metal1-only leaf cells.

        Every PDK-specific input arrives in ``target``, so no layer, pitch or DRC
        dimension is baked into this module.

        Args:
            cell: the cell to lay out. Its schematic is flattened to leaf cells.
            target: the :class:`PnrTarget` for this PDK, e.g.
                :func:`ordec.lib.ihp130_pnr.sg13g2_target`.
            layout: the :class:`Layout` to build into. Defaults to the enclosing
                ``viewgen layout`` root, or to a fresh Layout when there is none.

        Returns:
            The :class:`PnrResult`. Its layout is frozen when this call created it,
            and the caller's still-mutable root otherwise, which the view context
            freezes.

        Raises:
            PinAccessError: a pin is unreachable on the grid. This is permanent, so
                no retry is attempted.
            ValueError: the netlist breaks a structural assumption, either more than
                one net on a supply pin or a supply net under the wrong name.
            RuntimeError: the routing did not converge at the largest floorplan
                tried.
        """
    stack, cfg = target.stack, target.grid
    layout = layout or viewgen_layout_root(cell)
    if layout is not None:
        check_layout_empty(layout, cell)
        check_layout_layers(layout, stack, cell)
    cells, nets = extract(cell, target.pin_rects, target.is_leaf, cfg)

    # Rail abutment shorts every VDD rail in the block together (likewise VSS),
    # so the engine supports exactly one net per supply pin. It must also carry
    # the profile's conventional name, since supply handling is keyed off it.
    # Anything else would produce a layout that silently merges nets.
    for pname, expected in ((cfg.vdd_pin, cfg.vdd_net), (cfg.vss_pin, cfg.vss_net)):
        domains = sorted({net_name for net_name, net in nets.items()
            if any(p == pname for _i, p in net.terminals)})
        if len(domains) > 1:
            raise ValueError(f"nets {domains} all drive {pname} pins. Rail "
                "abutment would short them together, and the engine supports "
                "only one supply domain")
        if domains and domains[0] != expected:
            raise ValueError(f"the net on the {pname} pins is named "
                f"{domains[0]!r}, but the engine requires {expected!r}")

    signal_nets = {net_name: net for net_name, net in nets.items()
        if len(net.terminals) >= 2 and net_name not in cfg.supply_net_names}
    # A signal pin tied to a supply (e.g. an inactive preset/clear input held
    # high) shows up as an extra terminal on the supply net. The rails carry
    # power by abutment, not routing, so connect each such pin to its own cell's
    # rail with a short routed net, otherwise the input is left floating.
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
    # is not otherwise routed. Add it so it gets a Metal4 escape too, otherwise
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
    # fit and the die stays tight. Utilization sets the area and the aspect sets
    # the shape.
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
        cfg = replace(cfg, n_rows=nrows)
        order = place.order_cells_sa(cells, nets, cfg)
        placed, packed_w = place.place_rows(cells, order, cfg)
        # Die width: the floorplan target, the widest packed row, or (like a
        # pad-limited chip) the top-edge port pads, one escape column each.
        die_w = -(-max(round(core_area / (nrows * row_height)), packed_w,
            (escape_cols - 1) * x_pitch) // x_pitch) * x_pitch
        xmax = die_w // x_pitch
        # The power mesh needs >= 2 rails per supply to stitch, like the side
        # straps. A single-row block keeps its one shared rail per supply.
        # Its tap columns are chosen around the pin accesses this placement
        # forces: a tap that invalidates a terminal's every access candidate
        # deadlocks the rip-up loop (the terminal cannot negotiate away).
        mesh = cfg.power_mesh and nrows >= 2
        if mesh:
            taps = route.mesh_tap_columns(cfg, xmax,
                route.tap_avoid_columns(signal_nets, placed, cfg))
            blocked = route.mesh_blocked_nodes(cfg, xmax, taps)
        else:
            taps, blocked = (), frozenset()
        try:
            routing = route.route_nets(
                signal_nets, placed, cfg, xmax, port_nets, blocked, taps)
            break
        except PinAccessError:
            raise   # permanent: more rows cannot make a pin reachable
        except RuntimeError:
            if i == 4:
                raise
    if cfg.min_area_pass:
        route.extend_min_area(routing.nets, cfg, xmax,
            blocked | routing.reserved)

    if layout is None:
        layout = Layout(ref_layers=stack.layer_set, cell=cell, symbol=cell.symbol)
        own_layout = True
    else:
        own_layout = False
    for name, inst in placed.items():
        setattr(layout, name, LayoutInstance(ref=inst.cell.layout,
            pos=Vec2I(*inst.pos), orientation=inst.orient))

    # Emit routing directly with concrete coordinates (no constraint solver, so
    # it scales to hundreds of nets).
    for net_name, (edges, term_m2) in routing.nets.items():
        emit_net_direct(layout, stack, edges, term_m2, cfg,
            routing.term_via.get(net_name), routing.term_land.get(net_name))

    # Pad every row's rail out to the die width so the block is a flush rectangle
    # (like filler cells) and the right power strap ties into every rail.
    pad_rails(layout, stack, placed, die_w, cfg.supply_pin_names)
    if cfg.n_rows >= 2:
        emit_power_straps(layout, stack, placed, cfg, die_w)
    if mesh:
        emit_power_mesh(layout, stack, placed, cfg, die_w, taps)

    emit_ports(layout, stack, nets, placed, routing, cfg)
    return PnrResult(layout=layout.freeze() if own_layout else layout, cfg=cfg,
        placed=placed, routing=routing, die_w=die_w, taps=taps)


def check_layout_empty(layout, cell):
    """Refuse to emit into a layout that already holds geometry.

    The router knows nothing about shapes it did not place, so anything
    already there is merged over without a spacing violation to show for it.
    DRC stays clean and only LVS catches the short, which is the worst shape a
    failure can take. Compose hand geometry with the placed block at the
    parent level instead.

    Args:
        layout: the :class:`Layout` about to be emitted into.
        cell: the cell being laid out, for the message.

    Raises:
        ValueError: the layout holds any node beyond its root.
    """
    existing = len(list(layout.subgraph.nodes)) - 1   # the root itself
    if existing:
        raise ValueError(
            f"the layout of {cell} already holds {existing} node(s). "
            "place_and_route emits into the whole layout and cannot see "
            "geometry it did not place, so hand geometry belongs in a "
            "separate cell composed with the placed block at the parent "
            "level. Calling place_and_route twice fails here too")


def check_layout_layers(layout, stack, cell):
    """Bind the layout to this target's layer set, or reject a foreign one.

    A viewgen root arrives without layers, since the view context does not know
    the PDK. A root that already carries a different stack would take this
    engine's geometry on layers from another one.

    Args:
        layout: the :class:`Layout` about to be emitted into.
        stack: the :class:`RoutingStack` whose layers the engine emits on.
        cell: the cell being laid out, for the message.

    Raises:
        ValueError: the layout is bound to a different layer set.
    """
    if layout.ref_layers is None:
        layout.ref_layers = stack.layer_set
    elif layout.ref_layers != stack.layer_set:
        raise ValueError(
            f"the layout of {cell} is bound to a different layer set than "
            "the place-and-route target emits on")


def place_and_route(cell, target, layout=None):
    """Place + route ``cell``, returning its DRC/LVS-clean :class:`Layout`.

        The design-facing entry point, :func:`run_pnr` without the flow's internals.
        Inside a ``viewgen layout`` body it needs no return statement, since it
        emits into the root the view context owns::

            viewgen layout -> Layout:
                place_and_route(self, sg13g2_target())

        Args:
            cell: the cell to lay out.
            target: the :class:`PnrTarget` for this PDK.
            layout: the :class:`Layout` to build into. Defaults to the enclosing
                viewgen's root, or to a fresh Layout when there is none.

        Returns:
            The :class:`Layout`, frozen when this call created it and the caller's
            still-mutable root otherwise.
        """
    return run_pnr(cell, target, layout).layout


def emit_ports(layout, stack, nets, placed, routing, cfg):
    """Expose every top-level port of the block as a pin on emitted geometry.

    Args:
        layout: the mutable :class:`Layout` to emit into.
        stack: the :class:`~.model.RoutingStack` for this PDK.
        nets: ``{name: NetInfo}`` for the whole block (ports carry a pin).
        placed: ``{name: PlacedInst}``, for the supply rails.
        routing: the :class:`~.route.RoutingResult`, for the signal escapes.
        cfg: the routing grid + emitted geometry (:class:`GridConfig`).
    """
    # A signal port was escaped to the TOP edge (route_nets): expose its
    # pin on a Metal4 pad straddling the top rail, up in the channel above the
    # block, so the parent lands there without ever routing over the interior.
    # (Fallback: an interior Metal4 pad if the escape could not reach the edge.)
    # vdd/vss carry by rail abutment, so their port stays a Metal1 rail handle.
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    top_abs = cfg.n_rows * cfg.row_height        # absolute y of the top rail
    for net_name, net in nets.items():
        if net.port_pin is None:
            continue
        if net_name in routing.nets:             # signal port
            escape_x = routing.port_escape.get(net_name)
            if escape_x is not None:                   # top-edge pad, above the rows
                track_x = escape_x * x_pitch
                port_rect = layout % LayoutRect(layer=stack.m4, rect=Rect4I(
                    track_x - cfg.strap_half_w, top_abs - cfg.port_pad_below,
                    track_x + cfg.strap_half_w, top_abs + cfg.port_pad_above))
            else:                                # interior fallback pad
                xi, yi, _ = routing.nets[net_name][1][0]
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
                # that one rail already ties the whole supply, so expose it
                # directly.
                port_rect = layout % LayoutRect(layer=stack.m1, rect=rail)
        port_rect.create_pin(net.port_pin)


def largest_rect(rects):
    """Return the largest-area rect among ``rects``.

    Args:
        rects: ``(x0, y0, x1, y1)`` rectangles (a pin may have several).

    Returns:
        The biggest one, which is a pin's rail or body rect.
    """
    return max(rects, key=lambda r: r.width * r.height)



def supply_rails(placed, pname):
    """Distinct rail spans for one supply, sorted bottom-to-top.

        Rails are deduplicated where the boustrophedon shares one between adjacent
        rows. A side strap is emitted only when there are two or more, since a
        single shared rail already ties the whole supply.

        Args:
            placed: ``{name: PlacedInst}`` from :func:`place_rows`.
            pname: the supply pin name, e.g. ``'VDD'``.

        Returns:
            The sorted distinct ``(y0, y1)`` rail spans, in nm.
        """
    rails = set()
    for inst in placed.values():
        if pname in inst.pins:
            rail = largest_rect(inst.pins[pname])
            rails.add((rail.ly, rail.uy))
    return sorted(rails)



def pad_rails(layout, stack, placed, die_w, supply_pins):
    """Extend every row's supply rail rightward to a common die-width edge.

        Like filler cells, this makes the block a flush rectangle and lets the
        right-side power strap tap every row. Rows come out at slightly different
        packed widths, so without this the shorter rows would not reach the strap.

        Args:
            layout: the mutable :class:`Layout` to emit into.
            stack: the :class:`RoutingStack` for this PDK's layers.
            placed: ``{name: PlacedInst}`` from :func:`place_rows`.
            die_w: the die width to pad each rail out to, in nm.
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
    """Form a power ring per supply from a vertical Metal2 strap on each side.

        Each strap sits in the empty margin beside the cell area and taps every rail
        through a short Metal1 extension and a Via1. The boustrophedon shares a rail
        between adjacent rows, so the inner rails would otherwise float. The ring
        ties them and halves rail IR drop. Skipped for a supply with one shared
        rail, which already ties itself.

        Args:
            layout: the mutable :class:`Layout` to emit into.
            stack: the :class:`RoutingStack` for this PDK's layers.
            placed: ``{name: PlacedInst}`` from :func:`place_rows`.
            cfg: the routing grid + geometry (:class:`GridConfig`).
            die_w: the die width in nm. The right strap mirrors to it.
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



def emit_power_mesh(layout, stack, placed, cfg, die_w, taps):
    """Emit a Metal5 strap over every interior rail, stitched down at the taps.

        With the side straps (:func:`emit_power_straps`) this forms a supply mesh.
        Rail current no longer flows the full row length on thin Metal1 to reach a
        side strap, which is what bounds IR drop as blocks grow wider. Interior
        rails are shared between two abutted rows and carry the most current. The
        strap sits on the rail line, where no signal can route (see
        :func:`mesh_blocked_nodes`), so the mesh costs almost no routing capacity.

        The straps stay strictly within the die. The margins beyond it and the strip
        above the top rail belong to the block's interface, and the outermost rails
        are already tied at both ends by the side straps, which the mesh reaches
        through the rails themselves.

        Args:
            layout: the mutable :class:`Layout` to emit into.
            stack: the :class:`RoutingStack` for this PDK's layers.
            placed: ``{name: PlacedInst}`` from :func:`place_rows`.
            cfg: the routing grid + geometry (:class:`GridConfig`).
            die_w: the die width in nm.
            taps: the tap column indices (:func:`mesh_tap_columns`).
        """
    via_half, half_w, land_half = cfg.via_half, cfg.strap_half_w, cfg.land_half_h
    x_pitch = cfg.x_pitch
    core_top = cfg.n_rows * cfg.row_height

    def via_stack(x, y):
        # Via stack from the Metal1 rail up to the Metal5 strap. The
        # vertical-layer landings (Metal2, Metal4) stand upright, within the tap
        # column mesh_blocked_nodes reserves. The Metal3 landing must lie flat,
        # since upright it would reach into the horizontal tracks beside the
        # rail and short any wire crossing the column.
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
