# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.core import *
from ordec.core.constraints import LinearTerm, Vec2LinearTerm, Rect4LinearTerm, TD4LinearTerm
from ordec.ord.context import set_root, view_builder


class SimpleSymbol(Cell):
    @viewgen_noctx
    def symbol(self):
        s = Symbol(cell=self, outline=Rect4R(0, 0, 4, 6))
        s.inp = Pin(pos=Vec2R(0, 3), pintype=PinType.In, align=West)
        s.out = Pin(pos=Vec2R(4, 3), pintype=PinType.Out, align=East)
        return s


class MultiPinSymbol(Cell):
    bits = Parameter(int)

    @viewgen_noctx
    def symbol(self):
        s = Symbol(cell=self, outline=Rect4R(0, 0, 4, 2 + self.bits))
        s.d = PathNode()
        s.q = PathNode()
        for i in range(self.bits):
            s.d[i] = Pin(pos=Vec2R(0, 1 + i), pintype=PinType.In, align=West)
            s.q[i] = Pin(pos=Vec2R(4, 1 + i), pintype=PinType.Out, align=East)
        return s


def test_schem_instance_pos_constrainable():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol)
    assert isinstance(sch.inst1.pos, Vec2LinearTerm)


def test_schem_instance_subcursor_outline():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol)
    assert isinstance(sch.inst1.outline, Rect4LinearTerm)


def test_schem_instance_align_by_outline():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol)
    sch.inst2 = SchemInstance(symbol=SimpleSymbol().symbol)

    solver = Solver(sch)
    solver.constrain(sch.inst1.pos == Vec2R(0, 0))
    solver.constrain(sch.inst2.outline.lx == sch.inst1.outline.ux + 2)
    solver.constrain(sch.inst2.outline.cy == sch.inst1.outline.cy)
    solver.solve()

    assert sch.inst1.pos == Vec2R(0, 0)
    assert sch.inst2.pos == Vec2R(6, 0)


def test_schem_instance_align_by_pin():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol)
    sch.inst2 = SchemInstance(symbol=SimpleSymbol().symbol)

    solver = Solver(sch)
    solver.constrain(sch.inst1.pos == Vec2R(0, 0))
    solver.constrain(sch.inst2.inp.pos == sch.inst1.out.pos)
    solver.solve()

    assert sch.inst1.pos == Vec2R(0, 0)
    assert sch.inst2.pos == Vec2R(4, 0)

def test_rational_coefficient():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol)
    sch.inst2 = SchemInstance(symbol=SimpleSymbol().symbol)

    solver = Solver(sch)
    solver.constrain(sch.inst1.pos == Vec2R(5, 5))
    solver.constrain(sch.inst2.pos == Vec2R(1,1) + R('1/2')*sch.inst1.pos)
    solver.solve()

    assert sch.inst1.pos == Vec2R(5, 5)
    assert sch.inst2.pos == Vec2R('7/2', '7/2')


def test_schem_instance_hierarchical_pins():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=MultiPinSymbol(bits=4).symbol)
    sch.inst2 = SchemInstance(symbol=MultiPinSymbol(bits=4).symbol)

    solver = Solver(sch)
    solver.constrain(sch.inst1.pos == Vec2R(0, 0))
    solver.constrain(sch.inst2['d'][0].pos == sch.inst1['q'][0].pos)
    solver.solve()

    assert sch.inst1.pos == Vec2R(0, 0)
    assert sch.inst2.pos == Vec2R(4, 0)


def test_schem_instance_with_orientation():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol, orientation=R90)

    solver = Solver(sch)
    solver.constrain(sch.inst1.outline.lx == 10)
    solver.constrain(sch.inst1.outline.ly == 20)
    solver.solve()

    # R90: (x,y) -> (-y, x), outline (0,0,4,6) -> corners become (0,0), (0,4), (-6,4), (-6,0)
    # lx=-6+pos.x=10 -> pos.x=16; ly=0+pos.y=20 -> pos.y=20
    assert sch.inst1.pos == Vec2R(16, 20)


def test_outline_transform():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol, orientation=R90)

    solver = Solver(sch)
    solver.constrain(sch.inst1.outline.center == Vec2R(3, 4))
    solver.solve()

    assert sch.inst1.outline.center == Vec2R(3, 4)


def test_rational_precision():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol)

    solver = Solver(sch)
    solver.constrain(sch.inst1.pos.x == R('3/2'))
    solver.constrain(sch.inst1.pos.y == R('7/4'))
    solver.solve()

    assert sch.inst1.pos.x == R('3/2')
    assert sch.inst1.pos.y == R('7/4')


