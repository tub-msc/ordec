# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
The ORDeC boundary and the flow that runs between its two halves: read a
Schematic into the engine's records, place and route on the grid, write the
result back out as Layout geometry.

Every ORDB access in the package lives here. :func:`extract` is the only code
that reads a Schematic, and the Layout is written only here: the placed
LayoutInstances, which are the engine's placement representation, and the
``emit_*`` geometry. :mod:`.place` and :mod:`.route` stay free of the data
model.
"""

from collections import namedtuple
from dataclasses import dataclass, field, replace

from public import public

from ordec.core import *
from ordec.extlibrary import ExtLibraryCell

from . import place, route
from .route import HORIZ, M1, M2, M3, M4, M5, PinAccessError, VERT


@public
@dataclass(frozen=True)
class GridConfig:
    """Routing grid and emitted-geometry parameters.

    The engine reads every dimension from here, so retargeting a PDK is a new
    profile rather than an edit to the engine. The grid and geometry fields have
    no defaults, since they come from a PDK profile such as
    :data:`ordec.lib.ihp130.grid`. Only the flow knobs at the bottom
    carry universal defaults. All lengths are in nm.

    Frozen, so a profile is a constant the binding defines once and shares. The
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
    port_pad_inner: int      # port-pad extent from its edge rail into the block
    port_pad_outer: int      # port-pad extent from its edge rail out of the die
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


# The engine's routing codes bound to concrete PDK layers: the pin-access
# metal (M1), two vertical routing metals (m2, m4), two horizontal ones
# (m3, m5), the via between each pair, and the full layer set that becomes
# Layout.ref_layers. Derived from a RoutingSpec by stack_from_spec, never
# hand-built.
StackLayers = namedtuple('StackLayers',
    'layer_set m1 m2 m3 m4 m5 via1 via2 via3 via4')


def stack_from_spec(routing_spec):
    """Bind the engine's routing codes to a :class:`RoutingSpec`'s layers.

    The PDK's RoutingSpec (:mod:`ordec.core.schema`) is the single source of
    truth for the layer stack: its ``route_id`` order alternates metals (with
    ``route_wire_width`` set) and vias. The engine routes a fixed five-metal
    window, so it takes the nine layers with the lowest route_ids, the
    pin-access metal first. Layers above the window (sg13g2's top metals)
    are never touched, which leaves them to the assembly above the block.

    Args:
        routing_spec: the :class:`RoutingSpec` naming the PDK's layer stack.

    Returns:
        The :class:`StackLayers` the emission code works with.

    Raises:
        ValueError: the spec holds fewer than nine layers, or its window does
            not alternate metal and via.
    """
    rsls = sorted(routing_spec.all(RoutingSpecLayer), key=lambda l: l.route_id)
    if len(rsls) < 9:
        raise ValueError(
            f"the routing spec holds {len(rsls)} layers, but the engine "
            "routes a five-metal window and needs nine: the pin-access "
            "metal, four routing metals and the four vias between them")
    for i, rsl in enumerate(rsls[:9]):
        if (rsl.route_wire_width is not None) != (i % 2 == 0):
            raise ValueError(
                f"routing spec layer with route_id {rsl.route_id} breaks the "
                "metal/via alternation the engine's window requires (metals "
                "carry a route_wire_width, vias do not)")
    layer = [rsl.layer for rsl in rsls[:9]]
    return StackLayers(layer_set=routing_spec.ref_layers,
        m1=layer[0], m2=layer[2], m3=layer[4], m4=layer[6], m5=layer[8],
        via1=layer[1], via2=layer[3], via3=layer[5], via4=layer[7])


class PinRects(dict):
    """``{macro: {pin: [(x0, y0, x1, y1), ...]}}`` read from one LEF file.

    A macro whose pin or obstruction geometry leaves the pin layer is left out
    rather than mapped to its pin-layer rects alone, since the engine routes
    the metals above the leaf cells and would silently short or violate that
    geometry. The rejection has to wait until the macro is looked up: a library
    LEF holds macros a given design never places, so reading the file must not
    fail over one of them.
    """
    def __init__(self, rects, off_layer, pin_layer):
        super().__init__(rects)
        self.off_layer = off_layer   # {macro: [layer, ...]} of the rejects
        self.pin_layer = pin_layer

    def __missing__(self, macro):
        if macro not in self.off_layer:
            raise KeyError(macro)
        raise ValueError(
            f"{macro}: LEF pin/obstruction geometry on "
            f"{self.off_layer[macro]}. The P&R engine requires "
            f"{self.pin_layer}-only leaf cells, since it routes on the "
            "metals above them")


