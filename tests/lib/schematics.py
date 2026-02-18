# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *
from ordec.schematic import helpers
from ordec.lib.generic_mos import Or2, Nmos

class RotateTest(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)
        c = Or2().symbol

        s.R0 = SchemInstance(c.portmap(), pos=Vec2R(1, 1), orientation=Orientation.R0)
        s.R90 = SchemInstance(
            c.portmap(), pos=Vec2R(12, 1), orientation=Orientation.R90
        )
        s.R180 = SchemInstance(
            c.portmap(), pos=Vec2R(18, 6), orientation=Orientation.R180
        )
        s.R270 = SchemInstance(
            c.portmap(), pos=Vec2R(19, 6), orientation=Orientation.R270
        )

        s.MY = SchemInstance(c.portmap(), pos=Vec2R(6, 7), orientation=Orientation.MY)
        s.MY90 = SchemInstance(
            c.portmap(), pos=Vec2R(12, 12), orientation=Orientation.MY90
        )
        s.MX = SchemInstance(c.portmap(), pos=Vec2R(13, 12), orientation=Orientation.MX)
        s.MX90 = SchemInstance(
            c.portmap(), pos=Vec2R(19, 7), orientation=Orientation.MX90
        )

        s.outline = Rect4R(lx=0, ly=0, ux=25, uy=13)
        return s


