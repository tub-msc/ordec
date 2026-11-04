# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests basic DRC + LVS in SKY130.
"""

from ordec.core.schema import LvsItem, LvsItemType
import pytest

from ordec.core import *
from ordec.layout import SRouter
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


def test_route_stack():
    """Every metal with a turn, stacks in both directions and straight through."""
    layers = sky130.SKY130().layers
    l = Layout(ref_layers=layers)
    s = Solver(l)
    sr = SRouter(sky130.SKY130().default_routing_spec, layout=l, solver=s)
    sr.move(layers.met1, (0, 0))
    sr.wire((3000, 0))
    sr.layer(layers.met2)
    sr.wire((3000, 3000))
    sr.layer(layers.met3)
    sr.wire((6000, 3000))
    sr.layer(layers.met4)
    sr.wire((6000, 6000))
    sr.layer(layers.met5)
    sr.wire((16000, 6000))
    sr.layer(layers.met1)
    sr.wire((16000, -3000))
    sr.layer(layers.met5)
    sr.wire((26000, -3000))
    sr.move(layers.met5, (-6000, 4000))
    sr.wire((-6000, 14000))
    sr.layer(layers.met4)
    sr.wire((-9000, 14000))
    sr.layer(layers.met3)
    sr.wire((-9000, 11000))
    sr.layer(layers.met2)
    sr.wire((-12000, 11000))
    sr.layer(layers.met1)
    sr.wire((-12000, 8000))
    s.solve()
    assert sky130.run_drc(l.freeze(), use_tempdir=True).summary() == {}


def test_density():
    layers = sky130.SKY130().layers
    def filled(width):
        l = Layout(ref_layers=layers)
        l % LayoutRect(layer=layers.met1, rect=Rect4I(0, 0, width, 10000))
        return l
    with pytest.raises(ValueError):
        sky130.run_drc(filled(9000).freeze(), use_tempdir=True, density=True)
    def run(width):
        l = filled(width)
        l % LayoutRect(layer=layers.prBoundary, rect=Rect4I(0, 0, 10000, 10000))
        return sky130.run_drc(l.freeze(), use_tempdir=True, density=True,
            feol=False, beol=False, offgrid=False).summary()
    assert "m1.pd.1d" in run(9000)
    assert "m1.pd.1d" not in run(5000)
