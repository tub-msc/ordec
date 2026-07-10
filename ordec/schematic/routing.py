# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import numpy as np
import heapq
import sys
from collections import defaultdict
from typing import Iterable, NamedTuple
from dataclasses import dataclass

from ..core import *
from ..core.schema import SchemInstanceSubcursor
from .render import Renderer

"""Routing constraints and heuristics used by this module.

Constraints:
- Cell bodies, pins, and ports are blocked. Routed tracks and direction markers
  stay passable.
- Direction marker cells (`GRID_DIR`) restrict turning near terminal escape
  points unless the move stays aligned.
- Existing straight segments of other nets are converted into blocked moves,
  including corner-touch prevention.
Heuristics:
- A* uses Manhattan distance.
- Direction changes are penalized to prefer cleaner tracks.
- Optional congestion/history penalties discourage reuse of busy routed cells.
- Shortcut mode connects new branches to existing net paths via reverse A* and
  disables congestion cost for that shortcut search.
- On failure, one-route rip-up/reroute tries routes that blocked the search.
"""

SHORTCUT_ENABLED = True       # Enable branch-to-existing-path shortcut routing.
MAX_RIPUP_CANDIDATES = 5      # Blocking routes to try for one-route rip-up.
CONGESTION_PENALTY = 2.0      # Extra cost multiplier per routed-cell reuse.
ROUTED_BASE_PENALTY = 0.25    # Base cost for stepping onto an already routed cell.


# Grid cell type constants (int8 encoding)
# Values < GRID_BLOCKED are passable
GRID_EMPTY = 0    # passable empty cell
GRID_ROUTED = 1   # passable routed path
GRID_DIR = 2      # passable direction marker (turn restriction)
GRID_BLOCKED = 3  # impassable cell body
GRID_PIN = 4      # impassable cell pin
GRID_PORT = 5     # impassable port

class RoutingCache:
    """Per-run state for a single ``draw_connections`` invocation.

    Holds the memoized blocked-move results and the per-net change counters
    used to invalidate them. This state is local to one routing run so that
    concurrent ``draw_connections`` calls (e.g. the server building several
    schematics in parallel) do not clobber each other.
    """
    def __init__(self):
        self.cache = dict()
        self.change_count = defaultdict(int)

    def mark_changed(self, net: Net):
        self.change_count[net] += 1

    def dependency_versions(self, net: Net):
        """Return a version signature of all straight lines except ``net``."""
        if not self.change_count:
            return 0
        return sum(v for k, v in self.change_count.items() if k != net)

@dataclass
class RoutingPort:
    """Routing terminal of a Net, in raw schematic coordinates."""
    x: int
    y: int
    net: Net
    direction: D4       # unflipped rotation: North/East/South/West
    auto_wire: bool = True

@dataclass
class RoutingCell:
    """Blocked instance body, in raw schematic coordinates (lower-left)."""
    x: int
    y: int
    x_size: int
    y_size: int
    inst: SchemInstance

# A connection to route: from a net's routing terminal to an instance pin.
Connection = tuple[RoutingPort, SchemInstanceSubcursor]

class GridConn(NamedTuple):
    """A Connection projected onto the routing grid."""
    net: Net
    start: tuple[int, int]
    start_dir: D4
    end: tuple[int, int]
    end_dir: D4


# Directions (terminal facing and move directions) are the unflipped D4
# rotations North/East/South/West. A direction's unit grid step is its
# rotation applied to the "up" vector: d * Vec2R(0, 1).