class PortAlignTest(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.north = Pin(pintype=PinType.In, align=Orientation.North)
        s.south = Pin(pintype=PinType.In, align=Orientation.South)
        s.west = Pin(pintype=PinType.In, align=Orientation.West)
        s.east = Pin(pintype=PinType.In, align=Orientation.East)
        helpers.symbol_place_pins(s)

        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.n1 = Net(pin=self.symbol.north)
        s.n2 = Net(pin=self.symbol.south)
        s.n3 = Net(pin=self.symbol.east)
        s.n4 = Net(pin=self.symbol.west)

        s.n1 % SchemPort(pos=Vec2R(4, 2), align=Orientation.North)
        s.n2 % SchemPort(pos=Vec2R(4, 6), align=Orientation.South)
        s.n3 % SchemPort(pos=Vec2R(2, 4), align=Orientation.East)
        s.n4 % SchemPort(pos=Vec2R(6, 4), align=Orientation.West)

        s.outline = Rect4R(lx=0, ly=0, ux=8, uy=8)
        return s


class TapAlignTest(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.north = Net()
        s.south = Net()
        s.east = Net()
        s.west = Net()

        s.north % SchemTapPoint(pos=Vec2R(4, 6), align=Orientation.North)
        s.south % SchemTapPoint(pos=Vec2R(4, 2), align=Orientation.South)
        s.west % SchemTapPoint(pos=Vec2R(2, 4), align=Orientation.West)
        s.east % SchemTapPoint(pos=Vec2R(6, 4), align=Orientation.East)

        s.outline = Rect4R(lx=0, ly=0, ux=8, uy=8)
        return s


class DFF(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vss = Pin(pintype=PinType.In, align=Orientation.South)
        s.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        s.d = Pin(pintype=PinType.In, align=Orientation.West)
        s.q = Pin(pintype=PinType.Out, align=Orientation.East)
        s.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(s, vpadding=2, hpadding=3)

        return s


class MultibitReg_Arrays(Cell):
    bits = Parameter(int)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vss = Pin(pintype=PinType.In, align=Orientation.South)
        s.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        s.mkpath("d")
        s.mkpath("q")
        for i in range(self.bits):
            s.d[i] = Pin(pintype=PinType.In, align=Orientation.West)
            s.q[i] = Pin(pintype=PinType.Out, align=Orientation.East)
        s.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(s)

        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.vss = Net(pin=self.symbol.vss)
        s.vdd = Net(pin=self.symbol.vdd)
        s.clk = Net(pin=self.symbol.clk)
        s.mkpath("d")
        s.mkpath("q")
        s.mkpath("I")

        s.vss % SchemPort(pos=Vec2R(1, 0), align=Orientation.East)
        s.vdd % SchemPort(pos=Vec2R(1, 1), align=Orientation.East)
        s.clk % SchemPort(pos=Vec2R(1, 2), align=Orientation.East)
        for i in range(self.bits):
            s.d[i] = Net(pin=self.symbol.d[i])
            s.q[i] = Net(pin=self.symbol.q[i])
            s.I[i] = SchemInstance(
                DFF().symbol.portmap(
                    vss=s.vss,
                    vdd=s.vdd,
                    clk=s.clk,
                    d=s.d[i],
                    q=s.q[i],
                ),
                pos=Vec2R(2, 3 + 8 * i),
                orientation=Orientation.R0,
            )

            s.d[i] % SchemPort(pos=Vec2R(1, 5 + 8 * i), align=Orientation.East)
            s.d[i] % SchemWire(vertices=[Vec2R(1, 5 + 8 * i), Vec2R(2, 5 + 8 * i)])
            s.q[i] % SchemPort(pos=Vec2R(9, 5 + 8 * i), align=Orientation.West)
            s.q[i] % SchemWire(vertices=[Vec2R(8, 5 + 8 * i), Vec2R(9, 5 + 8 * i)])

        s.outline = Rect4R(lx=0, ly=0, ux=10, uy=2 + 8 * self.bits)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)

        return s


class MultibitReg_ArrayOfStructs(Cell):
    bits = Parameter(int)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vss = Pin(pintype=PinType.In, align=Orientation.South)
        s.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        s.mkpath("bit")
        for i in range(self.bits):
            s.bit.mkpath(i)
            s.bit[i].d = Pin(pintype=PinType.In, align=Orientation.West)
            s.bit[i].q = Pin(pintype=PinType.Out, align=Orientation.East)
        s.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(s)

        return s


class MultibitReg_StructOfArrays(Cell):
    bits = Parameter(int)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vss = Pin(pintype=PinType.In, align=Orientation.South)
        s.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        s.mkpath("data")
        s.data.mkpath("d")
        s.data.mkpath("q")
        for i in range(self.bits):
            s.data.d[i] = Pin(pintype=PinType.In, align=Orientation.West)
            s.data.q[i] = Pin(pintype=PinType.Out, align=Orientation.East)
        s.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(s)

        return s


class TestNmosInv(Cell):
    """For testing schem_check."""

    variant = Parameter(str)
    add_conn_points = Parameter(bool)
    add_terminal_taps = Parameter(bool)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vdd = Pin(pintype=PinType.Inout, align=Orientation.North)
        s.vss = Pin(pintype=PinType.Inout, align=Orientation.South)
        s.a = Pin(pintype=PinType.In, align=Orientation.West)
        s.y = Pin(pintype=PinType.Out, align=Orientation.East)
        helpers.symbol_place_pins(s)

        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.a = Net(pin=self.symbol.a)
        s.y = Net(pin=self.symbol.y)
        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)

        nmos = Nmos(w=R("500n"), l=R("250n")).symbol

        portmap = nmos.portmap(s=s.vss, b=s.vss, g=s.a, d=s.y)
        if self.variant == "incorrect_pin_conn":
            portmap = nmos.portmap(s=s.vss, b=s.a, g=s.a, d=s.y)
        elif self.variant == "portmap_missing_key":
            portmap = nmos.portmap(s=s.vss, b=s.vss, d=s.y)

        s.pd = SchemInstance(portmap, pos=Vec2R(3, 2))
        if self.variant == "portmap_stray_key":
            s.stray = Net()
            s.pd % SchemInstanceConn(here=s.stray, there=0)
        elif self.variant == "portmap_bad_value":
            list(s.pd.conns())[0].there = 12345

        s.pu = SchemInstance(
            nmos.portmap(d=s.vdd, b=s.vss, g=s.vdd, s=s.y), pos=Vec2R(3, 8)
        )
        if self.variant == "double_instance":
            s.pu2 = SchemInstance(
                nmos.portmap(d=s.vdd, b=s.vss, g=s.vdd, s=s.y), pos=Vec2R(3, 8)
            )

        s.vdd % SchemPort(pos=Vec2R(1, 13), align=Orientation.East)
        s.vss % SchemPort(pos=Vec2R(1, 1), align=Orientation.East)
        s.a % SchemPort(pos=Vec2R(1, 4), align=Orientation.East)
        if self.variant == "incorrect_port_conn":
            s.vss % SchemPort(pos=Vec2R(9, 7), align=Orientation.West)
        else:
            s.y % SchemPort(pos=Vec2R(9, 7), align=Orientation.West)

        if self.variant == "no_wiring":
            s.default_supply = s.vdd
            s.default_ground = s.vss
        else:
            s.vss % SchemWire(
                vertices=[Vec2R(1, 1), Vec2R(5, 1), s.pd.pos + nmos.s.pos]
            )
            if self.variant == "skip_single_pin":
                s.vss % SchemWire(vertices=[Vec2R(7, 4), Vec2R(8, 4)])
            else:
                s.vss % SchemWire(
                    vertices=[Vec2R(7, 4), Vec2R(8, 4), Vec2R(8, 10), Vec2R(7, 10)]
                )
            if self.variant not in ("net_partitioned", "net_partitioned_tapped"):
                s.vss % SchemWire(vertices=[Vec2R(8, 4), Vec2R(8, 1), Vec2R(5, 1)])

            if self.variant == "net_partitioned_tapped":
                s.vss % SchemTapPoint(pos=Vec2R(8, 4), align=Orientation.South)
                s.vss % SchemTapPoint(pos=Vec2R(5, 1), align=Orientation.East)

            if self.variant == "vdd_bad_wiring":
                s.vdd % SchemWire(vertices=[Vec2R(1, 13), Vec2R(2, 13)])
            elif self.variant != "skip_vdd_wiring":
                s.vdd % SchemWire(
                    vertices=[
                        Vec2R(1, 13),
                        Vec2R(2, 13),
                        Vec2R(5, 13),
                        s.pu.pos + nmos.d.pos,
                    ]
                )
                if self.variant == "terminal_multiple_wires":
                    s.vdd % SchemWire(
                        vertices=[Vec2R(1, 13), Vec2R(1, 10), Vec2R(3, 10)]
                    )
                else:
                    s.vdd % SchemWire(
                        vertices=[Vec2R(2, 13), Vec2R(2, 10), Vec2R(3, 10)]
                    )

            if self.variant == "terminal_connpoint":
                s.vdd % SchemConnPoint(pos=Vec2R(1, 13))

            if self.variant == "stray_conn_point":
                s.vdd % SchemConnPoint(pos=Vec2R(5, 13))
            if self.variant == "tap_short":
                s.vss % SchemTapPoint(pos=Vec2R(5, 13))

            if self.variant == "poly_short":
                s.vdd % SchemWire(
                    vertices=[
                        Vec2R(2, 10),
                        Vec2R(2, 4),
                    ]
                )

            s.a % SchemWire(vertices=[Vec2R(1, 4), Vec2R(2, 4), Vec2R(3, 4)])
            s.y % SchemWire(vertices=[Vec2R(5, 6), Vec2R(5, 7), Vec2R(5, 8)])
            s.y % SchemWire(vertices=[Vec2R(5, 7), Vec2R(9, 7)])

        if self.variant in ("manual_conn_points", "double_connpoint"):
            s.vss % SchemConnPoint(pos=Vec2R(5, 1))
            s.vss % SchemConnPoint(pos=Vec2R(8, 4))
            s.vdd % SchemConnPoint(pos=Vec2R(2, 13))
            s.y % SchemConnPoint(pos=Vec2R(5, 7))
            if self.variant == "double_connpoint":
                s.y % SchemConnPoint(pos=Vec2R(5, 7))

        if self.variant == "unconnected_conn_point":
            s.y % SchemConnPoint(pos=Vec2R(4, 7))

        s.outline = Rect4R(lx=0, ly=1, ux=10, uy=13)
        helpers.schem_check(
            s,
            add_conn_points=self.add_conn_points,
            add_terminal_taps=self.add_terminal_taps,
        )

        return s
