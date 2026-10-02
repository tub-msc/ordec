// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Cursors (NodeBase), attribute descriptors and the cursor iterator.

#include "module.h"

// ---------------------------------------------------------------------------
// Cursor (Node base class)
// ---------------------------------------------------------------------------

// Calls an of_subgraph function for the node nid. Returns the subgraph of
// the SubgraphRoot it returns (new reference), NULL with no error if it
// returned something else, NULL with error on failure.
Sg *
call_subfn(PyObject *fn, Sg *sg, int64_t nid)
{
    PyObject *c = sg_cursor(sg, nid, NPATH_NONE);
    if (!c)
        return NULL;
    PyObject *r = PyObject_CallFunctionObjArgs(fn, c, NULL);
    Py_DECREF(c);
    if (!r)
        return NULL;
    Sg *target = NULL;
    if (PyObject_TypeCheck(r, Node_Type) && ((NodeObj *)r)->nid == 0)
        target = (Sg *)Py_NewRef((PyObject *)((NodeObj *)r)->sg);
    Py_DECREF(r);
    return target;
}

PyObject *
node_make(PyObject *cls, Sg *sg, int64_t nid, int64_t npath)
{
    PyTypeObject *t = (PyTypeObject *)cls;
    NodeObj *c = (NodeObj *)PyType_GenericAlloc(t, 0);
    if (!c)
        return NULL;
    c->sg = (Sg *)Py_NewRef((PyObject *)sg);
    c->nid = nid;
    c->npath = npath;
    return (PyObject *)c;
}

PyObject *
key_error_nid(int64_t nid)
{
    PyObject *k = PyLong_FromLongLong(nid);
    if (k) {
        PyErr_SetObject(PyExc_KeyError, k);
        Py_DECREF(k);
    }
    return NULL;
}

PyObject *
sg_cursor(Sg *sg, int64_t nid, int64_t npath)
{
    int ti;
    if (!st_row(&sg->st, nid, &ti))
        return key_error_nid(nid);
    NType *nt = sg->st.tabs[ti].nt;
    PyObject *cls = sg->frozen ? nt->cur_frz : nt->cur_mut;
    if (!cls) {
        PyErr_SetString(PyExc_SystemError, "ORDB: node type without cursors");
        return NULL;
    }
    return node_make(cls, sg, nid, npath);
}

static int
node_traverse(NodeObj *c, visitproc visit, void *arg)
{
    Py_VISIT(Py_TYPE((PyObject *)c));
    Py_VISIT(c->sg);
    return 0;
}

static int
node_clear(NodeObj *c)
{
    Py_CLEAR(c->sg);
    return 0;
}

static void
node_dealloc(NodeObj *c)
{
    PyObject_GC_UnTrack(c);
    Py_XDECREF((PyObject *)c->sg);
    obj_free(c);
}

static int
node_resolve_npath(NodeObj *c)
{
    if (c->npath != NPATH_UNRESOLVED)
        return 0;
    if (c->nid < 0 || !g_npath_index) {
        c->npath = NPATH_NONE;
        return 0;
    }
    PyObject *key = PyLong_FromLongLong(c->nid);
    if (!key)
        return -1;
    PyObject *l = st_query(&c->sg->st, g_npath_index, key);
    Py_DECREF(key);
    if (!l)
        return -1;
    c->npath = PyList_Size(l) > 0
        ? PyLong_AsLongLong(PyList_GetItem(l, 0)) : NPATH_NONE;
    Py_DECREF(l);
    return 0;
}

static PyObject *
node_get_subgraph(NodeObj *c, void *closure)
{
    return Py_NewRef((PyObject *)c->sg);
}

static PyObject *
node_get_nid(NodeObj *c, void *closure)
{
    if (c->nid < 0)
        Py_RETURN_NONE;
    return PyLong_FromLongLong(c->nid);
}

static PyObject *
node_get_npath_nid(NodeObj *c, void *closure)
{
    if (node_resolve_npath(c) < 0)
        return NULL;
    if (c->npath < 0)
        Py_RETURN_NONE;
    return PyLong_FromLongLong(c->npath);
}

