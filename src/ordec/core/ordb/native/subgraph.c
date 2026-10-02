// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// SubgraphBase: reads, snapshots, content hash and equality, arrays.

#include "module.h"

// ---------------------------------------------------------------------------
// Subgraph
// ---------------------------------------------------------------------------

static PyObject *
sg_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"engine", NULL};
    int engine = ENGINE_KEYED;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|i", kwlist, &engine))
        return NULL;
    if (engine != ENGINE_KEYED) {
        PyErr_Format(PyExc_ValueError, "Unknown storage engine %d.", engine);
        return NULL;
    }
    Sg *sg = (Sg *)PyType_GenericAlloc(type, 0);
    if (!sg)
        return NULL;
    state_init(&sg->st);
    sg->wire_hash = Py_NewRef(Py_None);
    sg->arrays_memo = Py_NewRef(Py_None);
    return (PyObject *)sg;
}

static int
sg_traverse(Sg *sg, visitproc visit, void *arg)
{
    State *st = &sg->st;
    Py_VISIT(Py_TYPE((PyObject *)sg));
    Py_VISIT(st->dir.root);
    for (int i = 0; i < st->ntab; i++) {
        Py_VISIT(st->tabs[i].rows.root);
        Py_VISIT(st->tabs[i].nt);
    }
    for (int i = 0; i < st->nidx; i++) {
        Py_VISIT(st->idxs[i].index);
        Py_VISIT(st->idxs[i].tree.root);
    }
    Py_VISIT(st->boxed);
    Py_VISIT(sg->root_cursor);
    Py_VISIT(sg->wire_hash);
    Py_VISIT(sg->arrays_memo);
    return 0;
}

static int
sg_clear(Sg *sg)
{
    Py_CLEAR(sg->root_cursor);
    Py_CLEAR(sg->wire_hash);
    Py_CLEAR(sg->arrays_memo);
    if (!sg->txn)
        state_release(&sg->st);
    return 0;
}

static void
sg_dealloc(Sg *sg)
{
    PyObject_GC_UnTrack(sg);
    if (sg->weakreflist)
        PyObject_ClearWeakRefs((PyObject *)sg);
    Py_CLEAR(sg->root_cursor);
    Py_CLEAR(sg->wire_hash);
    Py_CLEAR(sg->arrays_memo);
    state_release(&sg->st);
    obj_free(sg);
}

// The nid of an integer o (int or with __index__, e.g. numpy ints from
// arrays()): 1 if o is an integer, 0 if not, -1 on error. Out of range
// gives nid -1 (no such node).
static int
index_nid(PyObject *o, int64_t *nid)
{
    int ovf;
    long long x;
    if (PyLong_Check(o)) {
        x = PyLong_AsLongLongAndOverflow(o, &ovf);
    } else {
        if (!PyIndex_Check(o))
            return 0;
        PyObject *i = PyNumber_Index(o);
        if (!i)
            return -1;
        x = PyLong_AsLongLongAndOverflow(i, &ovf);
        Py_DECREF(i);
    }
    if (x == -1 && PyErr_Occurred())
        return -1;
    *nid = ovf ? -1 : x;
    return 1;
}

static int
arg_nid(PyObject *o, int64_t *nid)
{
    int r = index_nid(o, nid);
    if (r == 0)
        PyErr_SetString(PyExc_TypeError, "nid must be int");
    return r == 1 ? 0 : -1;
}

static PyObject *
sg_row(Sg *sg, PyObject *arg)
{
    int64_t nid;
    int ti;
    if (arg_nid(arg, &nid) < 0)
        return NULL;
    const slot_t *p = st_row(&sg->st, nid, &ti);
    if (!p) {
        PyErr_SetObject(PyExc_KeyError, arg);
        return NULL;
    }
    return row_load(&sg->st, sg->st.tabs[ti].nt, p, nid);
}

static PyObject *
sg_ntuple(Sg *sg, PyObject *arg)
{
    int64_t nid;
    int ti;
    if (arg_nid(arg, &nid) < 0)
        return NULL;
    if (!st_row(&sg->st, nid, &ti)) {
        PyErr_SetObject(PyExc_KeyError, arg);
        return NULL;
    }
    return Py_NewRef(sg->st.tabs[ti].nt->tuple_cls);
}

