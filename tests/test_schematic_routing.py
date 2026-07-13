# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for the grid routing core (ordec.schematic.routing). Higher-level
auto_wire behavior is covered through test_renderview.py.
"""

import numpy as np

from ordec.core import *
from ordec.core.schema import SchemInstanceSubcursor
from ordec.schematic.routing import (
    RoutingPort, GridConn, place_cells_and_ports, draw_connections,
    _blocked_masks_by_node, _direction_bit,
    GRID_EMPTY, GRID_ROUTED, GRID_DIR, GRID_BLOCKED, GRID_PIN, GRID_PORT,
)


def print_grid(grid, key_grid, width, height):
    """ASCII dump of the routing grid with readable terminal labels.

    Stdout is captured by pytest, so this shows up only on test failure
    (or with pytest -s).
    """
    symbols = {GRID_EMPTY: '.', GRID_ROUTED: '+', GRID_DIR: 'D',
               GRID_BLOCKED: '#', GRID_PIN: 'P', GRID_PORT: 'O'}
    def fmt_key(key):
        if isinstance(key, SchemInstanceSubcursor):
            return f"{key.inst().full_path_label()}.{key.node().full_path_label()}"
        return key.full_path_label()
    cell_width = 5
    for ry in range(height - 1, -1, -1):
        print(''.join(
            f"{fmt_key(key_grid[(x, ry)]) if (x, ry) in key_grid else symbols.get(grid[ry][x], '?'):<{cell_width}}"
            for x in range(width)))


def test_direction_bit():
    # Documented encoding: N=1, S=2, E=4, W=8; one distinct bit per direction.
    assert _direction_bit(0, 1) == 1
    assert _direction_bit(0, -1) == 2
    assert _direction_bit(1, 0) == 4
    assert _direction_bit(-1, 0) == 8
    # Consistent with the D4 directions' unit steps.
    for d, bit in ((North, 1), (South, 2), (East, 4), (West, 8)):
        v = d * Vec2R(0, 1)
        assert _direction_bit(int(v.x), int(v.y)) == bit
    # Non-cardinal moves encode to 0.
    assert _direction_bit(0, 0) == 0
    assert _direction_bit(1, 1) == 0


def test_blocked_masks_match_direction_bit():
    # _blocked_masks_by_node() inlines _direction_bit()'s sign tests for
    # performance; this pins the two copies to each other.
    height = 7
    key = 3 * height + 2
    for step in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        move = ((3, 2), (3 + step[0], 2 + step[1]))
        assert _blocked_masks_by_node({move}, height) \
            == {key: _direction_bit(*step)}
    # Non-cardinal moves are skipped.
    assert _blocked_masks_by_node({((3, 2), (4, 3))}, height) == {}
    # Moves from the same node combine into one mask.
    moves = {((3, 2), (3, 3)), ((3, 2), (4, 2))}
    assert _blocked_masks_by_node(moves, height) == {key: 1 | 4}


def test_place_and_draw_connections():
    """Routes two stacked cells against four net terminals through the
    low-level grid API (formerly the module's __main__ demo)."""
    # Minimal schematic providing the ORDB nodes; 4x4 symbol outline with
    # pins at the edge midpoints.
    sym = Symbol()
    sym.S = Pin(align=South)
    sym.N = Pin(align=North)
    sym.W = Pin(align=West)
    sym.E = Pin(align=East)
    sym.place_pins(hpadding=2, vpadding=2)
    symf = sym.freeze()

    s = Schematic()
    s.vss = Net()
    s.vdd = Net()
    s.y = Net()
    s.a = Net()
    s.pd = SchemInstance(symf.portmap(S=s.vss, E=s.vss, W=s.a, N=s.y),
                         pos=Vec2R(4, 2))
    s.pu = SchemInstance(symf.portmap(N=s.vdd, E=s.vdd, W=s.a, S=s.y),
                         pos=Vec2R(4, 10))

    # Grid dimensions: canvas Rect4R(-1, -5, 10, 15), doubled, with the
    # schematic centered (same scheme as calculate_vertices).
    width = 11 * 2
    height = 20 * 2
    offset_x = (11 // 2) - (-1)
    offset_y = (20 // 2) - (-5)
    grid = np.zeros((height, width), dtype=np.int8)

    def gridpos(x, y):
        return int(x) + offset_x, int(y) + offset_y

    # Instances (bodies derived from their 4x4 symbol outlines) and net
    # terminals, in raw schematic coordinates
    cells = [s.pd, s.pu]
    ports = [
        RoutingPort(-1, -5, s.vss, East),
        RoutingPort(1, 15, s.vdd, East),
        RoutingPort(10, 8, s.y, West),
        RoutingPort(1, 8, s.a, East),
    ]
    connections = [
        (ports[0], s.pd.S),
        (ports[0], s.pd.E),
        (ports[1], s.pu.N),
        (ports[1], s.pu.E),
        (ports[3], s.pd.W),
        (ports[3], s.pu.W),
        (ports[2], s.pd.N),
        (ports[2], s.pu.S),
    ]

    key_grid = place_cells_and_ports(grid, cells, ports, width, height,
                                     offset_x, offset_y)

    # All terminals are placed and registered in key_grid: 4 ports + 8 pins.
    assert len(key_grid) == 12
    for port in ports:
        x, y = gridpos(port.x, port.y)
        assert grid[y][x] == GRID_PORT
        assert key_grid[(x, y)] == port.net
    for _, pin_sc in connections:
        x, y = gridpos(pin_sc.pos.x, pin_sc.pos.y)
        assert grid[y][x] == GRID_PIN
        assert key_grid[(x, y)] == pin_sc
    # Cell bodies are blocked.
    x, y = gridpos(6, 4)  # center of pd
    assert grid[y][x] == GRID_BLOCKED

    gconns = [GridConn.from_connection(c, offset_x, offset_y)
              for c in connections]
    vertices = draw_connections(grid, gconns, width, height)
    print_grid(grid, key_grid, width, height)

    # Every net is routed, with one path per connection (no failed routes).
    assert set(vertices) == {s.vss, s.vdd, s.y, s.a}
    assert all(len(paths) == 2 for paths in vertices.values())
    assert (grid == GRID_ROUTED).any()

    # Each path ends at its connection's pin; the first path of each net
    # starts at the net's routing terminal (later paths may branch off).
    ends_by_net = dict()
    for port, pin_sc in connections:
        ends_by_net.setdefault(port.net, set()).add(
            gridpos(pin_sc.pos.x, pin_sc.pos.y))
    for port in ports:
        paths = vertices[port.net]
        assert tuple(paths[0][0]) == gridpos(port.x, port.y)
        assert {tuple(p[-1]) for p in paths} == ends_by_net[port.net]


def test_ripup_keeps_terminal_connected():
    """Rip-up/reroute must not silently disconnect a net's start terminal.

    Two cell columns with two adjacent east-edge ports create congestion in
    which routing net y1 rips up y2's port-to-pin path. Rerouting that path
    in shortcut mode used to reconnect only the pin, leaving the y2 port
    silently unwired (NetMissesWiring). Paths that anchor their net's
    terminal are now rerouted in full instead.
    """
    io_sym = Symbol()
    for name, align in (('a1', West), ('y1', East), ('a2', West),
                        ('y2', East), ('vdd', North), ('vss', South)):
        io_sym[name] = Pin(align=align)
    io_sym.place_pins(hpadding=2, vpadding=2)
    iof = io_sym.freeze()

    sym = Symbol()
    sym.S = Pin(align=South)
    sym.N = Pin(align=North)
    sym.W = Pin(align=West)
    sym.E = Pin(align=East)
    sym.place_pins(hpadding=2, vpadding=2)
    symf = sym.freeze()

    s = Schematic(symbol=iof)
    for name in ('a1', 'y1', 'a2', 'y2', 'vdd', 'vss'):
        s[name] = Net(pin=iof[name])
    s.pd_l = SchemInstance(symf.portmap(W=s.a1, N=s.y1, S=s.vss, E=s.vss),
                           pos=Vec2R(2, 3))
    s.pu_l = SchemInstance(symf.portmap(W=s.a1, S=s.y1, N=s.vdd, E=s.vdd),
                           pos=Vec2R(2, 11))
    s.pd_r = SchemInstance(symf.portmap(W=s.a2, N=s.y2, S=s.vss, E=s.vss),
                           pos=Vec2R(14, 3))
    s.pu_r = SchemInstance(symf.portmap(W=s.a2, S=s.y2, N=s.vdd, E=s.vdd),
                           pos=Vec2R(14, 11))
    s.a1 % SchemPort(pos=Vec2R(0, 5), align=East)
    s.a2 % SchemPort(pos=Vec2R(0, 4), align=East)
    s.y1 % SchemPort(pos=Vec2R(20, 7), align=West)
    s.y2 % SchemPort(pos=Vec2R(20, 6), align=West)
    s.vdd % SchemPort(pos=Vec2R(4, 17), align=South)
    s.vss % SchemPort(pos=Vec2R(4, 1), align=North)

    s.auto_wire()
    s.check(add_conn_points=True, add_terminal_taps=True)

    # No net may end up with its port terminal cut off from its wired pins.
    # (Nets that fail routing entirely fall back to terminal taps on all
    # terminals, which stay label-connected and error-free.)
    assert not s.has_errors()
    # The y2 port is the terminal whose path gets ripped up while routing
    # y1. It must remain wire-connected.
    y2_vertices = {
        v for w in s.all(SchemWire.ref_idx.query(s.y2)) for v in w.vertices()
    }
    assert Vec2R(20, 6) in y2_vertices


def route_maze(open_cells, ports, conns, width=15, height=12):
    """Route conns on a grid that is fully blocked except for open_cells.
    The given terminals are placed on top by place_cells_and_ports."""
    grid = np.full((height, width), GRID_BLOCKED, dtype=np.int8)
    for x, y in open_cells:
        grid[y][x] = GRID_EMPTY
    key_grid = place_cells_and_ports(grid, [], ports, width, height, 0, 0)
    vertices = draw_connections(grid, conns, width, height)
    print_grid(grid, key_grid, width, height)
    return vertices


def route_ripup_branch_maze(cross_slot):
    """Corridor maze in which rip-up removes a path that hosts a branch.

    Net y (fanout 2) routes first: an anchor path from its port (0, 5)
    east through channel A (y=5) and down slot x=5 to pin2 (5, 1), plus a
    branch path from (5, 5) to pin1 (14, 5). Net a can only route through
    channel A cells x=2..4, fails there, and rips up y's anchor. The
    rerouted anchor must detour via channel B (y=8):

    - cross_slot=True: slot x=5 reaches up to channel B, so the detour
      descends through the branch point (5, 5).
    - cross_slot=False: the detour descends via a separate slot at x=7
      and misses the branch point entirely.

    Returns (vertices, net_y, net_a).
    """
    open_cells = [(x, 5) for x in range(1, 14)]     # channel A
    open_cells += [(x, 8) for x in range(1, 8)]     # channel B
    open_cells += [(1, 6), (1, 7)]                  # connector A-B at x=1
    if cross_slot:
        open_cells += [(5, y) for y in range(2, 8)]  # slot x=5 up to B
    else:
        open_cells += [(5, 3), (5, 4)]               # slot x=5 from A only
        open_cells += [(7, y) for y in range(2, 8)]  # slot x=7 from B
        open_cells += [(5, 2), (6, 2)]               # row joining the slots

    s = Schematic()
    s.y = Net()
    s.a = Net()
    ports = [
        RoutingPort(0, 5, s.y, East),
        RoutingPort(14, 5, s.y, West),   # y pin1
        RoutingPort(5, 1, s.y, North),   # y pin2
        RoutingPort(2, 4, s.a, North),
        RoutingPort(4, 4, s.a, North),   # a pin
    ]
    conns = [
        GridConn(s.y, (0, 5), East, (14, 5), West),
        GridConn(s.y, (0, 5), East, (5, 1), North),
        GridConn(s.a, (2, 4), North, (4, 4), North),
    ]
    return route_maze(open_cells, ports, conns), s.y, s.a


def route_ripup_overlap_maze():
    """Corridor maze in which the reroute would ride on top of its own net.

    Net y routes an anchor from its port (0, 5) through channel A (y=5)
    and down slot x=5 to pin1 (5, 1), plus a branch from (5, 5) up the
    slot to pin2 (7, 7). Net a can only route through channel A cells
    x=2..4, fails there, and rips up y's anchor. The only reroute of the
    anchor reaches pin1 by descending the slot from channel B (y=8) on
    top of the branch's segment (5, 5)-(5, 7), which would duplicate the
    wire. Riding the own net is a blocked move, so the reroute fails and
    the rip-up is rolled back.

    Returns (vertices, net_y, net_a).
    """
    open_cells = [(x, 5) for x in range(1, 6)]      # channel A
    open_cells += [(x, 8) for x in range(1, 6)]     # channel B
    open_cells += [(1, 6), (1, 7)]                  # connector A-B at x=1
    open_cells += [(5, y) for y in range(2, 8)]     # slot x=5, A and B
    open_cells += [(6, 7)]                          # approach to pin2

    s = Schematic()
    s.y = Net()
    s.a = Net()
    ports = [
        RoutingPort(0, 5, s.y, East),
        RoutingPort(5, 1, s.y, North),   # y pin1 (closer, anchor target)
        RoutingPort(7, 7, s.y, West),    # y pin2 (branch target)
        RoutingPort(2, 4, s.a, North),
        RoutingPort(4, 4, s.a, North),   # a pin
    ]
    conns = [
        GridConn(s.y, (0, 5), East, (5, 1), North),
        GridConn(s.y, (0, 5), East, (7, 7), West),
        GridConn(s.a, (2, 4), North, (4, 4), North),
    ]
    return route_maze(open_cells, ports, conns), s.y, s.a


def assert_anchor_hosts_branch(paths, ends):
    """Net y must keep both paths, with the branch path's first point an
    explicit vertex of the anchor path (a shared vertex is what connects
    wires at the schematic level, a mere crossing does not)."""
    assert len(paths) == 2
    anchor = next(p for p in paths if tuple(p[0]) == (0, 5))
    branch = next(p for p in paths if tuple(p[0]) != (0, 5))
    assert tuple(branch[0]) in {tuple(v) for v in anchor}
    assert {tuple(p[-1]) for p in paths} == ends


def test_ripup_reroute_keeps_branch_vertex():
    """The rerouted anchor re-crosses the branch point. That point must
    survive path reduction as a vertex even though rip-up reordered the
    paths (the branch now precedes its host in the net's path list)."""
    vertices, net_y, net_a = route_ripup_branch_maze(cross_slot=True)
    assert len(vertices[net_a]) == 1
    assert_anchor_hosts_branch(vertices[net_y], ends={(5, 1), (14, 5)})


def test_ripup_rejected_when_reroute_strands_branch():
    """Every possible reroute of the ripped-up anchor misses the branch
    point, so keeping it would fragment net y. The rip-up must be rejected
    and the original arrangement restored. Net a falls back to terminal
    taps instead."""
    vertices, net_y, net_a = route_ripup_branch_maze(cross_slot=False)
    assert not vertices[net_a]
    assert_anchor_hosts_branch(vertices[net_y], ends={(5, 1), (14, 5)})


def test_ripup_rejected_when_reroute_rides_own_net():
    """The only reroute of the ripped-up anchor would run on top of its own
    net's branch, duplicating the wire (OverlappingWires at the schematic
    level). The reroute must fail instead, rolling back the rip-up. Net a
    falls back to terminal taps."""
    vertices, net_y, net_a = route_ripup_overlap_maze()
    assert not vertices[net_a]
    assert_anchor_hosts_branch(vertices[net_y], ends={(5, 1), (7, 7)})
