# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# Reference layout for VcoRing, built from Layout.dump() output.
# Nmos/Pmos instances use the actual ihp130 library layouts.
# NPath naming is omitted since compare() only checks geometry.

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ordec.importer
from vco_pseudodiff import VcoHalfStage, VcoRing
from ordec.lib.ihp130 import SG13G2, Nmos, Pmos
from ordec.layout import compare
from ordec.core import *

layers = SG13G2().layers
nmos_layout = Nmos(l='130n', w='300n').layout
pmos_layout = Pmos(l='130n', w='300n').layout


def build_halfstage_ref():
    """Reference layout for VcoHalfStage, from VcoHalfStage().layout.dump()."""
    hs = VcoHalfStage()
    l = Layout(ref_layers=layers, symbol=hs.symbol, cell=hs)
    sym = hs.symbol

    # Transistor instances
    l % LayoutInstance(pos=Vec2I(0, 0), orientation=D4.R0, ref=pmos_layout)
    l % LayoutInstance(pos=Vec2I(0, -1800), orientation=D4.R0, ref=nmos_layout)
    l % LayoutInstance(pos=Vec2I(510, -1800), orientation=D4.R0, ref=nmos_layout)
    l % LayoutInstance(pos=Vec2I(510, 0), orientation=D4.R0, ref=pmos_layout)
    l % LayoutInstance(pos=Vec2I(1020, -1800), orientation=D4.R0, ref=nmos_layout)
    l % LayoutInstance(pos=Vec2I(1020, 0), orientation=D4.R0, ref=pmos_layout)
    l % LayoutInstance(pos=Vec2I(1530, -1800), orientation=D4.R0, ref=nmos_layout)
    l % LayoutInstance(pos=Vec2I(1530, 0), orientation=D4.R0, ref=pmos_layout)

    # Poly gate stripes
    l % LayoutRect(layer=layers.GatPoly, rect=Rect4I(340, -1800, 470, 660))
    l % LayoutRect(layer=layers.GatPoly, rect=Rect4I(850, -1800, 980, 660))
    l % LayoutRect(layer=layers.GatPoly, rect=Rect4I(1360, -1800, 1490, 660))
    l % LayoutRect(layer=layers.GatPoly, rect=Rect4I(1870, -1800, 2000, 660))

    # Poly contact 0 (rst_n)
    l % LayoutRect(layer=layers.GatPoly, rect=Rect4I(170, -1120, 470, -820))
    l % LayoutRect(layer=layers.Cont, rect=Rect4I(240, -1050, 400, -890))
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(190, -1120, 400, -520))
    r % LayoutPin(pin=sym.rst_n)

    # Poly contact 1 (inp)
    l % LayoutRect(layer=layers.GatPoly, rect=Rect4I(680, -1120, 980, -820))
    l % LayoutRect(layer=layers.Cont, rect=Rect4I(750, -1050, 910, -890))
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(700, -1120, 910, -520))
    r % LayoutPin(pin=sym.inp)

    # Poly contact 2 (fb)
    l % LayoutRect(layer=layers.GatPoly, rect=Rect4I(1360, -1120, 1660, -820))
    l % LayoutRect(layer=layers.Cont, rect=Rect4I(1430, -1050, 1590, -890))
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(1430, -1120, 1640, -520))
    r % LayoutPin(pin=sym.fb)

    # Poly contact 3 (gate tie, no pin)
    l % LayoutRect(layer=layers.GatPoly, rect=Rect4I(1700, -320, 2000, -20))
    l % LayoutRect(layer=layers.Cont, rect=Rect4I(1770, -250, 1930, -90))

    # outbar horizontal + vertical routing
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(70, -275, 2430, -65))
    r % LayoutPin(pin=sym.out)
    l % LayoutRect(layer=layers.Metal1, rect=Rect4I(1090, -1620, 1250, 480))
    l % LayoutRect(layer=layers.Metal1, rect=Rect4I(70, -275, 230, 480))
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(2630, -1620, 2840, 480))
    r % LayoutPin(pin=sym.out_n)
    l % LayoutRect(layer=layers.Metal1, rect=Rect4I(2110, 180, 2630, 480))
    l % LayoutRect(layer=layers.Metal1, rect=Rect4I(2110, -1620, 2630, -1320))

    # vdd bar
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(-430, 880, 2770, 1280))
    r % LayoutPin(pin=sym.vdd)
    l % LayoutRect(layer=layers.Metal1, rect=Rect4I(580, 180, 740, 880))
    l % LayoutRect(layer=layers.Metal1, rect=Rect4I(1600, 180, 1760, 880))

    # vss bar
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(-430, -2520, 2770, -2120))
    r % LayoutPin(pin=sym.vss)
    l % LayoutRect(layer=layers.Metal1, rect=Rect4I(70, -2120, 230, -1320))
    l % LayoutRect(layer=layers.Metal1, rect=Rect4I(1600, -2120, 1760, -1320))
    l % LayoutRect(layer=layers.Metal1, rect=Rect4I(580, -1920, 740, -1320))

    # nwell
    l % LayoutRect(layer=layers.NWell, rect=Rect4I(-310, -130, 2650, 790))

    return l.freeze()


