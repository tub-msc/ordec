# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from .. import helpers
from ..core import *
from ..sim2.sim_hierarchy import HighlevelSim

from .generic_mos import Or2, Nmos, Pmos, Ringosc, Inv
from .base import Gnd, NoConn, Res, Vdc, Idc
from . import sky130

class RotateTest(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)
        c = Or2().symbol

        s.R0   = SchemInstance(c.portmap(), pos=Vec2R(1, 1), orientation=Orientation.R0)
        s.R90  = SchemInstance(c.portmap(), pos=Vec2R(12, 1), orientation=Orientation.R90)
        s.R180 = SchemInstance(c.portmap(), pos=Vec2R(18, 6), orientation=Orientation.R180)
        s.R270 = SchemInstance(c.portmap(), pos=Vec2R(19, 6), orientation=Orientation.R270)

        s.MY   = SchemInstance(c.portmap(), pos=Vec2R(6, 7), orientation=Orientation.MY)
        s.MY90 = SchemInstance(c.portmap(), pos=Vec2R(12, 12), orientation=Orientation.MY90)
        s.MX   = SchemInstance(c.portmap(), pos=Vec2R(13, 12), orientation=Orientation.MX)
        s.MX90 = SchemInstance(c.portmap(), pos=Vec2R(19, 7), orientation=Orientation.MX90)
        
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
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vss = Pin(pintype=PinType.In, align=Orientation.South)
        s.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        s.mkpath('d')
        s.mkpath('q')
        for i in range(self.params.bits):
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
        s.mkpath('d')
        s.mkpath('q')
        s.mkpath("I")

        s.vss % SchemPort(pos=Vec2R(1, 0), align=Orientation.East)
        s.vdd % SchemPort(pos=Vec2R(1, 1), align=Orientation.East)
        s.clk % SchemPort(pos=Vec2R(1, 2), align=Orientation.East)
        for i in range(self.params.bits):
            s.d[i] = Net(pin=self.symbol.d[i])
            s.q[i] = Net(pin=self.symbol.q[i])
            s.I[i] = SchemInstance(DFF().symbol.portmap(
                    vss=s.vss,
                    vdd=s.vdd,
                    clk=s.clk,
                    d=s.d[i],
                    q=s.q[i],
                ), pos=Vec2R(2, 3 + 8*i), orientation=Orientation.R0)

            s.d[i] % SchemPort(pos=Vec2R(1, 5+8*i), align=Orientation.East)
            s.d[i] % SchemWire(vertices=[Vec2R(1, 5+8*i), Vec2R(2, 5+8*i)])
            s.q[i] % SchemPort(pos=Vec2R(9, 5+8*i), align=Orientation.West)
            s.q[i] % SchemWire(vertices=[Vec2R(8, 5+8*i), Vec2R(9, 5+8*i)])

        s.outline = Rect4R(lx=0, ly=0, ux=10, uy=2+8*self.params.bits)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)

        return s


