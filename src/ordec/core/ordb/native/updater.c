// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// UpdaterBase and the single-node transactions behind % and attribute
// assignment.

#include "module.h"

// ---------------------------------------------------------------------------
// Updater
// ---------------------------------------------------------------------------

// Statements (%, attribute assignment and the base.py statements through
// _statement_updater) join the open transaction of the calling thread
// instead of opening a nested one. Returns that transaction, or NULL if the
// statement needs a transaction of its own.
static Txn *
open_txn(Sg *sg)
{
    return sg->txn && sg->owner == PyThread_get_thread_ident() ? sg->txn
        : NULL;
}

// A statement that failed after it had started writing cannot be undone on
// its own: its transaction refuses further statements and aborts at exit.
static int
txn_usable(Txn *tx)
{
    if (tx->failed) {
        PyErr_SetString(OrdbException, "SubgraphUpdater cannot be used after"
            " a statement failed in it; it is rolled back at exit.");
        return -1;
    }
    return 0;
}

static void
op_failed(Txn *tx, uint64_t writes)
{
    if (tx->writes != writes)
        tx->failed = 1;
}

static PyObject *
upd_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    PyObject *sg;
    if (!PyArg_ParseTuple(args, "O!", Sg_Type, &sg))
        return NULL;
    Upd *u = (Upd *)PyType_GenericAlloc(type, 0);
    if (!u)
        return NULL;
    u->sg = (Sg *)Py_NewRef(sg);
    return (PyObject *)u;
}

// Whether transaction tx (with token tok) is still open. A transaction is
// freed when an enclosing updater is abandoned (see upd_dealloc), and its
// address may be reused, so tx is only dereferenced once found among the
// open transactions.
static int
txn_live(Sg *sg, Txn *tx, uint64_t tok)
{
    for (Txn *t = sg->txn; t; t = t->parent)
        if (t == tx)
            return t->tok == tok;
    return 0;
}

static int
upd_live(Upd *u)
{
    return txn_live(u->sg, u->tx, u->tok);
}

static int
upd_rolled_back(void)
{
    PyErr_SetString(OrdbException, "SubgraphUpdater was rolled back with an"
        " enclosing updater that was abandoned without __exit__.");
    return -1;
}

static int
upd_traverse(Upd *u, visitproc visit, void *arg)
{
    Py_VISIT(Py_TYPE((PyObject *)u));
    Py_VISIT(u->sg);
    return 0;
}

static void
upd_dealloc(Upd *u)
{
    PyObject_GC_UnTrack(u);
    if (u->tx && u->sg && !u->joined && upd_live(u)) {
        // Abandoned without __exit__: its transaction is aborted with all
        // transactions opened inside it, at the end of the write operation
        // in progress or right away. The owner thread stays unchanged.
        u->tx->abandoned = 1;
        u->sg->abandoned = 1;
        if (!u->sg->writing) {
            u->sg->writing = 1;
            sg_write_end(u->sg);
        }
    }
    Py_XDECREF((PyObject *)u->sg);
    obj_free(u);
}

static PyObject *
upd_enter(Upd *u, PyObject *noarg)
{
    if (u->tx) {
        PyErr_SetString(PyExc_TypeError, "SubgraphUpdater is already open.");
        return NULL;
    }
    if (u->sg->frozen) {
        PyErr_SetString(PyExc_TypeError,
            "Unsupported operation on FrozenSubgraph.");
        return NULL;
    }
    if (u->joined) {
        Txn *tx = open_txn(u->sg);
        if (!tx) {
            PyErr_SetString(OrdbException,
                "The updater of this statement was closed meanwhile.");
            return NULL;
        }
        if (txn_usable(tx) < 0)
            return NULL;
        u->tx = tx;
        u->tok = tx->tok;
        u->writes = tx->writes;
        u->commit = 1;
        u->valid = 1;
        return Py_NewRef((PyObject *)u);
    }
    u->tx = txn_begin(u->sg);
    if (!u->tx)
        return NULL;
    u->tok = u->tx->tok;
    u->commit = 1;
    u->valid = 1;
    return Py_NewRef((PyObject *)u);
}

