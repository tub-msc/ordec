# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..core import *

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