static PyObject *
sg_has(Sg *sg, PyObject *arg)
{
    int ti;
    int64_t nid;
    int r = index_nid(arg, &nid);
    if (r < 0)
        return NULL;
    return PyBool_FromLong(r && st_row(&sg->st, nid, &ti) != NULL);
}

static PyObject *
sg_count(Sg *sg, PyObject *noarg)
{
    return PyLong_FromUnsignedLongLong(sg->st.nlive);
}

static PyObject *
sg_ntuples(Sg *sg, PyObject *noarg)
{
    PyObject *l = PyList_New(0);
    if (!l)
        return NULL;
    for (int i = 0; i < sg->st.ntab; i++) {
        if (sg->st.tabs[i].live
                && PyList_Append(l, sg->st.tabs[i].nt->tuple_cls) < 0) {
            Py_DECREF(l);
            return NULL;
        }
    }
    return l;
}

// List of the n nids (copied out of storage before creating objects, which
// can run Python code); frees nids.
static PyObject *
nid_list(int64_t *nids, uint64_t n)
{
    PyObject *l = PyList_New((Py_ssize_t)n);
    for (uint64_t k = 0; l && k < n; k++) {
        PyObject *x = PyLong_FromLongLong(nids[k]);
        if (!x) {
            Py_CLEAR(l);
            break;
        }
        PyList_SetItem(l, k, x);
    }
    PyMem_Free(nids);
    return l;
}

// nids(): all nids; nids(X.Tuple): the nids of one node type. Ascending.
static PyObject *
sg_nids(Sg *sg, PyObject *args)
{
    PyObject *cls = Py_None;
    if (!PyArg_ParseTuple(args, "|O", &cls))
        return NULL;
    const State *st = &sg->st;
    if (cls == Py_None) {
        int64_t *nids = PyMem_Malloc(sizeof(int64_t) * (st->nlive + 1));
        if (!nids)
            return PyErr_NoMemory();
        uint64_t n = 0;
        int64_t nid = -1;
        for (const slot_t *d; (d = kmap_next(&st->dir, nid, &nid));)
            if (d[0] > 0)
                nids[n++] = nid;
        return nid_list(nids, n);
    }
    NType *nt = ntype_of_cls(cls);
    if (!nt)
        return NULL;
    int ti = st_find_tab(st, nt);
    if (ti < 0)
        return PyList_New(0);
    uint64_t n;
    const slot_t **rows = tab_rows_sorted(st, ti, &n);
    if (!rows)
        return NULL;
    int64_t *nids = PyMem_Malloc(sizeof(int64_t) * (n + 1));
    if (nids)
        for (uint64_t k = 0; k < n; k++)
            nids[k] = rows[k][0];
    PyMem_Free(rows);
    if (!nids)
        return PyErr_NoMemory();
    return nid_list(nids, n);
}

static PyObject *
sg_query(Sg *sg, PyObject *args)
{
    PyObject *index, *key;
    if (!PyArg_ParseTuple(args, "OO", &index, &key))
        return NULL;
    return st_query(&sg->st, index, key);
}

static PyObject *
sg_cursor_at(Sg *sg, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"nid", "npath_nid", "lookup_npath", NULL};
    PyObject *nid_o, *npath_o = Py_None;
    int lookup = 1;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "O|Op", kwlist, &nid_o,
            &npath_o, &lookup))
        return NULL;
    int64_t nid, npath;
    if (opt_nid(nid_o, -1, &nid) < 0
            || opt_nid(npath_o, lookup ? NPATH_UNRESOLVED : NPATH_NONE,
                &npath) < 0)
        return NULL;
    if (nid < 0) {
        // NPath without node
        if (npath < 0) {
            PyErr_SetString(PyExc_ValueError,
                "cursor_at(None) needs an npath_nid.");
            return NULL;
        }
        return node_make(sg->frozen ? g_pathnode_frz : g_pathnode_mut, sg,
            -1, npath);
    }
    return sg_cursor(sg, nid, npath);
}

static PyObject *
sg_get_root_cursor(Sg *sg, void *closure)
{
    if (!sg->root_cursor) {
        int ti;
        if (!st_row(&sg->st, 0, &ti))
            Py_RETURN_NONE;
        PyObject *c = sg_cursor(sg, 0, NPATH_NONE);
        if (!c)
            return NULL;
        // Allocating the cursor can run Python code, which may have filled
        // the cache meanwhile.
        if (sg->root_cursor)
            Py_DECREF(c);
        else
            sg->root_cursor = c;
    }
    return Py_NewRef(sg->root_cursor);
}

