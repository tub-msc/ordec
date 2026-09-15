# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests place-and-route using ihp130; runs DRC+LVS on a small result.
"""

from dataclasses import replace

import pytest
import ordec.importer

from ordec.core import Layout, LayoutRect
from ordec.layout.pnr import place_and_route, PdnRing, PdnVia
from ordec.lib import ihp130
from .lib import pnr_cells as fx


def pnr(cell):
    """Run the engine over ``cell`` with the sg13g2 inputs."""
    return place_and_route(cell.schematic,
        Layout(cell=cell, symbol=cell.symbol), grid=ihp130.grid,
        routing_spec=ihp130.SG13G2().default_routing_spec,
        pin_rects=fx.pin_rects())


def test_lef_pin_rects_inverter():
    rects = fx.pin_rects()["sg13g2_inv_1"]
    assert set(rects) == {"A", "Y", "VDD", "VSS"}
    assert rects["A"] == [(310, 1520, 625, 1850)]
    assert rects["Y"] == [(855, 610, 1085, 3175)]
    # The rail spans the cell, which is what sets the placement pitch.
    assert (0, 3560, 1440, 4000) in rects["VDD"]


def test_lef_pin_rects_are_per_pin():
    """Nor2's Y and B overlap by bounding box but not as LEF rectangles.

    A bbox-driven via would short the two nets, so the router needs the clean
    per-pin rects to place its access on the intended pin.
    """
    rects = fx.pin_rects()["sg13g2_nor2_1"]

    def bbox(rs):
        return (min(r[0] for r in rs), min(r[1] for r in rs),
            max(r[2] for r in rs), max(r[3] for r in rs))

    y, b = bbox(rects["Y"]), bbox(rects["B"])
    assert y[0] < b[2] and b[0] < y[2] and y[1] < b[3] and b[1] < y[3]
    for ry in rects["Y"]:
        for rb in rects["B"]:
            assert ry[2] <= rb[0] or rb[2] <= ry[0] \
                or ry[3] <= rb[1] or rb[3] <= ry[1]


def test_upper_metal_leaf_rejected():
    """The engine routes the metals above the leaf cells, so a leaf with its
    own geometry up there is rejected instead of being silently shorted."""
    with pytest.raises(ValueError, match="pins on Metal1 only"):
        fx.pin_rects()["sg13g2_sdfbbp_1"]


def test_split_supply_rejected():
    with pytest.raises(ValueError, match="Rail abutment"):
        pnr(fx.SplitSupply())


def test_misnamed_supply_rejected():
    with pytest.raises(ValueError, match="requires 'vdd'"):
        pnr(fx.MisnamedSupply())


@pytest.mark.parametrize("cell", [
    fx.RippleAdder(n=2),    # off-track pin access from xor2's Y
    fx.DffArray(n=4),       # multi-row, so stripes, rail taps and shared rails
], ids=["ripple_adder", "dff_array"])
def test_drc_lvs_clean(cell):
    assert ihp130.run_drc(cell.layout).summary() == {}
    assert ihp130.run_lvs(cell.layout, cell.symbol).clean()


def test_ring_drc_lvs_clean():
    """A core power ring in the die margin stays DRC and LVS clean.

    The ring is opt-in through PdnSpec.ring, so the other oracles keep the
    stripes-only PDN. sg13g2 carries it on the two top metals, TopMetal2 for
    the horizontal segments and TopMetal1 for the vertical ones.
    """
    ring = PdnRing(h_level=6, v_level=5, width=2200, spacing=2000, offset=3000,
        via=PdnVia(cut=900, cut_pitch=1960, encl_above=500, encl_below=500))
    grid = replace(ihp130.grid, pdn=replace(ihp130.grid.pdn, ring=ring))
    cell = fx.DffArray(n=4)
    layout = Layout(cell=cell, symbol=cell.symbol)
    place_and_route(cell.schematic, layout, grid=grid,
        routing_spec=ihp130.SG13G2().default_routing_spec,
        pin_rects=fx.pin_rects(), filler_cells=fx.FILL)
    layout = layout.freeze()
    # The ring emits into the negative margin outside the core.
    assert min(r.rect.ly for r in layout.all(LayoutRect)) < 0
    assert ihp130.run_drc(layout).summary() == {}
    assert ihp130.run_lvs(layout, cell.symbol).clean()
