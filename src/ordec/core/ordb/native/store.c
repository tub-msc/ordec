// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Storage primitives (see store.h): the directory vector, keyed tables,
// index trees and the types of their nodes.

#include "module.h"

uint64_t g_token = 1; // source of edit tokens; 0 is never a token
PyTypeObject *Leaf_Type, *InnerGC_Type;

// Frees an instance of one of the (heap) types of the core and drops the
// reference the instance holds to its type.
void
obj_free(void *o)
{
    PyTypeObject *tp = Py_TYPE((PyObject *)o);
    freefunc tp_free = (freefunc)PyType_GetSlot(tp, Py_tp_free);
    tp_free(o);
    Py_DECREF(tp);
}

// -- Vec (the directory) -------------------------------------------------------

static void
leaf_dealloc(Leaf *n)
{
    obj_free(n);
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
    Leaf *n = PyObject_NewVar(Leaf, Leaf_Type, nslots);
    if (!n)
        return NULL;
    n->owner = tok;
    n->rec = v->rec;
    memset(n->data, 0, sizeof(slot_t) * nslots);
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
    return (PyObject *)c;
}

// Writable record i; does not change count. With append, the caller
// states that no other snapshot of this vector can see record i.
//
// Write rule: a node is written in place if it was created by this
// transaction (owner == tx), or if it is owned by this subgraph
// (owner == lin) and the write is an append. Every other node on the path
// is copied first.
slot_t *
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

int
ent_cmp(const void *a, const void *b)
{
    return ent_lt(a, b) ? -1 : ent_lt(b, a) ? 1 : 0;
}

// -- keyed tables ----------------------------------------------------------------

static PyTypeObject *KLeaf_Type, *KLeafGC_Type, *KInner_Type;

#define KW (1u << KW_BITS)

static inline uint32_t
kleaf_n(const KLeaf *n)
{
    return (uint32_t)__builtin_popcount(n->mask);
}

static inline uint32_t
kinner_n(const KInner *n)
{
    return (uint32_t)__builtin_popcountll(n->mask);
}

static void
kleaf_dealloc(KLeaf *n)
{
    if (n->objmask)
        PyObject_GC_UnTrack(n);
    recs_clear(n->data, n->objmask, n->rec, kleaf_n(n));
    obj_free(n);
}

static int
kleaf_traverse(KLeaf *n, visitproc visit, void *arg)
{
    Py_VISIT(Py_TYPE((PyObject *)n));
    return recs_traverse(n->data, n->objmask, n->rec, kleaf_n(n), visit,
        arg);
}

static int
kleaf_clear(KLeaf *n)
{
    recs_clear(n->data, n->objmask, n->rec, kleaf_n(n));
    return 0;
}

static void
kinner_dealloc(KInner *n)
{
    PyObject_GC_UnTrack(n);
    for (uint32_t i = 0; i < kinner_n(n); i++)
        Py_XDECREF(n->kids[i]);
    obj_free(n);
}

static int
kinner_traverse(KInner *n, visitproc visit, void *arg)
{
    Py_VISIT(Py_TYPE((PyObject *)n));
    for (uint32_t i = 0; i < kinner_n(n); i++)
        Py_VISIT(n->kids[i]);
    return 0;
}

static int
kinner_clear(KInner *n)
{
    uint32_t k = kinner_n(n);
    n->mask = 0;
    for (uint32_t i = 0; i < k; i++)
        Py_CLEAR(n->kids[i]);
    return 0;
}

// Capacities grow in powers of two.
static uint32_t
cap_for(uint32_t n)
{
    uint32_t c = 1;
    while (c < n)
        c *= 2;
    return c;
}

static KLeaf *
kleaf_new(const KMap *m, uint32_t cap, uint64_t tok)
{
    Py_ssize_t nslots = (Py_ssize_t)cap * m->rec;
    KLeaf *n = m->objmask ? PyObject_GC_NewVar(KLeaf, KLeafGC_Type, nslots)
        : PyObject_NewVar(KLeaf, KLeaf_Type, nslots);
    if (!n)
        return NULL;
    n->owner = tok;
    n->objmask = m->objmask;
    n->rec = m->rec;
    n->mask = 0;
    n->cap = cap;
    memset(n->data, 0, sizeof(slot_t) * nslots);
    if (m->objmask)
        PyObject_GC_Track(n);
    return n;
}

static KInner *
kinner_new(uint32_t cap, uint64_t tok)
{
    KInner *n = PyObject_GC_NewVar(KInner, KInner_Type, cap);
    if (!n)
        return NULL;
    n->owner = tok;
    n->mask = 0;
    n->cap = cap;
    memset(n->kids, 0, sizeof(PyObject *) * cap);
    PyObject_GC_Track(n);
    return n;
}

