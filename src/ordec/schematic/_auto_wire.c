// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Inner loops of the schematic router ordec.schematic.auto_wire: the A*
// search of a_star() and reverse_a_star(), and the blocked move updates of
// BlockedMoves.add().
//
// Nodes are keyed by x * height + y. Blocked moves and route cell usage stay
// in the Python dicts of auto_wire (see BlockedMoves), queried per expanded
// node. Pop order is fully determined by (f_score, node_key), so results do
// not depend on the heap implementation.

#define PY_SSIZE_T_CLEAN
#define Py_LIMITED_API 0x030b0000 // abi3, Python 3.11+
#include <Python.h>
#include <stdlib.h>

#define GRID_ROUTED 1
#define GRID_DIR 2
#define GRID_BLOCKED 3

// Congestion cost of stepping onto a routed cell used u times:
// ROUTED_BASE_PENALTY + u * CONGESTION_PENALTY.
#define ROUTED_BASE_PENALTY 0.25
#define CONGESTION_PENALTY 2.0
// Cost of a direction change: half the remaining Manhattan distance, at
// least MIN_TURN_PENALTY. This favors straight runs near the destination.
#define MIN_TURN_PENALTY 10

// Search order and encoding of the move directions: North, South, East,
// West (N=1, S=2, E=4, W=8, as in the move keys of BlockedMoves).
static const int DX[4] = {0, 0, 1, -1};
static const int DY[4] = {1, -1, 0, 0};
static const int BIT[4] = {1, 2, 4, 8};

typedef struct {
    double f;
    long key;
    int dir;
    double g;
} Entry;

typedef struct {
    Entry *items;
    Py_ssize_t len, cap;
} Heap;

static int entry_less(const Entry *a, const Entry *b) {
    return a->f < b->f || (a->f == b->f && a->key < b->key);
}

static int heap_push(Heap *h, Entry e) {
    if (h->len == h->cap) {
        Py_ssize_t cap = h->cap ? 2 * h->cap : 1024;
        Entry *items = realloc(h->items, cap * sizeof(Entry));
        if (!items) {
            PyErr_NoMemory();
            return -1;
        }
        h->items = items;
        h->cap = cap;
    }
    Py_ssize_t i = h->len++;
    while (i > 0) {
        Py_ssize_t parent = (i - 1) / 2;
        if (!entry_less(&e, &h->items[parent]))
            break;
        h->items[i] = h->items[parent];
        i = parent;
    }
    h->items[i] = e;
    return 0;
}

typedef struct {
    long *items;
    Py_ssize_t len, cap;
} KeyList;

static int keys_append(KeyList *l, long key) {
    if (l->len == l->cap) {
        Py_ssize_t cap = l->cap ? 2 * l->cap : 1024;
        long *items = realloc(l->items, cap * sizeof(long));
        if (!items) {
            PyErr_NoMemory();
            return -1;
        }
        l->items = items;
        l->cap = cap;
    }
    l->items[l->len++] = key;
    return 0;
}

static Entry heap_pop(Heap *h) {
    Entry top = h->items[0];
    Entry last = h->items[--h->len];
    Py_ssize_t i = 0;
    for (;;) {
        Py_ssize_t child = 2 * i + 1;
        if (child >= h->len)
            break;
        if (child + 1 < h->len && entry_less(&h->items[child + 1], &h->items[child]))
            child++;
        if (!entry_less(&h->items[child], &last))
            break;
        h->items[i] = h->items[child];
        i = child;
    }
    if (h->len > 0)
        h->items[i] = last;
    return top;
}

// Value of dict[key] as long, or dflt if absent. Returns -1 with exception
// set on error (values are never negative).
static long dict_get_long(PyObject *dict, long key, long dflt) {
    PyObject *k = PyLong_FromLong(key);
    if (!k)
        return -1;
    PyObject *v = PyDict_GetItemWithError(dict, k); // borrowed
    Py_DECREF(k);
    if (!v)
        return PyErr_Occurred() ? -1 : dflt;
    return PyLong_AsLong(v);
}

// 1 if key is in the dict or set container, 0 if not, -1 on error.
static int contains(PyObject *container, long key) {
    PyObject *k = PyLong_FromLong(key);
    if (!k)
        return -1;
    int ret = PySequence_Contains(container, k);
    Py_DECREF(k);
    return ret;
}

