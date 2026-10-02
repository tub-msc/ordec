// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// NType (what the core knows about one node type) and NodeTuple
// construction.

#include "module.h"

// ---------------------------------------------------------------------------
// NType: what the core knows about one node type
// ---------------------------------------------------------------------------

static int
ntype_traverse(NType *nt, visitproc visit, void *arg)
{
    Py_VISIT(Py_TYPE((PyObject *)nt));
    Py_VISIT(nt->tuple_cls);
    Py_VISIT(nt->cursor_type);
    Py_VISIT(nt->cur_mut);
    Py_VISIT(nt->cur_frz);
    Py_VISIT(nt->permitted);
    for (int i = 0; i < nt->nattr; i++) {
        Py_VISIT(nt->attrs[i].attr);
        Py_VISIT(nt->attrs[i].vtype);
        Py_VISIT(nt->attrs[i].refcache);
        Py_VISIT(nt->attrs[i].ftype);
        Py_VISIT(nt->attrs[i].fdefault);
        Py_VISIT(nt->attrs[i].subfn);
        Py_VISIT(nt->attrs[i].ext_refs);
    }
    for (int i = 0; i < nt->nuse; i++) {
        Py_VISIT(nt->uses[i].index);
        Py_VISIT(nt->uses[i].sortfn);
    }
    return 0;
}

static int
ntype_clear(NType *nt)
{
    Py_CLEAR(nt->tuple_cls);
    Py_CLEAR(nt->cursor_type);
    Py_CLEAR(nt->cur_mut);
    Py_CLEAR(nt->cur_frz);
    Py_CLEAR(nt->permitted);
    for (int i = 0; i < nt->nattr; i++) {
        Py_CLEAR(nt->attrs[i].attr);
        Py_CLEAR(nt->attrs[i].vtype);
        Py_CLEAR(nt->attrs[i].refcache);
        Py_CLEAR(nt->attrs[i].ftype);
        Py_CLEAR(nt->attrs[i].fdefault);
        Py_CLEAR(nt->attrs[i].subfn);
        Py_CLEAR(nt->attrs[i].ext_refs);
    }
    for (int i = 0; i < nt->nuse; i++) {
        Py_CLEAR(nt->uses[i].index);
        Py_CLEAR(nt->uses[i].sortfn);
    }
    return 0;
}

static void
ntype_dealloc(NType *nt)
{
    PyObject_GC_UnTrack(nt);
    ntype_clear(nt);
    for (int i = 0; i < nt->nattr; i++)
        Py_XDECREF(nt->attrs[i].name);
    PyMem_Free(nt->attrs);
    PyMem_Free(nt->uses);
    PyMem_Free(nt->checks);
    obj_free(nt);
}

