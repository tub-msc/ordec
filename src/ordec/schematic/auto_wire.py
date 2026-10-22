# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""Routing constraints and heuristics used by this module.

Constraints:
- Cell bodies, pins, and ports are blocked. Routed tracks and direction markers
  stay passable.
- Direction marker cells (`GRID_DIR`) restrict turning near terminal escape
  points unless the move stays aligned.
- Existing straight segments of other nets are converted into blocked moves,
  including corner-touch prevention. The net's own segments block riding
  moves only (running along them would duplicate wires). Crossing and
  attaching stay allowed.
Heuristics:
- A* uses Manhattan distance.
- Direction changes are penalized to prefer cleaner tracks.
- Optional congestion/history penalties discourage reuse of busy routed cells.
- Shortcut mode connects new branches to existing net paths via reverse A* and
  disables congestion cost for that shortcut search.
- On failure, one-route rip-up/reroute tries routes that blocked the search.
  A reroute must keep its net connected: paths that anchor the net's terminal
  are rerouted in full (no shortcut), and rearrangements that strand a branch
  of the removed route are rejected.

The A* search loop and the blocked move updates are implemented in the C
extension _auto_wire (_auto_wire.c), which also defines the grid cell types,
the encoding of blocked moves and the cost constants.
"""

import math
import numpy as np
import logging
from collections import defaultdict
from typing import Iterable, NamedTuple
from dataclasses import dataclass

from ..core import *
from ..core.schema.schematic import SchemInstanceSubcursor
from .render import Renderer
from . import _auto_wire

logger = logging.getLogger(__name__)

SHORTCUT_ENABLED = True       # Enable branch-to-existing-path shortcut routing.
MAX_RIPUP_CANDIDATES = 5      # Blocking routes to try for one-route rip-up.


# Grid cell types (int8 encoding, see _auto_wire.c)
from ._auto_wire import GRID_EMPTY, GRID_ROUTED, GRID_DIR, GRID_BLOCKED, \
    GRID_PIN, GRID_PORT

class BlockedMoves:
    """Moves blocked by the routed segments of all nets, updated incrementally.

    A net's segments block moves along them (riding). For other nets, they
    additionally block all moves through their corner nodes (corner-touch
    prevention). The net being routed is blocked by its own riding moves
    only, so its branches can still cross and attach.

    The blocked directions are stored per node as direction masks, the
    number of nets blocking a move per move key (encodings: see
    _auto_wire.c). The blocked directions for the net being routed are
    determined in _auto_wire.c (block_mask). Rebuilding the blocked moves
    of all nets for every search made routing quadratic in the total wire
    length; here, appending segments only processes the new segments.
    """
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.ride_masks = defaultdict(dict) # net -> node_key -> riding directions
        self.net_masks = defaultdict(dict)  # net -> node_key -> riding+corner directions
        self.count = dict()                 # move key -> number of nets blocking it
        self.any_mask = dict()              # node_key -> directions blocked by any net

    def add(self, net: Net, segments: list, new_count: int):
        """Account for the last new_count entries of the net's segments."""
        old_count = len(segments) - new_count
        # Corner nodes are the endpoints of all segments of nets with
        # more than one segment.
        corner_points = []
        if len(segments) > 1:
            first = 0 if old_count == 1 else old_count
            corner_points = [point for segment in segments[first:] for point in segment]
        ride, own, count, any_mask = self.ride_masks[net], self.net_masks[net], \
            self.count, self.any_mask
        _auto_wire.add_moves(segments[old_count:], corner_points, ride, own, count,
            any_mask, self.width, self.height)

    def reset(self, net: Net, segments: list):
        """Replace the net's segments."""
        _auto_wire.remove_moves(self.net_masks.pop(net, {}), self.count, self.any_mask)
        self.ride_masks.pop(net, None)
        self.add(net, segments, len(segments))

    def move_keys(self, net: Net) -> set[int]:
        """Move keys of all moves blocked by the net's segments."""
        return _auto_wire.move_keys(self.net_masks.get(net, {}))

@dataclass
class RoutingPort:
    """Routing terminal of a Net, in raw schematic coordinates."""
    x: int
    y: int
    net: Net
    direction: D4       # unflipped rotation: North/East/South/West

# A connection to route: from a net's routing terminal to another terminal
# of the same net (instance pin or tap point).
Connection = tuple[RoutingPort, RoutingPort]