def test_multiple_instances_chain():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol)
    sch.inst2 = SchemInstance(symbol=SimpleSymbol().symbol)
    sch.inst3 = SchemInstance(symbol=SimpleSymbol().symbol)

    solver = Solver(sch)
    solver.constrain(sch.inst1.pos == Vec2R(0, 0))
    solver.constrain(sch.inst2.outline.lx == sch.inst1.outline.ux + 2)
    solver.constrain(sch.inst2.outline.cy == sch.inst1.outline.cy)
    solver.constrain(sch.inst3.outline.lx == sch.inst2.outline.ux + 2)
    solver.constrain(sch.inst3.outline.cy == sch.inst2.outline.cy)
    solver.solve()

    assert sch.inst1.pos == Vec2R(0, 0)
    assert sch.inst2.pos == Vec2R(6, 0)
    assert sch.inst3.pos == Vec2R(12, 0)


def test_defined_pos_not_placeholder():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol, pos=Vec2R(10, 20))

    assert isinstance(sch.inst1.pos, Vec2R)
    assert sch.inst1.pos == Vec2R(10, 20)
    assert isinstance(sch.inst1.outline, Rect4R)
    assert sch.inst1.outline == Rect4R(10, 20, 14, 26)


def test_loc_transform_with_defined_pos():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol, pos=Vec2R(10, 20))
    assert isinstance(sch.inst1.loc_transform(), TD4R)


def test_loc_transform_with_placeholder_pos():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol)
    assert isinstance(sch.inst1.loc_transform(), TD4LinearTerm)


def test_td4linearterm_mul_concrete_td4():
    # Composing a symbolic transform with a concrete one (as transform_stack()
    # does for nested layout instances whose outer position is still an
    # unsolved solver variable) must coerce the concrete operand rather than
    # falling back to tuple.__rmul__ ("cannot be interpreted as an integer").
    outer = TD4I(Vec2I(10, 20), R90)
    inner = TD4I(Vec2I(5, 6), MX)
    concrete = outer * inner

    result = (outer * TD4LinearTerm()) * inner  # value-equal symbolic outer
    assert isinstance(result, TD4LinearTerm)
    assert result.d4 == concrete.d4
    assert result.transl.x.constant == float(concrete.transl.x)
    assert result.transl.y.constant == float(concrete.transl.y)


def test_unresolved_subcursor_uses_recorded_params():
    # Geometry reads on an unresolved instance must resolve the symbol with the
    # parameters recorded so far, not with defaults (MultiPinSymbol has no
    # default for bits, so this raises if params are dropped). The read also
    # resolves the instance: setting parameters afterwards must raise.
    sch = Schematic()

    @viewgen
    def build():
        set_root(sch)
        builder = view_builder()
        sch.inst1 = SchemInstance(pos=Vec2R(1, 1))
        builder.register_unresolved(sch.inst1, MultiPinSymbol)
        sch.inst1.params.bits = 2

        assert sch.inst1['q'][1].pos == Vec2R(5, 3)
        assert sch.inst1.outline.uy == R(5)

        with pytest.raises(TypeError, match="already resolved"):
            sch.inst1.params.bits = 3

    build()


def test_solver_scalar_shared_axis():
    # A solver_scalar() axis shared across two matched pairs propagates the
    # mirror position from the pinned pair to the other one.
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol)
    sch.inst2 = SchemInstance(symbol=SimpleSymbol().symbol)
    sch.inst3 = SchemInstance(symbol=SimpleSymbol().symbol)
    sch.inst4 = SchemInstance(symbol=SimpleSymbol().symbol)

    c = solver_scalar()
    solver = Solver(sch)
    # Pair (inst1, inst2) fully pinned: fixes the shared axis at x=5.
    solver.constrain(sch.inst1.pos == Vec2R(0, 0))
    solver.constrain(sch.inst2.pos == Vec2R(10, 0))
    solver.constrain(sch.inst1.pos.x + sch.inst2.pos.x == 2 * c)
    solver.constrain(sch.inst1.pos.y == sch.inst2.pos.y)
    # Pair (inst3, inst4) coupled to the same axis; inst3 pinned, inst4 solved.
    solver.constrain(sch.inst3.pos.x == 2)
    solver.constrain(sch.inst3.pos.y == 3)
    solver.constrain(sch.inst3.pos.x + sch.inst4.pos.x == 2 * c)
    solver.constrain(sch.inst3.pos.y == sch.inst4.pos.y)
    solver.solve()

    assert sch.inst4.pos == Vec2R(8, 3)
