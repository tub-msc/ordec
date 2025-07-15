# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Most schematic-related stuff is tested through test_renderview.py.
Exception-related stuff cannot be tested there, so it is tested in this module
instead.
"""

import pytest
from ordec.lib import test as lib_test
from ordec.helpers import SchematicError

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
    with pytest.raises(KeyError):
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
