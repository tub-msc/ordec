# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec import lib, render_image
from ordec.lib import test as lib_test
import ordec.importer
from ordec.lib.examples import diffpair
from ordec.helpers import SchematicError
import importlib.resources
#import reference
import cairo
"""
Comparing symbol + schematic images to reference images.

To copy test results in as reference:

    cp /tmp/pytest-of-[username]/pytest-current/test_schematic_image*/*.png [dir]/tests/reference
"""


refdir = importlib.resources.files("tests.reference")

testdata = [
    (lib.Inv().schematic, refdir/"inverter_schematic.png"),
    (lib.Inv().symbol, refdir/"inverter_symbol.png"),
    (lib.Ringosc().schematic, refdir/"ringosc_schematic.png"),
    (lib_test.RotateTest().schematic, refdir/"rotatetest_schematic.png"),
    (lib.And2().symbol, refdir/"and2_symbol.png"),
    (lib.Or2().symbol, refdir/"or2_symbol.png"),
    (lib_test.PortAlignTest().schematic, refdir/"portaligntest_schematic.png"),
    (lib_test.TapAlignTest().schematic, refdir/"tapaligntest_schematic.png"),
    (lib_test.MultibitReg_Arrays(bits=5).symbol, refdir/"multibitref_arrays5_symbol.png"),
    (lib_test.MultibitReg_Arrays(bits=5).schematic, refdir/"multibitref_arrays5_schematic.png"),
    (lib_test.MultibitReg_Arrays(bits=32).symbol, refdir/"multibitref_arrays32_symbol.png"),
    (lib_test.MultibitReg_ArrayOfStructs(bits=5).symbol, refdir/"multibitref_arrayofstructs5_symbol.png"),
    (lib_test.MultibitReg_StructOfArrays(bits=5).symbol, refdir/"multibitref_structofarrays5_symbol.png"),
    (lib_test.TestNmosInv(variant='default', add_conn_points=True, add_terminal_taps=False).schematic, refdir/"testnmosinv.png"),
    (lib_test.TestNmosInv(variant='no_wiring', add_conn_points=False, add_terminal_taps=True).schematic, refdir/"testnmosinv_nowiring.png"),
    (diffpair.DiffPair().schematic, refdir/"ord_diffpair.png"),
    (diffpair.DiffPairTb().schematic, refdir/"ord_diffpair_tb.png"),
]

@pytest.mark.parametrize("testcase", testdata, ids=lambda t: t[1].with_suffix("").name)
def test_schematic_image(testcase, tmp_path):
    view, ref_file = testcase
    img = render_image(view)
    (tmp_path / ref_file.name).write_bytes(img.as_png())

    img_ref = cairo.ImageSurface.create_from_png(ref_file)

    assert img.surface.get_data() == img_ref.get_data()


def test_schematic_unconnected_conn_point():
    with pytest.raises(SchematicError, match=r"Incorrectly placed SchemConnPoint"):
        lib_test.TestNmosInv(variant='unconnected_conn_point', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_missing_conn_point():
    with pytest.raises(SchematicError, match=r"Missing SchemConnPoint"):
        lib_test.TestNmosInv(variant='default', add_conn_points=False, add_terminal_taps=False).schematic

def test_schematic_manual_conn_point():
    lib_test.TestNmosInv(variant='manual_conn_points', add_conn_points=False, add_terminal_taps=False).schematic

def test_schematic_net_partitioned():
    with pytest.raises(SchematicError, match=r"misses wiring to locations"):
        lib_test.TestNmosInv(variant='net_partitioned', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_net_partitioned_tapped():
    lib_test.TestNmosInv(variant='net_partitioned_tapped', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_bad_wiring():
    with pytest.raises(SchematicError, match=r"Unconnected wiring at"):
        lib_test.TestNmosInv(variant='vdd_bad_wiring', add_conn_points=True, add_terminal_taps=True).schematic

def test_schematic_missing_terminal_connection():
    with pytest.raises(SchematicError, match=r"Missing terminal connection at"):
        lib_test.TestNmosInv(variant='skip_vdd_wiring', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_missing_terminal_connection2():
    with pytest.raises(SchematicError, match=r"Missing terminal connection at"):
        lib_test.TestNmosInv(variant='skip_single_pin', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_add_terminal_taps():
    lib_test.TestNmosInv(variant='skip_vdd_wiring', add_conn_points=True, add_terminal_taps=True).schematic

def test_schematic_stray_conn_point():
    with pytest.raises(SchematicError, match=r"Stray SchemConnPoint"):
        lib_test.TestNmosInv(variant='stray_conn_point', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_tap_short():
    with pytest.raises(SchematicError, match=r"Geometric short at"):
        lib_test.TestNmosInv(variant='tap_short', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_poly_short():
    with pytest.raises(SchematicError, match=r"Geometric short at"):
        lib_test.TestNmosInv(variant='poly_short', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_incorrect_pin_conn():
    with pytest.raises(SchematicError, match=r"Incorrect terminal connection at"):
        lib_test.TestNmosInv(variant='incorrect_pin_conn', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_incorrect_port_conn():
    with pytest.raises(SchematicError, match=r"Incorrect terminal connection at"):
        lib_test.TestNmosInv(variant='incorrect_port_conn', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_portmap_missing_key():
    with pytest.raises(SchematicError, match=r"Missing pins"):
        lib_test.TestNmosInv(variant='portmap_missing_key', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_portmap_stray_key():
    with pytest.raises(SchematicError, match=r"Stray pins"):
        lib_test.TestNmosInv(variant='portmap_stray_key', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_portmap_bad_value():
    with pytest.raises(TypeError):
        lib_test.TestNmosInv(variant='portmap_bad_value', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_terminal_multiple_wires():
    with pytest.raises(SchematicError, match=r"Terminal with more than one connection"):
        lib_test.TestNmosInv(variant='terminal_multiple_wires', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_terminal_connpoint():
    with pytest.raises(SchematicError, match=r"SchemConnPoint overlapping terminal"):
        lib_test.TestNmosInv(variant='terminal_connpoint', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_double_connpoint():
    with pytest.raises(SchematicError, match=r"Overlapping SchemConnPoints at"):
        lib_test.TestNmosInv(variant='double_connpoint', add_conn_points=False, add_terminal_taps=False).schematic

def test_schematic_double_instance():
    with pytest.raises(SchematicError, match=r"Overlapping terminals at"):
        lib_test.TestNmosInv(variant='double_instance', add_conn_points=False, add_terminal_taps=False).schematic