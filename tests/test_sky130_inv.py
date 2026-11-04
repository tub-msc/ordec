# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests basic DRC + LVS in SKY130.
"""

from ordec.core.schema import LvsItem, LvsItemType
from ordec.lib import sky130
from .lib.sky130_inv import Inv
from .lib.sky130_mos2f import Mos2f

def test_lvs_clean():
    c = Inv()
    lvs_report = sky130.run_lvs(c.layout, c.symbol)
    assert lvs_report.clean()
    # MOSFET device items ("Mpd"/"Mpu" in SPICE) cross-reference the
    # schematic's SchemInstances.
    devices = {i.schem_name: i.schem for i in lvs_report.all(LvsItem)
               if i.item_type == LvsItemType.Device}
    assert devices == {'pd': c.schematic.pd, 'pu': c.schematic.pu}

def test_lvs_missing_y():
    c = Inv(variant="missing_y")
    lvs_report = sky130.run_lvs(c.layout, c.symbol)
    assert not lvs_report.clean()

def test_lvs_vss_vdd_pins_swapped():
    c = Inv(variant="vss_vdd_pins_swapped")
    lvs_report = sky130.run_lvs(c.layout, c.symbol, use_tempdir=True)
    assert not lvs_report.clean()

def test_drc_clean():
    res = sky130.run_drc(Inv().layout, use_tempdir=True)
    assert res.summary() == {}

def test_drc_violation():
    res = sky130.run_drc(Inv(variant="thin_m1").layout, use_tempdir=True)
    assert res.summary() == {'m1.1': 2}

def test_mos_two_finger():
    # The deck's global substrate net must carry the name of the net tying
    # the substrate tap, here the bulk pin b.
    cell = Mos2f()
    assert sky130.run_drc(cell.layout, use_tempdir=True).summary() == {}
    assert sky130.run_lvs(cell.layout, cell.symbol, substrate_net='b').clean()