class GridConn(NamedTuple):
    """A Connection translated onto the routing grid."""
    net: Net
    start: tuple[int, int]
    start_dir: D4
    end: tuple[int, int]
    end_dir: D4

    @classmethod
    def from_connection(cls, conn: Connection, offset_x: int, offset_y: int
                        ) -> "GridConn":
        """Build a GridConn from a schematic-space Connection, applying the
        schematic-to-grid offset."""
        start, end = conn
        return cls(
            net=start.net,
            start=(start.x + offset_x, start.y + offset_y),
            start_dir=start.direction,
            end=(end.x + offset_x, end.y + offset_y),
            end_dir=end.direction)


# Directions (terminal facing and move directions) are the unflipped D4
# rotations North/East/South/West. A direction's unit grid step is its
# rotation applied to the "up" vector: d * Vec2R(0, 1). The steps are
# tabulated, as the Rational arithmetic is slow.
_STEPS = {d: (int(v.x), int(v.y))
    for d in (North, East, South, West) for v in [d * Vec2R(0, 1)]}

# Place cells and ports on the grid
def place_cells_and_ports(grid: np.ndarray, cells: Iterable[SchemInstance],
                          ports: Iterable[RoutingPort], width: int, height: int,
                          offset_x: int, offset_y: int
                          ) -> dict[tuple[int, int], Net | SchemInstanceSubcursor]:
    """Place cells and ports initially on the schematic grid.

    Args:
        grid: Routing grid.
        cells: Instances whose bodies and pins block the grid.
        ports: Ports in the schematic.
        width: Width of the grid.
        height: Height of the grid.
        offset_x: X offset from schematic to grid coordinates.
        offset_y: Y offset from schematic to grid coordinates.

    Returns:
        dict: Sparse mapping of grid (x, y) to the pin subcursor or port
        net at that position, for debugging/grid printing.
    """

    key_grid = dict()

    def place_direction_marker(x, y, direction: D4):
        # The empty cell one step in front of a terminal becomes a
        # turn-restricted direction marker.
        dx, dy = _STEPS[direction]
        mx, my = x + dx, y + dy
        if 0 <= my < height and 0 <= mx < width and grid[my][mx] == GRID_EMPTY:
            grid[my][mx] = GRID_DIR

    # Place cells
    for inst in cells:
        # Block the instance body: the symbol outline in schematic space,
        # covering grid cells up to and including its upper edge.
        # Transform computed once per instance rather than through
        # SchemInstanceSubcursor per pin: the Rational arithmetic is slow.
        transform = inst.loc_transform()
        body = transform * inst.symbol.outline
        x, y = int(body.lx) + offset_x, int(body.ly) + offset_y
        grid[y:y + int(body.uy - body.ly) + 1,
            x:x + int(body.ux - body.lx) + 1] = GRID_BLOCKED
        for pin in inst.symbol.all(Pin):
            pos = transform * pin.pos
            cx, cy = int(pos.x) + offset_x, int(pos.y) + offset_y
            if 0 <= cy < height and 0 <= cx < width:
                grid[cy][cx] = GRID_PIN
                key_grid[(cx, cy)] = SchemInstanceSubcursor((inst, pin))
                place_direction_marker(cx, cy, (inst.orient * pin.orient).unflip())

    # Place ports
    for port in ports:
        px, py = port.x + offset_x, port.y + offset_y
        if 0 <= py < height and 0 <= px < width:
            grid[py][px] = GRID_PORT
            key_grid[(px, py)] = port.net
            place_direction_marker(px, py, port.direction)

    return key_grid

def adjust_start_end_for_direction(start: tuple[int, int], start_dir: D4,
                                   end: tuple[int, int], end_dir: D4
                                   ) -> tuple[tuple[int, int], tuple[int, int]]:
    """Step the start and end points one grid cell in their facing direction.

    Args:
        start: Start point (x, y).
        start_dir: Facing direction of the start port.
        end: End point (x, y).
        end_dir: Facing direction of the end port.

    Returns:
        tuple: Adjusted (start, end) points.
    """
    sx, sy = _STEPS[start_dir]
    ex, ey = _STEPS[end_dir]
    return (start[0] + sx, start[1] + sy), (end[0] + ex, end[1] + ey)

def _point_keys(points, width, height):
    # Points outside the grid are left out: their node keys would alias
    # nodes of the neighboring column.
    return {x * height + y for x, y in points
        if 0 <= x < width and 0 <= y < height}