// The leaf *pp, writable for tok and with room for need rows: copied
// (taking references) unless tok created it, moved to a larger leaf if full.
static KLeaf *
kleaf_writable(const KMap *m, PyObject **pp, uint32_t need, uint64_t tok)
{
    KLeaf *n = (KLeaf *)*pp;
    uint32_t cnt = kleaf_n(n);
    if (n->owner == tok && n->cap >= need)
        return n;
    KLeaf *c = kleaf_new(m, cap_for(need > cnt ? need : cnt), tok);
    if (!c)
        return NULL;
    memcpy(c->data, n->data, sizeof(slot_t) * cnt * m->rec);
    c->mask = n->mask;
    if (n->owner == tok)
        n->mask = 0; // grown: the references move to the copy
    else
        recs_incref(c->data, m->objmask, m->rec, cnt);
    *pp = (PyObject *)c;
    Py_DECREF(n);
    return c;
}

// As kleaf_writable, for an inner node with room for need children.
static KInner *
kinner_writable(PyObject **pp, uint32_t need, uint64_t tok)
{
    KInner *n = (KInner *)*pp;
    uint32_t cnt = kinner_n(n);
    if (n->owner == tok && n->cap >= need)
        return n;
    KInner *c = kinner_new(cap_for(need > cnt ? need : cnt), tok);
    if (!c)
        return NULL;
    memcpy(c->kids, n->kids, sizeof(PyObject *) * cnt);
    c->mask = n->mask;
    if (n->owner == tok)
        n->mask = 0; // grown: the children move to the copy
    else
        for (uint32_t i = 0; i < cnt; i++)
            Py_INCREF(c->kids[i]);
    *pp = (PyObject *)c;
    Py_DECREF(n);
    return c;
}

static inline unsigned
kmap_shift(int level)
{
    return KW_BITS + KF_BITS * (level - 1);
}

// The leaf holding nid, writable for tok with room for extra more rows;
// missing nodes are created (create) or NULL is returned.
static KLeaf *
kmap_leaf_w(KMap *m, int64_t nid, uint64_t tok, uint32_t extra, int create)
{
    if (!m->root) {
        while ((uint64_t)nid >> (KW_BITS + KF_BITS * m->levels))
            m->levels++;
        m->root = m->levels ? (PyObject *)kinner_new(1, tok)
            : (PyObject *)kleaf_new(m, 1, tok);
        if (!m->root)
            return NULL;
    }
    while ((uint64_t)nid >> (KW_BITS + KF_BITS * m->levels)) {
        KInner *r = kinner_new(1, tok);
        if (!r)
            return NULL;
        r->kids[0] = m->root;
        r->mask = 1;
        m->root = (PyObject *)r;
        m->levels++;
    }
    PyObject **pp = &m->root;
    for (int l = m->levels; l > 0; l--) {
        unsigned i = ((uint64_t)nid >> kmap_shift(l)) & ((1u << KF_BITS) - 1);
        uint64_t bit = 1ull << i;
        KInner *in = (KInner *)*pp;
        int has = (in->mask & bit) != 0;
        if (!has && !create) {
            PyErr_SetString(PyExc_SystemError, "ORDB: keyed row missing");
            return NULL;
        }
        if (!(in = kinner_writable(pp, kinner_n(in) + !has, tok)))
            return NULL;
        unsigned k = __builtin_popcountll(in->mask & (bit - 1));
        if (!has) {
            PyObject *kid = l > 1 ? (PyObject *)kinner_new(1, tok)
                : (PyObject *)kleaf_new(m, 1, tok);
            if (!kid)
                return NULL;
            memmove(&in->kids[k + 1], &in->kids[k],
                sizeof(PyObject *) * (kinner_n(in) - k));
            in->kids[k] = kid;
            in->mask |= bit;
        }
        pp = &in->kids[k];
    }
    KLeaf *lf = (KLeaf *)*pp;
    return kleaf_writable(m, pp, kleaf_n(lf) + extra, tok);
}

// A new, cleared record for nid (which must be absent).
slot_t *
kmap_insert(KMap *m, int64_t nid, uint64_t tok)
{
    KLeaf *lf = kmap_leaf_w(m, nid, tok, 1, 1);
    if (!lf)
        return NULL;
    unsigned b = (uint64_t)nid & (KW - 1);
    if (lf->mask >> b & 1) {
        PyErr_SetString(PyExc_SystemError, "ORDB: keyed row exists");
        return NULL;
    }
    uint32_t cnt = kleaf_n(lf), r = __builtin_popcount(lf->mask & ((1u << b) - 1));
    slot_t *p = lf->data + r * m->rec;
    memmove(p + m->rec, p, sizeof(slot_t) * m->rec * (cnt - r));
    memset(p, 0, sizeof(slot_t) * m->rec);
    lf->mask |= 1u << b;
    return p;
}

