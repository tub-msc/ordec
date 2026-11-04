# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import math

import pytest

from ordec.core import *
from ordec.lib import sky130, Gnd, Vdc
from .lib.thinwrap import gallery_wrapper_cell

# One gallery for a single DRC and a single LVS run (deck startup dominates).
# Both resistor stripe parities place the p terminal at opposite ends.
GALLERY = [
    sky130.Rpoly(), sky130.Cmim(),
    sky130.Rpoly(l="2.0u", w="0.5u", b=2),
]

def test_gallery():
    wrapper = gallery_wrapper_cell(GALLERY, "Gallery")
    assert sky130.run_drc(wrapper.layout, use_tempdir=True).summary() == {}
    assert sky130.run_lvs(wrapper.layout, wrapper.symbol, use_tempdir=True).clean()


@pytest.mark.magic
def test_gallery_magic():
    wrapper = gallery_wrapper_cell(GALLERY, "Gallery")
    assert sky130.run_magic_drc(wrapper.layout).summary() == {}


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


def test_mos_diffusion_per_finger():
    """ad/as/pd/ps derive from the per-finger width, since each diffusion
    region is w/nf wide."""
    d1 = sky130.Nmos(w="500n", l="150n").diffusion_params()
    d4 = sky130.Nmos(w="2u", l="150n", nf=4).diffusion_params()
    assert d4['ad'] == 2 * d1['ad']   # two drain regions of the same width
    assert d4['as_'] == 3 * d1['as_']


def resistor_tb(res_cell):
    """1 V source in series with the resistor."""
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
            s.r = SchemInstance(res_cell.symbol.portmap(p=s.vdd, n=s.vss), pos=Vec2R(12, 5))

            s.auto_wire()
            s.check(add_conn_points=True, add_terminal_taps=True)
            return s
    return Tb()


# Reference values are op-point results captured from ngspice.
@pytest.mark.parametrize("cell,expected_r", [
    (sky130.Rpoly(l="2u", w="2u"), 48.0714),
    (sky130.Rpoly(l="4u", w="1u"), 192.286),
    # leff counts each bend as ps plus two 0.56 corner squares.
    (sky130.Rpoly(l="2u", w="0.5u", b=2), 776.834),
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
