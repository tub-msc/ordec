// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Indices: per index one persistent B+tree (store.h) holding exactly one
// entry (h, s, nid) per indexed live node, queries and unique checks.

#include "module.h"

// ---------------------------------------------------------------------------
// Index
// ---------------------------------------------------------------------------

// The index of u in the state, created if missing (create), or NULL.
static Idx *
idx_of(State *st, const IdxUse *u, int create)
{
    int xi = st_find_idx(st, u->index);
    if (xi < 0 && create)
        xi = st_add_idx(st, u->index, u->combined);
    return xi < 0 ? NULL : &st->idxs[xi];
}

int
idx_insert(Sg *sg, const IdxUse *u, const Ent *e)
{
    Idx *ix = idx_of(&sg->st, u, 1);
    if (!ix)
        return -1;
    sg->txn->writes++;
    return bt_insert(&ix->tree, e, sg->txn->tok);
}

int
idx_remove(Sg *sg, const IdxUse *u, const Ent *e)
{
    Idx *ix = idx_of(&sg->st, u, 0);
    sg->txn->writes++;
    int r = ix ? bt_delete(&ix->tree, e, sg->txn->tok) : 0;
    if (r == 0)
        PyErr_Format(OrdbException, "Index entry of nid %lld not found:"
            " its sortkey or key hash changed without a change of the node.",
            (long long)e->nid);
    return r == 1 ? 0 : -1;
}

// Inserts n ascending entries.
int
idx_insert_sorted(Sg *sg, const IdxUse *u, const Ent *e, uint64_t n)
{
    if (n == 0)
        return 0;
    Idx *ix = idx_of(&sg->st, u, 1);
    if (!ix)
        return -1;
    sg->txn->writes++;
    return bt_add_sorted(&ix->tree, e, n, sg->txn->tok);
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

// The entries with hash h, ordered by (s, nid). They are copied out of the
// tree: comparing keys can run Python code, during which another thread
// may write to the subgraph.
static int
idx_candidates(const Idx *ix, uint64_t h, EntBuf *b)
{
    b->e = b->stack;
    b->n = 0;
    b->cap = 32;
    BIter it;
    Ent lo = {h, INT64_MIN, INT64_MIN};
    for (const Ent *e = bt_seek(&it, &ix->tree, &lo); e && e->h == h;
            e = bt_next(&it))
        if (entbuf_push(b, e) < 0)
            return -1;
    return 0;
}

// nids of the nodes with the given key, ordered by (sort value, nid).
PyObject *
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
        // The entry is current, but its key may differ from the query key
        // with the same hash. Rows may also have changed since the entries
        // were copied (another thread).
        int64_t nid = b.e[i].nid;
        int ti;
        const slot_t *p = st_row(st, nid, &ti);
        if (!p)
            continue;
        NType *nt = st->tabs[ti].nt;
        IdxUse *u = ntype_find_use(nt, index);
        if (!u || (u->combined && PyTuple_Size(key) != u->nkey))
            continue;
        int ok;
        const AttrInfo *ai = &nt->attrs[u->key[0]];
        slot_t x;
        if (!u->combined && ai->kind == K_INT && p[ai->slot] > SLOT_BOXED
                && long_as_slot(key, &x)) {
            ok = p[ai->slot] == x; // int keys: no Python code
        } else {
            Rec rec;
            if (rec_take(&rec, st, nt, p, nid) < 0)
                goto fail_buf;
            ok = 1;
            for (int k = 0; k < u->nkey && ok == 1; k++) {
                PyObject *comp = u->combined ? PyTuple_GetItem(key, k) : key;
                ok = rec_eq_pyval(&rec, u->key[k], comp);
            }
            rec_drop(&rec);
        }
        if (ok < 0)
            goto fail_buf;
        if (ok == 0)
            continue;
        PyObject *o = PyLong_FromLongLong(nid);
        if (!o || PyList_Append(ret, o) < 0) {
            Py_XDECREF(o);
            goto fail_buf;
        }
        Py_DECREF(o);
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
int
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
        ok = 1;
        for (int k = 0; k < u->nkey && ok == 1; k++)
            ok = rec_eq(r, u->key[k], &orec, ou->key[k]);
        rec_drop(&orec);
        found = ok;
    }
    entbuf_free(&b);
    return found;
}

// _check_indices(): for tests. Raises AssertionError unless every index tree
// is well-formed and holds exactly the entries computed from the live rows.
PyObject *
sg_check_indices(Sg *sg, PyObject *noarg)
{
    const State *st = &sg->st;
    for (int xi = 0; xi < st->nidx; xi++)
        if (bt_check(&st->idxs[xi].tree) < 0)
            return NULL;
    // Expected entries, per index of the state (indices of node types
    // without an Idx must have no entries at all).
    for (int ti = 0; ti < st->ntab; ti++) {
        const Tab *t = &st->tabs[ti];
        for (int i = 0; i < t->nt->nuse; i++) {
            if (st_find_idx(st, t->nt->uses[i].index) < 0 && t->live) {
                int64_t pos = -1;
                for (const slot_t *p; (p = tab_next(st, ti, &pos));) {
                    Rec rec;
                    uint64_t h;
                    int64_t s;
                    if (rec_take(&rec, st, t->nt, p, p[0]) < 0)
                        return NULL;
                    int on = rec_hs(&rec, &t->nt->uses[i], &h, &s);
                    rec_drop(&rec);
                    if (on < 0)
                        return NULL;
                    if (on) {
                        PyErr_SetString(PyExc_AssertionError,
                            "ORDB: index missing");
                        return NULL;
                    }
                }
            }
        }
    }
    for (int xi = 0; xi < st->nidx; xi++) {
        const Idx *ix = &st->idxs[xi];
        Ent *want = PyMem_Malloc(sizeof(Ent) * (st->nlive + 1));
        if (!want)
            return PyErr_NoMemory();
        uint64_t n = 0;
        for (int ti = 0; ti < st->ntab; ti++) {
            const Tab *t = &st->tabs[ti];
            const IdxUse *u = ntype_find_use(t->nt, ix->index);
            if (!u)
                continue;
            int64_t pos = -1;
            for (const slot_t *p; (p = tab_next(st, ti, &pos));) {
                Rec rec;
                Ent e = {0, 0, p[0]};
                if (rec_take(&rec, st, t->nt, p, p[0]) < 0) {
                    PyMem_Free(want);
                    return NULL;
                }
                int on = rec_hs(&rec, u, &e.h, &e.s);
                rec_drop(&rec);
                if (on < 0) {
                    PyMem_Free(want);
                    return NULL;
                }
                if (on)
                    want[n++] = e;
            }
        }
        qsort(want, n, sizeof(Ent), ent_cmp);
        BIter it;
        Ent lo = {0, INT64_MIN, INT64_MIN};
        uint64_t k = 0;
        int same = ix->tree.count == n;
        for (const Ent *e = bt_seek(&it, &ix->tree, &lo); e && same;
                e = bt_next(&it))
            same = k < n && ent_eq(e, &want[k++]);
        PyMem_Free(want);
        if (!same || k != n) {
            PyErr_SetString(PyExc_AssertionError,
                "ORDB: index entries differ from the live rows");
            return NULL;
        }
    }
    Py_RETURN_NONE;
}
