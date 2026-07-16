# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
W5 snapshot_chain -- freeze/thaw generation chains.

Mirrors the "build a view, freeze it, derive small variations" lifecycle:
a base graph of N nodes is frozen, then K generations are derived, each
thawing the newest snapshot, patching a small fraction p of the graph
(60% attribute updates / 25% inserts / 15% removals) in one transaction,
and freezing again. ALL generations are kept alive, so retained memory
measures structure sharing. The read phase then scans and point-queries
the newest generation, which for chained backends pays the chain-depth
cost; compact_every > 0 flattens the newest snapshot periodically.

This is the delta-chain sweet spot and the full-copy worst case.
"""

from ..prng import Lcg
from ..schema import ChainRoot, CNode
from . import workload, PhaseTimer, WorkloadRun

_TAGS = 64

@workload('snapshot_chain',
    phases=('build', 'chain', 'read'),
    params={
        'smoke':   dict(n=50, k=4, patch_permille=100, compact_every=0),
        'small':   dict(n=1000, k=8, patch_permille=20, compact_every=0),
        # Explicit compact() every C generations via
        # --param snapshot_chain.compact_every=C (0 = never).
        # Chain depth k is the whole point of this workload: at small k a
        # copy-on-write backend looks competitive because it never pays for a
        # deep chain. Keep the default deep enough to show that -- it is cheap
        # (a few hundred ms), so there is no reason to trim it.
        'default': dict(n=10000, k=32, patch_permille=20, compact_every=0),
        'large':   dict(n=50000, k=64, patch_permille=20, compact_every=0),
    },
    mirrors='freeze/thaw derivation chains (view variants, checkpoints)')
def snapshot_chain(params, seed):
    n, k = params['n'], params['k']
    n_patch = max(1, n * params['patch_permille'] // 1000)
    compact_every = params['compact_every']
    rng = Lcg(seed)
    t = PhaseTimer()

    with t.phase('build'):
        root = ChainRoot()
        sg = root.subgraph
        live = [] # ascending list of live nids, mirrored for reproducible picks
        with sg.updater() as u:
            for i in range(n):
                nid = u.add_single(CNode(tag=rng.randint(_TAGS),
                    val=rng.randint(1 << 20)), u.nid_generate())
                live.append(nid)
        gens = [sg.freeze()]

    with t.phase('chain'):
        for g in range(k):
            mut = gens[-1].thaw()
            with mut.updater() as u:
                for _ in range(n_patch):
                    r = rng.randint(100)
                    if r < 60: # update attribute of random node
                        nid = live[rng.randint(len(live))]
                        node = u.nodes[nid]
                        u.update(node.set(val=rng.randint(1 << 20)), nid)
                    elif r < 85: # insert new node
                        nid = u.add_single(CNode(tag=rng.randint(_TAGS),
                            val=rng.randint(1 << 20)), u.nid_generate())
                        live.append(nid)
                    else: # remove random node
                        pick = rng.randint(len(live))
                        u.remove_nid(live[pick])
                        live.pop(pick)
            frozen = mut.freeze()
            if compact_every and (g + 1) % compact_every == 0:
                frozen = frozen.compact()
            gens.append(frozen)

    with t.phase('read'):
        newest = gens[-1]
        acc = 0
        for cursor in newest.all(CNode):
            acc += cursor.val
        for tag in range(_TAGS):
            for nid in newest.all(CNode.tag_idx.query(tag), wrap_cursor=False):
                acc += nid
        nodes = newest.nodes
        for _ in range(n):
            acc += nodes[live[rng.randint(len(live))]].val

    return WorkloadRun(t.phase_ns, final=gens[-1], retained=gens)