// Ends the transaction of u: commit (after the checks) or abort. A
// pending exception is preserved across an abort.
static int
upd_finish(Upd *u, int commit)
{
    Txn *tx = u->tx;
    Sg *sg = u->sg;
    PyObject *et, *ev, *etb;
    PyErr_Fetch(&et, &ev, &etb);
    if (sg_write_begin(sg) < 0) {
        // Not to be closed from here: the transaction stays open.
        Py_XDECREF(et);
        Py_XDECREF(ev);
        Py_XDECREF(etb);
        return -1;
    }
    PyErr_Restore(et, ev, etb);
    u->tx = NULL;
    u->valid = 0;
    if (commit && txn_check(sg, tx, (PyObject *)u) == 0) {
        int r = txn_commit(sg, tx);
        sg_write_end(sg);
        return r;
    }
    PyErr_Fetch(&et, &ev, &etb);
    txn_abort(sg, tx);
    PyErr_Restore(et, ev, etb);
    sg_write_end(sg);
    return commit ? -1 : 0;
}

static PyObject *
upd_exit(Upd *u, PyObject *args)
{
    PyObject *exc_type = Py_None, *exc = Py_None, *tb = Py_None;
    if (!PyArg_ParseTuple(args, "|OOO", &exc_type, &exc, &tb))
        return NULL;
    Txn *tx = u->tx;
    if (!tx) {
        PyErr_SetString(PyExc_TypeError, "Invalid SubgraphUpdater.");
        return NULL;
    }
    if (!upd_live(u)) {
        upd_rolled_back();
        return NULL;
    }
    Sg *sg = u->sg;
    if (sg->txn != tx) {
        PyErr_SetString(OrdbException,
            "SubgraphUpdaters must be closed in reverse order of opening.");
        return NULL;
    }
    if (u->joined) {
        // The statement ends; the transaction it joined stays open.
        if (exc_type != Py_None)
            op_failed(tx, u->writes);
        u->tx = NULL;
        u->valid = 0;
        Py_RETURN_FALSE;
    }
    int failed = tx->failed;
    if (upd_finish(u, exc_type == Py_None && u->commit && !failed) < 0)
        return NULL;
    if (failed && exc_type == Py_None) {
        PyErr_SetString(OrdbException, "SubgraphUpdater rolled back: a"
            " statement failed in it after it had started writing.");
        return NULL;
    }
    Py_RETURN_FALSE;
}

static int
upd_usable(Upd *u)
{
    if (!u->valid || !u->tx) {
        PyErr_SetString(PyExc_TypeError, "Invalid SubgraphUpdater.");
        return -1;
    }
    if (!upd_live(u))
        return upd_rolled_back();
    if (u->sg->txn != u->tx) {
        PyErr_SetString(OrdbException,
            "SubgraphUpdater is not the innermost open updater.");
        return -1;
    }
    if (u->sg->owner != PyThread_get_thread_ident()) {
        PyErr_SetString(OrdbException,
            "SubgraphUpdater is used by another thread than the one that"
            " opened it.");
        return -1;
    }
    return txn_usable(u->tx);
}

static PyObject *
upd_nid_generate(Upd *u, PyObject *noarg)
{
    if (upd_usable(u) < 0)
        return NULL;
    Txn *tx = u->tx;
    if (tx->nid_gen < u->sg->st.nid_start || tx->nid_gen >= u->sg->st.nid_stop) {
        PyErr_SetString(OrdbException, "nid allocation exhausted.");
        return NULL;
    }
    return PyLong_FromLongLong(tx->nid_gen++);
}

static PyObject *
upd_add_single(Upd *u, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"node", "nid", "check_nid", NULL};
    PyObject *node;
    long long nid;
    int check_nid = 0;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "OL|p", kwlist, &node, &nid,
            &check_nid))
        return NULL;
    if (upd_usable(u) < 0)
        return NULL;
    const State *st = &u->sg->st;
    if (check_nid && (nid < st->nid_start || nid >= st->nid_stop)) {
        PyErr_Format(OrdbException,
            "selected nid %lld is outside allocated range(%lld, %lld).",
            nid, (long long)st->nid_start, (long long)st->nid_stop);
        return NULL;
    }
    if (sg_write_begin(u->sg) < 0)
        return NULL;
    uint64_t writes = u->tx->writes;
    int r = op_add(u->sg, nid, node);
    if (r < 0)
        op_failed(u->tx, writes);
    sg_write_end(u->sg);
    if (r < 0)
        return NULL;
    return PyLong_FromLongLong(nid);
}