int
opt_nid(PyObject *o, int64_t none, int64_t *out)
{
    if (o == Py_None) {
        *out = none;
        return 0;
    }
    *out = PyLong_AsLongLong(o);
    if (*out == -1 && PyErr_Occurred())
        return -1;
    if (*out < 0) {
        PyErr_SetString(PyExc_ValueError, "nid must not be negative");
        return -1;
    }
    return 0;
}

static PyObject *
node_raw_cursor(PyObject *cls, PyObject *args)
{
    PyObject *sg, *nid_o, *npath_o;
    int64_t nid, npath;
    if (!PyArg_ParseTuple(args, "O!OO", Sg_Type, &sg, &nid_o, &npath_o))
        return NULL;
    if (opt_nid(nid_o, -1, &nid) < 0 || opt_nid(npath_o, NPATH_NONE, &npath) < 0)
        return NULL;
    return node_make(cls, (Sg *)sg, nid, npath);
}

// Cursors of one subgraph are ordered by nid (PathNodes, nid -1: by npath),
// consistent with equality; code relies on this, e.g. as a tie breaker when
// sorting (key, cursor) pairs.
// NotImplemented is returned with Py_NewRef: Py_RETURN_NOTIMPLEMENTED of the
// 3.12+ headers does not increment the count, even for the 3.11 limited API.
static PyObject *
node_order(NodeObj *x, NodeObj *y, int op)
{
    int same = x->sg == y->sg;
    if (!same) {
        same = PyObject_RichCompareBool((PyObject *)x->sg, (PyObject *)y->sg,
            Py_EQ);
        if (same < 0)
            return NULL;
        if (!same)
            return Py_NewRef(Py_NotImplemented);
    }
    int c = x->nid != y->nid ? (x->nid < y->nid ? -1 : 1) : 0;
    if (c == 0 && x->nid < 0) {
        if (node_resolve_npath(x) < 0 || node_resolve_npath(y) < 0)
            return NULL;
        c = x->npath != y->npath ? (x->npath < y->npath ? -1 : 1) : 0;
    }
    Py_RETURN_RICHCOMPARE(c, 0, op);
}

static PyObject *
node_richcompare(PyObject *a, PyObject *b, int op)
{
    if (!PyObject_TypeCheck(b, Node_Type))
        return Py_NewRef(Py_NotImplemented);
    if (op != Py_EQ && op != Py_NE)
        return node_order((NodeObj *)a, (NodeObj *)b, op);
    NodeObj *x = (NodeObj *)a, *y = (NodeObj *)b;
    int eq = x->nid == y->nid;
    if (eq && x->nid < 0) {
        if (node_resolve_npath(x) < 0 || node_resolve_npath(y) < 0)
            return NULL;
        eq = x->npath == y->npath;
    }
    if (eq && x->sg != y->sg) {
        eq = PyObject_RichCompareBool((PyObject *)x->sg, (PyObject *)y->sg,
            Py_EQ);
        if (eq < 0)
            return NULL;
    }
    return PyBool_FromLong(op == Py_EQ ? eq : !eq);
}

static Py_hash_t
node_hash(NodeObj *c)
{
    Py_hash_t h = PyObject_Hash((PyObject *)c->sg);
    if (h == -1 && PyErr_Occurred())
        return -1;
    int64_t id = c->nid;
    if (id < 0) {
        if (node_resolve_npath(c) < 0)
            return -1;
        id = ~c->npath;
    }
    h = (Py_hash_t)mix((uint64_t)h, (uint64_t)id);
    return h == -1 ? -2 : h;
}

static PyGetSetDef node_getset[] = {
    {"subgraph", (getter)node_get_subgraph, NULL,
        "The subgraph of the selected node."},
    {"nid", (getter)node_get_nid, NULL,
        "The node ID (nid) of the selected node."},
    {"npath_nid", (getter)node_get_npath_nid, NULL,
        "The nid of the NPath node matching the selected node."},
    {NULL}
};