// Blocked directions at node key for the routed net. Moves blocked by
// other nets (any_mask) block, except where only the routed net itself
// blocks them as corner moves (counts: number of nets per move). The
// routed net's own riding moves always block.
static long block_mask(PyObject *any_mask, PyObject *own_masks,
        PyObject *ride_masks, PyObject *counts, long key) {
    long own = dict_get_long(own_masks, key, 0);
    if (own <= 0)
        return own < 0 ? -1 : dict_get_long(any_mask, key, 0);
    long ride = dict_get_long(ride_masks, key, 0);
    long any = dict_get_long(any_mask, key, 0);
    if (ride < 0 || any < 0)
        return -1;
    long mask = (any & ~own) | ride;
    for (int i = 0; i < 4; i++) {
        if ((own & BIT[i]) && !(ride & BIT[i])) {
            long count = dict_get_long(counts, (key << 4) | BIT[i], 0);
            if (count < 0)
                return -1;
            if (count > 1)
                mask |= BIT[i];
        }
    }
    return mask;
}

// List of (x, y) tuples along came_from from key back to the origin. The
// origin itself is included if with_origin.
static PyObject *trace(const long *came_from, long key, long height, int with_origin, int reverse) {
    PyObject *path = PyList_New(0);
    if (!path)
        return NULL;
    for (;;) {
        long prev = came_from[key] - 1;
        if (prev < 0 && !with_origin)
            break;
        PyObject *pt = Py_BuildValue("(ll)", key / height, key % height);
        if (!pt || PyList_Append(path, pt) < 0) {
            Py_XDECREF(pt);
            Py_DECREF(path);
            return NULL;
        }
        Py_DECREF(pt);
        if (prev < 0)
            break;
        key = prev;
    }
    if (reverse && PyList_Reverse(path) < 0) {
        Py_DECREF(path);
        return NULL;
    }
    return path;
}

// search(cells, scratch, width, height, origin_key, origin_dir, goal,
//     any_mask, own_masks, ride_masks, counts, usage, use_congestion, hits,
//     endpoint_keys)
//
// scratch is a writable buffer of SCRATCH_PER_NODE bytes per node, zeroed
// when first used; it is left zeroed for the next search. This avoids
// allocating and clearing grid-sized arrays per search.
//
// Forward search (a_star) if goal is an int: the end key. Returns the path
// from origin (excluded) to goal, [] on failure.
//
// Reverse search (reverse_a_star) if goal is a dict of target keys to
// (x, y) points. Returns the path with the fewest points from a target to
// origin (both included), [] on failure. Turns on direction markers are
// allowed at origin and at endpoint_keys. The heuristic aims at the target
// nearest to origin (the first one in dict order on ties).
//
// The heuristic is the Manhattan distance; each step costs 1, plus the
// turn and congestion penalties (see above). origin_dir is the index of the
// initial direction in N, S, E, W. Congestion costs apply if use_congestion,
// from usage (dict of node key to use count) or, if usage is None, from
// GRID_ROUTED cells. Blocked moves encountered are added to hits (set or
// None) as (node_key << 4) | bit.
#define SCRATCH_PER_NODE (sizeof(double) + sizeof(long) + 1)

