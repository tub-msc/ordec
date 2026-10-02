// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Storage primitives of the ORDB core (included by _ordb.c only):
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

typedef int64_t slot_t;

#define LEAF_BITS 4
#define LEAF_ROWS (1u << LEAF_BITS)
#define BITS 5
#define FAN (1u << BITS)
#define SHIFT(l) (LEAF_BITS + BITS * ((l) - 1))

static uint64_t g_token = 1; // source of edit tokens; 0 is never a token

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

static PyTypeObject *Leaf_Type, *LeafGC_Type, *InnerGC_Type;

// Frees an instance of one of the (heap) types of the core and drops the
// reference the instance holds to its type.
static void
obj_free(void *o)
{
    PyTypeObject *tp = Py_TYPE((PyObject *)o);
    freefunc tp_free = (freefunc)PyType_GetSlot(tp, Py_tp_free);
    tp_free(o);
    Py_DECREF(tp);
}

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

// -- paged blocks ------------------------------------------------------------

static void
leaf_dealloc(Leaf *n)
{
    if (n->objmask)
        PyObject_GC_UnTrack(n);
    recs_clear(n->data, n->objmask, n->rec, LEAF_ROWS);
    obj_free(n);
}

static int
leaf_traverse(Leaf *n, visitproc visit, void *arg)
{
    Py_VISIT(Py_TYPE((PyObject *)n));
    return recs_traverse(n->data, n->objmask, n->rec, LEAF_ROWS, visit, arg);
}

static int
leaf_clear(Leaf *n)
{
    recs_clear(n->data, n->objmask, n->rec, LEAF_ROWS);
    return 0;
}

static void
inner_dealloc(Inner *n)
{
    PyObject_GC_UnTrack(n);
    for (unsigned i = 0; i < FAN; i++)
        Py_XDECREF(n->kids[i]);
    obj_free(n);
}

static int
inner_traverse(Inner *n, visitproc visit, void *arg)
{
    Py_VISIT(Py_TYPE((PyObject *)n));
    for (unsigned i = 0; i < FAN; i++)
        Py_VISIT(n->kids[i]);
    return 0;
}

static int
inner_clear(Inner *n)
{
    for (unsigned i = 0; i < FAN; i++)
        Py_CLEAR(n->kids[i]);
    return 0;
}

static PyObject *
leaf_new(const Vec *v, uint64_t tok)
{
    Py_ssize_t nslots = (Py_ssize_t)v->rec * LEAF_ROWS;
    Leaf *n = v->objmask ? PyObject_GC_NewVar(Leaf, LeafGC_Type, nslots)
        : PyObject_NewVar(Leaf, Leaf_Type, nslots);
    if (!n)
        return NULL;
    n->owner = tok;
    n->objmask = v->objmask;
    n->rec = v->rec;
    memset(n->data, 0, sizeof(slot_t) * nslots);
    if (v->objmask)
        PyObject_GC_Track(n);
    return (PyObject *)n;
}

static PyObject *
inner_new(const Vec *v, uint64_t tok)
{
    Inner *n = PyObject_GC_New(Inner, InnerGC_Type);
    if (!n)
        return NULL;
    n->owner = tok;
    memset(n->kids, 0, sizeof(n->kids));
    PyObject_GC_Track(n);
    return (PyObject *)n;
}

// Copy of a tree node with a new owner; the copy shares the children.
static PyObject *
node_copy(const Vec *v, PyObject *n, int level, uint64_t tok)
{
    if (level > 0) {
        Inner *c = (Inner *)inner_new(v, tok);
        if (!c)
            return NULL;
        memcpy(c->kids, ((Inner *)n)->kids, sizeof(c->kids));
        for (unsigned i = 0; i < FAN; i++)
            Py_XINCREF(c->kids[i]);
        return (PyObject *)c;
    }
    Leaf *c = (Leaf *)leaf_new(v, tok);
    if (!c)
        return NULL;
    memcpy(c->data, ((Leaf *)n)->data, sizeof(slot_t) * v->rec * LEAF_ROWS);
    recs_incref(c->data, v->objmask, v->rec, LEAF_ROWS);
    return (PyObject *)c;
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

// Writable record i; does not change count. With append, the caller
// states that no other snapshot of this vector can see record i.
//
// Write rule: a node is written in place if it was created by this
// transaction (owner == tx), or if it is owned by this subgraph
// (owner == lin) and the write is an append. Every other node on the path
// is copied first.
static slot_t *
vec_at_w(Vec *v, uint64_t i, uint64_t lin, uint64_t tx, int append)
{
    uint64_t newtok = append ? lin : tx;
    if (!v->root) {
        v->root = leaf_new(v, newtok);
        if (!v->root)
            return NULL;
        v->levels = 0;
    }
    while (i >= ((uint64_t)LEAF_ROWS << (BITS * v->levels))) {
        Inner *r = (Inner *)inner_new(v, newtok);
        if (!r)
            return NULL;
        r->kids[0] = v->root;
        v->root = (PyObject *)r;
        v->levels++;
    }
    PyObject **pp = &v->root;
    for (int l = v->levels;; l--) {
        PyObject *n = *pp;
        uint64_t owner = l > 0 ? ((Inner *)n)->owner : ((Leaf *)n)->owner;
        if (!(owner == tx || (append && owner == lin))) {
            n = node_copy(v, n, l, newtok);
            if (!n)
                return NULL;
            Py_DECREF(*pp);
            *pp = n;
        }
        if (l == 0)
            return ((Leaf *)n)->data + (i & (LEAF_ROWS - 1)) * v->rec;
        pp = &((Inner *)n)->kids[(i >> SHIFT(l)) & (FAN - 1)];
        if (!*pp) {
            *pp = l > 1 ? inner_new(v, newtok) : leaf_new(v, newtok);
            if (!*pp)
                return NULL;
        }
    }
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

static int
ent_cmp(const void *a, const void *b)
{
    return ent_lt(a, b) ? -1 : ent_lt(b, a) ? 1 : 0;
}

static int
ent_cmp_sn(const void *pa, const void *pb)
{
    const Ent *a = pa, *b = pb;
    if (a->s != b->s)
        return a->s < b->s ? -1 : 1;
    return a->nid < b->nid ? -1 : a->nid > b->nid;
}

static Run *
run_new(uint32_t cap, uint64_t owner)
{
    Run *r = PyMem_Malloc(offsetof(Run, e) + sizeof(Ent) * (cap ? cap : 1));
    if (!r) {
        PyErr_NoMemory();
        return NULL;
    }
    r->rc = 1;
    r->n = 0;
    r->owner = owner;
    return r;
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
