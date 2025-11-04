# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
import tempfile

from public import public
from ..core import *
from .makevias import makevias
from .gds_out import write_gds
from . import klayout

@public
class SG13G2(Cell):
    @generate
    def layers(self):
        s = LayerStack(cell=self)

        s.unit = R('1n')

        # Frontend layers
        # ---------------

        s.Activ = Layer(
            gdslayer_shapes=GdsLayer(layer=1, data_type=0),
            style_fill=rgb_color("#00ff00"),
            )

        s.GatPoly = Layer(
            gdslayer_shapes=GdsLayer(layer=5, data_type=0),
            style_fill=rgb_color("#bf4026"),
            )
        s.GatPoly.pin = Layer(
            gdslayer_shapes=GdsLayer(layer=5, data_type=2),
            style_fill=rgb_color("#bf4026"),
            )
        
        s.Cont = Layer(
            gdslayer_shapes=GdsLayer(layer=6, data_type=0),
            style_stroke=rgb_color("#00ffff"),
            style_crossrect=True,
            )

        s.pSD = Layer(
            gdslayer_shapes=GdsLayer(layer=14, data_type=0),
            style_fill=rgb_color("#ccb899"),
            )

        s.NWell = Layer(
            gdslayer_shapes=GdsLayer(layer=31, data_type=0),
            style_fill=rgb_color("#268c6b"),
            )

        # Metal stack
        # -----------

        def addmetal(name, layer, color):
            setattr(s, name, Layer(
                gdslayer_shapes=GdsLayer(layer=layer, data_type=0),
                style_fill=color,
            ))
            getattr(s, name).pin = Layer(
                gdslayer_text=GdsLayer(layer=layer, data_type=25),
                gdslayer_shapes=GdsLayer(layer=layer, data_type=2),
                style_fill=color,
            )

        def addvia(name, layer, color):
            setattr(s, name, Layer(
                gdslayer_shapes=GdsLayer(layer=layer, data_type=0),
                style_stroke=color,
                style_crossrect=True,
            ))

        addmetal("Metal1", 8, rgb_color("#39bfff"))
        addvia("Via1", 19, rgb_color("#ccccff"))
        addmetal("Metal2", 10, rgb_color("#ccccd9"))
        addvia("Via2", 29, rgb_color("#ff3736"))
        addmetal("Metal3", 30, rgb_color("#d80000"))
        addvia("Via3", 49, rgb_color("#9ba940"))
        addmetal("Metal4", 50, rgb_color("#93e837"))
        addvia("Via4", 66, rgb_color("#deac5e"))
        addmetal("Metal5", 67, rgb_color("#dcd146"))
        addvia("TopVia1", 125, rgb_color("#ffe6bf"))
        addmetal("TopMetal1", 126, rgb_color("#ffe6bf"))
        addvia("TopVia2", 133, rgb_color("#ff8000"))
        addmetal("TopMetal2", 134, rgb_color("#ff8000"))

        # Other layers
        # ------------

        s.EXTBlock = Layer(
            gdslayer_shapes=GdsLayer(layer=111, data_type=0),
            style_fill=rgb_color("#5e00e6"),
            )

        s.MIM = Layer(
            gdslayer_shapes=GdsLayer(layer=36, data_type=0),
            style_fill=rgb_color("#268c6b"),
            )

        s.Substrate = Layer(
            gdslayer_shapes=GdsLayer(layer=40, data_type=0),
            style_fill=rgb_color("#ffffff"),
            )

        s.HeatTrans = Layer(
            gdslayer_shapes=GdsLayer(layer=51, data_type=0),
            style_fill=rgb_color("#8c8ca6"),
            )

        s.TEXT = Layer(
            gdslayer_text=GdsLayer(layer=63, data_type=0),
            )

        s.Recog = Layer(
            gdslayer_shapes=GdsLayer(layer=99, data_type=31),
            style_fill=rgb_color("#bdcccc"),
            )

        s.Vmim = Layer(
            gdslayer_shapes=GdsLayer(layer=129, data_type=0),
            style_fill=rgb_color("#ffe6bf"),
            )
        
        s.prBoundary = Layer(
            gdslayer_shapes=GdsLayer(layer=189, data_type=4), # data_type 4 or 0?
            style_fill=rgb_color("#9900e6"),
            style_stroke=rgb_color("#ff00ff"),
            )

        return s