static PyObject *search(PyObject *self, PyObject *args) {
    Py_buffer cells_buf, scratch_buf;
    long width, height, origin;
    int origin_dir, use_congestion;
    PyObject *goal, *any_mask, *own_masks, *ride_masks, *counts, *usage, *hits, *endpoint_keys;
    if (!PyArg_ParseTuple(args, "y*w*llliOOOOOOpOO", &cells_buf, &scratch_buf, &width, &height,
            &origin, &origin_dir, &goal, &any_mask, &own_masks,
            &ride_masks, &counts, &usage, &use_congestion, &hits, &endpoint_keys))
        return NULL;
    const unsigned char *cells = cells_buf.buf;
    long size = width * height;
    if (cells_buf.len < size || scratch_buf.len < size * (Py_ssize_t)SCRATCH_PER_NODE
            || origin < 0 || origin >= size) {
        PyBuffer_Release(&cells_buf);
        PyBuffer_Release(&scratch_buf);
        PyErr_SetString(PyExc_ValueError, "invalid search arguments");
        return NULL;
    }
    int reverse = !PyLong_Check(goal);
    long end_key = reverse ? -1 : PyLong_AsLong(goal);
    if (reverse && !PyDict_Check(goal)) {
        PyBuffer_Release(&cells_buf);
        PyBuffer_Release(&scratch_buf);
        PyErr_SetString(PyExc_TypeError, "goal must be an int or a dict");
        return NULL;
    }

    // Point (hx, hy) the heuristic aims at.
    long hx, hy;
    if (reverse) {
        long ox = origin / height, oy = origin % height, best = -1;
        hx = ox;
        hy = oy;
        Py_ssize_t pos = 0;
        PyObject *k, *pt;
        while (PyDict_Next(goal, &pos, &k, &pt)) {
            long x, y;
            if (!PyArg_ParseTuple(pt, "ll", &x, &y)) {
                PyBuffer_Release(&cells_buf);
                PyBuffer_Release(&scratch_buf);
                return NULL;
            }
            long dist = labs(ox - x) + labs(oy - y);
            if (best < 0 || dist < best) {
                best = dist;
                hx = x;
                hy = y;
            }
        }
    } else {
        hx = end_key / height;
        hy = end_key % height;
    }

    // g_score and came_from of a node are valid if it is visited. came_from
    // holds predecessor + 1, 0 for the origin. Visited nodes are listed in
    // touched, to unmark them in the end.
    double *g_score = scratch_buf.buf;
    long *came_from = (long *)(g_score + size);
    char *visited = (char *)(came_from + size);
    Heap heap = {NULL, 0, 0};
    KeyList touched = {NULL, 0, 0};
    PyObject *best_path = NULL, *ret = NULL;
    long best_len = -1;
    if (keys_append(&touched, origin) < 0)
        goto done;
    visited[origin] = 1;
    g_score[origin] = 0.0;
    came_from[origin] = 0;
    double h0 = labs(origin / height - hx) + labs(origin % height - hy);
    if (heap_push(&heap, (Entry){h0, origin, origin_dir, 0.0}) < 0)
        goto done;

    while (heap.len > 0) {
        Entry cur = heap_pop(&heap);
        long ck = cur.key;
        if (cur.g > g_score[ck])
            continue;
        if (reverse) {
            if (best_len >= 0 && g_score[ck] >= best_len)
                continue;
            int hit = contains(goal, ck);
            if (hit < 0)
                goto done;
            if (hit) {
                PyObject *path = trace(came_from, ck, height, 1, 0);
                if (!path)
                    goto done;
                long len = (long)PyList_Size(path);
                if (best_len < 0 || len < best_len) {
                    Py_XDECREF(best_path);
                    best_path = path;
                    best_len = len;
                } else {
                    Py_DECREF(path);
                }
                continue;
            }
        } else if (ck == end_key) {
            ret = trace(came_from, ck, height, 0, 1);
            goto done;
        }

        long cx = ck / height, cy = ck % height;
        long remaining = labs(cx - hx) + labs(cy - hy);
        if (reverse)
            remaining = labs(cx - origin / height) + labs(cy - origin % height);
        long mask = block_mask(any_mask, own_masks, ride_masks, counts, ck);
        if (mask < 0)
            goto done;
        double cur_g = g_score[ck];

        // Direction markers in front of terminals enforce straight escapes:
        // turns on them are only allowed at the origin and at the end (the
        // forward search's end key, the reverse search's endpoint_keys).
        int turn_allowed = 1;
        if (cells[ck] == GRID_DIR && ck != origin) {
            if (reverse) {
                int r = contains(endpoint_keys, ck);
                if (r < 0)
                    goto done;
                turn_allowed = r;
            } else {
                turn_allowed = ck == end_key;
            }
        }

        for (int d = 0; d < 4; d++) {
            if (mask & BIT[d]) {
                if (hits != Py_None) {
                    PyObject *hk = PyLong_FromLong((ck << 4) | BIT[d]);
                    if (!hk || PySet_Add(hits, hk) < 0) {
                        Py_XDECREF(hk);
                        goto done;
                    }
                    Py_DECREF(hk);
                }
                continue;
            }
            long nx = cx + DX[d], ny = cy + DY[d];
            if (nx < 0 || nx >= width || ny < 0 || ny >= height)
                continue;
            long nk = nx * height + ny;
            if (!turn_allowed && cur.dir != d)
                continue;
            if (cells[nk] >= GRID_BLOCKED)
                continue;

            double turn_penalty = 0;
            if (cur.dir != d) {
                turn_penalty = remaining * 0.5;
                if (turn_penalty < MIN_TURN_PENALTY)
                    turn_penalty = MIN_TURN_PENALTY;
            }
            double congestion_penalty = 0.0;
            if (use_congestion) {
                if (usage != Py_None) {
                    long u = dict_get_long(usage, nk, 0);
                    if (u < 0)
                        goto done;
                    if (u > 0)
                        congestion_penalty = ROUTED_BASE_PENALTY + (u * CONGESTION_PENALTY);
                } else if (cells[nk] == GRID_ROUTED) {
                    congestion_penalty = ROUTED_BASE_PENALTY;
                }
            }
            double g = cur_g + 1 + turn_penalty + congestion_penalty;
            if (!visited[nk] || g < g_score[nk]) {
                if (!visited[nk] && keys_append(&touched, nk) < 0)
                    goto done;
                visited[nk] = 1;
                came_from[nk] = ck + 1;
                g_score[nk] = g;
                double f = g + labs(nx - hx) + labs(ny - hy);
                if (heap_push(&heap, (Entry){f, nk, d, g}) < 0)
                    goto done;
            }
        }
    }
    if (reverse) {
        ret = best_path ? best_path : PyList_New(0);
        best_path = NULL;
    } else {
        ret = PyList_New(0);
    }

done:
    for (Py_ssize_t i = 0; i < touched.len; i++)
        visited[touched.items[i]] = 0;
    Py_XDECREF(best_path);
    free(heap.items);
    free(touched.items);
    PyBuffer_Release(&cells_buf);
    PyBuffer_Release(&scratch_buf);
    return ret;
}

