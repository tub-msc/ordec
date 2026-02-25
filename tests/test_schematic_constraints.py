# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *
from ordec.core.constraints import (
    LinearTerm, Vec2LinearTerm, Rect4LinearTerm, TD4LinearTerm
)


class SimpleSymbol(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self, outline=Rect4R(0, 0, 4, 6))
        s.inp = Pin(pos=Vec2R(0, 3), pintype=PinType.In, align=D4.West)
        s.out = Pin(pos=Vec2R(4, 3), pintype=PinType.Out, align=D4.East)
        return s


class MultiPinSymbol(Cell):
    bits = Parameter(int)

    @generate
    def symbol(self):
        s = Symbol(cell=self, outline=Rect4R(0, 0, 4, 2 + self.bits))
        s.d = PathNode()
        s.q = PathNode()
        for i in range(self.bits):
            s.d[i] = Pin(pos=Vec2R(0, 1 + i), pintype=PinType.In, align=D4.West)
            s.q[i] = Pin(pos=Vec2R(4, 1 + i), pintype=PinType.Out, align=D4.East)
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
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol, orientation=D4.R90)

    solver = Solver(sch)
    solver.constrain(sch.inst1.outline.lx == 10)
    solver.constrain(sch.inst1.outline.ly == 20)
    solver.solve()

    # R90: (x,y) -> (-y, x), outline (0,0,4,6) -> corners become (0,0), (0,4), (-6,4), (-6,0)
    # lx=-6+pos.x=10 -> pos.x=16; ly=0+pos.y=20 -> pos.y=20
    assert sch.inst1.pos == Vec2R(16, 20)


def test_outline_transform():
    sch = Schematic()
    sch.inst1 = SchemInstance(symbol=SimpleSymbol().symbol, orientation=Orientation.R90)

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