static PyMethodDef node_methods[] = {
    {"raw_cursor", (PyCFunction)node_raw_cursor, METH_VARARGS | METH_CLASS,
        NULL},
    {NULL}
};

// -- attribute descriptor ----------------------------------------------------

typedef struct {
    PyObject_HEAD
    PyObject *attr;
    NType *nt;
    int index;
} AttrDesc;

static PyObject *
attrdesc_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    PyObject *attr, *nt;
    int index;
    if (!PyArg_ParseTuple(args, "OO!i", &attr, NType_Type, &nt, &index))
        return NULL;
    if (index < 0 || index >= ((NType *)nt)->nattr) {
        PyErr_SetString(PyExc_ValueError, "bad attribute position");
        return NULL;
    }
    AttrDesc *d = (AttrDesc *)PyType_GenericAlloc(type, 0);
    if (!d)
        return NULL;
    d->attr = Py_NewRef(attr);
    d->nt = (NType *)Py_NewRef(nt);
    d->index = index;
    return (PyObject *)d;
}

static int
attrdesc_traverse(AttrDesc *d, visitproc visit, void *arg)
{
    Py_VISIT(Py_TYPE((PyObject *)d));
    Py_VISIT(d->attr);
    Py_VISIT(d->nt);
    return 0;
}

static int
attrdesc_clear(AttrDesc *d)
{
    Py_CLEAR(d->attr);
    Py_CLEAR(d->nt);
    return 0;
}

static void
attrdesc_dealloc(AttrDesc *d)
{
    PyObject_GC_UnTrack(d);
    attrdesc_clear(d);
    obj_free(d);
}

static PyObject *
attrdesc_get(AttrDesc *d, PyObject *obj, PyObject *type)
{
    if (!obj || obj == Py_None)
        return Py_NewRef(d->attr);
    if (!PyObject_TypeCheck(obj, Node_Type)) {
        PyErr_SetString(PyExc_TypeError, "descriptor requires a Node");
        return NULL;
    }
    NodeObj *c = (NodeObj *)obj;
    const State *st = &c->sg->st;
    NType *nt = d->nt;
    // The descriptor knows the node type and thus the table: no directory
    // lookup. Without a row there, the directory tells why.
    int ti = st_find_tab(st, nt);
    const slot_t *p = ti >= 0 ? kmap_get(&st->tabs[ti].rows, c->nid) : NULL;
    if (!p) {
        if (!st_row(st, c->nid, &ti))
            return key_error_nid(c->nid);
        PyErr_Format(OrdbException,
            "Node nid=%lld was replaced by a node of another type.",
            (long long)c->nid);
        return NULL;
    }
    const AttrInfo *ai = &nt->attrs[d->index];
    if (ai->read_mode == READ_LOCALREF && p[ai->slot] != SLOT_BOXED) {
        if (p[ai->slot] == SLOT_NONE)
            Py_RETURN_NONE;
        return sg_cursor(c->sg, p[ai->slot], NPATH_UNRESOLVED);
    }
    if (ai->read_mode == READ_EXTREF && ai->ext_refs) {
        // of_subgraph(cursor).cursor_at(value) of ExternalRef.read_hook.
        // Everything else (no target subgraph or root, a negative or boxed
        // value) is left to the hook.
        slot_t v = p[ai->slot];
        if (v == SLOT_NONE)
            Py_RETURN_NONE;
        Sg *target = v >= 0 ? ext_target(st, nt, ai, p, c->nid) : NULL;
        int rti;
        if (target && st_row(&target->st, 0, &rti)) {
            Py_INCREF((PyObject *)target);
            PyObject *r = sg_cursor(target, v, NPATH_UNRESOLVED);
            Py_DECREF((PyObject *)target);
            return r;
        }
    }
    PyObject *v = attr_value(st, nt, d->index, p, c->nid);
    if (!v || ai->read_mode == READ_PLAIN)
        return v;
    PyObject *r = PyObject_CallMethodObjArgs(ai->attr, str_read_hook, v, obj,
        NULL);
    Py_DECREF(v);
    return r;
}