// The writable record of the present nid.
slot_t *
kmap_at_w(KMap *m, int64_t nid, uint64_t tok)
{
    if (!kmap_get(m, nid)) {
        PyErr_SetString(PyExc_SystemError, "ORDB: keyed row missing");
        return NULL;
    }
    KLeaf *lf = kmap_leaf_w(m, nid, tok, 0, 0);
    if (!lf)
        return NULL;
    unsigned b = (uint64_t)nid & (KW - 1);
    return lf->data + __builtin_popcount(lf->mask & ((1u << b) - 1)) * m->rec;
}

// Removes nid below *pp; returns 1 if the node became empty.
static int
km_remove(const KMap *m, PyObject **pp, int level, int64_t nid, uint64_t tok)
{
    if (level == 0) {
        KLeaf *lf = kleaf_writable(m, pp, kleaf_n((KLeaf *)*pp), tok);
        if (!lf)
            return -1;
        unsigned b = (uint64_t)nid & (KW - 1);
        uint32_t cnt = kleaf_n(lf), r = __builtin_popcount(lf->mask & ((1u << b) - 1));
        slot_t *p = lf->data + r * m->rec;
        recs_clear(p, m->objmask, m->rec, 1);
        memmove(p, p + m->rec, sizeof(slot_t) * m->rec * (cnt - r - 1));
        memset(lf->data + (cnt - 1) * m->rec, 0, sizeof(slot_t) * m->rec);
        lf->mask &= ~(1u << b);
        return lf->mask == 0;
    }
    KInner *in = kinner_writable(pp, kinner_n((KInner *)*pp), tok);
    if (!in)
        return -1;
    unsigned i = ((uint64_t)nid >> kmap_shift(level)) & ((1u << KF_BITS) - 1);
    uint64_t bit = 1ull << i;
    unsigned k = __builtin_popcountll(in->mask & (bit - 1));
    int r = km_remove(m, &in->kids[k], level - 1, nid, tok);
    if (r != 1)
        return r;
    PyObject *kid = in->kids[k];
    memmove(&in->kids[k], &in->kids[k + 1],
        sizeof(PyObject *) * (kinner_n(in) - k - 1));
    in->kids[kinner_n(in) - 1] = NULL;
    in->mask &= ~bit;
    Py_DECREF(kid);
    return in->mask == 0;
}

int
kmap_remove(KMap *m, int64_t nid, uint64_t tok)
{
    if (!kmap_get(m, nid)) {
        PyErr_SetString(PyExc_SystemError, "ORDB: keyed row missing");
        return -1;
    }
    int r = km_remove(m, &m->root, m->levels, nid, tok);
    if (r < 0)
        return -1;
    if (r == 1) {
        Py_CLEAR(m->root);
        m->levels = 0;
    }
    return 0;
}

// The first record with a nid > after below the node n (covering nids from
// base), or NULL.
static const slot_t *
km_next(PyObject *n, int level, int64_t base, int64_t after, int64_t *out)
{
    if (level == 0) {
        const KLeaf *lf = (const KLeaf *)n;
        uint32_t mask = lf->mask;
        if (after >= base) {
            int64_t skip = after - base + 1;
            if (skip >= (int64_t)KW)
                return NULL;
            mask &= ~((1u << skip) - 1);
        }
        if (!mask)
            return NULL;
        unsigned b = __builtin_ctz(mask);
        *out = base + b;
        return lf->data + __builtin_popcount(lf->mask & ((1u << b) - 1))
            * lf->rec;
    }
    const KInner *in = (const KInner *)n;
    unsigned shift = kmap_shift(level);
    uint64_t mask = in->mask;
    if (after >= base) {
        uint64_t first = (uint64_t)(after - base) >> shift;
        if (first >= (1u << KF_BITS))
            return NULL;
        mask &= ~((1ull << first) - 1);
    }
    for (; mask; mask &= mask - 1) {
        unsigned i = __builtin_ctzll(mask);
        PyObject *kid = in->kids[__builtin_popcountll(in->mask & ((1ull << i) - 1))];
        const slot_t *p = km_next(kid, level - 1,
            base + ((int64_t)i << shift), after, out);
        if (p)
            return p;
    }
    return NULL;
}