// NType(tuple_cls, cursor_type, attrs, uses, checks)
//   attrs: [(name, kind, width, vtype, optional, attr, read_mode, ref_kind,
//       ext, fmode, ftype, fdefault, subfn)]
//   ext: None or (start, tuple of SubgraphRef attributes)
//   uses: [(index, key_positions, sort_position, unique, combined, sortfn)]
//   checks: [(kind, i)], in the order in which they are run
static PyObject *
ntype_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    PyObject *tuple_cls, *cursor_type, *attrs, *uses, *checks;
    if (!PyArg_ParseTuple(args, "OOO!O!O!", &tuple_cls, &cursor_type,
            &PyList_Type, &attrs, &PyList_Type, &uses, &PyList_Type, &checks))
        return NULL;
    NType *nt = (NType *)PyType_GenericAlloc(type, 0);
    if (!nt)
        return NULL;
    nt->tuple_cls = Py_NewRef(tuple_cls);
    nt->cursor_type = Py_NewRef(cursor_type);
    nt->permitted = PyDict_New();
    nt->nattr = (int)PyList_Size(attrs);
    nt->ref_attr = -1;
    nt->nuse = (int)PyList_Size(uses);
    nt->ncheck = (int)PyList_Size(checks);
    nt->attrs = PyMem_Calloc(nt->nattr + 1, sizeof(AttrInfo));
    nt->uses = PyMem_Calloc(nt->nuse + 1, sizeof(IdxUse));
    nt->checks = PyMem_Calloc(nt->ncheck + 1, sizeof(CheckItem));
    if (!nt->permitted || !nt->attrs || !nt->uses || !nt->checks) {
        Py_DECREF(nt);
        return PyErr_NoMemory();
    }
    int slot = 1;
    for (int i = 0; i < nt->nattr; i++) {
        AttrInfo *ai = &nt->attrs[i];
        PyObject *name, *vtype, *attr, *ext, *ftype, *fdefault, *subfn;
        if (!PyArg_ParseTuple(PyList_GetItem(attrs, i), "UiiOpOiiOiOOO", &name,
                &ai->kind, &ai->width, &vtype, &ai->optional, &attr,
                &ai->read_mode, &ai->ref_kind, &ext, &ai->fmode, &ftype,
                &fdefault, &subfn)) {
            Py_DECREF(nt);
            return NULL;
        }
        ai->name = Py_NewRef(name);
        ai->ftype = Py_NewRef(ftype);
        ai->fdefault = Py_NewRef(fdefault);
        if (PyUnicode_CompareWithASCIIString(name, "ref") == 0)
            nt->ref_attr = i;
        ai->attr = Py_NewRef(attr);
        ai->vtype = vtype == Py_None ? NULL : Py_NewRef(vtype);
        if (ext != Py_None) {
            PyObject *refs;
            if (!PyArg_ParseTuple(ext, "iO!", &ai->ext_start, &PyTuple_Type,
                    &refs)) {
                Py_DECREF(nt);
                return NULL;
            }
            ai->ext_refs = Py_NewRef(refs);
        }
        ai->subfn = subfn == Py_None ? NULL : Py_NewRef(subfn);
        if (ai->ref_kind != REF_NONE) {
            ai->refcache = PyDict_New();
            if (!ai->refcache) {
                Py_DECREF(nt);
                return NULL;
            }
        }
        if (ai->kind != K_IVEC)
            ai->width = 1;
        ai->slot = slot;
        if (ai->kind == K_OBJ)
            nt->objmask |= (uint64_t)1 << slot;
        slot += ai->width;
    }
    nt->rec = slot;
    if (slot > 64) {
        Py_DECREF(nt);
        PyErr_SetString(PyExc_TypeError,
            "Node types are limited to 63 attribute slots.");
        return NULL;
    }
    if (nt->nuse > MAXUSE) {
        Py_DECREF(nt);
        PyErr_Format(PyExc_TypeError,
            "Node types are limited to %d indices.", MAXUSE);
        return NULL;
    }
    for (int i = 0; i < nt->nuse; i++) {
        IdxUse *u = &nt->uses[i];
        PyObject *index, *key, *sortfn;
        if (!PyArg_ParseTuple(PyList_GetItem(uses, i), "OO!ippO", &index,
                &PyTuple_Type, &key, &u->sort, &u->unique, &u->combined,
                &sortfn)) {
            Py_DECREF(nt);
            return NULL;
        }
        u->nkey = (int)PyTuple_Size(key);
        if (u->nkey < 1 || u->nkey > MAXKEY) {
            Py_DECREF(nt);
            PyErr_Format(PyExc_TypeError,
                "Indices are limited to %d attributes.", MAXKEY);
            return NULL;
        }
        for (int k = 0; k < u->nkey; k++) {
            u->key[k] = (int)PyLong_AsLong(PyTuple_GetItem(key, k));
            if (u->key[k] < 0 || u->key[k] >= nt->nattr) {
                Py_DECREF(nt);
                if (!PyErr_Occurred())
                    PyErr_SetString(PyExc_ValueError, "bad key position");
                return NULL;
            }
        }
        if (u->sort >= nt->nattr
                || (u->sort >= 0 && nt->attrs[u->sort].kind != K_INT)) {
            Py_DECREF(nt);
            PyErr_SetString(PyExc_TypeError,
                "sortkey must be an int attribute of the node type.");
            return NULL;
        }
        u->index = Py_NewRef(index);
        u->sortfn = sortfn == Py_None ? NULL : Py_NewRef(sortfn);
    }
    for (int i = 0; i < nt->ncheck; i++) {
        CheckItem *c = &nt->checks[i];
        if (!PyArg_ParseTuple(PyList_GetItem(checks, i), "ii", &c->kind,
                &c->i)) {
            Py_DECREF(nt);
            return NULL;
        }
        int limit = c->kind == CHK_UNIQUE ? nt->nuse : nt->nattr;
        if (c->i < 0 || c->i >= limit) {
            Py_DECREF(nt);
            PyErr_SetString(PyExc_ValueError, "bad check item");
            return NULL;
        }
    }
    return (PyObject *)nt;
}

