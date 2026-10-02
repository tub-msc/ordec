// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// State, records and hashing, node operations, maintenance, transactions
// and their deferred checks: the storage engine below the Python types.

#include "module.h"

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

void
state_init(State *st)
{
    memset(st, 0, sizeof(State));
    kmap_init(&st->dir, 2, 0);
    st->nid_stop = (int64_t)1 << 32;
}

int
state_copy(State *dst, const State *src)
{
    *dst = *src;
    dst->tabs = PyMem_Malloc(sizeof(Tab) * (src->ntab + 1));
    dst->idxs = PyMem_Malloc(sizeof(Idx) * (src->nidx + 1));
    if (!dst->tabs || !dst->idxs) {
        PyMem_Free(dst->tabs);
        PyMem_Free(dst->idxs);
        PyErr_NoMemory();
        return -1;
    }
    if (src->ntab)
        memcpy(dst->tabs, src->tabs, sizeof(Tab) * src->ntab);
    if (src->nidx)
        memcpy(dst->idxs, src->idxs, sizeof(Idx) * src->nidx);
    for (int i = 0; i < src->ntab; i++) {
        Py_INCREF((PyObject *)src->tabs[i].nt);
        Py_XINCREF(src->tabs[i].rows.root);
    }
    Py_XINCREF(src->dir.root);
    for (int i = 0; i < src->nidx; i++) {
        const Idx *ix = &src->idxs[i];
        Py_INCREF(ix->index);
        Py_XINCREF(ix->tree.root);
    }
    Py_XINCREF(src->boxed);
    return 0;
}

static void
idxs_release(Idx *idxs, int nidx)
{
    for (int i = 0; i < nidx; i++) {
        Idx *ix = &idxs[i];
        Py_DECREF(ix->index);
        Py_XDECREF(ix->tree.root);
    }
    PyMem_Free(idxs);
}

void
state_release(State *st)
{
    Tab *tabs = st->tabs;
    int ntab = st->ntab;
    Idx *idxs = st->idxs;
    int nidx = st->nidx;
    PyObject *dir_root = st->dir.root, *boxed = st->boxed;
    st->tabs = NULL;
    st->ntab = 0;
    st->idxs = NULL;
    st->nidx = 0;
    st->dir.root = NULL;
    st->dir.levels = 0;
    st->boxed = NULL;
    st->nlive = 0;
    for (int i = 0; i < ntab; i++) {
        Py_XDECREF(tabs[i].rows.root);
        Py_DECREF(tabs[i].nt);
    }
    PyMem_Free(tabs);
    Py_XDECREF(dir_root);
    idxs_release(idxs, nidx);
    Py_XDECREF(boxed);
}

static int
st_add_tab(State *st, NType *nt)
{
    Tab *tabs = PyMem_Realloc(st->tabs, sizeof(Tab) * (st->ntab + 1));
    if (!tabs) {
        PyErr_NoMemory();
        return -1;
    }
    st->tabs = tabs;
    Tab *t = &tabs[st->ntab];
    memset(t, 0, sizeof(Tab));
    t->nt = (NType *)Py_NewRef((PyObject *)nt);
    kmap_init(&t->rows, nt->rec, nt->objmask);
    t->live = 0;
    return st->ntab++;
}

int
st_add_idx(State *st, PyObject *index, int combined)
{
    Idx *idxs = PyMem_Realloc(st->idxs, sizeof(Idx) * (st->nidx + 1));
    if (!idxs) {
        PyErr_NoMemory();
        return -1;
    }
    st->idxs = idxs;
    Idx *ix = &idxs[st->nidx];
    memset(ix, 0, sizeof(Idx));
    ix->index = Py_NewRef(index);
    ix->combined = combined;
    return st->nidx++;
}

// ---------------------------------------------------------------------------
// Subgraph and transaction
// ---------------------------------------------------------------------------

// Concurrency rules (see docs/dev/ordb_core.rst, "Threads"): one thread at a
// time may write a subgraph (the thread that opened the outermost updater),
// and no write may start while a write operation of the core is in progress
// (from a __hash__, a factory, a finalizer). Violations raise. Readers are
// not restricted; they never keep pointers into storage across Python code.
int
sg_write_begin(Sg *sg)
{
    unsigned long me = PyThread_get_thread_ident();
    if ((sg->txn || sg->writing) && sg->owner != me) {
        PyErr_SetString(OrdbException,
            "Subgraph is being modified by another thread.");
        return -1;
    }
    if (sg->writing) {
        PyErr_SetString(OrdbException, "Subgraph cannot be modified while"
            " ORDB is modifying it (e.g. from __hash__, __eq__, an attribute"
            " factory or a finalizer).");
        return -1;
    }
    sg->owner = me;
    sg->writing = 1;
    return 0;
}

// Writable directory record of nid, created (cleared) if missing.
static slot_t *
dir_w(Sg *sg, int64_t nid)
{
    State *st = &sg->st;
    if (nid < 0 || nid >= st->nid_stop) {
        PyErr_Format(OrdbException, "nid %lld is out of range.",
            (long long)nid);
        return NULL;
    }
    sg->txn->writes++;
    if (kmap_get(&st->dir, nid))
        return kmap_at_w(&st->dir, nid, sg->txn->tok);
    return kmap_insert(&st->dir, nid, sg->txn->tok);
}

// Removes the directory record d of nid if it has neither a node nor
// references.
static int
dir_tidy(Sg *sg, int64_t nid, const slot_t *d)
{
    if (d[0] || d[1])
        return 0;
    return kmap_remove(&sg->st.dir, nid, sg->txn->tok);
}

// Writable record of the live node nid in table ti.
static slot_t *
row_w(Sg *sg, int ti, int64_t nid)
{
    sg->txn->writes++;
    return kmap_at_w(&sg->st.tabs[ti].rows, nid, sg->txn->tok);
}

