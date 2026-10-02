// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Native core of ORDB (see docs/ref/ordb.rst and docs/dev/ordb_core.rst).
//
// A subgraph state consists of:
// - one table per node type: records of 8-byte slots, slot 0 is the nid
//   (tombstone: -1 - nid), followed by the attribute slots,
// - the nid directory: per nid the location (table, row) and the number of
//   LocalRefs pointing at it,
// - per index a set of sorted runs of (h, s, nid) plus an unsorted tail.
//   The index is a hint: removals and key changes leave stale entries,
//   every read verifies its candidates against the rows.
//
// Two storage engines share all of this (see _ordb_store.h): "paged"
// (persistent pages, a transaction keeps the previous state and abort
// swaps it back) and "flat" (contiguous blocks edited in place, abort
// replays an undo log).
//
// base.py owns the schema, the public classes and all error messages. On
// any failed constraint check, the core calls back into base.py, which
// repeats the check in Python and raises the exact exception.

#define PY_SSIZE_T_CLEAN
#define Py_LIMITED_API 0x030b0000 // abi3, Python 3.11+
#include <Python.h>
#include <structmember.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "_ordb_store.h"

#define SLOT_NONE INT64_MIN
#define SLOT_BOXED (INT64_MIN + 1)

#define ENGINE_PAGED 0
#define ENGINE_FLAT 1

#define K_INT 0 // int64 slot (int, LocalRef, ExternalRef)
#define K_IVEC 1 // width int64 slots (Vec2I, Rect4I)
#define K_OBJ 2 // Python object reference

#define REF_NONE 0
#define REF_LOCAL 1
#define REF_EXTERNAL 2

#define READ_PLAIN 0 // return the stored value
#define READ_LOCALREF 1 // return a cursor at the stored nid
#define READ_HOOK 2 // call attr.read_hook(value, cursor)

// How NodeTuple construction applies the attribute factory:
#define F_PLAIN 0 // Attr.factory with default and isinstance check, in C
#define F_REF 1 // LocalRef.factory / ExternalRef.factory, in C
#define F_PY 2 // call attr.factory(value)

#define CHK_UNIQUE 0
#define CHK_LOCAL 1
#define CHK_EXTERNAL 2

// Kinds of the check callback into base.py (_check_callback).
#define CB_PERMITTED 0
#define CB_NOTNULL 1
#define CB_LOCALREF 2
#define CB_EXTERNALREF 3
#define CB_UNIQUE 4
#define CB_DANGLING 5
#define CB_MISSING_ROOT 6

#define MAXKEY 4
#define MAXWIDTH 8 // slots of one attribute
#define H_NONE 0x9E3779B97F4A7C15ull

#define DIR_DEAD ((slot_t)1 << 62)
#define DIR_TAB(loc) ((int)(((loc) & ~DIR_DEAD) >> 40) - 1)
#define DIR_ROW(loc) ((uint64_t)((loc) & (((slot_t)1 << 40) - 1)))
#define DIR_LOC(ti, row) ((((slot_t)(ti) + 1) << 40) | (slot_t)(row))
#define DIR_MAX_GAP ((int64_t)1 << 24)

static PyObject *OrdbException;
static PyObject *g_check_cb; // base._check_callback(kind, sgu, nid, obj)
static PyObject *g_pathnode_mut, *g_pathnode_frz;
static PyObject *g_npath_index; // NPath.idx_path_of
static PyObject *g_npath_child_index; // NPath.idx_parent_name
static PyObject *QueryException;
static PyObject *str_ntype, *str_read_hook, *str_refcheck, *str_check_ref;

// ---------------------------------------------------------------------------
// NType: what the core knows about one node type
// ---------------------------------------------------------------------------

typedef struct {
    PyObject *name;
    PyObject *attr; // Attr object
    PyObject *vtype; // K_IVEC: value type (tuple subclass)
    PyObject *refcache; // refs: dict NType -> bool, results of attr.refcheck
    // ExternalRef: the target subgraph is held by the attribute of the start
    // node (ext_start: EXT_ROOT, EXT_SELF or the position of a LocalRef of
    // the node) that is one of ext_refs (SubgraphRef Attr objects). Without
    // ext_refs, the of_subgraph function subfn is called per node.
    PyObject *ext_refs;
    PyObject *subfn;
    int ext_start;
    PyObject *ftype; // F_PLAIN: values must be instances of ftype
    PyObject *fdefault; // F_PLAIN: value used for None
    int kind, width, slot; // slot: first slot in the record (>= 1)
    int optional, read_mode, ref_kind, fmode;
} AttrInfo;

typedef struct {
    PyObject *index;
    int nkey;
    int key[MAXKEY]; // attribute positions
    int sort; // attribute position of the sort value or -1
    PyObject *sortfn; // sortkey function (called with the NodeTuple) or NULL
    int unique, combined;
} IdxUse;

typedef struct {
    int kind, i;
} CheckItem;

typedef struct {
    PyObject_HEAD
    PyObject *tuple_cls; // X.Tuple
    PyObject *cursor_type; // X
    PyObject *cur_mut, *cur_frz; // X.Mutable, X.Frozen
    PyObject *permitted; // dict: root NType -> True
    int nattr, rec, nuse, ncheck;
    int ref_attr; // position of the attribute named 'ref' or -1
    uint64_t objmask;
    AttrInfo *attrs;
    IdxUse *uses;
    CheckItem *checks;
} NType;

static PyTypeObject *NType_Type;

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
static NType *
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

static inline IdxUse *
ntype_find_use(NType *nt, PyObject *index)
{
    for (int i = 0; i < nt->nuse; i++)
        if (nt->uses[i].index == index)
            return &nt->uses[i];
    return NULL;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

typedef struct {
    NType *nt;
    Vec rows;
    uint64_t live;
    int64_t last_nid; // nid of the last appended row
    int sorted; // rows are in ascending nid order
} Tab;

typedef struct {
    PyObject *index;
    Run *runs[MAXRUNS];
    int nruns;
    Run *tail;
    uint32_t tail_n;
    uint64_t garbage; // stale entries (estimate)
    int combined;
} Idx;

typedef struct {
    Vec dir; // records [loc, refs]
    Tab *tabs;
    int ntab;
    Idx *idxs;
    int nidx;
    PyObject *boxed; // dict {nid * 256 + attr position: value} or NULL
    uint64_t nlive;
    int64_t nid_start, nid_stop; // nid_alloc
} State;

static void
state_init(State *st, int flat)
{
    memset(st, 0, sizeof(State));
    vec_init(&st->dir, 2, 0, flat);
    st->nid_stop = (int64_t)1 << 32;
}

// With retain_vecs == 0, the copy borrows the blocks (flat engine: the
// pre-transaction state must not make the blocks look shared).
static int
state_copy(State *dst, const State *src, int retain_vecs)
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
        if (retain_vecs)
            Py_XINCREF(src->tabs[i].rows.root);
    }
    if (retain_vecs)
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

