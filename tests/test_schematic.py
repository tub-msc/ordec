# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Most schematic-related stuff is tested through test_renderview.py.
Error-related stuff could previously not be tested there, so it is tested in
this module instead.
"""

import pytest
from ordec.core import *
from .lib import schematics as lib_test
from ordec.lib.generic_mos import Nmos
from ordec.schematic import SchematicError

def test_schematic_unconnected_conn_point():
    s = lib_test.TestNmosInv(variant='unconnected_conn_point', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.IncorrectlyPlacedSchemConnPoint for e in errors)

def test_schematic_missing_conn_point():
    s = lib_test.TestNmosInv(variant='default', add_conn_points=False, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.MissingSchemConnPoint for e in errors)

def test_schematic_manual_conn_point():
    lib_test.TestNmosInv(variant='manual_conn_points', add_conn_points=False, add_terminal_taps=False).schematic

def test_schematic_net_partitioned():
    s = lib_test.TestNmosInv(variant='net_partitioned', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.NetMissesWiring for e in errors)

def test_schematic_net_partitioned_tapped():
    lib_test.TestNmosInv(variant='net_partitioned_tapped', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_bad_wiring():
    s = lib_test.TestNmosInv(variant='vdd_bad_wiring', add_conn_points=True, add_terminal_taps=True).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.UnconnectedWiring for e in errors)

def test_schematic_missing_terminal_connection():
    s = lib_test.TestNmosInv(variant='skip_vdd_wiring', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.MissingTerminalConnection for e in errors)

def test_schematic_missing_terminal_connection2():
    s = lib_test.TestNmosInv(variant='skip_single_pin', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.MissingTerminalConnection for e in errors)

def test_schematic_add_terminal_taps():
    lib_test.TestNmosInv(variant='skip_vdd_wiring', add_conn_points=True, add_terminal_taps=True).schematic

def test_schematic_stray_conn_point():
    s = lib_test.TestNmosInv(variant='stray_conn_point', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.StraySchemConnPoint for e in errors)

def test_schematic_tap_short():
    s = lib_test.TestNmosInv(variant='tap_short', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.GeometricShort for e in errors)

def test_schematic_poly_short():
    s = lib_test.TestNmosInv(variant='poly_short', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.GeometricShort for e in errors)

def test_schematic_incorrect_pin_conn():
    s = lib_test.TestNmosInv(variant='incorrect_pin_conn', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.IncorrectTerminalConnection for e in errors)

def test_schematic_incorrect_port_conn():
    s = lib_test.TestNmosInv(variant='incorrect_port_conn', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.IncorrectTerminalConnection for e in errors)

def test_schematic_portmap_missing_key():
    s = lib_test.TestNmosInv(variant='portmap_missing_key', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.UnconnectedPin for e in errors)

def test_schematic_portmap_stray_key():
    with pytest.raises(ModelViolation, match=r"ExternalRef invalid reference"):
        lib_test.TestNmosInv(variant='portmap_stray_key', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_portmap_bad_value():
    with pytest.raises(DanglingExternalRef):
        lib_test.TestNmosInv(variant='portmap_bad_value', add_conn_points=True, add_terminal_taps=False).schematic

def test_schematic_terminal_multiple_wires():
    s = lib_test.TestNmosInv(variant='terminal_multiple_wires', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.TerminalMultipleConnections for e in errors)

def test_schematic_terminal_connpoint():
    s = lib_test.TestNmosInv(variant='terminal_connpoint', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.SchemConnPointOverlappingTerminal for e in errors)

def test_schematic_double_connpoint():
    s = lib_test.TestNmosInv(variant='double_connpoint', add_conn_points=False, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.OverlappingSchemConnPoints for e in errors)

def test_schematic_double_instance():
    s = lib_test.TestNmosInv(variant='double_instance', add_conn_points=False, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.OverlappingTerminals for e in errors)

def test_scheminstance_unresolved():
    s_ref = MutableSubgraph.load({
        0: Schematic.Tuple(symbol=None, outline=None, cell=None, default_supply=None, default_ground=None),
        1: Net.Tuple(pin=None),
        2: NPath.Tuple(parent=None, name='g', ref=1),
        3: Net.Tuple(pin=None),
        4: NPath.Tuple(parent=None, name='s', ref=3),
        5: Net.Tuple(pin=None),
        6: NPath.Tuple(parent=None, name='d', ref=5),
        7: Net.Tuple(pin=None),
        8: NPath.Tuple(parent=None, name='b', ref=7),
        9: SchemInstance.Tuple(pos=Vec2R(R('1.'), R('2.')), orientation=R0, symbol=Nmos(l='2u', w='5u').symbol),
        10: NPath.Tuple(parent=None, name='myinst', ref=9),
        11: SchemInstanceConn.Tuple(ref=9, here=1, there=1),
        12: SchemInstanceConn.Tuple(ref=9, here=3, there=3),
        13: SchemInstanceConn.Tuple(ref=9, here=5, there=5),
        14: SchemInstanceConn.Tuple(ref=9, here=7, there=7),
    })

    s = Schematic()

    s.g = Net()
    s.s = Net()
    s.d = Net()
    s.b = Net()

    s.myinst = SchemInstanceUnresolved(pos=(1, 2), resolver=lambda **params: Nmos(**params).symbol)
    s.myinst % SchemInstanceUnresolvedConn(here=s.g, there=('g',))
    s.myinst % SchemInstanceUnresolvedConn(here=s.s, there=('s',))
    s.myinst % SchemInstanceUnresolvedConn(here=s.d, there=('d',))
    s.myinst % SchemInstanceUnresolvedConn(here=s.b, there=('b',))
    s.myinst % SchemInstanceUnresolvedParameter(name='l', value='2u')
    s.myinst % SchemInstanceUnresolvedParameter(name='w', value='5u')

    s.resolve_instances()

    assert s.matches(s_ref)

def test_scheminstance_unresolved_hierarchical_path():
    s = Schematic()

    s.mynet = Net()

    resolver = lambda **params: lib_test.MultibitReg_StructOfArrays(**params).symbol

    s.myinst = SchemInstanceUnresolved(resolver=resolver, pos=(0, 0))

    s.myinst % SchemInstanceUnresolvedParameter(name='bits', value=4)
    conn_u = s.myinst % SchemInstanceUnresolvedConn(here=s.mynet, there=('data', 'd', 3))

    s.resolve_instances()

    conn = list(s.myinst.conns())[0]
    assert conn.nid == conn_u.nid
    assert conn.here == s.mynet
    assert conn.there == lib_test.MultibitReg_StructOfArrays(bits=4).symbol.data.d[3]
