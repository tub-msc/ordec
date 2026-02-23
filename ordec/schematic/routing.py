# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports

import numpy as np
import heapq
import sys
from collections import defaultdict
from typing import NamedTuple
from dataclasses import dataclass

#ordec imports

from ..core import Pin, SchemPort, Vec2R, SchemInstance, Net, SchemWire, Rect4R

"""Routing constraints and heuristics used by this module.

Constraints:
- Cell bodies, pins, and ports are blocked. Routed tracks and direction markers
  stay passable.
- Direction marker cells (`GRID_DIR`) restrict turning near terminal escape
  points unless the move stays aligned.
- Existing straight segments of other nets are converted into blocked moves,
  including corner-touch prevention.
- Routing first tries local search windows and falls back to full-grid search.

Heuristics:
- A* uses Manhattan distance.
- Direction changes are penalized to prefer cleaner tracks.
- Optional congestion/history penalties discourage reuse of busy routed cells.
- Shortcut mode connects new branches to existing net paths via reverse A* and
  disables congestion cost for that shortcut search.
- A one-step rip-up/reroute retry is allowed when enabled.
"""

SHORTCUT_ENABLED = True       # Enable branch-to-existing-path shortcut routing.
MAX_RIPUP_REROUTE = 1         # Number of previous routes to temporarily rip up.
CONGESTION_PENALTY = 2.0      # Extra cost multiplier per routed-cell reuse.
ROUTED_BASE_PENALTY = 0.25    # Base cost for stepping onto an already routed cell.
WINDOW_MARGIN_STEPS = (4, 10) # Local A* window margins tried before full-grid.


# Grid cell type constants (int8 encoding)
# Values < GRID_BLOCKED are passable
GRID_EMPTY = 0    # passable empty cell
GRID_ROUTED = 1   # passable routed path
GRID_DIR = 2      # passable direction marker (turn restriction)
GRID_BLOCKED = 3  # impassable cell body
GRID_PIN = 4      # impassable cell pin
GRID_PORT = 5     # impassable port

_cache = dict()
_straight_line_change_count = defaultdict(int)
def mark_changed(start_name):
    global _straight_line_change_count
    _straight_line_change_count[start_name] += 1

class CellPin(NamedTuple):
    x: int
    y: int
    direction: str
    cell_name: str

@dataclass
class RoutingPort:
    x: int
    y: int
    name: str
    direction: str
    route: bool = True