// -- boxed values ------------------------------------------------------------

static PyObject *
boxed_key(int64_t nid, int ai)
{
    return PyLong_FromLongLong(nid * 256 + ai);
}

static int
boxed_writable(Sg *sg)
{
    State *st = &sg->st;
    if (!st->boxed) {
        st->boxed = PyDict_New();
        return st->boxed ? 0 : -1;
    }
    if (Py_REFCNT(st->boxed) > 1) {
        PyObject *c = PyDict_Copy(st->boxed);
        if (!c)
            return -1;
        Py_DECREF(st->boxed); // shared: not the last reference
        st->boxed = c;
    }
    return 0;
}

static int
boxed_set(Sg *sg, int64_t nid, int ai, PyObject *v)
{
    if (boxed_writable(sg) < 0)
        return -1;
    PyObject *k = boxed_key(nid, ai);
    if (!k)
        return -1;
    int r = PyDict_SetItem(sg->st.boxed, k, v);
    Py_DECREF(k);
    return r;
}

PyObject *
boxed_get(const State *st, int64_t nid, int ai)
{
    PyObject *k = boxed_key(nid, ai);
    if (!k)
        return NULL;
    PyObject *v = st->boxed ? PyDict_GetItemWithError(st->boxed, k) : NULL;
    Py_DECREF(k);
    if (!v && !PyErr_Occurred())
        PyErr_SetString(PyExc_SystemError, "ORDB: missing boxed value");
    return v; // borrowed
}

// Drops the boxed values of a record that is about to be overwritten.
static int
boxed_drop_row(Sg *sg, const NType *nt, const slot_t *p, int64_t nid)
{
    for (int i = 0; i < nt->nattr; i++) {
        const AttrInfo *ai = &nt->attrs[i];
        if (ai->kind == K_OBJ || p[ai->slot] != SLOT_BOXED)
            continue;
        if (boxed_writable(sg) < 0)
            return -1;
        PyObject *k = boxed_key(nid, i);
        if (!k)
            return -1;
        int r = PyDict_DelItem(sg->st.boxed, k);
        Py_DECREF(k);
        if (r < 0)
            PyErr_Clear();
    }
    return 0;
}

// -- values ------------------------------------------------------------------

// The record of a NodeTuple as it is stored (boxed values in r->box),
// without touching storage. No Python code runs.
static int
rec_make(Rec *r, const NType *nt, PyObject *node, int64_t nid)
{
    r->nt = nt;
    r->nid = nid;
    memset(r->s, 0, sizeof(slot_t) * nt->rec);
    memset(r->box, 0, sizeof(PyObject *) * nt->nattr);
    r->s[0] = nid;
    for (int i = 0; i < nt->nattr; i++) {
        const AttrInfo *ai = &nt->attrs[i];
        PyObject *v = PyTuple_GetItem(node, i);
        if (!v) {
            rec_drop(r);
            return -1;
        }
        slot_t *s = r->s + ai->slot;
        if (ai->kind == K_OBJ) {
            s[0] = v == Py_None ? 0 : (slot_t)Py_NewRef(v);
            continue;
        }
        if (v == Py_None) {
            s[0] = SLOT_NONE;
            continue;
        }
        if (ai->kind == K_INT) {
            if (long_as_slot(v, s))
                continue;
        } else if ((PyObject *)Py_TYPE(v) == ai->vtype
                && PyTuple_Size(v) == ai->width) {
            int ok = 1;
            for (int k = 0; k < ai->width && ok; k++)
                ok = long_as_slot(PyTuple_GetItem(v, k), s + k);
            if (ok)
                continue;
            for (int k = 1; k < ai->width; k++)
                s[k] = 0;
        }
        s[0] = SLOT_BOXED;
        r->box[i] = Py_NewRef(v);
    }
    return 0;
}

// Writes a record into the cleared storage record p.
static int
rec_store(Sg *sg, const Rec *r, slot_t *p)
{
    const NType *nt = r->nt;
    memcpy(p, r->s, sizeof(slot_t) * nt->rec);
    recs_incref(p, nt->objmask, nt->rec, 1);
    for (int i = 0; i < nt->nattr; i++)
        if (r->box[i] && boxed_set(sg, r->nid, i, r->box[i]) < 0)
            return -1;
    return 0;
}

static inline int
slot_is_none(const AttrInfo *ai, const slot_t *p)
{
    return ai->kind == K_OBJ ? p[ai->slot] == 0 : p[ai->slot] == SLOT_NONE;
}

// Instances of tuple subclasses (NodeTuples, Vec2I, ...) are built with
// t = tuple_start(cls, n), PyTuple_SetItem on t, then tuple_finish(cls, t).
// Since 3.14, tuples cache their hash, and only tuple's own tp_new marks the
// cache as empty (a directly allocated instance would hash to 0): there, the
// items are collected in a plain tuple and copied by tp_new. Before 3.14,
// the instance is allocated directly, which is faster.
PyObject *
tuple_start(PyTypeObject *cls, Py_ssize_t n)
{
    return Py_Version < 0x030e0000 ? PyType_GenericAlloc(cls, n)
        : PyTuple_New(n);
}

PyObject *
tuple_finish(PyTypeObject *cls, PyObject *t)
{
    static newfunc tuple_new;
    if (!t || Py_Version < 0x030e0000)
        return t;
    if (!tuple_new)
        tuple_new = (newfunc)PyType_GetSlot(&PyTuple_Type, Py_tp_new);
    PyObject *args = PyTuple_Pack(1, t);
    Py_DECREF(t);
    if (!args)
        return NULL;
    PyObject *r = tuple_new(cls, args, NULL);
    Py_DECREF(args);
    return r;
}

