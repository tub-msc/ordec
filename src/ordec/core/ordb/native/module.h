// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Native core of ORDB (see docs/ref/ordb.rst and docs/dev/ordb_core.rst).
//
// A subgraph state consists of:
// - one table per node type: a persistent sparse array keyed by nid (the
//   "keyed" engine) of records of 8-byte slots, slot 0 is the nid,
//   followed by the attribute slots,
// - the nid directory: per nid the table and the number of LocalRefs
//   pointing at it, a persistent vector,
// - per index a persistent B+tree with exactly one entry (h, s, nid) per
//   indexed live node.
//
// All three are persistent trees (see store.h): snapshots share nodes, a
// transaction keeps the previous state, and abort swaps it back.
//
// Files: store.h/store.c (tables, directory, index trees), engine.c (state,
// records, node operations, transactions and checks), index.c (indices),
// and one file per Python type: ntype.c, cursor.c, subgraph.c, updater.c.
// module.c defines the globals and initializes the module. This header holds
// what the files share.
//
// base.py owns the schema, the public classes and all error messages. On
// any failed constraint check, the core calls back into base.py, which
// repeats the check in Python and raises the exact exception.

#ifndef ORDB_MODULE_H
#define ORDB_MODULE_H

#define PY_SSIZE_T_CLEAN
#define Py_LIMITED_API 0x030b0000 // abi3, Python 3.11+
#include <Python.h>
#include <structmember.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

// Functions and globals shared between the files stay internal to the
// extension (PyMODINIT_FUNC exports PyInit__ordb regardless).
#if defined(__GNUC__)
#pragma GCC visibility push(hidden)
#endif

#include "store.h"

#define SLOT_NONE INT64_MIN
#define SLOT_BOXED (INT64_MIN + 1)

#define ENGINE_KEYED 0 // the only engine so far; the selection stays

#define K_INT 0 // int64 slot (int, LocalRef, ExternalRef)
#define K_IVEC 1 // width int64 slots (Vec2I, Rect4I)
#define K_OBJ 2 // Python object reference

#define REF_NONE 0
#define REF_LOCAL 1
#define REF_EXTERNAL 2

#define READ_PLAIN 0 // return the stored value
#define READ_LOCALREF 1 // return a cursor at the stored nid
#define READ_HOOK 2 // call attr.read_hook(value, cursor)
#define READ_EXTREF 3 // ExternalRef.read_hook, natively if possible

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
#define MAXUSE 32 // indices per node type
#define MAXWIDTH 8 // slots of one attribute
#define H_NONE 0x9E3779B97F4A7C15ull

// Directory record of a nid: [table + 1 (0: no node), inbound LocalRefs].
#define DIR_TAB(loc) ((int)(loc) - 1)
#define DIR_LOC(ti) ((slot_t)(ti) + 1)
#define DIR_MAX_GAP ((int64_t)1 << 24)

// The limited API has no static types. Like static types, the heap types
// of the core are immutable; those without tp_new cannot be instantiated
// from Python.
#define TPFLAGS (Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE)

// Globals (module.c)
extern PyObject *OrdbException, *QueryException;
extern PyObject *g_check_cb; // base._check_callback(kind, sgu, nid, obj)
extern PyObject *g_updater_cls; // base.SubgraphUpdater
extern PyObject *g_pathnode_mut, *g_pathnode_frz;
extern PyObject *g_npath_index; // NPath.idx_path_of
extern PyObject *g_npath_child_index; // NPath.idx_parent_name
extern PyObject *str_ntype, *str_read_hook, *str_refcheck, *str_check_ref,
    *str_factory;
extern PyTypeObject *NType_Type, *Node_Type, *AttrDesc_Type, *Sg_Type,
    *Upd_Type, *CurIter_Type;
extern PyType_Spec ntype_spec, node_spec, attrdesc_spec, curiter_spec,
    sg_spec, upd_spec;

// ---------------------------------------------------------------------------
// Data structures
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

typedef struct {
    NType *nt;
    KMap rows;
    uint64_t live;
} Tab;

typedef struct {
    PyObject *index;
    BTree tree; // exactly one entry (h, s, nid) per indexed live node
    int combined;
} Idx;

// The entry of a record in one index: (h, s), or on == 0 if the record is
// not indexed (single key that is None).
typedef struct {
    uint64_t h;
    int64_t s;
    int on;
} IdxKey;

typedef struct {
    Vec dir; // records [table + 1, refs]
    Tab *tabs;
    int ntab;
    Idx *idxs;
    int nidx;
    PyObject *boxed; // dict {nid * 256 + attr position: value} or NULL
    uint64_t nlive;
    int64_t nid_start, nid_stop; // nid_alloc
} State;