static PyObject *
ntype_set_cursors(NType *nt, PyObject *args)
{
    PyObject *mut, *frz;
    if (!PyArg_ParseTuple(args, "OO", &mut, &frz))
        return NULL;
    PyObject *old_mut = nt->cur_mut, *old_frz = nt->cur_frz;
    nt->cur_mut = Py_NewRef(mut);
    nt->cur_frz = Py_NewRef(frz);
    Py_XDECREF(old_mut);
    Py_XDECREF(old_frz);
    Py_RETURN_NONE;
}

static PyObject *ntype_set(NType *nt, PyObject *args);

static PyMethodDef ntype_methods[] = {
    {"set_cursors", (PyCFunction)ntype_set_cursors, METH_VARARGS, NULL},
    {"set", (PyCFunction)ntype_set, METH_VARARGS,
        "set(node, values): copy of the NodeTuple node with the attributes"
        " in the dict values replaced (factories applied)."},
    {NULL}
};

// The NType of a NodeTuple class (borrowed from the class attribute
// _ntype), or NULL with TypeError. An _ntype inherited from another
// NodeTuple class does not count.
NType *
ntype_of_cls(PyObject *cls)
{
    PyObject *nt = NULL;
    if (PyType_Check(cls)) {
        nt = PyObject_GetAttr(cls, str_ntype);
        if (!nt) {
            if (!PyErr_ExceptionMatches(PyExc_AttributeError))
                return NULL;
            PyErr_Clear();
        }
    }
    int ok = nt && Py_TYPE(nt) == NType_Type
        && ((NType *)nt)->tuple_cls == cls;
    Py_XDECREF(nt);
    if (!ok) {
        PyErr_SetString(PyExc_TypeError, "node must be instance of NodeTuple.");
        return NULL;
    }
    return (NType *)nt;
}

// -- NodeTuple construction -------------------------------------------------

// Applies the factory of an attribute to a value (NULL: not given).
static PyObject *
apply_factory(const AttrInfo *ai, PyObject *v)
{
    if (ai->fmode == F_PY)
        return PyObject_CallMethodObjArgs(ai->attr, str_factory,
            v ? v : Py_None, NULL);
    if (ai->fmode == F_REF) {
        if (!v || v == Py_None)
            Py_RETURN_NONE;
        if (PyObject_TypeCheck(v, Node_Type) && ((NodeObj *)v)->nid >= 0)
            return PyLong_FromLongLong(((NodeObj *)v)->nid);
        if (PyLong_Check(v))
            return Py_NewRef(v);
        PyErr_SetString(PyExc_TypeError, ai->ref_kind == REF_LOCAL
            ? "Only int or Node (or None if optional) can be assigned to LocalRef."
            : "Only None, int or Node can be assigned to ExternalRef.");
        return NULL;
    }
    if (!v || v == Py_None)
        v = ai->fdefault;
    if (PyObject_TypeCheck(v, Node_Type)) {
        PyErr_SetString(PyExc_TypeError, "Nodes can only be added to LocalRef,"
            " ExternalRef or SubgraphRef attributes.");
        return NULL;
    }
    if (v == Py_None)
        Py_RETURN_NONE;
    int ok = PyObject_IsInstance(v, ai->ftype);
    if (ok < 0)
        return NULL;
    if (!ok) {
        PyObject *n = PyType_GetName(Py_TYPE(v));
        PyErr_Format(PyExc_TypeError, "Incorrect type %S for attribute.", n);
        Py_XDECREF(n);
        return NULL;
    }
    return Py_NewRef(v);
}

static int
check_hashable(PyObject *v)
{
    if (v == Py_None || PyLong_CheckExact(v) || PyUnicode_CheckExact(v))
        return 0;
    if (PyObject_Hash(v) == -1 && PyErr_Occurred()) {
        PyErr_Clear();
        PyErr_SetString(PyExc_TypeError,
            "All attributes of NodeTuple must be hashable.");
        return -1;
    }
    return 0;
}