// Value of an attribute from a stable copy of its slots and, if boxed,
// its boxed value (new reference).
static PyObject *
slots_value(const AttrInfo *ai, const slot_t *s, PyObject *boxed)
{
    if (ai->kind == K_OBJ)
        return Py_NewRef(s[0] ? (PyObject *)s[0] : Py_None);
    if (s[0] == SLOT_NONE)
        Py_RETURN_NONE;
    if (s[0] == SLOT_BOXED) {
        if (!boxed)
            PyErr_SetString(PyExc_SystemError, "ORDB: missing boxed value");
        return Py_XNewRef(boxed);
    }
    if (ai->kind == K_INT)
        return PyLong_FromLongLong(s[0]);
    PyTypeObject *vt = (PyTypeObject *)ai->vtype;
    PyObject *v = tuple_start(vt, ai->width);
    if (!v)
        return NULL;
    for (int k = 0; k < ai->width; k++) {
        PyObject *x = PyLong_FromLongLong(s[k]);
        if (!x) {
            Py_DECREF(v);
            return NULL;
        }
        PyTuple_SetItem(v, k, x);
    }
    return tuple_finish(vt, v);
}

// Value of one attribute of a stored record (new reference). Everything is
// read from storage before allocating: allocation can run Python code
// (garbage collection), which can let another thread write to the
// subgraph and move the storage.
PyObject *
attr_value(const State *st, const NType *nt, int i, const slot_t *p,
    int64_t nid)
{
    const AttrInfo *ai = &nt->attrs[i];
    slot_t s[MAXWIDTH];
    memcpy(s, p + ai->slot, sizeof(slot_t) * ai->width);
    if (ai->kind == K_OBJ)
        return Py_NewRef(s[0] ? (PyObject *)s[0] : Py_None);
    PyObject *boxed = NULL;
    if (s[0] == SLOT_BOXED && !(boxed = boxed_get(st, nid, i)))
        return NULL;
    return slots_value(ai, s, boxed);
}

void
rec_drop(Rec *r)
{
    const NType *nt = r->nt;
    recs_clear(r->s, nt->objmask, nt->rec, 1);
    for (int i = 0; i < nt->nattr; i++)
        Py_CLEAR(r->box[i]);
}

// Copies a stored record into r (no Python code runs in between).
int
rec_take(Rec *r, const State *st, const NType *nt, const slot_t *p,
    int64_t nid)
{
    r->nt = nt;
    r->nid = nid;
    memcpy(r->s, p, sizeof(slot_t) * nt->rec);
    recs_incref(r->s, nt->objmask, nt->rec, 1);
    memset(r->box, 0, sizeof(PyObject *) * nt->nattr);
    for (int i = 0; i < nt->nattr; i++) {
        const AttrInfo *ai = &nt->attrs[i];
        if (ai->kind == K_OBJ || r->s[ai->slot] != SLOT_BOXED)
            continue;
        PyObject *v = boxed_get(st, nid, i);
        if (!v) {
            rec_drop(r);
            return -1;
        }
        r->box[i] = Py_NewRef(v);
    }
    return 0;
}

static inline PyObject *
rec_value(const Rec *r, int i)
{
    const AttrInfo *ai = &r->nt->attrs[i];
    return slots_value(ai, r->s + ai->slot, r->box[i]);
}

// The NodeTuple of a record (new reference).
static PyObject *
rec_load(const Rec *r)
{
    const NType *nt = r->nt;
    PyTypeObject *tc = (PyTypeObject *)nt->tuple_cls;
    PyObject *t = tuple_start(tc, nt->nattr);
    if (!t)
        return NULL;
    for (int i = 0; i < nt->nattr; i++) {
        PyObject *v = rec_value(r, i);
        if (!v) {
            Py_DECREF(t);
            return NULL;
        }
        PyTuple_SetItem(t, i, v);
    }
    return tuple_finish(tc, t);
}

PyObject *
row_load(const State *st, const NType *nt, const slot_t *p, int64_t nid)
{
    Rec r;
    if (rec_take(&r, st, nt, p, nid) < 0)
        return NULL;
    PyObject *t = rec_load(&r);
    rec_drop(&r);
    return t;
}

// -- hashing -----------------------------------------------------------------

// Whether v hashes and compares like a plain tuple (tuple's own __hash__ and
// __eq__), as the value types stored in int64 slots must (Vec2I, ...).
static int
tuple_like(PyObject *v)
{
    static void *thash, *tcmp;
    if (!PyTuple_Check(v))
        return 0;
    PyTypeObject *t = Py_TYPE(v);
    if (t == &PyTuple_Type)
        return 1;
    if (!thash) {
        thash = PyType_GetSlot(&PyTuple_Type, Py_tp_hash);
        tcmp = PyType_GetSlot(&PyTuple_Type, Py_tp_richcompare);
    }
    return PyType_GetSlot(t, Py_tp_hash) == thash
        && PyType_GetSlot(t, Py_tp_richcompare) == tcmp;
}

// Hash of a Python value, consistent with == and with the hash of the same
// value stored in slots: an int hashes like in Python (int_hash), a
// tuple-like value as the mix of its items' Python hashes (mix_ints for
// slots), so that e.g. (1, 2), (True, 2.0) and Vec2I(1, 2) hash alike.
static int
pyval_hash(PyObject *v, uint64_t *out)
{
    if (v == Py_None) {
        *out = H_NONE;
        return 0;
    }
    if (tuple_like(v)) {
        Py_ssize_t n = PyTuple_Size(v);
        uint64_t h = mix_start(n);
        for (Py_ssize_t k = 0; k < n; k++) {
            Py_hash_t e = PyObject_Hash(PyTuple_GetItem(v, k));
            if (e == -1 && PyErr_Occurred())
                return -1;
            h = mix(h, (uint64_t)e);
        }
        *out = h;
        return 0;
    }
    Py_hash_t h = PyObject_Hash(v);
    if (h == -1 && PyErr_Occurred())
        return -1;
    *out = (uint64_t)h;
    return 0;
}

