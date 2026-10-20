// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Scan of empty_regions() in ordec.schematic.annotate: the maximal empty
// rectangles of a cell grid with blocked spans.

#define PY_SSIZE_T_CLEAN
#define Py_LIMITED_API 0x030b0000 // abi3, Python 3.11+
#include <Python.h>
#include <stdlib.h>
#include <string.h>

static int cmp_long(const void *a, const void *b) {
    long x = *(const long *)a, y = *(const long *)b;
    return (x > y) - (x < y);
}

// Sorts and deduplicates v (length n), returns the new length.
static Py_ssize_t sort_unique(long *v, Py_ssize_t n) {
    qsort(v, n, sizeof(long), cmp_long);
    Py_ssize_t m = 0;
    for (Py_ssize_t i = 0; i < n; i++)
        if (m == 0 || v[m - 1] != v[i])
            v[m++] = v[i];
    return m;
}

// scan(x0, y0, nx, ny, spans): maximal empty rectangles of the nx x ny
// cell grid, in which the spans (i0, i1, j0, j1) (cell ranges, clipped to
// the grid, non-empty) are blocked. Returned as (lx, ly, ux, uy) offset by
// (x0, y0).
static PyObject *scan(PyObject *self, PyObject *args) {
    long x0, y0, nx, ny;
    PyObject *spans_obj;
    if (!PyArg_ParseTuple(args, "llllO", &x0, &y0, &nx, &ny, &spans_obj))
        return NULL;
    PyObject *spans_seq = PySequence_Fast(spans_obj, "spans must be a sequence");
    if (!spans_seq)
        return NULL;
    Py_ssize_t n_spans = PySequence_Size(spans_seq);

    long *spans = malloc((n_spans * 4 + 1) * sizeof(long));
    long *xs = malloc((2 * n_spans + 2) * sizeof(long));
    long *ys = malloc((2 * n_spans + 2) * sizeof(long));
    long *x_index = malloc((nx + 1) * sizeof(long));
    long *y_index = malloc((ny + 1) * sizeof(long));
    char *blocked = NULL;
    long *heights = NULL, *stack_start = NULL, *stack_h = NULL;
    PyObject *regions = NULL;
    if (!spans || !xs || !ys || !x_index || !y_index) {
        PyErr_NoMemory();
        goto done;
    }
    Py_ssize_t n_xs = 0, n_ys = 0;
    xs[n_xs++] = 0;
    xs[n_xs++] = nx;
    ys[n_ys++] = 0;
    ys[n_ys++] = ny;
    for (Py_ssize_t k = 0; k < n_spans; k++) {
        long *sp = spans + 4 * k;
        PyObject *item = PySequence_GetItem(spans_seq, k);
        int ok = item && PyArg_ParseTuple(item, "llll", &sp[0], &sp[1], &sp[2], &sp[3]);
        Py_XDECREF(item);
        if (!ok)
            goto done;
        if (sp[0] < 0 || sp[1] > nx || sp[0] >= sp[1]
                || sp[2] < 0 || sp[3] > ny || sp[2] >= sp[3]) {
            PyErr_SetString(PyExc_ValueError, "span outside of the grid or empty");
            goto done;
        }
        xs[n_xs++] = sp[0];
        xs[n_xs++] = sp[1];
        ys[n_ys++] = sp[2];
        ys[n_ys++] = sp[3];
    }

    // The scan runs on a compressed grid: blocked cells only start and end
    // at span edges, so between consecutive edges, all columns (rows) are
    // equal. Column i of the compressed grid spans the cell columns xs[i] to
    // xs[i + 1], row j likewise. This finds the same rectangles as a scan of
    // the cell grid, on far fewer cells.
    n_xs = sort_unique(xs, n_xs);
    n_ys = sort_unique(ys, n_ys);
    for (Py_ssize_t i = 0; i < n_xs; i++)
        x_index[xs[i]] = i;
    for (Py_ssize_t j = 0; j < n_ys; j++)
        y_index[ys[j]] = j;
    Py_ssize_t nxc = n_xs - 1, nyc = n_ys - 1;
    blocked = calloc(nxc * nyc + 1, 1);
    heights = calloc(nxc + 1, sizeof(long));
    stack_start = malloc((nxc + 1) * sizeof(long));
    stack_h = malloc((nxc + 1) * sizeof(long));
    regions = PyList_New(0);
    if (!blocked || !heights || !stack_start || !stack_h || !regions) {
        if (!PyErr_Occurred())
            PyErr_NoMemory();
        goto done;
    }
    for (Py_ssize_t k = 0; k < n_spans; k++) {
        long *sp = spans + 4 * k;
        for (long j = y_index[sp[2]]; j < y_index[sp[3]]; j++)
            memset(blocked + j * nxc + x_index[sp[0]], 1, x_index[sp[1]] - x_index[sp[0]]);
    }

    // Largest-rectangle-in-histogram scan, one histogram per row j
    // (heights[i]: number of free rows ending in row j of column i). Each
    // popped stack entry is a rectangle that cannot grow to the left, right
    // or downwards; it is maximal if it cannot grow upwards either.
    for (Py_ssize_t j = 0; j < nyc; j++) {
        const char *row = blocked + j * nxc;
        for (Py_ssize_t i = 0; i < nxc; i++)
            heights[i] = row[i] ? 0 : heights[i] + 1;
        Py_ssize_t sp = 0; // stack size
        for (Py_ssize_t i = 0; i <= nxc; i++) {
            long h = i < nxc ? heights[i] : 0;
            long start = i;
            while (sp > 0 && stack_h[sp - 1] > h) {
                sp--;
                start = stack_start[sp];
                long sh = stack_h[sp];
                int maximal = j == nyc - 1;
                if (!maximal) {
                    const char *above = blocked + (j + 1) * nxc;
                    for (long k = start; k < i && !maximal; k++)
                        maximal = above[k];
                }
                if (maximal) {
                    PyObject *r = Py_BuildValue("(llll)", x0 + xs[start],
                        y0 + ys[j + 1 - sh], x0 + xs[i], y0 + ys[j + 1]);
                    if (!r || PyList_Append(regions, r) < 0) {
                        Py_XDECREF(r);
                        Py_CLEAR(regions);
                        goto done;
                    }
                    Py_DECREF(r);
                }
            }
            if (h > 0 && (sp == 0 || stack_h[sp - 1] < h)) {
                stack_start[sp] = start;
                stack_h[sp] = h;
                sp++;
            }
        }
    }

done:
    if (PyErr_Occurred())
        Py_CLEAR(regions);
    Py_DECREF(spans_seq);
    free(spans);
    free(xs);
    free(ys);
    free(x_index);
    free(y_index);
    free(blocked);
    free(heights);
    free(stack_start);
    free(stack_h);
    return regions;
}

static PyMethodDef methods[] = {
    {"scan", scan, METH_VARARGS, "Scan of empty_regions()."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_annotate", NULL, -1, methods
};

PyMODINIT_FUNC PyInit__annotate(void) {
    return PyModule_Create(&module);
}
