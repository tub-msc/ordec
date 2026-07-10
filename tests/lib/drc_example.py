# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *
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
    layout % LayoutRect(layer=layers.Metal1, rect=Rect4I(0, 0, 1000, 1000))
    layout % LayoutRect(layer=layers.Metal1, rect=Rect4I(1100, 0, 2100, 1000))  # 100nm gap

    # Spacing violation 2: another pair too close
    layout % LayoutRect(layer=layers.Metal1, rect=Rect4I(0, 1500, 500, 2500))
    layout % LayoutRect(layer=layers.Metal1, rect=Rect4I(600, 1500, 1100, 2500))  # 100nm gap

    # --- Metal1 width violations ---
    # IHP Metal1 min width is 160nm, we use 100nm

    layout % LayoutRect(layer=layers.Metal1, rect=Rect4I(3000, 0, 3100, 1000))  # 100nm wide
    layout % LayoutRect(layer=layers.Metal1, rect=Rect4I(3500, 0, 3600, 800))  # 100nm wide
    layout % LayoutRect(layer=layers.Metal1, rect=Rect4I(4000, 0, 4050, 500))  # 50nm wide

    # --- Metal2 violations ---
    # Metal2 min width is 200nm, min spacing is 210nm

    # Metal2 width violation
    layout % LayoutRect(layer=layers.Metal2, rect=Rect4I(5000, 0, 5100, 1000))  # 100nm wide

    # Metal2 spacing violation
    layout % LayoutRect(layer=layers.Metal2, rect=Rect4I(6000, 0, 6500, 1000))
    layout % LayoutRect(layer=layers.Metal2, rect=Rect4I(6600, 0, 7100, 1000))  # 100nm gap

    # --- Via1 violations ---
    # Via1 must be exactly 190nm x 190nm, we make wrong-sized ones

    # Wrong-sized Via1 (too small: 100nm x 100nm)
    layout % LayoutRect(layer=layers.Via1, rect=Rect4I(8000, 0, 8100, 100))

    # Wrong-sized Via1 (too big: 300nm x 300nm)
    layout % LayoutRect(layer=layers.Via1, rect=Rect4I(8500, 0, 8800, 300))

    return layout


@generate_func
def drc_report() -> DrcReport:
    """Run IHP130 DRC on a layout with violations."""
    return run_drc(layout(), variant='minimal')