int
rec_slot_hash(const Rec *r, int i, uint64_t *out)
{
    const AttrInfo *ai = &r->nt->attrs[i];
    const slot_t *s = r->s + ai->slot;
    if (ai->kind == K_OBJ) {
        if (!s[0])
            return 1;
        return pyval_hash((PyObject *)s[0], out);
    }
    if (s[0] == SLOT_NONE)
        return 1;
    if (s[0] == SLOT_BOXED)
        return pyval_hash(r->box[i], out);
    *out = ai->kind == K_INT ? int_hash(s[0]) : mix_ints(ai->width, s);
    return 0;
}

// Index entry (h, s) of a record for one index. Returns 1 if the record
// is indexed, 0 if not (single key that is None), -1 on error.
int
rec_hs(const Rec *r, const IdxUse *u, uint64_t *h, int64_t *s)
{
    if (!u->combined) {
        int ok = rec_slot_hash(r, u->key[0], h);
        if (ok != 0)
            return ok < 0 ? -1 : 0;
    } else {
        uint64_t acc = 0x27D4EB2F165667C5ull;
        for (int k = 0; k < u->nkey; k++) {
            uint64_t hc = H_NONE;
            if (rec_slot_hash(r, u->key[k], &hc) < 0)
                return -1;
            acc = mix(acc, hc);
        }
        *h = acc;
    }
    *s = 0;
    if (u->sortfn) {
        PyObject *t = rec_load(r);
        if (!t)
            return -1;
        PyObject *v = PyObject_CallFunctionObjArgs(u->sortfn, t, NULL);
        Py_DECREF(t);
        if (!v)
            return -1;
        // None sorts like a None int attribute.
        if (v != Py_None && !PyLong_Check(v)) {
            PyObject *n = PyType_GetName(Py_TYPE(v));
            PyErr_Format(PyExc_TypeError,
                "sortkey must return an int or None, not %S.", n);
            Py_XDECREF(n);
            Py_DECREF(v);
            return -1;
        }
        long long x = v == Py_None ? SLOT_NONE : PyLong_AsLongLong(v);
        Py_DECREF(v);
        if (x == -1 && PyErr_Occurred())
            return -1;
        *s = x == SLOT_BOXED ? 0 : x;
    } else if (u->sort >= 0) {
        slot_t v = r->s[r->nt->attrs[u->sort].slot];
        *s = v == SLOT_BOXED ? 0 : v;
    }
    return 1;
}

// Hash of a query key. Returns 0 if the key cannot match anything.
int
key_hash(PyObject *key, int combined, uint64_t *h)
{
    if (!combined) {
        if (key == Py_None)
            return 0;
        return pyval_hash(key, h) < 0 ? -1 : 1;
    }
    if (!PyTuple_Check(key))
        return 0;
    uint64_t acc = 0x27D4EB2F165667C5ull;
    for (Py_ssize_t k = 0; k < PyTuple_Size(key); k++) {
        uint64_t hc;
        if (pyval_hash(PyTuple_GetItem(key, k), &hc) < 0)
            return -1;
        acc = mix(acc, hc);
    }
    *h = acc;
    return 1;
}

// Compares an attribute of a record with a Python value.
int
rec_eq_pyval(const Rec *r, int i, PyObject *v)
{
    const AttrInfo *ai = &r->nt->attrs[i];
    slot_t mine = r->s[ai->slot], x;
    if (ai->kind == K_INT && mine > SLOT_BOXED && long_as_slot(v, &x))
        return mine == x;
    if (ai->kind == K_OBJ && (PyObject *)mine == v)
        return 1;
    PyObject *val = rec_value(r, i);
    if (!val)
        return -1;
    int ret = PyObject_RichCompareBool(val, v, Py_EQ);
    Py_DECREF(val);
    return ret;
}

// Compares one attribute of two records (possibly of different subgraphs
// and, for index keys, of different node types).
int
rec_eq(const Rec *ra, int ia, const Rec *rb, int ib)
{
    const AttrInfo *a = &ra->nt->attrs[ia], *b = &rb->nt->attrs[ib];
    const slot_t *pa = ra->s + a->slot, *pb = rb->s + b->slot;
    if (a->kind == b->kind && a->width == b->width && a->vtype == b->vtype) {
        if (a->kind == K_OBJ) {
            if (pa[0] == pb[0])
                return 1;
        } else if (pa[0] != SLOT_BOXED && pb[0] != SLOT_BOXED) {
            return memcmp(pa, pb, sizeof(slot_t) * a->width) == 0;
        }
    }
    PyObject *va = rec_value(ra, ia);
    if (!va)
        return -1;
    PyObject *vb = rec_value(rb, ib);
    if (!vb) {
        Py_DECREF(va);
        return -1;
    }
    int ret = PyObject_RichCompareBool(va, vb, Py_EQ);
    Py_DECREF(va);
    Py_DECREF(vb);
    return ret;
}

// ---------------------------------------------------------------------------
// Node operations
// ---------------------------------------------------------------------------