class MultibitReg_ArrayOfStructs(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vss = Pin(pintype=PinType.In, align=Orientation.South)
        s.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        s.mkpath('bit')
        for i in range(self.params.bits):
            s.bit.mkpath(i)
            s.bit[i].d = Pin(pintype=PinType.In, align=Orientation.West)
            s.bit[i].q = Pin(pintype=PinType.Out, align=Orientation.East)
        s.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(s)

        return s

class MultibitReg_StructOfArrays(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vss = Pin(pintype=PinType.In, align=Orientation.South)
        s.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        s.mkpath('data')
        s.data.mkpath('d')
        s.data.mkpath('q')
        for i in range(self.params.bits):
            s.data.d[i] = Pin(pintype=PinType.In, align=Orientation.West)
            s.data.q[i] = Pin(pintype=PinType.Out, align=Orientation.East)
        s.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(s)

        return s

class TestNmosInv(Cell):
    """
    For testing schem_check.
    """
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
        if self.params.variant == "incorrect_pin_conn":
            portmap = nmos.portmap(s=s.vss, b=s.a, g=s.a, d=s.y)
        elif self.params.variant == "portmap_missing_key":
            portmap = nmos.portmap(s=s.vss, b=s.vss, d=s.y)

        s.pd = SchemInstance(portmap, pos=Vec2R(3, 2))
        if self.params.variant == "portmap_stray_key":
            s.pd % SchemInstanceConn(here=0, there=0)
        elif self.params.variant == "portmap_bad_value":
            list(s.pd.conns)[0].there = 12345

        s.pu = SchemInstance(nmos.portmap(d=s.vdd, b=s.vss, g=s.vdd, s=s.y), pos=Vec2R(3, 8))
        if self.params.variant=="double_instance":
            s.pu2 = SchemInstance(nmos.portmap(d=s.vdd, b=s.vss, g=s.vdd, s=s.y), pos=Vec2R(3, 8))

        s.vdd % SchemPort(pos=Vec2R(1, 13), align=Orientation.East)
        s.vss % SchemPort(pos=Vec2R(1, 1), align=Orientation.East)
        s.a % SchemPort(pos=Vec2R(1, 4), align=Orientation.East)
        if self.params.variant == 'incorrect_port_conn':
            s.vss % SchemPort(pos=Vec2R(9, 7), align=Orientation.West)
        else:
            s.y % SchemPort(pos=Vec2R(9, 7), align=Orientation.West)
        
        if self.params.variant == "no_wiring":
            s.default_supply = s.vdd
            s.default_ground = s.vss
        else:
            s.vss % SchemWire(vertices=[Vec2R(1, 1), Vec2R(5, 1), s.pd.pos + nmos.s.pos])
            if self.params.variant == 'skip_single_pin':
                s.vss % SchemWire(vertices=[Vec2R(7, 4), Vec2R(8, 4)])
            else:
                s.vss % SchemWire(vertices=[Vec2R(7, 4), Vec2R(8, 4), Vec2R(8, 10), Vec2R(7, 10)])
            if self.params.variant not in ('net_partitioned', 'net_partitioned_tapped'):
                s.vss % SchemWire(vertices=[Vec2R(8, 4), Vec2R(8, 1), Vec2R(5, 1)])

            if self.params.variant == 'net_partitioned_tapped':
                s.vss % SchemTapPoint(pos=Vec2R(8, 4), align=Orientation.South)
                s.vss % SchemTapPoint(pos=Vec2R(5, 1), align=Orientation.East)

            if self.params.variant == 'vdd_bad_wiring':
                s.vdd % SchemWire(vertices=[Vec2R(1, 13), Vec2R(2, 13)])
            elif self.params.variant != 'skip_vdd_wiring':
                s.vdd % SchemWire(vertices=[Vec2R(1, 13), Vec2R(2, 13), Vec2R(5, 13), s.pu.pos + nmos.d.pos])
                if self.params.variant == "terminal_multiple_wires":
                    s.vdd % SchemWire(vertices=[Vec2R(1, 13), Vec2R(1, 10), Vec2R(3, 10)])
                else:
                    s.vdd % SchemWire(vertices=[Vec2R(2, 13), Vec2R(2, 10), Vec2R(3, 10)])

            if self.params.variant == "terminal_connpoint":
                s.vdd % SchemConnPoint(pos=Vec2R(1, 13))

            if self.params.variant == "stray_conn_point":
                s.vdd % SchemConnPoint(pos=Vec2R(5, 13))
            if self.params.variant == "tap_short":
                s.vss % SchemTapPoint(pos=Vec2R(5, 13))

            if self.params.variant == 'poly_short':
                s.vdd % SchemWire(vertices=[Vec2R(2, 10), Vec2R(2, 4),])

            s.a % SchemWire(vertices=[Vec2R(1, 4), Vec2R(2, 4), Vec2R(3, 4)])
            s.y % SchemWire(vertices=[Vec2R(5, 6), Vec2R(5, 7), Vec2R(5, 8)])
            s.y % SchemWire(vertices=[Vec2R(5, 7), Vec2R(9, 7)])
            
        if self.params.variant in ("manual_conn_points", "double_connpoint"):
            s.vss % SchemConnPoint(pos=Vec2R(5, 1))
            s.vss % SchemConnPoint(pos=Vec2R(8, 4))
            s.vdd % SchemConnPoint(pos=Vec2R(2, 13))
            s.y % SchemConnPoint(pos=Vec2R(5, 7))
            if self.params.variant == "double_connpoint":
                s.y % SchemConnPoint(pos=Vec2R(5, 7))

        if self.params.variant == "unconnected_conn_point":
            s.y % SchemConnPoint(pos=Vec2R(4, 7))


        s.outline = Rect4R(lx=0, ly=1, ux=10, uy=13)
        helpers.schem_check(s, add_conn_points=self.params.add_conn_points, add_terminal_taps=self.params.add_terminal_taps)

        return s

class RingoscTb(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.vss = Net()
        s.y = Net()
        
        vdc = Vdc().symbol
        s.i0 = SchemInstance(pos=Vec2R(0, 2), ref=vdc,
            portmap={vdc.m:s.vss, vdc.p:s.vdd})

        ro = Ringosc().symbol
        s.dut = SchemInstance(pos=Vec2R(5, 2), ref=ro,
            portmap={ro.vdd:s.vdd, ro.vss:s.vss, ro.y:s.y})

        nc = NoConn().symbol
        s.i1 = SchemInstance(pos=Vec2R(10, 2), ref=nc,
            portmap={nc.a:s.y})

        g = Gnd().symbol
        s.i2 = SchemInstance(pos=Vec2R(0, -4), ref=g,
            portmap={g.p:s.vss})

        #s.ref = self.symbol

        s.outline = Rect4R(lx=0, ly=-4, ux=15, uy=7)

        s.vss % SchemWire(vertices=[Vec2R(2, 2), Vec2R(2, 1), Vec2R(2, 0)])
        s.vss % SchemWire(vertices=[Vec2R(2, 1), Vec2R(7, 1), Vec2R(7, 2)])
        s.vdd % SchemWire(vertices=[Vec2R(2, 6), Vec2R(2, 7), Vec2R(7, 7), Vec2R(7, 6)])
        s.y % SchemWire(vertices=[Vec2R(9, 4), Vec2R(10, 4)])
        
        helpers.schem_check(s, add_conn_points=True)

        return s

class ResdivFlatTb(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.vss = Net()
        s.a = Net()
        s.b = Net()

        sym_vdc = Vdc(dc=R(1)).symbol
        sym_gnd = Gnd().symbol
        sym_res = Res(r=R(100)).symbol

        s.I0 = SchemInstance(sym_gnd.portmap(p=s.vss), pos=Vec2R(5, 0))
        s.I1 = SchemInstance(sym_vdc.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 6))
        s.I2 = SchemInstance(sym_res.portmap(m=s.vss, p=s.a), pos=Vec2R(5, 6))
        s.I3 = SchemInstance(sym_res.portmap(m=s.a, p=s.b), pos=Vec2R(5, 11))
        s.I4 = SchemInstance(sym_res.portmap(m=s.b, p=s.vdd), pos=Vec2R(5, 16))
        
        s.vss % SchemWire(vertices=[Vec2R(7, 4), Vec2R(7, 5), Vec2R(7, 6)])
        s.vss % SchemWire(vertices=[Vec2R(2, 6), Vec2R(2, 5), Vec2R(7, 5)])
        s.vdd % SchemWire(vertices=[Vec2R(2, 10), Vec2R(2, 21), Vec2R(7, 21), Vec2R(7, 20)])
        s.a % SchemWire(vertices=[Vec2R(7, 10), Vec2R(7, 11)])
        s.b % SchemWire(vertices=[Vec2R(7, 15), Vec2R(7, 16)])
        
        s.outline = Rect4R(lx=0, ly=0, ux=9, uy=21)

        helpers.schem_check(s, add_conn_points=True)

        return s

    @generate
    def sim_dc(self):
        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s)
        sim.op()
        return s


class ResdivHier2(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.t = Pin(pintype=PinType.Inout, align=Orientation.North)
        s.r = Pin(pintype=PinType.Inout, align=Orientation.East)
        s.b = Pin(pintype=PinType.Inout, align=Orientation.South)
        helpers.symbol_place_pins(s, vpadding=2, hpadding=2)

        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.t = Net(pin=self.symbol.t)
        s.r = Net(pin=self.symbol.r)
        s.b = Net(pin=self.symbol.b)
        s.m = Net()

        s.t % SchemPort(pos=Vec2R(2, 12), align=Orientation.South)
        s.r % SchemPort(pos=Vec2R(10, 6), align=Orientation.West)
        s.b % SchemPort(pos=Vec2R(2, 0), align=Orientation.North)

        sym_res = Res(r=self.params.r).symbol

        s.I0 = SchemInstance(sym_res.portmap(m=s.b, p=s.m), pos=Vec2R(0, 1))
        s.I1 = SchemInstance(sym_res.portmap(m=s.m, p=s.t), pos=Vec2R(0, 7))
        s.I2 = SchemInstance(sym_res.portmap(m=s.r, p=s.m), pos=Vec2R(9, 4), orientation=Orientation.R90)

        s.outline = Rect4R(lx=0, ly=0, ux=10, uy=12)

        s.t % SchemWire(vertices=[Vec2R(2, 12), Vec2R(2, 11)])
        s.b % SchemWire(vertices=[Vec2R(2, 0), Vec2R(2, 1)])
        s.m % SchemWire(vertices=[Vec2R(2, 5), Vec2R(2, 6), Vec2R(2, 7)])
        s.m % SchemWire(vertices=[Vec2R(2, 6), Vec2R(5, 6)])
        s.r % SchemWire(vertices=[Vec2R(9, 6), Vec2R(10, 6)])

        helpers.schem_check(s, add_conn_points=True)
        return s

class ResdivHier1(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.t = Pin(pintype=PinType.Inout, align=Orientation.North)
        s.r = Pin(pintype=PinType.Inout, align=Orientation.East)
        s.b = Pin(pintype=PinType.Inout, align=Orientation.South)
        helpers.symbol_place_pins(s, vpadding=2, hpadding=2)

        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.t = Net(pin=self.symbol.t)
        s.r = Net(pin=self.symbol.r)
        s.b = Net(pin=self.symbol.b)
        s.tr = Net()
        s.br = Net()
        s.m = Net()

        s.t % SchemPort(pos=Vec2R(7, 11), align=Orientation.South)
        s.r % SchemPort(pos=Vec2R(15, 5), align=Orientation.West)
        s.b % SchemPort(pos=Vec2R(7, -1), align=Orientation.North)

        sym_1 = ResdivHier2(r=R(100)).symbol
        sym_2 = ResdivHier2(r=R(200)).symbol
    
        #s % SchemInstance(pos=Vec2R(5, 0), ref=sym_1, portmap={sym_1.t: s.m, sym_1.b:s.gnd, sym_1.r:s.br})
        s.I0 = SchemInstance(sym_1.portmap(t=s.m, b=s.b, r=s.br), pos=Vec2R(5, 0))
        s.I1 = SchemInstance(sym_2.portmap(t=s.t, b=s.m, r=s.tr), pos=Vec2R(5, 6))
        s.I2 = SchemInstance(sym_1.portmap(t=s.tr, b=s.br, r=s.r), pos=Vec2R(10, 3))
        
        s.outline = Rect4R(lx=5, ly=-1, ux=15, uy=12)

        s.b % SchemWire(vertices=[Vec2R(7, -1), Vec2R(7, 0)])
        s.m % SchemWire(vertices=[Vec2R(7, 4), Vec2R(7, 6)])
        s.t % SchemWire(vertices=[Vec2R(7, 10), Vec2R(7, 11)])
        s.tr % SchemWire(vertices=[Vec2R(9, 8), Vec2R(12, 8), Vec2R(12, 7)])
        s.br % SchemWire(vertices=[Vec2R(9, 2), Vec2R(12, 2), Vec2R(12, 3)])
        s.r % SchemWire(vertices=[Vec2R(14, 5), Vec2R(15, 5)])

        helpers.schem_check(s, add_conn_points=True)
        return s

class ResdivHierTb(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.t = Net()
        s.r = Net()
        s.gnd = Net()
    
        s.I0 = SchemInstance(ResdivHier1().symbol.portmap(t=s.t, b=s.gnd, r=s.r), pos=Vec2R(5, 0))
        s.I1 = SchemInstance(NoConn().symbol.portmap(a=s.r), pos=Vec2R(10, 0))
        s.I2 = SchemInstance(Vdc(dc=R(1)).symbol.portmap(m=s.gnd, p=s.t), pos=Vec2R(0, 0))
        s.I3 = SchemInstance(Gnd().symbol.portmap(p=s.gnd), pos=Vec2R(0, -6))

        s.outline = Rect4R(lx=0, ly=-6, ux=14, uy=5)

        s.gnd % SchemWire(vertices=[Vec2R(2, -2), Vec2R(2, -1), Vec2R(2, 0)])
        s.gnd % SchemWire(vertices=[Vec2R(2, -1), Vec2R(7, -1), Vec2R(7, 0)])
        s.t % SchemWire(vertices=[Vec2R(7, 4), Vec2R(7, 5), Vec2R(2, 5), Vec2R(2, 4)])
        s.r % SchemWire(vertices=[Vec2R(9, 2), Vec2R(10, 2)])

        helpers.schem_check(s, add_conn_points=True)
        return s

    @generate
    def sim_hierarchy(self):
        s = SimHierarchy(cell=self)
        # Build SimHierarchy, but runs no simulations.
        HighlevelSim(self.schematic, s)
        return s

    @generate
    def sim_dc(self):
        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s)
        sim.op()
        return s

class NmosSourceFollowerTb(Cell):
    """Nmos (generic_mos) source follower with optional parameter vin."""
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.i = Net()
        s.o = Net()
        s.vss = Net()
        try:
            vin = self.params.vin
        except AttributeError:
            vin = R(2)

        s.I0 = SchemInstance(Nmos(w=R('5u'), l=R('1u')).symbol.portmap(d=s.vdd, s=s.o, g=s.i, b=s.vss), pos=Vec2R(11, 12))
        
        s.I1 = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(11, 0))
        s.I2 = SchemInstance(Vdc(dc=R('5')).symbol.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 6))
        s.I3 = SchemInstance(Vdc(dc=vin).symbol.portmap(m=s.vss, p=s.i), pos=Vec2R(5, 6))
        s.I4 = SchemInstance(Idc(dc=R('5u')).symbol.portmap(m=s.vss, p=s.o), pos=Vec2R(11, 6))
        
        s.outline = Rect4R(lx=0, ly=0, ux=16, uy=22)
        
        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)

        return s

    @generate
    def sim_dc(self):
        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s)
        sim.op()
        return s

