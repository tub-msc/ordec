# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.base import *
from ordec.ordb import MutableSubgraph, NPath
from ordec.lib.generic_mos import Inv, Nmos, Pmos

def test_example_symbol():
    ref = MutableSubgraph.load({
        0: Symbol.head(outline=Rect4R(lx=R('0.'), ly=R('0.'), ux=R('4.'), uy=R('4.')), cell=Inv()),
        21: NPath(parent=None, name='vdd', ref=20),
        23: NPath(parent=None, name='vss', ref=22),
        25: NPath(parent=None, name='a', ref=24),
        27: NPath(parent=None, name='y', ref=26),
        20: Pin(pintype=PinType.Inout, pos=Vec2R(x=R('2.'), y=R('4.')), align=D4.R0),
        22: Pin(pintype=PinType.Inout, pos=Vec2R(x=R('2.'), y=R('0.')), align=D4.R180),
        24: Pin(pintype=PinType.In, pos=Vec2R(x=R('0.'), y=R('2.')), align=D4.R90),
        26: Pin(pintype=PinType.Out, pos=Vec2R(x=R('4.'), y=R('2.')), align=D4.R270),
        29: PolyVec2R(ref=28, order=0, pos=Vec2R(x=R('0.'), y=R('2.'))),
        30: PolyVec2R(ref=28, order=1, pos=Vec2R(x=R('1.'), y=R('2.'))),
        32: PolyVec2R(ref=31, order=0, pos=Vec2R(x=R('3.25'), y=R('2.'))),
        33: PolyVec2R(ref=31, order=1, pos=Vec2R(x=R('4.'), y=R('2.'))),
        35: PolyVec2R(ref=34, order=0, pos=Vec2R(x=R('1.'), y=R('1.'))),
        36: PolyVec2R(ref=34, order=1, pos=Vec2R(x=R('1.'), y=R('3.'))),
        37: PolyVec2R(ref=34, order=2, pos=Vec2R(x=R('2.75'), y=R('2.'))),
        38: PolyVec2R(ref=34, order=3, pos=Vec2R(x=R('1.'), y=R('1.'))),
        39: SymbolArc(pos=Vec2R(x=R('3.'), y=R('2.')), radius=R('250m')),
        28: SymbolPoly(),
        31: SymbolPoly(),
        34: SymbolPoly(),
    })

    symbol = Inv().symbol
    symbol2 = Inv().symbol

    assert symbol == symbol2
    assert symbol2 == symbol

    assert symbol == ref
    assert ref == symbol

