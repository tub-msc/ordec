# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Shared tests for the layout-capable PDKs (IHP130 and SKY130): DRC + LVS on
equivalent Inv testcases, the multi-finger MOS LVS pathway, and DRC, LVS and
ngspice checks of the passive devices. PDK-specific behavior (meander
geometry details, parameter bounds) stays in the per-PDK test files.
"""

import math
import sys

import pytest

from ordec.core import *
from ordec.core.schema import LvsItem, LvsItemType
from ordec.lib import ihp130, sky130, Gnd, Vdc
from .lib.ihp130_inv import Inv as Ihp130Inv
from .lib.sky130_inv import Inv as Sky130Inv
from .lib.pdk_mos2f import Mos2f
from .lib.thinwrap import thin_wrapper_cell


def pdklib(cell):
    """The PDK library module a device cell belongs to."""
    return sys.modules[type(cell).__module__]

def short_id(cell):
    return f"{type(cell).__module__.rsplit('.', 1)[-1]}-{type(cell).__name__}"


# Inverter: schematic/layout testcases built the same way on both PDKs
# ---------------------------------------------------------------------

# Per PDK: library module, Inv testcase and the expected DRC summary of the
# thin_m1 layout variant (the min-width rule names differ between decks).
INV_PDKS = {
    'ihp130': (ihp130, Ihp130Inv, {'M1.a': 2}),
    'sky130': (sky130, Sky130Inv, {'m1.1': 2}),
}

@pytest.fixture(params=INV_PDKS.keys())
def pdk_inv(request):
    return INV_PDKS[request.param]

def test_inv_lvs_clean(pdk_inv):
    lib, Inv, thin_m1_summary = pdk_inv
    c = Inv()
    lvs_report = lib.run_lvs(c.layout, c.symbol)
    assert lvs_report.clean()
    # MOSFET device items ("Mpd"/"Mpu" in SPICE) cross-reference the
    # schematic's SchemInstances.
    devices = {i.schem_name: i.schem for i in lvs_report.all(LvsItem)
               if i.item_type == LvsItemType.Device}
    assert devices == {'pd': c.schematic.pd, 'pu': c.schematic.pu}

def test_inv_lvs_missing_y(pdk_inv):
    lib, Inv, thin_m1_summary = pdk_inv
    c = Inv(variant="missing_y")
    lvs_report = lib.run_lvs(c.layout, c.symbol)
    assert not lvs_report.clean()

def test_inv_lvs_vss_vdd_pins_swapped(pdk_inv):
    lib, Inv, thin_m1_summary = pdk_inv
    c = Inv(variant="vss_vdd_pins_swapped")
    lvs_report = lib.run_lvs(c.layout, c.symbol, use_tempdir=True)
    assert not lvs_report.clean()

def test_inv_drc_clean(pdk_inv):
    lib, Inv, thin_m1_summary = pdk_inv
    res = lib.run_drc(Inv().layout, use_tempdir=True)
    assert res.summary() == {}

def test_inv_drc_violation(pdk_inv):
    lib, Inv, thin_m1_summary = pdk_inv
    res = lib.run_drc(Inv(variant="thin_m1").layout, use_tempdir=True)
    assert res.summary() == thin_m1_summary


# MOS: multi-finger LVS pathway (parallel extracted fingers vs. one card)
# -----------------------------------------------------------------------

MOS_PDKS = {'ihp130': ihp130, 'sky130': sky130}

def mos2f_run_lvs(pdk, cell):
    if pdk == 'sky130':
        # The SKY130 deck's global substrate net must carry the name of the
        # net tying the substrate tap, here the bulk pin b.
        return sky130.run_lvs(cell.layout, cell.symbol, substrate_net='b')
    return ihp130.run_lvs(cell.layout, cell.symbol)

@pytest.mark.parametrize("pdk", MOS_PDKS.keys())
def test_mos_two_finger_drc_clean(pdk):
    res = MOS_PDKS[pdk].run_drc(Mos2f(pdk=pdk).layout, use_tempdir=True)
    assert res.summary() == {}

@pytest.mark.parametrize("pdk", MOS_PDKS.keys())
def test_mos_two_finger_lvs_clean(pdk):
    cell = Mos2f(pdk=pdk)
    assert mos2f_run_lvs(pdk, cell).clean()


# Passives: DRC/LVS of the devices, meanders, resistance and capacitance
# ----------------------------------------------------------------------

PASSIVES = [
    ihp130.Rsil(), ihp130.Rppd(), ihp130.Rhigh(), ihp130.Cmim(),
    sky130.Rpoly(), sky130.Cmim(),
]

@pytest.mark.parametrize("cell", PASSIVES, ids=short_id)
def test_passive_lvs_clean(cell):
    wrapper = thin_wrapper_cell(cell)
    lvs_report = pdklib(cell).run_lvs(wrapper.layout, wrapper.symbol, use_tempdir=True)
    assert lvs_report.clean()

@pytest.mark.parametrize("cell", PASSIVES, ids=short_id)
def test_passive_drc_clean(cell):
    res = pdklib(cell).run_drc(thin_wrapper_cell(cell).layout, use_tempdir=True)
    assert res.summary() == {}


MEANDERS = [
    kind(l="2.0u", w="0.5u", b=bends, ps=ps)
    for kind in (ihp130.Rsil, ihp130.Rppd, ihp130.Rhigh)
    for bends, ps in ((1, "180n"), (2, "400n"), (5, "400n"))
] + [
    sky130.Rpoly(l="2.0u", w="0.5u", b=bends) for bends in (1, 2, 5)
]

@pytest.mark.parametrize("cell", MEANDERS, ids=short_id)
def test_resistor_meander_lvs_clean(cell):
    wrapper = thin_wrapper_cell(cell)
    lvs_report = pdklib(cell).run_lvs(wrapper.layout, wrapper.symbol, use_tempdir=True)
    assert lvs_report.clean()

@pytest.mark.parametrize("cell", MEANDERS, ids=short_id)
def test_resistor_meander_drc_clean(cell):
    res = pdklib(cell).run_drc(thin_wrapper_cell(cell).layout, use_tempdir=True)
    assert res.summary() == {}


def resistor_tb(res_cell):
    """1 V source in series with the resistor; bulk pin tied where present."""
    class Tb(Cell):
        @viewgen_noctx
        def schematic(self):
            s = Schematic(cell=self)
            s.vdd = Net()
            s.vss = Net()

            s.i_gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(0, -1))
            s.i_vdc = SchemInstance(
                Vdc(dc=1).symbol.portmap(n=s.vss, p=s.vdd), pos=Vec2R(0, 5)
            )
            portmap = dict(p=s.vdd, n=s.vss)
            if any(p.npath.name == 'bn' for p in res_cell.symbol.all(Pin)):
                portmap['bn'] = s.vss
            s.r = SchemInstance(res_cell.symbol.portmap(**portmap), pos=Vec2R(12, 5))

            s.auto_wire()
            s.check(add_conn_points=True, add_terminal_taps=True)
            return s
    return Tb()


# Two parameter sets per resistor type, moving l and w in opposite directions:
# a short+wide device (low R) vs. a long+narrow one (high R). Both parameters
# push resistance the same way here, giving a large spread (~3x) that confirms
# l and w both reach the model. Reference values are op-point results captured
# from ngspice.
@pytest.mark.parametrize("cell,expected_r", [
    (ihp130.Rsil(l="2u", w="2u"), 11.4314),
    (ihp130.Rsil(l="4u", w="1u"), 36.4522),
    (ihp130.Rppd(l="2u", w="2u"), 293.500),
    (ihp130.Rppd(l="4u", w="1u"), 1097.73),
    (ihp130.Rhigh(l="2u", w="2u"), 1496.98),
    (ihp130.Rhigh(l="4u", w="1u"), 6073.46),
    # leff = (b+1)*l + (2/kappa*weff + ps)*b: bends fold length into area.
    (ihp130.Rhigh(l="28u", w="500n", b=10, ps="400n"), 1026707.0),
    (sky130.Rpoly(l="2u", w="2u"), 48.0714),
    (sky130.Rpoly(l="4u", w="1u"), 192.286),
    # leff counts each bend as ps plus two 0.56 corner squares.
    (sky130.Rpoly(l="2u", w="0.5u", b=2), 776.834),
])
def test_resistor_op(cell, expected_r):
    """Ngspice op-point: drive each resistor with 1 V and check R = V / I."""
    tb = resistor_tb(cell)
    h = SimHierarchy.from_schematic(tb.schematic)
    h.simulate().op()
    # Series loop: the source branch current equals the resistor current. The
    # subckt resistor's own port currents (i(xr:1) ...) are not mapped to a
    # SimPin, so read the 1 V source's branch current instead.
    r = 1.0 / abs(float(h.i_vdc.p.current[0]))
    assert r == pytest.approx(expected_r, rel=0.02)


# Two sizes for the MiM capacitors. A capacitor passes no DC current, so it is
# characterized with a single-frequency AC analysis driven by a 1 V AC source:
# C = |I| / (2*pi*f) since |Z| = 1 / (2*pi*f*C) at V = 1. The larger plate area
# (l*w) yields the larger capacitance, confirming both l and w reach the model.
# Reference values are AC results captured from ngspice.
@pytest.mark.parametrize("cell,expected_c", [
    (ihp130.Cmim(l="5u", w="5u"), 3.8300e-14),
    (ihp130.Cmim(l="10u", w="8u"), 1.2144e-13),
    (sky130.Cmim(l="5u", w="5u"), 5.3282e-14),
    (sky130.Cmim(l="10u", w="8u"), 1.6592e-13),
])
def test_cmim_ac(cell, expected_c):
    """Ngspice AC: drive the MiM cap with a 1 V AC source and check C = |I|/(2*pi*f)."""
    cap_cell = cell
    freq = 1e6

    class Tb(Cell):
        @viewgen_noctx
        def schematic(self):
            s = Schematic(cell=self)
            s.vdd = Net()
            s.vss = Net()

            s.i_gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(0, -1))
            s.i_vac = SchemInstance(
                Vdc(ac_mag=1).symbol.portmap(n=s.vss, p=s.vdd),
                pos=Vec2R(0, 5),
            )
            s.c = SchemInstance(
                cap_cell.symbol.portmap(p=s.vdd, n=s.vss),
                pos=Vec2R(12, 5),
            )

            s.auto_wire()
            s.check(add_conn_points=True, add_terminal_taps=True)
            return s

    tb = Tb()
    h = SimHierarchy.from_schematic(tb.schematic)
    h.simulate().ac("lin", 1, freq, freq)
    # Series loop: the source branch current equals the cap current. The subckt
    # cap's own port currents are not mapped to a SimPin, so read the AC source's
    # complex branch current instead.
    i = complex(h.i_vac.p.current[0])
    c = abs(i) / (2 * math.pi * freq)
    assert c == pytest.approx(expected_c, rel=0.02)
