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

from ordec.core import LayoutPin, Rect4I
from ordec.layout import compare
from ordec.layout.digital_pnr import GridConfig, PinAccessError, run_pnr
from ordec.layout.digital_pnr import place, route
from ordec.layout.digital_pnr.flow import LeafCell, NetInfo
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
    m1_land_half_h=145, min_area_tracks=2, port_pad_below=600,
    port_pad_above=360, strap_vdd_x=-520, strap_vss_x=-1080, rail_ext=150,
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
        # One access node per terminal, all of them on the wire graph.
        nodes = {n for edge in edges for n in edge}
        assert len(term_m2) == len(net.terminals)
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


def test_every_terminal_lands_on_its_pin():
    """Each access node reaches the pin rect it serves, on or off track."""
    result = run_pnr(fx.RippleAdder(n=2), sg13g2_target())
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


def test_run_pnr_reports_its_decisions():
    result = run_pnr(fx.InvChain(n=4), sg13g2_target())
    assert len(result.placed) == 4
    assert set(result.routing.nets)
    assert result.die_w % result.cfg.x_pitch == 0
    assert result.taps == ()    # a single row needs no mesh