static PyObject *
sg_get_nid_alloc(Sg *sg, void *closure)
{
    return PyObject_CallFunction((PyObject *)&PyRange_Type, "LL",
        (long long)sg->st.nid_start, (long long)sg->st.nid_stop);
}

static PyObject *
sg_get_engine(Sg *sg, void *closure)
{
    return PyUnicode_FromString("keyed");
}

static PyObject *
sg_get_in_transaction(Sg *sg, void *closure)
{
    return PyBool_FromLong(sg->txn != NULL);
}

static int
sg_no_txn(Sg *sg, const char *what)
{
    if (sg->txn) {
        PyErr_Format(OrdbException,
            "Cannot %s a subgraph while an updater is open.", what);
        return -1;
    }
    return 0;
}

// _snapshot(cls, frozen): new subgraph of class cls sharing this state.
static PyObject *
sg_snapshot(Sg *sg, PyObject *args)
{
    PyObject *cls;
    int frozen;
    if (!PyArg_ParseTuple(args, "O!p", &PyType_Type, &cls, &frozen))
        return NULL;
    if (!PyType_IsSubtype((PyTypeObject *)cls, Sg_Type)) {
        PyErr_SetString(PyExc_TypeError, "cls must be a subgraph class");
        return NULL;
    }
    if (sg_no_txn(sg, frozen ? "freeze" : "copy") < 0)
        return NULL;
    Sg *n = (Sg *)PyType_GenericAlloc((PyTypeObject *)cls, 0);
    if (!n)
        return NULL;
    state_init(&n->st);
    n->wire_hash = Py_NewRef(Py_None);
    n->arrays_memo = Py_NewRef(Py_None);
    if (state_copy(&n->st, &sg->st) < 0) {
        state_init(&n->st);
        Py_DECREF(n);
        return NULL;
    }
    n->frozen = (char)frozen;
    return (PyObject *)n;
}

static PyObject *
sg_set_nid_start(Sg *sg, PyObject *arg)
{
    long long v = PyLong_AsLongLong(arg);
    if (v == -1 && PyErr_Occurred())
        return NULL;
    if (sg->frozen) {
        PyErr_SetString(PyExc_TypeError,
            "Unsupported operation on FrozenSubgraph.");
        return NULL;
    }
    if (sg_no_txn(sg, "change nid_alloc of") < 0)
        return NULL;
    sg->st.nid_start = v;
    sg->hash_valid = 0;
    Py_RETURN_NONE;
}

// Hash of a record whose hashing runs no Python code: no object slots
// and no boxed values.
static uint64_t
plain_row_hash(const NType *nt, const slot_t *p)
{
    uint64_t h = mix((uint64_t)(uintptr_t)nt->tuple_cls, (uint64_t)p[0]);
    for (int i = 0; i < nt->nattr; i++) {
        const AttrInfo *ai = &nt->attrs[i];
        const slot_t *s = p + ai->slot;
        h = mix(h, s[0] == SLOT_NONE ? H_NONE
            : ai->kind == K_INT ? int_hash(s[0]) : mix_ints(ai->width, s));
    }
    return h;
}

typedef struct {
    const NType *nt;
    uint64_t acc;
} PlainHash;

static int
plain_hash_add(const slot_t *p, void *arg)
{
    PlainHash *ph = arg;
    ph->acc += plain_row_hash(ph->nt, p);
    return 0;
}

// The hash of a stored row (may run Python code for object slots and
// boxed values).
static int
row_hash(const State *st, const NType *nt, const slot_t *p, uint64_t *out)
{
    if (!nt->objmask && !st->boxed) {
        *out = plain_row_hash(nt, p);
        return 0;
    }
    Rec rec;
    if (rec_take(&rec, st, nt, p, p[0]) < 0)
        return -1;
    uint64_t h = mix((uint64_t)(uintptr_t)nt->tuple_cls, (uint64_t)p[0]);
    int ok = 0;
    for (int i = 0; i < nt->nattr && ok >= 0; i++) {
        uint64_t hc = H_NONE;
        ok = rec_slot_hash(&rec, i, &hc);
        h = mix(h, hc);
    }
    rec_drop(&rec);
    *out = h;
    return ok < 0 ? -1 : 0;
}