def build_ring_ref():
    """Reference layout for VcoRing, from VcoRing().layout.dump()."""
    vr = VcoRing()
    sym = vr.symbol
    hs_ref = build_halfstage_ref()
    l = Layout(ref_layers=layers, symbol=sym, cell=vr)

    # nwell
    l % LayoutRect(layer=layers.NWell, rect=Rect4I(-2650, -2290, 3510, 130))

    # vdd_st bar
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(-2770, -1280, 3630, -880))
    r % LayoutPin(pin=sym.vdd_st)

    # vss_st bars (two bars, both pinned to vss_st)
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(-2770, -4680, 3630, -4280))
    r % LayoutPin(pin=sym.vss_st)
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(-2770, 2120, 3630, 2520))
    r % LayoutPin(pin=sym.vss_st)

    # HalfStage instances (4 total: 2 stage_p, 2 stage_n)
    l % LayoutInstance(pos=Vec2I(0, 0), orientation=D4.R180, ref=hs_ref)
    l % LayoutInstance(pos=Vec2I(0, -2160), orientation=D4.MY, ref=hs_ref)
    l % LayoutInstance(pos=Vec2I(860, 0), orientation=D4.MX, ref=hs_ref)
    l % LayoutInstance(pos=Vec2I(860, -2160), orientation=D4.R0, ref=hs_ref)

    # out_n vertical Metal1 bars + pins
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(-2840, -3780, -2630, -1680))
    r % LayoutPin(pin=sym.out_n[0])
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(3490, -3780, 3700, -1680))
    r % LayoutPin(pin=sym.out_n[1])

    # out_p vertical Metal1 bars + pins
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(-2840, -480, -2630, 1620))
    r % LayoutPin(pin=sym.out_p[0])
    r = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(3490, -480, 3700, 1620))
    r % LayoutPin(pin=sym.out_p[1])

    # rst_n SRouter Metal2 paths (L-shaped route + vertical stub)
    l % LayoutPath(layer=layers.Metal2, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(1155, -2980), Vec2I(430, -2980),
                  Vec2I(430, 820), Vec2I(-295, 820)])
    r = l % LayoutPath(layer=layers.Metal2, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(430, 820), Vec2I(430, 3320)])
    r % LayoutPin(pin=sym.rst_n)

    # rsttie RectPaths (dump layer=21 → Metal2)
    l % LayoutRectPath(layer=layers.Metal2, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        start_direction=RectDirection.Horizontal,
        vertices=[Vec2I(-295, -2980), Vec2I(-295, -1080)])
    l % LayoutRectPath(layer=layers.Metal2, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        start_direction=RectDirection.Horizontal,
        vertices=[Vec2I(1155, 820), Vec2I(1155, -1080)])

    # outv_p paths (dump layer=21 → Metal2, vertical)
    l % LayoutPath(layer=layers.Metal2, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(-1535, -2980), Vec2I(-1535, 170)])
    l % LayoutPath(layer=layers.Metal2, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(2395, -2980), Vec2I(2395, 170)])

    # outv_n paths (dump layer=21 → Metal2, L-shaped)
    l % LayoutPath(layer=layers.Metal2, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(-1535, 820), Vec2I(-2280, 820), Vec2I(-2280, -2330)])
    l % LayoutPath(layer=layers.Metal2, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(2395, 820), Vec2I(3140, 820), Vec2I(3140, -2330)])

    # Metal3 horizontal paths (dump layer=27)
    l % LayoutPath(layer=layers.Metal3, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(-2280, -2330), Vec2I(1665, -2330)])
    l % LayoutPath(layer=layers.Metal3, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(-1535, 170), Vec2I(1665, 170)])
    l % LayoutPath(layer=layers.Metal3, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(2395, -1830), Vec2I(-805, -1830)])
    l % LayoutPath(layer=layers.Metal3, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(3140, -330), Vec2I(-805, -330)])

    # Metal2 vertical stubs (dump layer=21)
    l % LayoutPath(layer=layers.Metal2, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(1665, -2980), Vec2I(1665, -2330)])
    l % LayoutPath(layer=layers.Metal2, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(1665, 820), Vec2I(1665, 170)])
    l % LayoutPath(layer=layers.Metal2, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(-805, -2980), Vec2I(-805, -1830)])
    l % LayoutPath(layer=layers.Metal2, width=200,
        endtype=PathEndType.Custom, ext_bgn=150, ext_end=150,
        vertices=[Vec2I(-805, 820), Vec2I(-805, -330)])

    # Via1 rects
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(-390, -3075, -200, -2885))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(-390, -1175, -200, -985))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(1060, 725, 1250, 915))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(1060, -1175, 1250, -985))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(1060, -3075, 1250, -2885))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(-390, 725, -200, 915))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(-1630, 75, -1440, 265))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(-2375, -2425, -2185, -2235))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(2300, 75, 2490, 265))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(3045, -2425, 3235, -2235))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(1570, -3075, 1760, -2885))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(1570, 725, 1760, 915))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(-900, -3075, -710, -2885))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(-900, 725, -710, 915))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(-1630, -3075, -1440, -2885))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(-1630, 725, -1440, 915))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(2300, -3075, 2490, -2885))
    l % LayoutRect(layer=layers.Via1, rect=Rect4I(2300, 725, 2490, 915))

    # Via2 rects
    l % LayoutRect(layer=layers.Via2, rect=Rect4I(-2375, -2425, -2185, -2235))
    l % LayoutRect(layer=layers.Via2, rect=Rect4I(1570, -2425, 1760, -2235))
    l % LayoutRect(layer=layers.Via2, rect=Rect4I(-1630, 75, -1440, 265))
    l % LayoutRect(layer=layers.Via2, rect=Rect4I(1570, 75, 1760, 265))
    l % LayoutRect(layer=layers.Via2, rect=Rect4I(2300, -1925, 2490, -1735))
    l % LayoutRect(layer=layers.Via2, rect=Rect4I(-900, -1925, -710, -1735))
    l % LayoutRect(layer=layers.Via2, rect=Rect4I(3045, -425, 3235, -235))
    l % LayoutRect(layer=layers.Via2, rect=Rect4I(-900, -425, -710, -235))

    return l


def test_vco_pseudodiff_layout():
    ref = build_ring_ref()
    actual = VcoRing().layout
    assert compare(actual, ref) is None
