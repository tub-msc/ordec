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
    vec_init(&st->dir, 2, 0);
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
        for (int r = 0; r < ix->nruns; r++)
            ix->runs[r]->rc++;
        if (ix->tail)
            ix->tail->rc++;
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
        for (int r = 0; r < ix->nruns; r++)
            run_decref(ix->runs[r]);
        run_decref(ix->tail);
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
    st->dir.count = 0;
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
    t->nt = (NType *)Py_NewRef((PyObject *)nt);
    vec_init(&t->rows, nt->rec, nt->objmask);
    t->live = 0;
    t->last_nid = -1;
    t->sorted = 1;
    return st->ntab++;
}

static int
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

// Writable directory record of nid. Extends the directory (zero-filled)
// when nid is beyond its end.
static slot_t *
dir_w(Sg *sg, int64_t nid)
{
    State *st = &sg->st;
    Txn *tx = sg->txn;
    Vec *dir = &st->dir;
    uint64_t txtok = tx ? tx->tok : 0;
    if (nid < 0 || nid >= st->nid_stop
            || nid >= (int64_t)dir->count + DIR_MAX_GAP) {
        PyErr_Format(OrdbException, "nid %lld is out of range.",
            (long long)nid);
        return NULL;
    }
    if (tx)
        tx->writes++;
    uint64_t i = (uint64_t)nid;
    if (i >= dir->count) {
        // Leaves owned by this subgraph may hold leftovers of aborted
        // transactions behind count: zero all existing leaves in the gap.
        slot_t *p = NULL;
        uint64_t j = dir->count;
        while (j <= i) {
            uint64_t end = (j | (LEAF_ROWS - 1)) + 1;
            if (end > i + 1)
                end = i + 1;
            int exists = dir->root
                && j < ((uint64_t)LEAF_ROWS << (BITS * dir->levels))
                && vec_get(dir, j) != NULL;
            if (exists || end == i + 1) {
                p = vec_at_w(dir, j, sg->tok, txtok, 1);
                if (!p)
                    return NULL;
                memset(p, 0, sizeof(slot_t) * 2 * (end - j));
                p += 2 * (i - j);
            }
            j = end;
        }
        dir->count = i + 1;
        return p;
    }
    int append = tx && i >= tx->saved.dir.count;
    return vec_at_w(dir, i, sg->tok, txtok, append);
}

// Writable record of an existing row.
static slot_t *
tab_row_w(Sg *sg, int ti, uint64_t row)
{
    Txn *tx = sg->txn;
    Vec *v = &sg->st.tabs[ti].rows;
    int append = tx && (ti >= tx->saved.ntab
        || row >= tx->saved.tabs[ti].rows.count);
    if (tx)
        tx->writes++;
    return vec_at_w(v, row, sg->tok, tx ? tx->tok : 0, append);
}

