# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
The sg13g2 place-and-route binding (ordec.lib.ihp130_pnr) and its sign-off.

The pin-rectangle and structural-rejection tests read the PDK but run no
KLayout. The DRC and LVS pair at the end is the engine's oracle and is the only
slow part of the P&R suite, so it covers two cells rather than the whole corpus
in tests/lib/pnr_cells.ord: a single-row block whose xor2 outputs need off-track
pin access, and a multi-row block with side straps, a power mesh and the shared
boustrophedon rails. Deselect them with ``-k "not drc_lvs"``.
"""

import pytest
import ordec.importer

from ordec.core import Layout
from ordec.layout.digital_pnr import place_and_route
from ordec.lib import ihp130
from ordec.lib.ihp130_pnr import (is_sg13g2_leaf, lef_pin_rects, sg13g2_grid,
    sg13g2_layers)
from .lib import pnr_cells as fx


def pnr(cell):
    """Run the engine over ``cell`` with the sg13g2 inputs."""
    return place_and_route(cell.schematic,
        Layout(cell=cell, symbol=cell.symbol), grid=sg13g2_grid(),
        stack=sg13g2_layers(), pin_rects=lef_pin_rects,
        is_leaf=is_sg13g2_leaf)


def test_lef_pin_rects_inverter():
    rects = lef_pin_rects("sg13g2_inv_1")
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
    rects = lef_pin_rects("sg13g2_nor2_1")

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
    with pytest.raises(ValueError, match="Metal1-only leaf cells"):
        lef_pin_rects("sg13g2_sdfbbp_1")


def test_grid_profile_is_shared():
    """The profile is a cacheable value, since the engine derives its
    per-floorplan variants rather than mutating it."""
    assert sg13g2_grid() is sg13g2_grid()


def test_split_supply_rejected():
    with pytest.raises(ValueError, match="Rail abutment"):
        pnr(fx.SplitSupply())


def test_misnamed_supply_rejected():
    with pytest.raises(ValueError, match="requires 'vdd'"):
        pnr(fx.MisnamedSupply())


@pytest.mark.parametrize("cell", [
    fx.RippleAdder(n=2),    # single row, off-track pin access from xor2's Y
    fx.DffArray(n=4),       # multi-row, so straps, mesh and shared rails
], ids=["ripple_adder", "dff_array"])
def test_drc_lvs_clean(cell):
    assert ihp130.run_drc(cell.layout).summary() == {}
    assert ihp130.run_lvs(cell.layout, cell.symbol).clean()
