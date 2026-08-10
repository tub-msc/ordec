# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Place-and-route engine tests that need no KLayout run.

The placement and routing phases work on grid coordinates and pin rectangles
alone, so most of this file builds a synthetic GridConfig and a handful of
LeafCells and asserts on what the phases decide. The remaining tests run the
full flow over the cells in tests/lib/pnr_cells.ord and read the decisions back
out of the PnrResult, which is far cheaper than checking them through the
emitted geometry. Sign-off DRC and LVS live in tests/test_ihp130_pnr.py.
"""

from dataclasses import replace

import pytest
import ordec.importer

from ordec.core import (GdsLayer, Layer, LayerStack, Layout,
    LayoutPin, R, Rect4I)
from ordec.layout import compare
from ordec.layout.digital_pnr import GridConfig, PinAccessError, run_pnr
from ordec.layout.digital_pnr import place, route
from ordec.layout.digital_pnr.flow import (LeafCell, NetInfo,
    flatten_schematic)
from ordec.layout.digital_pnr.route import M2, M3, VERT
from ordec.lib.ihp130_pnr import sg13g2_target
from .lib import pnr_cells as fx

# A grid with the sg13g2 dimensions but no PDK behind it, so the placement and
# routing tests below run without the LEF, the GDS or KLayout.
GRID = GridConfig(
    x_pitch=480, y_pitch=420, row_height=3780, tracks_per_row=9,
    via_half=95, encl=10, encl_endcap=50, manufacturing_grid=5,
    vdd_pin='VDD', vss_pin='VSS', vdd_net='vdd', vss_net='vss',
    wire_width=210, wire_ext=150, strap_half_w=105, land_half_h=345,
    m1_land_half_h=145, min_area_tracks=2, port_pad_inner=600,
    port_pad_outer=360, strap_vdd_x=-520, strap_vss_x=-1080, rail_ext=150,
    mesh_half_w=210)

CELL_W = 1920   # four x-tracks wide


def leaf(pin_x=(280, 680), pin_y=(1050, 1650)):
    """A synthetic leaf cell with one input, one output and the two rails.

    The default pin rects enclose a track intersection with room for the via
    and its endcap, so they are reachable on the grid.
    """
    x0, x1 = pin_x
    y0, y1 = pin_y
    return LeafCell(cell=None, width=CELL_W, pins={
        'A':   [Rect4I(x0, y0, x1, y1)],
        'Y':   [Rect4I(CELL_W - x1, y0, CELL_W - x0, y1)],
        'VDD': [Rect4I(0, 3600, CELL_W, 3780)],
        'VSS': [Rect4I(0, 0, CELL_W, 180)]})


def chain(count, **kwargs):
    """``(cells, nets)`` for ``count`` leaves wired output to input."""
    cells = {f'i{k}': leaf(**kwargs) for k in range(count)}
    nets = {f'n{k}': NetInfo(f'n{k}', [(f'i{k}', 'Y'), (f'i{k + 1}', 'A')])
        for k in range(count - 1)}
    return cells, nets


def place_chain(count, n_rows=2, **kwargs):
    """``(cfg, placed, nets, packed_width)`` for a placed chain."""
    cfg = replace(GRID, n_rows=n_rows)
    cells, nets = chain(count, **kwargs)
    order = place.order_cells_sa(cells, nets, cfg)
    placed, packed_w = place.place_rows(cells, order, cfg)
    return cfg, placed, nets, packed_w


def route_chain(count, n_rows=2, **kwargs):
    """``(cfg, placed, nets, RoutingResult)`` for a placed and routed chain."""
    cfg, placed, nets, packed_w = place_chain(count, n_rows, **kwargs)
    result = route.route_nets(nets, placed, cfg, xmax=packed_w // cfg.x_pitch)
    return cfg, placed, nets, result


# --- placement -------------------------------------------------------------

def test_partition_width():
    # Three equal cells over two rows split 2 + 1, not 3 + 0.
    assert place.partition_width([100, 100, 100], 2) == 200
    assert place.partition_width([100, 100, 100], 1) == 300
    # A cell wider than the balanced average still sets the floor.
    assert place.partition_width([500, 100, 100], 2) == 500
    assert place.partition_width([], 2) == 0


def test_place_rows_boustrophedon():
    cfg, placed, _nets, packed_w = place_chain(4)

    rows = {}
    for inst in placed.values():
        rows.setdefault(inst.row, []).append(inst)
    assert set(rows) == {0, 1}
    # Odd rows are mirrored, which is what lets adjacent rows share a rail.
    assert {str(i.orient) for i in rows[0]} == {'D4.R0'}
    assert {str(i.orient) for i in rows[1]} == {'D4.MX'}
    # A mirrored row is placed from its top edge, so both rows span rows 0..2.
    assert {i.pos[1] for i in rows[0]} == {0}
    assert {i.pos[1] for i in rows[1]} == {2 * cfg.row_height}
    assert packed_w == 2 * CELL_W


def test_place_rows_transforms_pin_rects():
    """A mirrored row's pin rects follow the cell into die coordinates."""
    cfg, placed, _nets, _packed_w = place_chain(4)
    for inst in placed.values():
        for rects in inst.pins.values():
            for r in rects:
                assert 0 <= r.ly and r.uy <= 2 * cfg.row_height
                assert inst.pos[0] <= r.lx and r.ux <= inst.pos[0] + CELL_W


