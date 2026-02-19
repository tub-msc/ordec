# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0
# cython: boundscheck=False, wraparound=False, cdivision=True, language_level=3
"""Cython-accelerated A* pathfinding for schematic routing.

Provides optimized versions of a_star() and reverse_a_star() from routing.py.
Falls back to pure Python implementations when Cython is not compiled.

v2: Pure C inner loop — C binary heap, integer-encoded directions,
flat arrays for blocked-segment / endpoint lookups. No Python object
overhead during node expansion.
"""

import numpy as np
cimport numpy as np
from libc.stdlib cimport malloc, free
from libc.string cimport memset

# ============================================================
# Constants (must match routing.py)
# ============================================================

cdef int _GRID_DIR = 2
cdef int _GRID_BLOCKED = 3
cdef int DIR_NONE = -1

# Direction offsets indexed by direction id: N=0, S=1, E=2, W=3
cdef int _DX[4]
cdef int _DY[4]
_DX[0] = 0;  _DY[0] = 1     # N = (0, 1)
_DX[1] = 0;  _DY[1] = -1    # S = (0, -1)
_DX[2] = 1;  _DY[2] = 0     # E = (1, 0)
_DX[3] = -1; _DY[3] = 0     # W = (-1, 0)

cdef inline int _c_abs(int x) noexcept:
    return x if x >= 0 else -x


# ============================================================
# C Binary Min-Heap
# ============================================================
# Stores (f_score, position_key, direction_int) triples.
# Tie-breaks by position_key to match Python tuple comparison.

cdef struct HeapEntry:
    double f
    int key
    int direction

cdef struct BinaryHeap:
    HeapEntry* data
    int size
    int capacity

cdef inline BinaryHeap* heap_create(int capacity) noexcept:
    cdef BinaryHeap* h = <BinaryHeap*>malloc(sizeof(BinaryHeap))
    if not h:
        return NULL
    h.data = <HeapEntry*>malloc(capacity * sizeof(HeapEntry))
    if not h.data:
        free(h)
        return NULL
    h.size = 0
    h.capacity = capacity
    return h

cdef inline void heap_free(BinaryHeap* h) noexcept:
    if h:
        if h.data:
            free(h.data)
        free(h)

cdef inline int _heap_lt(HeapEntry* a, HeapEntry* b) noexcept:
    """Return 1 if a < b (first by f-score, then by key)."""
    if a.f < b.f:
        return 1
    if a.f == b.f and a.key < b.key:
        return 1
    return 0

cdef inline void heap_push(BinaryHeap* h, double f, int key, int direction) noexcept:
    cdef int i = h.size
    h.size += 1
    h.data[i].f = f
    h.data[i].key = key
    h.data[i].direction = direction
    # Bubble up
    cdef int parent
    cdef HeapEntry temp
    while i > 0:
        parent = (i - 1) >> 1
        if _heap_lt(&h.data[i], &h.data[parent]):
            temp = h.data[parent]
            h.data[parent] = h.data[i]
            h.data[i] = temp
            i = parent
        else:
            break

cdef inline HeapEntry heap_pop(BinaryHeap* h) noexcept:
    cdef HeapEntry result = h.data[0]
    cdef int i = 0
    cdef int left, right, smallest
    cdef HeapEntry temp
    h.size -= 1
    if h.size > 0:
        h.data[0] = h.data[h.size]
        # Sift down
        i = 0
        while True:
            left = (i << 1) + 1
            right = (i << 1) + 2
            smallest = i
            if left < h.size and _heap_lt(&h.data[left], &h.data[smallest]):
                smallest = left
            if right < h.size and _heap_lt(&h.data[right], &h.data[smallest]):
                smallest = right
            if smallest != i:
                temp = h.data[i]
                h.data[i] = h.data[smallest]
                h.data[smallest] = temp
                i = smallest
            else:
                break
    return result


# ============================================================
# Forward A*
# ============================================================

