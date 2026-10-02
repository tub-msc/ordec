// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Storage primitives of the ORDB core (functions in store.c):
//
// - Vec: a dense vector of fixed-size records of 8-byte slots without
//   object references (the nid directory), a persistent radix tree with
//   leaves of 16 records.
// - KMap: a persistent sparse array of records keyed by nid (the tables).
// - BTree: a persistent B+tree of index entries (h, s, nid).
//
// All three copy on write by edit tokens. Table leaves that can hold
// Python object references (objmask != 0) are GC-tracked Python objects:
// leaves are shared between subgraphs, and the cycle collector must see
// each reference exactly once. Inner nodes are always GC objects (there
// are few of them), which also makes the leaves reachable for memory
// accounting via gc.get_referents.

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
vec_init(Vec *v, uint32_t rec)
{
    v->root = NULL;
    v->count = 0;
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

// -- keyed tables (engine "keyed") -------------------------------------------

// Population counts. Without a POPCNT target (the portable x86-64 baseline)
// the builtins become library calls; the bit tricks are inline.
static inline unsigned
popcount32(uint32_t x)
{
#ifdef __POPCNT__
    return (unsigned)__builtin_popcount(x);
#else
    x = x - ((x >> 1) & 0x55555555u);
    x = (x & 0x33333333u) + ((x >> 2) & 0x33333333u);
    return (((x + (x >> 4)) & 0x0F0F0F0Fu) * 0x01010101u) >> 24;
#endif
}

static inline unsigned
popcount64(uint64_t x)
{
#ifdef __POPCNT__
    return (unsigned)__builtin_popcountll(x);
#else
    x = x - ((x >> 1) & 0x5555555555555555ull);
    x = (x & 0x3333333333333333ull) + ((x >> 2) & 0x3333333333333333ull);
    return (((x + (x >> 4)) & 0x0F0F0F0F0F0F0F0Full)
        * 0x0101010101010101ull) >> 56;
#endif
}

#define KW_BITS 4 // nids per leaf: 16
#define KF_BITS 6 // children per inner node: 64

typedef struct {
    PyObject_VAR_HEAD // ob_size: slots allocated (cap * rec)
    uint64_t owner;
    uint64_t hsum; // sum of the row hashes, if hvalid (see sg_content_hash)
    uint8_t hvalid;
    uint64_t objmask;
    uint32_t rec;
    uint32_t mask; // bit b: nid base + b is present
    uint32_t cap; // rows allocated
    slot_t data[1]; // the present rows, packed in nid order
} KLeaf;

typedef struct {
    PyObject_HEAD
    uint64_t owner;
    uint64_t hsum; // sum of the row hashes below, if hvalid
    uint8_t hvalid;
    uint64_t mask; // bit i: kids[i] is present
    PyObject *kids[1u << KF_BITS];
} KInner;

// A persistent sparse array of records keyed by nid: a radix trie with
// occupancy masks. Like everywhere else, a node is written in place only by
// the transaction that created it. The shape depends only on the content:
// the root has the fewest levels that hold the largest nid.
typedef struct {
    PyObject *root; // KLeaf (levels 0) or KInner; NULL when empty
    uint64_t objmask;
    uint32_t rec;
    uint8_t levels; // inner levels above the leaves
} KMap;

static inline void
kmap_init(KMap *m, uint32_t rec, uint64_t objmask)
{
    m->root = NULL;
    m->objmask = objmask;
    m->rec = rec;
    m->levels = 0;
}

// The record of nid, or NULL.
static inline const slot_t *
kmap_get(const KMap *m, int64_t nid)
{
    PyObject *n = m->root;
    if (!n || nid < 0 || (uint64_t)nid >> (KW_BITS + KF_BITS * m->levels))
        return NULL;
    for (int l = m->levels; l > 0; l--) {
        unsigned i = ((uint64_t)nid >> (KW_BITS + KF_BITS * (l - 1)))
            & ((1u << KF_BITS) - 1);
        if (!(n = ((const KInner *)n)->kids[i]))
            return NULL;
    }
    const KLeaf *lf = (const KLeaf *)n;
    unsigned b = (uint64_t)nid & ((1u << KW_BITS) - 1);
    if (!(lf->mask >> b & 1))
        return NULL;
    return lf->data + popcount32(lf->mask & ((1u << b) - 1)) * lf->rec;
}

// -- index trees -------------------------------------------------------------

typedef struct {
    uint64_t h; // key hash
    int64_t s; // sort value
    int64_t nid;
} Ent;

static inline int
ent_lt(const Ent *a, const Ent *b)
{
    if (a->h != b->h)
        return a->h < b->h;
    if (a->s != b->s)
        return a->s < b->s;
    return a->nid < b->nid;
}

static inline int
ent_eq(const Ent *a, const Ent *b)
{
    return a->h == b->h && a->s == b->s && a->nid == b->nid;
}

#ifndef BT_LEAF
#define BT_LEAF 32 // entries per leaf
#endif
#ifndef BT_FAN
#define BT_FAN 32 // children per inner node
#endif
#define BT_MAXH 12 // levels (BT_FAN^11 leaves)
// Below these sizes, a node (other than the root) is merged with a sibling
// or evened out with it. Inner nodes keep at least two children, so that
// every leaf has a sibling to merge with.
#define BT_LEAF_MIN (BT_LEAF / 4 > 1 ? BT_LEAF / 4 : 1)
#define BT_FAN_MIN (BT_FAN / 4 > 2 ? BT_FAN / 4 : 2)

typedef struct {
    PyObject_HEAD
    uint64_t owner;
    uint32_t n;
    Ent e[BT_LEAF];
} BLeaf;

typedef struct {
    PyObject_HEAD
    uint64_t owner;
    uint32_t n;
    // key[i] <= every entry below kids[i] and > every entry below
    // kids[i - 1]: the separators.
    Ent key[BT_FAN];
    PyObject *kids[BT_FAN];
} BInner;

// A persistent B+tree of entries in ascending order. Like the table pages,
// a node is written in place only by the transaction that created it
// (owner == tok); any other write copies the path from the root.
typedef struct {
    PyObject *root; // BLeaf (height 0) or BInner; NULL when empty
    uint64_t count;
    int height; // inner levels above the leaves
} BTree;

// Position in a BTree for in-order iteration (bt_seek, bt_next).
typedef struct {
    int height;
    PyObject *node[BT_MAXH + 1];
    uint32_t pos[BT_MAXH + 1];
} BIter;

// store.c
extern PyTypeObject *Leaf_Type, *InnerGC_Type;
int store_init(void);
slot_t *kmap_insert(KMap *m, int64_t nid, uint64_t tok);
slot_t *kmap_at_w(KMap *m, int64_t nid, uint64_t tok);
int kmap_remove(KMap *m, int64_t nid, uint64_t tok);
const slot_t *kmap_next(const KMap *m, int64_t after, int64_t *nid);
int kmap_walk(const KMap *m, int (*fn)(const slot_t *, void *), void *arg);
int kmap_equal_plain(const KMap *a, const KMap *b);
void obj_free(void *o);
slot_t *vec_at_w(Vec *v, uint64_t i, uint64_t lin, uint64_t tx, int append);
int ent_cmp(const void *a, const void *b);
int bt_insert(BTree *t, const Ent *e, uint64_t tok);
int bt_delete(BTree *t, const Ent *e, uint64_t tok);
int bt_add_sorted(BTree *t, const Ent *e, uint64_t n, uint64_t tok);
const Ent *bt_seek(BIter *it, const BTree *t, const Ent *key);
const Ent *bt_next(BIter *it);
int bt_check(const BTree *t);

#endif
