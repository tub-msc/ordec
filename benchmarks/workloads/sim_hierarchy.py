# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
W4 sim_hierarchy -- recursive build with unique-index checks, then
interleaved query+insert back-annotation.

Mirrors SimHierarchy.from_schematic (ordec/core/schema.py:834-863) followed
by simulator result storage (ordec/sim/simulator.py:143-239): a hierarchy
of groups is built recursively (each item insert validates a unique
CombinedIndex), then every item is looked up by that index and annotated
with a new node in a small separate transaction.
"""

from ..prng import Lcg
from ..schema import SimRoot, SimGroup, SimItem, SimAnnot
from . import workload, PhaseTimer, WorkloadRun

@workload('sim_hierarchy',
    phases=('build', 'annotate'),
    params={
        'smoke':   dict(depth=2, fanout=2, items=3),
        'small':   dict(depth=3, fanout=3, items=4),
        'default': dict(depth=3, fanout=4, items=6),
        'large':   dict(depth=5, fanout=6, items=8),
    },
    mirrors='SimHierarchy.from_schematic + simulator._store_results')
def sim_hierarchy(params, seed):
    rng = Lcg(seed)
    t = PhaseTimer()
    root = SimRoot()
    sg = root.subgraph
    groups = []

    with t.phase('build'):
        def recurse(parent_node, depth):
            for f in range(params['fanout']):
                setattr(parent_node, f'g{f}', SimGroup(depth=depth))
                group = getattr(parent_node, f'g{f}')
                groups.append(group)
                for e in range(params['items']):
                    root % SimItem(group=group, key=f'k{e}')
                if depth + 1 < params['depth']:
                    recurse(group, depth + 1)
        recurse(root, 0)

    with t.phase('annotate'):
        for group in groups:
            for e in range(params['items']):
                item = sg.one(SimItem.group_key_idx.query((group.nid, f'k{e}')))
                root % SimAnnot(target=item, value=rng.randint(1 << 20))

    frozen = sg.freeze()
    return WorkloadRun(t.phase_ns, final=frozen, retained=[frozen])
