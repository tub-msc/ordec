# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from ordec.core import *
from ordec.extlibrary import ExtLibrary
from ordec.lib import sky130, Gnd, Vdc


class Tb(Cell):
    """One device of each corner library (MOS, resistor, capacitor) on a 1 V source."""
    @viewgen_noctx
    def schematic(self):
        s = Schematic(cell=self)
        s.vdd = Net()
        s.vss = Net()
        s.i_gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(0, -1))
        s.i_vdc = SchemInstance(Vdc(dc=1).symbol.portmap(n=s.vss, p=s.vdd), pos=Vec2R(0, 5))
        nmos = sky130.Nmos(w="1u", l="150n").symbol
        s.m = SchemInstance(nmos.portmap(d=s.vdd, g=s.vdd, s=s.vss, b=s.vss), pos=Vec2R(12, 5))
        s.r = SchemInstance(sky130.Rpoly(l="2u", w="1u").symbol.portmap(p=s.vdd, n=s.vss), pos=Vec2R(24, 5))
        s.c = SchemInstance(sky130.Cmim(l="5u", w="5u").symbol.portmap(p=s.vdd, n=s.vss), pos=Vec2R(36, 5))
        s.auto_wire()
        s.check(add_conn_points=True, add_terminal_taps=True)
        return s


def current(corner) -> float:
    h = SimHierarchy.from_schematic(Tb().schematic)
    h.simulate(corner=corner).op()
    return abs(float(h.i_vdc.p.current[0]))


def test_corners():
    """The MOS and the resistor corner each move the current the expected way."""
    tt = current(None)
    assert current(sky130.Corner.TT) == tt
    assert current(sky130.Corner.FF) > tt > current(sky130.Corner.SS)
    assert current(sky130.Corner(res="low", cap="low")) > tt > current(sky130.Corner(res="high", cap="high"))


def test_netlist_corner():
    h = SimHierarchy.from_schematic(Tb().schematic)
    nl = h.simulate(corner=sky130.Corner(mos="sf", res="high", cap="low")).netlister.out()
    assert "corners/sf.spice" in nl and "r+c/res_high__cap_low.spice" in nl
    assert "corners/leak.spice" in h.simulate(corner=sky130.Corner(mos="leak")).netlister.out()
    with pytest.raises(ValueError):
        sky130.Corner(res="high")
    with pytest.raises(TypeError, match="sky130.Corner"):
        SimHierarchy.from_schematic(Tb().schematic).simulate(corner="ss").op()


def test_read_spice_device_map(tmp_path):
    """Imported devices become the cells with their sizes."""
    spice = tmp_path / "t.spice"
    spice.write_text(".subckt t a b\n"
        "X1 a a b b sky130_fd_pr__nfet_01v8 w=2u l=150n nf=2 m=3\n"
        "R1 a b sky130_fd_pr__res_generic_po w=1u l=2u m=2\n"
        "X2 a b b sky130_fd_pr__res_high_po_0p35 l=2u\n"
        "X3 a b b sky130_fd_pr__cap_var_lvt w=1u l=180n vm=2\n"
        "X4 a a b b b sky130_fd_pr__nfet_20v0_iso w=60u l=2u\n"
        "X5 a a b b sky130_fd_pr__npn_05v5_W1p00L1p00 m=2\n"
        ".ends\n")
    lib = ExtLibrary()
    lib.read_spice(spice, device_map=sky130.device_map)
    cells = {type(i.symbol.cell): i.symbol.cell for i in lib["t"].schematic.all(SchemInstance)}
    mos = cells[sky130.Nmos]
    assert (mos.w, mos.l, mos.nf, mos.m) == (R("2u"), R("150n"), 2, 3)
    res = cells[sky130.Rpoly]
    assert (res.w, res.l, res.m) == (R("1u"), R("2u"), 2)
    # Cards that size the device other than the cell does, or not at all.
    assert cells[sky130.RhighPo0p35].w == R("0.35u")
    assert (cells[sky130.VarCapLvt].w, cells[sky130.VarCapLvt].nf) == (R("2u"), 2)
    assert cells[sky130.Nmos20v0Iso].w == R("60u")
    assert (cells[sky130.Npn].device, cells[sky130.Npn].m) == ("npn_05v5_W1p00L1p00", 2)
