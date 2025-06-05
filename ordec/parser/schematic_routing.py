# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import numpy as np
import heapq
import sys
import hashlib
import math

SHORTCUT_ENABLED = True
cache = {}

# Port class with direction
class Port:
    def __init__(self, x, y, name, direction):
        self.x = x
        self.y = y
        self.name = name
        self.direction = direction
        # Cell class with connection points and their directions

    def __str__(self):
        ret_str = f"X={self.x}; Y={self.y}; Name={self.name}; Direction={self.direction}"
        return ret_str

class Cell:
    def __init__(self, x, y, x_size, y_size, name, connections=None):
        self.x = x
        self.y = y
        self.x_size = x_size
        self.y_size = y_size
        self.name = name
        if connections is None:
            self.connections = {
                'S': (x + x_size // 2, y, 'S', self.name),
                'N': (x + x_size // 2, y + y_size - 1, 'N', self.name),
                'W': (x, y + y_size // 2, 'W', self.name),
                'E': (x + x_size - 1, y + y_size // 2, 'E', self.name),
            }
        else:
            # dict with name, position and direction
            self.connections = connections

    def __str__(self):
        ret_str = f"X= {self.x} Y= {self.y} X_SIZE= {self.x_size} Y_SIZE= {self.y_size} NAME= {self.name}\n"
        for connection_name, tuple_values in self.connections.items():
           ret_str += f"Name: {connection_name} Inner_x: {tuple_values[0]} " \
                        f"Inner_y: {tuple_values[1]} Orientation: {tuple_values[2]}\n"
        return ret_str


# valid moves for each direction
direction_moves = {
    'N': (0, 1),
    'S': (0, -1),
    'E': (1, 0),
    'W': (-1, 0),
}

# Place cells and ports on the grid
def place_cells_and_ports(grid, cells, ports, width, height):
    for cell in cells:
        x, y = cell.x, cell.y
        for i in range(cell.x_size):
            for j in range(cell.y_size):
                grid[y + j][x + i] = cell.name
        for name, (cx, cy, direction, _) in cell.connections.items():
            grid[cy][cx] = f"{cell.name}.{name}"
            if 0 <= cy < height and 0 <= cx < width:
                direction_offset_x = direction_moves[direction][0] + cx
                direction_offset_y = direction_moves[direction][1] + cy
                grid[direction_offset_y][direction_offset_x] = "__dir"


    for port in ports:
        if 0 <= port.y < height and 0 <= port.x < width:
            grid[port.y][port.x] = port.name
            direction_offset_x = direction_moves[port.direction][0] + port.x
            direction_offset_y = direction_moves[port.direction][1] + port.y
            grid[direction_offset_y][direction_offset_x] = "__dir"

def adjust_start_end_for_direction(start, start_dir, end, end_dir):
    """Adjust the start and end points to ensure proper direction handling."""

    # Adjust the start point based on start_dir
    if start_dir:
        dx, dy = direction_moves[start_dir]
        start = (start[0] + dx, start[1] + dy)

    # Adjust the end point based on end_dir
    if end_dir:
        dx, dy = direction_moves[end_dir]
        end = (end[0] + dx, end[1] + dy) 

    return start, end


def compute_hash(straight_lines, start_name):
    """Compute a hash of straight_lines (excluding start_name) to detect changes."""
    relevant_data = {key: value for key, value in straight_lines.items() if key != start_name}
    return hashlib.md5(str(sorted(relevant_data.items())).encode()).hexdigest()

def preprocess_straight_lines(straight_lines, start_name):
    """Preprocess straight lines into a set of blocked movements, including corner-touch prevention, while allowing orthogonal crossings."""
    global cache

    new_hash = compute_hash(straight_lines, start_name)
    # Only compute new blocked segments if something changed
    if start_name in cache and cache[start_name]["hash"] == new_hash:
        return cache[start_name]["blocked_moves"]

    blocked_moves = set()
    corner_nodes = set()

    for key, value in straight_lines.items():
        if key != start_name:
            # Get start and end
            for line_start, line_end in value:
                x1, y1 = line_start
                x2, y2 = line_end

                # Vertical
                if x1 == x2:
                    y_start, y_end = sorted([y1, y2])
                    for y in range(y_start, y_end):
                        a, b = (x1, y), (x1, y + 1)
                        blocked_moves.add((a, b))
                        blocked_moves.add((b, a))
                # Horizontal
                elif y1 == y2:
                    x_start, x_end = sorted([x1, x2])
                    for x in range(x_start, x_end):
                        a, b = (x, y1), (x + 1, y1)
                        blocked_moves.add((a, b))
                        blocked_moves.add((b, a))

                # Check if it's part of a corner
                # If line is not a terminal line (has predecessor or successor), then mark endpoints as corners
                if len(value) > 1:
                    corner_nodes.add(line_start)
                    corner_nodes.add(line_end)

    # For corner points, block all movement into and out of the node
    for node in corner_nodes:
        x, y = node
        for dx, dy in direction_moves.values():
            neighbor = (x + dx, y + dy)
            blocked_moves.add((node, neighbor))
            blocked_moves.add((neighbor, node))

    cache[start_name] = {"hash": new_hash, "blocked_moves": blocked_moves}
    return blocked_moves


def a_star(grid, start, end, width, height, ports, straight_lines, start_name, start_dir, cell_names, endpoint_mapping):

    def is_segment_blocked(start_point, end_point, blocked_moves):
        return (start_point, end_point) in blocked_moves

    def heuristic(point1, point2):
        """Heuristic function: Manhattan distance."""
        return abs(point1[0] - point2[0]) + abs(point1[1] - point2[1])

    use_dynamic_penalty = True
    # Preprocess straight lines into a set of blocked points
    blocked_segments = preprocess_straight_lines(straight_lines, start_name)

    # Preprocess ports into a set for faster lookups
    port_names = [port.name for port in ports]

    open_set = []  # Priority queue for A*
    heapq.heappush(open_set, (0, start, start_dir))  # Include direction in the tuple (direction starts as None)
    open_set_track = {start}  # Set to track elements in the open_set

    came_from = {}
    g_score = {start: 0}
    f_score = {start: heuristic(start, end)}

    while open_set:
        _, current, current_direction = heapq.heappop(open_set)
        open_set_track.remove(current)  # Remove current from the open set

        if current == end:
            # Reconstruct the path on reaching the end
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.reverse()
            return path

        # Explore neighbors
        for dx, dy in direction_moves.values():
            neighbor = (current[0] + dx, current[1] + dy)
            new_direction = (dx, dy)

            # Check if the path to the neighbor is blocked by straight lines
            if is_segment_blocked(current, neighbor, blocked_segments):
                continue

            # Check if inside the grid
            if 0 <= neighbor[0] < width and 0 <= neighbor[1] < height:
                current_element = grid[neighbor[1]][neighbor[0]]

                # If the new cell is "__dir", disallow movement **only if turning**
                if (grid[current[1]][current[0]] == "__dir" and
                        current_direction is not None and
                        current_direction != new_direction and
                        current != start and # Turn at start is fine
                        current not in endpoint_mapping[start_name]):
                    continue  # Skip this move if it would turn at "__dir"

                # Not allowed to cross a cell or a port
                if (not current_element.startswith(cell_names)) and (current_element not in port_names):
                    # Add a penalty for changing direction
                    remaining_distance = heuristic(current, end)
                    if current_direction and current_direction != new_direction:
                        if use_dynamic_penalty:
                            direction_change_penalty = remaining_distance * 0.5
                            if direction_change_penalty < 10:
                                direction_change_penalty = 10
                        else:
                            direction_change_penalty = 10
                    else:
                        direction_change_penalty = 0
                    tentative_g_score = g_score[current] + 1 + direction_change_penalty

                    # Save the path if it is better than the previous one
                    if neighbor not in g_score or tentative_g_score < g_score[neighbor]:
                        came_from[neighbor] = current
                        g_score[neighbor] = tentative_g_score
                        f_score[neighbor] = tentative_g_score + heuristic(neighbor, end)

                        # Only add neighbor to the heap if not already present
                        if neighbor not in open_set_track:
                            heapq.heappush(open_set, (f_score[neighbor], neighbor, new_direction))
                            open_set_track.add(neighbor)

    return []  # Return empty if no path found


def reverse_a_star(grid, start_points, end, width, height, ports, straight_lines, start_name, end_dir, cell_names,
                   endpoint_mapping):
    """Perform reverse A* from the end point to all start points."""

    def is_segment_blocked(start_point, end_point, blocked_moves):
        return (start_point, end_point) in blocked_moves

    def heuristic(point1, point2):
        """Heuristic function: Manhattan distance."""
        return abs(point1[0] - point2[0]) + abs(point1[1] - point2[1])

    use_dynamic_penalty = True
    # Preprocess straight lines into a set of blocked points
    blocked_segments = preprocess_straight_lines(straight_lines, start_name)

    open_set = []  # Priority queue for A* (heap)
    heapq.heappush(open_set, (0, end, end_dir))  # Start A* search from the end point
    port_names = [port.name for port in ports]

    came_from = {}
    g_score = {end: 0}
    min_distance = sys.maxsize
    start_point_min = start_points[0]
    for start_point in start_points:
        distance = heuristic(end, start_point)
        if distance < min_distance:
            start_point_min = start_point
            min_distance = distance
    f_score = {end: min_distance}  # Estimate distance from end to start
    open_set_track = {end}  # Set for quick lookup of elements in the open set

    best_path = []
    best_path_length = sys.maxsize

    while open_set:
        _, current, current_direction = heapq.heappop(open_set)
        open_set_track.remove(current)  # Remove current from the open set set

        current_path_length = g_score[current]
        # If the current path length is already greater than the best found so far, skip this node
        if current_path_length >= best_path_length:
            continue


        # If we reach one of the start points, return the path
        if current in start_points:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.append(current)  # Add the start point itself to the path

            # If this path is better than the previous, update the best path
            current_path_length = len(path)
            if current_path_length < best_path_length:
                best_path = path
                best_path_length = current_path_length

            continue  # After finding a valid path, continue to explore others

        # Explore neighbors
        for dx, dy in direction_moves.values():
            neighbor = (current[0] + dx, current[1] + dy)
            new_direction = (dx, dy)

            # Check if the path to the neighbor is blocked by straight lines
            if is_segment_blocked(current, neighbor, blocked_segments):
                continue

            # Check if inside the grid
            if 0 <= neighbor[0] < width and 0 <= neighbor[1] < height:
                current_element = grid[neighbor[1]][neighbor[0]]

                # If the new cell is "__dir", disallow movement **only if turning**
                if (grid[current[1]][current[0]] == "__dir" and
                        current_direction is not None and
                        current_direction != new_direction and
                        # Turn at start is fine
                        current != end and
                        current in endpoint_mapping[start_name]):
                    continue  # Skip this move if it would turn at "__dir"

                # Not allowed to cross a cell or a port
                if ((not current_element.startswith(cell_names)) and
                        current_element not in port_names):
                    # Add a penalty for changing direction
                    remaining_distance = heuristic(current, end)
                    if current_direction and current_direction != new_direction:
                        if use_dynamic_penalty:
                            direction_change_penalty = remaining_distance * 0.5
                            if direction_change_penalty < 10:
                                direction_change_penalty = 10
                        else:
                            direction_change_penalty = 10
                    else:
                        direction_change_penalty = 0
                    tentative_g_score = g_score[current] + 1 + direction_change_penalty

                    # Save the path if it is better than the previous one
                    if neighbor not in g_score or tentative_g_score < g_score[neighbor]:
                        came_from[neighbor] = current
                        g_score[neighbor] = tentative_g_score
                        f_score[neighbor] = tentative_g_score + heuristic(neighbor, start_point_min)

                        # Only add neighbor to the heap if not already present
                        if neighbor not in open_set_track:
                            heapq.heappush(open_set, (f_score[neighbor], neighbor, new_direction))
                            open_set_track.add(neighbor)

    return best_path



def shorten_lists(list_of_lists):
    """
    Shortens each list by removing overlapping prefixes with the previous list.
    The first list remains unchanged.
    """
    if not list_of_lists:
        return []

    shortened_lists = [list_of_lists[0]]  # Keep the first list as-is

    for i in range(1, len(list_of_lists)):
        #previous_list = list_of_lists[i-1]
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
    def is_corner(prev, curr, next_item):
        # A corner exists if there is a direction change
        return ((prev[0] != curr[0] and curr[1] != next_item[1]) or
                (prev[1] != curr[1] and curr[0] != next_item[0]))

    result = []
    first_line = True
    # start of consecutive lines
    starters = [line[0] for line in lines[1:]]

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
            # definetly safe the consecutive starts
            elif line[i] in starters:
                filtered_line.append(line[i])
        filtered_line.append(line[-1])  # Always keep the last element
        result.append(filtered_line)

    return result


def transform_to_pairs(list_of_lists, straights):
    """
    Transforms each list in the input into a list of consecutive pairs.
    For example: [(2, 1), (5, 1), (5, 2)] -> [((2, 1), (5, 1)), ((5, 1), (5, 2))]
    """

    for lst in list_of_lists:
        # Create pairs of consecutive elements
        for i in range(len(lst) - 1):
            pair = (lst[i], lst[i + 1])
            straights.append(pair)

    return straights


def sort_connections(connections):
    # Helper function to calculate Euclidean distance
    def euclidean_distance(point1, point2):
        return math.sqrt((point1[0] - point2[0])**2 + (point1[1] - point2[1])**2)

    # Draw all connections with paths
    sorted_connections = []
    name_endpoint_mapping = dict()

    for connection in connections:
        start, end = connection
        # Get the start which defines the drawing dictionary
        start_name = ""
        if isinstance(start, Port):
            start_name = start.name
            start = (start.x, start.y)
        elif isinstance(start, tuple) and len(start) == 4:  # Cell connection
            start_name = grid[start[1]][start[0]]
            start = (start[0], start[1])

        # Get the end which defines the endpoint
        if isinstance(end, Port):
            end = (end.x, end.y)
        elif isinstance(end, tuple) and len(end) == 4:  # Cell connection
            end = (end[0], end[1])

        distance = euclidean_distance(start, end)
        sorted_connections.append((distance, connection))
        name_endpoint_mapping.setdefault(start_name, [])
        name_endpoint_mapping[start_name].append(end)

    # Sort by distance
    sorted_connections.sort(key=lambda x: x[0])

    # Return the sorted connections without the distance
    return name_endpoint_mapping, [connection for _, connection in sorted_connections]



# Draw all connections with paths
def draw_connections(grid, connections, width, height, ports, cells):
    port_drawing_dict = dict()
    straight_lines = dict()
    # Get the cell names to avoid them on the path
    cell_names = tuple([cell.name for cell in cells])
    name_endpoint_mapping, sorted_connections = sort_connections(connections)

    for start, end in sorted_connections:
        # start and end direction and name of the starting point
        start_dir = None
        end_dir = None
        start_name = None

        # Get the start which defines the drawing dictionary
        if isinstance(start, Port):
            start_name = start.name
            if start_name not in port_drawing_dict.keys():
                port_drawing_dict[start_name] = []
            start_dir = start.direction
            start = (start.x, start.y)
        elif isinstance(start, tuple) and len(start) == 4:  # Cell connection
            start_name = grid[start[1]][start[0]]
            if start_name not in port_drawing_dict.keys():
                port_drawing_dict[start_name] = []
            start_dir = start[2]
            start = (start[0], start[1])

        # Get the end which the defines the endpoint
        if isinstance(end, Port):
            end_dir = end.direction
            end = (end.x, end.y)
        elif isinstance(end, tuple) and len(end) == 4:  # Cell connection
            end_dir = end[2]
            end = (end[0], end[1])

        # Adjust start and end positions for directions
        start_new, end_new = adjust_start_end_for_direction(start, start_dir, end, end_dir)
        # print(f"Trying connection: {start_new} ({start_dir}) -> {end_new} ({end_dir})")
        transformed_start_dir = direction_moves[start_dir]
        transformed_end_dir = direction_moves[end_dir]

        # check if there already is a path from this port/cell connection
        shortcut_available = False
        if SHORTCUT_ENABLED:
            if len(port_drawing_dict[start_name]) != 0:
                shortcut_available = True
                shortcut_start_points = port_drawing_dict[start_name]
                path_list = list()
                for shortcut in shortcut_start_points:
                    # extend except for first and last element (start/end)
                    path_list.extend(shortcut[1:-1])
                if end_new in path_list:
                    # if already in path_list no reason to do an a-star
                    path = [end_new]
                else:
                    # Call reverse A* from end point to all start points
                    path = reverse_a_star(grid, path_list, end_new, width, height, ports,
                                               straight_lines, start_name, transformed_end_dir, cell_names,
                                          name_endpoint_mapping)
            else:
                # No shortcut available, calculate the normal path
                path = a_star(grid, start_new, end_new, width, height, ports,
                                   straight_lines, start_name, transformed_start_dir, cell_names,
                              name_endpoint_mapping)

        else:
            # Normal path calculation if shortcutting is disabled
            path = a_star(grid, start_new, end_new, width, height, ports,
                               straight_lines, start_name, transformed_start_dir, cell_names,
                          name_endpoint_mapping)

        if not path and start_new != end_new:
            print(f"Failed to connect {start_new} to {end_new}. Adding terminal taps ...")
            continue

        # Add the final connection step if needed
        if start_dir and not shortcut_available:
            # only append if no shortcut available
            path.insert(0, start)
            path.insert(1, start_new)
        if end_dir:
            path.append(end)

        port_drawing_dict[start_name].append(path)
        # save all the straight lines
        current_path_stripped = keep_corners_and_edges([path])
        if start_name not in straight_lines.keys():
            straight_lines[start_name] = []
        straight_lines[start_name] = transform_to_pairs(current_path_stripped, straight_lines[start_name])
        # Draw the path on the grid
        for (x, y) in path:
            if grid[y][x] == '.':
                grid[y][x] = '+'


    for key, value in port_drawing_dict.items():
        if SHORTCUT_ENABLED:
            current_path = keep_corners_and_edges(port_drawing_dict[key])
        else:
            current_path = keep_corners_and_edges(shorten_lists(port_drawing_dict[key]))
        port_drawing_dict[key] = current_path
    return port_drawing_dict


def calculate_vertices(outline_xy, cells, ports, connections):
    # grid dimensions
    grid = np.full((outline_xy[1], outline_xy[0]), '.', dtype="<U100")
    grid[:] = '.'
    place_cells_and_ports(grid, list(cells.values()), list(ports.values()), outline_xy[0], outline_xy[1])
    vertices = draw_connections(grid, connections, outline_xy[0], outline_xy[1],
                                list(ports.values()), list(cells.values()))
    #reversed_grid = np.flipud(grid)
    #np.set_printoptions(formatter={'all': lambda x: f'{x:5}'}, linewidth=200)
    #print(reversed_grid)
    return vertices


if __name__ == "__main__":
    # grid dimensions
    GRID_WIDTH = 12
    GRID_HEIGHT = 17
    grid = np.full((GRID_HEIGHT, GRID_WIDTH), '.', dtype="<U100")

    # Sample cells with positions (bottom-left corner) and size
    cells = [
        Cell(4, 2, 5, 5, "pd"),
        Cell(4, 10, 5, 5, "pu")
    ]

    ports = [
        Port(1, 1, "vss", 'E'),
        Port(1, 15, "vdd", 'E'),
        Port(10, 8, "y", 'W'),
        Port(1, 8, "a", 'E')
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


    grid[:] = '.'
    place_cells_and_ports(grid, cells, ports, GRID_WIDTH, GRID_HEIGHT)
    draw_connections(grid, connections, GRID_WIDTH, GRID_HEIGHT, ports, cells)
    # Set the print options for a fixed width of 5 characters per value
    reversed_grid = np.flipud(grid)
    np.set_printoptions(formatter={'all': lambda x: f'{x:5}'}, linewidth=200)
    print(reversed_grid)

