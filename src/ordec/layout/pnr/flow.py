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
from .route import (HORIZ, LIDX, M1, M2, M3, M4, M5, PinAccessError, VERT,
    VIDX)


@public
@dataclass(frozen=True)
class PdnVia:
    """Via geometry for one power-stripe connection, sized to the DRC rules.

    Cut arrays are derived from these values and the stripe width, so a wider
    stripe automatically carries more cuts. All lengths are in nm.
    """
    cut: int         # via cut size (square)
    cut_pitch: int   # cut size plus minimum same-via cut spacing
    encl_above: int  # min enclosure by the stripe metal, per side
    encl_below: int  # min enclosure by the metal below, per side


@public
@dataclass(frozen=True)
class PdnStripes:
    """One power-stripe layer of the block's power distribution network.

    Stripes alternate the two supply nets at an even spacing across the die,
    so worst-case rail current travels a bounded distance on thin Metal1
    regardless of block width. The layer is named by its metal level in the
    PDK's RoutingSpec (0 is the pin-access metal), so odd levels run
    vertically and even levels horizontally, matching the routing layers
    below. All lengths are in nm.
    """
    level: int       # metal level in the routing spec (0 = pin-access metal)
    width: int       # stripe width
    pitch: int       # target center-to-center pitch of same-net stripes
    spacing: int     # min same-layer spacing at this width
    via: PdnVia      # cut geometry connecting down to the level below


@public
@dataclass(frozen=True)
class PdnRing:
    """A core ring: two concentric supply loops around the placement rows.

    The ring sits in a margin outside the core on two adjacent top layers, one
    carrying its horizontal (top and bottom) segments and the other its
    vertical (left and right) segments, joined at the four corners by via
    arrays. Each supply gets its own loop, one inside the other. The vertical
    stripes tie into the horizontal segments and the horizontal stripes into
    the vertical ones, and the block's supply ports move onto the ring. All
    lengths are in nm.
    """
    h_level: int     # metal level of the horizontal (top/bottom) segments
    v_level: int     # metal level of the vertical (left/right) segments
    width: int       # ring conductor width
    spacing: int     # min spacing between the loops and from the core
    offset: int      # gap from the core edge to the inner loop, >= spacing
    via: PdnVia      # cut geometry joining the two layers at the corners


@public
@dataclass(frozen=True)
class PdnSpec:
    """The PDK's power-distribution profile: stripe layers, ascending.

    The first level must be vertical (it taps the horizontal rails) and every
    further level connects to the one before it at their crossings. Levels
    that do not fit a given die (two stripes plus spacing) are left out from
    that level upward, so a small block simply carries fewer levels.

    An optional :class:`PdnRing` wraps the core in supply loops the stripes
    tie into. ``None`` leaves the stripes exposed at the die edges as before.
    """
    stripes: tuple            # PdnStripes, ascending level
    ring: 'PdnRing' = None    # optional core ring, None = stripes only


PdnLevel = namedtuple('PdnLevel', 'spec stripes')
# stripes: tuple of (supply pin name, center) with the center in nm, an x for a
# vertical level and a y for a horizontal one.


@public
@dataclass(frozen=True)
class PdnPlan:
    """One die's power-distribution plan, fixed before routing.

    The stripe positions must be known before routing because the rail-tap via
    stacks reserve router nodes, exactly like any other hard blockage.

    Args:
        levels: the emitted :class:`PdnLevel` per stripe layer, ascending. A
            level that does not fit the die is left out, along with everything
            above it.
        blocked: the router nodes the rail-tap via stacks make unusable.
        tap_landings: ``(x, y)`` centers of the taps' Metal2 landings, which
            off-track access bridges must keep metal spacing from.
    """
    levels: tuple
    blocked: frozenset
    tap_landings: tuple


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
    # Routing grid, from the PDK tech LEF. The base grid is the finest track
    # pitch per axis, and a coarser layer runs on every ``track_mult``-th
    # base track of its own axis (a uniform stack keeps all multiples at 1):
    x_pitch: int             # base vertical-layer track pitch
    y_pitch: int             # base horizontal-layer track pitch
    row_height: int          # standard-cell row height (= tracks_per_row * y_pitch)
    tracks_per_row: int      # y-tracks per row (row_height / y_pitch)
    via_half: tuple          # half the Via1..Via4 cut sizes, per via
    encl: int                # min metal enclosure of via on every side (V1.c)
    encl_endcap: int         # min metal enclosure on >= 1 side (V1.c1)
    manufacturing_grid: int  # layout quantum, off-track vias snap to it (MANUFACTURINGGRID)
    # Supply naming, from the cell library / netlist conventions of the PDK
    # binding. Rail abutment shorts all like-named rails, so the engine supports
    # exactly one net per supply pin and validates these names loudly.
    vdd_pin: str             # supply pin name on the leaf cells (e.g. 'VDD')
    vss_pin: str             # ground pin name on the leaf cells (e.g. 'VSS')
    vdd_net: str             # required schematic net name for the supply
    vss_net: str             # required schematic net name for ground
    # Emitted geometry, sized to the PDK DRC rules. The per-layer tuples run
    # (Metal2, Metal3, Metal4, Metal5) for metals and (Via1..Via4) for vias,
    # indexed through route.LIDX / route.VIDX:
    wire_width: tuple        # routing-wire width per layer (= min width)
    wire_space: tuple        # min same-layer metal spacing, per layer
    wire_ext: tuple          # wire overhang past its last via, per layer
    land_half_h: tuple       # half the long side of a min-area via landing
    m1_land_half_w: int      # half-width of the Metal1 landing under a Via1
    m1_land_half_h: int      # half-height of the Metal1 endcap landing under a Via1
    m1_space: int            # Metal1 min spacing, for access-landing conflicts
    via1_space: int          # Via1 cut min spacing, for access-cut conflicts
    min_area_tracks: tuple   # min wire span in run-axis grid steps, per layer
    port_pad_inner: int      # port-pad depth from the die edge into the block
    # Fields with defaults follow.
    # PDK grid data continued: track-pitch multiple of each layer on its own
    # axis (Metal2, Metal3, Metal4, Metal5), 1 for a uniform stack. The base
    # grids are defined by Metal2 (x) and the pin-access rows (y), so the
    # Metal2 entry is 1 by definition.
    track_mult: tuple = (1, 1, 1, 1)
    # Track offset of each layer on its own axis, in base-grid steps. A
    # half-pitch-offset lattice (sky130hd) sets the base grid to the half
    # pitch and each layer's offset to half its multiple.
    track_off: tuple = (0, 0, 0, 0)
    # Per-via landing pads, or None when the wires themselves enclose their
    # vias (a stack whose wire width covers cut + 2 * side enclosure). Four
    # ((below_cross_half, below_along_half), (above_cross_half,
    # above_along_half)) entries in Via1..Via4 order, cross being the axis
    # perpendicular to the metal's run direction. The Via1 entry is unused,
    # since Via1 appears only under terminal stacks with their own landings.
    via_land: tuple = None
    # Optional pin-access sub-layer below Metal1 (sky130's li1 with mcon):
    # signal pins live on the sub-layer and are reached by a sub-via under
    # the Metal1 landing, while supply rails stay on Metal1. None when
    # signal pins sit on Metal1 itself.
    sub_via_half: int = None  # half the sub-via cut size
    sub_via_space: int = 0    # sub-via cut min spacing, for access-cut conflicts
    sub_encl: int = 0         # sub-layer enclosure of the sub-via, all sides
    sub_encl_endcap: int = 0  # sub-layer enclosure on a pair of sides
    # The Metal1 landing over a sub-via is thin in y (just enclosing the
    # sub-via, so it clears the rails that near-rail pins sit close to) and
    # grows along x within the pin to meet Metal1 min area.
    sub_land_half_h: int = 0  # half the landing's y extent (encloses the
                              # sub-via below and the Via1 above, all sides)
    sub_land_half_w_min: int = 0  # min half-width (Via1 endcap enclosure)
    sub_land_min_area: int = 0  # Metal1 min area the landing must reach
    # Pins connected by well abutment rather than metal (sky130's VNB/VPB).
    # Their terminals are dropped from routing.
    abut_pins: tuple = ()
    # Max distance a packed row may run without a well-tap cell, for cell
    # libraries without cell-integrated well ties (sky130hd). 0 disables
    # insertion, and the tap cell itself is the well_tap_cell argument of
    # place_and_route.
    well_tap_dist: int = 0
    # Flow knobs, PDK-independent, with universal defaults:
    n_rows: int = 1          # number of abutted (flipped) standard-cell rows
    via_cost: float = 4.0    # A* cost of a layer change (in track units)
    min_area_pass: bool = True
    use_upper: bool = True   # allow routing on Metal4/Metal5 (else Metal2/3 only)
    use_m5: bool = True      # allow routing on Metal5 (off where its wires
                             # cannot fit the base grid, e.g. sky130's met5)
    # PDK-specific like the geometry above, but defaulted so an engine-level
    # profile without a PDK behind it can leave the PDN out entirely.
    pdn: PdnSpec = None      # power stripe profile, or None for no PDN
                             # (single-row blocks only, inner rails float
                             # without stripes)
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