@public
def lef_pin_rects(lef_path, pin_layer: str) -> dict[str, dict]:
    """Read the per-pin pin-layer rectangles of every macro in a LEF file.

    This is the ``pin_rects`` input :func:`place_and_route` takes. The LEF
    rectangles are clean, per-pin and non-overlapping, with the foundry pin
    names kept as-is, so the router can pick a via-access point that lands on
    exactly the intended pin.

    Args:
        lef_path: the library LEF holding the macros, e.g.
            ``ordec.lib.ihp130.pdk().stdcell_lef``.
        pin_layer (str): LEF name of the layer the engine accesses pins on,
            e.g. ``Metal1``.

    Returns:
        PinRects: ``{macro: {PIN: [(x0, y0, x1, y1), ...]}}`` in nm, holding
        every macro the engine can place. A macro with geometry off
        ``pin_layer`` is rejected when it is looked up.
    """
    import sc_leflib

    rects = {}
    off_layer = {}
    for macro_name, macro in sc_leflib.parse(str(lef_path))["macros"].items():
        macro_rects = {}
        off = set()   # layers other than pin_layer in the PIN or OBS geometry
        for pin, pin_data in macro["pins"].items():
            macro_rects[pin] = []
            for port in pin_data["ports"]:
                for geom in port["layer_geometries"]:
                    if geom["layer"] != pin_layer:
                        off.add(geom["layer"])
                        continue
                    for shape in geom["shapes"]:
                        # LEF also allows POLYGON here. The sg13g2 pins are all
                        # rectangles, and a polygon pin would need a polygon-exact
                        # via-access engine anyway.
                        if "rect" not in shape:
                            continue
                        x0, y0, x1, y1 = (round(v * 1000) for v in shape["rect"])
                        macro_rects[pin].append((x0, y0, x1, y1))
        for port in macro.get("obs") or []:
            for geom in port:
                if geom["layer"] != pin_layer:
                    off.add(geom["layer"])
        if off:
            off_layer[macro_name] = sorted(off)
        else:
            rects[macro_name] = macro_rects
    return PinRects(rects, off_layer, pin_layer)


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


@public
def is_extlibrary_leaf(cell):
    """The default routing-leaf test: an external-library cell is placed as-is.

    An :class:`~ordec.extlibrary.ExtLibraryCell`'s schematic is transistor
    level, which the engine must never flatten to, while an ORDeC-authored
    composite is exactly what it flattens.

    Args:
        cell: the cell to test.

    Returns:
        bool: true if the cell comes from an ExtLibrary.
    """
    return isinstance(cell, ExtLibraryCell)


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



