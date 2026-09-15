# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests place-and-route using sky130; runs DRC+LVS on small results.

The sky130hd stack exercises what sg13g2 cannot: per-layer track multiples,
via landing pads, li1 sub-layer pin access, well-abutment pins and power
stripes inside the routing window.
"""

import os
from pathlib import Path

import pytest
import ordec.importer


def stdcells_installed():
    root = os.environ.get("ORDEC_PDK_SKY130A")
    return root is not None and \
        (Path(root) / "libs.ref/sky130_fd_sc_hd").is_dir()


pytestmark = pytest.mark.skipif(not stdcells_installed(),
    reason="sky130_fd_sc_hd not installed under the sky130A PDK")


@pytest.fixture(scope="module")
def fx():
    from .lib import pnr_cells_sky130
    return pnr_cells_sky130


def test_lef_pin_rects_inverter(fx):
    rects = fx.pin_rects()["sky130_fd_sc_hd__inv_1"]
    # Signal pins on li1, rails on met1, well pins present but empty.
    assert rects["A"] == [(320, 1075, 650, 1315)]
    assert (0, -240, 1380, 240) in rects["VGND"]
    assert rects["VNB"] == []


@pytest.mark.parametrize("cell_name,n", [
    ("InvChain", 8),        # single cell type, li1 access
    ("RippleAdder", 4),     # multi-row, met4/met5 stripes, carry-chain fanout
    ("DffChain", 2),        # sequential cells: special devices, CDL combining
], ids=["inv_chain", "ripple_adder", "dff_chain"])
def test_drc_lvs_clean(fx, cell_name, n):
    from ordec.lib import sky130
    cell = getattr(fx, cell_name)(n=n)
    # The engine adds BEOL geometry only, and the foundry cells fail the
    # supplementary FEOL deck, which is calibrated for ORDeC's generators.
    assert sky130.run_drc(cell.layout, feol=False).summary() == {}
    assert sky130.run_lvs(cell.layout, cell.symbol).clean()
