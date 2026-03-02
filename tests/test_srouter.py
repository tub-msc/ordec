# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.layout import SRouter
from ordec.lib import ihp130
from ordec.core import *

@generate_func
def layout_x():
    layers = ihp130.SG13G2().layers
    l = Layout(ref_layers=layers)
    s = Solver(l)
    sr = SRouter(l, s, layers.Metal1, pos=(0, 0))
    sr.move((1000, 0))
    sr.move((1000, 1000))
    sr.layer(layers.Metal3)
    sr.move((0, 1000))

    s.solve()
    return l

def test_layout_x():
    layers = ihp130.SG13G2().layers
    l = layout_x()

    (p1,) = [p for p in l.all(LayoutPath) if p.layer == layers.Metal1]
    assert p1.width == 210
    assert p1.endtype == PathEndType.Custom
    assert p1.ext_bgn == p1.ext_end == 145
    assert p1.vertices() == [Vec2I(0, 0), Vec2I(1000, 0), Vec2I(1000, 1000)]

    (p3,) = [p for p in l.all(LayoutPath) if p.layer == layers.Metal3]
    assert p3.width == 210
    assert p3.endtype == PathEndType.Custom
    assert p3.ext_bgn == p3.ext_end == 145
    assert p3.vertices() == [Vec2I(1000, 1000), Vec2I(0, 1000)]

    (via1,) = [r for r in l.all(LayoutRect) if r.layer == layers.Via1]
    assert via1.rect == Rect4I(905, 905, 1095, 1095)

    (via2,) = [r for r in l.all(LayoutRect) if r.layer == layers.Via2]
    assert via2.rect == Rect4I(905, 905, 1095, 1095)

    (m2,) = [r for r in l.all(LayoutRect) if r.layer == layers.Metal2]
    assert m2.rect == Rect4I(760, 850, 1240, 1150)


# if __name__=="__main__":
#     from ordec.layout import write_gds
#     import os
#     with open("out.gds", "wb") as f:
#         write_gds(layout_x(), f)

#     os.system("rm -rf drc_out")
#     os.system("python3 $ORDEC_PDK_IHP_SG13G2/libs.tech/klayout/tech/drc/run_drc.py --path out.gds --no_density --run_dir=drc_out")
#     os.system("klayout out.gds -m drc_out/out_*_full.lyrdb")
