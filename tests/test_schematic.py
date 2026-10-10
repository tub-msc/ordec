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
    s.n % SchemPort(pos=Vec2R(0, 8), orient=East)
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
        9: SchemInstance.Tuple(pos=Vec2R(R('1.'), R('2.')), orient=R0, symbol=sym),
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
    # Symbol viewgens start with the default annotations and can adjust them:
    sym = lib_ann.Box(n=1).symbol
    assert [(a.key, a.value, a.shown) for a in sym.all(SymbolAnnotation)] == [
        (AnnotationKind.InstanceName, None, True),
        (AnnotationKind.CellName, 'Box', True), # in a fixed stack
        ('n', '1', True),
        ('m', '1', False), # left at its default
    ]
    # Keys are unique per symbol:
    with pytest.raises(UniqueViolation):
        sym.thaw() % SymbolAnnotation(key='n', value='2')
    # A symbol on its own has no instance name to show:
    assert 'class="instanceName"' not in sym.render().svg().decode()

    sch = lib_ann.Top().schematic
    # b1 is placed by place_annotations, b2 keeps its explicit position; the
    # outline covers both blocks:
    assert sch.b1.annotation_pos is not None
    assert sch.b2.annotation_pos == Vec2R(9, 7)
    assert sch.outline.uy >= 7
    svg = sch.render().svg().decode()
    assert svg.count('>Box<') == 2 # fixed stack of both instances
    assert re.findall(r'class="instanceName">(\w+)<', svg) == ['b1', 'b2']
    # b2 places its block explicitly, West-aligned (text-anchor end):
    b2_block = svg.split('class="symbolOutline"')[2]
    assert 'text-anchor="end"' in b2_block and 'n=2' in b2_block

    # Per-instance overrides of the shown flag:
    s = Schematic(outline=(0, 0, 8, 8))
    s.b = SchemInstance(pos=(0, 0), symbol=lib_ann.Box(n=2).symbol)
    line = lambda key: s.b.symbol.one(SymbolAnnotation.key_idx.query(key))
    s % SchemAnnotationOverride(ref=s.b, there=line('n'), shown=False)
    s % SchemAnnotationOverride(ref=s.b, there=line('m'), shown=True)
    s % SchemAnnotationOverride(ref=s.b, there=line(AnnotationKind.CellName), shown=False) # fixed stack
    svg = s.render().svg().decode()
    assert 'n=2' not in svg and 'm=1' in svg and 'class="cellName"' not in svg

    # Flatter arrangement: instance name and parameter share one text row.
    s.b.annotation_pos = (5, 5)
    s.b.annotation_wrap = 20
    assert '<tspan class="instanceName">b</tspan> <tspan class="params">m=1</tspan>' in s.render().svg().decode()

    # A stack centered vertically on pos is centered horizontally in an
    # instance rotated by 90 degrees:
    sym = Symbol(outline=(0, 0, 4, 4))
    sym % SymbolAnnotation(key=AnnotationKind.CellName, value='X',
        ref=sym % SymbolAnnotationStack(pos=(2, 2), valign=VAlign.Middle))
    s = Schematic(outline=(0, 0, 4, 4))
    s.x = SchemInstance(pos=(4, 0), orient=R90, symbol=sym.freeze())
    assert 'text-anchor="middle"' in s.render().svg().decode()

def test_pin_show_flags():
    from ordec.lib.generic_mos import Nmos, Inv
    # The MOS symbol hides its pin arrows and labels. Hidden labels are
    # still output, for the detail view of the web UI:
    svg = Nmos().symbol.render().svg().decode()
    assert 'class="pinArrow"' not in svg and 'class="pinLabel"' not in svg
    assert svg.count('class="pinLabel detailOnly"') == 4
    svg = Inv().symbol.render().svg().decode()
    assert svg.count('class="pinArrow"') == 4 and svg.count('class="pinLabel"') == 4
    # Without rotate_label, labels of vertical stubs are not rotated:
    for rotate, n_rotated in ((True, 2), (False, 0)):
        s = Symbol(outline=(0, 0, 4, 4))
        s.d = Pin(pos=(2, 4), orient=North, rotate_label=rotate)
        s.s = Pin(pos=(2, 0), orient=South, rotate_label=rotate)
        s.g = Pin(pos=(0, 2), orient=West, rotate_label=rotate)
        assert s.freeze().render().svg().decode().count('<text transform="matrix(0 ') == n_rotated
    # A centered label of a vertical stub without rotate_label is centered
    # across the stub:
    s = Symbol(outline=(0, 0, 4, 4))
    s.d = Pin(pos=(2, 4), orient=North, rotate_label=False, center_label=True)
    assert 'text-anchor="middle"' in s.freeze().render().svg().decode()