def a_star(cells: bytearray, scratch: bytearray, start: tuple[int, int],
           end: tuple[int, int], width: int, height: int, blocked: BlockedMoves,
           net: Net, start_dir: D4,
           route_cell_usage: dict | None = None, use_congestion: bool = True,
           blocked_move_hits: set | None = None) -> list[tuple[int, int]]:
    """Perform A* pathfinding between a start and end point.

    Args:
        cells: Routing grid cells, indexed by node key (x * height + y).
        scratch: Search state, see SCRATCH_PER_NODE in _auto_wire.c.
        start: Point to start from (x, y).
        end: Point to reach (x, y).
        width: Width of the grid.
        height: Height of the grid.
        blocked: Moves blocked by already routed paths.
        net: The net currently being routed.
        start_dir: Facing direction of the start terminal.
        route_cell_usage: Routed cell usage counts by node key (optional).
        use_congestion: Whether to apply congestion/history penalties.
        blocked_move_hits: If given, blocked moves encountered during search
            are added to this set as move keys (see _auto_wire.c).

    Returns:
        list: Calculated path as list of (x, y) tuples, or empty list on failure.
    """

    start_x, start_y = start
    end_x, end_y = end

    start_in_bounds = 0 <= start_x < width and 0 <= start_y < height
    end_in_bounds = 0 <= end_x < width and 0 <= end_y < height
    # Adjusted routing endpoints must stay in passable routing space.
    if not start_in_bounds or not end_in_bounds:
        return []
    start_key = start_x * height + start_y
    end_key = end_x * height + end_y
    if cells[start_key] >= GRID_BLOCKED or cells[end_key] >= GRID_BLOCKED:
        return []

    return _auto_wire.search_forward(cells, scratch, width, height, start_key,
        _STEPS[start_dir], end_key, blocked.any_mask, blocked.net_masks.get(net, {}),
        blocked.ride_masks.get(net, {}), blocked.count, route_cell_usage,
        use_congestion, blocked_move_hits)


def reverse_a_star(cells: bytearray, scratch: bytearray, start_points: dict,
                   end: tuple[int, int], width: int, height: int,
                   blocked: BlockedMoves, net: Net, end_dir: D4,
                   endpoint_mapping: dict,
                   route_cell_usage: dict | None = None,
                   use_congestion: bool = True,
                   blocked_move_hits: set | None = None) -> list[tuple[int, int]]:
    """Perform reverse A* from the end point towards any of the start points.

    Args:
        cells: Routing grid cells, indexed by node key (x * height + y).
        scratch: Search state, see SCRATCH_PER_NODE in _auto_wire.c.
        start_points: Target points to reach, as node key -> (x, y).
        end: Endpoint to start search from (x, y).
        width: Width of the grid.
        height: Height of the grid.
        blocked: Moves blocked by already routed paths.
        net: The net currently being routed.
        end_dir: Facing direction of the end terminal.
        endpoint_mapping: Mapping of Net to adjusted endpoint marker key set.
        route_cell_usage: Routed cell usage counts by node key (optional).
        use_congestion: Whether to apply congestion/history penalties.
        blocked_move_hits: If given, blocked moves encountered during search
            are added to this set as move keys (see _auto_wire.c).

    Returns:
        list: Lowest-cost path found as list of (x, y) tuples, or empty list.
    """

    end_x, end_y = end

    end_in_bounds = 0 <= end_x < width and 0 <= end_y < height
    # Adjusted routing endpoints must stay in passable routing space.
    if not end_in_bounds:
        return []
    end_key = end_x * height + end_y
    if cells[end_key] >= GRID_BLOCKED:
        return []
    endpoint_keys = endpoint_mapping.get(net, set())

    return _auto_wire.search_reverse(cells, scratch, width, height, end_key,
        _STEPS[end_dir], start_points, endpoint_keys, blocked.any_mask,
        blocked.net_masks.get(net, {}), blocked.ride_masks.get(net, {}),
        blocked.count, route_cell_usage, use_congestion, blocked_move_hits)


def shorten_lists(list_of_lists: list) -> list:
    """Shorten lists by removing overlapping prefixes with the first list.

    The first list remains unchanged. Important for intersecting paths.

    Args:
        list_of_lists: Lists to shorten.

    Returns:
        list: Shortened lists with shared prefixes removed.
    """
    if not list_of_lists:
        return []

    shortened_lists = [list_of_lists[0]]  # Keep the first list as-is

    for i in range(1, len(list_of_lists)):
        first_list = list_of_lists[0]
        current_list = list_of_lists[i]

        # Find where the current list starts to diverge from the previous one
        overlap_index = 0
        for j in range(min(len(first_list), len(current_list))):
            if first_list[j] != current_list[j]:
                break
            overlap_index += 1

        # Add the non-overlapping part of the current list to the result
        # Ensure that at least the first element of the next list is kept
        if overlap_index < len(current_list):
            shortened_lists.append(current_list[overlap_index - 1:])
        else:
            shortened_lists.append([])  # If the current list is identical to the previous, append an empty list

    return shortened_lists