def pdn_level_layers(routing_spec, level):
    """The metal layer of one PDN stripe level and the via layer below it.

    Levels count metals in ``route_id`` order, 0 being the pin-access metal,
    so level 5 on sg13g2 is TopMetal1 with TopVia1 below it.

    Args:
        routing_spec: the :class:`RoutingSpec` naming the PDK's layer stack.
        level: the metal level of the stripe layer.

    Returns:
        ``(metal_layer, via_layer)``.

    Raises:
        ValueError: the spec does not reach this level.
    """
    rsls = sorted(routing_spec.all(RoutingSpecLayer), key=lambda l: l.route_id)
    if len(rsls) < 2 * level + 1:
        raise ValueError(
            f"the PDN profile asks for stripes on metal level {level}, but "
            f"the routing spec ends after {(len(rsls) + 1) // 2} metals")
    return rsls[2 * level].layer, rsls[2 * level - 1].layer


class PinRects(dict):
    """``{macro: {pin: [(x0, y0, x1, y1), ...]}}`` read from one LEF file.

    A macro whose pin or obstruction geometry leaves the accepted layers is
    left out rather than mapped to its accepted rects alone, since the engine
    routes the metals above the leaf cells and would silently short or
    violate that geometry. The rejection has to wait until the macro is
    looked up: a library LEF holds macros a given design never places, so
    reading the file must not fail over one of them.
    """
    def __init__(self, rects, off_layer, pin_layer, obs=None, direct=None):
        super().__init__(rects)
        self.off_layer = off_layer   # {macro: [layer, ...]} of the rejects
        self.pin_layer = pin_layer
        self.obs = obs or {}         # {macro: [(x0, y0, x1, y1), ...]}
        self.direct = direct or {}   # {macro: frozenset(rail-layer pin names)}

    def __missing__(self, macro):
        if macro not in self.off_layer:
            raise KeyError(macro)
        raise ValueError(
            f"{macro}: LEF pin/obstruction geometry on "
            f"{self.off_layer[macro]}. The P&R engine requires leaf cells "
            f"with pins on {self.pin_layer} only, since it routes on the "
            "metals above them")


@public
def lef_pin_rects(lef_path, pin_layer: str, rail_layer: str = None,
        rail_pins: tuple = (), obs_ok: tuple = (),
        ignore_layers: tuple = ()) -> dict[str, dict]:
    """Read the per-pin pin-layer rectangles of every macro in a LEF file.

    This is the ``pin_rects`` input :func:`place_and_route` takes. The LEF
    rectangles are clean, per-pin and non-overlapping, with the foundry pin
    names kept as-is, so the router can pick a via-access point that lands on
    exactly the intended pin.

    Args:
        lef_path: the library LEF holding the macros, e.g.
            ``ordec.lib.ihp130.pdk().stdcell_lef``.
        pin_layer (str): LEF name of the layer signal pins live on, e.g.
            ``Metal1``, or the sub-layer ``li1`` of a sub-access stack.
        rail_layer (str): LEF name of the supply-rail layer when it differs
            from ``pin_layer`` (sky130's ``met1``). Pins named in
            ``rail_pins`` then keep their rail-layer rects instead.
        rail_pins: the supply pin names read from ``rail_layer``.
        obs_ok: obstruction layers the engine may ignore, e.g. the sub-layer
            itself, on which the engine only ever places sub-vias inside pin
            rects.
        ignore_layers: pin geometry layers with no metal role, e.g. the well
            pins' ``nwell``/``pwell``.

    Returns:
        PinRects: ``{macro: {PIN: [(x0, y0, x1, y1), ...]}}`` in nm, holding
        every macro the engine can place. A macro with geometry off the
        accepted layers is rejected when it is looked up.
    """
    import sc_leflib

    rects = {}
    off_layer = {}
    obs_rects = {}
    direct = {}   # macro -> pins accessed on rail_layer (Metal1) not pin_layer
    for macro_name, macro in sc_leflib.parse(str(lef_path))["macros"].items():
        macro_rects = {}
        macro_obs = []
        macro_direct = set()
        off = set()   # layers outside the accepted set in the PIN or OBS geometry
        allowed = {pin_layer, rail_layer} | set(ignore_layers)
        for pin, pin_data in macro["pins"].items():
            # Group the pin's rects by layer, so its access layer can be
            # chosen: a rail pin on rail_layer, otherwise pin_layer, else
            # rail_layer for a signal pin the library routed up to Metal1
            # (sky130's larger cells), which is then accessed directly.
            by_layer = {}
            for port in pin_data["ports"]:
                for geom in port["layer_geometries"]:
                    if geom["layer"] not in allowed:
                        off.add(geom["layer"])
                        continue
                    for shape in geom["shapes"]:
                        # LEF also allows POLYGON here. The known PDKs' pins are
                        # all rectangles, and a polygon pin would need a
                        # polygon-exact via-access engine anyway.
                        if "rect" not in shape:
                            continue
                        x0, y0, x1, y1 = (round(v * 1000) for v in shape["rect"])
                        by_layer.setdefault(geom["layer"], []).append(
                            (x0, y0, x1, y1))
            if pin in rail_pins:
                want = rail_layer
            elif by_layer.get(pin_layer):
                want = pin_layer
            elif rail_layer and by_layer.get(rail_layer):
                want = rail_layer
                macro_direct.add(pin)
            else:
                want = pin_layer
            macro_rects[pin] = by_layer.get(want, [])
        m1_layer = rail_layer or pin_layer
        for port in macro.get("obs") or []:
            for geom in port:
                if geom["layer"] == m1_layer:
                    # Cell-internal metal on the engine's Metal1: the
                    # landings must keep clear of it. Sub-layer obstructions
                    # (sky130's li1) sit below the engine's metal and are
                    # covered by obs_ok instead.
                    for shape in geom["shapes"]:
                        if "rect" in shape:
                            macro_obs.append(tuple(round(v * 1000)
                                for v in shape["rect"]))
                elif geom["layer"] != pin_layer \
                        and geom["layer"] not in obs_ok \
                        and geom["layer"] not in ignore_layers:
                    off.add(geom["layer"])
        if off:
            off_layer[macro_name] = sorted(off)
        else:
            rects[macro_name] = macro_rects
            obs_rects[macro_name] = macro_obs
            direct[macro_name] = frozenset(macro_direct)
    return PinRects(rects, off_layer, pin_layer, obs_rects, direct)


@dataclass
class NetInfo:
    """A net to route: its terminals (instance pin connections) and, if it is a
    top-level port, the symbol Pin it exposes."""
    name: str
    terminals: list = field(default_factory=list)  # (inst_name, pin_name)
    port_pin: object = None   # cell symbol Pin if this net is a top-level port


# One leaf cell before placement: the Cell, its Metal1 pin rects, and its width.
LeafCell = namedtuple('LeafCell', 'cell pins width obs', defaults=((),))


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
    if cfg.abut_pins:
        # Well pins connect by abutment, not metal, so they are no routing
        # terminals.
        net_terminals = {net: [t for t in terms if t[1] not in cfg.abut_pins]
            for net, terms in net_terminals.items()}

    cells = {}
    obs_lookup = getattr(pin_rects, 'obs', {})
    for name, leaf in leaf_insts.items():
        # Wrap the lookup's raw nm tuples as Rect4I, so the rest of the engine
        # works with named geometry (rect.lx / .cx / .width, vertex-in-rect) rather
        # than positional indexing.
        rects = {pin: [Rect4I(*r) for r in raw]
            for pin, raw in pin_rects[leaf.name].items()}
        obs = [Rect4I(*r) for r in obs_lookup.get(leaf.name, ())]
        # Cell pitch = power-rail width (the rail rect spans the whole cell).
        width = max(r.width for r in rects[cfg.vdd_pin])
        cells[name] = LeafCell(leaf, rects, width, obs)

    nets = {net_name: NetInfo(net_name, list(terms))
        for net_name, terms in net_terminals.items()}

    # Mark top-level port nets (Net.pin references a symbol Pin).
    for net in schematic.all(Net):
        if net.pin is not None:
            net_name = leaf_name(net)
            if net_name in nets:
                nets[net_name].port_pin = net.pin

    return cells, nets


