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
    RoutingCell, RoutingPort, place_cells_and_ports, draw_connections,
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

    # Cell bodies (5x5, bottom-left corner) and net terminals, in raw
    # schematic coordinates
    cells = [
        RoutingCell(4, 2, 5, 5, s.pd),
        RoutingCell(4, 10, 5, 5, s.pu),
    ]
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

    vertices = draw_connections(grid, connections, width, height,
                                offset_x, offset_y)
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