def flatten_schematic(schematic, is_leaf):
    """Flatten a hierarchical schematic to its foundry leaf instances.

    Sub-cells for which ``is_leaf`` is true are leaves. Any other instance is
    expanded into its own schematic, with internal nets uniquified by an
    instance prefix and port nets mapped to the parent's nets.

    Args:
        schematic: the Schematic to flatten.
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

    recurse(schematic, '', {})
    return leaf_insts, net_terminals



def extract(schematic, pin_rects, is_leaf, cfg):
    """Build the placement and net data for a flattened schematic.

    Args:
        schematic: the Schematic to lay out.
        pin_rects: the PDK's pin-rectangle lookup (see :func:`place_and_route`).
        is_leaf: the PDK's routing-leaf predicate (see :func:`place_and_route`).
        cfg: the :class:`GridConfig`, for the supply pin naming.

    Returns:
        ``(cells, nets)``, mapping each leaf instance name to a
        :class:`LeafCell` and each net name to a :class:`NetInfo`.
    """
    leaf_insts, net_terminals = flatten_schematic(schematic, is_leaf)

    cells = {}
    for name, leaf in leaf_insts.items():
        # Wrap the lookup's raw nm tuples as Rect4I, so the rest of the engine
        # works with named geometry (rect.lx / .cx / .width, vertex-in-rect) rather
        # than positional indexing.
        rects = {pin: [Rect4I(*r) for r in raw]
            for pin, raw in pin_rects[leaf.name].items()}
        # Cell pitch = power-rail width (the rail rect spans the whole cell).
        width = max(r.width for r in rects[cfg.vdd_pin])
        cells[name] = LeafCell(leaf, rects, width)

    nets = {net_name: NetInfo(net_name, list(terms))
        for net_name, terms in net_terminals.items()}

    # Mark top-level port nets (Net.pin references a symbol Pin).
    for net in schematic.all(Net):
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
        stack: the :class:`StackLayers` for this PDK's layers.
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



@public
@dataclass(frozen=True)
class PnrResult:
    """Everything one place-and-route run decided, beyond the geometry.

    The geometry itself lands in the caller's layout. A test or a report wants
    the decisions behind it.

    Args:
        cfg: the :class:`GridConfig` variant the floorplan settled on, with the
            ``n_rows`` that finally routed.
        pins: ``{inst: {pin: [Rect4I]}}``, the die-coordinate pin rectangles
            derived from the placed instances. The placement itself lives on
            the layout's LayoutInstances.
        routing: the :class:`~.route.RoutingResult` for the signal nets.
        die_w: the die width in nm, which the rails are padded flush to.
        taps: the power-mesh tap columns, empty when no mesh was emitted.
    """
    cfg: GridConfig
    pins: dict
    routing: object
    die_w: int
    taps: tuple


@public
def place_and_route(schematic, layout, *, grid, routing_spec, pin_rects,
        is_leaf=is_extlibrary_leaf, port_edges=None):
    """Place + route a schematic of Metal1-only leaf cells into ``layout``.

    The caller owns both sides of the boundary: ``schematic`` is read,
    ``layout`` is written and never frozen here. Every PDK-specific input is an
    explicit keyword parameter, so no layer, pitch or DRC dimension is baked
    into this module. The layout's LayoutInstances are the engine's placement
    representation: created once up front, their positions updated on every
    floorplan attempt, with the pin geometry the router works on derived from them.

    layout::

        viewgen layout(self) -> Layout:
            place_and_route(self.schematic, ., grid=ihp130.grid,
                routing_spec=ihp130.SG13G2().default_routing_spec,
                pin_rects=lef_pin_rects(ihp130.pdk().stdcell_lef, "Metal1"))

    Args:
        schematic: the :class:`Schematic` to lay out, flattened to leaf cells.
        layout: the mutable, empty :class:`Layout` the geometry is emitted
            into. Freezing it is the caller's (or the viewgen's) job.
        grid: the routing grid + emitted geometry (:class:`GridConfig`), e.g.
            :data:`ordec.lib.ihp130.grid`.
        routing_spec: the PDK's :class:`RoutingSpec`. The engine binds its
            routing codes to the spec's nine lowest ``route_id`` layers (see
            ``stack_from_spec``) and emits on those.
        pin_rects: ``{cell_name: {pin: [(x0, y0, x1, y1), ...]}}`` giving each
            leaf cell's per-pin Metal1 rectangles, in nm, e.g. from
            :func:`lef_pin_rects`.
        is_leaf: callable ``cell -> bool``, true for a routing leaf placed
            as-is, false for a composite the engine flattens. Defaults to
            :func:`is_extlibrary_leaf`, since foundry leaves come from an
            external library. Pass a predicate only for an unusual setup,
            e.g. a hand-drawn pin-metal-only cell placed as a leaf.
        port_edges: ``{port net: 'top' or 'bottom'}`` naming the edge each port
            leaves by. This is normally the parent's decision, since only the
            parent knows what sits above and below the block. A net left out
            falls back to the edge its own terminals sit nearer, which is
            uninformed about the parent. A key naming no port of this block is
            rejected rather than ignored.

    Returns:
        The :class:`PnrResult` with the run's decisions.

    Raises:
        PinAccessError: a pin is unreachable on the grid. This is permanent, so
            no retry is attempted.
        ValueError: the layout already holds geometry, an instance is no
            standard cell, or the netlist breaks a supply assumption.
        RuntimeError: the routing did not converge at the largest floorplan
            tried.
    """
    cfg = grid
    stack = stack_from_spec(routing_spec)
    cell = schematic.cell   # for the error messages only
    check_layout_empty(layout, cell)
    check_layout_layers(layout, stack, cell)
    cells, nets = extract(schematic, pin_rects, is_leaf, cfg)

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

    # The layout's LayoutInstances are the engine's placement representation:
    # one node per leaf, created here, its position and orientation updated on
    # every floorplan attempt below.
    insts = {}
    for name, leaf in cells.items():
        setattr(layout, name, LayoutInstance(ref=leaf.cell.layout,
            pos=Vec2I(0, 0), orientation=D4.R0))
        insts[name] = layout[name]

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
        slots, packed_w = place.place_rows(cells, order, cfg)
        for name, slot in slots.items():
            insts[name].update(pos=Vec2I(*slot.pos), orientation=slot.orient)
        rows = {name: slot.row for name, slot in slots.items()}
        # Derived from the placed instances, not from the placer's output, so
        # the layout stays the sole holder of the placement.
        pins = {name: place.transform_pins(cells[name].pins,
            (node.pos.x, node.pos.y), node.orientation)
            for name, node in insts.items()}
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
                route.tap_avoid_columns(signal_nets, pins, cfg))
            blocked = route.mesh_blocked_nodes(cfg, xmax, taps)
        else:
            taps, blocked = (), frozenset()
        try:
            routing = route.route_nets(
                signal_nets, pins, cfg, xmax, port_nets, blocked, taps,
                port_edges)
            break
        except PinAccessError:
            raise   # permanent: more rows cannot make a pin reachable
        except RuntimeError:
            if i == 4:
                raise
    if cfg.min_area_pass:
        route.extend_min_area(routing.nets, cfg, xmax,
            blocked | routing.reserved)

    # Emit routing directly with concrete coordinates (no constraint solver, so
    # it scales to hundreds of nets).
    for net_name, (edges, term_m2) in routing.nets.items():
        emit_net_direct(layout, stack, edges, term_m2, cfg,
            routing.term_via.get(net_name), routing.term_land.get(net_name))

    # Pad every row's rail out to the die width so the block is a flush rectangle
    # (like filler cells) and the right power strap ties into every rail.
    pad_rails(layout, stack, pins, rows, die_w, cfg.supply_pin_names)
    if cfg.n_rows >= 2:
        emit_power_straps(layout, stack, pins, cfg, die_w)
    if mesh:
        emit_power_mesh(layout, stack, pins, cfg, die_w, taps)

    emit_ports(layout, stack, nets, pins, routing, cfg)
    return PnrResult(cfg=cfg, pins=pins, routing=routing, die_w=die_w,
        taps=taps)


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

    A viewgen root arrives without layers, since the viewgen machinery does not know
    the PDK. A root that already carries a different stack would take this
    engine's geometry on layers from another one.

    Args:
        layout: the :class:`Layout` about to be emitted into.
        stack: the :class:`StackLayers` whose layers the engine emits on.
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


def emit_ports(layout, stack, nets, pins, routing, cfg):
    """Expose every top-level port of the block as a pin on emitted geometry.

    Args:
        layout: the mutable :class:`Layout` to emit into.
        stack: the :class:`StackLayers` for this PDK.
        nets: ``{name: NetInfo}`` for the whole block (ports carry a pin).
        pins: ``{inst: {pin: [Rect4I]}}``, for the supply rails.
        routing: the :class:`~.route.RoutingResult`, for the signal escapes.
        cfg: the routing grid + emitted geometry (:class:`GridConfig`).
    """
    # A signal port was escaped to the top or the bottom edge (route_nets):
    # expose its pin on a Metal4 pad straddling that rail, out in the parent's
    # channel, so the parent lands there without ever routing over the
    # interior. (Fallback: an interior Metal4 pad if the escape reached no
    # edge.) vdd/vss carry by rail abutment, so their port stays a Metal1 rail
    # handle.
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    top_abs = cfg.n_rows * cfg.row_height        # absolute y of the top rail
    for net_name, net in nets.items():
        if net.port_pin is None:
            continue
        if net_name in routing.nets:             # signal port
            escape = routing.port_escape.get(net_name)
            if escape is not None:               # edge pad, outside the rows
                escape_x, edge = escape
                track_x = escape_x * x_pitch
                # The pad straddles its edge rail, reaching port_pad_inner into
                # the block and port_pad_outer into the parent's channel.
                rail_y = top_abs if edge == 'top' else 0
                inner, outer = cfg.port_pad_inner, cfg.port_pad_outer
                lo, hi = ((rail_y - inner, rail_y + outer) if edge == 'top'
                    else (rail_y - outer, rail_y + inner))
                port_rect = layout % LayoutRect(layer=stack.m4, rect=Rect4I(
                    track_x - cfg.strap_half_w, lo,
                    track_x + cfg.strap_half_w, hi))
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
            rail = largest_rect(pins[iname][pname])
            if len(supply_rails(pins, pname)) >= 2:
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



def supply_rails(pins, pname):
    """Distinct rail spans for one supply, sorted bottom-to-top.

    Rails are deduplicated where the boustrophedon shares one between adjacent
    rows. A side strap is emitted only when there are two or more, since a
    single shared rail already ties the whole supply.

    Args:
        pins: ``{inst: {pin: [Rect4I]}}`` die-coordinate pin rectangles.
        pname: the supply pin name, e.g. ``'VDD'``.

    Returns:
        The sorted distinct ``(y0, y1)`` rail spans, in nm.
    """
    rails = set()
    for pin_rects in pins.values():
        if pname in pin_rects:
            rail = largest_rect(pin_rects[pname])
            rails.add((rail.ly, rail.uy))
    return sorted(rails)



def pad_rails(layout, stack, pins, rows, die_w, supply_pins):
    """Extend every row's supply rail rightward to a common die-width edge.

    Like filler cells, this makes the block a flush rectangle and lets the
    right-side power strap tap every row. Rows come out at slightly different
    packed widths, so without this the shorter rows would not reach the strap.

    Args:
        layout: the mutable :class:`Layout` to emit into.
        stack: the :class:`StackLayers` for this PDK's layers.
        pins: ``{inst: {pin: [Rect4I]}}`` die-coordinate pin rectangles.
        rows: ``{inst: row index}`` from the fold.
        die_w: the die width to pad each rail out to, in nm.
        supply_pins: the supply pin names (``cfg.supply_pin_names``).
    """
    rails = {}   # (row, supply) -> [x1, y0, y1]
    for name, pin_rects in pins.items():
        for supply in supply_pins:
            if supply not in pin_rects:
                continue
            rect = largest_rect(pin_rects[supply])
            key = (rows[name], supply)
            existing = rails.get(key)
            if existing is None:
                rails[key] = [rect.ux, rect.ly, rect.uy]
            else:
                existing[0] = max(existing[0], rect.ux)
    for (row, supply), (x1, y0, y1) in rails.items():
        if x1 < die_w:
            layout % LayoutRect(layer=stack.m1, rect=Rect4I(x1, y0, die_w, y1))



def emit_power_straps(layout, stack, pins, cfg, die_w):
    """Form a power ring per supply from a vertical Metal2 strap on each side.

    Each strap sits in the empty margin beside the cell area and taps every rail
    through a short Metal1 extension and a Via1. The boustrophedon shares a rail
    between adjacent rows, so the inner rails would otherwise float. The ring
    ties them and halves rail IR drop. Skipped for a supply with one shared
    rail, which already ties itself.

    Args:
        layout: the mutable :class:`Layout` to emit into.
        stack: the :class:`StackLayers` for this PDK's layers.
        pins: ``{inst: {pin: [Rect4I]}}`` die-coordinate pin rectangles.
        cfg: the routing grid + geometry (:class:`GridConfig`).
        die_w: the die width in nm. The right strap mirrors to it.
    """
    via_half = cfg.via_half
    for pname, strap_left_x, strap_right_x in (
            (cfg.vdd_pin, cfg.strap_vdd_x, die_w - cfg.strap_vdd_x),
            (cfg.vss_pin, cfg.strap_vss_x, die_w - cfg.strap_vss_x)):
        rails = supply_rails(pins, pname)
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



def emit_power_mesh(layout, stack, pins, cfg, die_w, taps):
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
        stack: the :class:`StackLayers` for this PDK's layers.
        pins: ``{inst: {pin: [Rect4I]}}`` die-coordinate pin rectangles.
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
        for rail_y0, rail_y1 in supply_rails(pins, pname):
            rail_y_center = (rail_y0 + rail_y1) // 2
            if not 0 < rail_y_center < core_top:   # interior rails only
                continue
            layout % LayoutRect(layer=stack.m5, rect=Rect4I(
                0, rail_y_center - cfg.mesh_half_w,
                die_w, rail_y_center + cfg.mesh_half_w))
            for xi in taps:
                via_stack(xi * x_pitch, rail_y_center)