static int
chk_add(Txn *tx, int64_t nid)
{
    if (tx->nchk && tx->chk[2 * tx->nchk - 1] == nid) {
        tx->chk[2 * tx->nchk - 1] = nid + 1;
        return 0;
    }
    if (tx->nchk == tx->capchk) {
        size_t cap = tx->capchk ? tx->capchk * 2 : 8;
        int64_t *c = PyMem_Realloc(tx->chk, sizeof(int64_t) * 2 * cap);
        if (!c) {
            PyErr_NoMemory();
            return -1;
        }
        tx->chk = c;
        tx->capchk = cap;
    }
    tx->chk[2 * tx->nchk] = nid;
    tx->chk[2 * tx->nchk + 1] = nid + 1;
    tx->nchk++;
    return 0;
}

static int
rem_add(Txn *tx, int64_t nid)
{
    if (tx->nrem == tx->caprem) {
        size_t cap = tx->caprem ? tx->caprem * 2 : 8;
        int64_t *c = PyMem_Realloc(tx->rem, sizeof(int64_t) * cap);
        if (!c) {
            PyErr_NoMemory();
            return -1;
        }
        tx->rem = c;
        tx->caprem = cap;
    }
    tx->rem[tx->nrem++] = nid;
    return 0;
}

static inline void
txn_seen_nid(Txn *tx, int64_t nid)
{
    if (nid > tx->nid_max)
        tx->nid_max = nid;
    if (tx->nid_gen < tx->nid_max + 1)
        tx->nid_gen = tx->nid_max + 1;
}

// Adjusts the inbound reference counts for the LocalRefs of a record.
static int
refs_adjust(Sg *sg, const NType *nt, const slot_t *p, int delta)
{
    for (int i = 0; i < nt->nattr; i++) {
        const AttrInfo *ai = &nt->attrs[i];
        if (ai->ref_kind != REF_LOCAL)
            continue;
        slot_t v = p[ai->slot];
        if (v < 0) // None, boxed or invalid: caught by the commit check
            continue;
        if (delta < 0 && !st_dir(&sg->st, v))
            continue;
        slot_t *d = dir_w(sg, v);
        if (!d)
            return -1;
        d[1] += delta;
        if (delta < 0 && dir_tidy(sg, v, d) < 0)
            return -1;
    }
    return 0;
}

// The index keys of a record, one per index of its node type. Hashes and
// sortkey functions may run Python code: callers compute keys before
// their first write.
static int
rec_keys(const Rec *r, IdxKey *k)
{
    for (int i = 0; i < r->nt->nuse; i++) {
        k[i].on = rec_hs(r, &r->nt->uses[i], &k[i].h, &k[i].s);
        if (k[i].on < 0)
            return -1;
    }
    return 0;
}

// The index keys of the stored record p of node nid.
static int
row_keys(const State *st, const NType *nt, const slot_t *p, int64_t nid,
    IdxKey *k)
{
    if (!nt->nuse)
        return 0;
    Rec rec;
    if (rec_take(&rec, st, nt, p, nid) < 0)
        return -1;
    int r = rec_keys(&rec, k);
    rec_drop(&rec);
    return r;
}

// Replaces the index entries of node nid with the keys o by those with the
// keys n (either may be NULL: no entries).
static int
index_change(Sg *sg, const NType *nt, const IdxKey *o, const IdxKey *n,
    int64_t nid)
{
    for (int i = 0; i < nt->nuse; i++) {
        int on_o = o && o[i].on, on_n = n && n[i].on;
        if (on_o && on_n && o[i].h == n[i].h && o[i].s == n[i].s)
            continue;
        if (on_o) {
            Ent e = {o[i].h, o[i].s, nid};
            if (idx_remove(sg, &nt->uses[i], &e) < 0)
                return -1;
        }
        if (on_n) {
            Ent e = {n[i].h, n[i].s, nid};
            if (idx_insert(sg, &nt->uses[i], &e) < 0)
                return -1;
        }
    }
    return 0;
}

// Reserves the record for a new node nid of type nt. The record is
// returned cleared, with the directory pointing at it.
static slot_t *
node_place(Sg *sg, NType *nt, int64_t nid)
{
    State *st = &sg->st;
    int ti = st_find_tab(st, nt);
    if (ti < 0 && (ti = st_add_tab(st, nt)) < 0)
        return NULL;
    slot_t *d = dir_w(sg, nid);
    if (!d)
        return NULL;
    sg->txn->writes++;
    slot_t *p = kmap_insert(&st->tabs[ti].rows, nid, sg->txn->tok);
    if (!p)
        return NULL;
    d[0] = DIR_LOC(ti);
    p[0] = nid;
    st->tabs[ti].live++;
    st->nlive++;
    return p;
}

int
op_add(Sg *sg, int64_t nid, PyObject *node)
{
    Txn *tx = sg->txn;
    NType *nt = ntype_of_cls((PyObject *)Py_TYPE(node));
    if (!nt)
        return -1;
    int ti;
    if (st_row(&sg->st, nid, &ti)) {
        PyErr_SetString(OrdbException, "Duplicate nid.");
        return -1;
    }
    Rec rec;
    IdxKey k[MAXUSE];
    if (rec_make(&rec, nt, node, nid) < 0)
        return -1;
    int ret = -1;
    if (rec_keys(&rec, k) == 0) {
        slot_t *p = node_place(sg, nt, nid);
        if (p && rec_store(sg, &rec, p) == 0 && refs_adjust(sg, nt, p, 1) == 0
                && index_change(sg, nt, NULL, k, nid) == 0
                && chk_add(tx, nid) == 0) {
            txn_seen_nid(tx, nid);
            ret = 0;
        }
    }
    rec_drop(&rec);
    return ret;
}

