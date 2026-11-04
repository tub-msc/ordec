# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import math

import pytest

from ordec.core import *
from ordec.lib import sky130, Gnd, Vdc
from .lib.thinwrap import gallery_wrapper_cell

# One gallery for a single DRC and a single LVS run (deck startup dominates).
# The guard rings of the NMOS devices and the substrate resistors tie the
# common substrate, whose net the LVS deck merges by name.
GALLERY = [
    sky130.Nmos(w="1u", l="150n"), sky130.NmosLvt(w="1u", l="150n"), sky130.NmosHv(w="1u", l="500n"),
    sky130.Nmos05v0Nvt(w="1u", l="900n"), sky130.Nmos03v3Nvt(w="1u", l="500n"),
    sky130.Pmos(w="1u", l="150n"), sky130.PmosLvt(w="1u", l="350n"), sky130.PmosHvt(w="1u", l="150n"),
    sky130.PmosHv(w="1u", l="500n"),
    sky130.Rpoly(l="1.65u", w="0.33u"), sky130.Rpoly(l="2u", w="0.5u", nx=3, snake=True),
    sky130.Rnd(l="2.1u", w="0.42u"), sky130.Rpd(l="2.1u", w="0.42u"), sky130.RndHv(l="2.1u", w="0.42u"),
    sky130.RpdHv(l="2.1u", w="0.42u"), sky130.RhighPo0p35(l="2u", w="0.35u"),
    sky130.RxhighPo0p69(l="2u", w="0.69u"), sky130.RhighPo5p73(l="2u", w="5.73u"),
    sky130.RisoPw(l="26.5u", w="2.65u"),
    sky130.Cmim(),
    sky130.DiodePw2nd(), sky130.DiodePw2ndLvt(), sky130.DiodePw2ndNvt(), sky130.DiodePw2nd11v0(),
    sky130.DiodePd2nw(), sky130.DiodePd2nwLvt(), sky130.DiodePd2nwHvt(), sky130.DiodePd2nw11v0(),
]
SUBSTRATE = "nmos0_b"
TIES = ("nmoslvt1_b", "nmoshv2_b", "nmos05v0nvt3_b", "nmos03v3nvt4_b")

def test_gallery():
    wrapper = gallery_wrapper_cell(GALLERY, "Gallery", substrate=SUBSTRATE, ties=TIES)
    assert sky130.run_drc(wrapper.layout, use_tempdir=True).summary() == {}
    assert sky130.run_lvs(wrapper.layout, wrapper.symbol, use_tempdir=True, substrate_net=SUBSTRATE).clean()


@pytest.mark.magic
def test_gallery_magic():
    wrapper = gallery_wrapper_cell(GALLERY, "Gallery", substrate=SUBSTRATE, ties=TIES)
    # Magic reads the contacts of the LVT, NVT and HVT diodes from GDS as
    # plain diode contacts, which then fail licon.5a: the copyup rules of the
    # cifinput section of sky130A.tech ignore the threshold implants.
    assert sky130.run_magic_drc(wrapper.layout).summary() == {"licon.5a": 32}


@pytest.mark.parametrize("build", [
    lambda: sky130.Nmos(w="1u", l="100n"),
    lambda: sky130.Nmos(w="300n", l="150n"),
    lambda: sky130.Nmos(w="1u", l="150n", nf=4),
    lambda: sky130.Nmos(w="2u", l="150n", nf=3),
], ids=["short-l", "narrow-w", "narrow-finger", "indivisible"])
def test_mos_dimension_limits(build):
    """Out-of-range dimensions are rejected at cell construction, before
    they can silently reach simulation or layout."""
    with pytest.raises(ParameterError):
        build()


def test_snake_limits():
    """Snakes that the generator cannot draw are rejected at layout generation."""
    for cell in (sky130.RhighPo0p69(l="0.5u", w="0.69u", nx=2, snake=True),
            sky130.RhighPo0p35(l="2.5u", w="0.35u", nx=2, snake=True)):
        with pytest.raises(ParameterError):
            cell.layout


def test_mos_diffusion_per_finger():
    """ad/as/pd/ps derive from the per-finger width, since each diffusion
    region is w/nf wide."""
    d1 = sky130.Nmos(w="500n", l="150n").diffusion_params()
    d4 = sky130.Nmos(w="2u", l="150n", nf=4).diffusion_params()
    assert d4['ad'] == 2 * d1['ad']   # two drain regions of the same width
    assert d4['as_'] == 3 * d1['as_']