def a_star_fast(np.int8_t[:, :] grid,
                tuple start, tuple end,
                int width, int height,
                set blocked_segments,
                set endpoint_set,
                object start_dir):
    """Cython-optimized forward A* pathfinding (pure C inner loop).

    :param grid: int8 numpy array (typed memoryview)
    :param start: (x, y) start position
    :param end: (x, y) end position
    :param width: grid width
    :param height: grid height
    :param blocked_segments: set of ((x1,y1),(x2,y2)) blocked moves
    :param endpoint_set: set of (x,y) endpoint positions
    :param start_dir: initial direction tuple or None
    :returns: list of (x,y) path tuples (excluding start)
    """
    cdef int sx = start[0], sy = start[1]
    cdef int ex = end[0], ey = end[1]
    cdef int h = height
    cdef int start_key = sx * h + sy
    cdef int end_key = ex * h + ey
    cdef int grid_size = width * h

    # Convert direction tuple to int once
    cdef int start_direction = DIR_NONE
    if start_dir is not None:
        if start_dir == (0, 1): start_direction = 0
        elif start_dir == (0, -1): start_direction = 1
        elif start_dir == (1, 0): start_direction = 2
        elif start_dir == (-1, 0): start_direction = 3

    # Allocate all C arrays
    cdef double* g_score = <double*>malloc(grid_size * sizeof(double))
    cdef int* came_from = <int*>malloc(grid_size * sizeof(int))
    cdef char* in_open = <char*>malloc(grid_size * sizeof(char))
    cdef char* blocked = <char*>malloc(grid_size * 4 * sizeof(char))
    cdef char* ep_arr = <char*>malloc(grid_size * sizeof(char))
    cdef BinaryHeap* heap = heap_create(grid_size)

    if not g_score or not came_from or not in_open or not blocked or not ep_arr or not heap:
        if g_score: free(g_score)
        if came_from: free(came_from)
        if in_open: free(in_open)
        if blocked: free(blocked)
        if ep_arr: free(ep_arr)
        heap_free(heap)
        raise MemoryError("Failed to allocate A* arrays")

    cdef int i, key, x1, y1, x2, y2, dx, dy, seg_dir
    cdef double INF = 1e18
    cdef int current_key, cx, cy, nx, ny, neighbor_key
    cdef int d, current_direction
    cdef double tentative_g, f_val, remaining_distance, penalty, cur_g
    cdef HeapEntry entry

    try:
        # Initialize arrays
        for i in range(grid_size):
            g_score[i] = INF
            came_from[i] = -1
        memset(in_open, 0, grid_size)
        memset(blocked, 0, grid_size * 4)
        memset(ep_arr, 0, grid_size)

        # Build blocked-moves flat array from Python set
        for s_pt, e_pt in blocked_segments:
            x1 = <int>s_pt[0]; y1 = <int>s_pt[1]
            x2 = <int>e_pt[0]; y2 = <int>e_pt[1]
            if x1 < 0 or x1 >= width or y1 < 0 or y1 >= h:
                continue
            if x2 < 0 or x2 >= width or y2 < 0 or y2 >= h:
                continue
            dx = x2 - x1; dy = y2 - y1
            if dx == 0:
                seg_dir = 0 if dy > 0 else 1
            else:
                seg_dir = 2 if dx > 0 else 3
            blocked[(x1 * h + y1) * 4 + seg_dir] = 1

        # Build endpoint flat array from Python set
        for p in endpoint_set:
            x1 = <int>p[0]; y1 = <int>p[1]
            if 0 <= x1 < width and 0 <= y1 < h:
                ep_arr[x1 * h + y1] = 1

        # Initialize start node
        g_score[start_key] = 0.0
        in_open[start_key] = 1
        heap_push(heap, <double>(_c_abs(sx - ex) + _c_abs(sy - ey)),
                  start_key, start_direction)

        # ===== Main A* loop (pure C, no Python calls) =====
        while heap.size > 0:
            entry = heap_pop(heap)
            current_key = entry.key
            current_direction = entry.direction
            in_open[current_key] = 0

            if current_key == end_key:
                # Reconstruct path (only runs once)
                path = []
                key = current_key
                while came_from[key] != -1:
                    path.append((key // h, key % h))
                    key = came_from[key]
                path.reverse()
                return path

            cx = current_key // h
            cy = current_key % h
            cur_g = g_score[current_key]

            for d in range(4):
                nx = cx + _DX[d]
                ny = cy + _DY[d]

                # Bounds check
                if nx < 0 or nx >= width or ny < 0 or ny >= h:
                    continue

                # Blocked segment: flat array lookup
                if blocked[current_key * 4 + d]:
                    continue

                # Direction marker turn restriction
                if (grid[cy, cx] == _GRID_DIR and
                        current_direction != DIR_NONE and
                        current_direction != d and
                        current_key != start_key and
                        not ep_arr[current_key]):
                    continue

                neighbor_key = nx * h + ny

                # Not allowed to cross a cell body, pin, or port
                if grid[ny, nx] < _GRID_BLOCKED:
                    remaining_distance = _c_abs(cx - ex) + _c_abs(cy - ey)
                    if current_direction != DIR_NONE and current_direction != d:
                        penalty = remaining_distance * 0.5
                        if penalty < 10:
                            penalty = 10
                    else:
                        penalty = 0

                    tentative_g = cur_g + 1.0 + penalty

                    if tentative_g < g_score[neighbor_key]:
                        came_from[neighbor_key] = current_key
                        g_score[neighbor_key] = tentative_g
                        f_val = tentative_g + _c_abs(nx - ex) + _c_abs(ny - ey)

                        if not in_open[neighbor_key]:
                            heap_push(heap, f_val, neighbor_key, d)
                            in_open[neighbor_key] = 1

        return []

    finally:
        free(g_score)
        free(came_from)
        free(in_open)
        free(blocked)
        free(ep_arr)
        heap_free(heap)


# ============================================================
# Reverse A*
# ============================================================

def reverse_a_star_fast(np.int8_t[:, :] grid,
                        list start_points, tuple end,
                        int width, int height,
                        set blocked_segments,
                        set endpoint_set,
                        object end_dir):
    """Cython-optimized reverse A* pathfinding (pure C inner loop).

    Searches from end toward multiple start_points, returns the best path.

    :param grid: int8 numpy array (typed memoryview)
    :param start_points: list of (x,y) candidate start positions
    :param end: (x, y) end position (A* starts here)
    :param width: grid width
    :param height: grid height
    :param blocked_segments: set of ((x1,y1),(x2,y2)) blocked moves
    :param endpoint_set: set of (x,y) endpoint positions
    :param end_dir: initial direction tuple
    :returns: list of (x,y) path tuples
    """
    cdef int ex = end[0], ey = end[1]
    cdef int h = height
    cdef int end_key = ex * h + ey
    cdef int grid_size = width * h

    # Find closest start point for heuristic
    cdef int min_dist = 2000000000
    cdef int dist, spx, spy
    start_point_min = start_points[0]
    for sp in start_points:
        spx = <int>sp[0]
        spy = <int>sp[1]
        dist = _c_abs(ex - spx) + _c_abs(ey - spy)
        if dist < min_dist:
            start_point_min = sp
            min_dist = dist
    cdef int spm_x = start_point_min[0]
    cdef int spm_y = start_point_min[1]

    # Convert direction tuple to int once
    cdef int end_direction = DIR_NONE
    if end_dir is not None:
        if end_dir == (0, 1): end_direction = 0
        elif end_dir == (0, -1): end_direction = 1
        elif end_dir == (1, 0): end_direction = 2
        elif end_dir == (-1, 0): end_direction = 3

    # Allocate all C arrays
    cdef double* g_score = <double*>malloc(grid_size * sizeof(double))
    cdef int* came_from = <int*>malloc(grid_size * sizeof(int))
    cdef char* in_open = <char*>malloc(grid_size * sizeof(char))
    cdef char* blocked = <char*>malloc(grid_size * 4 * sizeof(char))
    cdef char* ep_arr = <char*>malloc(grid_size * sizeof(char))
    cdef char* sp_arr = <char*>malloc(grid_size * sizeof(char))
    cdef BinaryHeap* heap = heap_create(grid_size)

    if (not g_score or not came_from or not in_open or
            not blocked or not ep_arr or not sp_arr or not heap):
        if g_score: free(g_score)
        if came_from: free(came_from)
        if in_open: free(in_open)
        if blocked: free(blocked)
        if ep_arr: free(ep_arr)
        if sp_arr: free(sp_arr)
        heap_free(heap)
        raise MemoryError("Failed to allocate A* arrays")

    cdef int i, key, x1, y1, x2, y2, dx, dy, seg_dir
    cdef double INF = 1e18
    cdef int current_key, cx, cy, nx, ny, neighbor_key
    cdef int d, current_direction
    cdef double tentative_g, f_val, remaining_distance, penalty, cur_g
    cdef int best_path_length = 2000000000
    cdef HeapEntry entry

    try:
        # Initialize arrays
        for i in range(grid_size):
            g_score[i] = INF
            came_from[i] = -1
        memset(in_open, 0, grid_size)
        memset(blocked, 0, grid_size * 4)
        memset(ep_arr, 0, grid_size)
        memset(sp_arr, 0, grid_size)

        # Build blocked-moves flat array from Python set
        for s_pt, e_pt in blocked_segments:
            x1 = <int>s_pt[0]; y1 = <int>s_pt[1]
            x2 = <int>e_pt[0]; y2 = <int>e_pt[1]
            if x1 < 0 or x1 >= width or y1 < 0 or y1 >= h:
                continue
            if x2 < 0 or x2 >= width or y2 < 0 or y2 >= h:
                continue
            dx = x2 - x1; dy = y2 - y1
            if dx == 0:
                seg_dir = 0 if dy > 0 else 1
            else:
                seg_dir = 2 if dx > 0 else 3
            blocked[(x1 * h + y1) * 4 + seg_dir] = 1

        # Build endpoint flat array from Python set
        for p in endpoint_set:
            x1 = <int>p[0]; y1 = <int>p[1]
            if 0 <= x1 < width and 0 <= y1 < h:
                ep_arr[x1 * h + y1] = 1

        # Build start-points flat array
        for sp in start_points:
            x1 = <int>sp[0]; y1 = <int>sp[1]
            if 0 <= x1 < width and 0 <= y1 < h:
                sp_arr[x1 * h + y1] = 1

        # Initialize end node (reverse search starts from end)
        g_score[end_key] = 0.0
        in_open[end_key] = 1
        heap_push(heap, <double>min_dist, end_key, end_direction)

        best_path = []

        # ===== Main A* loop (pure C, no Python calls) =====
        while heap.size > 0:
            entry = heap_pop(heap)
            current_key = entry.key
            current_direction = entry.direction
            in_open[current_key] = 0

            cur_g = g_score[current_key]
            if cur_g >= best_path_length:
                continue

            # Check if we reached a start point
            if sp_arr[current_key]:
                # Reconstruct path
                path = []
                key = current_key
                while came_from[key] != -1:
                    path.append((key // h, key % h))
                    key = came_from[key]
                path.append((key // h, key % h))  # Add the start point itself

                if len(path) < best_path_length:
                    best_path = path
                    best_path_length = len(path)

                continue

            cx = current_key // h
            cy = current_key % h

            for d in range(4):
                nx = cx + _DX[d]
                ny = cy + _DY[d]

                # Bounds check
                if nx < 0 or nx >= width or ny < 0 or ny >= h:
                    continue

                # Blocked segment: flat array lookup
                if blocked[current_key * 4 + d]:
                    continue

                # Direction marker turn restriction (reversed logic from forward)
                if (grid[cy, cx] == _GRID_DIR and
                        current_direction != DIR_NONE and
                        current_direction != d and
                        current_key != end_key and
                        ep_arr[current_key]):
                    continue

                neighbor_key = nx * h + ny

                # Not allowed to cross a cell body, pin, or port
                if grid[ny, nx] < _GRID_BLOCKED:
                    remaining_distance = _c_abs(cx - ex) + _c_abs(cy - ey)
                    if current_direction != DIR_NONE and current_direction != d:
                        penalty = remaining_distance * 0.5
                        if penalty < 10:
                            penalty = 10
                    else:
                        penalty = 0

                    tentative_g = cur_g + 1.0 + penalty

                    if tentative_g < g_score[neighbor_key]:
                        came_from[neighbor_key] = current_key
                        g_score[neighbor_key] = tentative_g
                        f_val = tentative_g + _c_abs(nx - spm_x) + _c_abs(ny - spm_y)

                        if not in_open[neighbor_key]:
                            heap_push(heap, f_val, neighbor_key, d)
                            in_open[neighbor_key] = 1

        return best_path

    finally:
        free(g_score)
        free(came_from)
        free(in_open)
        free(blocked)
        free(ep_arr)
        free(sp_arr)
        heap_free(heap)