def emit_net_direct(layout, stack, edges, term_m2, cfg,
        term_via=None, term_land=None, sub_via_layer=None, sub_set=()):
    """Emit one routed net's geometry directly with concrete coordinates.

    No constraint solver is used, since ORDeC's general solver is fast per cell
    but takes minutes for a few-hundred-net block. Wire runs become
    Metal2/3/4/5 paths and each layer change is a via cut. The wires provide
    the via landings where their width covers the enclosure, with explicit
    pads (``cfg.via_land``) where it does not, and the router's via-access
    pass keeps every run long enough to meet min area and endcap.

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
        sub_via_layer: the sub-via layer of a pin-access sub-layer stack
            (``cfg.sub_via_half``), or None without one.
    """
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    metal_layer = {M2: stack.m2, M3: stack.m3, M4: stack.m4, M5: stack.m5}
    via_layer = {frozenset((M1, M2)): stack.via1, frozenset((M2, M3)): stack.via2,
        frozenset((M3, M4)): stack.via3, frozenset((M4, M5)): stack.via4}
    vert_runs = {}    # (layer, xi) -> set(yi)   on vertical layers (M2, M4)
    horiz_runs = {}   # (layer, yi) -> set(xi)   on horizontal layers (M3, M5)
    vias = set()  # (xi, yi, frozenset(layer pair))
    net_metal = {M2: [], M3: [], M4: [], M5: []}   # emitted rects, for healing

    def put(code, rect):
        net_metal[code].append(rect)
        layout % LayoutRect(layer=metal_layer[code], rect=rect)

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

    def path(code, p0, p1):
        half_w = cfg.wire_width[LIDX[code]] // 2
        ext = cfg.wire_ext[LIDX[code]]
        net_metal[code].append(Rect4I(
            min(p0.x, p1.x) - (ext if p0.y == p1.y else half_w),
            min(p0.y, p1.y) - (half_w if p0.y == p1.y else ext),
            max(p0.x, p1.x) + (ext if p0.y == p1.y else half_w),
            max(p0.y, p1.y) + (half_w if p0.y == p1.y else ext)))
        layout % LayoutPath(layer=metal_layer[code],
            width=cfg.wire_width[LIDX[code]], endtype=PathEndType.Custom,
            ext_bgn=cfg.wire_ext[LIDX[code]], ext_end=cfg.wire_ext[LIDX[code]],
            vertices=[p0, p1])

    # A single-node run is a pass-through via landing (e.g. Metal3 in a
    # Metal2->Metal3->Metal4 stack). A zero-length path emits no metal, so lay a
    # min-area landing rect instead. Multi-node runs already meet min area via
    # the grow and extend_min_area passes.
    for (layer, xi), y_tracks in vert_runs.items():
        half_w = cfg.wire_width[LIDX[layer]] // 2
        land_half = cfg.land_half_h[LIDX[layer]]
        for y0, y1 in runs(y_tracks):
            if y0 != y1:
                path(layer, Vec2I(xi * x_pitch, y0 * y_pitch),
                    Vec2I(xi * x_pitch, y1 * y_pitch))
                continue
            put(layer, Rect4I(
                xi * x_pitch - half_w, y0 * y_pitch - land_half,
                xi * x_pitch + half_w, y0 * y_pitch + land_half))
    for (layer, yi), x_tracks in horiz_runs.items():
        half_w = cfg.wire_width[LIDX[layer]] // 2
        land_half = cfg.land_half_h[LIDX[layer]]
        for x0, x1 in runs(x_tracks):
            if x0 != x1:
                path(layer, Vec2I(x0 * x_pitch, yi * y_pitch),
                    Vec2I(x1 * x_pitch, yi * y_pitch))
                continue
            put(layer, Rect4I(
                x0 * x_pitch - land_half, yi * y_pitch - half_w,
                x0 * x_pitch + land_half, yi * y_pitch + half_w))
    for xi, yi, layer_pair in vias:
        via_half = cfg.via_half[VIDX[layer_pair]]
        vx, vy = xi * x_pitch, yi * y_pitch
        layout % LayoutRect(layer=via_layer[layer_pair], rect=Rect4I(
            vx - via_half, vy - via_half, vx + via_half, vy + via_half))
        if cfg.via_land is not None:
            # Landing pads on both metals, since these wires are narrower
            # than the via enclosure they would otherwise have to provide.
            below, above = sorted(layer_pair, key=(M2, M3, M4, M5).index)
            pads = cfg.via_land[VIDX[layer_pair]]
            for code, (cross_half, along_half) in zip((below, above), pads):
                dx, dy = ((cross_half, along_half) if code in VERT
                    else (along_half, cross_half))
                put(code, Rect4I(vx - dx, vy - dy, vx + dx, vy + dy))
    term_via = term_via or {}
    via1_half = cfg.via_half[0]
    m2_half_w, m2_land_half = cfg.wire_width[0] // 2, cfg.land_half_h[0]

    def sub_via(via_x, via_y, land):
        # Sub-access stack rung: the sub-via cut on the sub-layer pin plus
        # the Metal1 landing it shares with the Via1 above. The landing
        # (from the router, grown along x for min area) is the Metal1 here.
        half = cfg.sub_via_half
        layout % LayoutRect(layer=sub_via_layer, rect=Rect4I(
            via_x - half, via_y - half, via_x + half, via_y + half))
        layout % LayoutRect(layer=stack.m1, rect=Rect4I(*land))

    def term_m2_pad(via_x, via_y):
        # Metal2 pad over a terminal Via1 whose wire is too narrow to
        # enclose it (via_land, like any other via).
        if cfg.via_land is None:
            return
        cross_half, along_half = cfg.via_land[0][1]
        put(M2, Rect4I(
            via_x - cross_half, via_y - along_half,
            via_x + cross_half, via_y + along_half))

    # dict.fromkeys: two terminals of one net may share an access node, so its
    # via stack is emitted once.
    for node in dict.fromkeys(term_m2):   # Via1 from the Metal1 pin up to Metal2
        xi, yi, _layer = node
        if node in term_via:
            # Off-track pin (no track lands inside it): drop the via on the pin
            # at via_x and jog to track xi with a short Metal2 segment. The pin's
            # own metal gives the Via1 endcap, so no Metal1 landing is added (it
            # would notch the pin and break Metal1 spacing). A sub-access pin sits
            # below Metal1, so its landing is emitted (no Metal1 pin to notch).
            via_x, via_y = term_via[node]
            if node in sub_set:
                sub_via(via_x, via_y, (term_land or {})[node])
            term_m2_pad(via_x, via_y)
            layout % LayoutRect(layer=stack.via1, rect=Rect4I(
                via_x - via1_half, via_y - via1_half,
                via_x + via1_half, via_y + via1_half))
            lo, hi = min(via_x, xi * x_pitch), max(via_x, xi * x_pitch)
            put(M2, Rect4I(
                lo - m2_half_w, via_y - m2_land_half,
                hi + m2_half_w, via_y + m2_land_half))
        else:
            via_x, via_y = xi * x_pitch, yi * y_pitch
            if node in sub_set:
                sub_via(via_x, via_y, (term_land or {})[node])
            term_m2_pad(via_x, via_y)
            layout % LayoutRect(layer=stack.via1, rect=Rect4I(
                via_x - via1_half, via_y - via1_half,
                via_x + via1_half, via_y + via1_half))
            # Metal1 endcap landing (merges with the cell pin) so the via meets the
            # 50 nm endcap rule (V1.c1) even on short foundry pins. access_nodes
            # shapes it along the pin's enclosing axis so it never notches a
            # neighbouring cell pin.
            land = (term_land or {}).get(node, (
                via_x - cfg.m1_land_half_w, via_y - cfg.m1_land_half_h,
                via_x + cfg.m1_land_half_w, via_y + cfg.m1_land_half_h))
            layout % LayoutRect(layer=stack.m1, rect=Rect4I(*land))

    # Two disjoint pieces of one net closer than the metal spacing form a notch
    # no rerouting can fix, so heal each gap with a filler overlapping both
    # pieces. Nothing foreign fits inside the spacing so it shorts nothing, and
    # it is widened to the wire width within their union to meet min width.
    mgrid = cfg.manufacturing_grid

    def filler_span(lo, hi, a_lo, a_hi, b_lo, b_hi, wmin):
        gap = lo - hi   # positive when the axes do not overlap
        if gap > 0:
            g = max(20, (wmin - gap + 1) // 2 + 10)
            g = -(-g // mgrid) * mgrid
            return hi - g, lo + g
        span_lo, span_hi = lo, hi
        short = wmin - (hi - lo)
        if short > 0:
            grow_lo = min(lo - min(a_lo, b_lo), -(-short // 2))
            grow_lo = grow_lo // mgrid * mgrid
            span_lo -= grow_lo
            grow_hi = min(max(a_hi, b_hi) - hi, short - grow_lo)
            grow_hi = -(-grow_hi // mgrid) * mgrid
            span_hi += grow_hi
        return span_lo, span_hi

    for code, rects in net_metal.items():
        space = cfg.wire_space[LIDX[code]]
        wmin = cfg.wire_width[LIDX[code]]
        for i in range(len(rects)):
            a = rects[i]
            for j in range(i + 1, len(rects)):
                b = rects[j]
                gx0, gx1 = max(a.lx, b.lx), min(a.ux, b.ux)
                gy0, gy1 = max(a.ly, b.ly), min(a.uy, b.uy)
                dgx, dgy = max(0, gx0 - gx1), max(0, gy0 - gy1)
                if dgx * dgx + dgy * dgy >= space * space:
                    continue   # euclidean spacing satisfied
                if dgx == 0 and dgy == 0:
                    continue   # touching or overlapping already
                fx0, fx1 = filler_span(gx0, gx1, a.lx, a.ux, b.lx, b.ux,
                    wmin)
                fy0, fy1 = filler_span(gy0, gy1, a.ly, a.uy, b.ly, b.uy,
                    wmin)
                layout % LayoutRect(layer=metal_layer[code],
                    rect=Rect4I(fx0, fy0, fx1, fy1))



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
        pdn: the :class:`PdnPlan` the die was routed around, with empty
            ``levels`` when the profile has no PDN or nothing fit.
    """
    cfg: GridConfig
    pins: dict
    routing: object
    die_w: int
    pdn: PdnPlan


def insert_well_taps(slots, cells, cfg, tap_w):
    """Insert well-tap slots into packed rows every ``cfg.well_tap_dist``.

    Standard cells without their own well and substrate ties (sky130hd) need
    tap cells at a bounded distance. Each row is re-abutted with a tap
    wherever the run since the last one would exceed the limit. The taps
    carry no signal pins, so routing is unaffected beyond the shifted cell
    positions.

    Args:
        slots: ``{name: RowSlot}`` from :func:`.place.place_rows`.
        cells: ``{name: LeafCell}``, for the cell widths.
        cfg: the :class:`GridConfig` (``well_tap_dist``).
        tap_w: the tap cell width in nm.

    Returns:
        ``(tap_slots, slots, packed_w)``: the inserted taps as their own
        ``{name: RowSlot}``, the shifted cell slots, and the new widest
        packed row.
    """
    by_row = {}
    for name, slot in slots.items():
        by_row.setdefault(slot.row, []).append((slot.pos[0], name))
    new_slots = {}
    tap_slots = {}
    packed_w = 0
    k = 0
    for row, entries in sorted(by_row.items()):
        entries.sort()
        row_y = slots[entries[0][1]].pos[1]
        orient = slots[entries[0][1]].orient
        x = 0
        since = 0
        tapped = False
        for _x, name in entries:
            w = cells[name].width
            if since + w > cfg.well_tap_dist:
                tap_slots[f"welltap{k}"] = place.RowSlot((x, row_y), orient,
                    row)
                k += 1
                x += tap_w
                since = 0
                tapped = True
            new_slots[name] = place.RowSlot((x, row_y), orient, row)
            x += w
            since += w
        if not tapped:
            # A row shorter than the limit still needs its well tied.
            tap_slots[f"welltap{k}"] = place.RowSlot((x, row_y), orient, row)
            k += 1
            x += tap_w
        packed_w = max(packed_w, x)
    return tap_slots, new_slots, packed_w


def insert_fillers(slots, tap_slots, cells, cfg, fillers, die_w, tap_w):
    """Fill each row's tail with filler cells out to the die edge.

    Rows pack abutted from the left, so the die's spare width shows as a
    gap at the right end of every row. Filler cells close it exactly (the
    die is a whole number of sites), keeping the rails and wells continuous
    the way an assembled row keeps them.

    Args:
        slots: ``{name: RowSlot}`` of the converged placement.
        tap_slots: the well-tap slots of the same placement.
        cells: ``{name: LeafCell}``, for the placed cells' widths.
        cfg: the :class:`GridConfig`.
        fillers: ``{width: Cell}`` filler cells by their width.
        die_w: the die width in nm.
        tap_w: the well-tap cell width in nm.

    Returns:
        ``{name: (RowSlot, width)}``, the filler instances to create.

    Raises:
        ValueError: the filler widths cannot tile a row's gap.
    """
    row_end = {}
    row_at = {}
    for name, slot in slots.items():
        end = slot.pos[0] + cells[name].width
        if end > row_end.get(slot.row, 0):
            row_end[slot.row] = end
            row_at[slot.row] = slot
    for name, slot in tap_slots.items():
        end = slot.pos[0] + tap_w
        if end > row_end.get(slot.row, 0):
            row_end[slot.row] = end
            row_at[slot.row] = slot
    out = {}
    k = 0
    for row, end in sorted(row_end.items()):
        slot = row_at[row]
        x = end
        for w in sorted(fillers, reverse=True):
            while die_w - x >= w:
                out[f"fill{k}"] = (place.RowSlot((x, slot.pos[1]),
                    slot.orient, row), w)
                k += 1
                x += w
        if x != die_w:
            raise ValueError(f"the filler cells (widths "
                f"{sorted(fillers)}) cannot tile the {die_w - x} nm tail "
                f"of row {row}")
    return out


@public
def place_and_route(schematic, layout, *, grid, routing_spec, pin_rects,
        is_leaf=is_extlibrary_leaf, port_edges=None, sub_via_layer=None,
        well_tap_cell=None, filler_cells=()):
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
        port_edges: ``{port net: edge}`` naming the die edge ('top',
            'bottom', 'left' or 'right') each port leaves by. This is
            normally the parent's decision, since only the parent knows what
            surrounds the block. A net left out falls back to its nearest
            edge, which is uninformed about the parent. A key naming no port
            of this block is rejected rather than ignored.

    Returns:
        The :class:`PnrResult` with the run's decisions.

    Raises:
        PinAccessError: a pin is unreachable on the grid. This is permanent, so
            no retry is attempted.
        ValueError: the layout already holds geometry, an instance is no
            standard cell, or the netlist breaks a supply assumption.
        CongestionError: the routing did not converge at the largest
            floorplan tried.
    """
    cfg = grid
    stack = stack_from_spec(routing_spec)
    if (cfg.sub_via_half is None) != (sub_via_layer is None):
        raise ValueError("a pin-access sub-layer needs both the profile's "
            "sub_via_half and the sub_via_layer argument, or neither")
    if (cfg.well_tap_dist == 0) != (well_tap_cell is None):
        raise ValueError("well-tap insertion needs both the profile's "
            "well_tap_dist and the well_tap_cell argument, or neither")
    tap_w = 0
    if well_tap_cell is not None:
        tap_rects = {pin: [Rect4I(*r) for r in raw]
            for pin, raw in pin_rects[well_tap_cell.name].items()}
        tap_w = max(r.width for r in tap_rects[cfg.vdd_pin])
    fillers = {}
    filler_rects = {}
    for fcell in filler_cells:
        rects = {pin: [Rect4I(*r) for r in raw]
            for pin, raw in pin_rects[fcell.name].items()}
        width = max(r.width for r in rects[cfg.vdd_pin])
        fillers[width] = fcell
        filler_rects[width] = rects
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

    # Which net each terminal drives, for the access-landing clearance
    # checks. Supply pins map to their rails' net.
    term_net = {}
    for net_name, net in nets.items():
        for iname, pname in net.terminals:
            term_net[(iname, pname)] = net_name

    # Pins the library routed up to Metal1 (accessed directly, not through
    # the sub-via), by flat instance name.
    pin_direct = getattr(pin_rects, 'direct', {})
    direct_pins = {(iname, pname)
        for iname, leaf in cells.items()
        for pname in pin_direct.get(leaf.cell.name, ())}

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
    # Stripe columns cannot host port escapes, so a pad-limited die needs
    # extra columns beyond one per port. The minimum stripe count covers the
    # common case, and a die wide enough for more stripes has columns to
    # spare. When the columns still run short, the escape allocation says so
    # (EscapeCapacityError) and the die widens by the deficit.
    escape_cols = len(port_nets) + (2 if cfg.pdn else 0)
    # A multi-row block must fit the first stripe level, since without the
    # stripes the boustrophedon's inner rails would float. A first level
    # inside the routing window blocks a corridor of its own layer around
    # each stripe, so the die must additionally fit two corridors and a few
    # escape columns between them.
    pdn_min_w = 0
    stripe_floor = 0
    if cfg.pdn and cfg.pdn.stripes:
        sp0 = cfg.pdn.stripes[0]
        pdn_min_w = 2 * (sp0.width + sp0.spacing)
        if sp0.level <= 4:
            code = (M2, M3, M4, M5)[sp0.level - 1]
            clearance = (sp0.width + cfg.wire_width[LIDX[code]]) // 2 \
                + sp0.spacing
            stripe_floor = 4 * clearance \
                + 3 * cfg.x_pitch * cfg.track_mult[LIDX[M4]]
    # The die is a whole number of placement sites, so filler cells can
    # close every row exactly.
    site = x_pitch * cfg.track_mult[LIDX[M2]]
    extra_w = 0
    for i, nrows in enumerate(range(base, base + 5)):
        if nrows >= 2 and not (cfg.pdn and cfg.pdn.stripes):
            raise ValueError("a multi-row block needs a PDN stripe profile "
                "(GridConfig.pdn): without stripes the boustrophedon's inner "
                "rails would float")
        cfg = replace(cfg, n_rows=nrows)
        order = place.order_cells_sa(cells, nets, cfg)
        slots, packed_w = place.place_rows(cells, order, cfg)
        tap_slots = {}
        if well_tap_cell is not None:
            tap_slots, slots, packed_w = insert_well_taps(slots, cells, cfg,
                tap_w)
        for name, slot in slots.items():
            insts[name].update(pos=Vec2I(*slot.pos), orientation=slot.orient)
        rows = {name: slot.row for name, slot in slots.items()}
        # Derived from the placed instances, not from the placer's output, so
        # the layout stays the sole holder of the placement.
        pins = {name: place.transform_pins(cells[name].pins,
            (node.pos.x, node.pos.y), node.orientation)
            for name, node in insts.items()}
        # Every placed Metal1 rect with its net, plus the cells'
        # obstruction metal, for the access-landing clearance checks. With a
        # pin-access sub-layer the signal pins live below Metal1, so only the
        # rails and the pins the library routed up to Metal1 count.
        m1_shapes = []
        for name, node in insts.items():
            for pname, rects in pins[name].items():
                if (cfg.sub_via_half is not None
                        and pname not in cfg.supply_pin_names
                        and (name, pname) not in direct_pins):
                    continue
                snet = term_net.get((name, pname))
                for rect in rects:
                    m1_shapes.append((rect, snet))
            obs = place.transform_pins({'o': cells[name].obs},
                (node.pos.x, node.pos.y), node.orientation)['o']
            for rect in obs:
                m1_shapes.append((rect, None))
        width_tries = 0
        min_w = 0   # congestion-widening floor, per row count
        while True:
            # Die width: the floorplan target, the widest packed row, or
            # (like a pad-limited chip) the port pads, one escape column
            # each.
            die_w = -(-max(round(core_area / (nrows * row_height)), packed_w,
                (escape_cols - 1) * x_pitch + extra_w, stripe_floor,
                pdn_min_w if nrows >= 2 else 0, min_w) // site) * site
            xmax = die_w // x_pitch
            # Stripe columns are chosen around the pin accesses this
            # placement forces: a tap that invalidates a terminal's every
            # access candidate deadlocks the rip-up loop (the terminal
            # cannot negotiate away).
            avoid = (route.tap_avoid_columns(signal_nets, pins, cfg,
                direct_pins) if cfg.pdn else frozenset())
            try:
                plan = plan_pdn(cfg, die_w, pins, avoid)
                routing = route.route_nets(
                    signal_nets, pins, cfg, xmax, port_nets, plan.blocked,
                    plan.tap_landings, port_edges, m1_shapes, direct_pins)
                converged = True
                break
            except route.EscapeCapacityError as e:
                # Not permanent. A top or bottom shortage is width: widen by
                # the missing columns and retry at the same row count. A side
                # shortage is rows: fall through to the next row count.
                if e.edge in ('left', 'right'):
                    if i == 4:
                        raise
                    converged = False
                    break
                extra_w += e.deficit * x_pitch * cfg.track_mult[LIDX[M4]]
            except PinAccessError:
                raise   # permanent: more rows cannot make a pin reachable
            except route.CongestionError:
                # Congestion. Adding rows relieves it for a multi-row block,
                # but a pin-dense block in little area (few cells, many
                # ports) needs routing room that only more width gives, so
                # widen and retry the same row count a bounded number of
                # times before advancing.
                if width_tries < 2:
                    min_w = die_w + die_w // 3
                    width_tries += 1
                    continue
                if i == 4:
                    raise
                converged = False
                break
        if converged:
            break
    if cfg.min_area_pass:
        route.extend_min_area(routing.nets, cfg, xmax,
            plan.blocked | routing.reserved)

    # Emit routing directly with concrete coordinates (no constraint solver, so
    # it scales to hundreds of nets).
    for net_name, (edges, term_m2) in routing.nets.items():
        emit_net_direct(layout, stack, edges, term_m2, cfg,
            routing.term_via.get(net_name), routing.term_land.get(net_name),
            sub_via_layer, routing.sub_nodes.get(net_name, ()))

    # The converged floorplan's well taps become instances like any leaf,
    # and their rails join the pin map so the rail padding sees them.
    for tname, slot in tap_slots.items():
        setattr(layout, tname, LayoutInstance(ref=well_tap_cell.layout,
            pos=Vec2I(*slot.pos), orientation=slot.orient))
        pins[tname] = place.transform_pins(tap_rects, slot.pos, slot.orient)
        rows[tname] = slot.row
    if fillers:
        for fname, (slot, width) in insert_fillers(slots, tap_slots, cells,
                cfg, fillers, die_w, tap_w).items():
            setattr(layout, fname, LayoutInstance(ref=fillers[width].layout,
                pos=Vec2I(*slot.pos), orientation=slot.orient))
            pins[fname] = place.transform_pins(filler_rects[width],
                slot.pos, slot.orient)
            rows[fname] = slot.row

    # Pad every row's rail out to the die width so the block is a flush
    # rectangle (like filler cells) and every stripe column crosses rail metal.
    pad_rails(layout, stack, pins, rows, die_w, cfg.supply_pin_names)
    supply_ports = emit_pdn(layout, stack, routing_spec, plan, pins, cfg,
        die_w)
    if cfg.pdn and cfg.pdn.ring:
        # A ring moves the supply ports onto its outer loop. Stripe-end ports
        # stand in when the die is too small to carry the ring levels.
        ring_ports = emit_ring(layout, routing_spec, cfg.pdn.ring, plan, cfg,
            die_w)
        supply_ports = ring_ports or supply_ports

    emit_ports(layout, stack, nets, pins, routing, cfg, supply_ports,
        die_w)
    return PnrResult(cfg=cfg, pins=pins, routing=routing, die_w=die_w,
        pdn=plan)


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


def emit_ports(layout, stack, nets, pins, routing, cfg, supply_ports,
        die_w):
    """Expose every top-level port of the block as a pin on emitted geometry.

    Args:
        layout: the mutable :class:`Layout` to emit into.
        stack: the :class:`StackLayers` for this PDK.
        nets: ``{name: NetInfo}`` for the whole block (ports carry a pin).
        pins: ``{inst: {pin: [Rect4I]}}``, for the supply rails.
        routing: the :class:`~.route.RoutingResult`, for the signal escapes.
        cfg: the routing grid + emitted geometry (:class:`GridConfig`).
        supply_ports: ``{supply pin name: stripe node}`` from
            :func:`emit_pdn`, empty when no stripes were emitted.
        die_w: the die width in nm, for the right-edge pads.
    """
    # A signal port was escaped to one of the four die edges (route_nets):
    # expose its pin on a pad flush with that edge, reaching port_pad_inner
    # into the block, on Metal4 for the top and bottom edges and Metal3 for
    # the sides. The parent lands on the pad and never routes over the
    # interior. vdd/vss are exposed on their stripes, or on a Metal1 rail
    # handle when the block carries no stripes.
    x_pitch, y_pitch = cfg.x_pitch, cfg.y_pitch
    die_h = cfg.n_rows * cfg.row_height
    inner = cfg.port_pad_inner
    for net_name, net in nets.items():
        if net.port_pin is None:
            continue
        if net_name in routing.nets:             # signal port
            track, edge = routing.port_escape[net_name]
            if edge in ('top', 'bottom'):
                track_x = track * x_pitch
                half_w = cfg.wire_width[LIDX[M4]] // 2
                lo, hi = ((die_h - inner, die_h) if edge == 'top'
                    else (0, inner))
                port_rect = layout % LayoutRect(layer=stack.m4, rect=Rect4I(
                    track_x - half_w, lo, track_x + half_w, hi))
            else:
                track_y = track * y_pitch
                half_w = cfg.wire_width[LIDX[M3]] // 2
                lo, hi = ((die_w - inner, die_w) if edge == 'right'
                    else (0, inner))
                port_rect = layout % LayoutRect(layer=stack.m3, rect=Rect4I(
                    lo, track_y - half_w, hi, track_y + half_w))
        else:                                    # vdd/vss
            # Expose on the supply's stripe, where a parent lands without ever
            # stacking onto a rail over the block interior. A block without
            # stripes exposes a rail handle instead: a signal pin tied to this
            # rail (e.g. a held-high RESET_B on the vdd net) is also a
            # terminal here, but the port belongs on the VDD/VSS rail, not on
            # that tied pin (which would put it on the wrong net).
            iname, pname = next((i, p) for i, p in net.terminals
                if p in cfg.supply_pin_names)
            if pname in supply_ports:
                port_rect = supply_ports[pname]
            else:
                port_rect = layout % LayoutRect(layer=stack.m1,
                    rect=largest_rect(pins[iname][pname]))
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

    The boustrophedon's shared rails appear once per abutting row, so a shared
    rail contributes two half-rail spans here.

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

    Like filler cells, this makes the block a flush rectangle and guarantees
    rail metal under every stripe column. Rows come out at slightly different
    packed widths, so without this a stripe past a short row's end would tap
    into nothing.

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



def stripe_count(extent, spec):
    """How many stripes of one level fit the die extent perpendicular to them.

    The count is even, so both supplies get the same number, and targets one
    supply pair per ``pitch``. It shrinks until the stripes fit ``extent`` with
    ``spacing`` between them and half a spacing to each die edge, and a level
    that cannot fit at least one pair returns 0.

    Args:
        extent: the die extent perpendicular to the stripes, in nm.
        spec: the :class:`PdnStripes` level.

    Returns:
        The stripe count, an even number or 0.
    """
    n = 2 * max(1, round(extent / (2 * spec.pitch)))
    while n >= 2 and n * (spec.width + spec.spacing) > extent:
        n -= 2
    return n


def rail_rows(pins, cfg):
    """Map each rail's row-boundary index to the supply pin that owns it.

    Rails sit centered on row boundaries, and the boustrophedon's shared rails
    appear as two half-rail spans that map to the same boundary.

    Args:
        pins: ``{inst: {pin: [Rect4I]}}`` die-coordinate pin rectangles.
        cfg: the routing grid + geometry (:class:`GridConfig`).

    Returns:
        ``{row boundary index: supply pin name}``.
    """
    rows = {}
    for pname in cfg.supply_pin_names:
        for y0, y1 in supply_rails(pins, pname):
            rows[round((y0 + y1) / 2 / cfg.row_height)] = pname
    return rows


def fit_cuts(width, encl, via):
    """How many via cuts fit a metal of ``width`` with ``encl`` per side."""
    return 1 + max(0, (width - 2 * encl - via.cut) // via.cut_pitch)


def tap_cuts_x(spec):
    """Cut count of one rail tap's top via, fit into the stripe width."""
    return fit_cuts(spec.width, spec.via.encl_above, spec.via)


def tap_land_dims(cfg, spec):
    """Half-extents (x, y) of a rail tap's topmost landing.

    The landing lies flat on the window metal below the stripe level: long
    enough for the top via's cut row, tall enough for its cut, and never
    smaller than the landing pads of the via below it.
    """
    via = spec.via
    span = via.cut + (tap_cuts_x(spec) - 1) * via.cut_pitch
    code = (M2, M3, M4, M5)[spec.level - 2]
    x_half = cfg.land_half_h[LIDX[code]]
    y_half = cfg.wire_width[LIDX[code]] // 2
    if cfg.via_land is not None:
        cross, along = cfg.via_land[spec.level - 2][1]
        x_half = max(x_half, along)
        y_half = max(y_half, cross)
    return (max(span // 2 + via.encl_below, x_half),
        max(via.cut // 2 + via.encl_below, y_half))


def plan_pdn(cfg, die_w, pins, avoid):
    """Fix the stripe positions and the router blockages their taps cost.

    Vertical stripe centers snap to track columns, so their rail-tap via
    stacks sit on router nodes, and a column in ``avoid`` is nudged to the
    nearest free one, since a tap that invalidates a terminal's every access
    candidate deadlocks the rip-up loop. Horizontal levels never touch the
    routing grid and snap to the manufacturing grid.

    Args:
        cfg: the routing grid + geometry (:class:`GridConfig`).
        die_w: the die width in nm.
        pins: ``{inst: {pin: [Rect4I]}}`` die-coordinate pin rectangles.
        avoid: track columns no tap may use (:func:`.route.tap_avoid_columns`).

    Returns:
        The :class:`PdnPlan`. Empty when the profile has no PDN.

    Raises:
        CongestionError: a stripe found no usable column, which a larger
            floorplan resolves.
        ValueError: the profile's levels are unusable (first level not
            vertical, levels not consecutive, too narrow for their via cuts,
            or inside the routing window).
    """
    if cfg.pdn is None or not cfg.pdn.stripes:
        return PdnPlan((), frozenset(), ())
    sp0 = cfg.pdn.stripes[0]
    if sp0.level % 2 != 1:
        raise ValueError("the first PDN stripe level must be vertical (odd), "
            "since it taps the horizontal rails")
    if sp0.width < sp0.via.cut + 2 * sp0.via.encl_above:
        raise ValueError(f"PDN stripe level {sp0.level} is too narrow to "
            "enclose one rail-tap via cut")
    for prev, sp in zip(cfg.pdn.stripes, cfg.pdn.stripes[1:]):
        if sp.level != prev.level + 1:
            raise ValueError("PDN stripe levels must be consecutive, since "
                "each level connects down to the one before it")
        if (sp.width < sp.via.cut + 2 * sp.via.encl_above
                or prev.width < sp.via.cut + 2 * sp.via.encl_below):
            raise ValueError(f"PDN stripe levels {prev.level} and {sp.level} "
                "are too narrow to enclose one crossing via cut")
    ring = cfg.pdn.ring
    if ring is not None:
        if ring.v_level % 2 != 1 or ring.h_level % 2 != 0:
            raise ValueError("the PDN ring needs an odd (vertical) v_level and "
                "an even (horizontal) h_level")
        if abs(ring.h_level - ring.v_level) != 1:
            raise ValueError("the PDN ring's two layers must be adjacent, one "
                "via joins them at the corners")
        levels = {sp.level for sp in cfg.pdn.stripes}
        if not levels.issuperset({ring.v_level, ring.h_level}):
            raise ValueError("the PDN ring reuses stripe layers, so both ring "
                "levels must carry stripes to tie into")
        if ring.offset < ring.spacing:
            raise ValueError("the PDN ring's offset must be at least its "
                "spacing, so the inner loop clears the core")
        min_span = ring.via.cut + 2 * max(ring.via.encl_above,
            ring.via.encl_below)
        spans = [ring.width] + [sp.width for sp in cfg.pdn.stripes
            if sp.level in (ring.v_level, ring.h_level)]
        if min(spans) < min_span:
            raise ValueError("the PDN ring and its stripe levels must be wide "
                "enough for the corner via to keep its enclosure")

    x_pitch, die_h = cfg.x_pitch, cfg.n_rows * cfg.row_height
    xmax = die_w // x_pitch
    window_codes = (M2, M3, M4, M5)
    levels = []
    for sp in cfg.pdn.stripes:
        vert = sp.level % 2 == 1
        extent = die_w if vert else die_h
        n = stripe_count(extent, sp)
        if n < 2:
            break   # a higher level cannot be fed without this one
        slot = extent / n
        stripes = []
        if vert:
            # Snap to track columns, keeping the stripe inside the die and
            # clear of the previous one, and nudge off avoided columns. An
            # in-window stripe level snaps to its own layer's lattice, so
            # its rail-tap stacks and blockages sit on real nodes.
            if sp.level <= 4:
                code = window_codes[sp.level - 1]
                lmult = cfg.track_mult[LIDX[code]]
                loff = cfg.track_off[LIDX[code]]
            else:
                lmult, loff = 1, 0
            col_margin = -(-(sp.width // 2) // x_pitch)
            col_sep = -(-(sp.width + sp.spacing) // x_pitch)
            reach = max(1, round(slot / (2 * x_pitch)))
            steps = max(1, reach // lmult)
            prev_col = None
            for k in range(n):
                nominal = (round(slot * (k + 0.5) / x_pitch) - loff
                    + lmult // 2) // lmult * lmult + loff
                lo = col_margin if prev_col is None else prev_col + col_sep
                col = None
                for delta in sorted((d * lmult
                        for d in range(-steps, steps + 1)), key=abs):
                    cand = nominal + delta
                    if lo <= cand <= xmax - col_margin and cand not in avoid:
                        col = cand
                        break
                if col is None:
                    raise route.CongestionError(
                        f"power stripe {k} on level {sp.level} found no "
                        "usable track column")
                prev_col = col
                stripes.append((cfg.supply_pin_names[k % 2], col * x_pitch))
        else:
            mg = cfg.manufacturing_grid
            for k in range(n):
                yc = round(slot * (k + 0.5) / mg) * mg
                stripes.append((cfg.supply_pin_names[k % 2], yc))
        levels.append(PdnLevel(sp, tuple(stripes)))

    # The first level's rail taps reserve router nodes: the via stack and its
    # landings on the vertical layers around the rail track, and the wide
    # topmost landing under the top via, whose neighborhood no wire on its
    # layer may enter. Horizontal-layer nodes on the rail track itself need no
    # entry, since a layer change is never allowed on rail tracks and the
    # router cannot reach them.
    blocked = set()
    landings = []
    if levels:
        first = levels[0]
        # The taps' wide topmost landing sits on the window metal below the
        # first stripe level. Nodes of that layer near a landing are blocked:
        # across the landing's x-extent on the rows within spacing of it.
        land_code = window_codes[first.spec.level - 2]
        li = LIDX[land_code]
        land_half_x, land_half_y = tap_land_dims(cfg, first.spec)
        spacing = cfg.wire_space[li]
        reach_x = (land_half_x + spacing + cfg.wire_ext[li] - 1) // x_pitch
        reach_y = -(-(land_half_y + spacing + cfg.wire_width[li] // 2)
            // cfg.y_pitch) - 1
        # A tap landing on a vertical window layer can be bigger than a
        # wire (its via pads), so nodes whose wire or wire end would come
        # within metal spacing of it are blocked: columns beside the tap
        # column and, along it, the rows whose end extension reaches the
        # landing.
        vert_reach = {}
        for lvl in range(1, first.spec.level):
            code = window_codes[lvl - 1]
            if code not in (M2, M4):
                continue
            i = LIDX[code]
            half_w = cfg.wire_width[i] // 2
            half_h = cfg.land_half_h[i]
            if cfg.via_land is not None:
                half_w = max(half_w, cfg.via_land[lvl - 1][1][0])
                half_h = max(half_h, cfg.via_land[lvl - 1][1][1])
                if lvl < first.spec.level - 1:
                    half_w = max(half_w, cfg.via_land[lvl][0][0])
                    half_h = max(half_h, cfg.via_land[lvl][0][1])
            vert_reach[code] = (
                (half_w + cfg.wire_space[i] + cfg.wire_width[i] // 2)
                    // x_pitch,
                (half_h + cfg.wire_space[i] + cfg.wire_ext[i])
                    // cfg.y_pitch)
        rails = rail_rows(pins, cfg)
        for pname, xc in first.stripes:
            xi = xc // x_pitch
            for row, owner in rails.items():
                if owner != pname:
                    continue
                landings.append((xc, row * cfg.row_height))
                yi = row * cfg.tracks_per_row
                for code, (rcx, rcy) in vert_reach.items():
                    for dx in range(-rcx, rcx + 1):
                        for dy in range(-rcy, rcy + 1):
                            if (0 <= xi + dx <= xmax
                                    and 0 <= yi + dy <= cfg.y_track_max):
                                blocked.add((xi + dx, yi + dy, code))
                for dx in range(-reach_x, reach_x + 1):
                    for dy in range(-reach_y, reach_y + 1):
                        if (dy and 0 <= xi + dx <= xmax
                                and 0 <= yi + dy <= cfg.y_track_max):
                            blocked.add((xi + dx, yi + dy, land_code))

    # A stripe level inside the routing window blocks its own layer along
    # the stripe's whole length: every node whose wire would come within the
    # profile's stripe spacing of the stripe metal is reserved.
    for level in levels:
        sp = level.spec
        if sp.level > 4:
            continue
        code = window_codes[sp.level - 1]
        clearance = (sp.width + cfg.wire_width[LIDX[code]]) // 2 + sp.spacing
        if code in VERT:
            for _pname, c in level.stripes:
                for xi in range(xmax + 1):
                    if abs(xi * x_pitch - c) < clearance:
                        for yi in range(cfg.y_track_max + 1):
                            blocked.add((xi, yi, code))
        else:
            for _pname, c in level.stripes:
                for yi in range(cfg.y_track_max + 1):
                    if abs(yi * cfg.y_pitch - c) < clearance:
                        for xi in range(xmax + 1):
                            blocked.add((xi, yi, code))
    return PdnPlan(tuple(levels), frozenset(blocked), tuple(landings))


def emit_pdn(layout, stack, routing_spec, plan, pins, cfg, die_w):
    """Emit the power stripes, their rail taps and their level crossings.

    The first (vertical) level taps every rail of its net where the stripe
    crosses it: a via stack from the Metal1 rail through the routing metals,
    topped by a landing wide enough for the top via's cut row. Rail current
    then travels at most half a stripe pitch on thin Metal1, which is what
    bounds IR drop as blocks grow wider, and the taps sit on rail lines where
    no signal can route, so the stripes cost almost no routing capacity. Each
    further level crosses the one below at right angles and connects with a
    cut array at every same-net crossing.

    A stripe overhangs a die edge only just far enough to enclose its
    edge-rail tap cuts, sitting in the parent's channel like the signal port
    pads do.

    Args:
        layout: the mutable :class:`Layout` to emit into.
        stack: the :class:`StackLayers` for this PDK's layers.
        routing_spec: the :class:`RoutingSpec`, for the stripe layers above
            the routing window.
        plan: the :class:`PdnPlan` fixed before routing.
        pins: ``{inst: {pin: [Rect4I]}}`` die-coordinate pin rectangles.
        cfg: the routing grid + geometry (:class:`GridConfig`).
        die_w: the die width in nm.

    Returns:
        ``{supply pin name: stripe node}`` naming one topmost-level stripe
        per supply, for the block's supply ports.
    """
    die_h = cfg.n_rows * cfg.row_height
    # The window's metal layers and vias below them, by metal level.
    window_metals = (stack.m2, stack.m3, stack.m4, stack.m5)
    window_codes = (M2, M3, M4, M5)
    window_vias = (stack.via1, stack.via2, stack.via3, stack.via4)
    port_rects = {}
    prev_level = None
    for level in plan.levels:
        sp = level.spec
        metal, via_layer = pdn_level_layers(routing_spec, sp.level)
        via = sp.via
        if prev_level is None:
            # First level: vertical stripes tapping the rails.
            rails = rail_rows(pins, cfg)
            cuts = tap_cuts_x(sp)
            span = via.cut + (cuts - 1) * via.cut_pitch
            overhang = via.encl_above + via.cut // 2
            for pname, xc in level.stripes:
                rows = [r for r, owner in rails.items() if owner == pname]
                y0 = -overhang if 0 in rows else 0
                y1 = die_h + overhang if cfg.n_rows in rows else die_h
                port_rects[pname] = layout % LayoutRect(layer=metal,
                    rect=Rect4I(xc - sp.width // 2, y0,
                        xc + sp.width // 2, y1))
                for row in rows:
                    y = row * cfg.row_height
                    # Via stack from the rail through the window metals below
                    # the stripe. Vertical-layer landings stand upright
                    # within the reserved tap column. Horizontal-layer
                    # landings lie flat, since upright they would reach into
                    # the tracks beside the rail and short a crossing wire.
                    # The topmost landing (always on a horizontal layer,
                    # since the stripe is vertical) lies flat too and is
                    # sized for the top via's cut row.
                    for lvl in range(1, sp.level):
                        code = window_codes[lvl - 1]
                        vh = cfg.via_half[lvl - 1]
                        layout % LayoutRect(layer=window_vias[lvl - 1],
                            rect=Rect4I(xc - vh, y - vh, xc + vh, y + vh))
                        half_w = cfg.wire_width[LIDX[code]] // 2
                        land_half = cfg.land_half_h[LIDX[code]]
                        if cfg.via_land is not None:
                            # The landing must enclose the via below (as its
                            # upper metal) and, unless topmost, the via above
                            # (as its lower metal).
                            cross, along = cfg.via_land[lvl - 1][1]
                            if lvl < sp.level - 1:
                                b_cross, b_along = cfg.via_land[lvl][0]
                                cross = max(cross, b_cross)
                                along = max(along, b_along)
                            half_w = max(half_w, cross)
                            land_half = max(land_half, along)
                        if lvl == sp.level - 1:
                            x_half, y_half = tap_land_dims(cfg, sp)
                            land = Rect4I(xc - x_half, y - y_half,
                                xc + x_half, y + y_half)
                        elif code in VERT:
                            land = Rect4I(xc - half_w, y - land_half,
                                xc + half_w, y + land_half)
                        else:
                            land = Rect4I(xc - land_half, y - half_w,
                                xc + land_half, y + half_w)
                        layout % LayoutRect(layer=window_metals[lvl - 1],
                            rect=land)
                    for i in range(cuts):
                        cx = xc - span // 2 + via.cut // 2 + i * via.cut_pitch
                        layout % LayoutRect(layer=via_layer, rect=Rect4I(
                            cx - via.cut // 2, y - via.cut // 2,
                            cx + via.cut // 2, y + via.cut // 2))
        else:
            # Further level: stripes crossing the previous level at right
            # angles, connected by a cut array at every same-net crossing.
            # The array is sized to fit the narrower stripe of the pair.
            vert = sp.level % 2 == 1
            encl = max(via.encl_above, via.encl_below)
            n_this = fit_cuts(sp.width, encl, via)
            n_below = fit_cuts(prev_level.spec.width, encl, via)
            nx, ny = (n_this, n_below) if vert else (n_below, n_this)
            span_x = via.cut + (nx - 1) * via.cut_pitch
            span_y = via.cut + (ny - 1) * via.cut_pitch
            for pname, c in level.stripes:
                half = sp.width // 2
                rect = (Rect4I(c - half, 0, c + half, die_h) if vert
                    else Rect4I(0, c - half, die_w, c + half))
                port_rects[pname] = layout % LayoutRect(layer=metal,
                    rect=rect)
                for below_pname, c_below in prev_level.stripes:
                    if below_pname != pname:
                        continue
                    xc, yc = (c, c_below) if vert else (c_below, c)
                    for i in range(nx):
                        for j in range(ny):
                            cx = xc - span_x // 2 + via.cut // 2 \
                                + i * via.cut_pitch
                            cy = yc - span_y // 2 + via.cut // 2 \
                                + j * via.cut_pitch
                            layout % LayoutRect(layer=via_layer, rect=Rect4I(
                                cx - via.cut // 2, cy - via.cut // 2,
                                cx + via.cut // 2, cy + via.cut // 2))
        prev_level = level
    return port_rects


def emit_via_array(layout, via_layer, via, x0, y0, x1, y1):
    """Fill an overlap region with a centered cut array the metals enclose.

    The cut count on each axis is what fits the region with via enclosure to
    spare on both sides, so the array never pokes past the enclosing metal.
    """
    encl = max(via.encl_above, via.encl_below)
    nx = fit_cuts(x1 - x0, encl, via)
    ny = fit_cuts(y1 - y0, encl, via)
    cx0 = (x0 + x1) // 2 - (via.cut + (nx - 1) * via.cut_pitch) // 2
    cy0 = (y0 + y1) // 2 - (via.cut + (ny - 1) * via.cut_pitch) // 2
    for i in range(nx):
        for j in range(ny):
            cx = cx0 + i * via.cut_pitch
            cy = cy0 + j * via.cut_pitch
            layout % LayoutRect(layer=via_layer,
                rect=Rect4I(cx, cy, cx + via.cut, cy + via.cut))


def emit_ring(layout, routing_spec, ring, plan, cfg, die_w):
    """Emit the core power ring and tie the stripes into it.

    Two concentric loops, one per supply, in the margin outside the core: the
    horizontal segments on ``h_level``, the vertical ones on ``v_level``, met
    at the corners by via arrays. Each stripe of a ring level runs a short
    riser out to its supply's segment and connects with a via array there,
    crossing the other supply's segment on the far layer without touching it.

    Args:
        layout: the mutable :class:`Layout` to emit into.
        routing_spec: the :class:`RoutingSpec` naming the PDK's layer stack.
        ring: the :class:`PdnRing` profile.
        plan: the :class:`PdnPlan` fixed before routing.
        cfg: the routing grid + geometry (:class:`GridConfig`).
        die_w: the die width in nm.

    Returns:
        ``{supply pin name: ring segment node}`` for the block's supply ports,
        or ``{}`` when the die is too small to carry the ring's stripe levels.
    """
    # The vertical stripes feed the top and bottom segments and the corners
    # carry that around to the sides, so the ring needs only its vertical
    # level present. A die too narrow even for that carries no ring.
    present = {level.spec.level for level in plan.levels}
    if ring.v_level not in present:
        return {}
    die_h = cfg.n_rows * cfg.row_height
    h_metal, _ = pdn_level_layers(routing_spec, ring.h_level)
    v_metal, _ = pdn_level_layers(routing_spec, ring.v_level)
    _, via_layer = pdn_level_layers(routing_spec, max(ring.h_level, ring.v_level))
    via = ring.via

    loops = {}
    supply_ports = {}
    for k, pname in enumerate(cfg.supply_pin_names):
        d_lo = ring.offset + k * (ring.width + ring.spacing)
        d_hi = d_lo + ring.width
        loops[pname] = (d_lo, d_hi)
        top = layout % LayoutRect(layer=h_metal, rect=Rect4I(
            -d_hi, die_h + d_lo, die_w + d_hi, die_h + d_hi))
        layout % LayoutRect(layer=h_metal, rect=Rect4I(
            -d_hi, -d_hi, die_w + d_hi, -d_lo))
        layout % LayoutRect(layer=v_metal, rect=Rect4I(
            -d_hi, -d_hi, -d_lo, die_h + d_hi))
        layout % LayoutRect(layer=v_metal, rect=Rect4I(
            die_w + d_lo, -d_hi, die_w + d_hi, die_h + d_hi))
        supply_ports[pname] = top
        for x0, y0 in ((-d_hi, die_h + d_lo), (die_w + d_lo, die_h + d_lo),
                (-d_hi, -d_hi), (die_w + d_lo, -d_hi)):
            emit_via_array(layout, via_layer, via,
                x0, y0, x0 + ring.width, y0 + ring.width)

    for level in plan.levels:
        sp = level.spec
        half = min(sp.width, ring.width) // 2
        if sp.level == ring.v_level:   # vertical stripes reach the h segments
            for pname, xc in level.stripes:
                d_lo, d_hi = loops[pname]
                layout % LayoutRect(layer=v_metal, rect=Rect4I(
                    xc - sp.width // 2, die_h, xc + sp.width // 2, die_h + d_hi))
                layout % LayoutRect(layer=v_metal, rect=Rect4I(
                    xc - sp.width // 2, -d_hi, xc + sp.width // 2, 0))
                emit_via_array(layout, via_layer, via,
                    xc - half, die_h + d_lo, xc + half, die_h + d_hi)
                emit_via_array(layout, via_layer, via,
                    xc - half, -d_hi, xc + half, -d_lo)
        elif sp.level == ring.h_level:  # horizontal stripes reach the v segments
            for pname, yc in level.stripes:
                d_lo, d_hi = loops[pname]
                layout % LayoutRect(layer=h_metal, rect=Rect4I(
                    die_w, yc - sp.width // 2, die_w + d_hi, yc + sp.width // 2))
                layout % LayoutRect(layer=h_metal, rect=Rect4I(
                    -d_hi, yc - sp.width // 2, 0, yc + sp.width // 2))
                emit_via_array(layout, via_layer, via,
                    die_w + d_lo, yc - half, die_w + d_hi, yc + half)
                emit_via_array(layout, via_layer, via,
                    -d_hi, yc - half, -d_lo, yc + half)
    return supply_ports