// The sum of the row hashes below the table node n, cached on the node.
// Only for frozen subgraphs: their nodes are never written in place, so a
// stored sum stays valid, also while hashing values runs Python code.
static int
node_hsum(const State *st, const NType *nt, PyObject *n, int level,
    uint64_t *out)
{
    if (level == 0) {
        Leaf *lf = (Leaf *)n;
        if (!lf->hvalid) {
            uint64_t acc = 0, h;
            for (uint32_t k = 0; k < popcount32(lf->mask); k++) {
                if (row_hash(st, nt, lf->data + k * nt->rec, &h) < 0)
                    return -1;
                acc += h;
            }
            lf->hsum = acc;
            lf->hvalid = 1;
        }
        *out = lf->hsum;
        return 0;
    }
    Inner *in = (Inner *)n;
    if (!in->hvalid) {
        uint64_t acc = 0, h;
        for (uint64_t m = in->mask; m; m &= m - 1) {
            if (node_hsum(st, nt, in->kids[__builtin_ctzll(m)], level - 1,
                    &h) < 0)
                return -1;
            acc += h;
        }
        in->hsum = acc;
        in->hvalid = 1;
    }
    *out = in->hsum;
    return 0;
}

// Content hash: order-independent sum of record hashes plus nid_alloc.
// Frozen subgraphs sum the cached sums of their table nodes, so a new
// generation only hashes the rows below the nodes it changed. Mutable ones
// look the tables up again for every row: hashing values can run Python
// code, during which another thread may write.
static PyObject *
sg_content_hash(Sg *sg, PyObject *noarg)
{
    if (sg->hash_valid)
        return PyLong_FromSsize_t(sg->hash);
    const State *st = &sg->st;
    uint64_t acc = mix((uint64_t)st->nid_start, (uint64_t)st->nid_stop);
    for (int ti = 0; ti < st->ntab; ti++) {
        const Tab *t = &st->tabs[ti];
        if (sg->frozen) {
            uint64_t h = 0;
            if (t->rows.root && node_hsum(st, t->nt, t->rows.root,
                    t->rows.levels, &h) < 0)
                return NULL;
            acc += h;
            continue;
        }
        if (!t->nt->objmask && !st->boxed) {
            // No Python code runs for these rows: one walk.
            PlainHash ph = {t->nt, 0};
            kmap_walk(&t->rows, plain_hash_add, &ph);
            acc += ph.acc;
            continue;
        }
        int64_t pos = -1;
        for (const slot_t *p; (p = tab_next(st, ti, &pos));) {
            uint64_t h;
            if (row_hash(st, st->tabs[ti].nt, p, &h) < 0)
                return NULL;
            acc += h;
        }
    }
    Py_hash_t h = (Py_hash_t)acc;
    if (h == -1)
        h = -2;
    if (sg->frozen) {
        sg->hash = h;
        sg->hash_valid = 1;
    }
    return PyLong_FromSsize_t(h);
}

// Compares two live records of the same node type.
static int
rows_equal(const State *sa, const State *sb, NType *nt, const slot_t *p,
    const slot_t *q)
{
    if (!nt->objmask && !sa->boxed && !sb->boxed)
        return memcmp(p, q, sizeof(slot_t) * nt->rec) == 0;
    Rec ra, rb;
    if (rec_take(&ra, sa, nt, p, p[0]) < 0)
        return -1;
    if (rec_take(&rb, sb, nt, q, q[0]) < 0) {
        rec_drop(&ra);
        return -1;
    }
    int eq = 1;
    for (int i = 0; i < nt->nattr && eq == 1; i++)
        eq = rec_eq(&ra, i, &rb, i);
    rec_drop(&ra);
    rec_drop(&rb);
    return eq;
}

