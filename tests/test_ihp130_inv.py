# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests basic DRC + LVS + PEX in IHP130.
"""

import io
import math
import re
import pytest

import ordec.importer

from ordec.core import *
from ordec.core.schema import LvsItem, LvsItemType
from ordec.lib import ihp130, Gnd, Vdc, Res, Cap
from ordec.layout import kpex, write_gds, gds_text
from .lib.ihp130_inv import Inv
from .lib.ihp130_nmos_series import SeriesNmos

pytestmark = pytest.mark.ihp130

def test_lvs_clean():
    c = Inv()
    lvs_report = ihp130.run_lvs(c.layout, c.symbol)
    assert lvs_report.clean()
    # MOSFET device items ("Mpd"/"Mpu" in SPICE) cross-reference the
    # schematic's SchemInstances.
    devices = {i.schem_name: i.schem for i in lvs_report.all(LvsItem)
               if i.item_type == LvsItemType.Device}
    assert devices == {'pd': c.schematic.pd, 'pu': c.schematic.pu}

def test_lvs_missing_y():
    c = Inv(variant="missing_y")
    lvs_report = ihp130.run_lvs(c.layout, c.symbol)
    assert not lvs_report.clean()

def test_lvs_vss_vdd_pins_swapped():
    c = Inv(variant="vss_vdd_pins_swapped")
    lvs_report = ihp130.run_lvs(c.layout, c.symbol, use_tempdir=True)
    assert not lvs_report.clean()

def test_drc_clean():
    res = ihp130.run_drc(Inv().layout, use_tempdir=True)
    assert res.summary() == {}


def test_drc_violation():
    res = ihp130.run_drc(Inv(variant="thin_m1").layout, use_tempdir=True)
    assert res.summary() == {'M1.a': 2}


def test_series_nmos_drc_clean():
    """The uncontacted source/drain needs no Activ of its own to pass DRC."""
    assert SeriesNmos().drc.summary() == {}


def test_series_nmos_lvs_clean():
    """The abutted pair matches its two-transistor series schematic, with the
    shared bare diffusion as the internal source/drain node."""
    assert SeriesNmos().lvs.clean()

def test_lvs_pin_without_label():
    """A top-level pin on GatPoly cannot name its net in LVS or PEX."""
    nmos = ihp130.Nmos(w="1u", l="130n")
    with pytest.raises(ValueError, match="Route it to metal"):
        ihp130.run_lvs(nmos.layout, nmos.symbol)
    with pytest.raises(ValueError, match="Route it to metal"):
        ihp130.run_pex(nmos.layout)


class InvTb(Cell):
    @viewgen_noctx
    def schematic(self):
        s = Schematic(cell=self)
        s.vss = Net()
        s.vdd = Net()
        s.a = Net()
        s.y = Net()
        s.gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss))
        s.vsup = SchemInstance(Vdc(dc="1.2").symbol.portmap(p=s.vdd, n=s.vss))
        s.vin = SchemInstance(Vdc(dc=0, ac_mag=1).symbol.portmap(p=s.a, n=s.vss))
        s.dut = SchemInstance(Inv().symbol.portmap(a=s.a, y=s.y, vdd=s.vdd, vss=s.vss))
        return s

    def input_capacitance(self, extracted=()):
        h = SimHierarchy.from_schematic(self.schematic, extracted=extracted)
        h.simulate().ac('dec', 1, R('1G'), R('1G'))
        return abs(h.vin.p.current[0]) / (2 * math.pi * 1e9)


@pytest.mark.kpex
def test_pex(tmp_path):
    report = ihp130.run_pex(Inv().layout)
    pex = report.schematic
    assert {n.full_path_str() for n in pex.all(Net) if n.pin is not None} == {'a', 'y', 'vdd', 'vss'}
    cells = [i.symbol.cell for i in pex.all(SchemInstance)]
    # The devices come with their junction geometry, the parasitics as Res and Cap.
    assert ihp130.Nmos(w="1u", l="130n", ad="340f", as_="340f", pd="2.68u", ps="2.68u") in cells
    assert len([c for c in cells if isinstance(c, ihp130.Mos)]) == 2
    assert any(isinstance(c, Res) for c in cells) and any(isinstance(c, Cap) for c in cells)

    # The report has the nets, not the nodes of their resistor networks.
    assert {n.net.full_path_str() for n in report.all(PexNet)} == {'a', 'y', 'vdd', 'vss'}
    assert report.net(pex.vdd).nodes > 1 and report.net(pex.vdd).resistors > 1
    viewtype, data = report.webdata_static()
    assert viewtype == 'report' and data['elements'][1]['html'].count('<tr>') == 1 + 4

    # Post-layout simulation: the parasitic capacitance of the input adds to
    # the gate capacitance.
    tb = InvTb()
    assert tb.input_capacitance(extracted=[pex]) - tb.input_capacitance() \
        == pytest.approx(float(report.net(pex.a).capacitance), rel=0.05)

    with pytest.raises(kpex.KpexError, match="pin y"):
        ihp130.run_pex(Inv(variant="missing_y").layout)

    # Netlists that would simulate something else than the layout are
    # rejected: pins on one net (here as two ports of one resistor network),
    # the label of a pin on a second net and a substrate without a pin.
    directory = Directory()
    for pin in Inv().symbol.all(Pin):
        directory.name_node(pin)
    for ports, card, match in (
        ("a y vdd vss", "Rext_1 a y 1m", "pins a and y"),
        ("a y vdd vss x|a", "", "label of pin a"),
        ("a y vdd vss sub!", "", "substrate"),
    ):
        (tmp_path / 'pex.spice').write_text(f".subckt inv {ports}\n{card}\n.ends\n")
        with pytest.raises(kpex.KpexError, match=match):
            kpex.read_netlist(tmp_path / 'pex.spice', Inv().layout, directory, ihp130.device_map)

    # The net of a pin keeps its name next to another label on it.
    (tmp_path / 'pex.spice').write_text(".subckt inv A a y vdd vss\nRext_1 A a 1m\n.ends\n")
    report = kpex.read_netlist(tmp_path / 'pex.spice', Inv().layout, directory, ihp130.device_map)
    assert report.net(report.schematic.a).nodes == 2


def test_gds_sublayout_pins():
    """A flat extraction would take the labels of the sublayouts' pins (and
    other labels on pin layers) for labels of the inverter, so its GDS file
    leaves them out."""
    layers = ihp130.SG13G2().layers
    sub = Layout(ref_layers=layers)
    sub % LayoutLabel(layer=layers.Metal1.pin, pos=(0, 0), text="x")
    layout = Inv().layout.mutable_copy()
    layout % LayoutInstance(ref=sub.freeze(), pos=(0, 0))
    layout = layout.freeze()

    def labels(**kwargs):
        buf = io.BytesIO()
        write_gds(layout, buf, **kwargs)
        buf.seek(0)
        return set(re.findall(r"STRING: '(\w+)'", gds_text(buf)))

    assert labels() - labels(sublayout_pins=False) == {'d', 'g', 's', 'b', 'x'}
    assert labels(sublayout_pins=False) >= {'a', 'y', 'vdd', 'vss'}