# --- routing ---------------------------------------------------------------

def test_route_nets_connects_every_net():
    _cfg, _placed, nets, result = route_chain(4)
    assert set(result.nets) == set(nets)
    for name, net in nets.items():
        edges, term_m2 = result.nets[name]
        assert edges, f"net {name} routed to nothing"
        # Every access node is on the wire graph, and there is at most one
        # per terminal (two terminals may share a node when they agree on the
        # via geometry).
        nodes = {n for edge in edges for n in edge}
        assert 1 <= len(set(term_m2)) <= len(net.terminals)
        assert set(term_m2) <= nodes


def test_route_nets_stays_on_legal_tracks():
    cfg, _placed, _nets, result = route_chain(4)
    for edges, _term_m2 in result.nets.values():
        for a, b in edges:
            assert 0 <= a[1] <= cfg.y_track_max
            assert 0 <= b[1] <= cfg.y_track_max
            if a[2] != b[2]:
                # A layer change is a via, which may never sit on a rail track.
                assert a[:2] == b[:2]
                assert cfg.is_signal_track(a[1])
            elif a[2] in VERT:
                assert a[0] == b[0]     # vertical layers step in y
            else:
                assert a[1] == b[1]     # horizontal layers step in x


def test_pin_access_error_on_unreachable_pin():
    """A pin too narrow for a via and its enclosure is permanently unroutable,
    which the engine reports rather than working around."""
    with pytest.raises(PinAccessError, match="no routable access point"):
        route_chain(4, pin_x=(400, 600))


def test_spacing_neighbors_only_flags_facing_ends():
    # A horizontal layer conflicts one x step away, not on the parallel track.
    assert set(route.spacing_neighbors((5, 3, M3))) == {(4, 3, M3), (6, 3, M3)}
    # A vertical layer conflicts along y instead.
    assert set(route.spacing_neighbors((5, 3, M2))) == {(5, 2, M2), (5, 4, M2)}


def test_mst_edges_spans_all_terminals():
    points = [(0, 0), (10, 0), (10, 10), (0, 10)]
    edges = route.mst_edges(points)
    assert len(edges) == len(points) - 1
    reached = {0}
    for i, j in edges:
        assert (i in reached) != (j in reached)   # a tree, never a cycle
        reached |= {i, j}
    assert reached == set(range(len(points)))


def test_route_nets_avoids_mesh_blockages():
    cfg, placed, nets, packed_w = place_chain(6)
    xmax = packed_w // cfg.x_pitch
    taps = route.mesh_tap_columns(cfg, xmax,
        route.tap_avoid_columns(nets, placed, cfg))
    blocked = route.mesh_blocked_nodes(cfg, xmax, taps)
    assert blocked, "the two-row chain should carry a mesh"
    result = route.route_nets(nets, placed, cfg, xmax, blocked=blocked,
        taps=taps)
    routed = {n for edges, _term_m2 in result.nets.values()
        for edge in edges for n in edge}
    assert routed.isdisjoint(blocked)


# --- the whole flow --------------------------------------------------------

def test_deterministic():
    """Two runs of the same cell emit identical geometry.

    The engine uses sets, dicts and an RNG throughout, so this guards against
    an ordering change quietly making the output unstable.
    """
    a = run_pnr(fx.InvChain(n=8), sg13g2_target())
    b = run_pnr(fx.InvChain(n=8), sg13g2_target())
    assert compare(a.layout, b.layout) is None