def test_annotation_placement():
    from ordec.schematic.annotate import block_rects, schematic_obstacles, symbol_body, fits, rect_gap
    from ordec.lib.generic_mos import Inv
    from .lib.ord import strongarm
    # Inv wires manually and calls place_annotations itself, Strongarm runs
    # the viewgen pipeline and has mirrored instances. No block may overlap
    # another shape or block, and all stay close to their instance.
    for sch in (Inv().schematic, strongarm.Strongarm().schematic):
        obstacles = [r.tofloat() for r in schematic_obstacles(sch)]
        rects = block_rects(sch)
        assert len(rects) == len(list(sch.all(SchemInstance)))
        for nid, (rect, wrap, halign) in rects.items():
            others = [r.tofloat() for n, (r, w, h) in rects.items() if n != nid]
            assert fits(rect.tofloat(), obstacles + others)
            inst = sch.cursor_at(nid)
            body = symbol_body(inst.symbol, inst.loc_transform(), inst)
            assert rect_gap(rect.tofloat(), body.tofloat()) == 0
            if rect.ux <= body.lx:
                # Blocks left of their symbol are right-aligned.
                assert halign == HAlign.Right
    # An explicitly placed block is an obstacle for the blocks of instances
    # before it in node order, too:
    s = Schematic(outline=(0, 0, 20, 10))
    s.a = SchemInstance(pos=(2, 2), symbol=Nmos().symbol)
    s.b = SchemInstance(pos=(12, 2), symbol=Nmos().symbol, annotation_pos=(5, 5))
    rects = block_rects(s)
    assert fits(rects[s.a.nid][0].tofloat(), [rects[s.b.nid][0].tofloat()])
    # VcoRing leaves stage_n[0] no empty spot. Its block covers a wire then,
    # but still stays nearer to its own symbol than to any other.
    from ordec.examples.vco_pseudodiff import VcoRing
    sch = VcoRing().schematic
    bodies = {inst.nid: symbol_body(inst.symbol, inst.loc_transform(), inst).tofloat()
        for inst in sch.all(SchemInstance)}
    for nid, (rect, wrap, halign) in block_rects(sch).items():
        others = [rect_gap(rect.tofloat(), b) for n, b in bodies.items() if n != nid]
        assert rect_gap(rect.tofloat(), bodies[nid]) < min(others)
    # Blocks of box symbols go above their top left corner, left-aligned and
    # moved further left where pin labels are in the way (the others go
    # beside their symbols, see above).
    from .lib.ord import d_latch
    sch = d_latch.D_latch().schematic
    for nid, (rect, wrap, halign) in block_rects(sch).items():
        inst = sch.cursor_at(nid)
        outline = inst.loc_transform() * inst.symbol.outline
        assert inst.symbol.is_box and halign == HAlign.Left
        assert rect.lx <= outline.lx and rect.ly >= outline.uy
    # Rotations by 90 degrees keep East as preferred side: the NoConn
    # instances of VcoTb (R90 and R270) all get their block on the right.
    from ordec.examples.vco_pseudodiff import VcoTb
    sch = VcoTb().schematic
    for i in range(4):
        nc = sch.nc[i]
        assert nc.annotation_pos.x > (nc.loc_transform() * nc.symbol.outline).cx

def test_scheminstance_params_without_viewgen():
    s = Schematic()
    s.myinst = SchemInstance(pos=(0, 0), symbol=Nmos().symbol)
    with pytest.raises(TypeError, match="viewgen body"):
        s.myinst.params.l = '2u'
