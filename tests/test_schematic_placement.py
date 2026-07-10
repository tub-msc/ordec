# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the schematic placement pipeline: constraints from ORD `!`
statements solved in SchematicViewContext.postprocess, placement groups
(Col/Row/Series/Parallel) and align-based auto-placement of ports
(schem_place_ports).
"""

import pytest

import ordec.importer
from ordec.core import *
from ordec.lib.generic_mos import Nmos, Pmos
from ordec.schematic.helpers import schem_place_ports


def net_of(sch, inst, pin_name):
    """Returns the Net connected to a pin of a resolved SchemInstance."""
    pin_nid = getattr(inst.symbol, pin_name).nid
    for conn in sch.all(SchemInstanceConn.ref_idx.query(inst)):
        if conn.there.nid == pin_nid:
            return conn.here
    return None


def test_ord_schematic_solver_and_port_autoplace():
    from .lib.ord.inverter_solver import Inv

    sch = Inv().schematic

    # Instance positions from ! constraints
    assert sch.pd.pos == Vec2R(2, 2)
    assert sch.pu.pos == Vec2R(2, 10)

    # Content bbox is (2,2)-(6,14); ports sit two units outside the edge
    # opposite to their arrow direction, lined up with the connected pin
    # nearest to their edge.
    assert sch.a.pos == Vec2R(0, 4)    # left edge, at pd.g (2,4)
    assert sch.y.pos == Vec2R(8, 6)    # right edge, at pd.d (4,6)
    assert sch.vss.pos == Vec2R(4, 0)  # bottom edge, at pd.s (4,2)
    assert sch.vdd.pos == Vec2R(4, 16) # top edge, at pu.s (4,14)

    assert not sch.has_errors()


def test_place_ports_declaration_order_and_stacking():
    # Two ports on the same edge: declaration order, top to bottom,
    # centered on the edge.
    class TwoIn(Cell):
        @generate
        def symbol(self):
            s = Symbol(cell=self, outline=Rect4R(0, 0, 4, 4))
            s.i0 = Pin(pos=Vec2R(0, 1), pintype=PinType.In, align=West)
            s.i1 = Pin(pos=Vec2R(0, 3), pintype=PinType.In, align=West)
            return s

    sym = TwoIn().symbol
    sch = Schematic(symbol=sym)
    sch.inst = SchemInstance(symbol=sym, pos=Vec2R(0, 0))
    sch.i0 = Net(pin=sym.i0)
    sch.i1 = Net(pin=sym.i1)
    p0 = sch.i0 % SchemPort(align=East)
    p1 = sch.i1 % SchemPort(align=East)

    schem_place_ports(sch)

    # bbox (0,0)-(4,4), left edge at x=-2, centered on cy=2
    assert p0.pos == Vec2R(-2, 2)
    assert p1.pos == Vec2R(-2, 1)


def test_ord_col_group_auto_anchor():
    from .lib.ord.inverter_stack import Inv

    sch = Inv().schematic

    # Col stacks pu above pd with gap 4; auto-anchored at (0, 0).
    assert sch.pd.pos == Vec2R(0, 0)
    assert sch.pu.pos == Vec2R(0, 8)

    # Ports auto-placed around the (0,0)-(4,12) bbox, lined up with the
    # connected pin nearest to their edge.
    assert sch.a.pos == Vec2R(-2, 2)   # at pd.g (0,2)
    assert sch.y.pos == Vec2R(6, 4)    # at pd.d (2,4)
    assert sch.vss.pos == Vec2R(2, -2) # at pd.s (2,0)
    assert sch.vdd.pos == Vec2R(2, 14) # at pu.s (2,12)

    assert not sch.has_errors()


def test_ord_col_group_manual_anchor():
    from .lib.ord.inverter_stack import InvAnchored

    sch = InvAnchored().schematic

    # ! stack.southwest == (3, 1) replaces the automatic anchor.
    assert sch.pd.pos == Vec2R(3, 1)
    assert sch.pu.pos == Vec2R(3, 9)
    assert not sch.has_errors()


def test_nested_groups_python_api():
    class Box(Cell):
        @generate
        def symbol(self):
            return Symbol(cell=self, outline=Rect4R(0, 0, 4, 4))

    sym = Box().symbol
    sch = Schematic(symbol=sym)
    sch.a = SchemInstance(symbol=sym)
    sch.b = SchemInstance(symbol=sym)
    sch.c = SchemInstance(symbol=sym)

    col = Col(gap=2)
    col.add(sch.a)
    col.add(sch.b)
    row = Row(gap=3)
    row.add(col)
    row.add(sch.c)

    solver = Solver(sch)
    row.emit(solver)
    solver.solve()

    # col: a above b -> b (0,0)-(4,4), a (0,6)-(4,10); col spans (0,0)-(4,10)
    # row: c east of col with gap 3, centered on col's vertical center
    assert sch.b.pos == Vec2R(0, 0)
    assert sch.a.pos == Vec2R(0, 6)
    assert sch.c.pos == Vec2R(7, 3)


def test_ord_series_auto_connection():
    from .lib.ord.inverter_series import Inv

    sch = Inv().schematic

    # Placement: vdd/pu/pd/vss stacked top to bottom, anchored at (0, 0).
    assert sch.pd.pos == Vec2R(0, 4)
    assert sch.pu.pos == Vec2R(0, 12)
    assert sch.vdd.pos == Vec2R(2, 20)
    assert sch.vss.pos == Vec2R(2, 0)

    # Auto-connections along the chain.
    assert net_of(sch, sch.pu, 's').nid == sch.vdd.nid
    assert net_of(sch, sch.pd, 's').nid == sch.vss.nid
    # .b -- vss inside the pd body connected to the forward-declared net,
    # which the later port statement bound to the symbol pin.
    assert net_of(sch, sch.pd, 'b').nid == sch.vss.nid
    assert sch.vss.pin.nid == Inv().symbol.vss.nid
    # Junction pu.d--pd.d reuses the explicitly wired net y.
    assert net_of(sch, sch.pu, 'd').nid == sch.y.nid
    assert net_of(sch, sch.pd, 'd').nid == sch.y.nid

    assert not sch.has_errors()


class TwoTop(Cell):
    """Symbol with an ambiguous (two-pin) north side."""
    @generate
    def symbol(self):
        s = Symbol(cell=self, outline=Rect4R(0, 0, 4, 4))
        s.a = Pin(pos=Vec2R(1, 4), align=North, pintype=PinType.Inout)
        s.b = Pin(pos=Vec2R(3, 4), align=North, pintype=PinType.Inout)
        s.c = Pin(pos=Vec2R(2, 0), align=South, pintype=PinType.Inout)
        return s


def test_series_ambiguous_pins_error():
    sym = TwoTop().symbol
    sch = Schematic(symbol=sym)
    sch.i1 = SchemInstance(symbol=sym)
    sch.i2 = SchemInstance(symbol=sym)
    group = Series(gap=2)
    group.add(sch.i1)
    group.add(sch.i2)

    with pytest.raises(ValueError, match="exactly one upward-facing pin"):
        group.emit(Solver(sch))


def test_series_pin_override_and_anonymous_net():
    sym = TwoTop().symbol
    sch = Schematic(symbol=sym)
    sch.i1 = SchemInstance(symbol=sym)
    sch.i2 = SchemInstance(symbol=sym)
    group = Series(gap=2, top='a', bottom='c')
    group.add(sch.i1)
    group.add(sch.i2)

    solver = Solver(sch)
    group.emit(solver)
    solver.solve(allow_undefined=True)

    # Default align='pins': i2 shifts right by 1 so that i1.c (x=2) and
    # i2.a (x=1 within its symbol) line up.
    assert sch.i1.pos == Vec2R(0, 6)
    assert sch.i2.pos == Vec2R(1, 0)
    assert sch.i1.c.pos.x == sch.i2.a.pos.x
    # i1.c and i2.a share an anonymous net.
    net = net_of(sch, sch.i1, 'c')
    assert net is not None
    assert net.nid == net_of(sch, sch.i2, 'a').nid


def test_series_horizontal():
    class RSym(Cell):
        @generate
        def symbol(self):
            s = Symbol(cell=self, outline=Rect4R(0, 0, 4, 2))
            s.l = Pin(pos=Vec2R(0, 1), align=West, pintype=PinType.Inout)
            s.r = Pin(pos=Vec2R(4, 1), align=East, pintype=PinType.Inout)
            return s

    sym = RSym().symbol
    sch = Schematic(symbol=sym)
    sch.r1 = SchemInstance(symbol=sym)
    sch.r2 = SchemInstance(symbol=sym)
    sch.r3 = SchemInstance(symbol=sym)
    group = Series(gap=2, horizontal=True)
    group.add(sch.r1)
    group.add(sch.r2)
    group.add(sch.r3)

    solver = Solver(sch)
    group.emit(solver)
    solver.solve(allow_undefined=True)

    assert sch.r1.pos == Vec2R(0, 0)
    assert sch.r2.pos == Vec2R(6, 0)
    assert sch.r3.pos == Vec2R(12, 0)
    # Adjacent right/left pins share anonymous junction nets.
    n12 = net_of(sch, sch.r1, 'r')
    n23 = net_of(sch, sch.r2, 'r')
    assert n12.nid == net_of(sch, sch.r2, 'l').nid
    assert n23.nid == net_of(sch, sch.r3, 'l').nid
    assert n12.nid != n23.nid


def test_parallel_auto_connection():
    class RSym(Cell):
        @generate
        def symbol(self):
            s = Symbol(cell=self, outline=Rect4R(0, 0, 2, 4))
            s.p = Pin(pos=Vec2R(1, 4), align=North, pintype=PinType.Inout)
            s.m = Pin(pos=Vec2R(1, 0), align=South, pintype=PinType.Inout)
            return s

    sym = RSym().symbol
    sch = Schematic(symbol=sym)
    sch.r1 = SchemInstance(symbol=sym)
    sch.r2 = SchemInstance(symbol=sym)
    sch.out = Net()
    # Naming one rail explicitly: r1.p is pre-wired to net out.
    sch.r1 % SchemInstanceConn(here=sch.out, there=sym.p)
    group = Parallel(gap=2)
    group.add(sch.r1)
    group.add(sch.r2)

    solver = Solver(sch)
    group.emit(solver)
    solver.solve(allow_undefined=True)

    # Side by side, left to right.
    assert sch.r1.pos == Vec2R(0, 0)
    assert sch.r2.pos == Vec2R(4, 0)
    # Top rail reuses the explicitly wired net, bottom rail is anonymous.
    assert net_of(sch, sch.r1, 'p').nid == sch.out.nid
    assert net_of(sch, sch.r2, 'p').nid == sch.out.nid
    bottom = net_of(sch, sch.r1, 'm')
    assert bottom is not None
    assert bottom.nid == net_of(sch, sch.r2, 'm').nid
    assert bottom.nid != sch.out.nid


def test_ord_nand_nested_parallel_in_series():
    from .lib.ord.nand_placement import Nand2

    sch = Nand2().schematic

    # One Series stack vdd/pullup/pd_a/pd_b/vss, with the Parallel pull-up
    # nested inside; auto-anchored at (0, 0).
    assert sch.vdd.pos == Vec2R(6, 28)
    assert sch.pu_a.pos == Vec2R(0, 20)
    assert sch.pu_b.pos == Vec2R(8, 20)
    assert sch.pd_a.pos == Vec2R(4, 12)
    assert sch.pd_b.pos == Vec2R(4, 4)
    assert sch.vss.pos == Vec2R(6, 0)

    # Parallel rails: sources on vdd, drains on y.
    assert net_of(sch, sch.pu_a, 's').nid == sch.vdd.nid
    assert net_of(sch, sch.pu_b, 's').nid == sch.vdd.nid
    assert net_of(sch, sch.pu_a, 'd').nid == sch.y.nid
    assert net_of(sch, sch.pu_b, 'd').nid == sch.y.nid

    # Series pull-down: y -> pd_a -> (anonymous) -> pd_b -> vss.
    assert net_of(sch, sch.pd_a, 'd').nid == sch.y.nid
    junction = net_of(sch, sch.pd_a, 's')
    assert junction.nid == net_of(sch, sch.pd_b, 'd').nid
    assert junction.nid not in (sch.y.nid, sch.vss.nid)
    assert net_of(sch, sch.pd_b, 's').nid == sch.vss.nid

    assert not sch.has_errors()


def test_ord_two_toplevel_groups_side_by_side():
    from .lib.ord.two_stacks import TwoStacks

    sch = TwoStacks().schematic

    # Both Col groups are auto-anchored: the first at (0, 0), the second
    # beside it with 4 units of routing space, instead of overlapping.
    assert sch.pd_l.pos == Vec2R(0, 0)
    assert sch.pu_l.pos == Vec2R(0, 8)
    assert sch.pd_r.pos == Vec2R(8, 0)
    assert sch.pu_r.pos == Vec2R(8, 8)


def test_group_follows_pinned_child():
    sch = Schematic()
    sch.pu = SchemInstance(symbol=Pmos().symbol, pos=Vec2R(3, 7))
    sch.pd = SchemInstance(symbol=Nmos().symbol)
    group = Col(gap=2)
    group.add(sch.pu)
    group.add(sch.pd)

    solver = Solver(sch)
    # The directly assigned pu position suppresses the automatic anchor;
    # the group follows the pinned child.
    assert group.emit(solver) is False
    solver.solve(allow_undefined=True)
    assert sch.pd.pos == Vec2R(3, 1)


def test_group_contradiction_clear_error():
    sch = Schematic()
    sch.m = SchemInstance(symbol=Nmos().symbol)
    group = Col(gap=2)
    group.add(sch.m)
    group.add(sch.m)

    with pytest.raises(ValueError, match="contradicts"):
        group.emit(Solver(sch))


def test_group_net_without_port_error():
    sch = Schematic()
    sch.m = SchemInstance(symbol=Nmos().symbol)
    sch.n = Net()
    group = Col(gap=2)
    group.add(sch.m)
    group.add(sch.n)

    with pytest.raises(ValueError, match="has no port"):
        group.emit(Solver(sch))


def test_group_unknown_attribute_does_not_seal():
    group = Col(gap=2)
    with pytest.raises(AttributeError):
        group.no_such_attribute
    assert not group.sealed


def test_ord_hierarchical_buf():
    from .lib.ord.buf_hier import Buf

    sch = Buf().schematic

    # Two Inv subcells side by side (Inv symbol is 4x4), anchored at (0,0).
    assert sch.i0.pos == Vec2R(0, 0)
    assert sch.i1.pos == Vec2R(8, 0)

    # Horizontal series: i0.y and i1.a share an anonymous stage net.
    stage = net_of(sch, sch.i0, 'y')
    assert stage.nid == net_of(sch, sch.i1, 'a').nid
    assert stage.nid not in (sch.a.nid, sch.y.nid)

    # Explicit wiring to the outer ports.
    assert net_of(sch, sch.i0, 'a').nid == sch.a.nid
    assert net_of(sch, sch.i1, 'y').nid == sch.y.nid
    assert net_of(sch, sch.i0, 'vdd').nid == sch.vdd.nid
    assert net_of(sch, sch.i1, 'vss').nid == sch.vss.nid

    assert not sch.has_errors()


def test_series_nested_in_parallel():
    # AOI-style pull-down: (n1 in series with n2) in parallel with n3.
    sym = Nmos().symbol
    sch = Schematic()
    sch.n1 = SchemInstance(symbol=sym)
    sch.n2 = SchemInstance(symbol=sym)
    sch.n3 = SchemInstance(symbol=sym)
    inner = Series(gap=2)
    inner.add(sch.n1)
    inner.add(sch.n2)
    outer = Parallel(gap=4)
    outer.add(inner)
    outer.add(sch.n3)

    solver = Solver(sch)
    outer.emit(solver)
    solver.solve(allow_undefined=True)

    # Placement: inner stack left, n3 beside it, vertically centered.
    assert sch.n2.pos == Vec2R(0, 0)
    assert sch.n1.pos == Vec2R(0, 6)
    assert sch.n3.pos == Vec2R(8, 3)

    # Rails connect through the nested series stack's boundary pins.
    top = net_of(sch, sch.n1, 'd')
    bottom = net_of(sch, sch.n2, 's')
    junction = net_of(sch, sch.n1, 's')
    assert top.nid == net_of(sch, sch.n3, 'd').nid
    assert bottom.nid == net_of(sch, sch.n3, 's').nid
    assert junction.nid == net_of(sch, sch.n2, 'd').nid
    assert len({top.nid, bottom.nid, junction.nid}) == 3


class WideCell(Cell):
    """Non-square symbol (8x4) with two pins on its south side."""
    @generate
    def symbol(self):
        s = Symbol(cell=self, outline=Rect4R(0, 0, 8, 4))
        s.o1 = Pin(pos=Vec2R(2, 0), align=South, pintype=PinType.Inout)
        s.o2 = Pin(pos=Vec2R(6, 0), align=South, pintype=PinType.Inout)
        s.i = Pin(pos=Vec2R(4, 4), align=North, pintype=PinType.Inout)
        return s


class NarrowCell(Cell):
    """Non-square symbol (3x4) with single north/south pins."""
    @generate
    def symbol(self):
        s = Symbol(cell=self, outline=Rect4R(0, 0, 3, 4))
        s.t = Pin(pos=Vec2R(1, 4), align=North, pintype=PinType.Inout)
        s.b = Pin(pos=Vec2R(1, 0), align=South, pintype=PinType.Inout)
        return s


def test_series_multi_pin_side_requires_override():
    sch = Schematic()
    sch.w = SchemInstance(symbol=WideCell().symbol)
    sch.n = SchemInstance(symbol=NarrowCell().symbol)
    group = Series()
    group.add(sch.w)
    group.add(sch.n)

    with pytest.raises(ValueError, match="exactly one downward-facing pin"):
        group.emit(Solver(sch))


def test_series_non_square_symbols_override_and_snap():
    sch = Schematic()
    sch.w = SchemInstance(symbol=WideCell().symbol)
    sch.n = SchemInstance(symbol=NarrowCell().symbol)
    # bottom= only applies where a downward-facing pin is needed: on w,
    # whose south side faces n. n's south side is the open boundary.
    group = Series(gap=2, bottom='o2', align='center')
    group.add(sch.w)
    group.add(sch.n)

    solver = Solver(sch)
    group.emit(solver)
    solver.solve(allow_undefined=True)

    # 8-wide over 3-wide: centering offset floor((8-3)/2) = 2 keeps the
    # narrow cell on the unit grid.
    assert sch.w.pos == Vec2R(0, 6)
    assert sch.n.pos == Vec2R(2, 0)

    # The override picked o2; o1 stays unconnected.
    junction = net_of(sch, sch.w, 'o2')
    assert junction is not None
    assert junction.nid == net_of(sch, sch.n, 't').nid
    assert net_of(sch, sch.w, 'o1') is None


def test_parallel_multi_pin_side_override():
    sch = Schematic()
    sch.w1 = SchemInstance(symbol=WideCell().symbol)
    sch.w2 = SchemInstance(symbol=WideCell().symbol)
    group = Parallel(bottom='o1')
    group.add(sch.w1)
    group.add(sch.w2)

    solver = Solver(sch)
    group.emit(solver)
    solver.solve(allow_undefined=True)

    # Top rail via unambiguous i pins, bottom rail via the o1 override.
    assert net_of(sch, sch.w1, 'i').nid == net_of(sch, sch.w2, 'i').nid
    assert net_of(sch, sch.w1, 'o1').nid == net_of(sch, sch.w2, 'o1').nid
    assert net_of(sch, sch.w1, 'o2') is None
    assert net_of(sch, sch.w2, 'o2') is None


def test_series_align_pins():
    # align='pins' lines the facing pins up for a straight junction wire,
    # instead of centering the differently-sized bounding boxes.
    sch = Schematic()
    sch.w = SchemInstance(symbol=WideCell().symbol)
    sch.n = SchemInstance(symbol=NarrowCell().symbol)
    group = Series(gap=2, bottom='o2', align='pins')
    group.add(sch.w)
    group.add(sch.n)

    solver = Solver(sch)
    group.emit(solver)
    solver.solve(allow_undefined=True)

    assert sch.w.pos == Vec2R(0, 6)
    assert sch.n.pos == Vec2R(5, 0)
    # w.o2 at x=6 and n.t at x=5+1=6: the junction is vertical.
    assert sch.w.o2.pos.x == sch.n.t.pos.x


def test_groups_snap_odd_sizes_to_grid():
    # A Parallel with gap 3 spans 11 units; centering the 4-wide pull-down
    # under it must stay on the unit grid (the router cannot reach
    # half-grid pins).
    sch = Schematic()
    sch.pu_a = SchemInstance(symbol=Pmos().symbol)
    sch.pu_b = SchemInstance(symbol=Pmos().symbol)
    sch.pd = SchemInstance(symbol=Nmos().symbol)
    par = Parallel(gap=3)
    par.add(sch.pu_a)
    par.add(sch.pu_b)
    ser = Series(gap=4)
    ser.add(par)
    ser.add(sch.pd)

    solver = Solver(sch)
    ser.emit(solver)
    solver.solve(allow_undefined=True)

    assert sch.pd.pos == Vec2R(3, 0)
    for inst in (sch.pu_a, sch.pu_b, sch.pd):
        assert inst.pos.x.denominator == 1
        assert inst.pos.y.denominator == 1


def test_ord_amp_two_multi_pin_symbols():
    from .lib.ord.amp_multipin import Amp

    sch = Amp().schematic

    # Col stacks the load over the nested Series (diff pair, tail, vss).
    assert sch.load.pos == Vec2R(0, 21)
    assert sch.dp.pos == Vec2R(0, 12)
    assert sch.tail.pos == Vec2R(0, 4)
    assert sch.vss.pos == Vec2R(2, 0)

    # Series junction dp.tail -- tail.d is anonymous; tail.s lands on vss.
    junction = net_of(sch, sch.dp, 'tail')
    assert junction.nid == net_of(sch, sch.tail, 'd').nid
    assert junction.nid != sch.vss.nid
    assert net_of(sch, sch.tail, 's').nid == sch.vss.nid

    # The two parallel load/diff-pair junctions are wired explicitly.
    assert net_of(sch, sch.load, 'outp').nid == sch.outp.nid
    assert net_of(sch, sch.dp, 'outp').nid == sch.outp.nid
    assert net_of(sch, sch.load, 'outn').nid == sch.outn.nid
    assert net_of(sch, sch.dp, 'outn').nid == sch.outn.nid
    # Matching pins of the two multi-pin symbols line up vertically.
    assert sch.load.outp.pos.x == sch.dp.outp.pos.x
    assert sch.load.outn.pos.x == sch.dp.outn.pos.x

    assert not sch.has_errors()


class WestPinCell(Cell):
    """4x4 symbol with a single west-facing pin."""
    @generate
    def symbol(self):
        s = Symbol(cell=self, outline=Rect4R(0, 0, 4, 4))
        s.i = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=West)
        return s


def test_place_ports_pin_alignment():
    sym = WestPinCell().symbol
    sch = Schematic()
    sch.top = SchemInstance(symbol=sym, pos=Vec2R(0, 6))
    sch.bot = SchemInstance(symbol=sym, pos=Vec2R(0, 0))
    sch.n1 = Net()
    sch.n2 = Net()
    sch.n3 = Net()
    sch.top % SchemInstanceConn(here=sch.n1, there=sym.i)
    sch.bot % SchemInstanceConn(here=sch.n2, there=sym.i)
    p1 = sch.n1 % SchemPort(align=East)
    p2 = sch.n2 % SchemPort(align=East)
    p3 = sch.n3 % SchemPort(align=East) # no pins -> fallback stacking

    schem_place_ports(sch)

    # p1/p2 line up with their pins at y=8 and y=2 (bbox (0,0)-(4,10));
    # p3 has no pin to align with and stacks centered on the edge.
    assert p1.pos == Vec2R(-2, 8)
    assert p2.pos == Vec2R(-2, 2)
    assert p3.pos == Vec2R(-2, 5)


def test_place_ports_alignment_collision():
    sym = WestPinCell().symbol
    sch = Schematic()
    sch.l = SchemInstance(symbol=sym, pos=Vec2R(0, 0))
    sch.r = SchemInstance(symbol=sym, pos=Vec2R(8, 0))
    sch.na = Net()
    sch.nb = Net()
    sch.l % SchemInstanceConn(here=sch.na, there=sym.i)
    sch.r % SchemInstanceConn(here=sch.nb, there=sym.i)
    pa = sch.na % SchemPort(align=East)
    pb = sch.nb % SchemPort(align=East)

    schem_place_ports(sch)

    # Both pins sit on row 2; the port declared later shifts one unit
    # down instead of overlapping.
    assert pa.pos == Vec2R(-2, 2)
    assert pb.pos == Vec2R(-2, 1)


def test_group_errors_on_anonymous_instance():
    # Nodes are not required to have an NPath; error messages must not
    # assume one (full_path_str raises on anonymous nodes).
    sym = TwoTop().symbol
    sch = Schematic(symbol=sym)
    i1 = sch % SchemInstance(symbol=sym)
    i2 = sch % SchemInstance(symbol=sym)
    group = Series(gap=2)
    group.add(i1)
    group.add(i2)

    with pytest.raises(ValueError,
            match=r"upward-facing pin on SchemInstance(\.Mutable)?\(nid="):
        group.emit(Solver(sch))


def test_group_conflict_error_on_anonymous_nets():
    sym = Nmos().symbol
    sch = Schematic()
    sch.m1 = SchemInstance(symbol=sym)
    sch.m2 = SchemInstance(symbol=sym)
    # The facing pins of the series junction m1.s -- m2.d are pre-wired
    # to two different anonymous nets.
    sch.m1 % SchemInstanceConn(here=sch % Net(), there=sym.s)
    sch.m2 % SchemInstanceConn(here=sch % Net(), there=sym.d)
    group = Series(gap=2)
    group.add(sch.m1)
    group.add(sch.m2)

    with pytest.raises(ValueError,
            match=r"Connection conflict: .* Net(\.Mutable)?\(nid=\d+\)"):
        group.emit(Solver(sch))


def test_place_ports_keeps_defined_positions():
    class OneIn(Cell):
        @generate
        def symbol(self):
            s = Symbol(cell=self, outline=Rect4R(0, 0, 4, 4))
            s.i0 = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=West)
            return s

    sym = OneIn().symbol
    sch = Schematic(symbol=sym)
    sch.inst = SchemInstance(symbol=sym, pos=Vec2R(0, 0))
    sch.i0 = Net(pin=sym.i0)
    p0 = sch.i0 % SchemPort(align=East, pos=Vec2R(10, 10))

    schem_place_ports(sch)

    assert p0.pos == Vec2R(10, 10)