// Appends a record and returns it with its object slots cleared.
static slot_t *
tab_append(Sg *sg, int ti)
{
    Vec *v = &sg->st.tabs[ti].rows;
    if (sg->txn)
        sg->txn->writes++;
    slot_t *p = vec_at_w(v, v->count, sg->tok, sg->txn ? sg->txn->tok : 0, 1);
    if (!p)
        return NULL;
    recs_clear(p, v->objmask, v->rec, 1);
    v->count++;
    return p;
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

static inline int
long_as_slot(PyObject *v, slot_t *out)
{
    if (!PyLong_CheckExact(v))
        return 0;
    int ovf;
    long long x = PyLong_AsLongLongAndOverflow(v, &ovf);
    if (ovf || x <= SLOT_BOXED)
        return 0;
    *out = x;
    return 1;
}

// Writes the values of a NodeTuple into a cleared record.
static int
row_store(Sg *sg, const NType *nt, slot_t *p, PyObject *node, int64_t nid)
{
    for (int i = 0; i < nt->nattr; i++) {
        const AttrInfo *ai = &nt->attrs[i];
        PyObject *v = PyTuple_GetItem(node, i);
        if (!v)
            return -1;
        slot_t *s = p + ai->slot;
        if (ai->kind == K_OBJ) {
            s[0] = v == Py_None ? 0 : (slot_t)Py_NewRef(v);
            continue;
        }
        for (int k = 1; k < ai->width; k++)
            s[k] = 0;
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
        if (boxed_set(sg, nid, i, v) < 0)
            return -1;
    }
    return 0;
}

static inline int
slot_is_none(const AttrInfo *ai, const slot_t *p)
{
    return ai->kind == K_OBJ ? p[ai->slot] == 0 : p[ai->slot] == SLOT_NONE;
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
    PyObject *v = PyType_GenericAlloc(vt, ai->width);
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
    return v;
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
    PyObject *t = PyType_GenericAlloc(tc, nt->nattr);
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
    return t;
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

// Hash of a Python value, consistent with how the same value hashes when
// it is stored in slots: ints by value, tuples of ints by mix_ints.
static int
pyval_hash(PyObject *v, uint64_t *out)
{
    if (v == Py_None) {
        *out = H_NONE;
        return 0;
    }
    if (PyLong_Check(v)) {
        int ovf;
        long long x = PyLong_AsLongLongAndOverflow(v, &ovf);
        if (!ovf) {
            *out = (uint64_t)x;
            return 0;
        }
    } else if (PyTuple_Check(v) && PyTuple_Size(v) <= 8) {
        slot_t x[8];
        int n = (int)PyTuple_Size(v), ok = 1;
        for (int k = 0; k < n && ok; k++)
            ok = long_as_slot(PyTuple_GetItem(v, k), &x[k]);
        if (ok && n > 0) {
            *out = mix_ints(n, x);
            return 0;
        }
    }
    Py_hash_t h = PyObject_Hash(v);
    if (h == -1 && PyErr_Occurred())
        return -1;
    *out = (uint64_t)h;
    return 0;
}

// Hash of one attribute of a record. Returns 1 if the value is None.
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
    *out = ai->kind == K_INT ? (uint64_t)s[0] : mix_ints(ai->width, s);
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
        if (delta < 0 && (uint64_t)v >= sg->st.dir.count)
            continue;
        slot_t *d = dir_w(sg, v);
        if (!d)
            return -1;
        d[1] += delta;
    }
    return 0;
}

static int
index_row(Sg *sg, NType *nt, const slot_t *p, int64_t nid)
{
    if (!nt->nuse)
        return 0;
    Rec rec;
    if (rec_take(&rec, &sg->st, nt, p, nid) < 0)
        return -1;
    int ret = 0;
    for (int i = 0; i < nt->nuse && ret == 0; i++) {
        IdxUse *u = &nt->uses[i];
        Ent e = {0, 0, nid};
        int r = rec_hs(&rec, u, &e.h, &e.s);
        if (r <= 0) {
            ret = r;
            continue;
        }
        int xi = st_find_idx(&sg->st, u->index);
        if ((xi < 0 && (xi = st_add_idx(&sg->st, u->index, u->combined)) < 0)
                || idx_insert(sg, &sg->st.idxs[xi], e) < 0)
            ret = -1;
    }
    rec_drop(&rec);
    return ret;
}

static void
index_garbage(State *st, const NType *nt)
{
    for (int i = 0; i < nt->nuse; i++) {
        int xi = st_find_idx(st, nt->uses[i].index);
        if (xi >= 0)
            st->idxs[xi].garbage++;
    }
}

