# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
W3 render_scan -- read-only scans on a frozen graph.

Mirrors ordec/schematic/render.py:293-367 (the webdata rendering hotspot):
repeated full-type scans over a frozen schematic-like subgraph, per-instance
index queries, ExternalRef resolution into symbol subgraphs with coordinate
arithmetic per symbol shape, and NPath path reconstruction. Zero mutation.
"""

from ..prng import Lcg
from ..schema import (SymRoot, SymPin, SymPoly, SymVertex,
    SchRoot, SchNet, SchInst, SchConn)
from . import workload, PhaseTimer, WorkloadRun

def _build_symbol(rng, pins, polys, verts):
    root = SymRoot()
    sg = root.subgraph
    with sg.updater() as u:
        pin_nids = [u.add_single(SymPin(num=j), u.nid_generate())
            for j in range(pins)]
        for q in range(polys):
            poly_nid = u.add_single(SymPoly(layer=rng.randint(8)),
                u.nid_generate())
            for o in range(verts):
                u.add_single(SymVertex(ref=poly_nid, order=o,
                    x=rng.randint(100), y=rng.randint(100)), u.nid_generate())
    return sg.freeze()

@workload('render_scan',
    phases=('build', 'scan'),
    params={
        'smoke':   dict(symbols=2, pins=3, polys=2, verts=3, insts=5,
                        nets=4, repeats=2),
        'small':   dict(symbols=8, pins=4, polys=6, verts=5, insts=200,
                        nets=100, repeats=5),
        'default': dict(symbols=8, pins=4, polys=6, verts=5, insts=2000,
                        nets=1000, repeats=20),
        'large':   dict(symbols=8, pins=4, polys=6, verts=5, insts=8000,
                        nets=4000, repeats=20),
    },
    mirrors='ordec/schematic/render.py render_schematic (webdata hotspot)')
def render_scan(params, seed):
    rng = Lcg(seed)
    t = PhaseTimer()

    with t.phase('build'):
        symbols = [_build_symbol(rng, params['pins'], params['polys'],
            params['verts']) for _ in range(params['symbols'])]
        root = SchRoot()
        sg = root.subgraph
        nets = []
        for n in range(params['nets']):
            net = root % SchNet(w=rng.randint(4))
            setattr(root, f'n{n}', net)
            nets.append(net)
        for i in range(params['insts']):
            sym = symbols[rng.randint(len(symbols))]
            pin_nids = list(sym.all(SymPin, wrap_cursor=False))
            inst = root % SchInst(sym=sym, x=rng.randint(100000),
                y=rng.randint(100000))
            setattr(root, f'i{i}', inst)
            for pin_nid in pin_nids:
                root % SchConn(ref=inst, pin=pin_nid,
                    net=nets[rng.randint(len(nets))])
        frozen = sg.freeze()

    with t.phase('scan'):
        acc = 0
        for _ in range(params['repeats']):
            for inst in frozen.all(SchInst):
                ix, iy = inst.x, inst.y
                sym = inst.sym # SubgraphRef resolution
                for conn in frozen.all(SchConn.ref_idx.query(inst.nid)):
                    acc += conn.pin.num # ExternalRef resolution
                for poly in sym.all(SymPoly):
                    for vtx in sym.all(SymVertex.ref_idx.query(poly.nid)):
                        acc += ix + vtx.x + iy + vtx.y
                acc += len(inst.full_path_str()) # NPath reconstruction
            for net in frozen.all(SchNet):
                acc += net.w

    return WorkloadRun(t.phase_ns, final=frozen, retained=[frozen])
