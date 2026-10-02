// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Indices: sorted runs of (h, s, nid) plus an unsorted tail, queries and
// unique checks.

#include "module.h"

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
int
idx_add_run(const State *st, Idx *ix, Run *r)
{
    if (r->n == 0) {
        run_decref(r);
        return 0;
    }
    ix->runs[ix->nruns++] = r;
    return idx_cascade(st, ix);
}

int
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
int
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