// Reserves the record for a new node nid of type nt: revives the node's
// tombstone if it is in the same table, else appends. The record is
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
    slot_t loc = d[0];
    slot_t *p;
    if ((loc & DIR_DEAD) && DIR_TAB(loc) == ti) {
        p = tab_row_w(sg, ti, DIR_ROW(loc));
        if (!p)
            return NULL;
        recs_clear(p, nt->objmask, nt->rec, 1);
        d[0] = loc & ~DIR_DEAD;
    } else {
        uint64_t row = st->tabs[ti].rows.count;
        p = tab_append(sg, ti);
        if (!p)
            return NULL;
        d[0] = DIR_LOC(ti, row);
        Tab *t = &st->tabs[ti];
        if (nid > t->last_nid)
            t->last_nid = nid;
        else
            t->sorted = 0;
    }
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
    slot_t *p = node_place(sg, nt, nid);
    if (!p)
        return -1;
    if (row_store(sg, nt, p, node, nid) < 0
            || refs_adjust(sg, nt, p, 1) < 0
            || index_row(sg, nt, p, nid) < 0
            || chk_add(tx, nid) < 0)
        return -1;
    txn_seen_nid(tx, nid);
    return 0;
}

// Removes a node without the root guard and without marking it removed.
static int
node_drop(Sg *sg, int64_t nid, int ti)
{
    State *st = &sg->st;
    NType *nt = st->tabs[ti].nt;
    const slot_t *d = st_dir(st, nid);
    uint64_t row = DIR_ROW(d[0]);
    slot_t *p = tab_row_w(sg, ti, row);
    if (!p)
        return -1;
    if (refs_adjust(sg, nt, p, -1) < 0 || boxed_drop_row(sg, nt, p, nid) < 0)
        return -1;
    index_garbage(st, nt);
    recs_clear(p, nt->objmask, nt->rec, 1);
    memset(p, 0, sizeof(slot_t) * nt->rec);
    p[0] = -1 - nid;
    slot_t *dw = dir_w(sg, nid);
    if (!dw)
        return -1;
    dw[0] |= DIR_DEAD;
    st->tabs[ti].live--;
    st->nlive--;
    return 0;
}

int
op_remove(Sg *sg, int64_t nid)
{
    int ti;
    if (nid == 0) {
        PyErr_SetString(OrdbException, "Cannot delete SubgraphRoot (nid=0).");
        return -1;
    }
    if (!st_row(&sg->st, nid, &ti)) {
        PyObject *k = PyLong_FromLongLong(nid);
        PyErr_SetObject(PyExc_KeyError, k);
        Py_XDECREF(k);
        return -1;
    }
    if (node_drop(sg, nid, ti) < 0)
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
    if (st->tabs[ti].nt != nt) {
        // Type change: the node moves to another table.
        if (node_drop(sg, nid, ti) < 0)
            return -1;
        slot_t *p = node_place(sg, nt, nid);
        if (!p || row_store(sg, nt, p, node, nid) < 0
                || refs_adjust(sg, nt, p, 1) < 0
                || index_row(sg, nt, p, nid) < 0)
            return -1;
        return chk_add(tx, nid);
    }
    // Entries of indices whose (h, s) does not change stay valid.
    uint64_t oh[16];
    int64_t os[16];
    int oi[16];
    int nuse = nt->nuse < 16 ? nt->nuse : 16;
    Rec rec;
    if (nt->nuse) {
        if (rec_take(&rec, st, nt, cp, nid) < 0)
            return -1;
        for (int i = 0; i < nuse; i++)
            oi[i] = rec_hs(&rec, &nt->uses[i], &oh[i], &os[i]);
        rec_drop(&rec);
        for (int i = 0; i < nuse; i++)
            if (oi[i] < 0)
                return -1;
    }
    uint64_t row = DIR_ROW(st_dir(st, nid)[0]);
    slot_t *p = tab_row_w(sg, ti, row);
    if (!p)
        return -1;
    if (refs_adjust(sg, nt, p, -1) < 0 || boxed_drop_row(sg, nt, p, nid) < 0)
        return -1;
    recs_clear(p, nt->objmask, nt->rec, 1);
    if (row_store(sg, nt, p, node, nid) < 0 || refs_adjust(sg, nt, p, 1) < 0)
        return -1;
    if (nt->nuse && rec_take(&rec, st, nt, p, nid) < 0)
        return -1;
    int ret = 0;
    for (int i = 0; i < nt->nuse && ret == 0; i++) {
        IdxUse *u = &nt->uses[i];
        Ent e = {0, 0, nid};
        int r = rec_hs(&rec, u, &e.h, &e.s);
        if (r < 0) {
            ret = -1;
            break;
        }
        if (i < nuse && r == oi[i] && (r == 0 || (e.h == oh[i] && e.s == os[i])))
            continue;
        int xi = st_find_idx(st, u->index);
        if (xi < 0 && (xi = st_add_idx(st, u->index, u->combined)) < 0) {
            ret = -1;
            break;
        }
        if (i >= nuse || oi[i] == 1)
            st->idxs[xi].garbage++;
        if (r == 1 && idx_insert(sg, &st->idxs[xi], e) < 0)
            ret = -1;
    }
    if (nt->nuse)
        rec_drop(&rec);
    return ret < 0 ? -1 : chk_add(tx, nid);
}