// dict[key] = value (both C longs). Returns -1 on error.
static int dict_set_long(PyObject *dict, long key, long value) {
    PyObject *k = PyLong_FromLong(key), *v = PyLong_FromLong(value);
    int ret = (k && v) ? PyDict_SetItem(dict, k, v) : -1;
    Py_XDECREF(k);
    Py_XDECREF(v);
    return ret;
}

// One blocked move of a net, see BlockedMoves.add(). Returns -1 on error.
static int add_move(PyObject *ride, PyObject *own, PyObject *count,
        PyObject *any_mask, long key, long bit) {
    if (ride) {
        long r = dict_get_long(ride, key, 0);
        if (r < 0 || dict_set_long(ride, key, r | bit) < 0)
            return -1;
    }
    long mask = dict_get_long(own, key, 0);
    if (mask < 0)
        return -1;
    if (mask & bit)
        return 0;
    if (dict_set_long(own, key, mask | bit) < 0)
        return -1;
    long move_key = (key << 4) | bit;
    long c = dict_get_long(count, move_key, 0);
    if (c < 0 || dict_set_long(count, move_key, c + 1) < 0)
        return -1;
    if (c == 0) {
        long any = dict_get_long(any_mask, key, 0);
        if (any < 0 || dict_set_long(any_mask, key, any | bit) < 0)
            return -1;
    }
    return 0;
}

// add_moves(segments, corner_points, ride, own, count, any_mask, width,
//     height): adds the blocked moves of a net, see BlockedMoves. Riding
// moves (in both directions along the straight segments) go to ride and
// own, corner moves (all moves out of the corner points and all in-grid
// moves into them) to own only. Moves new to own are counted in count and
// marked in any_mask.
static PyObject *add_moves(PyObject *self, PyObject *args) {
    PyObject *segments, *corners, *ride, *own, *count, *any_mask;
    long width, height;
    if (!PyArg_ParseTuple(args, "OOOOOOll", &segments, &corners, &ride, &own,
            &count, &any_mask, &width, &height))
        return NULL;
    Py_ssize_t n = PySequence_Size(segments);
    if (n < 0)
        return NULL;
    for (Py_ssize_t i = 0; i < n; i++) {
        long x1, y1, x2, y2;
        PyObject *seg = PySequence_GetItem(segments, i);
        int ok = seg && PyArg_ParseTuple(seg, "(ll)(ll)", &x1, &y1, &x2, &y2);
        Py_XDECREF(seg);
        if (!ok)
            return NULL;
        if (x1 == x2) {
            for (long y = y1 < y2 ? y1 : y2; y < (y1 < y2 ? y2 : y1); y++) {
                if (add_move(ride, own, count, any_mask, x1 * height + y, 1) < 0
                        || add_move(ride, own, count, any_mask, x1 * height + y + 1, 2) < 0)
                    return NULL;
            }
        } else if (y1 == y2) {
            for (long x = x1 < x2 ? x1 : x2; x < (x1 < x2 ? x2 : x1); x++) {
                if (add_move(ride, own, count, any_mask, x * height + y1, 4) < 0
                        || add_move(ride, own, count, any_mask, (x + 1) * height + y1, 8) < 0)
                    return NULL;
            }
        }
    }
    n = PySequence_Size(corners);
    if (n < 0)
        return NULL;
    for (Py_ssize_t i = 0; i < n; i++) {
        long x, y;
        PyObject *pt = PySequence_GetItem(corners, i);
        int ok = pt && PyArg_ParseTuple(pt, "ll", &x, &y);
        Py_XDECREF(pt);
        if (!ok)
            return NULL;
        long key = x * height + y;
        for (int b = 0; b < 4; b++)
            if (add_move(NULL, own, count, any_mask, key, BIT[b]) < 0)
                return NULL;
        if ((y > 0 && add_move(NULL, own, count, any_mask, key - 1, 1) < 0)
                || (y < height - 1 && add_move(NULL, own, count, any_mask, key + 1, 2) < 0)
                || (x > 0 && add_move(NULL, own, count, any_mask, key - height, 4) < 0)
                || (x < width - 1 && add_move(NULL, own, count, any_mask, key + height, 8) < 0))
            return NULL;
    }
    Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
    {"search", search, METH_VARARGS, "A* search loop of a_star() and reverse_a_star()."},
    {"add_moves", add_moves, METH_VARARGS, "Loop of BlockedMoves.add()."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_auto_wire", NULL, -1, methods
};

PyMODINIT_FUNC PyInit__auto_wire(void) {
    return PyModule_Create(&module);
}