// Removes a node with the index keys k (computed beforehand), without the
// root guard and without recording the removal.
static int
node_drop(Sg *sg, int64_t nid, int ti, const IdxKey *k)
{
    State *st = &sg->st;
    NType *nt = st->tabs[ti].nt;
    if (index_change(sg, nt, k, NULL, nid) < 0)
        return -1;
    const slot_t *p = kmap_get(&st->tabs[ti].rows, nid);
    if (refs_adjust(sg, nt, p, -1) < 0 || boxed_drop_row(sg, nt, p, nid) < 0)
        return -1;
    sg->txn->writes++;
    if (kmap_remove(&st->tabs[ti].rows, nid, sg->txn->tok) < 0)
        return -1;
    slot_t *dw = dir_w(sg, nid);
    if (!dw)
        return -1;
    dw[0] = 0;
    if (dir_tidy(sg, nid, dw) < 0)
        return -1;
    st->tabs[ti].live--;
    st->nlive--;
    return 0;
}

int
op_remove(Sg *sg, int64_t nid)
{
    State *st = &sg->st;
    int ti;
    if (nid == 0) {
        PyErr_SetString(OrdbException, "Cannot delete SubgraphRoot (nid=0).");
        return -1;
    }
    const slot_t *p = st_row(st, nid, &ti);
    if (!p) {
        PyObject *k = PyLong_FromLongLong(nid);
        PyErr_SetObject(PyExc_KeyError, k);
        Py_XDECREF(k);
        return -1;
    }
    IdxKey k[MAXUSE];
    if (row_keys(st, st->tabs[ti].nt, p, nid, k) < 0
            || node_drop(sg, nid, ti, k) < 0)
        return -1;
    return rem_add(sg->txn, nid);
}

int
op_update(Sg *sg, int64_t nid, PyObject *node)
{
    State *st = &sg->st;
    Txn *tx = sg->txn;
    NType *nt = ntype_of_cls((PyObject *)Py_TYPE(node));
    if (!nt)
        return -1;
    int ti;
    const slot_t *cp = st_row(st, nid, &ti);
    if (!cp) {
        PyErr_Format(PyExc_KeyError, "nid %lld not found", (long long)nid);
        return -1;
    }
    NType *ont = st->tabs[ti].nt;
    IdxKey ok[MAXUSE], nk[MAXUSE];
    Rec rec;
    if (row_keys(st, ont, cp, nid, ok) < 0
            || rec_make(&rec, nt, node, nid) < 0)
        return -1;
    int ret = -1;
    if (rec_keys(&rec, nk) < 0)
        goto done;
    // Writes from here on.
    if (ont != nt) {
        // Type change: the node moves to another table.
        slot_t *p;
        if (node_drop(sg, nid, ti, ok) == 0
                && (p = node_place(sg, nt, nid))
                && rec_store(sg, &rec, p) == 0
                && refs_adjust(sg, nt, p, 1) == 0
                && index_change(sg, nt, NULL, nk, nid) == 0)
            ret = chk_add(tx, nid);
        goto done;
    }
    slot_t *p = row_w(sg, ti, nid);
    if (!p || refs_adjust(sg, nt, p, -1) < 0
            || boxed_drop_row(sg, nt, p, nid) < 0)
        goto done;
    recs_clear(p, nt->objmask, nt->rec, 1);
    if (rec_store(sg, &rec, p) == 0 && refs_adjust(sg, nt, p, 1) == 0
            && index_change(sg, nt, ok, nk, nid) == 0)
        ret = chk_add(tx, nid);
done:
    rec_drop(&rec);
    return ret;
}

// Inserts n rows of an all-integer node type from int64 columns (one
// buffer of n * width values per attribute). The index entries (which may
// call sortkey functions) and the values are checked before the first
// write.
int
op_insert_rows(Sg *sg, NType *nt, const int64_t *nids, Py_ssize_t n,
    const int64_t **cols)
{
    State *st = &sg->st;
    Txn *tx = sg->txn;
    int nuse = nt->nuse;
    Ent *ents[MAXUSE] = {NULL};
    uint64_t nents[MAXUSE] = {0};
    int ret = -1;
    for (int i = 0; i < nuse; i++) {
        if (!(ents[i] = PyMem_Malloc(sizeof(Ent) * (n + 1)))) {
            PyErr_NoMemory();
            goto done;
        }
    }
    for (Py_ssize_t r = 0; r < n; r++) {
        int64_t nid = nids[r];
        int ti;
        if (st_row(st, nid, &ti)) {
            PyErr_SetString(OrdbException, "Duplicate nid.");
            goto done;
        }
        Rec rec;
        rec.nt = nt;
        rec.nid = nid;
        rec.s[0] = nid;
        memset(rec.box, 0, sizeof(PyObject *) * nt->nattr);
        for (int i = 0; i < nt->nattr; i++) {
            const AttrInfo *ai = &nt->attrs[i];
            for (int k = 0; k < ai->width; k++) {
                int64_t v = cols[i][r * ai->width + k];
                if (v <= SLOT_BOXED) {
                    PyErr_SetString(PyExc_ValueError,
                        "array value outside the supported int64 range.");
                    goto done;
                }
                rec.s[ai->slot + k] = v;
            }
        }
        IdxKey k[MAXUSE];
        if (rec_keys(&rec, k) < 0)
            goto done;
        for (int i = 0; i < nuse; i++)
            if (k[i].on)
                ents[i][nents[i]++] = (Ent){k[i].h, k[i].s, nid};
    }
    // Writes from here on.
    for (Py_ssize_t r = 0; r < n; r++) {
        int64_t nid = nids[r];
        int ti;
        if (st_row(st, nid, &ti)) { // the same nid twice in the batch
            PyErr_SetString(OrdbException, "Duplicate nid.");
            goto done;
        }
        slot_t *p = node_place(sg, nt, nid);
        if (!p)
            goto done;
        for (int i = 0; i < nt->nattr; i++) {
            const AttrInfo *ai = &nt->attrs[i];
            memcpy(p + ai->slot, cols[i] + r * ai->width,
                sizeof(slot_t) * ai->width);
        }
        if (refs_adjust(sg, nt, p, 1) < 0 || chk_add(tx, nid) < 0)
            goto done;
        txn_seen_nid(tx, nid);
    }
    for (int i = 0; i < nuse; i++) {
        int sorted = 1;
        for (uint64_t k = 1; k < nents[i] && sorted; k++)
            sorted = ent_lt(&ents[i][k - 1], &ents[i][k]);
        if (!sorted)
            qsort(ents[i], nents[i], sizeof(Ent), ent_cmp);
        if (idx_insert_sorted(sg, &nt->uses[i], ents[i], nents[i]) < 0)
            goto done;
    }
    ret = 0;
done:
    for (int i = 0; i < nuse; i++)
        PyMem_Free(ents[i]);
    return ret;
}