static PyObject *
upd_remove_nid(Upd *u, PyObject *arg)
{
    long long nid = PyLong_AsLongLong(arg);
    if (nid == -1 && PyErr_Occurred())
        return NULL;
    // Checked after anything that can run Python code (here __index__).
    if (upd_usable(u) < 0 || sg_write_begin(u->sg) < 0)
        return NULL;
    uint64_t writes = u->tx->writes;
    int r = op_remove(u->sg, nid);
    if (r < 0)
        op_failed(u->tx, writes);
    sg_write_end(u->sg);
    if (r < 0)
        return NULL;
    Py_RETURN_NONE;
}

static PyObject *
upd_update(Upd *u, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"node", "nid", NULL};
    PyObject *node;
    long long nid;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "OL", kwlist, &node, &nid))
        return NULL;
    if (upd_usable(u) < 0)
        return NULL;
    if (sg_write_begin(u->sg) < 0)
        return NULL;
    uint64_t writes = u->tx->writes;
    int r = op_update(u->sg, nid, node);
    if (r < 0)
        op_failed(u->tx, writes);
    sg_write_end(u->sg);
    if (r < 0)
        return NULL;
    Py_RETURN_NONE;
}

// _insert_rows(X.Tuple, nids, cols): nids and each column are buffers of
// int64 (columns: n * width values, in attribute order).
static PyObject *
upd_insert_rows(Upd *u, PyObject *args)
{
    PyObject *cls, *nids_o, *cols_o;
    if (!PyArg_ParseTuple(args, "OOO!", &cls, &nids_o, &PyList_Type, &cols_o))
        return NULL;
    NType *nt = ntype_of_cls(cls);
    if (!nt)
        return NULL;
    if (PyList_Size(cols_o) != nt->nattr || nt->nattr > 63) {
        PyErr_SetString(PyExc_ValueError, "one column per attribute expected");
        return NULL;
    }
    Py_buffer nb, cb[64];
    const int64_t *cols[64];
    int ncb = 0;
    PyObject *ret = NULL;
    if (PyObject_GetBuffer(nids_o, &nb, PyBUF_SIMPLE) < 0)
        return NULL;
    Py_ssize_t n = nb.len / 8;
    for (int i = 0; i < nt->nattr; i++) {
        const AttrInfo *ai = &nt->attrs[i];
        if (ai->kind == K_OBJ) {
            PyErr_SetString(PyExc_TypeError,
                "node type has attributes that are not array-representable.");
            goto done;
        }
        if (PyObject_GetBuffer(PyList_GetItem(cols_o, i), &cb[ncb],
                PyBUF_SIMPLE) < 0)
            goto done;
        ncb++;
        if (cb[i].len != n * 8 * ai->width) {
            PyErr_SetString(PyExc_ValueError, "column length mismatch");
            goto done;
        }
        cols[i] = cb[i].buf;
    }
    // Checked after the buffers are acquired, which can run Python code.
    if (upd_usable(u) < 0 || sg_write_begin(u->sg) < 0)
        goto done;
    uint64_t writes = u->tx->writes;
    if (op_insert_rows(u->sg, nt, nb.buf, n, cols) == 0)
        ret = Py_NewRef(Py_None);
    else
        op_failed(u->tx, writes);
    sg_write_end(u->sg);
done:
    for (int i = 0; i < ncb; i++)
        PyBuffer_Release(&cb[i]);
    PyBuffer_Release(&nb);
    return ret;
}