class RoutingCell:
    def __init__(self, x, y, x_size, y_size, name, connections=None):
        self.x = x
        self.y = y
        self.x_size = x_size
        self.y_size = y_size
        self.name = name
        if connections is None:
            self.connections = dict(
                S=CellPin(x + x_size // 2, y, 'S', self.name),
                N=CellPin(x + x_size // 2, y + y_size - 1, 'N', self.name),
                W=CellPin(x, y + y_size // 2, 'W', self.name),
                E=CellPin(x + x_size - 1, y + y_size // 2, 'E', self.name),
            )
        else:
            # dict with name, position and direction
            self.connections = connections

    def __str__(self):
        ret_str = f"X= {self.x} Y= {self.y} X_SIZE= {self.x_size} Y_SIZE= {self.y_size} NAME= {self.name}\n"
        for connection_name, pin in self.connections.items():
           ret_str += f"Name: {connection_name} Inner_x: {pin.x} " \
                        f"Inner_y: {pin.y} Orientation: {pin.direction}\n"
        return ret_str


# valid moves for each direction
direction_moves = {
    'N': (0, 1),
    'S': (0, -1),
    'E': (1, 0),
    'W': (-1, 0),
}
DIRECTION_OFFSETS = tuple(direction_moves.values())  # Neighbor expansion order for A*.
DIR_NONE = -1  # Sentinel for "no previous move direction".
DIR_TO_INT = {  # Map direction vectors to compact integer IDs.
    (0, 1): 0,
    (0, -1): 1,
    (1, 0): 2,
    (-1, 0): 3,
}

# Place cells and ports on the grid
def place_cells_and_ports(grid, cells, ports, width, height):
    """Place cells and ports initially on the schematic grid.

    Args:
        grid (np.ndarray): Schematic grid.
        cells (list): Cells in the schematic.
        ports (list): Ports in the schematic.
        width (int): Width of the schematic.
        height (int): Height of the schematic.

    Returns:
        dict: Sparse mapping of (x, y) to string name for cell pins/ports.
    """

    name_grid = dict()  # sparse dict: (x, y) -> string name (for cell pins/ports)

    # Place cells
    for cell in cells:
        x, y = cell.x, cell.y
        for i in range(cell.x_size):
            for j in range(cell.y_size):
                grid[y + j][x + i] = GRID_BLOCKED
        for name, (cx, cy, direction, _) in cell.connections.items():
            grid[cy][cx] = GRID_PIN
            name_grid[(cx, cy)] = f"{cell.name}.{name}"
            if 0 <= cy < height and 0 <= cx < width:
                direction_offset_x = direction_moves[direction][0] + cx
                direction_offset_y = direction_moves[direction][1] + cy
                if 0 <= direction_offset_y < height and 0 <= direction_offset_x < width:
                    grid[direction_offset_y][direction_offset_x] = GRID_DIR

    # Place ports
    for port in ports:
        if 0 <= port.y < height and 0 <= port.x < width:
            grid[port.y][port.x] = GRID_PORT
            name_grid[(port.x, port.y)] = port.name
            direction_offset_x = direction_moves[port.direction][0] + port.x
            direction_offset_y = direction_moves[port.direction][1] + port.y
            if 0 <= direction_offset_y < height and 0 <= direction_offset_x < width:
                grid[direction_offset_y][direction_offset_x] = GRID_DIR

    return name_grid

def adjust_start_end_for_direction(start, start_dir, end, end_dir):
    """Adjust start and end points by stepping one cell in their direction.

    Args:
        start (tuple): Start point (x, y).
        start_dir (str): Direction of the start port.
        end (tuple): End point (x, y).
        end_dir (str): Direction of the end port.

    Returns:
        tuple: Adjusted (start, end) points.
    """

    # Adjust the start point based on start_dir
    if start_dir:
        dx, dy = direction_moves[start_dir]
        start = (start[0] + dx, start[1] + dy)

    # Adjust the end point based on end_dir
    if end_dir:
        dx, dy = direction_moves[end_dir]
        end = (end[0] + dx, end[1] + dy)

    return start, end

def dependency_versions(start_name):
    """Return a version signature of all straight lines except ``start_name``."""
    if not _straight_line_change_count:
        return 0
    return sum(v for k, v in _straight_line_change_count.items() if k != start_name)

def preprocess_straight_lines(straight_lines, start_name, height):
    """Preprocess straight lines into blocked movements with corner-touch prevention.

    Allows orthogonal crossings. Results are cached per ``start_name`` and
    invalidated when dependency versions change.

    Args:
        straight_lines (dict): Already routed paths keyed by net name.
        start_name (str): Name of the net currently being routed (excluded).
        height (int): Grid height used for key encoding.

    Returns:
        tuple: (blocked_moves set, blocked_masks dict).
    """
    global _cache
    # Cache is keyed by net name and invalidated when other nets change
    dep_version = dependency_versions(start_name)

    entry = _cache.get(start_name)
    if entry and entry["dep_version"] == dep_version:
        blocked_masks = entry["blocked_masks"].get(height)
        if blocked_masks is None:
            blocked_masks = _build_blocked_move_masks(entry["blocked_moves"], height)
            entry["blocked_masks"][height] = blocked_masks
        return entry["blocked_moves"], blocked_masks

    blocked_moves = set()
    corner_nodes = set()

    for key, value in straight_lines.items():
        if key == start_name:
            continue

        for line_start, line_end in value:
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
            if len(value) > 1:
                corner_nodes.add(line_start)
                corner_nodes.add(line_end)

    # Block all movement through corner nodes to prevent touching
    for x, y in corner_nodes:
        for dx, dy in DIRECTION_OFFSETS:
            n = (x + dx, y + dy)
            blocked_moves.add(((x, y), n))
            blocked_moves.add((n, (x, y)))

    blocked_masks = _build_blocked_move_masks(blocked_moves, height)
    _cache[start_name] = {
        "dep_version": dep_version,
        "blocked_moves": blocked_moves,
        "blocked_masks": {height: blocked_masks},
    }
    return blocked_moves, blocked_masks


def _build_blocked_move_masks(blocked_segments, height):
    """Encode blocked moves as per-node direction bitmasks.

    Args:
        blocked_segments (set): Set of (start_point, end_point) tuples.
        height (int): Grid height used for key encoding.

    Returns:
        dict: Mapping of node key to direction bitmask.
    """
    # Each node key maps to a 4-bit mask: bit 0=N, 1=S, 2=E, 3=W
    blocked_masks = dict()
    for start_point, end_point in blocked_segments:
        sx, sy = start_point
        ex, ey = end_point
        dx = ex - sx
        dy = ey - sy

        # Map movement delta to direction bit index
        if dx == 0:
            direction_id = 0 if dy > 0 else 1
        elif dy == 0:
            direction_id = 2 if dx > 0 else 3
        else:
            continue  # skip non-cardinal moves (shouldn't occur)

        start_key = sx * height + sy
        blocked_masks[start_key] = blocked_masks.get(start_key, 0) | (1 << direction_id)
    return blocked_masks


def _point_keys(points, height):
    return {x * height + y for x, y in points}


def _window_from_points(points, width, height, margin):
    """Create a clamped search window around points.

    Args:
        points (list): List of (x, y) points to enclose.
        width (int): Grid width.
        height (int): Grid height.
        margin (int): Margin to add around the bounding box.

    Returns:
        tuple: (min_x, max_x, min_y, max_y) clamped to grid bounds.
    """
    min_x = min(p[0] for p in points) - margin
    max_x = max(p[0] for p in points) + margin
    min_y = min(p[1] for p in points) - margin
    max_y = max(p[1] for p in points) + margin
    return (
        max(0, min_x),
        min(width - 1, max_x),
        max(0, min_y),
        min(height - 1, max_y),
    )

def a_star(grid, start, end, width, height, straight_lines,
           start_name, start_dir, endpoint_mapping,
           route_cell_usage=None, search_window=None,
           use_congestion=True):
    """Perform A* pathfinding between a start and end point.

    Args:
        grid (np.ndarray): Schematic grid (int8 array).
        start (tuple): Point to start from (x, y).
        end (tuple): Point to reach (x, y).
        width (int): Width of the schematic.
        height (int): Height of the schematic.
        straight_lines (dict): Already calculated paths.
        start_name (str): Name of the starting port.
        start_dir (tuple): Direction vector to start from.
        endpoint_mapping (dict): Mapping of start name to endpoint key set.
        route_cell_usage (dict, optional): Routed cell usage counts.
        search_window (tuple, optional): (min_x, max_x, min_y, max_y) bounds.
        use_congestion (bool): Whether to apply congestion/history penalties.

    Returns:
        list: Calculated path as list of (x, y) tuples, or empty list on failure.
    """

    _, blocked_masks = preprocess_straight_lines(
        straight_lines, start_name, height
    )
    endpoint_keys = endpoint_mapping[start_name]

    end_x, end_y = end
    start_key = start[0] * height + start[1]
    end_key = end_x * height + end_y
    start_direction = DIR_TO_INT.get(start_dir, DIR_NONE)

    # Flat arrays indexed by node key (x * height + y) for O(1) lookup
    grid_size = width * height
    inf_score = float("inf")
    g_score = [inf_score] * grid_size
    came_from = [-1] * grid_size
    g_score[start_key] = 0.0

    # Priority queue: (f_score, node_key, direction_id, g_score)
    h_start = abs(start[0] - end_x) + abs(start[1] - end_y)
    open_set = [(h_start, start_key, start_direction, 0.0)]

    has_search_window = search_window is not None
    if has_search_window:
        min_x, max_x, min_y, max_y = search_window

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

        for direction_id, (dx, dy) in enumerate(DIRECTION_OFFSETS):
            # Skip if this direction is blocked by an existing route segment
            if block_mask & (1 << direction_id):
                continue

            nx = cx + dx
            ny = cy + dy
            if nx < 0 or nx >= width or ny < 0 or ny >= height:
                continue
            if has_search_window and (nx < min_x or nx > max_x or ny < min_y or ny > max_y):
                continue

            # Direction markers enforce straight escape from pins/ports:
            # only allow turning if we're at the start or an endpoint
            if (grid[cy, cx] == GRID_DIR and
                    current_direction != DIR_NONE and
                    current_direction != direction_id and
                    current_key != start_key and
                    current_key not in endpoint_keys):
                continue

            if grid[ny, nx] >= GRID_BLOCKED:
                continue

            # Penalize direction changes proportional to remaining distance
            # to encourage straight runs near the destination
            if current_direction != DIR_NONE and current_direction != direction_id:
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
                heapq.heappush(open_set, (f_score, neighbor_key, direction_id,
                                          tentative_g_score))

    return []


def reverse_a_star(grid, start_points, end, width, height, straight_lines, start_name, end_dir,
                   endpoint_mapping, route_cell_usage=None, search_window=None,
                   use_congestion=True):
    """Perform reverse A* from the end point towards any of the start points.

    Args:
        grid (np.ndarray): Schematic grid (int8 array).
        start_points (list): Target points to reach.
        end (tuple): Endpoint to start search from (x, y).
        width (int): Width of the schematic.
        height (int): Height of the schematic.
        straight_lines (dict): Already calculated paths.
        start_name (str): Name of the starting port.
        end_dir (tuple): Direction vector to end with.
        endpoint_mapping (dict): Mapping of start name to endpoint key set.
        route_cell_usage (dict, optional): Routed cell usage counts.
        search_window (tuple, optional): (min_x, max_x, min_y, max_y) bounds.
        use_congestion (bool): Whether to apply congestion/history penalties.

    Returns:
        list: Shortest path found as list of (x, y) tuples, or empty list.
    """

    _, blocked_masks = preprocess_straight_lines(
        straight_lines, start_name, height
    )
    endpoint_keys = endpoint_mapping[start_name]

    end_x, end_y = end
    end_key = end_x * height + end_y
    end_direction = DIR_TO_INT.get(end_dir, DIR_NONE)
    start_points_keys = _point_keys(start_points, height)

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
    open_set = [(min_distance, end_key, end_direction, 0.0)]

    has_search_window = search_window is not None
    if has_search_window:
        min_x, max_x, min_y, max_y = search_window

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

        for direction_id, (dx, dy) in enumerate(DIRECTION_OFFSETS):
            if block_mask & (1 << direction_id):
                continue

            nx = cx + dx
            ny = cy + dy
            if nx < 0 or nx >= width or ny < 0 or ny >= height:
                continue
            if has_search_window and (nx < min_x or nx > max_x or ny < min_y or ny > max_y):
                continue

            if (grid[cy, cx] == GRID_DIR and
                    current_direction != DIR_NONE and
                    current_direction != direction_id and
                    current_key != end_key and
                    current_key in endpoint_keys):
                continue

            if grid[ny, nx] >= GRID_BLOCKED:
                continue

            if current_direction != DIR_NONE and current_direction != direction_id:
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
                heapq.heappush(open_set, (f_score, neighbor_key, direction_id,
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


def sort_connections(connections, name_grid=None):
    """Sort connections by routing difficulty.

    Higher fanout nets are routed first, then shorter distances within
    the same fanout group.

    Args:
        connections (list): Connections between subcells.
        name_grid (dict, optional): Sparse mapping of (x, y) to string name.

    Returns:
        tuple: (name_endpoint_mapping, sorted_connections).
    """
    # Helper function to calculate squared Euclidean distance.
    # sqrt() is monotonic, so squared distance preserves sorting order.
    def euclidean_distance_sq(point1, point2):
        dx = point1[0] - point2[0]
        dy = point1[1] - point2[1]
        return dx * dx + dy * dy

    sortable_connections = []
    name_endpoint_mapping = dict()

    for index, connection in enumerate(connections):
        start, end = connection
        # Get the start which defines the drawing dictionary
        start_name = ""
        if isinstance(start, RoutingPort):
            start_name = start.name
            start = (start.x, start.y)
        elif isinstance(start, CellPin):
            start_name = name_grid.get((start.x, start.y), "") if name_grid else ""
            start = (start.x, start.y)

        # Get the end which defines the endpoint
        if isinstance(end, RoutingPort):
            end = (end.x, end.y)
        elif isinstance(end, CellPin):
            end = (end.x, end.y)

        distance = euclidean_distance_sq(start, end)
        sortable_connections.append((start_name, distance, index, connection))
        name_endpoint_mapping.setdefault(start_name, set())
        name_endpoint_mapping[start_name].add(end)

    fanout_by_start = {
        start_name: len(endpoints)
        for start_name, endpoints in name_endpoint_mapping.items()
    }

    # Fanout-aware ordering: higher fanout first, then shorter distance.
    sortable_connections.sort(
        key=lambda item: (
            -fanout_by_start[item[0]],
            item[1],
            item[2],
        )
    )

    return name_endpoint_mapping, [item[3] for item in sortable_connections]



# Draw all connections with paths
def draw_connections(grid, connections, width, height, ports, cells, name_grid=None):
    """Route all connections and return the calculated vertices.

    Args:
        grid (np.ndarray): Schematic grid (int8 array).
        connections (list): Connections between subcells.
        width (int): Width of the schematic.
        height (int): Height of the schematic.
        ports (list): Ports in the schematic.
        cells (list): Cells in the schematic.
        name_grid (dict, optional): Sparse mapping of (x, y) to string name.

    Returns:
        dict: Drawing dict mapping net name to list of vertex paths.
    """
    _cache.clear()
    _straight_line_change_count.clear()
    port_drawing_dict = defaultdict(list)
    straight_lines = defaultdict(list)
    route_cell_usage = dict()
    routed_entries = []
    name_endpoint_mapping, sorted_connections = sort_connections(connections, name_grid)
    endpoint_key_mapping = {
        start_name: _point_keys(endpoints, height)
        for start_name, endpoints in name_endpoint_mapping.items()
    }

    def append_path(start_name, path):
        port_drawing_dict[start_name].append(path)
        current_path_stripped = keep_corners_and_edges([path])
        if start_name not in straight_lines:
            straight_lines[start_name] = []
        straight_lines[start_name] = transform_to_pairs(
            current_path_stripped, straight_lines[start_name]
        )
        mark_changed(start_name)

    def rebuild_straight_lines(start_name):
        paths = port_drawing_dict[start_name]
        if paths:
            straight_lines[start_name] = transform_to_pairs(
                keep_corners_and_edges(paths), []
            )
        else:
            straight_lines[start_name] = []
        mark_changed(start_name)

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

    def route_forward_with_window(start_new, end_new, start_name, transformed_start_dir,
                                  use_congestion=True):
        # Try progressively larger search windows before falling back to full grid
        points = [start_new, end_new]
        for margin in WINDOW_MARGIN_STEPS:
            search_window = _window_from_points(points, width, height, margin)
            path = a_star(grid, start_new, end_new, width, height,
                          straight_lines, start_name, transformed_start_dir,
                          endpoint_key_mapping, route_cell_usage,
                          search_window=search_window,
                          use_congestion=use_congestion)
            if path:
                return path
        return a_star(grid, start_new, end_new, width, height,
                      straight_lines, start_name, transformed_start_dir,
                      endpoint_key_mapping, route_cell_usage,
                      search_window=None,
                      use_congestion=use_congestion)

    def route_reverse_with_window(path_list, end_new, start_name, transformed_end_dir,
                                  use_congestion=True):
        points = list(path_list)
        points.append(end_new)
        for margin in WINDOW_MARGIN_STEPS:
            search_window = _window_from_points(points, width, height, margin)
            path = reverse_a_star(grid, path_list, end_new, width, height,
                                  straight_lines, start_name, transformed_end_dir,
                                  endpoint_key_mapping, route_cell_usage,
                                  search_window=search_window,
                                  use_congestion=use_congestion)
            if path:
                return path
        return reverse_a_star(grid, path_list, end_new, width, height,
                              straight_lines, start_name, transformed_end_dir,
                              endpoint_key_mapping, route_cell_usage,
                              search_window=None,
                              use_congestion=use_congestion)

    def try_route_connection(start, end, start_dir, end_dir, start_name):
        start_new, end_new = adjust_start_end_for_direction(start, start_dir, end, end_dir)
        transformed_start_dir = direction_moves[start_dir]
        transformed_end_dir = direction_moves[end_dir]

        if start != end_new and end != start_new:
            shortcut_available = False
            # Shortcut mode: if this net already has routed paths, try to
            # branch off an existing path via reverse A* instead of routing
            # all the way back to the original start
            if SHORTCUT_ENABLED and len(port_drawing_dict[start_name]) != 0:
                shortcut_available = True
                shortcut_start_points = port_drawing_dict[start_name]
                # Collect interior points of existing paths as branch candidates
                path_list = list()
                for shortcut in shortcut_start_points:
                    path_list.extend(shortcut[1:-1])
                if end_new in path_list:
                    # Endpoint already lies on an existing path --> trivial connection
                    path = [end_new]
                elif not path_list:
                    raise IndexError(f"Shortcut doesn't have valid branch point to connect nid:{start_name}")
                else:
                    # Try reverse A* from endpoint to any existing path point
                    path = route_reverse_with_window(
                        path_list, end_new, start_name, transformed_end_dir,
                        use_congestion=False
                    )
                    # Fall back to forward A* if reverse search fails
                    if not path:
                        path = route_forward_with_window(
                            start_new, end_new, start_name, transformed_start_dir,
                            use_congestion=False
                        )
            else:
                # First connection for this net, standard forward A*
                path = route_forward_with_window(
                    start_new, end_new, start_name, transformed_start_dir
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

    for start, end in sorted_connections:
        # start and end direction and name of the starting point
        start_dir = None
        end_dir = None
        start_name = None

        # Get the start which defines the drawing dictionary
        if isinstance(start, RoutingPort):
            start_name = start.name
            start_dir = start.direction
            start = (start.x, start.y)
        elif isinstance(start, CellPin):
            start_name = name_grid.get((start.x, start.y), "") if name_grid else ""
            start_dir = start.direction
            start = (start.x, start.y)

        # Get the end which the defines the endpoint
        if isinstance(end, RoutingPort):
            end_dir = end.direction
            end = (end.x, end.y)
        elif isinstance(end, CellPin):
            end_dir = end.direction
            end = (end.x, end.y)

        path, start_new, end_new = try_route_connection(start, end, start_dir, end_dir, start_name)

        # Rip-up/reroute: if routing failed, temporarily remove the previous
        # route and retry. If both can be rerouted, keep the new arrangement;
        # otherwise restore the original route.
        if path is None and MAX_RIPUP_REROUTE > 0 and routed_entries:
            previous_entry = routed_entries.pop()
            previous_start_name = previous_entry["start_name"]
            if port_drawing_dict[previous_start_name]:
                port_drawing_dict[previous_start_name].pop()
            rebuild_straight_lines(previous_start_name)
            remove_path_from_grid(previous_entry["path_cells"])

            # Retry current connection with the previous route removed
            path, start_new, end_new = try_route_connection(start, end, start_dir, end_dir, start_name)
            if path is not None:
                path_cells = apply_path_to_grid(path)
                append_path(start_name, path)
                routed_entries.append({
                    "start": start,
                    "end": end,
                    "start_dir": start_dir,
                    "end_dir": end_dir,
                    "start_name": start_name,
                    "path": path,
                    "path_cells": path_cells,
                })

                # Try to reroute the previously ripped-up connection
                previous_path, _, _ = try_route_connection(
                    previous_entry["start"],
                    previous_entry["end"],
                    previous_entry["start_dir"],
                    previous_entry["end_dir"],
                    previous_start_name,
                )
                if previous_path is not None:
                    # Both succeeded --> keep the new arrangement
                    previous_cells = apply_path_to_grid(previous_path)
                    append_path(previous_start_name, previous_path)
                    previous_entry["path"] = previous_path
                    previous_entry["path_cells"] = previous_cells
                    routed_entries.append(previous_entry)
                    continue

                # Previous route failed to reroute, undo current and restore
                if port_drawing_dict[start_name]:
                    port_drawing_dict[start_name].pop()
                rebuild_straight_lines(start_name)
                remove_path_from_grid(path_cells)

            # Restore the original previous route
            restore_cells = apply_path_to_grid(previous_entry["path"])
            append_path(previous_start_name, previous_entry["path"])
            previous_entry["path_cells"] = restore_cells
            routed_entries.append(previous_entry)

        if path is None:
            print(f"Failed to connect {start_new} to {end_new}. Adding terminal taps ...")
            continue

        path_cells = apply_path_to_grid(path)
        append_path(start_name, path)
        routed_entries.append({
            "start": start,
            "end": end,
            "start_dir": start_dir,
            "end_dir": end_dir,
            "start_name": start_name,
            "path": path,
            "path_cells": path_cells,
        })

    # Post-process: reduce full paths to corner/edge vertices for rendering
    for key, value in port_drawing_dict.items():
        if SHORTCUT_ENABLED:
            current_path = keep_corners_and_edges(port_drawing_dict[key])
        else:
            current_path = keep_corners_and_edges(shorten_lists(port_drawing_dict[key]))
        port_drawing_dict[key] = current_path
    return port_drawing_dict


def calculate_vertices(outline, cells, ports, connections):
    """Place elements on a grid and perform A* routing.

    Args:
        outline (Rect4R): Current schematic outline.
        cells (dict): Cells in the schematic.
        ports (dict): Ports in the schematic.
        connections (list): Connections between subcells.

    Returns:
        dict: Calculated vertices of routes keyed by net name.
    """
    width = int(outline.ux - outline.lx) * 2
    height = int(outline.uy - outline.ly) * 2
    grid = np.zeros((height, width), dtype=np.int8)
    name_grid = place_cells_and_ports(grid, list(cells.values()), list(ports.values()), width, height)
    # _GRID_SYMBOLS = {GRID_EMPTY: '.', GRID_ROUTED: '+', GRID_DIR: 'D',
    #                  GRID_BLOCKED: '#', GRID_PIN: 'P', GRID_PORT: 'O'}
    # cell_width = 5
    # for ry in range(height - 1, -1, -1):
    #     print(''.join(f"{name_grid.get((x, ry), _GRID_SYMBOLS.get(grid[ry][x], '?')):<{cell_width}}"
    #                   for x in range(width)))
    vertices = draw_connections(grid, connections, width, height,
                                list(ports.values()), list(cells.values()), name_grid)
    return vertices


def adjust_outline_initial(node):
    """Compute an initial outline enclosing all ports and instances.

    Args:
        node: Node instance containing schematic elements.

    Returns:
        Rect4R: Adjusted outline bounding all elements.
    """
    outline = None
    for port in node.all(SchemPort):
        if outline:
            outline = outline.extend(port.pos)
        else:
            outline = Rect4R(lx=port.pos.x, ly=port.pos.y,
                             ux=port.pos.x, uy=port.pos.y)
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

def schematic_routing(node, outline=None, routing=None):
    """Calculate routing vertices via A* pathfinding and attach wires to the node.

    Args:
        node: Current node containing schematic elements.
        outline (Rect4R, optional): Outline coordinates. Computed if not given.
        routing (dict, optional): Port routing overrides. Keys are port IDs,
            values are booleans enabling/disabling routing.

    Returns:
        Rect4R: Adjusted outline extended to cover all routed wires.
    """
    # Get all the connections of ports and instances
    if routing is None:
        routing = dict()
    if outline is None:
        outline = adjust_outline_initial(node)
    width = int(outline.ux - outline.lx)
    height = int(outline.uy - outline.ly)
    # Calculate offset for positive coordinates while routing
    offset_x = (width  // 2) - int(outline.lx)
    offset_y = (height // 2) - int(outline.ly)
    ports = dict()
    cells = dict()
    # mapping between net and name
    array_mapping_list = dict()

    #======================
    # Build Cells and Ports
    #======================

    for instance in node.all(SchemInstance):
        instance_transform = instance.loc_transform()
        # Add instance for cells
        symbol_size = instance_transform * instance.symbol.outline
        pos = Vec2R(x=symbol_size.lx + offset_x, y=symbol_size.ly + offset_y)
        x_size = symbol_size.ux - symbol_size.lx
        y_size = symbol_size.uy - symbol_size.ly
        instance_nid = str(instance.nid)
        # Add inner connections for the cell (symbol)
        inner_connections = dict()
        for pin in instance.symbol.all(Pin):
            alignment = (instance.orientation * pin.align).unflip().lefdef()
            inner_pos = instance_transform * pin.pos
            # Get the parent instance name to get a unique assignment
            pin_nid = str(pin.nid)
            inner_x = int(inner_pos.x)
            inner_y = int(inner_pos.y)
            inner_connections[pin_nid] = CellPin(inner_x + offset_x,
                                                   inner_y + offset_y,
                                                   alignment,
                                                   instance_nid)
        # Add to cells dictionary
        cells[instance_nid] = RoutingCell(int(pos.x),
                                    int(pos.y),
                                    int(x_size) + 1,
                                    int(y_size) + 1,
                                    instance_nid,
                                    inner_connections)
    for instance in node.all(SchemPort):
        # Add instances for ports
        port_alignment = instance.align.lefdef()
        pos = instance.pos
        # Check if port has npath
        net_nid = str(instance.ref.nid)
        # Mapping to seperate ports form inner nets
        array_mapping_list[instance.ref] = net_nid
        # Add to ports dictionary
        inner_x = int(pos.x)
        inner_y = int(pos.y)
        route = instance.ref.route
        ports[net_nid] = RoutingPort(inner_x + offset_x,
                           inner_y + offset_y,
                           net_nid,
                           port_alignment,
                           route)

    #======================
    # Determine connections
    #======================

    # Get the connections defined via the portmap
    connections = list()
    inter_instance_connections = list()
    for instance in node.all(SchemInstance):
        instance_nid = str(instance.nid)
        # Connections of Cells and ports
        for conn in instance.conns():
            inner_connection = conn.there
            connected_to = conn.here
            # Get the instance name to get a unique assignment
            inner_connection_nid = str(inner_connection.nid)
            connected_nid = array_mapping_list.get(connected_to, None)
            connection_position = cells[instance_nid].connections[inner_connection_nid]
            # Only if the ports have the connection and if it's not an inter cell connection
            if connected_nid in ports:
                # ORD1 in dictionry
                if routing.get(int(connected_nid) if connected_nid.isdigit() else connected_nid, True):
                    # ORD2 in schema
                    if ports[connected_nid].route:
                        connections.append((ports[connected_nid], connection_position))
                # Connection not in ports <=> inter instance connection
            else:
                connected_nid = str(connected_to.nid)
                if connected_nid not in inter_instance_connections:
                    # Create the inner port on first appearance and save the inter instance connection
                    inter_instance_connections.append(connected_nid)
                    ports[connected_nid] = RoutingPort(int(connection_position.x),
                                                 int(connection_position.y),
                                                 connected_nid, connection_position.direction)
                    array_mapping_list[connected_to] = connected_nid
                else:
                    # Save the path after the inter instance connection is established
                    if ports[connected_nid].route:
                        connections.append((ports[connected_nid], connection_position))

    #=====================================================
    # Calculate the vertices and add them to the schematic
    #=====================================================
    
    vertices_dict = dict()
    if len(connections) > 0:
        vertices_dict = calculate_vertices(outline, cells, ports, connections)
    named_vertice_counter = 0
    for name, vertices_lists in vertices_dict.items():
        # Example: node.vss % SchemWire(vertices=[Vec2R(x=6, y=1), Vec2R(x=6, y=2)])
        for vertices in vertices_lists:
            schem_element = node.cursor_at(int(name) if name.isdigit() else name)
            converted_vertices = list()
            # Case for inner nets
            if isinstance(schem_element, Net):
                for vert in vertices:
                    # Remove the offset
                    converted_vertex = Vec2R(x=vert[0] - offset_x, y=vert[1] - offset_y)
                    outline = outline.extend(converted_vertex)
                    converted_vertices.append(converted_vertex)
                schem_element % SchemWire(vertices=converted_vertices)
            # Case for external ports
            else:
                for vert in vertices:
                    # Remove the offset
                    converted_vertex = Vec2R(x=vert[0] - offset_x, y=vert[1] - offset_y)
                    outline = outline.extend(converted_vertex)
                    converted_vertices.append(converted_vertex)
                setattr(schem_element.ref, f"vert_{named_vertice_counter}",
                        SchemWire(vertices=converted_vertices))
            named_vertice_counter += 1
    return outline


if __name__ == "__main__":
    """
    Test function for the routing module
    """
    # grid dimensions
    GRID_WIDTH = 11
    GRID_HEIGHT = 20
    lx = -1
    ly = -5
    width = GRID_WIDTH * 2
    height = GRID_HEIGHT * 2
    # center in the bigger canvas and stay within positive coordinates
    offset_x = (GRID_WIDTH  // 2) - lx
    offset_y = (GRID_HEIGHT // 2) - ly
    grid = np.zeros((height, width), dtype=np.int8)

    # Sample cells with positions (bottom-left corner) and size
    cells = [
        RoutingCell(4 + offset_x, 2 + offset_y, 5, 5, "pd"),
        RoutingCell(4 + offset_x, 10 + offset_y, 5, 5, "pu")
    ]

    ports = [
        RoutingPort(-1 + offset_x, -5 + offset_y, "vss", 'E'),
        RoutingPort(1 + offset_x, 15 + offset_y, "vdd", 'E'),
        RoutingPort(10 + offset_x, 8 + offset_y, "y", 'W'),
        RoutingPort(1 + offset_x, 8 + offset_y, "a", 'E')
    ]

    # Connections list for drawing paths
    connections = [
        (ports[0], cells[0].connections['S']),
        (ports[0], cells[0].connections['E']),
        (ports[1], cells[1].connections['N']),
        (ports[1], cells[1].connections['E']),
        (ports[3], cells[0].connections['W']),
        (ports[3], cells[1].connections['W']),
        (ports[2], cells[0].connections['N']),
        (ports[2], cells[1].connections['S']),
    ]

    name_grid = place_cells_and_ports(grid, cells, ports, width, height)
    draw_connections(grid, connections, width, height, ports, cells, name_grid)
    # Print grid with readable names
    _GRID_SYMBOLS = {GRID_EMPTY: '.', GRID_ROUTED: '+', GRID_DIR: 'D',
                     GRID_BLOCKED: '#', GRID_PIN: 'P', GRID_PORT: 'O'}
    cell_width = 5
    for ry in range(height - 1, -1, -1):
        print(''.join(f"{name_grid.get((x, ry), _GRID_SYMBOLS.get(grid[ry][x], '?')):<{cell_width}}"
                      for x in range(width)))
