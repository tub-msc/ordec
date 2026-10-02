// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Storage primitives of the ORDB core (functions in store.c):
//
// - Vec: a vector of fixed-size records of 8-byte slots, stored as a
//   persistent radix tree with small leaves and edit tokens (the "paged"
//   engine).
// - Run: a sorted, immutable array of index entries (h, s, nid).
//
// Leaves that can hold Python object references (objmask != 0) are
// GC-tracked Python objects: leaves are shared between subgraphs, and the
// cycle collector must see each reference exactly once. Inner tree nodes
// are always GC objects (there are few of them), which also makes the
// leaves reachable for memory accounting via gc.get_referents.

#ifndef ORDB_STORE_H
#define ORDB_STORE_H

typedef int64_t slot_t;

#define LEAF_BITS 4
#define LEAF_ROWS (1u << LEAF_BITS)
#define BITS 5
#define FAN (1u << BITS)
#define SHIFT(l) (LEAF_BITS + BITS * ((l) - 1))

extern uint64_t g_token; // source of edit tokens; 0 is never a token

typedef struct {
    PyObject_VAR_HEAD
    uint64_t owner;
    uint64_t objmask;
    uint32_t rec;
    slot_t data[1];
} Leaf;

typedef struct {
    PyObject_HEAD
    uint64_t owner;
    PyObject *kids[FAN];
} Inner;

typedef struct {
    PyObject *root; // Leaf or Inner; NULL when empty
    uint64_t count; // records visible through this Vec
    uint64_t objmask; // bit b set: slot b of a record holds a PyObject*
    uint32_t rec; // slots per record
    uint8_t levels; // inner levels above the leaves
} Vec;

// Releases the object references of n records and zeroes those slots.
static inline void
recs_clear(slot_t *p, uint64_t objmask, uint32_t rec, uint64_t n)
{
    if (!objmask)
        return;
    for (uint64_t r = 0; r < n; r++, p += rec) {
        for (uint64_t m = objmask; m; m &= m - 1) {
            int b = __builtin_ctzll(m);
            PyObject *o = (PyObject *)p[b];
            p[b] = 0;
            Py_XDECREF(o);
        }
    }
}

static inline void
recs_incref(const slot_t *p, uint64_t objmask, uint32_t rec, uint64_t n)
{
    if (!objmask)
        return;
    for (uint64_t r = 0; r < n; r++, p += rec)
        for (uint64_t m = objmask; m; m &= m - 1)
            Py_XINCREF((PyObject *)p[__builtin_ctzll(m)]);
}

static inline int
recs_traverse(const slot_t *p, uint64_t objmask, uint32_t rec, uint64_t n,
    visitproc visit, void *arg)
{
    for (uint64_t r = 0; r < n; r++, p += rec)
        for (uint64_t m = objmask; m; m &= m - 1)
            Py_VISIT((PyObject *)p[__builtin_ctzll(m)]);
    return 0;
}

// -- Vec ---------------------------------------------------------------------

static inline void
vec_init(Vec *v, uint32_t rec, uint64_t objmask)
{
    v->root = NULL;
    v->count = 0;
    v->objmask = objmask;
    v->rec = rec;
    v->levels = 0;
}

// Record i (i < count). For sparsely written vectors (the nid directory),
// NULL if no leaf covers i.
static inline const slot_t *
vec_get(const Vec *v, uint64_t i)
{
    PyObject *n = v->root;
    for (int l = v->levels; l > 0; l--) {
        n = ((Inner *)n)->kids[(i >> SHIFT(l)) & (FAN - 1)];
        if (!n)
            return NULL;
    }
    return ((Leaf *)n)->data + (i & (LEAF_ROWS - 1)) * v->rec;
}

// -- index runs --------------------------------------------------------------

typedef struct {
    uint64_t h; // key hash
    int64_t s; // sort value
    int64_t nid;
} Ent;

typedef struct Run {
    uint32_t rc;
    uint32_t n;
    uint64_t owner; // tails only: the subgraph that may append
    Ent e[1];
} Run;

#define TAIL_CAP 64
#define MAXRUNS 32

static inline int
ent_lt(const Ent *a, const Ent *b)
{
    if (a->h != b->h)
        return a->h < b->h;
    if (a->s != b->s)
        return a->s < b->s;
    return a->nid < b->nid;
}

static inline void
run_decref(Run *r)
{
    if (r && --r->rc == 0)
        PyMem_Free(r);
}

static inline uint32_t
run_lower_bound(const Run *r, uint64_t h)
{
    uint32_t lo = 0, hi = r->n;
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        if (r->e[mid].h < h)
            lo = mid + 1;
        else
            hi = mid;
    }
    return lo;
}

// store.c
extern PyTypeObject *Leaf_Type, *LeafGC_Type, *InnerGC_Type;
int store_init(void);
void obj_free(void *o);
slot_t *vec_at_w(Vec *v, uint64_t i, uint64_t lin, uint64_t tx, int append);
int ent_cmp(const void *a, const void *b);
int ent_cmp_sn(const void *pa, const void *pb);
Run *run_new(uint32_t cap, uint64_t owner);

#endif
