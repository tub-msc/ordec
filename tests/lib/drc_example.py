# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *
from ordec.core.schema import DrcReport
from ordec.lib.ihp130 import SG13G2, run_drc


@generate_func
def layout() -> Layout:
    """Layout with intentional DRC violations for testing."""
    pdk = SG13G2()
    layers = pdk.layers
    layout = Layout(ref_layers=layers)

    # --- Metal1 spacing violations ---
    # IHP Metal1 min spacing is 180nm, we use 100nm gap

    # Spacing violation 1: two rectangles too close
    poly1 = layout % LayoutPoly(layer=layers.Metal1)
    layout % PolyVec2I(ref=poly1, order=0, pos=Vec2I(0, 0))
    layout % PolyVec2I(ref=poly1, order=1, pos=Vec2I(1000, 0))
    layout % PolyVec2I(ref=poly1, order=2, pos=Vec2I(1000, 1000))
    layout % PolyVec2I(ref=poly1, order=3, pos=Vec2I(0, 1000))

    poly2 = layout % LayoutPoly(layer=layers.Metal1)
    layout % PolyVec2I(ref=poly2, order=0, pos=Vec2I(1100, 0))  # 100nm gap
    layout % PolyVec2I(ref=poly2, order=1, pos=Vec2I(2100, 0))
    layout % PolyVec2I(ref=poly2, order=2, pos=Vec2I(2100, 1000))
    layout % PolyVec2I(ref=poly2, order=3, pos=Vec2I(1100, 1000))

    # Spacing violation 2: another pair too close
    poly3 = layout % LayoutPoly(layer=layers.Metal1)
    layout % PolyVec2I(ref=poly3, order=0, pos=Vec2I(0, 1500))
    layout % PolyVec2I(ref=poly3, order=1, pos=Vec2I(500, 1500))
    layout % PolyVec2I(ref=poly3, order=2, pos=Vec2I(500, 2500))
    layout % PolyVec2I(ref=poly3, order=3, pos=Vec2I(0, 2500))

    poly4 = layout % LayoutPoly(layer=layers.Metal1)
    layout % PolyVec2I(ref=poly4, order=0, pos=Vec2I(600, 1500))  # 100nm gap
    layout % PolyVec2I(ref=poly4, order=1, pos=Vec2I(1100, 1500))
    layout % PolyVec2I(ref=poly4, order=2, pos=Vec2I(1100, 2500))
    layout % PolyVec2I(ref=poly4, order=3, pos=Vec2I(600, 2500))

    # --- Metal1 width violations ---
    # IHP Metal1 min width is 160nm, we use 100nm

    # Width violation 1
    poly5 = layout % LayoutPoly(layer=layers.Metal1)
    layout % PolyVec2I(ref=poly5, order=0, pos=Vec2I(3000, 0))
    layout % PolyVec2I(ref=poly5, order=1, pos=Vec2I(3100, 0))  # 100nm wide
    layout % PolyVec2I(ref=poly5, order=2, pos=Vec2I(3100, 1000))
    layout % PolyVec2I(ref=poly5, order=3, pos=Vec2I(3000, 1000))

    # Width violation 2
    poly6 = layout % LayoutPoly(layer=layers.Metal1)
    layout % PolyVec2I(ref=poly6, order=0, pos=Vec2I(3500, 0))
    layout % PolyVec2I(ref=poly6, order=1, pos=Vec2I(3600, 0))  # 100nm wide
    layout % PolyVec2I(ref=poly6, order=2, pos=Vec2I(3600, 800))
    layout % PolyVec2I(ref=poly6, order=3, pos=Vec2I(3500, 800))

    # Width violation 3
    poly7 = layout % LayoutPoly(layer=layers.Metal1)
    layout % PolyVec2I(ref=poly7, order=0, pos=Vec2I(4000, 0))
    layout % PolyVec2I(ref=poly7, order=1, pos=Vec2I(4050, 0))  # 50nm wide
    layout % PolyVec2I(ref=poly7, order=2, pos=Vec2I(4050, 500))
    layout % PolyVec2I(ref=poly7, order=3, pos=Vec2I(4000, 500))

    # --- Metal2 violations ---
    # Metal2 min width is 200nm, min spacing is 210nm

    # Metal2 width violation
    poly8 = layout % LayoutPoly(layer=layers.Metal2)
    layout % PolyVec2I(ref=poly8, order=0, pos=Vec2I(5000, 0))
    layout % PolyVec2I(ref=poly8, order=1, pos=Vec2I(5100, 0))  # 100nm wide
    layout % PolyVec2I(ref=poly8, order=2, pos=Vec2I(5100, 1000))
    layout % PolyVec2I(ref=poly8, order=3, pos=Vec2I(5000, 1000))

    # Metal2 spacing violation
    poly9 = layout % LayoutPoly(layer=layers.Metal2)
    layout % PolyVec2I(ref=poly9, order=0, pos=Vec2I(6000, 0))
    layout % PolyVec2I(ref=poly9, order=1, pos=Vec2I(6500, 0))
    layout % PolyVec2I(ref=poly9, order=2, pos=Vec2I(6500, 1000))
    layout % PolyVec2I(ref=poly9, order=3, pos=Vec2I(6000, 1000))

    poly10 = layout % LayoutPoly(layer=layers.Metal2)
    layout % PolyVec2I(ref=poly10, order=0, pos=Vec2I(6600, 0))  # 100nm gap
    layout % PolyVec2I(ref=poly10, order=1, pos=Vec2I(7100, 0))
    layout % PolyVec2I(ref=poly10, order=2, pos=Vec2I(7100, 1000))
    layout % PolyVec2I(ref=poly10, order=3, pos=Vec2I(6600, 1000))

    # --- Via1 violations ---
    # Via1 must be exactly 190nm x 190nm, we make wrong-sized ones

    # Wrong-sized Via1 (too small: 100nm x 100nm)
    via1 = layout % LayoutPoly(layer=layers.Via1)
    layout % PolyVec2I(ref=via1, order=0, pos=Vec2I(8000, 0))
    layout % PolyVec2I(ref=via1, order=1, pos=Vec2I(8100, 0))
    layout % PolyVec2I(ref=via1, order=2, pos=Vec2I(8100, 100))
    layout % PolyVec2I(ref=via1, order=3, pos=Vec2I(8000, 100))

    # Wrong-sized Via1 (too big: 300nm x 300nm)
    via2 = layout % LayoutPoly(layer=layers.Via1)
    layout % PolyVec2I(ref=via2, order=0, pos=Vec2I(8500, 0))
    layout % PolyVec2I(ref=via2, order=1, pos=Vec2I(8800, 0))
    layout % PolyVec2I(ref=via2, order=2, pos=Vec2I(8800, 300))
    layout % PolyVec2I(ref=via2, order=3, pos=Vec2I(8500, 300))

    return layout


@generate_func
def drc_report() -> DrcReport:
    """Run IHP130 DRC on a layout with violations."""
    return run_drc(layout(), variant='minimal')