// The record with the smallest nid > after (stored in *nid), or NULL. It
// descends from the root on every call, so it stays valid when the map
// changes between calls.
const slot_t *
kmap_next(const KMap *m, int64_t after, int64_t *nid)
{
    if (!m->root)
        return NULL;
    return km_next(m->root, m->levels, 0, after, nid);
}

// -- index trees ---------------------------------------------------------------

static PyTypeObject *BLeaf_Type, *BInner_Type;

static void
bleaf_dealloc(BLeaf *n)
{
    obj_free(n);
}

static void
binner_dealloc(BInner *n)
{
    PyObject_GC_UnTrack(n);
    for (uint32_t i = 0; i < n->n; i++)
        Py_XDECREF(n->kids[i]);
    obj_free(n);
}

static int
binner_traverse(BInner *n, visitproc visit, void *arg)
{
    Py_VISIT(Py_TYPE((PyObject *)n));
    for (uint32_t i = 0; i < n->n; i++)
        Py_VISIT(n->kids[i]);
    return 0;
}

static int
binner_clear(BInner *n)
{
    uint32_t k = n->n;
    n->n = 0;
    for (uint32_t i = 0; i < k; i++)
        Py_CLEAR(n->kids[i]);
    return 0;
}

static BLeaf *
bleaf_new(uint64_t tok)
{
    BLeaf *n = PyObject_New(BLeaf, BLeaf_Type);
    if (!n)
        return NULL;
    n->owner = tok;
    n->n = 0;
    return n;
}

static BInner *
binner_new(uint64_t tok)
{
    BInner *n = PyObject_GC_New(BInner, BInner_Type);
    if (!n)
        return NULL;
    n->owner = tok;
    n->n = 0;
    PyObject_GC_Track(n);
    return n;
}

static inline uint32_t
bt_n(PyObject *n, int leaf)
{
    return leaf ? ((BLeaf *)n)->n : ((BInner *)n)->n;
}

// First position in the leaf whose entry is >= e.
static uint32_t
leaf_lower_bound(const BLeaf *l, const Ent *e)
{
    uint32_t lo = 0, hi = l->n;
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        if (ent_lt(&l->e[mid], e))
            lo = mid + 1;
        else
            hi = mid;
    }
    return lo;
}

// The child of an inner node whose subtree holds e: the last one whose
// separator is <= e (the first one if there is none).
static uint32_t
inner_child(const BInner *in, const Ent *e)
{
    uint32_t lo = 1, hi = in->n;
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        if (ent_lt(e, &in->key[mid]))
            hi = mid;
        else
            lo = mid + 1;
    }
    return lo - 1;
}

// Makes the node *pp writable for transaction tok: copies it first unless
// tok created it.
static PyObject *
bt_writable(PyObject **pp, int leaf, uint64_t tok)
{
    PyObject *n = *pp;
    if ((leaf ? ((BLeaf *)n)->owner : ((BInner *)n)->owner) == tok)
        return n;
    PyObject *c;
    if (leaf) {
        BLeaf *src = (BLeaf *)n, *dst = bleaf_new(tok);
        if (!dst)
            return NULL;
        memcpy(dst->e, src->e, sizeof(Ent) * src->n);
        dst->n = src->n;
        c = (PyObject *)dst;
    } else {
        BInner *src = (BInner *)n, *dst = binner_new(tok);
        if (!dst)
            return NULL;
        memcpy(dst->key, src->key, sizeof(Ent) * src->n);
        for (uint32_t i = 0; i < src->n; i++)
            dst->kids[i] = Py_NewRef(src->kids[i]);
        dst->n = src->n;
        c = (PyObject *)dst;
    }
    *pp = c;
    Py_DECREF(n);
    return c;
}