def test_example_schematic():
    ref = MutableSubgraph.load({
        0: Schematic.head(symbol=Inv().symbol, outline=Rect4R(lx=R('0.'), ly=R('1.'), ux=R('10.'), uy=R('13.')), cell=Inv()),
        1: Net(pin=5),
        2: NPath(parent=None, name='a', ref=1),
        3: Net(pin=7),
        4: NPath(parent=None, name='y', ref=3),
        5: Net(pin=1),
        6: NPath(parent=None, name='vdd', ref=5),
        7: Net(pin=3),
        8: NPath(parent=None, name='vss', ref=7),
        9: SchemInstance(pos=Vec2R(x=R('3.'), y=R('2.')), orientation=D4.R0, symbol=Nmos(l=R('250n'),w=R('500n')).symbol),
        10: SchemInstanceConn(ref=9, here=7, there=3),
        11: SchemInstanceConn(ref=9, here=7, there=7),
        12: SchemInstanceConn(ref=9, here=1, there=1),
        13: SchemInstanceConn(ref=9, here=3, there=5),
        14: NPath(parent=None, name='pd', ref=9),
        15: SchemInstance(pos=Vec2R(x=R('3.'), y=R('8.')), orientation=D4.R0, symbol=Pmos(l=R('250n'),w=R('500n')).symbol),
        16: SchemInstanceConn(ref=15, here=5, there=5),
        17: SchemInstanceConn(ref=15, here=5, there=7),
        18: SchemInstanceConn(ref=15, here=1, there=1),
        19: SchemInstanceConn(ref=15, here=3, there=3),
        20: NPath(parent=None, name='pu', ref=15),
        21: SchemPort(ref=5, pos=Vec2R(x=R('2.'), y=R('13.')), align=D4.R270),
        22: SchemPort(ref=7, pos=Vec2R(x=R('2.'), y=R('1.')), align=D4.R270),
        23: SchemPort(ref=1, pos=Vec2R(x=R('1.'), y=R('7.')), align=D4.R270),
        24: SchemPort(ref=3, pos=Vec2R(x=R('9.'), y=R('7.')), align=D4.R90),
        25: SchemWire(ref=7),
        26: PolyVec2R(ref=25, order=0, pos=Vec2R(x=R('2.'), y=R('1.'))),
        27: PolyVec2R(ref=25, order=1, pos=Vec2R(x=R('5.'), y=R('1.'))),
        28: PolyVec2R(ref=25, order=2, pos=Vec2R(x=R('8.'), y=R('1.'))),
        29: PolyVec2R(ref=25, order=3, pos=Vec2R(x=R('8.'), y=R('4.'))),
        30: PolyVec2R(ref=25, order=4, pos=Vec2R(x=R('7.'), y=R('4.'))),
        31: SchemWire(ref=7),
        32: PolyVec2R(ref=31, order=0, pos=Vec2R(x=R('5.'), y=R('1.'))),
        33: PolyVec2R(ref=31, order=1, pos=Vec2R(x=R('5.'), y=R('2.'))),
        34: SchemWire(ref=5),
        35: PolyVec2R(ref=34, order=0, pos=Vec2R(x=R('2.'), y=R('13.'))),
        36: PolyVec2R(ref=34, order=1, pos=Vec2R(x=R('5.'), y=R('13.'))),
        37: PolyVec2R(ref=34, order=2, pos=Vec2R(x=R('8.'), y=R('13.'))),
        38: PolyVec2R(ref=34, order=3, pos=Vec2R(x=R('8.'), y=R('10.'))),
        39: PolyVec2R(ref=34, order=4, pos=Vec2R(x=R('7.'), y=R('10.'))),
        40: SchemWire(ref=5),
        41: PolyVec2R(ref=40, order=0, pos=Vec2R(x=R('5.'), y=R('13.'))),
        42: PolyVec2R(ref=40, order=1, pos=Vec2R(x=R('5.'), y=R('12.'))),
        43: SchemWire(ref=1),
        44: PolyVec2R(ref=43, order=0, pos=Vec2R(x=R('3.'), y=R('4.'))),
        45: PolyVec2R(ref=43, order=1, pos=Vec2R(x=R('2.'), y=R('4.'))),
        46: PolyVec2R(ref=43, order=2, pos=Vec2R(x=R('2.'), y=R('7.'))),
        47: PolyVec2R(ref=43, order=3, pos=Vec2R(x=R('2.'), y=R('10.'))),
        48: PolyVec2R(ref=43, order=4, pos=Vec2R(x=R('3.'), y=R('10.'))),
        49: SchemWire(ref=1),
        50: PolyVec2R(ref=49, order=0, pos=Vec2R(x=R('1.'), y=R('7.'))),
        51: PolyVec2R(ref=49, order=1, pos=Vec2R(x=R('2.'), y=R('7.'))),
        52: SchemWire(ref=3),
        53: PolyVec2R(ref=52, order=0, pos=Vec2R(x=R('5.'), y=R('6.'))),
        54: PolyVec2R(ref=52, order=1, pos=Vec2R(x=R('5.'), y=R('7.'))),
        55: PolyVec2R(ref=52, order=2, pos=Vec2R(x=R('5.'), y=R('8.'))),
        56: SchemWire(ref=3),
        57: PolyVec2R(ref=56, order=0, pos=Vec2R(x=R('5.'), y=R('7.'))),
        58: PolyVec2R(ref=56, order=1, pos=Vec2R(x=R('9.'), y=R('7.'))),
        59: SchemConnPoint(ref=7, pos=Vec2R(x=R('2.'), y=R('7.'))),
        60: SchemConnPoint(ref=7, pos=Vec2R(x=R('5.'), y=R('7.'))),
        61: SchemConnPoint(ref=7, pos=Vec2R(x=R('5.'), y=R('13.'))),
        62: SchemConnPoint(ref=7, pos=Vec2R(x=R('5.'), y=R('1.'))),
    })

    schematic = Inv().schematic

    assert schematic == ref
