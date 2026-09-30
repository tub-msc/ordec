# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Real-data layout benchmark: GDS import of an sg13g2_io cell and the web
viewer path, using the actual ORDeC schema (unlike the synthetic workloads
in benchmarks/workloads). Needs the IHP SG13G2 PDK.

    python -m benchmarks.gds_layout --cell sg13g2_Filler2000 --instances 4

Measures one backend per process, so that peak RSS is meaningful; select it
with ORDEC_ORDB_BACKEND. Do not run under a profiler when comparing numbers:
cProfile inflates ORDB-heavy code about 3x.
"""

import argparse
import resource
import time

from ordec.core import *
from ordec.core import ordb
from ordec.extlibrary import ExtLibrary
from ordec.layout.webdata import webdata
from ordec.server import ws_encode
from ordec.lib import ihp130
from ordec.lib.ihp130 import SG13G2

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cell', default='sg13g2_Filler2000')
    parser.add_argument('--instances', type=int, default=4,
        help="placements of the cell in the top layout for the flattening webdata stage")
    args = parser.parse_args()

    times = {}
    def stage(name, fn):
        t0 = time.perf_counter()
        result = fn()
        times[name] = time.perf_counter() - t0
        return result

    layers = SG13G2().layers
    extlib = ExtLibrary()
    gds_fn = ihp130.pdk().root / "libs.ref/sg13g2_io/gds/sg13g2_io.gds"
    stage('discover', lambda: extlib.read_gds(gds_fn, layers))
    cell = stage('import', lambda: extlib[args.cell].layout)
    n_shapes = len(list(cell.all(LayoutPoly))) + len(list(cell.all(LayoutRect)))
    n_nodes = len(cell.subgraph.nodes)

    def scan():
        n = 0
        for poly in cell.all(LayoutPoly):
            n += len(poly.vertices())
        return n
    stage('scan', scan)
    stage('webdata_cell', lambda: webdata(cell))

    top = Layout(ref_layers=layers)
    for i in range(args.instances):
        top % LayoutInstance(pos=Vec2I(i * 10**6, 0), orientation=D4.R0, ref=cell)
    top = top.freeze()
    data = stage('webdata_top', lambda: webdata(top))
    msg_bytes = len(stage('cbor_top', lambda: ws_encode(data)))

    try:
        import pvectorc
        c_ext = True
    except ImportError:
        c_ext = False
    print(f"backend={ordb.default_backend().name} pyrsistent_c_ext={c_ext} "
        f"cell={args.cell} shapes={n_shapes} nodes={n_nodes} instances={args.instances}")
    for name, t in times.items():
        if name in ('import', 'scan', 'webdata_cell'):
            per_shape = f"{t / n_shapes * 1e6:8.1f} us/shape"
        elif name in ('webdata_top', 'cbor_top'):
            per_shape = f"{t / (n_shapes * args.instances) * 1e6:8.1f} us/shape"
        else:
            per_shape = ''
        print(f"  {name:14s} {t:8.2f} s {per_shape}")
    print(f"  cbor_top size  {msg_bytes / 1e6:8.2f} MB")
    print(f"  peak RSS       {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3:8.0f} MB")

if __name__ == '__main__':
    main()