static PyObject *
sg_content_eq(Sg *a, PyObject *arg)
{
    if (!PyObject_TypeCheck(arg, Sg_Type)) {
        PyErr_SetString(PyExc_TypeError, "Expected Subgraph.");
        return NULL;
    }
    Sg *b = (Sg *)arg;
    const State *sa = &a->st, *sb = &b->st;
    if (a == b)
        Py_RETURN_TRUE;
    if (sa->nlive != sb->nlive || sa->nid_start != sb->nid_start
            || sa->nid_stop != sb->nid_stop)
        Py_RETURN_FALSE;
    for (int ti = 0; ti < sa->ntab; ti++) {
        NType *nt = sa->tabs[ti].nt;
        int tj = st_find_tab(sb, nt);
        if (tj < 0 || sb->tabs[tj].live != sa->tabs[ti].live) {
            if (sa->tabs[ti].live == 0)
                continue;
            Py_RETURN_FALSE;
        }
        if (sa->tabs[ti].rows.root == sb->tabs[tj].rows.root
                && sa->boxed == sb->boxed)
            continue; // shared storage
        if (!nt->objmask && !sa->boxed && !sb->boxed) {
            // No Python code runs for these rows: the tables are compared
            // in parallel, skipping shared subtrees.
            if (!kmap_equal_plain(&sa->tabs[ti].rows, &sb->tabs[tj].rows))
                Py_RETURN_FALSE;
            continue;
        }
        int64_t pos = -1;
        for (const slot_t *p; (p = tab_next(sa, ti, &pos));) {
            int tk;
            const slot_t *q = st_row(sb, p[0], &tk);
            if (!q || sb->tabs[tk].nt != nt)
                Py_RETURN_FALSE;
            if (p == q)
                continue;
            int eq = rows_equal(sa, sb, nt, p, q);
            if (eq < 0)
                return NULL;
            if (!eq)
                Py_RETURN_FALSE;
        }
    }
    Py_RETURN_TRUE;
}

// int64 values of an integer attribute; 0 if not representable (None, or
// a boxed value that is not an int / tuple of ints in the int64 range).
static int
attr_ints(const State *st, const NType *nt, int i, const slot_t *p,
    int64_t nid, int64_t *out)
{
    const AttrInfo *ai = &nt->attrs[i];
    slot_t v = p[ai->slot];
    if (v == SLOT_NONE)
        return 0;
    if (v != SLOT_BOXED) {
        memcpy(out, p + ai->slot, sizeof(slot_t) * ai->width);
        return 1;
    }
    PyObject *o = boxed_get(st, nid, i);
    if (!o)
        return -1;
    int ovf;
    if (ai->kind == K_INT) {
        if (!PyLong_Check(o))
            return 0;
        out[0] = PyLong_AsLongLongAndOverflow(o, &ovf);
        return !ovf;
    }
    if (!PyTuple_Check(o) || PyTuple_Size(o) != ai->width)
        return 0;
    for (int k = 0; k < ai->width; k++) {
        PyObject *x = PyTuple_GetItem(o, k);
        if (!PyLong_Check(x))
            return 0;
        out[k] = PyLong_AsLongLongAndOverflow(x, &ovf);
        if (ovf)
            return 0;
    }
    return 1;
}

