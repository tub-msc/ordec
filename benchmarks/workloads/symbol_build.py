# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
W1 symbol_build -- many small subgraph builds, insert-dominated.

Mirrors view generators like ordec.lib.base Res.symbol: M small symbol-like
subgraphs, each built with per-statement transactions (every attribute
assignment / '%' insert opens its own updater, exactly like real generator
code), then frozen. Stresses transaction begin/commit overhead and small-
bucket index insertion.
"""

from ..prng import Lcg
from ..schema import SymRoot, SymPin, SymPoly, SymVertex
from . import workload, PhaseTimer, WorkloadRun

@workload('symbol_build',
    phases=('build',),
    params={
        'tiny':    dict(m=5, k=4, p=2, v=3),
        'small':   dict(m=100, k=8, p=6, v=5),
        'default': dict(m=200, k=8, p=6, v=5),
        'large':   dict(m=5000, k=8, p=6, v=5),
    },
    mirrors='ordec.lib.base symbol generators (@generate view builds)')
def symbol_build(params, seed):
    m, k, p, v = params['m'], params['k'], params['p'], params['v']
    rng = Lcg(seed)
    t = PhaseTimer()
    frozen = []
    with t.phase('build'):
        for i in range(m):
            root = SymRoot()
            for j in range(k):
                setattr(root, f'p{j}', SymPin(num=j)) # NPath-named pin
            for q in range(p):
                poly = root % SymPoly(layer=rng.randint(8))
                for o in range(v):
                    poly % SymVertex(order=o, x=rng.randint(1000),
                        y=rng.randint(1000))
            frozen.append(root.freeze())
    return WorkloadRun(t.phase_ns, final=[f.subgraph for f in frozen],
        retained=frozen)