static PyObject *
upd_get_nid_gen(Upd *u, void *closure)
{
    if (!u->tx) {
        PyErr_SetString(PyExc_TypeError, "Invalid SubgraphUpdater.");
        return NULL;
    }
    if (!upd_live(u)) {
        upd_rolled_back();
        return NULL;
    }
    return PyLong_FromLongLong(u->tx->nid_gen);
}

static PyObject *
upd_get_nid_max(Upd *u, void *closure)
{
    if (!u->tx) {
        PyErr_SetString(PyExc_TypeError, "Invalid SubgraphUpdater.");
        return NULL;
    }
    if (!upd_live(u)) {
        upd_rolled_back();
        return NULL;
    }
    return PyLong_FromLongLong(u->tx->nid_max);
}

static PyMethodDef upd_methods[] = {
    {"__enter__", (PyCFunction)upd_enter, METH_NOARGS, NULL},
    {"__exit__", (PyCFunction)upd_exit, METH_VARARGS, NULL},
    {"nid_generate", (PyCFunction)upd_nid_generate, METH_NOARGS, NULL},
    {"add_single", (PyCFunction)(void (*)(void))upd_add_single, METH_VARARGS | METH_KEYWORDS,
        NULL},
    {"remove_nid", (PyCFunction)upd_remove_nid, METH_O, NULL},
    {"update", (PyCFunction)(void (*)(void))upd_update, METH_VARARGS | METH_KEYWORDS,
        "update(node, nid): replaces node nid by node of the same type."},
    {"_insert_rows", (PyCFunction)upd_insert_rows, METH_VARARGS, NULL},
    {NULL}
};

static PyMemberDef upd_members[] = {
    {"target_subgraph", T_OBJECT, offsetof(Upd, sg), READONLY, NULL},
    {"commit", T_BOOL, offsetof(Upd, commit), 0, NULL},
    {"valid", T_BOOL, offsetof(Upd, valid), READONLY, NULL},
    {NULL}
};

static PyGetSetDef upd_getset[] = {
    {"nid_gen_counter", (getter)upd_get_nid_gen, NULL, NULL},
    {"nid_max_encountered", (getter)upd_get_nid_max, NULL, NULL},
    {NULL}
};

// -- statements ---------------------------------------------------------------

static Upd *
upd_alloc(Sg *sg)
{
    PyTypeObject *t = g_updater_cls ? (PyTypeObject *)g_updater_cls : Upd_Type;
    Upd *u = (Upd *)PyType_GenericAlloc(t, 0);
    if (u)
        u->sg = (Sg *)Py_NewRef((PyObject *)sg);
    return u;
}

// _statement_updater(): the updater for one statement in base.py: a handle
// on the open transaction of the calling thread (its exit neither commits
// nor aborts) or, without one, a new updater.
PyObject *
sg_statement_updater(Sg *sg, PyObject *noarg)
{
    Upd *u = upd_alloc(sg);
    if (u)
        u->joined = open_txn(sg) != NULL;
    return (PyObject *)u;
}

// A transaction of its own for a statement outside of any updater.
static Upd *
upd_open(Sg *sg)
{
    Upd *u = upd_alloc(sg);
    if (!u)
        return NULL;
    PyObject *r = upd_enter(u, NULL);
    if (!r) {
        Py_DECREF(u);
        return NULL;
    }
    Py_DECREF(r);
    return u;
}

// Commits (ok) or aborts the transaction of u and releases u.
static int
upd_close(Upd *u, int ok)
{
    int r = upd_finish(u, ok);
    Py_DECREF(u);
    return ok ? r : -1;
}

