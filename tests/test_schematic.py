# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Most schematic-related stuff is tested through test_renderview.py.
Error-related stuff could previously not be tested there, so it is tested in
this module instead.
"""

import pytest
from ordec.core import *
from ordec.core.context import SchematicViewBuilder
from .lib import schematics as lib_test
from ordec.lib.base import Res
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
    assert any(e.error_type == SchemErrorType.NetMissesWiring and e.pos == Vec2R(7, 4) for e in errors)

def test_schematic_net_partitioned_tapped():
    s = lib_test.TestNmosInv(variant='net_partitioned_tapped', add_conn_points=True, add_terminal_taps=False).schematic
    assert not s.has_errors()

def test_schematic_net_partitioned_port_labeled():
    # One partition carries a tap and the other contains the vss port. Both
    # display the net name, so the partition is connected by label.
    s = lib_test.TestNmosInv(variant='net_partitioned_port_labeled', add_conn_points=True, add_terminal_taps=False).schematic
    assert not s.has_errors()

def test_schematic_net_partitioned_unlabeled_main():
    # The port labels the smaller island of net n. The larger, pins-only
    # island must still be flagged, since nothing displays its net
    # membership -- even though it is the net's largest component.
    res = Res(r=R(1000)).symbol
    s = Schematic()
    s.n = Net()
    s.n2 = Net()
    s.r1 = SchemInstance(res.portmap(p=s.n, n=s.n2), pos=Vec2R(0, 2))
    s.r2 = SchemInstance(res.portmap(p=s.n, n=s.n2), pos=Vec2R(6, 2))
    s.r3 = SchemInstance(res.portmap(p=s.n, n=s.n), pos=Vec2R(12, 2))
    s.n % SchemPort(pos=Vec2R(0, 8), align=East)
    s.n % SchemWire(vertices=[Vec2R(0, 8), Vec2R(2, 8), Vec2R(2, 6)])
    s.n % SchemWire(vertices=[Vec2R(8, 6), Vec2R(8, 8), Vec2R(11, 8),
                              Vec2R(14, 8), Vec2R(14, 6)])
    s.n % SchemWire(vertices=[Vec2R(14, 2), Vec2R(14, 0), Vec2R(18, 0),
                              Vec2R(18, 10), Vec2R(11, 10), Vec2R(11, 8)])
    s.n2 % SchemWire(vertices=[Vec2R(2, 2), Vec2R(2, 0), Vec2R(8, 0), Vec2R(8, 2)])
    s.check(add_conn_points=True)
    errors = list(s.all(SchemErrorMarker))
    assert [e.error_type for e in errors] == [SchemErrorType.NetMissesWiring]
    # The marker sits on a terminal of the unlabeled island.
    assert errors[0].pos in (Vec2R(8, 6), Vec2R(14, 6), Vec2R(14, 2))

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

def test_schematic_overlapping_instances():
    s = lib_test.TestNmosInv(variant='overlapping_instances', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.OverlappingInstances for e in errors)

def test_schematic_touching_instances():
    s = lib_test.TestNmosInv(variant='touching_instances', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.OverlappingInstances for e in errors)

def test_schematic_segment_short():
    s = lib_test.TestNmosInv(variant='segment_short', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.OverlappingWires for e in errors)

def test_schematic_segment_overlap():
    s = lib_test.TestNmosInv(variant='segment_overlap', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.OverlappingWires for e in errors)

def test_schematic_incorrect_pin_conn():
    s = lib_test.TestNmosInv(variant='incorrect_pin_conn', add_conn_points=True, add_terminal_taps=False).schematic
    errors = list(s.all(SchemErrorMarker))
    assert any(e.error_type == SchemErrorType.IncorrectTerminalConnection for e in errors)

def test_schematic_incorrect_port_conn():
    with pytest.raises(UniqueViolation):
        lib_test.TestNmosInv(variant='incorrect_port_conn', add_conn_points=True, add_terminal_taps=False).schematic

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
    assert any(e.error_type == SchemErrorType.OverlappingInstances for e in errors)

def test_scheminstance_unresolved_resolution():
    sym = Nmos(l='2u', w='5u').symbol
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
        9: SchemInstance.Tuple(pos=Vec2R(R('1.'), R('2.')), orientation=R0, symbol=sym),
        10: NPath.Tuple(parent=None, name='myinst', ref=9),
        11: SchemInstanceConn.Tuple(ref=9, here=1, there=sym.g.nid),
        12: SchemInstanceConn.Tuple(ref=9, here=3, there=sym.s.nid),
        13: SchemInstanceConn.Tuple(ref=9, here=5, there=sym.d.nid),
        14: SchemInstanceConn.Tuple(ref=9, here=7, there=sym.b.nid),
    })

    s = Schematic()
    ctx = SchematicViewBuilder(s)

    s.g = Net()
    s.s = Net()
    s.d = Net()
    s.b = Net()

    s.myinst = SchemInstance(pos=(1, 2))
    ctx.register_unresolved(s.myinst, Nmos)
    ctx.record_unresolved_conn(s.myinst, s.g, ('g',))
    ctx.record_unresolved_conn(s.myinst, s.s, ('s',))
    ctx.record_unresolved_conn(s.myinst, s.d, ('d',))
    ctx.record_unresolved_conn(s.myinst, s.b, ('b',))
    ctx.set_unresolved_param(s.myinst, 'l', '1u')
    ctx.set_unresolved_param(s.myinst, 'w', '5u')
    # Parameters are open until resolution; the last assignment wins:
    ctx.set_unresolved_param(s.myinst, 'l', '2u')

    assert s.myinst.symbol is None
    ctx.resolve_all_instances()
    assert s.myinst.symbol is not None

    assert s.matches(s_ref)

def test_scheminstance_unresolved_hierarchical_path():
    s = Schematic()
    ctx = SchematicViewBuilder(s)

    s.mynet = Net()

    s.myinst = SchemInstance(pos=(0, 0))
    ctx.register_unresolved(s.myinst, lib_test.MultibitReg_StructOfArrays)
    ctx.set_unresolved_param(s.myinst, 'bits', 4)
    ctx.record_unresolved_conn(s.myinst, s.mynet, ('data', 'd', 3))

    ctx.resolve_all_instances()

    conn = list(s.myinst.conns())[0]
    assert conn.here == s.mynet
    assert conn.there == lib_test.MultibitReg_StructOfArrays(bits=4).symbol.data.d[3]

def test_annotations():
    from .lib.ord import annotations as lib_ann
    import re
    # Symbol viewgens start with the default block and can adjust it:
    sym = lib_ann.Box(n=1).symbol
    assert [(a.kind, a.text, a.shown) for a in sym.all(SymbolAnnotation)] == [
        (AnnotationKind.InstanceName, None, True),
        (AnnotationKind.CellName, 'Box', False),
        (AnnotationKind.Param, 'n=1', True),
        (AnnotationKind.Param, 'm=1', False), # left at its default
    ]
    # A symbol on its own has no instance name to show:
    assert 'class="instanceName"' not in sym.render().svg().decode()

    sch = lib_ann.Top().schematic
    # b1 is placed at its symbol's hint, b2 keeps its explicit position; the
    # outline covers both blocks:
    assert sch.b1.annotation_pos == Vec2R(3, 7)
    assert sch.b2.annotation_pos == Vec2R(9, 7)
    assert sch.outline.uy >= 7
    svg = sch.render().svg().decode()
    assert svg.count('>Box<') == 2 # SymbolText of both instances
    assert re.findall(r'class="instanceName">(\w+)<', svg) == ['b1', 'b2']
    # b2 places its block explicitly, West-aligned (text-anchor end):
    b2_block = svg.split('class="symbolOutline"')[2]
    assert 'text-anchor="end"' in b2_block and 'n=2' in b2_block

    # Per-instance overrides of the shown flag:
    s = Schematic(outline=(0, 0, 8, 8))
    s.b = SchemInstance(pos=(0, 0), symbol=lib_ann.Box(n=2).symbol)
    by_text = {a.text: a for a in s.b.symbol.all(SymbolAnnotation)}
    s % SchemAnnotationOverride(ref=s.b, there=by_text['n=2'], shown=False)
    s % SchemAnnotationOverride(ref=s.b, there=by_text['Box'], shown=True)
    svg = s.render().svg().decode()
    assert 'n=2' not in svg
    assert re.findall(r'class="cellName">Box<', svg) == ['class="cellName">Box<'] * 2

    # Flatter arrangement: instance and cell name share one text row.
    s.b.annotation_pos = (5, 5)
    s.b.annotation_wrap = 20
    assert '<tspan class="instanceName">b</tspan> <tspan class="cellName">Box</tspan>' in s.render().svg().decode()

def test_pin_show_flags():
    from ordec.lib.generic_mos import Nmos, Inv
    # The MOS symbol hides its pin arrows and labels. Hidden labels are
    # still output, for the detail view of the web UI:
    svg = Nmos().symbol.render().svg().decode()
    assert 'class="pinArrow"' not in svg and 'class="pinLabel"' not in svg
    assert svg.count('class="pinLabel detail"') == 4
    svg = Inv().symbol.render().svg().decode()
    assert svg.count('class="pinArrow"') == 4 and svg.count('class="pinLabel"') == 4

def test_annotation_placement():
    from ordec.schematic.annotate import block_rects, schematic_obstacles, symbol_body, fits, rect_gap
    from ordec.lib.generic_mos import Inv
    from .lib.ord import strongarm
    # Inv wires manually (blocks are placed at render time), Strongarm runs
    # the viewgen pipeline and has mirrored instances. No block may overlap
    # another shape or block, and all stay close to their instance. For this,
    # the blocks of Inv need a flatter arrangement than the default.
    for sch in (Inv().schematic, strongarm.Strongarm().schematic):
        obstacles = [r.tofloat() for r in schematic_obstacles(sch)]
        rects = block_rects(sch)
        assert len(rects) == len(list(sch.all(SchemInstance)))
        for nid, (rect, wrap) in rects.items():
            others = [r.tofloat() for n, (r, w) in rects.items() if n != nid]
            assert fits(rect.tofloat(), obstacles + others)
            inst = sch.cursor_at(nid)
            body = symbol_body(inst.symbol, inst.loc_transform(), inst)
            assert rect_gap(rect.tofloat(), body.tofloat()) == 0
            if inst.annotation_pos is not None:
                # Blocks left of their symbol are right-aligned.
                assert (inst.annotation_align == West) == (rect.cx < body.cx)
    assert all(wrap > 0 for rect, wrap in block_rects(Inv().schematic).values())

def test_scheminstance_params_without_viewgen():
    s = Schematic()
    s.myinst = SchemInstance(pos=(0, 0), symbol=Nmos().symbol)
    with pytest.raises(TypeError, match="viewgen body"):
        s.myinst.params.l = '2u'