def keep_corners_and_edges(lines: list) -> list:
    """Filter full paths down to corners and edge points only.

    Args:
        lines: Calculated paths as lists of (x, y) tuples.

    Returns:
        list: Paths reduced to corner and edge vertices.
    """
    def is_corner(prev, curr, next_item):
        # A corner exists if there is a direction change
        return ((prev[0] != curr[0] and curr[1] != next_item[1]) or
                (prev[1] != curr[1] and curr[0] != next_item[0]))

    result = []
    first_line = True
    # Starts of all lines: branch points must survive as vertices on the
    # path they attach to. Rip-up/reroute can reorder paths, so the
    # attaching path is not necessarily behind its host in the list.
    starters = {line[0] for line in lines}

    for line in lines:
        if len(line) <= 2:  # If the line has two or fewer points, include all points
            result.append(line)
            continue

        # The first line need the first two elements
        # If there are at least two lines available
        # --> Second point for other lines to attach
        if first_line is True and not len(lines) == 1:
            filtered_line = [line[0], line[1]]
            start_index = 2
            first_line = False
        else:
            start_index = 1
            filtered_line = [line[0]]  # Always keep the first element

        for i in range(start_index, len(line) - 1):
            if is_corner(line[i - 1], line[i], line[i + 1]):
                filtered_line.append(line[i])
            # definitely save the consecutive starts
            elif line[i] in starters:
                filtered_line.append(line[i])
        filtered_line.append(line[-1])  # Always keep the last element
        result.append(filtered_line)

    return result


def transform_to_pairs(list_of_lists: list, straights: list) -> list:
    """Transform point lists into consecutive pairs and append to straights.

    Example: ``[(2, 1), (5, 1), (5, 2)]`` becomes
    ``[((2, 1), (5, 1)), ((5, 1), (5, 2))]``.

    Args:
        list_of_lists: List of point lists.
        straights: Accumulator list to append pairs to.

    Returns:
        list: The straights list with new pairs appended.
    """

    for lst in list_of_lists:
        # Create pairs of consecutive elements
        for i in range(len(lst) - 1):
            pair = (lst[i], lst[i + 1])
            straights.append(pair)

    return straights


def sort_connections(connections: list[GridConn]
                     ) -> tuple[dict[Net, set], list[GridConn]]:
    """Sort grid connections by routing difficulty.

    Higher fanout nets are routed first, then shorter distances within
    the same fanout group.

    Args:
        connections: Grid connections to sort.

    Returns:
        tuple: (net_endpoint_marker_mapping, sorted grid connections).
    """
    # Helper function to calculate squared Euclidean distance.
    # sqrt() is monotonic, so squared distance preserves sorting order.
    def euclidean_distance_sq(point1, point2):
        dx = point1[0] - point2[0]
        dy = point1[1] - point2[1]
        return dx * dx + dy * dy

    sortable_connections = []
    net_endpoint_mapping = dict()
    net_endpoint_marker_mapping = dict()

    for index, gconn in enumerate(connections):
        distance = euclidean_distance_sq(gconn.start, gconn.end)
        sortable_connections.append((distance, index, gconn))
        net_endpoint_mapping.setdefault(gconn.net, set()).add(gconn.end)
        # The endpoint marker is the cell one step in front of the endpoint
        ex, ey = _STEPS[gconn.end_dir]
        net_endpoint_marker_mapping.setdefault(gconn.net, set()).add(
            (gconn.end[0] + ex, gconn.end[1] + ey))

    fanout_by_net = {
        net: len(endpoints)
        for net, endpoints in net_endpoint_mapping.items()
    }

    # Fanout-aware ordering: higher fanout first, then shorter distance.
    sortable_connections.sort(
        key=lambda item: (
            -fanout_by_net[item[2].net],
            item[0],
            item[1],
        )
    )

    return net_endpoint_marker_mapping, [item[2] for item in sortable_connections]


@dataclass(eq=False)
class RoutedEntry:
    """A routed connection tracked for rip-up/reroute.

    ``eq=False`` keeps identity comparison, so list operations on
    ``routed_entries`` match this exact entry rather than an
    equal-valued one.
    """
    start: tuple[int, int]
    end: tuple[int, int]
    start_dir: D4
    end_dir: D4
    net: Net
    path: list[tuple[int, int]]
    path_cells: list[int]   # node keys
    # Moves blocked by path, see path_blocked_move_keys. Computed when
    # needed for rip-up only.
    blocked_move_keys: set[int] | None = None