// _arrays(X.Tuple, partial) -> (nids, [column per attribute]) as bytes of
// int64. Rows with None or boxed values are skipped (partial) or raise.
static PyObject *
sg_arrays(Sg *sg, PyObject *args)
{
    PyObject *cls;
    int partial;
    if (!PyArg_ParseTuple(args, "Op", &cls, &partial))
        return NULL;
    NType *nt = ntype_of_cls(cls);
    if (!nt)
        return NULL;
    for (int i = 0; i < nt->nattr; i++) {
        if (nt->attrs[i].kind == K_OBJ) {
            PyErr_SetString(PyExc_TypeError,
                "node type has attributes that are not array-representable.");
            return NULL;
        }
    }
    const State *st = &sg->st;
    int ti = st_find_tab(st, nt);
    uint64_t n = ti >= 0 ? st->tabs[ti].live : 0;
    const slot_t **rows = NULL;
    PyObject *cols = NULL, *ret = NULL;
    int64_t *colp[64];
    PyObject *nids = PyBytes_FromStringAndSize(NULL, n * 8);
    if (!nids || !(cols = PyList_New(nt->nattr)))
        goto done;
    for (int i = 0; i < nt->nattr; i++) {
        PyObject *b = PyBytes_FromStringAndSize(NULL,
            n * 8 * nt->attrs[i].width);
        if (!b)
            goto done;
        colp[i] = (int64_t *)PyBytes_AsString(b);
        PyList_SetItem(cols, i, b);
    }
    int64_t *nidp = (int64_t *)PyBytes_AsString(nids);
    // The rows are taken after allocating (which can run Python code); no
    // Python code runs while they are read.
    uint64_t nrows = 0;
    if (n && (ti = st_find_tab(st, nt)) >= 0
            && !(rows = tab_rows_sorted(st, ti, &nrows)))
        goto done;
    if (nrows != n) {
        PyErr_SetString(OrdbException, "Subgraph changed during arrays().");
        goto done;
    }
    uint64_t m = 0;
    for (uint64_t k = 0; k < n; k++) {
        const slot_t *p = rows[k];
        int ok = 1;
        for (int i = 0; i < nt->nattr && ok == 1; i++)
            ok = attr_ints(st, nt, i, p, p[0],
                colp[i] + m * nt->attrs[i].width);
        if (ok < 0)
            goto done;
        if (!ok) {
            if (partial)
                continue;
            PyObject *name = PyType_GetName((PyTypeObject *)nt->cursor_type);
            PyErr_Format(PyExc_ValueError, "%S nid=%lld has values that are"
                " None or outside the int64 range and cannot be represented"
                " as array.", name, (long long)p[0]);
            Py_XDECREF(name);
            goto done;
        }
        nidp[m++] = p[0];
    }
    if (m != n) {
        // Rows were skipped: shorten by copying (no _PyBytes_Resize in the
        // limited API).
        PyObject *b = PyBytes_FromStringAndSize((char *)nidp, m * 8);
        Py_DECREF(nids);
        nids = b;
        if (!nids)
            goto done;
        for (int i = 0; i < nt->nattr; i++) {
            b = PyBytes_FromStringAndSize((char *)colp[i],
                m * 8 * nt->attrs[i].width);
            if (!b || PyList_SetItem(cols, i, b) < 0)
                goto done;
        }
    }
    ret = PyTuple_Pack(2, nids, cols);
done:
    PyMem_Free(rows);
    Py_XDECREF(nids);
    Py_XDECREF(cols);
    return ret;
}

// Size of the subgraph object with its private arrays. Table and index
// nodes are separate objects, reachable through gc.get_referents.
static PyObject *
sg_sizeof(Sg *sg, PyObject *noarg)
{
    const State *st = &sg->st;
    // Subclasses may be larger than Sg.
    PyObject *bs = PyObject_GetAttrString((PyObject *)Py_TYPE((PyObject *)sg),
        "__basicsize__");
    if (!bs)
        return NULL;
    double n = PyLong_AsDouble(bs) + sizeof(Tab) * st->ntab
        + sizeof(Idx) * st->nidx;
    Py_DECREF(bs);
    return PyLong_FromDouble(n);
}

// Storage statistics for tests and benchmarks.
static PyObject *
sg_stats(Sg *sg, PyObject *noarg)
{
    const State *st = &sg->st;
    uint64_t entries = 0;
    for (int i = 0; i < st->nidx; i++)
        entries += st->idxs[i].tree.count;
    return Py_BuildValue("{s:K,s:i,s:i,s:K}",
        "nodes", (unsigned long long)st->nlive,
        "tables", st->ntab, "indices", st->nidx,
        "index_entries", (unsigned long long)entries);
}

// _child(npath_nid, name): cursor of the child path name below the NPath
// npath_nid (None: top level). QueryException if there is none.
static PyObject *
sg_child(Sg *sg, PyObject *args)
{
    PyObject *parent, *name;
    if (!PyArg_ParseTuple(args, "OO", &parent, &name))
        return NULL;
    PyObject *key = PyTuple_Pack(2, parent, name);
    if (!key)
        return NULL;
    PyObject *l = st_query(&sg->st, g_npath_child_index, key);
    Py_DECREF(key);
    if (!l)
        return NULL;
    if (PyList_Size(l) != 1) {
        Py_DECREF(l);
        PyErr_Format(QueryException, "Attribute or path %R not found.", name);
        return NULL;
    }
    long long npath = PyLong_AsLongLong(PyList_GetItem(l, 0));
    Py_DECREF(l);
    int ti;
    const slot_t *p = st_row(&sg->st, npath, &ti);
    NType *nt = p ? sg->st.tabs[ti].nt : NULL;
    if (!nt || nt->ref_attr < 0) {
        PyErr_SetString(PyExc_SystemError, "ORDB: bad NPath");
        return NULL;
    }
    slot_t ref = p[nt->attrs[nt->ref_attr].slot];
    if (ref == SLOT_NONE)
        return node_make(sg->frozen ? g_pathnode_frz : g_pathnode_mut, sg,
            -1, npath);
    return sg_cursor(sg, ref, npath);
}

