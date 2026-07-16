# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
W6 micro_* -- index-bucket micro-benchmarks (absorbed from the former
tests/bench_ordb_index.py) plus a transaction-abort micro.

All four stress the per-type (NType) index bucket, which holds the nids of
all nodes of one type and is therefore the largest bucket in practice:

- micro_remove_all:        remove N nodes one-by-one in one transaction
                           (bucket.remove per node; O(n^2) with pvector).
- micro_insert_descending: insert N nodes with descending nids; each insert
                           lands at bucket position 0 (slice-rebuild path
                           with pvector).
- micro_replace:           replace each Box by an MPoly reusing the nid
                           (mirrors ordec.layout.helpers.expand_rects).
- micro_abort:             transaction of B inserts ending in a
                           UniqueViolation; measures rollback cost.
"""

from ordec.core.ordb import UniqueViolation

from ..schema import MicroRoot, Box, MPoly, UNode
from . import workload, PhaseTimer, WorkloadRun

def _build(n):
    """Subgraph with root and n Box nodes (nids 1..n), single transaction."""
    root = MicroRoot()
    sg = root.subgraph
    with sg.updater() as u:
        for i in range(n):
            u.add_single(Box(val=i), u.nid_generate())
    return sg

_PARAMS = {
    'smoke':   dict(n=100),
    'small':   dict(n=1000),
    # micro_remove_all/insert_descending are O(n^2) on pvector buckets, so the
    # everyday tier stays small; use --scale large to measure that asymptote.
    'default': dict(n=3000),
    'large':   dict(n=50000),
}

@workload('micro_remove_all', phases=('remove',), params=_PARAMS,
    mirrors='bulk node removal (NType bucket shrink)')
def micro_remove_all(params, seed):
    n = params['n']
    sg = _build(n)
    nids = list(sg.all(Box, wrap_cursor=False))
    assert len(nids) == n
    t = PhaseTimer()
    with t.phase('remove'):
        with sg.updater() as u:
            for nid in nids:
                u.remove_nid(nid)
    assert len(list(sg.all(Box, wrap_cursor=False))) == 0
    frozen = sg.freeze()
    return WorkloadRun(t.phase_ns, final=frozen, retained=[frozen])

@workload('micro_insert_descending', phases=('insert',), params=_PARAMS,
    mirrors='out-of-order nid insertion (bucket head insert)')
def micro_insert_descending(params, seed):
    n = params['n']
    root = MicroRoot()
    sg = root.subgraph
    t = PhaseTimer()
    with t.phase('insert'):
        with sg.updater() as u:
            for nid in range(n, 0, -1):
                u.add_single(Box(val=nid), nid)
    assert list(sg.all(Box, wrap_cursor=False)) == list(range(1, n + 1))
    frozen = sg.freeze()
    return WorkloadRun(t.phase_ns, final=frozen, retained=[frozen])

@workload('micro_replace', phases=('replace',), params=_PARAMS,
    mirrors='ordec.layout.helpers.expand_rects (NType bucket migration)')
def micro_replace(params, seed):
    n = params['n']
    sg = _build(n)
    t = PhaseTimer()
    with t.phase('replace'):
        for cursor in sg.all(Box):
            cursor.replace(MPoly(val=cursor.val))
    assert len(list(sg.all(Box, wrap_cursor=False))) == 0
    assert len(list(sg.all(MPoly, wrap_cursor=False))) == n
    frozen = sg.freeze()
    return WorkloadRun(t.phase_ns, final=frozen, retained=[frozen])

@workload('micro_abort', phases=('abort',),
    params={
        'smoke':   dict(n=100, batch=20, rounds=3),
        'small':   dict(n=1000, batch=100, rounds=5),
        'default': dict(n=3000, batch=300, rounds=10),
        'large':   dict(n=50000, batch=2000, rounds=20),
    },
    mirrors='failed transaction rollback (constraint violation at commit)')
def micro_abort(params, seed):
    n, batch, rounds = params['n'], params['batch'], params['rounds']
    root = MicroRoot()
    sg = root.subgraph
    with sg.updater() as u:
        for i in range(n):
            u.add_single(UNode(val=i), u.nid_generate())
    n_nodes = len(sg.nodes)
    t = PhaseTimer()
    with t.phase('abort'):
        for r in range(rounds):
            try:
                with sg.updater() as u:
                    for b in range(batch):
                        u.add_single(UNode(val=n + b), u.nid_generate())
                    u.add_single(UNode(val=0), u.nid_generate()) # duplicate
            except UniqueViolation:
                pass
            assert len(sg.nodes) == n_nodes # rollback left state untouched
    frozen = sg.freeze()
    return WorkloadRun(t.phase_ns, final=frozen, retained=[frozen])