# Draw all connections with paths
def draw_connections(grid: np.ndarray, connections: list[GridConn],
                     width: int, height: int
                     ) -> dict[Net, list[list[tuple[int, int]]]]:
    """Route all connections and return the calculated vertices.

    Args:
        grid: Routing grid (int8 array).
        connections: Grid connections to route.
        width: Width of the grid.
        height: Height of the grid.

    Returns:
        dict: Grid-space vertex paths per Net.
    """
    # Flat copy of the grid, indexed by node key (x * height + y) like all
    # routing state. Indexing it is much faster than indexing the numpy grid.
    assert grid.dtype == np.int8
    cells = bytearray(grid.T.tobytes())
    # Search state, reused by all searches: allocating grid-sized state per
    # search dominated the routing time of large schematics.
    scratch = bytearray(width * height * _auto_wire.SCRATCH_PER_NODE)
    blocked = BlockedMoves(width, height)
    port_drawing_dict = defaultdict(list)
    straight_lines = defaultdict(list)
    # Per net, the points where further paths can branch off (see
    # try_route_connection), as node key -> (x, y) in path order.
    branch_points = defaultdict(dict)
    route_cell_usage = dict()
    routed_entries = []

    endpoint_marker_mapping, sorted_connections = sort_connections(connections)
    endpoint_key_mapping = {
        net: _point_keys(endpoints, width, height)
        for net, endpoints in endpoint_marker_mapping.items()
    }

    def add_branch_points(net, path):
        points = branch_points[net]
        for x, y in path[1:-1]:
            points.setdefault(x * height + y, (x, y))
        if path:
            x, y = path[0]
            if cells[x * height + y] < GRID_BLOCKED:
                points.setdefault(x * height + y, (x, y))

    def append_path(net, path):
        port_drawing_dict[net].append(path)
        add_branch_points(net, path)
        new_lines = transform_to_pairs(keep_corners_and_edges([path]), [])
        straight_lines[net].extend(new_lines)
        blocked.add(net, straight_lines[net], len(new_lines))

    def rebuild_straight_lines(net):
        paths = port_drawing_dict[net]
        if paths:
            straight_lines[net] = transform_to_pairs(
                keep_corners_and_edges(paths), []
            )
        else:
            straight_lines[net] = []
        blocked.reset(net, straight_lines[net])
        branch_points[net] = {}
        for path in paths:
            add_branch_points(net, path)

    def apply_path_to_grid(path):
        path_cells = []
        for (x, y) in path:
            key = x * height + y
            if cells[key] == GRID_EMPTY:
                cells[key] = GRID_ROUTED
            if cells[key] == GRID_ROUTED:
                route_cell_usage[key] = route_cell_usage.get(key, 0) + 1
                path_cells.append(key)
        return path_cells

    def remove_path_from_grid(path_cells):
        for key in path_cells:
            usage = route_cell_usage.get(key, 0)
            if usage <= 1:
                route_cell_usage.pop(key, None)
                if cells[key] == GRID_ROUTED:
                    cells[key] = GRID_EMPTY
            else:
                route_cell_usage[key] = usage - 1

    def pop_path(entry):
        paths = port_drawing_dict[entry.net]
        for index, path in enumerate(paths):
            if path is entry.path or path == entry.path:
                paths.pop(index)
                rebuild_straight_lines(entry.net)
                return index
        return None

    def insert_path(entry, index):
        paths = port_drawing_dict[entry.net]
        if index is None or index >= len(paths):
            paths.append(entry.path)
        else:
            paths.insert(index, entry.path)
        rebuild_straight_lines(entry.net)

    # Paths of a net attach where one path's first point lies on another path
    # (terminal anchor and branch junctions). Mere crossings do not connect
    # wires. Rip-up reroutes can violate this by no longer covering the branch
    # points of paths that branched off the removed route.
    def net_paths_attached(net):
        paths = port_drawing_dict[net]
        if len(paths) <= 1:
            return True
        point_sets = [set(path) for path in paths]
        pending = set(range(1, len(paths)))
        frontier = [0]
        while frontier:
            i = frontier.pop()
            attached = {
                j for j in pending
                if paths[j][0] in point_sets[i] or paths[i][0] in point_sets[j]
            }
            pending -= attached
            frontier.extend(attached)
        return not pending

    def path_blocked_move_keys(path):
        # The moves a net with only this path would block.
        segments = transform_to_pairs(keep_corners_and_edges([path]), [])
        single = BlockedMoves(width, height)
        single.add(None, segments, len(segments))
        return single.move_keys(None)

    def make_routed_entry(start, end, start_dir, end_dir, net, path, path_cells):
        return RoutedEntry(
            start=start, end=end, start_dir=start_dir, end_dir=end_dir,
            net=net, path=path, path_cells=path_cells)

    def blocking_ripup_candidates(blocked_move_hits):
        if not blocked_move_hits:
            return []

        scored_entries = []
        for index, entry in enumerate(routed_entries):
            if entry.blocked_move_keys is None:
                entry.blocked_move_keys = path_blocked_move_keys(entry.path)
            hits = blocked_move_hits & entry.blocked_move_keys
            if hits:
                scored_entries.append((len(hits), index, entry))

        scored_entries.sort(key=lambda item: (-item[0], -item[1]))
        return [entry for _, _, entry in scored_entries[:MAX_RIPUP_CANDIDATES]]

    def try_route_connection(start, end, start_dir, end_dir, net,
                             blocked_move_hits=None, allow_shortcut=True):
        start_new, end_new = adjust_start_end_for_direction(start, start_dir, end, end_dir)

        if start != end_new and end != start_new:
            # Shortcut mode: if this net already has routed paths, try to
            # branch off an existing path via reverse A* instead of routing
            # all the way back to the original start
            # Branch candidates: interior points of existing paths
            points = branch_points[net] if allow_shortcut and SHORTCUT_ENABLED else {}
            # No candidates (e.g. the net's only path joins two adjacent
            # pins, so it has no interior points): route like a first
            # connection
            shortcut_available = bool(points)
            if shortcut_available:
                # Compared by point: the node key of an end_new outside
                # the grid aliases a node of the neighboring column.
                if points.get(end_new[0] * height + end_new[1]) == end_new:
                    # Endpoint already lies on an existing path --> trivial connection
                    path = [end_new]
                else:
                    # Try reverse A* from endpoint to any existing path point
                    path = reverse_a_star(
                        cells, scratch, points, end_new, width, height,
                        blocked, net, end_dir,
                        endpoint_key_mapping, route_cell_usage,
                        use_congestion=False,
                        blocked_move_hits=blocked_move_hits
                    )
                    # Fall back to forward A* if reverse search fails
                    if not path:
                        path = a_star(
                            cells, scratch, start_new, end_new, width, height,
                            blocked, net, start_dir,
                            route_cell_usage, use_congestion=False,
                            blocked_move_hits=blocked_move_hits
                        )
            else:
                # First connection for this net, standard forward A*
                path = a_star(
                    cells, scratch, start_new, end_new, width, height,
                    blocked, net, start_dir,
                    route_cell_usage,
                    blocked_move_hits=blocked_move_hits
                )

            if not path and start_new != end_new:
                return None, start_new, end_new

            # Prepend the original pin and its escape point for non-shortcut paths
            if start_dir and not shortcut_available:
                path.insert(0, start)
                path.insert(1, start_new)
            if end_dir:
                path.append(end)
        else:
            # Start and end are adjacent --> direct connection
            path = [start, end]

        return path, start_new, end_new

    for net, start, start_dir, end, end_dir in sorted_connections:
        blocked_move_hits = set()
        path, start_new, end_new = try_route_connection(
            start, end, start_dir, end_dir, net, blocked_move_hits
        )

        # Rip-up/reroute: if routing failed, temporarily remove a
        # route that blocked the failed search and retry. If both routes can be
        # completed, keep the new arrangement; otherwise restore the original.
        if path is None and MAX_RIPUP_CANDIDATES > 0 and routed_entries:
            for blocking_entry in blocking_ripup_candidates(blocked_move_hits):
                try:
                    blocking_index = routed_entries.index(blocking_entry)
                except ValueError:
                    continue

                routed_entries.pop(blocking_index)
                blocking_net = blocking_entry.net
                blocking_path_index = pop_path(blocking_entry)
                remove_path_from_grid(blocking_entry.path_cells)

                # Retry current connection with the blocking route removed
                path, start_new, end_new = try_route_connection(
                    start, end, start_dir, end_dir, net
                )
                if path is not None:
                    path_cells = apply_path_to_grid(path)
                    append_path(net, path)
                    current_entry = make_routed_entry(
                        start, end, start_dir, end_dir, net,
                        path, path_cells
                    )
                    routed_entries.append(current_entry)

                    # Try to reroute the removed blocking connection. If the
                    # removed path anchored the net's start terminal, a shortcut
                    # reroute would only reconnect the end pin and silently
                    # leave the terminal unwired, so reroute it in full.
                    anchors_terminal = (
                        blocking_entry.path[0] == blocking_entry.start)
                    blocking_path, _, _ = try_route_connection(
                        blocking_entry.start,
                        blocking_entry.end,
                        blocking_entry.start_dir,
                        blocking_entry.end_dir,
                        blocking_net,
                        allow_shortcut=not anchors_terminal,
                    )
                    if blocking_path is not None:
                        blocking_cells = apply_path_to_grid(blocking_path)
                        append_path(blocking_net, blocking_path)
                        if net_paths_attached(blocking_net):
                            # Both succeeded --> keep the new arrangement
                            blocking_entry.path = blocking_path
                            blocking_entry.path_cells = blocking_cells
                            blocking_entry.blocked_move_keys = None
                            routed_entries.append(blocking_entry)
                            break
                        # The reroute stranded a branch of the removed route:
                        # undo it and treat it as failed.
                        port_drawing_dict[blocking_net].pop()
                        rebuild_straight_lines(blocking_net)
                        remove_path_from_grid(blocking_cells)

                    # Blocking route failed to reroute, undo current and restore
                    if port_drawing_dict[net]:
                        port_drawing_dict[net].pop()
                    rebuild_straight_lines(net)
                    remove_path_from_grid(path_cells)
                    if current_entry in routed_entries:
                        routed_entries.remove(current_entry)
                    path = None

                # Restore the original blocking route
                restore_cells = apply_path_to_grid(blocking_entry.path)
                insert_path(blocking_entry, blocking_path_index)
                blocking_entry.path_cells = restore_cells
                blocking_entry.blocked_move_keys = None
                if blocking_index >= len(routed_entries):
                    routed_entries.append(blocking_entry)
                else:
                    routed_entries.insert(blocking_index, blocking_entry)

            if path is not None:
                continue

        if path is None:
            logger.warning(
                f"Failed to connect net '{net.full_path_label()}' from "
                f"{start_new} to {end_new}; wire dropped.")
            continue

        path_cells = apply_path_to_grid(path)
        append_path(net, path)
        routed_entries.append(make_routed_entry(
            start, end, start_dir, end_dir, net, path, path_cells
        ))

    # Post-process: reduce full paths to corner/edge vertices for rendering
    for key in port_drawing_dict:
        if SHORTCUT_ENABLED:
            current_path = keep_corners_and_edges(port_drawing_dict[key])
        else:
            current_path = keep_corners_and_edges(shorten_lists(port_drawing_dict[key]))
        port_drawing_dict[key] = current_path
    grid[:] = np.frombuffer(cells, dtype=np.int8).reshape(width, height).T
    return port_drawing_dict