// Inserts e below *pp (height inner levels). If the node splits, *right is
// the new right sibling and *sep its separator.
static int
bt_ins(PyObject **pp, int height, const Ent *e, uint64_t tok,
    PyObject **right, Ent *sep)
{
    *right = NULL;
    PyObject *n = bt_writable(pp, height == 0, tok);
    if (!n)
        return -1;
    if (height == 0) {
        BLeaf *l = (BLeaf *)n, *r = l;
        uint32_t i = leaf_lower_bound(l, e);
        if (l->n == BT_LEAF) {
            // Appending to a full leaf (ascending inserts, e.g. growing
            // nids within one key) keeps it full; otherwise split evenly.
            uint32_t keep = i == BT_LEAF ? BT_LEAF : BT_LEAF / 2;
            if (!(r = bleaf_new(tok)))
                return -1;
            r->n = BT_LEAF - keep;
            memcpy(r->e, l->e + keep, sizeof(Ent) * r->n);
            l->n = keep;
            *right = (PyObject *)r;
            if (i <= keep && keep < BT_LEAF)
                r = l;
            else
                i -= keep;
        }
        memmove(&r->e[i + 1], &r->e[i], sizeof(Ent) * (r->n - i));
        r->e[i] = *e;
        r->n++;
        if (*right)
            *sep = ((BLeaf *)*right)->e[0];
        return 0;
    }
    BInner *in = (BInner *)n;
    uint32_t i = inner_child(in, e);
    if (ent_lt(e, &in->key[i]))
        in->key[i] = *e; // i == 0: e is the new minimum
    PyObject *kid;
    Ent ksep;
    if (bt_ins(&in->kids[i], height - 1, e, tok, &kid, &ksep) < 0)
        return -1;
    if (!kid)
        return 0;
    BInner *r = in;
    i++; // position of the new child
    if (in->n == BT_FAN) {
        // As for leaves; the new node gets at least two children.
        uint32_t keep = i == BT_FAN ? BT_FAN - 1 : (BT_FAN + 1) / 2;
        if (!(r = binner_new(tok))) {
            Py_DECREF(kid);
            return -1;
        }
        uint32_t move = BT_FAN - keep;
        memcpy(r->key, in->key + keep, sizeof(Ent) * move);
        memcpy(r->kids, in->kids + keep, sizeof(PyObject *) * move);
        r->n = move;
        in->n = keep;
        *right = (PyObject *)r;
        if (i <= keep)
            r = in;
        else
            i -= keep;
    }
    memmove(&r->key[i + 1], &r->key[i], sizeof(Ent) * (r->n - i));
    memmove(&r->kids[i + 1], &r->kids[i], sizeof(PyObject *) * (r->n - i));
    r->key[i] = ksep;
    r->kids[i] = kid;
    r->n++;
    if (*right)
        *sep = ((BInner *)*right)->key[0];
    return 0;
}

int
bt_insert(BTree *t, const Ent *e, uint64_t tok)
{
    if (!t->root) {
        if (!(t->root = (PyObject *)bleaf_new(tok)))
            return -1;
        t->height = 0;
    }
    PyObject *right;
    Ent sep;
    if (bt_ins(&t->root, t->height, e, tok, &right, &sep) < 0)
        return -1;
    if (right) {
        if (t->height + 1 > BT_MAXH) {
            Py_DECREF(right);
            PyErr_SetString(PyExc_MemoryError, "ORDB: index too deep");
            return -1;
        }
        BInner *root = binner_new(tok);
        if (!root) {
            Py_DECREF(right);
            return -1;
        }
        root->key[0] = t->height == 0 ? ((BLeaf *)t->root)->e[0]
            : ((BInner *)t->root)->key[0];
        root->kids[0] = t->root;
        root->key[1] = sep;
        root->kids[1] = right;
        root->n = 2;
        t->root = (PyObject *)root;
        t->height++;
    }
    t->count++;
    return 0;
}

