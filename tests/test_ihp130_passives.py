# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import math

import pytest

from ordec.core import *
from ordec.core import ParameterError
from ordec.lib import ihp130, Gnd, Vdc
from .lib.thinwrap import thin_wrapper_cell


@pytest.mark.parametrize("kind", [ihp130.Rsil, ihp130.Rppd, ihp130.Rhigh])
def test_resistor_lvs_clean(kind):
    cell = thin_wrapper_cell(kind())
    lvs_report = ihp130.run_lvs(cell.layout, cell.symbol, use_tempdir=True)
    assert lvs_report.clean()


@pytest.mark.parametrize("kind", [ihp130.Rsil, ihp130.Rppd, ihp130.Rhigh])
def test_resistor_meander_layout_rejected(kind):
    with pytest.raises(ParameterError, match="b != 0 not supported for layout."):
        thin_wrapper_cell(kind(l="1.0u", w="0.5u", b=2, ps="0.5u")).layout


@pytest.mark.parametrize("kind", [ihp130.Rsil, ihp130.Rppd, ihp130.Rhigh])
def test_resistor_drc_clean(kind):
    cell = thin_wrapper_cell(kind())
    res = ihp130.run_drc(cell.layout, use_tempdir=True)
    assert res.summary() == {}


def test_cmim_lvs_clean():
    cell = thin_wrapper_cell(ihp130.Cmim())
    lvs_report = ihp130.run_lvs(cell.layout, cell.symbol, use_tempdir=True)
    assert lvs_report.clean()


def test_cmim_drc_clean():
    cell = thin_wrapper_cell(ihp130.Cmim())
    res = ihp130.run_drc(cell.layout, use_tempdir=True)
    assert res.summary() == {}


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
])
def test_resistor_op(cell, expected_r):
    """Ngspice op-point: drive each resistor with 1 V and check R = V / I."""
    res_cell = cell

    class Tb(Cell):
        @generate
        def schematic(self):
            s = Schematic(cell=self)
            s.vdd = Net()
            s.vss = Net()

            s.i_gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(0, -1))
            s.i_vdc = SchemInstance(
                Vdc(dc=1).symbol.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 5)
            )
            s.r = SchemInstance(
                res_cell.symbol.portmap(p=s.vdd, m=s.vss, bn=s.vss),
                pos=Vec2R(12, 5),
            )

            s.auto_wire()
            s.check(add_conn_points=True, add_terminal_taps=True)
            return s

    tb = Tb()
    h = SimHierarchy.from_schematic(tb.schematic)
    h.simulate(batch=True).op()
    # Series loop: the source branch current equals the resistor current. The
    # subckt resistor's own port currents (i(xr:1) ...) are not mapped to a
    # SimPin, so read the 1 V source's branch current instead.
    r = 1.0 / abs(float(h.i_vdc.p.current[0]))
    assert r == pytest.approx(expected_r, rel=0.02)


# Two sizes for the MiM capacitor. A capacitor passes no DC current, so it is
# characterized with a single-frequency AC analysis driven by a 1 V AC source:
# C = |I| / (2*pi*f) since |Z| = 1 / (2*pi*f*C) at V = 1. The larger plate area
# (l*w) yields the larger capacitance, confirming both l and w reach the model.
# Reference values are AC results captured from ngspice.
@pytest.mark.parametrize("cell,expected_c", [
    (ihp130.Cmim(l="5u", w="5u"), 3.8300e-14),
    (ihp130.Cmim(l="10u", w="8u"), 1.2144e-13),
])
def test_cmim_ac(cell, expected_c):
    """Ngspice AC: drive the MiM cap with a 1 V AC source and check C = |I|/(2*pi*f)."""
    cap_cell = cell
    freq = 1e6

    class Tb(Cell):
        @generate
        def schematic(self):
            s = Schematic(cell=self)
            s.vdd = Net()
            s.vss = Net()

            s.i_gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(0, -1))
            s.i_vac = SchemInstance(
                Vdc(ac_mag=1).symbol.portmap(m=s.vss, p=s.vdd),
                pos=Vec2R(0, 5),
            )
            s.c = SchemInstance(
                cap_cell.symbol.portmap(p=s.vdd, m=s.vss),
                pos=Vec2R(12, 5),
            )

            s.auto_wire()
            s.check(add_conn_points=True, add_terminal_taps=True)
            return s

    tb = Tb()
    h = SimHierarchy.from_schematic(tb.schematic)
    h.simulate(batch=True).ac("lin", 1, freq, freq)
    # Series loop: the source branch current equals the cap current. The subckt
    # cap's own port currents are not mapped to a SimPin, so read the AC source's
    # complex branch current instead.
    i = complex(h.i_vac.p.current[0])
    c = abs(i) / (2 * math.pi * freq)
    assert c == pytest.approx(expected_c, rel=0.02)