def calculate_vertices(outline: Rect4R, cells: Iterable[SchemInstance],
                       ports: Iterable[RoutingPort],
                       connections: list[Connection]
                       ) -> dict[Net, list[list[Vec2R]]]:
    """Place elements on a grid and perform A* routing.

    The routing grid is twice the outline size, with the outline centered
    and shifted to positive coordinates; this schematic-to-grid offset is
    internal to this function.

    Args:
        outline: Current schematic outline.
        cells: Instances in the schematic.
        ports: Ports in the schematic.
        connections: Connections from net terminals to instance pins.

    Returns:
        dict: Schematic-space vertex paths keyed by Net.
    """
    width = int(outline.ux - outline.lx)
    height = int(outline.uy - outline.ly)
    offset_x = (width  // 2) - int(outline.lx)
    offset_y = (height // 2) - int(outline.ly)
    grid = np.zeros((height * 2, width * 2), dtype=np.int8)
    place_cells_and_ports(grid, cells, ports, width * 2, height * 2,
                          offset_x, offset_y)
    gconns = [GridConn.from_connection(c, offset_x, offset_y)
              for c in connections]
    vertices = draw_connections(grid, gconns, width * 2, height * 2)
    return {
        net: [[Vec2R(x=x - offset_x, y=y - offset_y) for x, y in path]
              for path in paths]
        for net, paths in vertices.items()
    }


def tap_outline_point(tap: SchemTapPoint) -> Vec2R:
    """Outermost point of a tap point's glyph and net label, which extend
    from tap.pos toward orient * (0, 1) (see Renderer.draw_schem_tappoint)."""
    node = tap.root
    if tap.ref == node.default_supply or tap.ref == node.default_ground:
        total = 1.0  # supply/ground glyph without label
    else:
        total = Renderer.port_text_space \
            + 0.35 * len(tap.ref.full_path_label())
    return tap.pos + (tap.orient * Vec2R(0, 1)) * total

def adjust_outline_initial(node: Schematic) -> Rect4R | None:
    """Compute an initial outline enclosing all ports, tap points and
    instances (annotation blocks are placed after wiring).

    Args:
        node: Schematic containing the elements.

    Returns:
        Rect4R: Adjusted outline bounding all elements, or None for an
        empty schematic.
    """
    label_char_width = Renderer.label_char_width
    port_text_space = Renderer.port_text_space

    outline = None
    for port in node.all(SchemPort):
        if outline:
            outline = outline.extend(port.pos)
        else:
            outline = Rect4R(lx=port.pos.x, ly=port.pos.y,
                             ux=port.pos.x, uy=port.pos.y)
        # Extend outline to fit port label text
        label = port.ref.pin.full_path_label()
        text_width = len(label) * label_char_width
        total = port_text_space + text_width
        direction = port.orient * Vec2R(0, -1)
        outline = outline.extend(port.pos + direction * total)
    for tap in node.all(SchemTapPoint):
        if outline:
            outline = outline.extend(tap.pos)
        else:
            outline = Rect4R(lx=tap.pos.x, ly=tap.pos.y,
                             ux=tap.pos.x, uy=tap.pos.y)
        outline = outline.extend(tap_outline_point(tap))
    for instance in node.all(SchemInstance):
        instance_transform = instance.loc_transform()
        instance_geometry = instance_transform * instance.symbol.outline
        if outline:
            low_pos = Vec2R(x=instance_geometry.lx , y=instance_geometry.ly)
            up_pos = Vec2R(x=instance_geometry.ux , y=instance_geometry.uy)
            outline = outline.extend(low_pos)
            outline = outline.extend(up_pos)
        else:
            outline = instance_geometry
    if outline is not None:
        # Label extents are fractional; keep the outline on whole grid units,
        # which the routing grid (calculate_vertices) relies on.
        outline = Rect4R(math.floor(outline.lx), math.floor(outline.ly),
            math.ceil(outline.ux), math.ceil(outline.uy))
    return outline

def auto_wire(node: Schematic) -> None:
    """Calculate routing vertices via A* pathfinding and attach wires to the node.

    Routing starts from the node's existing ``node.outline`` if set; otherwise
    the initial outline is computed from the schematic elements. On return,
    ``node.outline`` is that initial outline extended to cover all routed wires.

    Args:
        node: Schematic to wire up.
    """
    outline = node.outline
    if outline is None:
        # No outline set on the node, so compute it from the schematic elements.
        outline = adjust_outline_initial(node)
        if outline is None:
            # adjust_outline_initial returns None for an empty schematic (no
            # ports, no instances). The remaining routing steps are then all
            # no-ops, so an empty outline at the origin is enough.
            outline = Rect4R(lx=0, ly=0, ux=0, uy=0)

    #======================
    # Build Cells and Ports
    #======================

    cells = list(node.all(SchemInstance))

    connections: list[Connection] = list()

    ports: dict[Net, RoutingPort] = dict()
    for port in node.all(SchemPort):
        net = port.ref
        ports[net] = RoutingPort(
            x=int(port.pos.x), y=int(port.pos.y),
            net=net, direction=port.orient)

    # Tap points participate in routing like ports and pins: the first
    # terminal seen for a net becomes its routing terminal, every further
    # tap is routed to that terminal like a pin. Wires attach opposite the
    # tap's glyph and label, which extend toward orient * (0, 1).
    extra_terminals: list[RoutingPort] = list()
    for tap in node.all(SchemTapPoint):
        net = tap.ref
        tap_port = RoutingPort(
            x=int(tap.pos.x), y=int(tap.pos.y),
            net=net, direction=tap.orient * R180)
        if net in ports:
            if net.auto_wire:
                connections.append((ports[net], tap_port))
                extra_terminals.append(tap_port)
        else:
            ports[net] = tap_port

    # Early return when ports exist but none need auto-wiring
    if ports and not any(net.auto_wire for net in ports):
        node.outline = outline
        return

    #======================
    # Determine connections
    #======================

    for instance in node.all(SchemInstance):
        # See place_cells_and_ports() on the per-instance transform.
        transform = instance.loc_transform()
        for conn in instance.conns():
            net = conn.here
            pin = conn.there
            pos = transform * pin.pos
            pin_port = RoutingPort(
                x=int(pos.x), y=int(pos.y), net=net,
                direction=(instance.orient * pin.orient).unflip())
            if net in ports:
                # External port/tap or previously seen inter-instance net
                if net.auto_wire:
                    connections.append((ports[net], pin_port))
            else:
                # Inter-instance net: the first pin encountered becomes the
                # net's routing terminal
                ports[net] = pin_port

    #=====================================================
    # Calculate the vertices and add them to the schematic
    #=====================================================

    if len(connections) > 0:
        vertices_dict = calculate_vertices(outline, cells,
                                           list(ports.values()) + extra_terminals,
                                           connections)
        for net, paths in vertices_dict.items():
            # Example: node.vss % SchemWire(vertices=[Vec2R(x=6, y=1), Vec2R(x=6, y=2)])
            for path in paths:
                for vertex in path:
                    outline = outline.extend(vertex)
                net % SchemWire(vertices=path)
    node.outline = outline