static void
state_release(State *st, int release_vecs)
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
        if (release_vecs)
            Py_XDECREF(tabs[i].rows.root);
        Py_DECREF(tabs[i].nt);
    }
    PyMem_Free(tabs);
    if (release_vecs)
        Py_XDECREF(dir_root);
    idxs_release(idxs, nidx);
    Py_XDECREF(boxed);
}

static inline int
st_find_tab(const State *st, const NType *nt)
{
    for (int i = 0; i < st->ntab; i++)
        if (st->tabs[i].nt == nt)
            return i;
    return -1;
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
    vec_init(&t->rows, nt->rec, nt->objmask, st->dir.flat);
    t->live = 0;
    t->last_nid = -1;
    t->sorted = 1;
    return st->ntab++;
}

static inline int
st_find_idx(const State *st, const PyObject *index)
{
    for (int i = 0; i < st->nidx; i++)
        if (st->idxs[i].index == index)
            return i;
    return -1;
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

static inline const slot_t *
st_dir(const State *st, int64_t nid)
{
    if (nid < 0 || (uint64_t)nid >= st->dir.count)
        return NULL;
    return vec_get(&st->dir, (uint64_t)nid);
}

// Record of a live node, or NULL.
static inline const slot_t *
st_row(const State *st, int64_t nid, int *ti)
{
    const slot_t *d = st_dir(st, nid);
    if (!d || d[0] <= 0 || (d[0] & DIR_DEAD))
        return NULL;
    *ti = DIR_TAB(d[0]);
    return vec_get(&st->tabs[*ti].rows, DIR_ROW(d[0]));
}

// ---------------------------------------------------------------------------
// Subgraph and transaction
// ---------------------------------------------------------------------------

typedef struct {
    int is_dir;
    int tab;
    uint64_t i;
    slot_t *old; // copy of the record, owning its object references
} UndoEnt;

typedef struct Txn {
    struct Txn *parent;
    State saved; // state at begin
    uint64_t tok;
    UndoEnt *undo; // flat engine only
    size_t nundo, capundo;
    int64_t *chk; // [start, end) nid ranges to check at commit
    size_t nchk, capchk;
    int64_t *rem; // removed nids
    size_t nrem, caprem;
    int64_t nid_gen, nid_max;
} Txn;

typedef struct Sg {
    PyObject_HEAD
    State st; // always the current state, including uncommitted changes
    Txn *txn; // innermost open transaction
    uint64_t tok; // lineage token: this subgraph may append to such blocks
    PyObject *root_cursor;
    PyObject *wire_hash; // memo slot used by base.py
    PyObject *arrays_memo; // memo slot used by arrays.py (frozen only)
    PyObject *weakreflist;
    Py_hash_t hash;
    unsigned long owner; // thread with open transactions
    char hash_valid, frozen;
    char writing; // a write operation of the core is in progress
} Sg;

static PyTypeObject *Sg_Type, *Node_Type, *Upd_Type, *AttrDesc_Type,
    *CurIter_Type;

typedef struct {
    PyObject_HEAD
    Sg *sg;
    Txn *tx;
    char commit, valid;
} Upd;

static PyObject *g_updater_cls; // base.SubgraphUpdater
static Upd *upd_open(Sg *sg);
static int upd_close(Upd *u, int ok);
static int sg_set1(Sg *sg, int64_t nid, NType *nt, int index, PyObject *value);
static PyObject *sg_add1(Sg *sg, PyObject *args);
static PyObject *sg_cursors(Sg *sg, PyObject *nids);
static PyObject *sg_child(Sg *sg, PyObject *args);

#define SG_FLAT(sg) ((sg)->st.dir.flat)

// Concurrency rules (see docs/dev/ordb_core.rst, "Threads"): one thread at a
// time may write a subgraph (the thread that opened the outermost updater),
// and no write may start while a write operation of the core is in progress
// (from a __hash__, a factory, a finalizer). Violations raise. Readers are
// not restricted; they never keep pointers into storage across Python code.
static int
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

static inline void
sg_write_end(Sg *sg)
{
    sg->writing = 0;
}

static int
undo_log(Txn *tx, int is_dir, int tab, uint64_t i, const slot_t *rec,
    uint32_t nslots, uint64_t objmask)
{
    if (tx->nundo == tx->capundo) {
        size_t cap = tx->capundo ? tx->capundo * 2 : 16;
        UndoEnt *u = PyMem_Realloc(tx->undo, sizeof(UndoEnt) * cap);
        if (!u) {
            PyErr_NoMemory();
            return -1;
        }
        tx->undo = u;
        tx->capundo = cap;
    }
    slot_t *old = PyMem_Malloc(sizeof(slot_t) * nslots);
    if (!old) {
        PyErr_NoMemory();
        return -1;
    }
    memcpy(old, rec, sizeof(slot_t) * nslots);
    recs_incref(old, objmask, nslots, 1);
    tx->undo[tx->nundo++] = (UndoEnt){is_dir, tab, i, old};
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
    uint64_t i = (uint64_t)nid;
    if (i >= dir->count) {
        slot_t *p;
        if (dir->flat) {
            p = vec_at_w(dir, i, sg->tok, txtok, 1);
            if (!p)
                return NULL;
            FBlock *b = (FBlock *)dir->root;
            memset(b->data + dir->count * 2, 0,
                sizeof(slot_t) * 2 * (i + 1 - dir->count));
        } else {
            // Leaves owned by this subgraph may hold leftovers of aborted
            // transactions behind count: zero all existing leaves in the gap.
            uint64_t j = dir->count;
            p = NULL;
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
        }
        dir->count = i + 1;
        return p;
    }
    int append = tx && i >= tx->saved.dir.count;
    if (dir->flat && tx && !append) {
        if (undo_log(tx, 1, 0, i, vec_get(dir, i), 2, 0) < 0)
            return NULL;
    }
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
    if (v->flat && tx && !append) {
        if (undo_log(tx, 0, ti, row, vec_get(v, row), v->rec, v->objmask) < 0)
            return NULL;
    }
    return vec_at_w(v, row, sg->tok, tx ? tx->tok : 0, append);
}

// Appends a record and returns it with its object slots cleared.
static slot_t *
tab_append(Sg *sg, int ti)
{
    Vec *v = &sg->st.tabs[ti].rows;
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

static PyObject *
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
static PyObject *
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

// A record taken out of storage: a copy of its slots that owns references
// to its objects (object slots and boxed values). Code that may run Python
// (hashing, comparing, allocating) works on a Rec, never on a pointer into
// storage, which that Python code may invalidate.
typedef struct {
    const NType *nt;
    int64_t nid;
    slot_t s[64];
    PyObject *box[64]; // per attribute: boxed value or NULL
} Rec;

static void
rec_drop(Rec *r)
{
    const NType *nt = r->nt;
    recs_clear(r->s, nt->objmask, nt->rec, 1);
    for (int i = 0; i < nt->nattr; i++)
        Py_CLEAR(r->box[i]);
}

// Copies a stored record into r (no Python code runs in between).
static int
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

static PyObject *
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

static inline uint64_t
mix(uint64_t h, uint64_t x)
{
    h = (h ^ x) * 0xFF51AFD7ED558CCDull;
    return h ^ (h >> 33);
}

static inline uint64_t
mix_ints(int n, const slot_t *x)
{
    uint64_t h = 0xC2B2AE3D27D4EB4Full + (uint64_t)n;
    for (int k = 0; k < n; k++)
        h = mix(h, (uint64_t)x[k]);
    return h;
}

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
static int
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
static int
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
static int
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
static int
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
static int
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
// Index
// ---------------------------------------------------------------------------

// An entry is valid if its node is alive and still has this (h, s).
static int
ent_valid(const State *st, const PyObject *index, const Ent *e)
{
    int ti;
    const slot_t *p = st_row(st, e->nid, &ti);
    if (!p)
        return 0;
    NType *nt = st->tabs[ti].nt;
    IdxUse *u = ntype_find_use(nt, (PyObject *)index);
    if (!u)
        return 0;
    uint64_t h;
    int64_t s;
    Rec rec;
    if (rec_take(&rec, st, nt, p, e->nid) < 0) {
        PyErr_Clear();
        return 1; // cannot tell: keep the entry
    }
    int r = rec_hs(&rec, u, &h, &s);
    rec_drop(&rec);
    if (r < 0) {
        PyErr_Clear();
        return 1;
    }
    return r == 1 && h == e->h && s == e->s;
}

// Merges runs of similar size. When many entries are stale, merging
// drops the stale ones.
static int
idx_cascade(const State *st, Idx *ix)
{
    while (ix->nruns >= 2) {
        Run *a = ix->runs[ix->nruns - 2], *b = ix->runs[ix->nruns - 1];
        if (a->n > 2 * b->n && ix->nruns < MAXRUNS - 1)
            break;
        Run *m = run_new(a->n + b->n, 0);
        if (!m)
            return -1;
        int filter = ix->garbage >= 32
            && ix->garbage * 2 >= (uint64_t)a->n + b->n;
        uint64_t dropped = 0;
        uint32_t i = 0, j = 0, k = 0;
        while (i < a->n || j < b->n) {
            const Ent *e;
            if (j >= b->n || (i < a->n && !ent_lt(&b->e[j], &a->e[i])))
                e = &a->e[i++];
            else
                e = &b->e[j++];
            if (k > 0 && m->e[k - 1].h == e->h && m->e[k - 1].s == e->s
                    && m->e[k - 1].nid == e->nid)
                continue;
            if (filter && !ent_valid(st, ix->index, e)) {
                dropped++;
                continue;
            }
            m->e[k++] = *e;
        }
        m->n = k;
        ix->garbage -= dropped < ix->garbage ? dropped : ix->garbage;
        run_decref(a);
        run_decref(b);
        ix->nruns--;
        ix->runs[ix->nruns - 1] = m;
    }
    return 0;
}

// Adds a sorted run (steals the reference).
static int
idx_add_run(const State *st, Idx *ix, Run *r)
{
    if (r->n == 0) {
        run_decref(r);
        return 0;
    }
    ix->runs[ix->nruns++] = r;
    return idx_cascade(st, ix);
}

static int
idx_insert(Sg *sg, Idx *ix, Ent e)
{
    Run *t = ix->tail;
    if (!t) {
        t = ix->tail = run_new(TAIL_CAP, sg->tok);
        if (!t)
            return -1;
        ix->tail_n = 0;
    } else if (t->owner != sg->tok) {
        // The tail belongs to another subgraph: continue on a copy.
        Run *c = run_new(TAIL_CAP, sg->tok);
        if (!c)
            return -1;
        memcpy(c->e, t->e, sizeof(Ent) * ix->tail_n);
        run_decref(t);
        t = ix->tail = c;
    }
    // Entries behind tail_n are invisible to all other snapshots.
    t->e[ix->tail_n++] = e;
    if (ix->tail_n < TAIL_CAP)
        return 0;
    Run *r = run_new(TAIL_CAP, 0);
    if (!r)
        return -1;
    memcpy(r->e, t->e, sizeof(Ent) * TAIL_CAP);
    r->n = TAIL_CAP;
    qsort(r->e, r->n, sizeof(Ent), ent_cmp);
    run_decref(t);
    ix->tail = NULL;
    ix->tail_n = 0;
    return idx_add_run(&sg->st, ix, r);
}

// Rewrites an index as one run without stale entries.
static int
idx_compact(const State *st, Idx *ix)
{
    uint64_t total = ix->tail_n;
    for (int r = 0; r < ix->nruns; r++)
        total += ix->runs[r]->n;
    Run *m = run_new((uint32_t)total, 0);
    if (!m)
        return -1;
    uint32_t k = 0;
    for (int r = 0; r < ix->nruns; r++) {
        memcpy(m->e + k, ix->runs[r]->e, sizeof(Ent) * ix->runs[r]->n);
        k += ix->runs[r]->n;
    }
    if (ix->tail) {
        memcpy(m->e + k, ix->tail->e, sizeof(Ent) * ix->tail_n);
        k += ix->tail_n;
    }
    qsort(m->e, k, sizeof(Ent), ent_cmp);
    uint32_t n = 0;
    for (uint32_t i = 0; i < k; i++) {
        const Ent *e = &m->e[i];
        if (n > 0 && m->e[n - 1].h == e->h && m->e[n - 1].s == e->s
                && m->e[n - 1].nid == e->nid)
            continue;
        if (!ent_valid(st, ix->index, e))
            continue;
        m->e[n++] = *e;
    }
    m->n = n;
    for (int r = 0; r < ix->nruns; r++)
        run_decref(ix->runs[r]);
    run_decref(ix->tail);
    ix->tail = NULL;
    ix->tail_n = 0;
    ix->nruns = 0;
    ix->garbage = 0;
    if (n)
        ix->runs[ix->nruns++] = m;
    else
        run_decref(m);
    return 0;
}

typedef struct {
    Ent *e;
    size_t n, cap;
    Ent stack[32];
} EntBuf;

static int
entbuf_push(EntBuf *b, const Ent *e)
{
    if (b->n == b->cap) {
        size_t cap = b->cap * 2;
        Ent *ne = PyMem_Malloc(sizeof(Ent) * cap);
        if (!ne) {
            PyErr_NoMemory();
            return -1;
        }
        memcpy(ne, b->e, sizeof(Ent) * b->n);
        if (b->e != b->stack)
            PyMem_Free(b->e);
        b->e = ne;
        b->cap = cap;
    }
    b->e[b->n++] = *e;
    return 0;
}

static void
entbuf_free(EntBuf *b)
{
    if (b->e != b->stack)
        PyMem_Free(b->e);
}

// All entries with hash h (stale ones included), ordered by (s, nid).
static int
idx_candidates(const Idx *ix, uint64_t h, EntBuf *b)
{
    b->e = b->stack;
    b->n = 0;
    b->cap = 32;
    for (int r = 0; r < ix->nruns; r++) {
        const Run *run = ix->runs[r];
        for (uint32_t i = run_lower_bound(run, h);
                i < run->n && run->e[i].h == h; i++)
            if (entbuf_push(b, &run->e[i]) < 0)
                return -1;
    }
    for (uint32_t i = 0; i < ix->tail_n; i++)
        if (ix->tail->e[i].h == h && entbuf_push(b, &ix->tail->e[i]) < 0)
            return -1;
    if (b->n > 1)
        qsort(b->e, b->n, sizeof(Ent), ent_cmp_sn);
    return 0;
}

// nids of the nodes with the given key, ordered by (sort value, nid).
static PyObject *
st_query(const State *st, PyObject *index, PyObject *key)
{
    PyObject *ret = PyList_New(0);
    if (!ret)
        return NULL;
    int xi = st_find_idx(st, index);
    if (xi < 0)
        return ret;
    const Idx *ix = &st->idxs[xi];
    uint64_t h;
    int r = key_hash(key, ix->combined, &h);
    if (r < 0)
        goto fail;
    if (r == 0)
        return ret;
    EntBuf b;
    if (idx_candidates(ix, h, &b) < 0) {
        entbuf_free(&b);
        goto fail;
    }
    for (size_t i = 0; i < b.n; i++) {
        const Ent *e = &b.e[i];
        if (i > 0 && b.e[i - 1].s == e->s && b.e[i - 1].nid == e->nid)
            continue;
        int ti;
        const slot_t *p = st_row(st, e->nid, &ti);
        if (!p)
            continue;
        NType *nt = st->tabs[ti].nt;
        IdxUse *u = ntype_find_use(nt, index);
        if (!u)
            continue;
        if (u->combined && PyTuple_Size(key) != u->nkey)
            continue;
        uint64_t rh;
        int64_t rs;
        Rec rec;
        if (rec_take(&rec, st, nt, p, e->nid) < 0)
            goto fail_buf;
        int ok = rec_hs(&rec, u, &rh, &rs);
        if (ok == 1 && (rh != h || rs != e->s))
            ok = 0;
        for (int k = 0; k < u->nkey && ok == 1; k++) {
            PyObject *comp = u->combined ? PyTuple_GetItem(key, k) : key;
            ok = rec_eq_pyval(&rec, u->key[k], comp);
        }
        rec_drop(&rec);
        if (ok < 0)
            goto fail_buf;
        if (ok == 0)
            continue;
        PyObject *nid = PyLong_FromLongLong(e->nid);
        if (!nid || PyList_Append(ret, nid) < 0) {
            Py_XDECREF(nid);
            goto fail_buf;
        }
        Py_DECREF(nid);
    }
    entbuf_free(&b);
    return ret;
fail_buf:
    entbuf_free(&b);
fail:
    Py_DECREF(ret);
    return NULL;
}

// Is there another live node with the same key as the record r?
static int
unique_violated(const State *st, const Rec *r, const IdxUse *u)
{
    uint64_t h;
    int64_t s;
    int ok = rec_hs(r, u, &h, &s);
    if (ok <= 0)
        return ok;
    int xi = st_find_idx(st, u->index);
    if (xi < 0)
        return 0;
    EntBuf b;
    if (idx_candidates(&st->idxs[xi], h, &b) < 0) {
        entbuf_free(&b);
        return -1;
    }
    int found = 0;
    for (size_t i = 0; i < b.n && found == 0; i++) {
        int64_t other = b.e[i].nid;
        if (other == r->nid)
            continue;
        int ti;
        const slot_t *q = st_row(st, other, &ti);
        if (!q)
            continue;
        NType *ont = st->tabs[ti].nt;
        IdxUse *ou = ntype_find_use(ont, u->index);
        if (!ou || ou->nkey != u->nkey)
            continue;
        Rec orec;
        if (rec_take(&orec, st, ont, q, other) < 0) {
            found = -1;
            break;
        }
        uint64_t oh;
        int64_t os;
        ok = rec_hs(&orec, ou, &oh, &os);
        if (ok == 1 && oh != h)
            ok = 0;
        for (int k = 0; k < u->nkey && ok == 1; k++)
            ok = rec_eq(r, u->key[k], &orec, ou->key[k]);
        rec_drop(&orec);
        found = ok;
    }
    entbuf_free(&b);
    return found;
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

static int
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

static int
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

static int
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
static int
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
            // All-integer rows: hashing runs no Python code.
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

typedef struct {
    int64_t nid;
    uint64_t row;
} NidRow;

static int
nidrow_cmp(const void *a, const void *b)
{
    int64_t x = ((const NidRow *)a)->nid, y = ((const NidRow *)b)->nid;
    return x < y ? -1 : x > y;
}

// Live (nid, row) pairs of a table in ascending nid order.
static NidRow *
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
static int
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
    vec_init(&nv, t->rows.rec, t->rows.objmask, t->rows.flat);
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

static int
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

static Txn *
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
    if (state_copy(&tx->saved, &sg->st, !SG_FLAT(sg)) < 0) {
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
    for (size_t i = 0; i < tx->nundo; i++)
        PyMem_Free(tx->undo[i].old);
    PyMem_Free(tx->undo);
    PyMem_Free(tx->chk);
    PyMem_Free(tx->rem);
    PyMem_Free(tx);
}

static void
undo_release(Sg *sg, Txn *tx)
{
    State *st = &sg->st;
    for (size_t i = 0; i < tx->nundo; i++) {
        UndoEnt *u = &tx->undo[i];
        if (!u->is_dir && u->tab < st->ntab) {
            Vec *v = &st->tabs[u->tab].rows;
            recs_clear(u->old, v->objmask, v->rec, 1);
        }
    }
}

static void
txn_abort(Sg *sg, Txn *tx)
{
    State *st = &sg->st;
    sg->txn = tx->parent;
    sg->hash_valid = 0;
    if (!SG_FLAT(sg)) {
        state_release(st, 1);
        *st = tx->saved;
        txn_free(tx);
        return;
    }
    // Flat: restore the overwritten records (newest first), then the
    // counts. Blocks written in this transaction are private, so they are
    // written directly.
    for (size_t i = tx->nundo; i-- > 0;) {
        UndoEnt *u = &tx->undo[i];
        Vec *v = u->is_dir ? &st->dir : &st->tabs[u->tab].rows;
        slot_t *p = ((FBlock *)v->root)->data + u->i * v->rec;
        recs_clear(p, v->objmask, v->rec, 1);
        memcpy(p, u->old, sizeof(slot_t) * v->rec); // takes the references
    }
    for (int ti = 0; ti < st->ntab; ti++) {
        Tab *t = &st->tabs[ti];
        if (ti < tx->saved.ntab) {
            const Tab *s = &tx->saved.tabs[ti];
            t->rows.count = s->rows.count;
            t->live = s->live;
            t->last_nid = s->last_nid;
            t->sorted = s->sorted;
        } else {
            Py_XDECREF(t->rows.root);
            Py_DECREF(t->nt);
        }
    }
    st->ntab = tx->saved.ntab;
    st->dir.count = tx->saved.dir.count;
    idxs_release(st->idxs, st->nidx);
    st->idxs = tx->saved.idxs;
    st->nidx = tx->saved.nidx;
    PyObject *boxed = st->boxed;
    st->boxed = tx->saved.boxed;
    Py_XDECREF(boxed);
    st->nlive = tx->saved.nlive;
    st->nid_start = tx->saved.nid_start;
    for (int i = 0; i < tx->saved.ntab; i++)
        Py_DECREF(tx->saved.tabs[i].nt);
    PyMem_Free(tx->saved.tabs);
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

static Sg *call_subfn(PyObject *fn, Sg *sg, int64_t nid);

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

// Deferred constraint checks of a transaction. The core only decides
// "fine" on its fast paths; everything else goes to base.py, which raises.
static int
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
                            target = subref_target(st, 0, ai->ext_refs);
                            if (target && next < 8) {
                                ext_attr[next] = ai;
                                ext_sg[next++] = target;
                            }
                        }
                    } else {
                        int64_t start = ai->ext_start == EXT_SELF ? nid
                            : p[nt->attrs[ai->ext_start].slot];
                        target = subref_target(st, start, ai->ext_refs);
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

static int
txn_commit(Sg *sg, Txn *tx)
{
    State *st = &sg->st;
    st->nid_start = tx->nid_max + 1;
    sg->txn = tx->parent;
    sg->hash_valid = 0;
    if (SG_FLAT(sg)) {
        if (tx->parent) {
            // The parent must be able to undo what this transaction did.
            Txn *pa = tx->parent;
            for (size_t i = 0; i < tx->nundo; i++) {
                UndoEnt *u = &tx->undo[i];
                uint64_t seen = u->is_dir ? pa->saved.dir.count
                    : u->tab < pa->saved.ntab
                        ? pa->saved.tabs[u->tab].rows.count : 0;
                Vec *v = u->is_dir ? &st->dir : &st->tabs[u->tab].rows;
                if (u->i < seen) {
                    if (undo_log(pa, u->is_dir, u->tab, u->i, u->old, v->rec,
                            v->objmask) < 0)
                        PyErr_Clear(); // out of memory: parent abort is lossy
                }
            }
        }
        undo_release(sg, tx);
        state_release(&tx->saved, 0);
    } else {
        state_release(&tx->saved, 1);
    }
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

// ---------------------------------------------------------------------------
// Cursor (Node base class)
// ---------------------------------------------------------------------------

#define NPATH_NONE (-1)
#define NPATH_UNRESOLVED (-2)

typedef struct {
    PyObject_HEAD
    Sg *sg;
    int64_t nid; // -1: no node (PathNode)
    int64_t npath; // nid of the NPath, NPATH_NONE or NPATH_UNRESOLVED
} NodeObj;

static PyObject *sg_cursor(Sg *sg, int64_t nid, int64_t npath);

// Calls an of_subgraph function for the node nid. Returns the subgraph of
// the SubgraphRoot it returns (new reference), NULL with no error if it
// returned something else, NULL with error on failure.
static Sg *
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

static PyObject *
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

static PyObject *
key_error_nid(int64_t nid)
{
    PyObject *k = PyLong_FromLongLong(nid);
    if (k) {
        PyErr_SetObject(PyExc_KeyError, k);
        Py_DECREF(k);
    }
    return NULL;
}

static PyObject *
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

static int
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

// Cursors of one subgraph are ordered by (nid, npath) like the tuples
// (subgraph, nid, npath) they used to be; code relies on this, e.g. as a
// tie breaker when sorting (key, cursor) pairs.
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
            Py_RETURN_NOTIMPLEMENTED;
    }
    if (node_resolve_npath(x) < 0 || node_resolve_npath(y) < 0)
        return NULL;
    int c = x->nid != y->nid ? (x->nid < y->nid ? -1 : 1)
        : x->npath != y->npath ? (x->npath < y->npath ? -1 : 1) : 0;
    Py_RETURN_RICHCOMPARE(c, 0, op);
}

static PyObject *
node_richcompare(PyObject *a, PyObject *b, int op)
{
    if (!PyObject_TypeCheck(b, Node_Type))
        Py_RETURN_NOTIMPLEMENTED;
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

// -- NodeTuple construction -------------------------------------------------

static PyObject *str_factory;

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
    PyObject *t = PyType_GenericAlloc(tc, nt->nattr);
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
    return t;
fail:
    Py_DECREF(t);
    return NULL;
}

// NodeTuple.__new__(cls, **values)
static PyObject *
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
    int ti;
    const slot_t *p = st_row(st, c->nid, &ti);
    if (!p)
        return key_error_nid(c->nid);
    NType *nt = d->nt;
    if (st->tabs[ti].nt != nt) {
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

// ---------------------------------------------------------------------------
// Subgraph
// ---------------------------------------------------------------------------

static PyObject *
sg_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"engine", NULL};
    int engine = ENGINE_PAGED;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|i", kwlist, &engine))
        return NULL;
    Sg *sg = (Sg *)PyType_GenericAlloc(type, 0);
    if (!sg)
        return NULL;
    state_init(&sg->st, engine == ENGINE_FLAT);
    sg->tok = ++g_token;
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
    for (int i = 0; i < st->nidx; i++)
        Py_VISIT(st->idxs[i].index);
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
        state_release(&sg->st, 1);
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
    state_release(&sg->st, 1);
    obj_free(sg);
}

static int
arg_nid(PyObject *o, int64_t *nid)
{
    if (!PyLong_Check(o)) {
        PyErr_SetString(PyExc_TypeError, "nid must be int");
        return -1;
    }
    int ovf;
    *nid = PyLong_AsLongLongAndOverflow(o, &ovf);
    if (ovf)
        *nid = -1; // no such node
    return 0;
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
    if (!PyLong_Check(arg))
        Py_RETURN_FALSE;
    int ovf;
    long long nid = PyLong_AsLongLongAndOverflow(arg, &ovf);
    return PyBool_FromLong(!ovf && st_row(&sg->st, nid, &ti) != NULL);
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

// nids(): all nids; nids(X.Tuple): the nids of one node type. Ascending.
static PyObject *
sg_nids(Sg *sg, PyObject *args)
{
    PyObject *cls = Py_None;
    if (!PyArg_ParseTuple(args, "|O", &cls))
        return NULL;
    const State *st = &sg->st;
    if (cls == Py_None) {
        PyObject *l = PyList_New((Py_ssize_t)st->nlive);
        if (!l)
            return NULL;
        Py_ssize_t k = 0;
        for (uint64_t i = 0; i < st->dir.count; i++) {
            const slot_t *d = vec_get(&st->dir, i);
            if (!d || d[0] <= 0 || (d[0] & DIR_DEAD))
                continue;
            PyObject *x = PyLong_FromUnsignedLongLong(i);
            if (!x) {
                Py_DECREF(l);
                return NULL;
            }
            PyList_SetItem(l, k++, x);
        }
        return l;
    }
    NType *nt = ntype_of_cls(cls);
    if (!nt)
        return NULL;
    int ti = st_find_tab(st, nt);
    if (ti < 0)
        return PyList_New(0);
    uint64_t n;
    NidRow *o = tab_order(&st->tabs[ti], &n);
    if (!o)
        return NULL;
    PyObject *l = PyList_New((Py_ssize_t)n);
    for (uint64_t k = 0; l && k < n; k++) {
        PyObject *x = PyLong_FromLongLong(o[k].nid);
        if (!x) {
            Py_CLEAR(l);
            break;
        }
        PyList_SetItem(l, k, x);
    }
    PyMem_Free(o);
    return l;
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
    return PyUnicode_FromString(SG_FLAT(sg) ? "flat" : "paged");
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
    if (!sg->frozen) {
        if (sg_write_begin(sg) < 0)
            return NULL;
        int r = sg_maintain(sg, frozen);
        sg_write_end(sg);
        if (r < 0)
            return NULL;
    }
    Sg *n = (Sg *)PyType_GenericAlloc((PyTypeObject *)cls, 0);
    if (!n)
        return NULL;
    state_init(&n->st, SG_FLAT(sg));
    n->wire_hash = Py_NewRef(Py_None);
    n->arrays_memo = Py_NewRef(Py_None);
    if (state_copy(&n->st, &sg->st, 1) < 0) {
        state_init(&n->st, SG_FLAT(sg));
        Py_DECREF(n);
        return NULL;
    }
    n->tok = ++g_token;
    n->frozen = (char)frozen;
    return (PyObject *)n;
}

static PyObject *
sg_set_nid_start(Sg *sg, PyObject *arg)
{
    long long v = PyLong_AsLongLong(arg);
    if (v == -1 && PyErr_Occurred())
        return NULL;
    if (sg->frozen || sg_no_txn(sg, "change nid_alloc of") < 0)
        return NULL;
    sg->st.nid_start = v;
    sg->hash_valid = 0;
    Py_RETURN_NONE;
}

static PyObject *
sg_compact(Sg *sg, PyObject *noarg)
{
    if (sg_no_txn(sg, "compact") < 0 || sg_write_begin(sg) < 0)
        return NULL;
    int r = 0;
    for (int ti = 0; ti < sg->st.ntab && r == 0; ti++)
        r = tab_compact(sg, ti);
    for (int xi = 0; xi < sg->st.nidx && r == 0; xi++)
        r = idx_compact(&sg->st, &sg->st.idxs[xi]);
    sg_write_end(sg);
    if (r < 0)
        return NULL;
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
            : ai->kind == K_INT ? (uint64_t)s[0] : mix_ints(ai->width, s));
    }
    return h;
}