static int
attrdesc_set(AttrDesc *d, PyObject *obj, PyObject *value)
{
    if (!value) {
        PyErr_SetString(PyExc_TypeError, "Attributes cannot be deleted.");
        return -1;
    }
    if (!PyObject_TypeCheck(obj, Node_Type)) {
        PyErr_SetString(PyExc_TypeError, "descriptor requires a Node");
        return -1;
    }
    NodeObj *c = (NodeObj *)obj;
    return sg_set1(c->sg, c->nid, d->nt, d->index, value);
}

// -- cursor iteration and path lookup ---------------------------------------

typedef struct {
    PyObject_HEAD
    Sg *sg;
    PyObject *nids; // list
    Py_ssize_t pos;
} CurIter;

static int
curiter_traverse(CurIter *it, visitproc visit, void *arg)
{
    Py_VISIT(Py_TYPE((PyObject *)it));
    Py_VISIT(it->sg);
    Py_VISIT(it->nids);
    return 0;
}

static void
curiter_dealloc(CurIter *it)
{
    PyObject_GC_UnTrack(it);
    Py_XDECREF((PyObject *)it->sg);
    Py_XDECREF(it->nids);
    obj_free(it);
}

static PyObject *
curiter_next(CurIter *it)
{
    if (it->pos >= PyList_Size(it->nids))
        return NULL;
    long long nid = PyLong_AsLongLong(PyList_GetItem(it->nids, it->pos++));
    if (nid == -1 && PyErr_Occurred())
        return NULL;
    return sg_cursor(it->sg, nid, NPATH_UNRESOLVED);
}

// _cursors(nids): iterator of cursors at the nids of a list (snapshot).
PyObject *
sg_cursors(Sg *sg, PyObject *nids)
{
    if (!PyList_Check(nids)) {
        PyErr_SetString(PyExc_TypeError, "list expected");
        return NULL;
    }
    CurIter *it = PyObject_GC_New(CurIter, CurIter_Type);
    if (!it)
        return NULL;
    it->sg = (Sg *)Py_NewRef((PyObject *)sg);
    it->nids = Py_NewRef(nids);
    it->pos = 0;
    PyObject_GC_Track(it);
    return (PyObject *)it;
}
static PyType_Slot node_slots[] = {
    {Py_tp_dealloc, node_dealloc},
    {Py_tp_traverse, node_traverse},
    {Py_tp_clear, node_clear},
    {Py_tp_richcompare, node_richcompare},
    {Py_tp_hash, node_hash},
    {Py_tp_getset, node_getset},
    {Py_tp_methods, node_methods},
    {0, NULL}
};

PyType_Spec node_spec = {"ordec.core.ordb._ordb.NodeBase",
    sizeof(NodeObj), 0, TPFLAGS | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC
    | Py_TPFLAGS_DISALLOW_INSTANTIATION, node_slots};

static PyType_Slot attrdesc_slots[] = {
    {Py_tp_new, attrdesc_new},
    {Py_tp_dealloc, attrdesc_dealloc},
    {Py_tp_traverse, attrdesc_traverse},
    {Py_tp_clear, attrdesc_clear},
    {Py_tp_descr_get, attrdesc_get},
    {Py_tp_descr_set, attrdesc_set},
    {0, NULL}
};

PyType_Spec attrdesc_spec = {"ordec.core.ordb._ordb.AttrDescriptor",
    sizeof(AttrDesc), 0, TPFLAGS | Py_TPFLAGS_HAVE_GC, attrdesc_slots};

static PyType_Slot curiter_slots[] = {
    {Py_tp_dealloc, curiter_dealloc},
    {Py_tp_traverse, curiter_traverse},
    {Py_tp_iter, PyObject_SelfIter},
    {Py_tp_iternext, curiter_next},
    {0, NULL}
};

PyType_Spec curiter_spec = {"ordec.core.ordb._ordb.CursorIterator",
    sizeof(CurIter), 0, TPFLAGS | Py_TPFLAGS_HAVE_GC
    | Py_TPFLAGS_DISALLOW_INSTANTIATION, curiter_slots};