// Inserts n rows of an all-integer node type from int64 columns (one
// buffer of n * width values per attribute).
int
op_insert_rows(Sg *sg, NType *nt, const int64_t *nids, Py_ssize_t n,
    const int64_t **cols)
{
    State *st = &sg->st;
    Txn *tx = sg->txn;
    Run *runs[16] = {NULL};
    int nuse = nt->nuse;
    if (nuse > 16) {
        PyErr_SetString(PyExc_TypeError, "too many indices for insert_array");
        return -1;
    }
    for (int i = 0; i < nuse; i++) {
        if (n > UINT32_MAX || !(runs[i] = run_new((uint32_t)n, 0)))
            goto fail;
    }
    for (Py_ssize_t r = 0; r < n; r++) {
        int64_t nid = nids[r];
        int ti;
        if (st_row(st, nid, &ti)) {
            PyErr_SetString(OrdbException, "Duplicate nid.");
            goto fail;
        }
        slot_t *p = node_place(sg, nt, nid);
        if (!p)
            goto fail;
        for (int i = 0; i < nt->nattr; i++) {
            const AttrInfo *ai = &nt->attrs[i];
            for (int k = 0; k < ai->width; k++) {
                int64_t v = cols[i][r * ai->width + k];
                if (v <= SLOT_BOXED) {
                    PyErr_SetString(PyExc_ValueError,
                        "array value outside the supported int64 range.");
                    goto fail;
                }
                p[ai->slot + k] = v;
            }
        }
        if (refs_adjust(sg, nt, p, 1) < 0)
            goto fail;
        if (nuse) {
            // Hashing all-integer rows runs no Python code, but a sortkey
            // that is not an attribute chain is called per row.
            Rec rec;
            if (rec_take(&rec, st, nt, p, nid) < 0)
                goto fail;
            int ok = 1;
            for (int i = 0; i < nuse && ok >= 0; i++) {
                Ent e = {0, 0, nid};
                ok = rec_hs(&rec, &nt->uses[i], &e.h, &e.s);
                if (ok == 1)
                    runs[i]->e[runs[i]->n++] = e;
            }
            rec_drop(&rec);
            if (ok < 0)
                goto fail;
        }
        if (chk_add(tx, nid) < 0)
            goto fail;
        txn_seen_nid(tx, nid);
    }
    for (int i = 0; i < nuse; i++) {
        Run *run = runs[i];
        runs[i] = NULL;
        int sorted = 1;
        for (uint32_t k = 1; k < run->n && sorted; k++)
            sorted = !ent_lt(&run->e[k], &run->e[k - 1]);
        if (!sorted)
            qsort(run->e, run->n, sizeof(Ent), ent_cmp);
        IdxUse *u = &nt->uses[i];
        int xi = st_find_idx(st, u->index);
        if (xi < 0 && (xi = st_add_idx(st, u->index, u->combined)) < 0) {
            run_decref(run);
            goto fail;
        }
        if (idx_add_run(st, &st->idxs[xi], run) < 0)
            goto fail;
    }
    return 0;
fail:
    for (int i = 0; i < nuse; i++)
        run_decref(runs[i]);
    return -1;
}

