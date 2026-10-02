// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Storage primitives of the ORDB core (functions in store.c):
//
// - KMap: a persistent sparse array of records keyed by nid (the tables and
//   the directory).
// - BTree: a persistent B+tree of index entries (h, s, nid).
//
// Both copy on write by edit tokens. Table leaves that can hold
// Python object references (objmask != 0) are GC-tracked Python objects:
// leaves are shared between subgraphs, and the cycle collector must see
// each reference exactly once. Inner nodes are always GC objects (there
// are few of them), which also makes the leaves reachable for memory
// accounting via gc.get_referents.

#ifndef ORDB_STORE_H
#define ORDB_STORE_H

typedef int64_t slot_t;

extern uint64_t g_token; // source of edit tokens; 0 is never a token

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

// Index of the lowest set bit of m (m != 0), portable: the population
// count of the zeros below it.
static inline unsigned
ctz64(uint64_t m)
{
    return popcount64((m & (0 - m)) - 1);
}

// Releases the object references of n records and zeroes those slots.
static inline void
recs_clear(slot_t *p, uint64_t objmask, uint32_t rec, uint64_t n)
{
    if (!objmask)
        return;
    for (uint64_t r = 0; r < n; r++, p += rec) {
        for (uint64_t m = objmask; m; m &= m - 1) {
            int b = ctz64(m);
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
            Py_XINCREF((PyObject *)p[ctz64(m)]);
}

static inline int
recs_traverse(const slot_t *p, uint64_t objmask, uint32_t rec, uint64_t n,
    visitproc visit, void *arg)
{
    for (uint64_t r = 0; r < n; r++, p += rec)
        for (uint64_t m = objmask; m; m &= m - 1)
            Py_VISIT((PyObject *)p[ctz64(m)]);
    return 0;
}

// -- KMap --------------------------------------------------------------------

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
} Leaf;

typedef struct {
    PyObject_HEAD
    uint64_t owner;
    uint64_t hsum; // sum of the row hashes below, if hvalid
    uint8_t hvalid;
    uint64_t mask; // bit i: kids[i] is present
    PyObject *kids[1u << KF_BITS];
} Inner;

// A persistent sparse array of records keyed by nid: a radix trie with
// occupancy masks. Like everywhere else, a node is written in place only by
// the transaction that created it. The shape depends only on the content:
// the root has the fewest levels that hold the largest nid.
typedef struct {
    PyObject *root; // Leaf (levels 0) or Inner; NULL when empty
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
        if (!(n = ((const Inner *)n)->kids[i]))
            return NULL;
    }
    const Leaf *lf = (const Leaf *)n;
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
int store_init(void);
slot_t *kmap_insert(KMap *m, int64_t nid, uint64_t tok);
slot_t *kmap_at_w(KMap *m, int64_t nid, uint64_t tok);
int kmap_remove(KMap *m, int64_t nid, uint64_t tok);
const slot_t *kmap_next(const KMap *m, int64_t after, int64_t *nid);
int kmap_walk(const KMap *m, int (*fn)(const slot_t *, void *), void *arg);
int kmap_equal_plain(const KMap *a, const KMap *b);
void obj_free(void *o);
int ent_cmp(const void *a, const void *b);
int bt_insert(BTree *t, const Ent *e, uint64_t tok);
int bt_delete(BTree *t, const Ent *e, uint64_t tok);
int bt_add_sorted(BTree *t, const Ent *e, uint64_t n, uint64_t tok);
const Ent *bt_seek(BIter *it, const BTree *t, const Ent *key);
const Ent *bt_next(BIter *it);
int bt_check(const BTree *t);

#endif
