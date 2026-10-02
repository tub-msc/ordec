// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Storage primitives (see store.h): tree nodes, Vec writes, index runs
// and the block types.

#include "module.h"

uint64_t g_token = 1; // source of edit tokens; 0 is never a token
PyTypeObject *Leaf_Type, *LeafGC_Type, *InnerGC_Type;

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

int
ent_cmp_sn(const void *pa, const void *pb)
{
    const Ent *a = pa, *b = pb;
    if (a->s != b->s)
        return a->s < b->s ? -1 : 1;
    return a->nid < b->nid ? -1 : a->nid > b->nid;
}

Run *
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

// Creates the types of the tree nodes.
int
store_init(void)
{
    if (!(Leaf_Type = block_type("_ordb.Leaf", offsetof(Leaf, data),
            sizeof(slot_t), (destructor)leaf_dealloc, NULL, NULL))
        || !(LeafGC_Type = block_type("_ordb.LeafGC", offsetof(Leaf, data),
            sizeof(slot_t), (destructor)leaf_dealloc,
            (traverseproc)leaf_traverse, (inquiry)leaf_clear))
        || !(InnerGC_Type = block_type("_ordb.InnerGC", sizeof(Inner), 0,
            (destructor)inner_dealloc, (traverseproc)inner_traverse,
            (inquiry)inner_clear)))
        return -1;
    return 0;
}
