# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests basic DRC + LVS in IHP130.
"""

from ordec.lib import ihp130
from .lib.ihp130_inv import Inv

def test_lvs_clean():
    assert ihp130.run_lvs(Inv().layout, Inv().symbol)

def test_lvs_missing_y():
    c = Inv(variant="missing_y")
    assert not ihp130.run_lvs(c.layout, c.symbol)

def test_lvs_vss_vdd_pins_swapped():
    c = Inv(variant="vss_vdd_pins_swapped")
    assert not ihp130.run_lvs(c.layout, c.symbol, use_tempdir=True)

def test_drc_clean():
    res = ihp130.run_drc(Inv().layout, use_tempdir=True)
    assert res.summary() == {}


def test_drc_violation():
    res = ihp130.run_drc(Inv(variant="thin_m1").layout, use_tempdir=True)
    assert res.summary() == {'M1.a': 2}

if __name__=="__main__":
    # Generate GDS + schematic netlist for manual inspection:
    ihp130.run_lvs(Inv().layout, Inv().symbol, use_tempdir=True)