// NodeTuple from the dict values (attribute name -> value); attributes
// not in values are taken from base, or get their factory default.
static PyObject *
ntuple_build(NType *nt, PyObject *base, PyObject *values)
{
    PyTypeObject *tc = (PyTypeObject *)nt->tuple_cls;
    PyObject *t = tuple_start(tc, nt->nattr);
    if (!t)
        return NULL;
    Py_ssize_t used = 0;
    for (int i = 0; i < nt->nattr; i++) {
        const AttrInfo *ai = &nt->attrs[i];
        PyObject *v = values ? PyDict_GetItemWithError(values, ai->name) : NULL;
        PyObject *item;
        if (v)
            used++;
        else if (PyErr_Occurred())
            goto fail;
        if (!v && base) {
            item = Py_NewRef(PyTuple_GetItem(base, i));
        } else {
            item = apply_factory(ai, v);
            if (!item)
                goto fail;
            if (check_hashable(item) < 0) {
                Py_DECREF(item);
                goto fail;
            }
        }
        PyTuple_SetItem(t, i, item);
    }
    if (values && used != PyDict_Size(values)) {
        PyObject *unknown = PyList_New(0), *key, *val, *sep, *joined;
        Py_ssize_t pos = 0;
        while (unknown && PyDict_Next(values, &pos, &key, &val)) {
            int known = 0;
            for (int i = 0; i < nt->nattr && !known; i++)
                known = PyObject_RichCompareBool(key, nt->attrs[i].name,
                    Py_EQ) == 1;
            if (!known && PyList_Append(unknown, key) < 0)
                Py_CLEAR(unknown);
        }
        if (unknown && (sep = PyUnicode_FromString(", "))) {
            joined = PyUnicode_Join(sep, unknown);
            Py_DECREF(sep);
            if (joined) {
                PyErr_Format(PyExc_AttributeError,
                    "Unknown attributes provided: %U", joined);
                Py_DECREF(joined);
            }
        }
        Py_XDECREF(unknown);
        goto fail;
    }
    return tuple_finish(tc, t);
fail:
    Py_DECREF(t);
    return NULL;
}

// NodeTuple.__new__(cls, **values)
PyObject *
mod_ntuple_new(PyObject *m, PyObject *args, PyObject *kwds)
{
    if (PyTuple_Size(args) != 1) {
        PyErr_SetString(PyExc_TypeError,
            "NodeTuple takes keyword arguments only.");
        return NULL;
    }
    NType *nt = ntype_of_cls(PyTuple_GetItem(args, 0));
    if (!nt)
        return NULL;
    return ntuple_build(nt, NULL, kwds);
}

static PyObject *
ntype_set(NType *nt, PyObject *args)
{
    PyObject *node, *values;
    if (!PyArg_ParseTuple(args, "OO!", &node, &PyDict_Type, &values))
        return NULL;
    if ((PyObject *)Py_TYPE(node) != nt->tuple_cls) {
        PyErr_SetString(PyExc_TypeError, "node of another type");
        return NULL;
    }
    return ntuple_build(nt, node, values);
}

// Copy of a NodeTuple with one attribute value replaced.
PyObject *
ntuple_replace(NType *nt, PyObject *node, int index, PyObject *value)
{
    PyObject *v = apply_factory(&nt->attrs[index], value);
    if (!v)
        return NULL;
    if (check_hashable(v) < 0) {
        Py_DECREF(v);
        return NULL;
    }
    PyTypeObject *tc = (PyTypeObject *)nt->tuple_cls;
    PyObject *t = tuple_start(tc, nt->nattr);
    if (!t) {
        Py_DECREF(v);
        return NULL;
    }
    for (int i = 0; i < nt->nattr; i++)
        PyTuple_SetItem(t, i, i == index ? v
            : Py_NewRef(PyTuple_GetItem(node, i)));
    return tuple_finish(tc, t);
}

static PyType_Slot ntype_slots[] = {
    {Py_tp_new, ntype_new},
    {Py_tp_dealloc, ntype_dealloc},
    {Py_tp_traverse, ntype_traverse},
    {Py_tp_clear, ntype_clear},
    {Py_tp_methods, ntype_methods},
    {0, NULL}
};

PyType_Spec ntype_spec = {"ordec.core.ordb._ordb.NType",
    sizeof(NType), 0, TPFLAGS | Py_TPFLAGS_HAVE_GC, ntype_slots};