@pytest.mark.parametrize("cell", [
    fx.RippleAdder(n=2),    # off-track pin access
    fx.Crossbar(n=4),       # max-fan-out nets
    fx.TiedReset(n=4),      # signal pins tied to a rail
    fx.PairChain(n=3),      # flattened composite sub-cells
], ids=["ripple_adder", "crossbar", "tied_reset", "pair_chain"])
def test_every_terminal_lands_on_its_pin(cell):
    """Each access node reaches the pin rect it serves, on or off track."""
    result = run_pnr(cell, sg13g2_target())
    cfg = result.cfg
    pin_rects = [r for inst in result.placed.values()
        for rects in inst.pins.values() for r in rects]
    for name, (_edges, term_m2) in result.routing.nets.items():
        for node in term_m2:
            via = result.routing.term_via.get(name, {}).get(node)
            x, y = via if via else (node[0] * cfg.x_pitch,
                node[1] * cfg.y_pitch)
            assert any(r.lx <= x <= r.ux and r.ly <= y <= r.uy
                for r in pin_rects), \
                f"net {name} access at ({x}, {y}) is on no pin"


def test_every_port_gets_a_pin():
    result = run_pnr(fx.InvChain(n=4), sg13g2_target())
    symbol = fx.InvChain(n=4).symbol
    pinned = {p.pin.nid for p in result.layout.all(LayoutPin)}
    assert {symbol.a.nid, symbol.y.nid, symbol.vdd.nid, symbol.vss.nid} \
        <= pinned


def test_floorplan_grows_rows():
    """A cell too wide for one row lands on several and still routes."""
    small = run_pnr(fx.InvChain(n=4), sg13g2_target())
    large = run_pnr(fx.InvChain(n=32), sg13g2_target())
    assert small.cfg.n_rows == 1
    assert large.cfg.n_rows > 1
    assert large.die_w >= small.die_w
    assert large.taps, "a multi-row block carries a power mesh"


def test_flatten_expands_composites():
    """A composite sub-cell is replaced by its own leaves, with its internal
    nets uniquified by the instance prefix and its ports rewired."""
    from ordec.lib.ihp130_pnr import is_sg13g2_leaf
    leaves, nets = flatten_schematic(fx.PairChain(n=3), is_sg13g2_leaf)

    # Three InvPairs of two inverters each, none of them composite any more.
    assert sorted(leaves) == [f"pr[{i}]/i{k}" for i in range(3) for k in (0, 1)]
    # Each pair's internal net survives as its own, prefixed net.
    assert {"pr[0]/mid", "pr[1]/mid", "pr[2]/mid"} <= set(nets)
    assert nets["pr[1]/mid"] == [("pr[1]/i0", "Y"), ("pr[1]/i1", "A")]
    # The sub-cell ports are gone, rewired onto the parent's nets.
    assert nets["nd[0]"] == [("pr[0]/i1", "Y"), ("pr[1]/i0", "A")]
    assert nets["a"] == [("pr[0]/i0", "A")]
    assert len(nets["vdd"]) == len(leaves)


def test_hierarchical_cell_routes():
    result = run_pnr(fx.PairChain(n=3), sg13g2_target())
    assert len(result.placed) == 6
    assert all(edges for edges, _term_m2 in result.routing.nets.values())


def test_supply_tied_pin_gets_its_own_net():
    """A signal pin held at a supply is routed to its cell's rail.

    The rails carry power by abutment rather than by routing, so without the
    synthesised tie net the input would be left floating.
    """
    result = run_pnr(fx.TiedReset(n=4), sg13g2_target())
    ties = {name: edges for name, (edges, _term_m2)
        in result.routing.nets.items() if name.startswith("_tie_")}
    assert set(ties) == {f"_tie_vdd_ff[{i}]_RESET_B" for i in range(4)}
    assert all(edges for edges in ties.values())