# Place cells and ports on the grid
def place_cells_and_ports(grid: np.ndarray, cells: list[RoutingCell],
                          ports: Iterable[RoutingPort], width: int, height: int,
                          offset_x: int, offset_y: int
                          ) -> dict[tuple[int, int], Net | SchemInstanceSubcursor]:
    """Place cells and ports initially on the schematic grid.

    Args:
        grid: Routing grid.
        cells: Cells in the schematic.
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
        v = direction * Vec2R(0, 1)
        mx, my = x + int(v.x), y + int(v.y)
        if 0 <= my < height and 0 <= mx < width and grid[my][mx] == GRID_EMPTY:
            grid[my][mx] = GRID_DIR

    # Place cells
    for cell in cells:
        x, y = cell.x + offset_x, cell.y + offset_y
        for i in range(cell.x_size):
            for j in range(cell.y_size):
                grid[y + j][x + i] = GRID_BLOCKED
        for pin in cell.inst.symbol.all(Pin):
            sc = SchemInstanceSubcursor((cell.inst, pin))
            pos = sc.pos
            cx, cy = int(pos.x) + offset_x, int(pos.y) + offset_y
            grid[cy][cx] = GRID_PIN
            key_grid[(cx, cy)] = sc
            if 0 <= cy < height and 0 <= cx < width:
                place_direction_marker(cx, cy, sc.align.unflip())

    # Place ports
    for port in ports:
        px, py = port.x + offset_x, port.y + offset_y
        if 0 <= py < height and 0 <= px < width:
            grid[py][px] = GRID_PORT
            key_grid[(px, py)] = port.net
            place_direction_marker(px, py, port.direction)

    return key_grid

def adjust_start_end_for_direction(start, start_dir: D4, end, end_dir: D4):
    """Step the start and end points one grid cell in their facing direction.

    Args:
        start (tuple): Start point (x, y).
        start_dir (D4): Facing direction of the start port.
        end (tuple): End point (x, y).
        end_dir (D4): Facing direction of the end port.

    Returns:
        tuple: Adjusted (start, end) points.
    """
    sv = start_dir * Vec2R(0, 1)
    ev = end_dir * Vec2R(0, 1)
    return ((start[0] + int(sv.x), start[1] + int(sv.y)),
            (end[0] + int(ev.x), end[1] + int(ev.y)))

def preprocess_straight_lines(straight_lines: dict[Net, list], net: Net,
                              height: int, routing_cache: RoutingCache):
    """Preprocess straight lines into blocked movements with corner-touch prevention.

    Allows orthogonal crossings. Results are cached per ``net`` and
    invalidated when dependency versions change.

    Args:
        straight_lines (dict): Already routed paths keyed by Net.
        net (Net): The net currently being routed (excluded).
        height (int): Grid height used for key encoding.
        routing_cache (RoutingCache): Per-run memoization state.

    Returns:
        tuple: (blocked_moves set, blocked_masks dict).
    """
    # Cache is keyed by Net and invalidated when other nets change
    dep_version = routing_cache.dependency_versions(net)

    entry = routing_cache.cache.get(net)
    if entry and entry["dep_version"] == dep_version:
        blocked_masks = entry["blocked_masks"].get(height)
        if blocked_masks is None:
            blocked_masks = _blocked_masks_by_node(entry["blocked_moves"], height)
            entry["blocked_masks"][height] = blocked_masks
        return entry["blocked_moves"], blocked_masks

    blocked_moves = set()
    for key, value in straight_lines.items():
        if key != net:
            blocked_moves.update(_blocked_moves_for_segments(value))

    blocked_masks = _blocked_masks_by_node(blocked_moves, height)
    routing_cache.cache[net] = {
        "dep_version": dep_version,
        "blocked_moves": blocked_moves,
        "blocked_masks": {height: blocked_masks},
    }
    return blocked_moves, blocked_masks


def _blocked_moves_for_segments(segments):
    blocked_moves = set()
    corner_nodes = set()

    for line_start, line_end in segments:
        x1, y1 = line_start
        x2, y2 = line_end

        # Block movement along existing segments in both directions
        # to prevent parallel overlap, while orthogonal crossings remain allowed
        if x1 == x2:
            y_start, y_end = sorted((y1, y2))
            for y in range(y_start, y_end):
                a, b = (x1, y), (x1, y + 1)
                blocked_moves.add((a, b))
                blocked_moves.add((b, a))

        # Horizontal
        elif y1 == y2:
            x_start, x_end = sorted((x1, x2))
            for x in range(x_start, x_end):
                a, b = (x, y1), (x + 1, y1)
                blocked_moves.add((a, b))
                blocked_moves.add((b, a))

        # Collect corner nodes where segments meet, these need
        # all-direction blocking to prevent diagonal touch violations
        if len(segments) > 1:
            corner_nodes.add(line_start)
            corner_nodes.add(line_end)

    # Block all movement through corner nodes to prevent touching
    steps = ((0, 1), (0, -1), (1, 0), (-1, 0))
    for x, y in corner_nodes:
        for dx, dy in steps:
            n = (x + dx, y + dy)
            blocked_moves.add(((x, y), n))
            blocked_moves.add((n, (x, y)))

    return blocked_moves


# Blocked move directions are encoded as int bitmasks rather than as
# set[D4]. This is a performance optimization: with sets, per-move set
# insertion churn and D4 hashing (Enum.__hash__ is a Python-level method)
# in _blocked_masks_by_node made overall routing of larger schematics
# ~1.5x slower.
def _direction_bit(dx, dy) -> int:
    """Bit identifying the direction of a unit grid move (dx, dy):
    N=1, S=2, E=4, W=8. Returns 0 if the move is not cardinal
    (shouldn't occur)."""
    if dx == 0 and dy != 0:
        return 1 if dy > 0 else 2
    if dy == 0 and dx != 0:
        return 4 if dx > 0 else 8
    return 0


def _blocked_masks_by_node(blocked_moves, height):
    """Encode blocked moves as per-node direction bitmasks.

    Args:
        blocked_moves (set): Set of ((x1, y1), (x2, y2)) unit moves.
        height (int): Grid height used for key encoding.

    Returns:
        dict: Mapping of node key to bitmask of blocked move directions
        (_direction_bit() encoding).
    """
    blocked_masks = dict()
    for (sx, sy), (ex, ey) in blocked_moves:
        # _direction_bit() inlined: this loop runs over every blocked move of
        # every routed net, on each cache rebuild.
        dx = ex - sx
        dy = ey - sy
        if dx == 0 and dy != 0:
            bit = 1 if dy > 0 else 2
        elif dy == 0 and dx != 0:
            bit = 4 if dx > 0 else 8
        else:
            continue  # skip non-cardinal moves (shouldn't occur)
        key = sx * height + sy
        blocked_masks[key] = blocked_masks.get(key, 0) | bit
    return blocked_masks


def _point_keys(points, height):
    return {x * height + y for x, y in points}


def a_star(grid, start, end, width, height, straight_lines,
           net: Net, start_dir: D4, routing_cache, route_cell_usage=None,
           use_congestion=True, blocked_move_hits=None) -> list[tuple[int, int]]:
    """Perform A* pathfinding between a start and end point.

    Args:
        grid (np.ndarray): Schematic grid (int8 array).
        start (tuple): Point to start from (x, y).
        end (tuple): Point to reach (x, y).
        width (int): Width of the schematic.
        height (int): Height of the schematic.
        straight_lines (dict): Already calculated paths.
        net (Net): The net currently being routed.
        start_dir (D4): Facing direction of the start terminal.
        routing_cache (RoutingCache): Per-run memoization state.
        route_cell_usage (dict, optional): Routed cell usage counts.
        use_congestion (bool): Whether to apply congestion/history penalties.
        blocked_move_hits (set, optional): Blocked moves encountered during
            search, encoded as (node_key << 4) | _direction_bit().

    Returns:
        list: Calculated path as list of (x, y) tuples, or empty list on failure.
    """

    _, blocked_masks = preprocess_straight_lines(
        straight_lines, net, height, routing_cache
    )

    start_x, start_y = start
    end_x, end_y = end

    start_in_bounds = 0 <= start_x < width and 0 <= start_y < height
    end_in_bounds = 0 <= end_x < width and 0 <= end_y < height
    # Adjusted routing endpoints must stay in passable routing space.
    if not start_in_bounds or not end_in_bounds:
        return []
    if grid[start_y, start_x] >= GRID_BLOCKED or grid[end_y, end_x] >= GRID_BLOCKED:
        return []

    start_key = start_x * height + start_y
    end_key = end_x * height + end_y

    # Flat arrays indexed by node key (x * height + y) for O(1) lookup
    grid_size = width * height
    inf_score = float("inf")
    g_score = [inf_score] * grid_size
    came_from = [-1] * grid_size
    g_score[start_key] = 0.0

    # Unit grid steps and blocked-move mask bits of the four directions,
    # precomputed for the search loop.
    moves = []
    for d in (North, South, East, West):
        v = d * Vec2R(0, 1)
        dx, dy = int(v.x), int(v.y)
        moves.append((d, _direction_bit(dx, dy), dx, dy))

    # Priority queue: (f_score, node_key, direction, g_score). The direction
    # (a D4, which is not orderable) is never compared: re-pushes of a node
    # strictly improve g_score, so (f_score, node_key) pairs are unique.
    h_start = abs(start[0] - end_x) + abs(start[1] - end_y)
    open_set = [(h_start, start_key, start_dir, 0.0)]

    while open_set:
        _, current_key, current_direction, popped_g_score = heapq.heappop(open_set)
        # Skip stale entries: a better path to this node was already found
        if popped_g_score > g_score[current_key]:
            continue

        # Goal reached: reconstruct path by walking came_from chain
        if current_key == end_key:
            path = []
            key = current_key
            while came_from[key] != -1:
                path.append((key // height, key % height))
                key = came_from[key]
            path.reverse()
            return path

        # Decode flat key back to 2D coordinates
        cx = current_key // height
        cy = current_key % height
        remaining_distance = abs(cx - end_x) + abs(cy - end_y)
        block_mask = blocked_masks.get(current_key, 0)
        current_g_score = g_score[current_key]

        for d, bit, dx, dy in moves:
            # Skip if this direction is blocked by an existing route segment
            if block_mask & bit:
                if blocked_move_hits is not None:
                    blocked_move_hits.add((current_key << 4) | bit)
                continue

            nx = cx + dx
            ny = cy + dy
            if nx < 0 or nx >= width or ny < 0 or ny >= height:
                continue

            # Direction markers enforce straight escape from pins/ports. A turn
            # is allowed on this route's start marker, and on the destination
            # marker if that marker is the current route target.
            if (grid[cy, cx] == GRID_DIR and
                    current_direction is not None and
                    current_direction != d and
                    current_key != start_key and
                    current_key != end_key):
                continue

            if grid[ny, nx] >= GRID_BLOCKED:
                continue

            # Penalize direction changes proportional to remaining distance
            # to encourage straight runs near the destination
            if current_direction is not None and current_direction != d:
                direction_change_penalty = remaining_distance * 0.5
                if direction_change_penalty < 10:
                    direction_change_penalty = 10
            else:
                direction_change_penalty = 0

            # Discourage reuse of cells already occupied by other routes
            congestion_penalty = 0.0
            if use_congestion:
                if route_cell_usage is not None:
                    usage = route_cell_usage.get((nx, ny), 0)
                    if usage > 0:
                        congestion_penalty = ROUTED_BASE_PENALTY + (usage * CONGESTION_PENALTY)
                elif grid[ny, nx] == GRID_ROUTED:
                    congestion_penalty = ROUTED_BASE_PENALTY

            tentative_g_score = current_g_score + 1 + direction_change_penalty + congestion_penalty
            neighbor_key = nx * height + ny
            if tentative_g_score < g_score[neighbor_key]:
                came_from[neighbor_key] = current_key
                g_score[neighbor_key] = tentative_g_score
                f_score = tentative_g_score + abs(nx - end_x) + abs(ny - end_y)
                heapq.heappush(open_set, (f_score, neighbor_key, d,
                                          tentative_g_score))

    return []


def reverse_a_star(grid, start_points, end, width, height, straight_lines,
                   net: Net, end_dir: D4, endpoint_mapping, routing_cache,
                   route_cell_usage=None, use_congestion=True,
                   blocked_move_hits=None) -> list[tuple[int, int]]:
    """Perform reverse A* from the end point towards any of the start points.

    Args:
        grid (np.ndarray): Schematic grid (int8 array).
        start_points (list): Target points to reach.
        end (tuple): Endpoint to start search from (x, y).
        width (int): Width of the schematic.
        height (int): Height of the schematic.
        straight_lines (dict): Already calculated paths.
        net (Net): The net currently being routed.
        end_dir (D4): Facing direction of the end terminal.
        endpoint_mapping (dict): Mapping of Net to adjusted endpoint
            marker key set.
        routing_cache (RoutingCache): Per-run memoization state.
        route_cell_usage (dict, optional): Routed cell usage counts.
        use_congestion (bool): Whether to apply congestion/history penalties.
        blocked_move_hits (set, optional): Blocked moves encountered during
            search, encoded as (node_key << 4) | _direction_bit().

    Returns:
        list: Shortest path found as list of (x, y) tuples, or empty list.
    """

    _, blocked_masks = preprocess_straight_lines(
        straight_lines, net, height, routing_cache
    )

    end_x, end_y = end

    end_in_bounds = 0 <= end_x < width and 0 <= end_y < height
    # Adjusted routing endpoints must stay in passable routing space.
    if not end_in_bounds:
        return []
    if grid[end_y, end_x] >= GRID_BLOCKED:
        return []

    end_key = end_x * height + end_y
    start_points_keys = _point_keys(start_points, height)
    endpoint_keys = endpoint_mapping.get(net, set())

    # Use the closest start point for the heuristic estimate.
    # This may be inadmissible for farther start points but keeps search fast.
    min_distance = sys.maxsize
    start_point_min = start_points[0]
    for sp in start_points:
        distance = abs(end_x - sp[0]) + abs(end_y - sp[1])
        if distance < min_distance:
            start_point_min = sp
            min_distance = distance
    spm_x, spm_y = start_point_min

    grid_size = width * height
    inf_score = float("inf")
    g_score = [inf_score] * grid_size
    came_from = [-1] * grid_size
    g_score[end_key] = 0.0

    # Unit grid steps and blocked-move mask bits of the four directions,
    # precomputed for the search loop.
    moves = []
    for d in (North, South, East, West):
        v = d * Vec2R(0, 1)
        dx, dy = int(v.x), int(v.y)
        moves.append((d, _direction_bit(dx, dy), dx, dy))

    # Priority queue: (f_score, node_key, direction, g_score); the direction
    # is never compared, see a_star().
    open_set = [(min_distance, end_key, end_dir, 0.0)]

    # Track the best path found so far; search continues to find shorter ones
    best_path = []
    best_path_score = sys.maxsize

    while open_set:
        _, current_key, current_direction, popped_g_score = heapq.heappop(open_set)
        if popped_g_score > g_score[current_key]:
            continue

        # Prune paths that can't beat the current best
        current_path_length = g_score[current_key]
        if current_path_length >= best_path_score:
            continue

        # Reached one of the target start points, record if shortest so far
        if current_key in start_points_keys:
            path = []
            key = current_key
            while came_from[key] != -1:
                path.append((key // height, key % height))
                key = came_from[key]
            path.append((key // height, key % height))

            current_path_score = len(path)
            if current_path_score < best_path_score:
                best_path = path
                best_path_score = current_path_score

            continue

        cx = current_key // height
        cy = current_key % height
        remaining_distance = abs(cx - end_x) + abs(cy - end_y)
        block_mask = blocked_masks.get(current_key, 0)
        current_g_score = g_score[current_key]

        for d, bit, dx, dy in moves:
            if block_mask & bit:
                if blocked_move_hits is not None:
                    blocked_move_hits.add((current_key << 4) | bit)
                continue

            nx = cx + dx
            ny = cy + dy
            if nx < 0 or nx >= width or ny < 0 or ny >= height:
                continue

            if (grid[cy, cx] == GRID_DIR and
                    current_direction is not None and
                    current_direction != d and
                    current_key != end_key and
                    current_key not in endpoint_keys):
                continue

            if grid[ny, nx] >= GRID_BLOCKED:
                continue

            if current_direction is not None and current_direction != d:
                direction_change_penalty = remaining_distance * 0.5
                if direction_change_penalty < 10:
                    direction_change_penalty = 10
            else:
                direction_change_penalty = 0

            congestion_penalty = 0.0
            if use_congestion:
                if route_cell_usage is not None:
                    usage = route_cell_usage.get((nx, ny), 0)
                    if usage > 0:
                        congestion_penalty = ROUTED_BASE_PENALTY + (usage * CONGESTION_PENALTY)
                elif grid[ny, nx] == GRID_ROUTED:
                    congestion_penalty = ROUTED_BASE_PENALTY

            tentative_g_score = current_g_score + 1 + direction_change_penalty + congestion_penalty
            neighbor_key = nx * height + ny
            if tentative_g_score < g_score[neighbor_key]:
                came_from[neighbor_key] = current_key
                g_score[neighbor_key] = tentative_g_score
                f_score = tentative_g_score + abs(nx - spm_x) + abs(ny - spm_y)
                heapq.heappush(open_set, (f_score, neighbor_key, d,
                                          tentative_g_score))

    return best_path



def shorten_lists(list_of_lists):
    """Shorten lists by removing overlapping prefixes with the first list.

    The first list remains unchanged. Important for intersecting paths.

    Args:
        list_of_lists (list): Lists to shorten.

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


def keep_corners_and_edges(lines):
    """Filter full paths down to corners and edge points only.

    Args:
        lines (list): Calculated paths as lists of (x, y) tuples.

    Returns:
        list: Paths reduced to corner and edge vertices.
    """
    def is_corner(prev, curr, next_item):
        # A corner exists if there is a direction change
        return ((prev[0] != curr[0] and curr[1] != next_item[1]) or
                (prev[1] != curr[1] and curr[0] != next_item[0]))

    result = []
    first_line = True
    # start of consecutive lines
    starters = {line[0] for line in lines[1:]}

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


def transform_to_pairs(list_of_lists, straights):
    """Transform point lists into consecutive pairs and append to straights.

    Example: ``[(2, 1), (5, 1), (5, 2)]`` becomes
    ``[((2, 1), (5, 1)), ((5, 1), (5, 2))]``.

    Args:
        list_of_lists (list): List of point lists.
        straights (list): Accumulator list to append pairs to.

    Returns:
        list: The straights list with new pairs appended.
    """

    for lst in list_of_lists:
        # Create pairs of consecutive elements
        for i in range(len(lst) - 1):
            pair = (lst[i], lst[i + 1])
            straights.append(pair)

    return straights


def sort_connections(connections: list[Connection], offset_x: int, offset_y: int
                     ) -> tuple[dict[Net, set], list[GridConn]]:
    """Project connections onto the grid and sort them by routing difficulty.

    Higher fanout nets are routed first, then shorter distances within
    the same fanout group.

    Args:
        connections: Connections from net terminals to instance pins.
        offset_x: X offset from schematic to grid coordinates.
        offset_y: Y offset from schematic to grid coordinates.

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

    for index, (port, pin_sc) in enumerate(connections):
        start = (port.x + offset_x, port.y + offset_y)
        end_pos = pin_sc.pos
        end = (int(end_pos.x) + offset_x, int(end_pos.y) + offset_y)
        end_dir = pin_sc.align.unflip()
        gconn = GridConn(port.net, start, port.direction, end, end_dir)

        distance = euclidean_distance_sq(start, end)
        sortable_connections.append((distance, index, gconn))
        net_endpoint_mapping.setdefault(gconn.net, set()).add(end)
        # The endpoint marker is the cell one step in front of the endpoint
        ev = end_dir * Vec2R(0, 1)
        net_endpoint_marker_mapping.setdefault(gconn.net, set()).add(
            (end[0] + int(ev.x), end[1] + int(ev.y)))

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


# Draw all connections with paths
def draw_connections(grid: np.ndarray, connections: list[Connection],
                     width: int, height: int, offset_x: int, offset_y: int
                     ) -> dict[Net, list[list[tuple[int, int]]]]:
    """Route all connections and return the calculated vertices.

    Args:
        grid: Routing grid (int8 array).
        connections: Connections from net terminals to instance pins.
        width: Width of the grid.
        height: Height of the grid.
        offset_x: X offset from schematic to grid coordinates.
        offset_y: Y offset from schematic to grid coordinates.

    Returns:
        dict: Grid-space vertex paths per Net.
    """
    routing_cache = RoutingCache()
    port_drawing_dict = defaultdict(list)
    straight_lines = defaultdict(list)
    route_cell_usage = dict()
    routed_entries = []

    endpoint_marker_mapping, sorted_connections = sort_connections(
        connections, offset_x, offset_y)
    endpoint_key_mapping = {
        net: _point_keys(endpoints, height)
        for net, endpoints in endpoint_marker_mapping.items()
    }

    def append_path(net, path):
        port_drawing_dict[net].append(path)
        current_path_stripped = keep_corners_and_edges([path])
        if net not in straight_lines:
            straight_lines[net] = []
        straight_lines[net] = transform_to_pairs(
            current_path_stripped, straight_lines[net]
        )
        routing_cache.mark_changed(net)

    def rebuild_straight_lines(net):
        paths = port_drawing_dict[net]
        if paths:
            straight_lines[net] = transform_to_pairs(
                keep_corners_and_edges(paths), []
            )
        else:
            straight_lines[net] = []
        routing_cache.mark_changed(net)

    def apply_path_to_grid(path):
        path_cells = []
        for (x, y) in path:
            if grid[y][x] == GRID_EMPTY:
                grid[y][x] = GRID_ROUTED
                route_cell_usage[(x, y)] = route_cell_usage.get((x, y), 0) + 1
                path_cells.append((x, y))
            elif grid[y][x] == GRID_ROUTED:
                route_cell_usage[(x, y)] = route_cell_usage.get((x, y), 0) + 1
                path_cells.append((x, y))
        return path_cells

    def remove_path_from_grid(path_cells):
        for (x, y) in path_cells:
            usage = route_cell_usage.get((x, y), 0)
            if usage <= 1:
                route_cell_usage.pop((x, y), None)
                if grid[y][x] == GRID_ROUTED:
                    grid[y][x] = GRID_EMPTY
            else:
                route_cell_usage[(x, y)] = usage - 1

    def pop_path(entry):
        paths = port_drawing_dict[entry["net"]]
        for index, path in enumerate(paths):
            if path is entry["path"] or path == entry["path"]:
                paths.pop(index)
                rebuild_straight_lines(entry["net"])
                return index
        return None

    def insert_path(entry, index):
        paths = port_drawing_dict[entry["net"]]
        if index is None or index >= len(paths):
            paths.append(entry["path"])
        else:
            paths.insert(index, entry["path"])
        rebuild_straight_lines(entry["net"])

    def path_blocked_move_keys(path):
        blocked_keys = set()
        segments = transform_to_pairs(keep_corners_and_edges([path]), [])
        for (sx, sy), (ex, ey) in _blocked_moves_for_segments(segments):
            bit = _direction_bit(ex - sx, ey - sy)
            if bit:
                blocked_keys.add(((sx * height + sy) << 4) | bit)
        return blocked_keys

    def make_routed_entry(start, end, start_dir, end_dir, net, path, path_cells):
        return {
            "start": start,
            "end": end,
            "start_dir": start_dir,
            "end_dir": end_dir,
            "net": net,
            "path": path,
            "path_cells": path_cells,
            "blocked_move_keys": path_blocked_move_keys(path),
        }

    def routed_entry_index(entry):
        for index, routed_entry in enumerate(routed_entries):
            if routed_entry is entry:
                return index
        return None

    def blocking_ripup_candidates(blocked_move_hits):
        if not blocked_move_hits:
            return []

        scored_entries = []
        for index, entry in enumerate(routed_entries):
            hits = blocked_move_hits & entry["blocked_move_keys"]
            if hits:
                scored_entries.append((len(hits), index, entry))

        scored_entries.sort(key=lambda item: (-item[0], -item[1]))
        return [entry for _, _, entry in scored_entries[:MAX_RIPUP_CANDIDATES]]

    def try_route_connection(start, end, start_dir, end_dir, net, blocked_move_hits=None):
        start_new, end_new = adjust_start_end_for_direction(start, start_dir, end, end_dir)

        if start != end_new and end != start_new:
            shortcut_available = False
            # Shortcut mode: if this net already has routed paths, try to
            # branch off an existing path via reverse A* instead of routing
            # all the way back to the original start
            if SHORTCUT_ENABLED and len(port_drawing_dict[net]) != 0:
                shortcut_available = True
                shortcut_start_points = port_drawing_dict[net]
                # Collect interior points of existing paths as branch candidates
                path_list = list()
                for shortcut in shortcut_start_points:
                    path_list.extend(shortcut[1:-1])
                    if shortcut:
                        x, y = shortcut[0]
                        if grid[y][x] < GRID_BLOCKED:
                            path_list.append(shortcut[0])
                path_list = list(dict.fromkeys(path_list))
                if end_new in path_list:
                    # Endpoint already lies on an existing path --> trivial connection
                    path = [end_new]
                elif not path_list:
                    raise IndexError(f"Shortcut doesn't have valid branch point to connect net '{net.full_path_label()}'")
                else:
                    # Try reverse A* from endpoint to any existing path point
                    path = reverse_a_star(
                        grid, path_list, end_new, width, height,
                        straight_lines, net, end_dir,
                        endpoint_key_mapping, routing_cache, route_cell_usage,
                        use_congestion=False,
                        blocked_move_hits=blocked_move_hits
                    )
                    # Fall back to forward A* if reverse search fails
                    if not path:
                        path = a_star(
                            grid, start_new, end_new, width, height,
                            straight_lines, net, start_dir,
                            routing_cache, route_cell_usage, use_congestion=False,
                            blocked_move_hits=blocked_move_hits
                        )
            else:
                # First connection for this net, standard forward A*
                path = a_star(
                    grid, start_new, end_new, width, height,
                    straight_lines, net, start_dir,
                    routing_cache, route_cell_usage,
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
                blocking_index = routed_entry_index(blocking_entry)
                if blocking_index is None:
                    continue

                blocking_entry = routed_entries.pop(blocking_index)
                blocking_net = blocking_entry["net"]
                blocking_path_index = pop_path(blocking_entry)
                remove_path_from_grid(blocking_entry["path_cells"])

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

                    # Try to reroute the removed blocking connection
                    blocking_path, _, _ = try_route_connection(
                        blocking_entry["start"],
                        blocking_entry["end"],
                        blocking_entry["start_dir"],
                        blocking_entry["end_dir"],
                        blocking_net,
                    )
                    if blocking_path is not None:
                        # Both succeeded --> keep the new arrangement
                        blocking_cells = apply_path_to_grid(blocking_path)
                        append_path(blocking_net, blocking_path)
                        blocking_entry["path"] = blocking_path
                        blocking_entry["path_cells"] = blocking_cells
                        blocking_entry["blocked_move_keys"] = path_blocked_move_keys(blocking_path)
                        routed_entries.append(blocking_entry)
                        break

                    # Blocking route failed to reroute, undo current and restore
                    if port_drawing_dict[net]:
                        port_drawing_dict[net].pop()
                    rebuild_straight_lines(net)
                    remove_path_from_grid(path_cells)
                    current_index = routed_entry_index(current_entry)
                    if current_index is not None:
                        routed_entries.pop(current_index)
                    path = None

                # Restore the original blocking route
                restore_cells = apply_path_to_grid(blocking_entry["path"])
                insert_path(blocking_entry, blocking_path_index)
                blocking_entry["path_cells"] = restore_cells
                blocking_entry["blocked_move_keys"] = path_blocked_move_keys(blocking_entry["path"])
                if blocking_index >= len(routed_entries):
                    routed_entries.append(blocking_entry)
                else:
                    routed_entries.insert(blocking_index, blocking_entry)

            if path is not None:
                continue

        if path is None:
            print(f"Failed to connect net '{net.full_path_label()}' from "
                  f"{start_new} to {end_new}. Adding terminal taps ...")
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
    return port_drawing_dict


def calculate_vertices(outline: Rect4R, cells: list[RoutingCell],
                       ports: Iterable[RoutingPort],
                       connections: list[Connection]
                       ) -> dict[Net, list[list[Vec2R]]]:
    """Place elements on a grid and perform A* routing.

    The routing grid is twice the outline size, with the outline centered
    and shifted to positive coordinates; this schematic-to-grid offset is
    internal to this function.

    Args:
        outline: Current schematic outline.
        cells: Cells in the schematic.
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
    vertices = draw_connections(grid, connections, width * 2, height * 2,
                                offset_x, offset_y)
    return {
        net: [[Vec2R(x=x - offset_x, y=y - offset_y) for x, y in path]
              for path in paths]
        for net, paths in vertices.items()
    }


def adjust_outline_initial(node: Schematic) -> Rect4R | None:
    """Compute an initial outline enclosing all ports and instances.

    Args:
        node: Schematic containing the elements.

    Returns:
        Rect4R: Adjusted outline bounding all elements, or None for an
        empty schematic.
    """
    # Character width in schematic units (11pt Inconsolata 75% stretch * scale 0.045)
    label_char_width = 0.3
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
        direction = port.align * Vec2R(0, -1)
        outline = outline.extend(port.pos + direction * total)
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

    cells: list[RoutingCell] = list()
    for instance in node.all(SchemInstance):
        body = instance.loc_transform() * instance.symbol.outline
        cells.append(RoutingCell(
            x=int(body.lx), y=int(body.ly),
            x_size=int(body.ux - body.lx) + 1,
            y_size=int(body.uy - body.ly) + 1,
            inst=instance))

    ports: dict[Net, RoutingPort] = dict()
    for port in node.all(SchemPort):
        net = port.ref
        ports[net] = RoutingPort(
            x=int(port.pos.x), y=int(port.pos.y),
            net=net, direction=port.align.unflip(),
            auto_wire=net.auto_wire)

    # Early return when ports exist but none need auto-wiring
    if ports and not any(p.auto_wire for p in ports.values()):
        node.outline = outline
        return

    #======================
    # Determine connections
    #======================

    connections: list[Connection] = list()
    for instance in node.all(SchemInstance):
        for conn in instance.conns():
            net = conn.here
            pin_sc = SchemInstanceSubcursor((instance, conn.there))
            if net in ports:
                # External port or previously seen inter-instance net
                if ports[net].auto_wire:
                    connections.append((ports[net], pin_sc))
            else:
                # Inter-instance net: the first pin encountered becomes the
                # net's routing terminal
                pos = pin_sc.pos
                ports[net] = RoutingPort(
                    x=int(pos.x), y=int(pos.y), net=net,
                    direction=pin_sc.align.unflip(),
                    auto_wire=net.auto_wire)

    #=====================================================
    # Calculate the vertices and add them to the schematic
    #=====================================================

    if len(connections) > 0:
        vertices_dict = calculate_vertices(outline, cells, ports.values(),
                                           connections)
        for net, paths in vertices_dict.items():
            # Example: node.vss % SchemWire(vertices=[Vec2R(x=6, y=1), Vec2R(x=6, y=2)])
            for path in paths:
                for vertex in path:
                    outline = outline.extend(vertex)
                net % SchemWire(vertices=path)
    node.outline = outline


if __name__ == "__main__":
    """
    Demo of the routing core: builds a minimal schematic, routes it with
    place_cells_and_ports + draw_connections and prints the resulting grid.
    """
    # Minimal schematic providing the ORDB nodes for the routing demo.
    sym = Symbol()
    sym.S = Pin(align=South)
    sym.N = Pin(align=North)
    sym.W = Pin(align=West)
    sym.E = Pin(align=East)
    sym.place_pins(hpadding=2, vpadding=2)  # 4x4 outline, pins at edge midpoints
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
    GRID_WIDTH = 11
    GRID_HEIGHT = 20
    lx = -1
    ly = -5
    width = GRID_WIDTH * 2
    height = GRID_HEIGHT * 2
    offset_x = (GRID_WIDTH  // 2) - lx
    offset_y = (GRID_HEIGHT // 2) - ly
    grid = np.zeros((height, width), dtype=np.int8)

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

    # Connections list for drawing paths
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
    draw_connections(grid, connections, width, height, offset_x, offset_y)
    # Print grid with readable labels
    _GRID_SYMBOLS = {GRID_EMPTY: '.', GRID_ROUTED: '+', GRID_DIR: 'D',
                     GRID_BLOCKED: '#', GRID_PIN: 'P', GRID_PORT: 'O'}
    def _fmt_key(key):
        if isinstance(key, SchemInstanceSubcursor):
            return f"{key.inst().full_path_label()}.{key.node().full_path_label()}"
        return key.full_path_label()
    cell_width = 5
    for ry in range(height - 1, -1, -1):
        print(''.join(f"{_fmt_key(key_grid[(x, ry)]) if (x, ry) in key_grid else _GRID_SYMBOLS.get(grid[ry][x], '?'):<{cell_width}}"
                      for x in range(width)))
