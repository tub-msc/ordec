# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
W2 layout_flatten -- copy / bulk insert / replace-migration / scan.

Mirrors the layout webdata pipeline (ordec/layout/webdata.py:21-76 with
helpers.py flatten and expand_geom): a frozen hierarchical layout is
mutable-copied, every instance is inlined by re-inserting its cell's
transformed shapes, every LRect is then .replace()d by an LPoly with four
vertices (NType bucket migration -- the expand_rects pattern), the result
is frozen and fully scanned. The expand phase iterates the bucket snapshot
returned by all(LRect) while removing exactly those nodes.
"""

from ordec.core.ordb import FuncInserter

from ..prng import Lcg
from ..schema import LayRoot, LRect, LPoly, LVertex, LLabel, LInst
from . import workload, PhaseTimer, WorkloadRun

def _build_cell(rng, n_shapes):
    """Frozen library cell: half rects, half polys-with-vertices, labels."""
    root = LayRoot(kind=1)
    sg = root.subgraph
    with sg.updater() as u:
        for s in range(n_shapes):
            layer = rng.randint(8)
            x = rng.randint(10000)
            y = rng.randint(10000)
            if s % 2 == 0:
                u.add_single(LRect(layer=layer, lx=x, ly=y,
                    ux=x + 1 + rng.randint(500), uy=y + 1 + rng.randint(500)),
                    u.nid_generate())
            else:
                poly_nid = u.add_single(LPoly(layer=layer), u.nid_generate())
                for o in range(4):
                    u.add_single(LVertex(ref=poly_nid, order=o,
                        x=x + rng.randint(500), y=y + rng.randint(500)),
                        u.nid_generate())
            if s % 8 == 0:
                u.add_single(LLabel(layer=layer, x=x, y=y, text=f"lbl{s}"),
                    u.nid_generate())
    return sg.freeze()

def _rect_to_poly(cursor):
    """Replace one LRect by an LPoly with 4 vertices, reusing the nid
    (mirrors ordec.layout.helpers.expand_rects)."""
    layer = cursor.layer
    corners = ((cursor.lx, cursor.ly), (cursor.ux, cursor.ly),
               (cursor.ux, cursor.uy), (cursor.lx, cursor.uy))
    def ins(sgu, primary_nid):
        poly_nid = sgu.add_single(LPoly(layer=layer), primary_nid)
        for o, (x, y) in enumerate(corners):
            sgu.add_single(LVertex(ref=poly_nid, order=o, x=x, y=y),
                sgu.nid_generate())
        return poly_nid
    cursor.replace(FuncInserter(ins))

@workload('layout_flatten',
    phases=('copy', 'flatten', 'expand', 'freeze', 'scan'),
    params={
        'tiny':    dict(cells=2, shapes_per_cell=8, instances=4),
        'small':   dict(cells=5, shapes_per_cell=20, instances=20),
        'default': dict(cells=5, shapes_per_cell=40, instances=50),
        'large':   dict(cells=10, shapes_per_cell=200, instances=2000),
    },
    mirrors='ordec/layout/webdata.py + helpers.py flatten/expand_geom')
def layout_flatten(params, seed):
    rng = Lcg(seed)
    t = PhaseTimer()

    # Untimed setup: cell library + frozen top with instances.
    cells = [_build_cell(rng, params['shapes_per_cell'])
        for _ in range(params['cells'])]
    top_root = LayRoot(kind=0)
    top_sg = top_root.subgraph
    for i in range(params['instances']):
        cell = cells[rng.randint(len(cells))]
        setattr(top_root, f'i{i}', LInst(sub=cell,
            dx=rng.randint(100000), dy=rng.randint(100000)))
    top_frozen = top_sg.freeze()

    with t.phase('copy'):
        top = top_frozen.mutable_copy()

    with t.phase('flatten'):
        root = top.root_cursor
        for inst in list(top.all(LInst)):
            dx, dy = inst.dx, inst.dy
            src = inst.sub.subgraph
            for r in src.all(LRect):
                root % LRect(layer=r.layer, lx=r.lx + dx, ly=r.ly + dy,
                    ux=r.ux + dx, uy=r.uy + dy)
            for p in src.all(LPoly):
                new_poly = root % LPoly(layer=p.layer)
                for vtx in src.all(LVertex.ref_idx.query(p.nid)):
                    new_poly % LVertex(order=vtx.order, x=vtx.x + dx,
                        y=vtx.y + dy)
            for lab in src.all(LLabel):
                root % LLabel(layer=lab.layer, x=lab.x + dx, y=lab.y + dy,
                    text=lab.text)
            inst.remove()

    with t.phase('expand'):
        for cursor in top.all(LRect):
            _rect_to_poly(cursor)

    with t.phase('freeze'):
        result = top.freeze()

    with t.phase('scan'):
        acc = 0
        for _ in range(3):
            for p in result.all(LPoly):
                acc += p.layer
            for vtx in result.all(LVertex):
                acc += vtx.x + vtx.y
            for lab in result.all(LLabel):
                acc += len(lab.text)

    return WorkloadRun(t.phase_ns, final=result, retained=[result])