static PyMethodDef sg_methods[] = {
    {"row", (PyCFunction)sg_row, METH_O,
        "row(nid): the NodeTuple stored at nid. KeyError if absent."},
    {"ntuple", (PyCFunction)sg_ntuple, METH_O,
        "ntuple(nid): the NodeTuple subclass of the node at nid."},
    {"has", (PyCFunction)sg_has, METH_O, "has(nid): whether nid exists."},
    {"count", (PyCFunction)sg_count, METH_NOARGS, "Number of nodes."},
    {"ntuples", (PyCFunction)sg_ntuples, METH_NOARGS,
        "NodeTuple subclasses that have nodes in this subgraph."},
    {"nids", (PyCFunction)sg_nids, METH_VARARGS,
        "nids(ntuple=None): ascending nids of all nodes or of one type."},
    {"query", (PyCFunction)sg_query, METH_VARARGS,
        "query(index, key): nids matching key, in index order."},
    {"cursor_at", (PyCFunction)(void (*)(void))sg_cursor_at, METH_VARARGS | METH_KEYWORDS,
        NULL},
    {"_snapshot", (PyCFunction)sg_snapshot, METH_VARARGS, NULL},
    {"_add1", (PyCFunction)sg_add1, METH_VARARGS, NULL},
    {"_statement_updater", (PyCFunction)sg_statement_updater, METH_NOARGS,
        NULL},
    {"_cursors", (PyCFunction)sg_cursors, METH_O, NULL},
    {"_child", (PyCFunction)sg_child, METH_VARARGS, NULL},
    {"_set_nid_start", (PyCFunction)sg_set_nid_start, METH_O, NULL},
    {"_check_indices", (PyCFunction)sg_check_indices, METH_NOARGS, NULL},
    {"_content_hash", (PyCFunction)sg_content_hash, METH_NOARGS, NULL},
    {"_content_eq", (PyCFunction)sg_content_eq, METH_O, NULL},
    {"_arrays", (PyCFunction)sg_arrays, METH_VARARGS, NULL},
    {"_stats", (PyCFunction)sg_stats, METH_NOARGS, NULL},
    {"__sizeof__", (PyCFunction)sg_sizeof, METH_NOARGS, NULL},
    {NULL}
};

static PyGetSetDef sg_getset[] = {
    {"root_cursor", (getter)sg_get_root_cursor, NULL,
        "Root cursor pointing to subgraph root."},
    {"nid_alloc", (getter)sg_get_nid_alloc, NULL,
        "An allocation range from which new nids must be generated."},
    {"engine", (getter)sg_get_engine, NULL, "Name of the storage engine."},
    {"in_transaction", (getter)sg_get_in_transaction, NULL,
        "Whether an updater is open on this subgraph."},
    {NULL}
};

static PyMemberDef sg_members[] = {
    {"_cached_wire_hash", T_OBJECT, offsetof(Sg, wire_hash), 0, NULL},
    {"_cached_arrays", T_OBJECT, offsetof(Sg, arrays_memo), 0, NULL},
    {"__weaklistoffset__", T_PYSSIZET, offsetof(Sg, weakreflist), READONLY},
    {NULL}
};

static PyType_Slot sg_slots[] = {
    {Py_tp_new, sg_new},
    {Py_tp_dealloc, sg_dealloc},
    {Py_tp_traverse, sg_traverse},
    {Py_tp_clear, sg_clear},
    {Py_tp_methods, sg_methods},
    {Py_tp_getset, sg_getset},
    {Py_tp_members, sg_members},
    {0, NULL}
};

PyType_Spec sg_spec = {"ordec.core.ordb._ordb.SubgraphBase",
    sizeof(Sg), 0, TPFLAGS | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC,
    sg_slots};