def resistor_tb(res_cell):
    """1 V source in series with the resistor, bulk pin tied where present."""
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
            if res_cell.bulk:
                portmap[res_cell.bulk] = s.vss
            s.r = SchemInstance(res_cell.symbol.portmap(**portmap), pos=Vec2R(12, 5))

            s.auto_wire()
            s.check(add_conn_points=True, add_terminal_taps=True)
            return s
    return Tb()


# Reference values are op-point results captured from ngspice.
@pytest.mark.parametrize("cell,expected_r", [
    (sky130.Rpoly(l="2u", w="2u"), 48.07),
    (sky130.Rpoly(l="2u", w="0.5u", nx=3, snake=True), 769.1),
    (sky130.RhighPo0p35(l="2u", w="0.35u"), 2977),
    (sky130.RhighPo5p73(l="6u", w="5.73u"), 413.7),
    (sky130.RxhighPo0p35(l="2u", w="0.35u"), 1.273e4),
    (sky130.Rnd(l="2.1u", w="0.42u"), 574.2),
    (sky130.Rpd(l="2.1u", w="0.42u"), 900.7),
    (sky130.RndHv(l="2.1u", w="0.42u"), 545.5),
    (sky130.RpdHv(l="2.1u", w="0.42u"), 916.5),
    (sky130.Rl1(l="2u", w="0.17u"), 130.2),
    (sky130.Rm1(l="10u", w="0.14u"), 12.26),
    (sky130.Rm5(l="20u", w="1.6u"), 0.3735),
    (sky130.RisoPw(l="26.5u", w="2.65u"), 3.799e4),
])
def test_resistor_op(cell, expected_r):
    """Ngspice op-point: drive each resistor with 1 V and check R = V / I."""
    h = SimHierarchy.from_schematic(resistor_tb(cell).schematic)
    h.simulate().op()
    # The source branch current equals the resistor current.
    r = 1.0 / abs(float(h.i_vdc.p.current[0]))
    assert r == pytest.approx(expected_r, rel=0.02)
    assert cell.nominal_resistance() == pytest.approx(r, rel=0.1)


# A 1 V AC source gives C = |I| / (2*pi*f). Reference values are AC results
# captured from ngspice.
@pytest.mark.parametrize("cell,expected_c", [
    (sky130.Cmim(l="5u", w="5u"), 5.3282e-14),
    (sky130.Cmim(l="10u", w="8u"), 1.6592e-13),
])
def test_cmim_ac(cell, expected_c):
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
            s.c = SchemInstance(cell.symbol.portmap(p=s.vdd, n=s.vss), pos=Vec2R(12, 5))

            s.auto_wire()
            s.check(add_conn_points=True, add_terminal_taps=True)
            return s

    h = SimHierarchy.from_schematic(Tb().schematic)
    h.simulate().ac("lin", 1, freq, freq)
    c = abs(complex(h.i_vac.p.current[0])) / (2 * math.pi * freq)
    assert c == pytest.approx(expected_c, rel=0.02)


@pytest.mark.parametrize("cell,expected_i", [
    (sky130.DiodePw2nd(w="1u", l="1u"), 3.31e-5),
    (sky130.DiodePd2nw(w="1u", l="1u"), 1.2e-5),
    (sky130.DiodePd2nw11v0(w="1u", l="1u"), 1.75e-7),
])
def test_diode_op(cell, expected_i):
    """Ngspice op-point: forward current at 0.8 V, captured from ngspice."""
    class Tb(Cell):
        @viewgen_noctx
        def schematic(self):
            s = Schematic(cell=self)
            s.vdd = Net()
            s.vss = Net()
            s.i_gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(0, -1))
            s.i_vdc = SchemInstance(Vdc(dc=R("0.8")).symbol.portmap(n=s.vss, p=s.vdd), pos=Vec2R(0, 5))
            s.d = SchemInstance(cell.symbol.portmap(p=s.vdd, n=s.vss), pos=Vec2R(12, 5))
            s.auto_wire()
            s.check(add_conn_points=True, add_terminal_taps=True)
            return s

    h = SimHierarchy.from_schematic(Tb().schematic)
    h.simulate().op()
    assert abs(float(h.i_vdc.p.current[0])) == pytest.approx(expected_i, rel=0.05)