typedef struct {
    const slot_t **rows;
    uint64_t n;
} RowList;

static int
rowlist_add(const slot_t *p, void *arg)
{
    RowList *l = arg;
    l->rows[l->n++] = p;
    return 0;
}

// The live rows of table ti in ascending nid order. The pointers are valid
// until the next write or Python code.
const slot_t **
tab_rows_sorted(const State *st, int ti, uint64_t *n_out)
{
    const Tab *t = &st->tabs[ti];
    const slot_t **rows = PyMem_Malloc(sizeof(slot_t *) * (t->live + 1));
    if (!rows) {
        PyErr_NoMemory();
        return NULL;
    }
    RowList l = {rows, 0};
    kmap_walk(&t->rows, rowlist_add, &l);
    *n_out = l.n;
    return rows;
}

// ---------------------------------------------------------------------------
// Transactions
// ---------------------------------------------------------------------------

Txn *
txn_begin(Sg *sg)
{
    if (sg_write_begin(sg) < 0)
        return NULL;
    sg_write_end(sg);
    Txn *tx = PyMem_Calloc(1, sizeof(Txn));
    if (!tx) {
        PyErr_NoMemory();
        return NULL;
    }
    if (state_copy(&tx->saved, &sg->st) < 0) {
        PyMem_Free(tx);
        return NULL;
    }
    tx->tok = ++g_token;
    if (sg->txn) { // nested: continue the nid counter of the parent
        tx->nid_gen = sg->txn->nid_gen;
        tx->nid_max = sg->txn->nid_max;
    } else {
        tx->nid_gen = sg->st.nid_start;
        tx->nid_max = sg->st.nid_start - 1;
    }
    tx->parent = sg->txn;
    if (!sg->txn)
        sg->owner = PyThread_get_thread_ident();
    sg->txn = tx;
    return tx;
}

static void
txn_free(Txn *tx)
{
    PyMem_Free(tx->chk);
    PyMem_Free(tx->rem);
    PyMem_Free(tx);
}

void
txn_abort(Sg *sg, Txn *tx)
{
    sg->txn = tx->parent;
    sg->hash_valid = 0;
    state_release(&sg->st);
    sg->st = tx->saved;
    txn_free(tx);
}

// Aborts the abandoned transactions (see upd_dealloc) with all transactions
// opened inside them. Called at the end of a write operation.
void
txn_abort_abandoned(Sg *sg)
{
    Txn *outer = NULL;
    for (Txn *t = sg->txn; t; t = t->parent)
        if (t->abandoned)
            outer = t;
    sg->abandoned = 0;
    for (int last = !outer; !last;) {
        last = sg->txn == outer;
        txn_abort(sg, sg->txn);
    }
}

static int
call_check(int kind, PyObject *sgu, int64_t nid, PyObject *obj)
{
    PyObject *r = PyObject_CallFunction(g_check_cb, "iOLO", kind, sgu,
        (long long)nid, obj ? obj : Py_None);
    if (!r)
        return -1;
    Py_DECREF(r);
    return 0;
}

// attr.refcheck(target type), memoized per target type.
static int
refcheck(AttrInfo *ai, NType *target)
{
    PyObject *c = PyDict_GetItemWithError(ai->refcache, (PyObject *)target);
    if (c)
        return c == Py_True;
    if (PyErr_Occurred())
        return -1;
    PyObject *r = PyObject_CallMethodObjArgs(ai->attr, str_refcheck,
        target->cursor_type, NULL);
    if (!r)
        return -1;
    int ok = PyObject_IsTrue(r);
    Py_DECREF(r);
    if (ok < 0 || PyDict_SetItem(ai->refcache, (PyObject *)target,
            ok ? Py_True : Py_False) < 0)
        return -1;
    return ok;
}

#define EXT_ROOT (-2)
#define EXT_SELF (-1)

// The subgraph in the SubgraphRef of node nid that is one of the attributes
// refs (borrowed from the storage), or NULL.
static Sg *
subref_target(const State *st, int64_t nid, PyObject *refs)
{
    int ti;
    const slot_t *p = nid >= 0 ? st_row(st, nid, &ti) : NULL;
    if (!p)
        return NULL;
    const NType *nt = st->tabs[ti].nt;
    for (int a = 0; a < nt->nattr; a++) {
        const AttrInfo *ai = &nt->attrs[a];
        if (ai->kind != K_OBJ)
            continue;
        for (Py_ssize_t k = 0; k < PyTuple_Size(refs); k++) {
            if (PyTuple_GetItem(refs, k) == ai->attr) {
                PyObject *o = (PyObject *)p[ai->slot];
                return o && PyObject_TypeCheck(o, Sg_Type) ? (Sg *)o : NULL;
            }
        }
    }
    return NULL;
}