def test_shared_buses_route_under_congestion():
    """Two buses spanning every cell are the max-fan-out case the rip-up
    negotiation has to resolve."""
    result = run_pnr(fx.Crossbar(n=4), sg13g2_target())
    cfg = result.cfg
    for bus, pin in (("busA", "A0"), ("busB", "A1")):
        _edges, term_m2 = result.routing.nets[bus]
        points = [result.routing.term_via.get(bus, {}).get(node)
            or (node[0] * cfg.x_pitch, node[1] * cfg.y_pitch)
            for node in term_m2]
        reached = {name for name, inst in result.placed.items()
            for r in inst.pins[pin]
            if any(r.lx <= x <= r.ux and r.ly <= y <= r.uy
                for x, y in points)}
        assert len(reached) == 4, f"{bus} reaches {reached}"


def test_ports_escape_to_the_nearer_edge():
    """A port leaves by the edge its terminals sit nearer.

    Escaping everything to the top would make a net driven from the bottom row
    climb the whole block, only for the parent to bring it straight back down.
    """
    result = run_pnr(fx.DffArray(n=8), sg13g2_target())
    cfg = result.cfg
    escapes = {name: e for name, e in result.routing.port_escape.items() if e}
    assert escapes, "the register array should escape its ports to an edge"
    for name, (_x, edge) in escapes.items():
        _edges, term_m2 = result.routing.nets[name]
        mean_y = sum(n[1] for n in term_m2) / len(term_m2)
        expected = "top" if 2 * mean_y >= cfg.y_track_max else "bottom"
        assert edge == expected, f"{name} left by {edge}, nearer was {expected}"
    # A tall array reaches both edges rather than piling onto one.
    assert {edge for _x, edge in escapes.values()} == {"top", "bottom"}


def test_port_edges_pin_the_escape():
    """A parent that knows its floorplan can override the choice."""
    cell = fx.DffArray(n=4)
    pins = {"clk": "top", "rst": "top"}
    pins |= {f"{p}[{i}]": "top" for p in ("d", "q") for i in range(4)}
    result = run_pnr(cell, sg13g2_target(), port_edges=pins)
    edges = {edge for _x, edge in result.routing.port_escape.values()
        if _x is not None}
    assert edges == {"top"}


def test_escape_row_is_just_inside_the_rail():
    cfg = replace(GRID, n_rows=3)
    assert route.escape_row(cfg, "top") == cfg.y_track_max - 1
    assert route.escape_row(cfg, "bottom") == 1
    assert cfg.is_signal_track(route.escape_row(cfg, "top"))
    assert cfg.is_signal_track(route.escape_row(cfg, "bottom"))
    with pytest.raises(ValueError, match="must be 'top' or 'bottom'"):
        route.escape_row(cfg, "left")


# --- what the engine refuses ----------------------------------------------

def test_hand_geometry_in_the_viewgen_rejected():
    """Emitting over shapes the router cannot see would short them.

    DRC would stay clean, since overlapping same-layer shapes need no spacing,
    so only LVS would catch it. The engine refuses up front instead.
    """
    with pytest.raises(ValueError, match="already holds 2 node"):
        fx.HandGeometry().layout


def test_place_and_route_twice_rejected():
    """The second call sees the first call's geometry, so the same guard
    catches it."""
    target = sg13g2_target()
    result = run_pnr(fx.InvChain(n=2), target)
    with pytest.raises(ValueError, match="already holds"):
        run_pnr(fx.InvChain(n=2), target, layout=result.layout.mutable_copy())


def test_device_level_instance_rejected():
    """A bare transistor is neither a routing leaf nor a composite, and the
    error names the instance rather than failing on a missing attribute."""
    with pytest.raises(ValueError, match=r"instance 'm0' is a Nmos"):
        fx.DeviceLeaf().layout


def test_foreign_layer_set_rejected():
    """A layout already bound to another PDK's layers would take this
    engine's geometry on the wrong ones."""
    other = LayerStack()
    other.unit = R("1n")
    other.SomeMetal = Layer(gdslayer_shapes=GdsLayer(layer=1, data_type=0))
    foreign = Layout(ref_layers=other.freeze())
    with pytest.raises(ValueError, match="different layer set"):
        run_pnr(fx.InvChain(n=2), sg13g2_target(), layout=foreign)


def test_run_pnr_reports_its_decisions():
    result = run_pnr(fx.InvChain(n=4), sg13g2_target())
    assert len(result.placed) == 4
    assert set(result.routing.nets)
    assert result.die_w % result.cfg.x_pitch == 0
    assert result.taps == ()    # a single row needs no mesh
