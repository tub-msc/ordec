# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import math

import pytest

from ordec.core import *
from ordec.lib import ihp130, Gnd, Vdc
from .lib.thinwrap import gallery_wrapper_cell
from .lib.ihp130_inv import Inv


# One gallery for a single DRC and a single LVS run (deck startup dominates).
# MOS devices come in the inverter fixture, whose body tap ties the
# substrate to its vss, as the pnp's collector and the guard rings of RF
# NMOS and rfcmim do. NWell devices alternate with others (NBL.c, NBL.d),
# the bondpad has no Activ next to it (Pad.d1R). Svaricap with w=3.74u fails
# NW.e, as the foundry PCell does.
GALLERY = [
    ihp130.Bondpad(size="80u"), ihp130.Bondpad(size="80u", shape=1, bottom_metal=1, add_filler_ex=True),
    ihp130.Rsil(l="0.5u", w="0.5u"), ihp130.Rppd(l="0.5u", w="0.5u"), ihp130.Rhigh(l="0.96u", w="0.5u"),
    ihp130.Cmim(l="6.99u", w="6.99u"),
    ihp130.Rsil(l="2.0u", w="0.5u", b=1, ps="180n"),
    ihp130.Rppd(l="2.0u", w="0.5u", b=2, ps="400n"),
    ihp130.Rhigh(l="2.0u", w="0.5u", b=5, ps="400n"),
    ihp130.Ntap1(w="0.78u", l="0.78u"), ihp130.Ptap1(w="0.78u", l="0.78u"), ihp130.Ntap1(w="1u", l="2u"),
    ihp130.Ptap1(w="3u", l="0.8u"),
    ihp130.Npn13G2(nx=2), ihp130.PnpMPA(w="1u", l="2u"), ihp130.Npn13G2l(el=1, thermal=True),
    ihp130.Npn13G2v(nx=2, el=2),
    ihp130.Svaricap(w="9.74u", l="0.3u"),
    ihp130.RfPmosHv(w="1u", l="0.72u"), ihp130.RfNmos(w="1u", l="0.72u"), ihp130.Rfcmim(w="7u", l="7u", wfeed="3u"),
    ihp130.Dpantenna(w="1.5u", l="4u"), ihp130.Dantenna(w="0.78u", l="0.78u"),
    ihp130.Inductor3(w="2u", s="2.1u", d="25.84u", nr_r=2),
    Inv(variant="hv"),
]
SUBSTRATE = f"inv{len(GALLERY) - 1}_vss"
TIES = ("pnpmpa14_c", "rfnmos19_b", "rfcmim20_bn")


def test_device_gallery_drc_clean():
    wrapper = gallery_wrapper_cell(GALLERY, "DeviceGallery", SUBSTRATE, TIES)
    assert ihp130.run_drc(wrapper.layout, use_tempdir=True).summary() == {}


def test_device_gallery_lvs_clean():
    wrapper = gallery_wrapper_cell(GALLERY, "DeviceGallery", SUBSTRATE, TIES)
    assert ihp130.run_lvs(wrapper.layout, wrapper.symbol, use_tempdir=True).clean()


def supply_current(cell, volts, freq=None, **conns):
    """Supply current of one device, its pins on the nets ``vdd`` or ``vss``;
    with freq, the current magnitude for an AC source of amplitude volts."""
    class Tb(Cell):
        @viewgen_noctx
        def schematic(self):
            s = Schematic(cell=self)
            s.vdd = Net()
            s.vss = Net()
            s.i_gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(0, -1))
            source = Vdc(ac_mag=volts) if freq else Vdc(dc=volts)
            s.i_vdc = SchemInstance(source.symbol.portmap(n=s.vss, p=s.vdd), pos=Vec2R(0, 5))
            s.x = SchemInstance(
                cell.symbol.portmap(**{pin: getattr(s, net) for pin, net in conns.items()}),
                pos=Vec2R(12, 5))
            s.auto_wire()
            s.check(add_conn_points=True, add_terminal_taps=True)
            return s

    h = SimHierarchy.from_schematic(Tb().schematic)
    if freq:
        h.simulate().ac("lin", 1, freq, freq)
    else:
        h.simulate().op()
    return abs(complex(h.i_vdc.p.current[0]))


# Reference values captured from ngspice. An LV Nmos of the HV size draws
# 1.28 mA; the taps draw 1 V / R (262.85 and 98 Ohm); the HBTs are forward
# biased diodes, npn13G2 base and collector joined.
@pytest.mark.parametrize("cell,volts,conns,expected", [
    (ihp130.NmosHv(w="1u", l="450n"), "3.3", dict(d="vdd", g="vdd", s="vss", b="vss"), 532.68e-6),
    (ihp130.PmosHv(w="1u", l="450n"), "3.3", dict(d="vss", g="vss", s="vdd", b="vdd"), 219.31e-6),
    (ihp130.Ntap1(w="0.78u", l="0.78u"), "1", dict(tie="vdd", well="vss"), 3.8045e-3),
    (ihp130.Ptap1(w="3u", l="0.8u"), "1", dict(tie="vdd", sub="vss"), 10.204e-3),
    (ihp130.Npn13G2(), "0.8", dict(c="vdd", b="vdd", e="vss", bn="vss"), 138.62e-6),
    (ihp130.PnpMPA(w="1u", l="2u"), "0.8", dict(e="vdd", b="vss", c="vss"), 10.142e-6),
    (ihp130.RfNmos(w="1u", l="0.72u"), "1.2", dict(d="vdd", g="vdd", s="vss", b="vss"), 179.91e-6),
    (ihp130.Dantenna(w="0.78u", l="0.78u"), "0.8", dict(d0="vdd", d1="vss"), 389.91e-9),
])
def test_device_op(cell, volts, conns, expected):
    assert supply_current(cell, volts, **conns) == pytest.approx(expected, rel=0.02)


# Capacitance from the AC current at 1 MHz, C = |I| / (2 pi f) for 1 V.
@pytest.mark.parametrize("cell,conns,expected", [
    (ihp130.Svaricap(w="9.74u", l="0.3u"), dict(g1="vdd", nw="vss", g2="vss", bn="vss"), 12.883e-15),
    (ihp130.Cpara(c="20f"), dict(p="vdd", n="vss"), 20e-15),
    (ihp130.Rfcmim(w="7u", l="7u", wfeed="3u"), dict(p="vdd", n="vss", bn="vss"), 74.621e-15),
])
def test_device_ac(cell, conns, expected):
    freq = 1e6
    assert supply_current(cell, "1", freq, **conns) / (2 * math.pi * freq) == pytest.approx(expected, rel=0.02)