// Merges or evens out the children j and j + 1 of the writable inner node
// in (children are leaves if leaf).
static int
bt_balance(BInner *in, uint32_t j, int leaf, uint64_t tok)
{
    PyObject *a = bt_writable(&in->kids[j], leaf, tok);
    PyObject *b = a ? bt_writable(&in->kids[j + 1], leaf, tok) : NULL;
    if (!b)
        return -1;
    uint32_t na = bt_n(a, leaf), nb = bt_n(b, leaf);
    uint32_t cap = leaf ? BT_LEAF : BT_FAN;
    if (na + nb <= cap) {
        // b goes into a.
        if (leaf) {
            memcpy(((BLeaf *)a)->e + na, ((BLeaf *)b)->e, sizeof(Ent) * nb);
            ((BLeaf *)a)->n = na + nb;
        } else {
            BInner *ia = (BInner *)a, *ib = (BInner *)b;
            memcpy(ia->key + na, ib->key, sizeof(Ent) * nb);
            memcpy(ia->kids + na, ib->kids, sizeof(PyObject *) * nb);
            ia->key[na] = in->key[j + 1]; // ib->key[0] may be stale
            ia->n = na + nb;
            ib->n = 0; // its children moved to ia
        }
        Py_DECREF(b);
        memmove(&in->key[j + 1], &in->key[j + 2],
            sizeof(Ent) * (in->n - j - 2));
        memmove(&in->kids[j + 1], &in->kids[j + 2],
            sizeof(PyObject *) * (in->n - j - 2));
        in->n--;
        return 0;
    }
    // Even out: move k entries (children) between a and b.
    uint32_t ta = (na + nb) / 2;
    if (leaf) {
        BLeaf *la = (BLeaf *)a, *lb = (BLeaf *)b;
        if (na < ta) {
            uint32_t k = ta - na;
            memcpy(la->e + na, lb->e, sizeof(Ent) * k);
            memmove(lb->e, lb->e + k, sizeof(Ent) * (nb - k));
        } else {
            uint32_t k = na - ta;
            memmove(lb->e + k, lb->e, sizeof(Ent) * nb);
            memcpy(lb->e, la->e + ta, sizeof(Ent) * k);
        }
        lb->n = na + nb - ta;
        la->n = ta;
        in->key[j + 1] = lb->e[0];
    } else {
        BInner *ia = (BInner *)a, *ib = (BInner *)b;
        ib->key[0] = in->key[j + 1];
        if (na < ta) {
            uint32_t k = ta - na;
            memcpy(ia->key + na, ib->key, sizeof(Ent) * k);
            memcpy(ia->kids + na, ib->kids, sizeof(PyObject *) * k);
            memmove(ib->key, ib->key + k, sizeof(Ent) * (nb - k));
            memmove(ib->kids, ib->kids + k, sizeof(PyObject *) * (nb - k));
        } else {
            uint32_t k = na - ta;
            memmove(ib->key + k, ib->key, sizeof(Ent) * nb);
            memmove(ib->kids + k, ib->kids, sizeof(PyObject *) * nb);
            memcpy(ib->key, ia->key + ta, sizeof(Ent) * k);
            memcpy(ib->kids, ia->kids + ta, sizeof(PyObject *) * k);
        }
        ib->n = na + nb - ta;
        ia->n = ta;
        in->key[j + 1] = ib->key[0];
    }
    return 0;
}

// Removes e below *pp. Returns 1 if removed, 0 if absent, -1 on error.
static int
bt_del(PyObject **pp, int height, const Ent *e, uint64_t tok)
{
    if (height == 0) {
        BLeaf *l = (BLeaf *)*pp;
        uint32_t i = leaf_lower_bound(l, e);
        if (i >= l->n || !ent_eq(&l->e[i], e))
            return 0;
        if (!(l = (BLeaf *)bt_writable(pp, 1, tok)))
            return -1;
        memmove(&l->e[i], &l->e[i + 1], sizeof(Ent) * (l->n - i - 1));
        l->n--;
        return 1;
    }
    BInner *in = (BInner *)bt_writable(pp, 0, tok);
    if (!in)
        return -1;
    uint32_t i = inner_child(in, e);
    int r = bt_del(&in->kids[i], height - 1, e, tok);
    if (r <= 0)
        return r;
    int leaf = height == 1;
    if (in->n > 1 && bt_n(in->kids[i], leaf) < (leaf ? BT_LEAF_MIN : BT_FAN_MIN)
            && bt_balance(in, i + 1 < in->n ? i : i - 1, leaf, tok) < 0)
        return -1;
    return 1;
}

int
bt_delete(BTree *t, const Ent *e, uint64_t tok)
{
    if (!t->root)
        return 0;
    int r = bt_del(&t->root, t->height, e, tok);
    if (r <= 0)
        return r;
    t->count--;
    while (t->height > 0 && ((BInner *)t->root)->n == 1) {
        PyObject *kid = Py_NewRef(((BInner *)t->root)->kids[0]);
        Py_DECREF(t->root);
        t->root = kid;
        t->height--;
    }
    if (t->height == 0 && ((BLeaf *)t->root)->n == 0)
        Py_CLEAR(t->root);
    return 1;
}

// Position of the current leaf entry, moving to the next leaf at its end.
static const Ent *
bt_cur(BIter *it)
{
    int h = it->height;
    if (h < 0)
        return NULL;
    while (it->pos[h] >= ((BLeaf *)it->node[h])->n) {
        int l = h - 1;
        while (l >= 0 && it->pos[l] + 1 >= ((BInner *)it->node[l])->n)
            l--;
        if (l < 0) {
            it->height = -1;
            return NULL;
        }
        it->pos[l]++;
        for (l++; l <= h; l++) {
            it->node[l] = ((BInner *)it->node[l - 1])->kids[it->pos[l - 1]];
            it->pos[l] = 0;
        }
    }
    return &((BLeaf *)it->node[h])->e[it->pos[h]];
}