// The subgraph that the ExternalRef ai of the record p (node nid) points
// into, resolved through ai->ext_refs (borrowed from the storage), or NULL.
Sg *
ext_target(const State *st, const NType *nt, const AttrInfo *ai,
    const slot_t *p, int64_t nid)
{
    int64_t start = ai->ext_start == EXT_ROOT ? 0
        : ai->ext_start == EXT_SELF ? nid
        : p[nt->attrs[ai->ext_start].slot];
    return subref_target(st, start, ai->ext_refs);
}

// Deferred constraint checks of a transaction. The core only decides
// "fine" on its fast paths; everything else goes to base.py, which raises.
int
txn_check(Sg *sg, Txn *tx, PyObject *sgu)
{
    State *st = &sg->st;
    int rti;
    if (!st_row(st, 0, &rti))
        return call_check(CB_MISSING_ROOT, sgu, 0, NULL);
    NType *root_nt = st->tabs[rti].nt;
    // Subgraphs referenced through the root, resolved once per commit.
    const AttrInfo *ext_attr[8];
    Sg *ext_sg[8];
    int next = 0;

    for (size_t c = 0; c < tx->nchk; c++) {
        for (int64_t nid = tx->chk[2 * c]; nid < tx->chk[2 * c + 1]; nid++) {
            int ti;
            const slot_t *p = st_row(st, nid, &ti);
            if (!p)
                continue;
            NType *nt = st->tabs[ti].nt;
            if (nid != 0) {
                PyObject *ok = PyDict_GetItemWithError(nt->permitted,
                    (PyObject *)root_nt);
                if (!ok) {
                    if (PyErr_Occurred()
                            || call_check(CB_PERMITTED, sgu, nid, NULL) < 0
                            || PyDict_SetItem(nt->permitted,
                                (PyObject *)root_nt, Py_True) < 0)
                        return -1;
                    if (!(p = st_row(st, nid, &ti)))
                        continue;
                }
            }
            for (int i = 0; i < nt->nattr; i++) {
                const AttrInfo *ai = &nt->attrs[i];
                if (!ai->optional && slot_is_none(ai, p)) {
                    if (call_check(CB_NOTNULL, sgu, nid, ai->attr) < 0)
                        return -1;
                }
            }
            for (int k = 0; k < nt->ncheck; k++) {
                CheckItem *ci = &nt->checks[k];
                // Callbacks may run arbitrary code: look the record up again.
                p = st_row(st, nid, &ti);
                if (!p || st->tabs[ti].nt != nt)
                    break;
                if (ci->kind == CHK_UNIQUE) {
                    IdxUse *u = &nt->uses[ci->i];
                    Rec rec;
                    if (rec_take(&rec, st, nt, p, nid) < 0)
                        return -1;
                    int v = unique_violated(st, &rec, u);
                    rec_drop(&rec);
                    if (v < 0 || (v && call_check(CB_UNIQUE, sgu, nid,
                            u->index) < 0))
                        return -1;
                    continue;
                }
                AttrInfo *ai = &nt->attrs[ci->i];
                slot_t v = p[ai->slot];
                if (v == SLOT_NONE)
                    continue;
                if (ci->kind == CHK_LOCAL) {
                    int tti, ok = 0;
                    if (v >= 0 && st_row(st, v, &tti)) {
                        ok = refcheck(ai, st->tabs[tti].nt);
                        if (ok < 0)
                            return -1;
                    }
                    if (!ok && call_check(CB_LOCALREF, sgu, nid, ai->attr) < 0)
                        return -1;
                    continue;
                }
                // ExternalRef
                int ok = 0;
                if (ai->ext_refs && v >= 0) {
                    Sg *target = NULL;
                    if (ai->ext_start == EXT_ROOT) {
                        // Same root for all nodes: resolved once per commit.
                        int e;
                        for (e = 0; e < next && ext_attr[e] != ai; e++)
                            ;
                        if (e < next) {
                            target = ext_sg[e];
                        } else {
                            target = ext_target(st, nt, ai, p, nid);
                            if (target && next < 8) {
                                ext_attr[next] = ai;
                                ext_sg[next++] = target;
                            }
                        }
                    } else {
                        target = ext_target(st, nt, ai, p, nid);
                    }
                    int tti;
                    if (target && st_row(&target->st, v, &tti)) {
                        ok = refcheck(ai, target->st.tabs[tti].nt);
                        if (ok < 0)
                            return -1;
                    }
                } else if (ai->subfn && v >= 0) {
                    Sg *target = call_subfn(ai->subfn, sg, nid);
                    if (!target && PyErr_Occurred())
                        return -1;
                    int tti;
                    if (target && st_row(&target->st, v, &tti))
                        ok = refcheck(ai, target->st.tabs[tti].nt);
                    Py_XDECREF((PyObject *)target);
                    if (ok < 0)
                        return -1;
                }
                if (!ok && call_check(CB_EXTERNALREF, sgu, nid, ai->attr) < 0)
                    return -1;
            }
        }
    }
    for (size_t i = 0; i < tx->nrem; i++) {
        int64_t nid = tx->rem[i];
        int ti;
        const slot_t *d = st_dir(st, nid);
        if (d && d[1] > 0 && !st_row(st, nid, &ti)) {
            if (call_check(CB_DANGLING, sgu, nid, NULL) < 0)
                return -1;
        }
    }
    return 0;
}

int
txn_commit(Sg *sg, Txn *tx)
{
    State *st = &sg->st;
    st->nid_start = tx->nid_max + 1;
    sg->txn = tx->parent;
    sg->hash_valid = 0;
    state_release(&tx->saved);
    if (tx->parent) {
        if (tx->nid_max > tx->parent->nid_max)
            tx->parent->nid_max = tx->nid_max;
        if (tx->nid_gen > tx->parent->nid_gen)
            tx->parent->nid_gen = tx->nid_gen;
    }
    txn_free(tx);
    return 0;
}