// Content hash: order-independent sum of record hashes plus nid_alloc.
// Tables are looked up again for every row: hashing values can run Python
// code, during which another thread may write to a mutable subgraph.
static PyObject *
sg_content_hash(Sg *sg, PyObject *noarg)
{
    if (sg->hash_valid)
        return PyLong_FromSsize_t(sg->hash);
    const State *st = &sg->st;
    uint64_t acc = mix((uint64_t)st->nid_start, (uint64_t)st->nid_stop);
    for (int ti = 0; ti < st->ntab; ti++) {
        for (uint64_t r = 0; ti < st->ntab && r < st->tabs[ti].rows.count; r++) {
            NType *nt = st->tabs[ti].nt;
            const slot_t *p = vec_get(&st->tabs[ti].rows, r);
            if (p[0] < 0)
                continue;
            if (!nt->objmask && !st->boxed) {
                acc += plain_row_hash(nt, p);
                continue;
            }
            Rec rec;
            if (rec_take(&rec, st, nt, p, p[0]) < 0)
                return NULL;
            uint64_t h = mix((uint64_t)(uintptr_t)nt->tuple_cls, (uint64_t)p[0]);
            int ok = 0;
            for (int i = 0; i < nt->nattr && ok >= 0; i++) {
                uint64_t hc = H_NONE;
                ok = rec_slot_hash(&rec, i, &hc);
                h = mix(h, hc);
            }
            rec_drop(&rec);
            if (ok < 0)
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
                && sa->tabs[ti].rows.count == sb->tabs[tj].rows.count
                && sa->boxed == sb->boxed)
            continue; // shared storage
        for (uint64_t r = 0; ti < sa->ntab && r < sa->tabs[ti].rows.count; r++) {
            const slot_t *p = vec_get(&sa->tabs[ti].rows, r);
            if (p[0] < 0)
                continue;
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
    uint64_t n = 0;
    NidRow *o = NULL;
    if (ti >= 0 && !(o = tab_order(&st->tabs[ti], &n)))
        return NULL;
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
    uint64_t m = 0;
    for (uint64_t k = 0; k < n; k++) {
        const slot_t *p = vec_get(&st->tabs[ti].rows, o[k].row);
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
    PyMem_Free(o);
    Py_XDECREF(nids);
    Py_XDECREF(cols);
    return ret;
}

// Size of the subgraph object with its private arrays and its share of
// the index runs (bytes / number of sharing states). Blocks are separate
// objects, reachable through gc.get_referents.
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
    for (int i = 0; i < st->nidx; i++) {
        const Idx *ix = &st->idxs[i];
        for (int r = 0; r < ix->nruns; r++)
            n += (double)(offsetof(Run, e) + sizeof(Ent) * ix->runs[r]->n)
                / ix->runs[r]->rc;
        if (ix->tail)
            n += (double)(offsetof(Run, e) + sizeof(Ent) * TAIL_CAP)
                / ix->tail->rc;
    }
    return PyLong_FromDouble(n);
}

// Storage statistics for tests and benchmarks.
static PyObject *
sg_stats(Sg *sg, PyObject *noarg)
{
    const State *st = &sg->st;
    uint64_t rows = 0, entries = 0, runs = 0, garbage = 0;
    for (int i = 0; i < st->ntab; i++)
        rows += st->tabs[i].rows.count;
    for (int i = 0; i < st->nidx; i++) {
        const Idx *ix = &st->idxs[i];
        runs += ix->nruns;
        entries += ix->tail_n;
        garbage += ix->garbage;
        for (int r = 0; r < ix->nruns; r++)
            entries += ix->runs[r]->n;
    }
    return Py_BuildValue("{s:K,s:K,s:i,s:i,s:K,s:K,s:K,s:K}",
        "nodes", (unsigned long long)st->nlive,
        "rows", (unsigned long long)rows,
        "tables", st->ntab, "indices", st->nidx,
        "index_entries", (unsigned long long)entries,
        "index_runs", (unsigned long long)runs,
        "index_garbage", (unsigned long long)garbage,
        "directory", (unsigned long long)st->dir.count);
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
    {"_cursors", (PyCFunction)sg_cursors, METH_O, NULL},
    {"_child", (PyCFunction)sg_child, METH_VARARGS, NULL},
    {"_set_nid_start", (PyCFunction)sg_set_nid_start, METH_O, NULL},
    {"_compact", (PyCFunction)sg_compact, METH_NOARGS, NULL},
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

// ---------------------------------------------------------------------------
// Updater
// ---------------------------------------------------------------------------

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
    if (u->tx && u->sg && !u->sg->writing) {
        // Abandoned without __exit__: undo it and everything opened after.
        // (During a write operation of the core it stays open instead.)
        u->sg->owner = PyThread_get_thread_ident();
        u->sg->writing = 1;
        while (u->sg->txn && u->sg->txn != u->tx)
            txn_abort(u->sg, u->sg->txn);
        if (u->sg->txn == u->tx)
            txn_abort(u->sg, u->tx);
        u->sg->writing = 0;
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
    u->tx = txn_begin(u->sg);
    if (!u->tx)
        return NULL;
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
    Sg *sg = u->sg;
    if (sg->txn != tx) {
        PyErr_SetString(OrdbException,
            "SubgraphUpdaters must be closed in reverse order of opening.");
        return NULL;
    }
    if (upd_finish(u, exc_type == Py_None && u->commit) < 0)
        return NULL;
    Py_RETURN_FALSE;
}

static int
upd_usable(Upd *u)
{
    if (!u->valid || !u->tx) {
        PyErr_SetString(PyExc_TypeError, "Invalid SubgraphUpdater.");
        return -1;
    }
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
    return 0;
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
    int r = op_add(u->sg, nid, node);
    sg_write_end(u->sg);
    if (r < 0)
        return NULL;
    return PyLong_FromLongLong(nid);
}

static PyObject *
upd_remove_nid(Upd *u, PyObject *arg)
{
    if (upd_usable(u) < 0)
        return NULL;
    long long nid = PyLong_AsLongLong(arg);
    if (nid == -1 && PyErr_Occurred())
        return NULL;
    if (sg_write_begin(u->sg) < 0)
        return NULL;
    int r = op_remove(u->sg, nid);
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
    int r = op_update(u->sg, nid, node);
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
    if (upd_usable(u) < 0)
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
    if (sg_write_begin(u->sg) < 0)
        goto done;
    if (op_insert_rows(u->sg, nt, nb.buf, n, cols) == 0)
        ret = Py_NewRef(Py_None);
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
    return PyLong_FromLongLong(u->tx->nid_gen);
}

static PyObject *
upd_get_nid_max(Upd *u, void *closure)
{
    if (!u->tx) {
        PyErr_SetString(PyExc_TypeError, "Invalid SubgraphUpdater.");
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
    {"update", (PyCFunction)(void (*)(void))upd_update, METH_VARARGS | METH_KEYWORDS, NULL},
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
static PyObject *
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

// -- single-node transactions without Python-level updater -----------------

static Upd *
upd_open(Sg *sg)
{
    PyTypeObject *t = g_updater_cls ? (PyTypeObject *)g_updater_cls : Upd_Type;
    Upd *u = (Upd *)PyType_GenericAlloc(t, 0);
    if (!u)
        return NULL;
    u->sg = (Sg *)Py_NewRef((PyObject *)sg);
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

// Copy of a NodeTuple with one attribute value replaced.
static PyObject *
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
    PyObject *t = PyType_GenericAlloc(tc, nt->nattr);
    if (!t) {
        Py_DECREF(v);
        return NULL;
    }
    for (int i = 0; i < nt->nattr; i++)
        PyTuple_SetItem(t, i, i == index ? v
            : Py_NewRef(PyTuple_GetItem(node, i)));
    return t;
}

// _add1(node[, ref]): inserts the NodeTuple node (with its attribute
// 'ref' set to ref, if given) in a transaction of its own. Returns the
// cursor of the new node. Backs '%' and Subgraph.add.
static PyObject *
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
    Upd *u = upd_open(sg);
    if (!u) {
        Py_DECREF(node);
        return NULL;
    }
    Txn *tx = u->tx;
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

// Sets attribute index (of node type nt) of node nid in a transaction of
// its own. Backs attribute assignment on cursors.
static int
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

// ---------------------------------------------------------------------------
// Module
// ---------------------------------------------------------------------------

// _setup(**objects): hands base.py's classes and callbacks to the core.
static PyObject *
mod_setup(PyObject *m, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"OrdbException", "QueryException",
        "check_callback", "updater_class", "pathnode_mutable",
        "pathnode_frozen", "npath_index", "npath_child_index", NULL};
    PyObject *v[8] = {NULL};
    PyObject **g[8] = {&OrdbException, &QueryException, &g_check_cb,
        &g_updater_cls, &g_pathnode_mut, &g_pathnode_frz, &g_npath_index,
        &g_npath_child_index};
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|OOOOOOOO", kwlist, &v[0],
            &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7]))
        return NULL;
    for (int i = 0; i < 8; i++) {
        if (v[i]) {
            PyObject *old = *g[i];
            *g[i] = Py_NewRef(v[i]);
            Py_XDECREF(old);
        }
    }
    Py_RETURN_NONE;
}

static PyMethodDef mod_methods[] = {
    {"_setup", (PyCFunction)(void (*)(void))mod_setup, METH_VARARGS | METH_KEYWORDS, NULL},
    {"ntuple_new", (PyCFunction)(void (*)(void))mod_ntuple_new,
        METH_VARARGS | METH_KEYWORDS, "NodeTuple.__new__(cls, **values)"},
    {NULL}
};

static struct PyModuleDef moddef = {
    PyModuleDef_HEAD_INIT, "ordec.core.ordb._ordb", NULL, -1, mod_methods
};

// The limited API has no static types. Like static types, the heap types
// below are immutable; those without tp_new cannot be instantiated from
// Python.
#define TPFLAGS (Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE)

static PyTypeObject *
block_type(const char *name, int basicsize, int itemsize, destructor dealloc,
    traverseproc traverse, inquiry clear, PyMethodDef *methods)
{
    PyType_Slot slots[5] = {{Py_tp_dealloc, dealloc}};
    int n = 1;
    if (traverse) {
        slots[n++] = (PyType_Slot){Py_tp_traverse, traverse};
        slots[n++] = (PyType_Slot){Py_tp_clear, clear};
    }
    if (methods)
        slots[n++] = (PyType_Slot){Py_tp_methods, methods};
    PyType_Spec spec = {name, basicsize, itemsize,
        TPFLAGS | Py_TPFLAGS_DISALLOW_INSTANTIATION
        | (traverse ? Py_TPFLAGS_HAVE_GC : 0), slots};
    return (PyTypeObject *)PyType_FromSpec(&spec);
}

static PyType_Slot ntype_slots[] = {
    {Py_tp_new, ntype_new},
    {Py_tp_dealloc, ntype_dealloc},
    {Py_tp_traverse, ntype_traverse},
    {Py_tp_clear, ntype_clear},
    {Py_tp_methods, ntype_methods},
    {0, NULL}
};

static PyType_Spec ntype_spec = {"ordec.core.ordb._ordb.NType",
    sizeof(NType), 0, TPFLAGS | Py_TPFLAGS_HAVE_GC, ntype_slots};

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

static PyType_Spec node_spec = {"ordec.core.ordb._ordb.NodeBase",
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

static PyType_Spec attrdesc_spec = {"ordec.core.ordb._ordb.AttrDescriptor",
    sizeof(AttrDesc), 0, TPFLAGS | Py_TPFLAGS_HAVE_GC, attrdesc_slots};

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

static PyType_Spec sg_spec = {"ordec.core.ordb._ordb.SubgraphBase",
    sizeof(Sg), 0, TPFLAGS | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC,
    sg_slots};

static PyType_Slot upd_slots[] = {
    {Py_tp_new, upd_new},
    {Py_tp_dealloc, upd_dealloc},
    {Py_tp_traverse, upd_traverse},
    {Py_tp_methods, upd_methods},
    {Py_tp_members, upd_members},
    {Py_tp_getset, upd_getset},
    {0, NULL}
};

static PyType_Spec upd_spec = {"ordec.core.ordb._ordb.UpdaterBase",
    sizeof(Upd), 0, TPFLAGS | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC,
    upd_slots};

static PyType_Slot curiter_slots[] = {
    {Py_tp_dealloc, curiter_dealloc},
    {Py_tp_traverse, curiter_traverse},
    {Py_tp_iter, PyObject_SelfIter},
    {Py_tp_iternext, curiter_next},
    {0, NULL}
};

static PyType_Spec curiter_spec = {"ordec.core.ordb._ordb.CursorIterator",
    sizeof(CurIter), 0, TPFLAGS | Py_TPFLAGS_HAVE_GC
    | Py_TPFLAGS_DISALLOW_INSTANTIATION, curiter_slots};

PyMODINIT_FUNC
PyInit__ordb(void)
{
    if (!(Leaf_Type = block_type("_ordb.Leaf", offsetof(Leaf, data),
            sizeof(slot_t), (destructor)leaf_dealloc, NULL, NULL, NULL))
        || !(LeafGC_Type = block_type("_ordb.LeafGC", offsetof(Leaf, data),
            sizeof(slot_t), (destructor)leaf_dealloc,
            (traverseproc)leaf_traverse, (inquiry)leaf_clear, NULL))
        || !(InnerGC_Type = block_type("_ordb.InnerGC", sizeof(Inner), 0,
            (destructor)inner_dealloc, (traverseproc)inner_traverse,
            (inquiry)inner_clear, NULL))
        || !(FBlock_Type = block_type("_ordb.FBlock", sizeof(FBlock), 0,
            (destructor)fblock_dealloc, NULL, NULL, fblock_methods))
        || !(FBlockGC_Type = block_type("_ordb.FBlockGC", sizeof(FBlock), 0,
            (destructor)fblock_dealloc, (traverseproc)fblock_traverse,
            (inquiry)fblock_clear, fblock_methods)))
        return NULL;
    if (!(NType_Type = (PyTypeObject *)PyType_FromSpec(&ntype_spec))
            || !(Node_Type = (PyTypeObject *)PyType_FromSpec(&node_spec))
            || !(AttrDesc_Type = (PyTypeObject *)PyType_FromSpec(
                &attrdesc_spec))
            || !(Sg_Type = (PyTypeObject *)PyType_FromSpec(&sg_spec))
            || !(Upd_Type = (PyTypeObject *)PyType_FromSpec(&upd_spec))
            || !(CurIter_Type = (PyTypeObject *)PyType_FromSpec(
                &curiter_spec)))
        return NULL;

    str_ntype = PyUnicode_InternFromString("_ntype");
    str_read_hook = PyUnicode_InternFromString("read_hook");
    str_refcheck = PyUnicode_InternFromString("refcheck");
    str_check_ref = PyUnicode_InternFromString("check_ref");
    str_factory = PyUnicode_InternFromString("factory");
    if (!str_ntype || !str_read_hook || !str_refcheck || !str_check_ref
            || !str_factory)
        return NULL;

    PyObject *m = PyModule_Create(&moddef);
    if (!m)
        return NULL;
    if (PyModule_AddObjectRef(m, "NType", (PyObject *)NType_Type) < 0
            || PyModule_AddObjectRef(m, "NodeBase", (PyObject *)Node_Type) < 0
            || PyModule_AddObjectRef(m, "AttrDescriptor",
                (PyObject *)AttrDesc_Type) < 0
            || PyModule_AddObjectRef(m, "SubgraphBase",
                (PyObject *)Sg_Type) < 0
            || PyModule_AddObjectRef(m, "UpdaterBase",
                (PyObject *)Upd_Type) < 0
            || PyModule_AddIntConstant(m, "ENGINE_PAGED", ENGINE_PAGED) < 0
            || PyModule_AddIntConstant(m, "ENGINE_FLAT", ENGINE_FLAT) < 0
            || PyModule_AddIntConstant(m, "K_INT", K_INT) < 0
            || PyModule_AddIntConstant(m, "K_IVEC", K_IVEC) < 0
            || PyModule_AddIntConstant(m, "K_OBJ", K_OBJ) < 0) {
        Py_DECREF(m);
        return NULL;
    }
    return m;
}