// _add1(node[, ref]): inserts the NodeTuple node (with its attribute
// 'ref' set to ref, if given), in the open transaction or in one of its
// own. Returns the cursor of the new node. Backs '%' and Subgraph.add.
PyObject *
sg_add1(Sg *sg, PyObject *args)
{
    PyObject *node, *ref = NULL;
    if (!PyArg_ParseTuple(args, "O|O", &node, &ref))
        return NULL;
    NType *nt = ntype_of_cls((PyObject *)Py_TYPE(node));
    if (!nt)
        return NULL;
    Py_INCREF(node);
    if (ref) {
        if (nt->ref_attr < 0) {
            PyErr_SetString(PyExc_AttributeError,
                "Unknown attributes provided: ref");
            Py_DECREF(node);
            return NULL;
        }
        PyObject *n = ntuple_replace(nt, node, nt->ref_attr, ref);
        Py_DECREF(node);
        if (!n)
            return NULL;
        node = n;
    }
    Txn *tx = open_txn(sg);
    if (tx) {
        int64_t nid = tx->nid_gen;
        int r = txn_usable(tx);
        if (r == 0 && (nid < sg->st.nid_start || nid >= sg->st.nid_stop)) {
            PyErr_SetString(OrdbException, "nid allocation exhausted.");
            r = -1;
        }
        if (r == 0 && (r = sg_write_begin(sg)) == 0) {
            uint64_t writes = tx->writes, tok = tx->tok;
            tx->nid_gen++;
            r = op_add(sg, nid, node);
            if (r < 0)
                op_failed(tx, writes);
            sg_write_end(sg);
            if (r == 0 && !txn_live(sg, tx, tok))
                r = upd_rolled_back();
        }
        Py_DECREF(node);
        return r < 0 ? NULL : sg_cursor(sg, nid, NPATH_NONE);
    }
    Upd *u = upd_open(sg);
    if (!u) {
        Py_DECREF(node);
        return NULL;
    }
    tx = u->tx;
    int64_t nid = tx->nid_gen++;
    int ok = 1;
    if (nid < sg->st.nid_start || nid >= sg->st.nid_stop) {
        PyErr_SetString(OrdbException, "nid allocation exhausted.");
        ok = 0;
    } else if (sg_write_begin(sg) == 0) {
        ok = op_add(sg, nid, node) == 0;
        sg_write_end(sg);
    } else {
        ok = 0;
    }
    Py_DECREF(node);
    if (upd_close(u, ok) < 0)
        return NULL;
    return sg_cursor(sg, nid, NPATH_NONE);
}

// Sets attribute index (of node type nt) of node nid, in the open
// transaction or in one of its own. Backs attribute assignment on cursors.
int
sg_set1(Sg *sg, int64_t nid, NType *nt, int index, PyObject *value)
{
    int ti;
    const slot_t *p = st_row(&sg->st, nid, &ti);
    if (!p) {
        key_error_nid(nid);
        return -1;
    }
    if (sg->st.tabs[ti].nt != nt) {
        PyErr_Format(OrdbException,
            "Node nid=%lld was replaced by a node of another type.",
            (long long)nid);
        return -1;
    }
    PyObject *row = row_load(&sg->st, nt, p, nid);
    if (!row)
        return -1;
    PyObject *n = ntuple_replace(nt, row, index, value);
    Py_DECREF(row);
    if (!n)
        return -1;
    row = n;
    Txn *tx = open_txn(sg);
    if (tx) {
        int r = -1;
        if (txn_usable(tx) == 0 && sg_write_begin(sg) == 0) {
            uint64_t writes = tx->writes, tok = tx->tok;
            r = op_update(sg, nid, row);
            if (r < 0)
                op_failed(tx, writes);
            sg_write_end(sg);
            if (r == 0 && !txn_live(sg, tx, tok))
                r = upd_rolled_back();
        }
        Py_DECREF(row);
        return r;
    }
    Upd *u = upd_open(sg);
    if (!u) {
        Py_DECREF(row);
        return -1;
    }
    int ok = sg_write_begin(sg) == 0;
    if (ok) {
        ok = op_update(sg, nid, row) == 0;
        sg_write_end(sg);
    }
    Py_DECREF(row);
    return upd_close(u, ok);
}

static PyType_Slot upd_slots[] = {
    {Py_tp_new, upd_new},
    {Py_tp_dealloc, upd_dealloc},
    {Py_tp_traverse, upd_traverse},
    {Py_tp_methods, upd_methods},
    {Py_tp_members, upd_members},
    {Py_tp_getset, upd_getset},
    {0, NULL}
};

PyType_Spec upd_spec = {"ordec.core.ordb._ordb.UpdaterBase",
    sizeof(Upd), 0, TPFLAGS | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC,
    upd_slots};