// The first entry >= key (NULL if none). The tree must not change while
// the iteration lasts (no Python code may run in between).
const Ent *
bt_seek(BIter *it, const BTree *t, const Ent *key)
{
    if (!t->root) {
        it->height = -1;
        return NULL;
    }
    it->height = t->height;
    PyObject *n = t->root;
    for (int l = 0; l < t->height; l++) {
        uint32_t i = inner_child((BInner *)n, key);
        it->node[l] = n;
        it->pos[l] = i;
        n = ((BInner *)n)->kids[i];
    }
    it->node[t->height] = n;
    it->pos[t->height] = leaf_lower_bound((BLeaf *)n, key);
    return bt_cur(it);
}

const Ent *
bt_next(BIter *it)
{
    if (it->height < 0)
        return NULL;
    it->pos[it->height]++;
    return bt_cur(it);
}

// Builds a tree from n ascending entries into the empty tree t, with evenly
// filled nodes.
static int
bt_build(BTree *t, const Ent *e, uint64_t n, uint64_t tok)
{
    if (n == 0)
        return 0;
    uint64_t m = (n + BT_LEAF - 1) / BT_LEAF; // nodes of the current level
    PyObject **nodes = PyMem_Malloc(sizeof(PyObject *) * m);
    Ent *mins = PyMem_Malloc(sizeof(Ent) * m);
    uint64_t live = 0; // nodes[0, live) are owned by the array
    int height = 0;
    if (!nodes || !mins) {
        PyErr_NoMemory();
        goto fail;
    }
    for (uint64_t pos = 0; live < m; live++) {
        uint64_t cnt = n / m + (live < n % m);
        BLeaf *l = bleaf_new(tok);
        if (!l)
            goto fail;
        memcpy(l->e, e + pos, sizeof(Ent) * cnt);
        l->n = (uint32_t)cnt;
        nodes[live] = (PyObject *)l;
        mins[live] = e[pos];
        pos += cnt;
    }
    while (m > 1) {
        uint64_t p = (m + BT_FAN - 1) / BT_FAN, src = 0;
        if (height == BT_MAXH) {
            PyErr_SetString(PyExc_MemoryError, "ORDB: index too deep");
            goto fail;
        }
        for (uint64_t k = 0; k < p; k++) {
            uint64_t cnt = m / p + (k < m % p);
            BInner *in = binner_new(tok);
            if (!in) {
                // nodes[0, k) are new, nodes[src, m) not yet moved.
                for (uint64_t x = 0; x < k; x++)
                    Py_DECREF(nodes[x]);
                for (uint64_t x = src; x < m; x++)
                    Py_DECREF(nodes[x]);
                live = 0;
                goto fail;
            }
            memcpy(in->key, mins + src, sizeof(Ent) * cnt);
            memcpy(in->kids, nodes + src, sizeof(PyObject *) * cnt);
            in->n = (uint32_t)cnt;
            nodes[k] = (PyObject *)in;
            mins[k] = mins[src];
            src += cnt;
        }
        live = m = p;
        height++;
    }
    t->root = nodes[0];
    t->height = height;
    t->count = n;
    PyMem_Free(nodes);
    PyMem_Free(mins);
    return 0;
fail:
    for (uint64_t x = 0; x < live; x++)
        Py_DECREF(nodes[x]);
    PyMem_Free(nodes);
    PyMem_Free(mins);
    return -1;
}

// Adds n ascending entries (none of them in t yet). A batch at least as
// large as the tree is merged and rebuilt, a smaller one inserted entry by
// entry (in order, so consecutive entries mostly go to the same leaf).
int
bt_add_sorted(BTree *t, const Ent *e, uint64_t n, uint64_t tok)
{
    if (n < t->count) {
        for (uint64_t k = 0; k < n; k++)
            if (bt_insert(t, &e[k], tok) < 0)
                return -1;
        return 0;
    }
    Ent *all = PyMem_Malloc(sizeof(Ent) * (t->count + n + 1));
    if (!all) {
        PyErr_NoMemory();
        return -1;
    }
    uint64_t k = 0, j = 0;
    BIter it;
    Ent lo = {0, INT64_MIN, INT64_MIN};
    for (const Ent *x = bt_seek(&it, t, &lo); x; x = bt_next(&it)) {
        while (j < n && ent_lt(&e[j], x))
            all[k++] = e[j++];
        all[k++] = *x;
    }
    while (j < n)
        all[k++] = e[j++];
    BTree nt = {NULL, 0, 0};
    int r = bt_build(&nt, all, k, tok);
    PyMem_Free(all);
    if (r < 0)
        return -1;
    Py_XDECREF(t->root);
    *t = nt;
    return 0;
}

