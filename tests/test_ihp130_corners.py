# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from ordec.core import *
from ordec.lib import ihp130, Gnd, Vdc
from ordec.sim import Simulator


class CornerTb(Cell):
    """One device of each corner library (MOS, resistor, capacitor)
    across 1 V, so every .lib section is loaded by ngspice."""
    @viewgen_noctx
    def schematic(self):
        s = Schematic(cell=self)
        s.vdd = Net()
        s.vss = Net()
        s.i_gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(0, -1))
        s.i_vdc = SchemInstance(
            Vdc(dc=1).symbol.portmap(n=s.vss, p=s.vdd), pos=Vec2R(0, 5))
        s.m = SchemInstance(
            ihp130.Nmos(l="130n", w="1u").symbol.portmap(
                d=s.vdd, g=s.vdd, s=s.vss, b=s.vss),
            pos=Vec2R(12, 5))
        s.r = SchemInstance(
            ihp130.Rsil().symbol.portmap(p=s.vdd, n=s.vss, bn=s.vss),
            pos=Vec2R(18, 5))
        s.c = SchemInstance(
            ihp130.Cmim().symbol.portmap(p=s.vdd, n=s.vss),
            pos=Vec2R(24, 5))
        s.auto_wire()
        s.check(add_conn_points=True, add_terminal_taps=True)
        return s


def test_netlist_corner_and_temp():
    """Ensure corner and temp emit the correct netlist constructs."""
    h = SimHierarchy.from_schematic(CornerTb().schematic)
    nl = Simulator(h).netlister.out()
    assert " mos_tt\n" in nl and " res_typ\n" in nl and " cap_typ\n" in nl
    assert ".option temp=" not in nl

    h = SimHierarchy.from_schematic(CornerTb().schematic)
    corner = ihp130.Corner(mos="ss", res="typ", cap=ihp130.CapCorner.WCS)
    nl = Simulator(h, corner=corner, temp=125).netlister.out()
    assert " mos_ss\n" in nl and " res_typ\n" in nl and " cap_wcs\n" in nl
    assert f".option temp={R(125).compat_str()}\n" in nl

    h = SimHierarchy.from_schematic(CornerTb().schematic)
    with pytest.raises(TypeError, match="expects an ihp130.Corner"):
        Simulator(h, corner="ss")


def test_corner_class():
    assert ihp130.Corner.SS == ihp130.Corner(mos="ss")


def test_corner_simulation():
    """Non-tt sections of all three corner libraries exist and
    simulate at a non-default temperature."""
    h = SimHierarchy.from_schematic(CornerTb().schematic)
    corner = ihp130.Corner(mos="ss", res="wcs", cap="wcs")
    h.simulate(corner=corner, temp=125).op()
    assert h.vdd.voltage[0] == pytest.approx(1.0)
    assert 0 < abs(float(h.i_vdc.p.current[0])) < 1


def test_temp_sweep():
    h = SimHierarchy.from_schematic(CornerTb().schematic)
    h.simulate().temp_sweep(-40, 125, 4)
    assert h.sim_type == SimType.DCSWEEP
    assert h.sweep.quantity == Quantity.TEMPERATURE
    assert list(h.sweep) == pytest.approx([-40, 15, 70, 125])
    assert len(h.i_vdc.p.current) == 4
    with pytest.raises(ValueError, match="step_count"):
        h.simulate().temp_sweep(0, 100, 1)