@public
class Nmos(Cell):

    l = Parameter(R)  #: Length
    w = Parameter(R)  #: Width
    ng = Parameter(int, default=1)  #: Number of gate fingers

    @generate
    def layout(self) -> Layout:
        # See also: ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib/ihp/nmos_code.py
        layers = SG13G2().layers
        l = Layout(ref_layers=layers, cell=self)
        s = Solver(l)

        L = int(self.l/R("1n"))
        W = int(self.w/R("1n") / self.ng)

        l.mkpath('polys')
        l.mkpath('sd')

        def add_sd(i):
            nonlocal l, s, x_cur
            l.sd[i] = LayoutRect(layer=layers.Metal1)
            sd = l.sd[i]
            s.constrain(sd.rect.width == 160)
            s.constrain(sd.rect.cy == l.activ.rect.cy)
            s.constrain(sd.rect.lx == x_cur)
            if W >= 300:
                s.constrain(sd.rect.height == W)
            else:
                s.constrain(sd.rect.height == 260)

                activ_ext = l % LayoutRect(layer=layers.Activ)
                s.constrain(activ_ext.rect.cx == sd.rect.cx)
                s.constrain(activ_ext.rect.cy == sd.rect.cy)
                s.constrain(activ_ext.rect.width == 300)
                s.constrain(activ_ext.rect.height == 300)
            x_cur = sd.rect.ux    

        def add_poly(i):
            nonlocal l, s, x_cur
            x_cur += 140
            l.polys[i] = LayoutRect(layer=layers.GatPoly)
            poly = l.polys[i]
            s.constrain(poly.rect.cy == l.activ.rect.cy)
            s.constrain(poly.rect.width == L)
            s.constrain(poly.rect.lx == x_cur)
            s.constrain(poly.rect.ly + 100 == l.activ.rect.ly)
            s.constrain(poly.rect.ly == 0)
            x_cur = poly.rect.ux + 140

        l.activ = LayoutRect(layer=layers.Activ)
        s.constrain(l.activ.rect.height == W)
        s.constrain(l.activ.rect.lx == 0)
        x_cur = l.activ.rect.lx + 70

        add_sd(0)
        for i in range(self.ng):
            add_poly(i)
            add_sd(i+1)

        s.constrain(l.activ.rect.ux == x_cur + 70)

        s.solve()

        for i in range(self.ng + 1):
            makevias(l, l.sd[i].rect, layers.Cont, 
                size=Vec2I(160, 160),
                spacing=Vec2I(180, 180),
                margin=Vec2I(50, 50),
                cols=1,
                )
            
        return l



@public
def run_drc(l: Layout, variant='maximal'):
    if variant not in ('minimal', 'maximal'):
        raise ValueError("variant must be either 'minimal' or 'maximal'.")
    ihp130_root = Path(os.environ['ORDEC_PDK_IHP_SG13G2'])
    script = ihp130_root / "libs.tech/klayout/tech/drc/sg13g2_minimal.lydrc"

    with tempfile.TemporaryDirectory() as cwd_str:
        cwd = Path(cwd_str)
        with open(cwd / "layout.gds", "wb") as f:
            name_of_layout = write_gds(l, f)

        klayout.run(script, cwd,
            in_gds="layout.gds",
            report_file="drc.xml",
            log_file="drc.log",
            cell=name_of_layout[l],
            )

        log = (cwd / "drc.log").read_text() # currently ignored
        return klayout.parse_rdb(cwd / "drc.xml", name_of_layout)
