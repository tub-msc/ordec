# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0
import subprocess

import pytest

from ordec.core import *
from ordec.layout import gdsrecords
from ordec.lib import sky130

pytestmark = pytest.mark.magic


def test_run_magic(tmp_path):
    (tmp_path / "gen.tcl").write_text(
        "load top\n"
        "magic::gencell sky130::sky130_fd_pr__nfet_01v8 m1 w $w l 0.15\n"
        "select top cell\n"
        "gds write $gds\n")
    sky130.run_magic("gen.tcl", tmp_path, capture="gen.log", w=1.0, gds="top.gds")
    _, structures = gdsrecords.scan((tmp_path / "top.gds").read_bytes())
    assert any(name.startswith(b"sky130_fd_pr__nfet_01v8_") for name, _, _ in structures)

    (tmp_path / "fail.tcl").write_text("no_such_command\n")
    with pytest.raises(subprocess.CalledProcessError):
        sky130.run_magic("fail.tcl", tmp_path, capture="fail.log")
    assert "no_such_command" in (tmp_path / "fail.log").read_text()


@viewgen_noctx
def met1_layers():
    layers = LayerStack(unit=R('1n'))
    layers.met1 = Layer(gdslayer_shapes=GdsLayer(68, 20))
    return layers


class Sub(Cell):
    """Two met1 rects 100 nm apart, below the 140 nm of met1.2."""
    @viewgen_noctx
    def layout(self):
        l = Layout(ref_layers=met1_layers(), cell=self)
        l % LayoutRect(layer=l.ref_layers.met1, rect=Rect4I(0, 0, 1000, 1000))
        l % LayoutRect(layer=l.ref_layers.met1, rect=Rect4I(1100, 0, 2100, 1000))
        return l


class Top(Cell):
    """Sub three times, one rotated, and a met1 rect 100 nm left of sub1."""
    @viewgen_noctx
    def layout(self):
        l = Layout(ref_layers=met1_layers(), cell=self)
        l.sub1 = LayoutInstance(ref=Sub().layout, pos=(0, 0))
        l.sub2 = LayoutInstance(ref=Sub().layout, pos=(0, 5000))
        l.sub3 = LayoutInstance(ref=Sub().layout, pos=(5000, 10000), orient=R90)
        l % LayoutRect(layer=l.ref_layers.met1, rect=Rect4I(-1100, 0, -100, 1000))
        return l


def test_run_magic_drc():
    report = sky130.run_magic_drc(Top().layout)
    # As in KLayout's deep mode (test_ihp130_drc_hier), Sub's violation is
    # attached once to Sub, in its coordinates, and the cross-hierarchy one
    # to the top cell. Magic marks a violation on both of its shapes.
    assert report.summary() == {"met1.2": 4}
    assert [c.description for c in report.all(DrcCategory)] == ["Metal1 spacing < 0.14um (met1.2)"]
    assert {c.name: c.ref_layout for c in report.all(DrcCell)} == {"top": Top().layout, "sub": Sub().layout}
    assert {(b.item.cell.name, b.rect) for b in report.all(DrcBox)} == {
        ("sub", Rect4I(960, 0, 1000, 1000)), ("sub", Rect4I(1100, 0, 1140, 1000)),
        ("top", Rect4I(-140, 0, -100, 1000)), ("top", Rect4I(0, 0, 40, 1000))}