typedef struct Txn {
    struct Txn *parent;
    State saved; // state at begin
    uint64_t tok;
    uint64_t writes; // record writes so far (tells whether a statement wrote)
    char failed; // a statement failed after writing: abort at exit
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

typedef struct {
    PyObject_HEAD
    Sg *sg;
    Txn *tx;
    char commit, valid;
    char joined; // statement handle on an open transaction (not its owner)
    uint64_t writes; // joined: tx->writes at enter
} Upd;

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

#define NPATH_NONE (-1)
#define NPATH_UNRESOLVED (-2)

typedef struct {
    PyObject_HEAD
    Sg *sg;
    int64_t nid; // -1: no node (PathNode)
    int64_t npath; // nid of the NPath, NPATH_NONE or NPATH_UNRESOLVED
} NodeObj;

// ---------------------------------------------------------------------------
// Inline helpers
// ---------------------------------------------------------------------------

static inline IdxUse *
ntype_find_use(NType *nt, PyObject *index)
{
    for (int i = 0; i < nt->nuse; i++)
        if (nt->uses[i].index == index)
            return &nt->uses[i];
    return NULL;
}

static inline int
st_find_tab(const State *st, const NType *nt)
{
    for (int i = 0; i < st->ntab; i++)
        if (st->tabs[i].nt == nt)
            return i;
    return -1;
}

static inline int
st_find_idx(const State *st, const PyObject *index)
{
    for (int i = 0; i < st->nidx; i++)
        if (st->idxs[i].index == index)
            return i;
    return -1;
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
    if (!d || d[0] <= 0)
        return NULL;
    *ti = DIR_TAB(d[0]);
    return kmap_get(&st->tabs[*ti].rows, nid);
}

// The row of table ti with the smallest nid > *nid (start with -1), which
// becomes the new *nid. Each call looks the table up again, so the loop may
// run Python code between calls.
static inline const slot_t *
tab_next(const State *st, int ti, int64_t *nid)
{
    return ti < st->ntab ? kmap_next(&st->tabs[ti].rows, *nid, nid) : NULL;
}

// The int64 slot value of an exact int that is representable unboxed.
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

static inline void
sg_write_end(Sg *sg)
{
    sg->writing = 0;
}

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

// ---------------------------------------------------------------------------
// Functions shared between files
// ---------------------------------------------------------------------------

// engine.c
void state_init(State *st);
int state_copy(State *dst, const State *src);
int st_add_idx(State *st, PyObject *index, int combined);
void state_release(State *st);
int sg_write_begin(Sg *sg);
PyObject *boxed_get(const State *st, int64_t nid, int ai);
PyObject *attr_value(const State *st, const NType *nt, int i, const slot_t *p,
    int64_t nid);
void rec_drop(Rec *r);
int rec_take(Rec *r, const State *st, const NType *nt, const slot_t *p,
    int64_t nid);
PyObject *row_load(const State *st, const NType *nt, const slot_t *p,
    int64_t nid);
int rec_slot_hash(const Rec *r, int i, uint64_t *out);
int rec_hs(const Rec *r, const IdxUse *u, uint64_t *h, int64_t *s);
int key_hash(PyObject *key, int combined, uint64_t *h);
int rec_eq_pyval(const Rec *r, int i, PyObject *v);
int rec_eq(const Rec *ra, int ia, const Rec *rb, int ib);
int op_add(Sg *sg, int64_t nid, PyObject *node);
int op_remove(Sg *sg, int64_t nid);
int op_update(Sg *sg, int64_t nid, PyObject *node);
int op_insert_rows(Sg *sg, NType *nt, const int64_t *nids, Py_ssize_t n,
    const int64_t **cols);
const slot_t **tab_rows_sorted(const State *st, int ti, uint64_t *n_out);
Txn *txn_begin(Sg *sg);
void txn_abort(Sg *sg, Txn *tx);
Sg *ext_target(const State *st, const NType *nt, const AttrInfo *ai,
    const slot_t *p, int64_t nid);
int txn_check(Sg *sg, Txn *tx, PyObject *sgu);
int txn_commit(Sg *sg, Txn *tx);

// index.c
int idx_insert(Sg *sg, const IdxUse *u, const Ent *e);
int idx_remove(Sg *sg, const IdxUse *u, const Ent *e);
int idx_insert_sorted(Sg *sg, const IdxUse *u, const Ent *e, uint64_t n);
PyObject *st_query(const State *st, PyObject *index, PyObject *key);
int unique_violated(const State *st, const Rec *r, const IdxUse *u);
PyObject *sg_check_indices(Sg *sg, PyObject *noarg);

// ntype.c
NType *ntype_of_cls(PyObject *cls);
PyObject *mod_ntuple_new(PyObject *m, PyObject *args, PyObject *kwds);
PyObject *ntuple_replace(NType *nt, PyObject *node, int index,
    PyObject *value);

// cursor.c
Sg *call_subfn(PyObject *fn, Sg *sg, int64_t nid);
PyObject *node_make(PyObject *cls, Sg *sg, int64_t nid, int64_t npath);
PyObject *key_error_nid(int64_t nid);
PyObject *sg_cursor(Sg *sg, int64_t nid, int64_t npath);
int opt_nid(PyObject *o, int64_t none, int64_t *out);
PyObject *sg_cursors(Sg *sg, PyObject *nids);

// updater.c
PyObject *sg_add1(Sg *sg, PyObject *args);
PyObject *sg_statement_updater(Sg *sg, PyObject *noarg);
int sg_set1(Sg *sg, int64_t nid, NType *nt, int index, PyObject *value);

#if defined(__GNUC__)
#pragma GCC visibility pop
#endif

#endif