// ---------------------------------------------------------------------------
// Maintenance: compaction of tables and indices (no open transaction)
// ---------------------------------------------------------------------------

static int
nidrow_cmp(const void *a, const void *b)
{
    int64_t x = ((const NidRow *)a)->nid, y = ((const NidRow *)b)->nid;
    return x < y ? -1 : x > y;
}

// Live (nid, row) pairs of a table in ascending nid order.
NidRow *
tab_order(const Tab *t, uint64_t *n_out)
{
    NidRow *o = PyMem_Malloc(sizeof(NidRow) * (t->live + 1));
    if (!o) {
        PyErr_NoMemory();
        return NULL;
    }
    uint64_t n = 0;
    for (uint64_t r = 0; r < t->rows.count; r++) {
        const slot_t *p = vec_get(&t->rows, r);
        if (p[0] >= 0)
            o[n++] = (NidRow){p[0], r};
    }
    if (!t->sorted)
        qsort(o, n, sizeof(NidRow), nidrow_cmp);
    *n_out = n;
    return o;
}

// Rewrites a table without tombstones, in nid order.
int
tab_compact(Sg *sg, int ti)
{
    State *st = &sg->st;
    Tab *t = &st->tabs[ti];
    uint64_t tok = ++g_token;
    uint64_t n;
    NidRow *o = tab_order(t, &n);
    if (!o)
        return -1;
    Vec nv;
    vec_init(&nv, t->rows.rec, t->rows.objmask);
    int ret = -1;
    // Forget the tombstones (their rows go away).
    for (uint64_t r = 0; r < t->rows.count; r++) {
        const slot_t *p = vec_get(&t->rows, r);
        if (p[0] >= 0)
            continue;
        int64_t nid = -1 - p[0];
        const slot_t *d = st_dir(st, nid);
        if (d && (d[0] & DIR_DEAD) && DIR_TAB(d[0]) == ti
                && DIR_ROW(d[0]) == r) {
            slot_t *dw = vec_at_w(&st->dir, (uint64_t)nid, sg->tok, tok, 0);
            if (!dw)
                goto done;
            dw[0] = 0;
        }
    }
    for (uint64_t k = 0; k < n; k++) {
        const slot_t *p = vec_get(&t->rows, o[k].row);
        slot_t *q = vec_at_w(&nv, k, tok, tok, 1);
        if (!q)
            goto done;
        memcpy(q, p, sizeof(slot_t) * nv.rec);
        recs_incref(q, nv.objmask, nv.rec, 1);
        nv.count = k + 1;
        slot_t *dw = vec_at_w(&st->dir, (uint64_t)o[k].nid, sg->tok, tok, 0);
        if (!dw)
            goto done;
        dw[0] = DIR_LOC(ti, k);
    }
    Py_XDECREF(t->rows.root);
    t->rows = nv;
    nv.root = NULL;
    t->sorted = 1;
    t->last_nid = n ? o[n - 1].nid : -1;
    ret = 0;
done:
    Py_XDECREF(nv.root);
    PyMem_Free(o);
    return ret;
}

int
sg_maintain(Sg *sg, int freezing)
{
    State *st = &sg->st;
    for (int ti = 0; ti < st->ntab; ti++) {
        Tab *t = &st->tabs[ti];
        uint64_t dead = t->rows.count - t->live;
        if ((dead > t->live && dead >= 64) || (freezing && !t->sorted)) {
            if (tab_compact(sg, ti) < 0)
                return -1;
        }
    }
    for (int xi = 0; xi < st->nidx; xi++) {
        Idx *ix = &st->idxs[xi];
        uint64_t total = ix->tail_n;
        for (int r = 0; r < ix->nruns; r++)
            total += ix->runs[r]->n;
        if (ix->garbage >= 64 && ix->garbage * 2 > total) {
            if (idx_compact(st, ix) < 0)
                return -1;
        }
    }
    return 0;
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
    if (!sg->txn)
        return sg_maintain(sg, 0);
    return 0;
}