class InvTb(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)
        s.vdd = Net()
        s.i = Net()
        s.o = Net()
        s.vss = Net()
        try:
            vin = self.params.vin
        except AttributeError:
            vin = R(0)

        s.I0 = SchemInstance(Inv().symbol.portmap(vdd = s.vdd, vss=s.vss, a=s.i, y=s.o), pos=Vec2R(11, 9))
        s.I1 = SchemInstance(NoConn().symbol.portmap(a=s.o), pos=Vec2R(16, 9))
        s.I2 = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(11, 0))
        s.I3 = SchemInstance(Vdc(dc=R('5')).symbol.portmap(m=s.vss, p = s.vdd), pos=Vec2R(0, 6))
        s.I4 = SchemInstance(Vdc(dc=vin).symbol.portmap(m=s.vss, p = s.i), pos=Vec2R(5, 6))
        
        s.outline = Rect4R(lx=0, ly=0, ux=20, uy=14)
        
        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)

        return s

    @generate
    def sim_dc(self):
        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s)
        sim.op()
        return s

class InvSkyTb(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.i = Net()
        s.o = Net()
        s.vss = Net()
        try:
            vin = self.params.vin
        except AttributeError:
            vin = R(0)

        sym_inv = sky130.Inv().symbol
        sym_nc = NoConn().symbol
        sym_gnd = Gnd().symbol
        sym_vdc_vdd = Vdc(dc=R('5')).symbol
        sym_vdc_in = Vdc(dc=vin).symbol

        s.i_inv = SchemInstance(sym_inv.portmap(vdd=s.vdd, vss=s.vss, a=s.i, y=s.o), pos=Vec2R(11, 9))
        s.i_nc = SchemInstance(sym_nc.portmap(a=s.o), pos=Vec2R(16, 9))

        s.i_gnd = SchemInstance(sym_gnd.portmap(p=s.vss), pos=Vec2R(11, 0))
        s.i_vdd = SchemInstance(sym_vdc_vdd.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 6))
        s.i_in = SchemInstance(sym_vdc_in.portmap(m=s.vss, p=s.i), pos=Vec2R(5, 6))

        s.outline = Rect4R(lx=0, ly=0, ux=20, uy=14)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)

        return s

    @generate
    def sim_dc(self):
        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s)
        sim.op()
        return s