// Checks the structure of a subtree: entry order, separators, node sizes.
// lo/hi bound its entries (lo <= entry < hi; NULL: unbounded).
static int
bt_check_node(PyObject *n, int height, const Ent *lo, const Ent *hi,
    int root, uint64_t *count)
{
    const char *bad = NULL;
    if (height == 0) {
        const BLeaf *l = (const BLeaf *)n;
        if (Py_TYPE(n) != BLeaf_Type)
            bad = "leaf expected";
        else if (l->n > BT_LEAF || (!root && !l->n))
            bad = "leaf size";
        for (uint32_t i = 0; !bad && i < l->n; i++) {
            if (i && !ent_lt(&l->e[i - 1], &l->e[i]))
                bad = "leaf order";
            else if ((lo && ent_lt(&l->e[i], lo))
                    || (hi && !ent_lt(&l->e[i], hi)))
                bad = "leaf entry outside its separators";
        }
        *count += l->n;
    } else {
        const BInner *in = (const BInner *)n;
        if (Py_TYPE(n) != BInner_Type)
            bad = "inner node expected";
        else if (in->n > BT_FAN || in->n < (root ? 2 : 1))
            bad = "inner node size";
        for (uint32_t i = 0; !bad && i < in->n; i++) {
            if (i && !ent_lt(&in->key[i - 1], &in->key[i]))
                bad = "separator order";
            else {
                const Ent *klo = i ? &in->key[i] : lo;
                const Ent *khi = i + 1 < in->n ? &in->key[i + 1] : hi;
                if (bt_check_node(in->kids[i], height - 1, klo, khi, 0,
                        count) < 0)
                    return -1;
            }
        }
    }
    if (bad) {
        PyErr_Format(PyExc_AssertionError,
            "ORDB: index tree is malformed (%s, height %d)", bad, height);
        return -1;
    }
    return 0;
}

int
bt_check(const BTree *t)
{
    uint64_t count = 0;
    if (t->root && bt_check_node(t->root, t->height, NULL, NULL, 1,
            &count) < 0)
        return -1;
    if (count != t->count) {
        PyErr_SetString(PyExc_AssertionError, "ORDB: index count is wrong");
        return -1;
    }
    return 0;
}

static PyTypeObject *
block_type(const char *name, int basicsize, int itemsize, destructor dealloc,
    traverseproc traverse, inquiry clear)
{
    PyType_Slot slots[4] = {{Py_tp_dealloc, dealloc}};
    if (traverse) {
        slots[1] = (PyType_Slot){Py_tp_traverse, traverse};
        slots[2] = (PyType_Slot){Py_tp_clear, clear};
    }
    PyType_Spec spec = {name, basicsize, itemsize,
        TPFLAGS | Py_TPFLAGS_DISALLOW_INSTANTIATION
        | (traverse ? Py_TPFLAGS_HAVE_GC : 0), slots};
    return (PyTypeObject *)PyType_FromSpec(&spec);
}

// Creates the types of the tree nodes (tables and indices).
int
store_init(void)
{
    if (!(Leaf_Type = block_type("_ordb.Leaf", offsetof(Leaf, data),
            sizeof(slot_t), (destructor)leaf_dealloc, NULL, NULL))
        || !(InnerGC_Type = block_type("_ordb.InnerGC", sizeof(Inner), 0,
            (destructor)inner_dealloc, (traverseproc)inner_traverse,
            (inquiry)inner_clear))
        || !(BLeaf_Type = block_type("_ordb.IndexLeaf", sizeof(BLeaf), 0,
            (destructor)bleaf_dealloc, NULL, NULL))
        || !(BInner_Type = block_type("_ordb.IndexInnerGC", sizeof(BInner), 0,
            (destructor)binner_dealloc, (traverseproc)binner_traverse,
            (inquiry)binner_clear))
        || !(KLeaf_Type = block_type("_ordb.KeyedLeaf", offsetof(KLeaf, data),
            sizeof(slot_t), (destructor)kleaf_dealloc, NULL, NULL))
        || !(KLeafGC_Type = block_type("_ordb.KeyedLeafGC",
            offsetof(KLeaf, data), sizeof(slot_t), (destructor)kleaf_dealloc,
            (traverseproc)kleaf_traverse, (inquiry)kleaf_clear))
        || !(KInner_Type = block_type("_ordb.KeyedInnerGC",
            offsetof(KInner, kids), sizeof(PyObject *),
            (destructor)kinner_dealloc, (traverseproc)kinner_traverse,
            (inquiry)kinner_clear)))
        return -1;
    return 0;
}
