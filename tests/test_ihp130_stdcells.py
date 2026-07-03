# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from subprocess import CalledProcessError

from ordec.core import Directory
from ordec.core.schema import LvsCircuitPair
from ordec.extlibrary import ExtLibrary
from ordec.lib import ihp130

stdcell_root = ihp130.pdk().root / "libs.ref/sg13g2_stdcell"


def build_lib():
    lib = ExtLibrary()
    lib.read_lef(stdcell_root / "lef/sg13g2_stdcell.lef")
    lib.read_gds(stdcell_root / "gds/sg13g2_stdcell.gds", ihp130.SG13G2().layers)
    lib.read_spice(stdcell_root / "spice/sg13g2_stdcell.spice", device_map=ihp130.device_map)
    return lib


def test_lvs_match():
    lib = build_lib()
    inv = lib["sg13g2_inv_1"]
    # The GDS reader associates the layout with its ExtLibraryCell, so that
    # LVS names the layout topcell and the schematic subckt identically.
    # LVS pairing relies on layout and symbol/schematic sharing the same
    # singleton cell object, so assert identity, not just equality.
    assert inv.layout.cell is inv
    report = ihp130.run_lvs(inv.layout, inv.symbol)
    assert report.clean()
    pairs = {(p.layout_cell, p.schem_cell) for p in report.all(LvsCircuitPair)}
    assert pairs == {("sg13g2_inv_1", "SG13G2_INV_1")}


def test_lvs_fatal_name_mismatch():
    # LVS of a layout against the schematic of a different cell must never
    # match. The distinct topcell/subckt names make KLayout's alignment step
    # abort; only a silent match would be a bug.
    lib = build_lib()
    try:
        report = ihp130.run_lvs(lib["sg13g2_inv_1"].layout, lib["sg13g2_nand2_1"].symbol)
    except CalledProcessError:
        # TODO: This is not really nice behavior. Maybe we can improve the
        # Python-side UX of this type of fatal LVS error at some point.
        return
    assert not report.clean()


def test_lvs_name_collision():
    # Same-named cells from different ExtLibrary instances are distinct cell
    # objects and must never share a name within one Directory (a shared name
    # would let LVS pair a layout and a schematic of different cells).
    lib1 = build_lib()
    lib2 = build_lib()
    d = Directory()
    name1 = d.name_cell(lib1["sg13g2_inv_1"])
    name2 = d.name_cell(lib2["sg13g2_inv_1"])
    assert name1 == "sg13g2_inv_1"
    assert name2 != name1
    assert name2.startswith("sg13g2_inv_1")
