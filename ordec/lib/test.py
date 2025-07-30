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
        node = Schematic(cell=self)
        c = Or2().symbol

        node.R0   = SchemInstance(c.portmap(), pos=Vec2R(1, 1), orientation=Orientation.R0)
        node.R90  = SchemInstance(c.portmap(), pos=Vec2R(12, 1), orientation=Orientation.R90)
        node.R180 = SchemInstance(c.portmap(), pos=Vec2R(18, 6), orientation=Orientation.R180)
        node.R270 = SchemInstance(c.portmap(), pos=Vec2R(19, 6), orientation=Orientation.R270)

        node.MY   = SchemInstance(c.portmap(), pos=Vec2R(6, 7), orientation=Orientation.MY)
        node.MY90 = SchemInstance(c.portmap(), pos=Vec2R(12, 12), orientation=Orientation.MY90)
        node.MX   = SchemInstance(c.portmap(), pos=Vec2R(13, 12), orientation=Orientation.MX)
        node.MX90 = SchemInstance(c.portmap(), pos=Vec2R(19, 7), orientation=Orientation.MX90)
        
        node.outline = Rect4R(lx=0, ly=0, ux=25, uy=13)
        return node

class PortAlignTest(Cell):
    @generate
    def symbol(self):
        node = Symbol(cell=self)

        node.north = Pin(pintype=PinType.In, align=Orientation.North)
        node.south = Pin(pintype=PinType.In, align=Orientation.South)
        node.west = Pin(pintype=PinType.In, align=Orientation.West)
        node.east = Pin(pintype=PinType.In, align=Orientation.East)
        helpers.symbol_place_pins(node)

        return node

    @generate
    def schematic(self):
        node = Schematic(cell=self, symbol=self.symbol)

        node.n1 = Net(pin=self.symbol.north)
        node.n2 = Net(pin=self.symbol.south)
        node.n3 = Net(pin=self.symbol.east)
        node.n4 = Net(pin=self.symbol.west)

        node.n1 % SchemPort(pos=Vec2R(4, 2), align=Orientation.North)
        node.n2 % SchemPort(pos=Vec2R(4, 6), align=Orientation.South)
        node.n3 % SchemPort(pos=Vec2R(2, 4), align=Orientation.East)
        node.n4 % SchemPort(pos=Vec2R(6, 4), align=Orientation.West)

        node.outline = Rect4R(lx=0, ly=0, ux=8, uy=8)
        return node

class TapAlignTest(Cell):
    @generate
    def schematic(self):
        node = Schematic(cell=self)

        node.north = Net()
        node.south = Net()
        node.east = Net()
        node.west = Net()

        node.north % SchemTapPoint(pos=Vec2R(4, 6), align=Orientation.North)
        node.south % SchemTapPoint(pos=Vec2R(4, 2), align=Orientation.South)
        node.west % SchemTapPoint(pos=Vec2R(2, 4), align=Orientation.West)
        node.east % SchemTapPoint(pos=Vec2R(6, 4), align=Orientation.East)

        node.outline = Rect4R(lx=0, ly=0, ux=8, uy=8)
        return node


class DFF(Cell):
    @generate
    def symbol(self):
        node = Symbol(cell=self)

        node.vss = Pin(pintype=PinType.In, align=Orientation.South)
        node.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        node.d = Pin(pintype=PinType.In, align=Orientation.West)
        node.q = Pin(pintype=PinType.Out, align=Orientation.East)
        node.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(node, vpadding=2, hpadding=3)

        return node

class MultibitReg_Arrays(Cell):
    @generate
    def symbol(self):
        node = Symbol(cell=self)

        node.vss = Pin(pintype=PinType.In, align=Orientation.South)
        node.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        node.mkpath('d')
        node.mkpath('q')
        for i in range(self.params.bits):
            node.d[i] = Pin(pintype=PinType.In, align=Orientation.West)
            node.q[i] = Pin(pintype=PinType.Out, align=Orientation.East)
        node.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(node)

        return node

    @generate
    def schematic(self):
        node = Schematic(cell=self, symbol=self.symbol)

        node.vss = Net(pin=self.symbol.vss)
        node.vdd = Net(pin=self.symbol.vdd)
        node.clk = Net(pin=self.symbol.clk)
        node.mkpath('d')
        node.mkpath('q')
        node.mkpath("I")

        node.vss % SchemPort(pos=Vec2R(1, 0), align=Orientation.East)
        node.vdd % SchemPort(pos=Vec2R(1, 1), align=Orientation.East)
        node.clk % SchemPort(pos=Vec2R(1, 2), align=Orientation.East)
        for i in range(self.params.bits):
            node.d[i] = Net(pin=self.symbol.d[i])
            node.q[i] = Net(pin=self.symbol.q[i])
            node.I[i] = SchemInstance(DFF().symbol.portmap(
                    vss=node.vss,
                    vdd=node.vdd,
                    clk=node.clk,
                    d=node.d[i],
                    q=node.q[i],
                ), pos=Vec2R(2, 3 + 8*i), orientation=Orientation.R0)

            node.d[i] % SchemPort(pos=Vec2R(1, 5+8*i), align=Orientation.East)
            node.d[i] % SchemWire(vertices=[Vec2R(1, 5+8*i), Vec2R(2, 5+8*i)])
            node.q[i] % SchemPort(pos=Vec2R(9, 5+8*i), align=Orientation.West)
            node.q[i] % SchemWire(vertices=[Vec2R(8, 5+8*i), Vec2R(9, 5+8*i)])

        node.outline = Rect4R(lx=0, ly=0, ux=10, uy=2+8*self.params.bits)

        helpers.schem_check(node, add_conn_points=True, add_terminal_taps=True)

        return node


class MultibitReg_ArrayOfStructs(Cell):
    @generate
    def symbol(self):
        node = Symbol(cell=self)

        node.vss = Pin(pintype=PinType.In, align=Orientation.South)
        node.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        node.mkpath('bit')
        for i in range(self.params.bits):
            node.bit.mkpath(i)
            node.bit[i].d = Pin(pintype=PinType.In, align=Orientation.West)
            node.bit[i].q = Pin(pintype=PinType.Out, align=Orientation.East)
        node.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(node)

        return node

class MultibitReg_StructOfArrays(Cell):
    @generate
    def symbol(self):
        node = Symbol(cell=self)

        node.vss = Pin(pintype=PinType.In, align=Orientation.South)
        node.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        node.mkpath('data')
        node.data.mkpath('d')
        node.data.mkpath('q')
        for i in range(self.params.bits):
            node.data.d[i] = Pin(pintype=PinType.In, align=Orientation.West)
            node.data.q[i] = Pin(pintype=PinType.Out, align=Orientation.East)
        node.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(node)

        return node

class TestNmosInv(Cell):
    """
    For testing schem_check.
    """
    @generate
    def symbol(self):
        node = Symbol(cell=self)

        node.vdd = Pin(pintype=PinType.Inout, align=Orientation.North)
        node.vss = Pin(pintype=PinType.Inout, align=Orientation.South)
        node.a = Pin(pintype=PinType.In, align=Orientation.West)
        node.y = Pin(pintype=PinType.Out, align=Orientation.East)
        helpers.symbol_place_pins(node)

        return node
        
    @generate
    def schematic(self):
        node = Schematic(cell=self, symbol=self.symbol)

        node.a = Net(pin=self.symbol.a)
        node.y = Net(pin=self.symbol.y)
        node.vdd = Net(pin=self.symbol.vdd)
        node.vss = Net(pin=self.symbol.vss)

        nmos = Nmos(w=R("500n"), l=R("250n")).symbol

        portmap = nmos.portmap(s=node.vss, b=node.vss, g=node.a, d=node.y)
        if self.params.variant == "incorrect_pin_conn":
            portmap = nmos.portmap(s=node.vss, b=node.a, g=node.a, d=node.y)
        elif self.params.variant == "portmap_missing_key":
            portmap = nmos.portmap(s=node.vss, b=node.vss, d=node.y)

        node.pd = SchemInstance(portmap, pos=Vec2R(3, 2))
        if self.params.variant == "portmap_stray_key":
            node.pd % SchemInstanceConn(here=0, there=0)
        elif self.params.variant == "portmap_bad_value":
            list(node.pd.conns)[0].there = 12345

        node.pu = SchemInstance(nmos.portmap(d=node.vdd, b=node.vss, g=node.vdd, s=node.y), pos=Vec2R(3, 8))
        if self.params.variant=="double_instance":
            node.pu2 = SchemInstance(nmos.portmap(d=node.vdd, b=node.vss, g=node.vdd, s=node.y), pos=Vec2R(3, 8))

        node.vdd % SchemPort(pos=Vec2R(1, 13), align=Orientation.East)
        node.vss % SchemPort(pos=Vec2R(1, 1), align=Orientation.East)
        node.a % SchemPort(pos=Vec2R(1, 4), align=Orientation.East)
        if self.params.variant == 'incorrect_port_conn':
            node.vss % SchemPort(pos=Vec2R(9, 7), align=Orientation.West)
        else:
            node.y % SchemPort(pos=Vec2R(9, 7), align=Orientation.West)
        
        if self.params.variant == "no_wiring":
            node.default_supply = node.vdd
            node.default_ground = node.vss
        else:
            node.vss % SchemWire(vertices=[Vec2R(1, 1), Vec2R(5, 1), node.pd.pos + nmos.s.pos])
            if self.params.variant == 'skip_single_pin':
                node.vss % SchemWire(vertices=[Vec2R(7, 4), Vec2R(8, 4)])
            else:
                node.vss % SchemWire(vertices=[Vec2R(7, 4), Vec2R(8, 4), Vec2R(8, 10), Vec2R(7, 10)])
            if self.params.variant not in ('net_partitioned', 'net_partitioned_tapped'):
                node.vss % SchemWire(vertices=[Vec2R(8, 4), Vec2R(8, 1), Vec2R(5, 1)])

            if self.params.variant == 'net_partitioned_tapped':
                node.vss % SchemTapPoint(pos=Vec2R(8, 4), align=Orientation.South)
                node.vss % SchemTapPoint(pos=Vec2R(5, 1), align=Orientation.East)

            if self.params.variant == 'vdd_bad_wiring':
                node.vdd % SchemWire(vertices=[Vec2R(1, 13), Vec2R(2, 13)])
            elif self.params.variant != 'skip_vdd_wiring':
                node.vdd % SchemWire(vertices=[Vec2R(1, 13), Vec2R(2, 13), Vec2R(5, 13), node.pu.pos + nmos.d.pos])
                if self.params.variant == "terminal_multiple_wires":
                    node.vdd % SchemWire(vertices=[Vec2R(1, 13), Vec2R(1, 10), Vec2R(3, 10)])
                else:
                    node.vdd % SchemWire(vertices=[Vec2R(2, 13), Vec2R(2, 10), Vec2R(3, 10)])

            if self.params.variant == "terminal_connpoint":
                node.vdd % SchemConnPoint(pos=Vec2R(1, 13))

            if self.params.variant == "stray_conn_point":
                node.vdd % SchemConnPoint(pos=Vec2R(5, 13))
            if self.params.variant == "tap_short":
                node.vss % SchemTapPoint(pos=Vec2R(5, 13))

            if self.params.variant == 'poly_short':
                node.vdd % SchemWire(vertices=[Vec2R(2, 10), Vec2R(2, 4),])

            node.a % SchemWire(vertices=[Vec2R(1, 4), Vec2R(2, 4), Vec2R(3, 4)])
            node.y % SchemWire(vertices=[Vec2R(5, 6), Vec2R(5, 7), Vec2R(5, 8)])
            node.y % SchemWire(vertices=[Vec2R(5, 7), Vec2R(9, 7)])
            
        if self.params.variant in ("manual_conn_points", "double_connpoint"):
            node.vss % SchemConnPoint(pos=Vec2R(5, 1))
            node.vss % SchemConnPoint(pos=Vec2R(8, 4))
            node.vdd % SchemConnPoint(pos=Vec2R(2, 13))
            node.y % SchemConnPoint(pos=Vec2R(5, 7))
            if self.params.variant == "double_connpoint":
                node.y % SchemConnPoint(pos=Vec2R(5, 7))

        if self.params.variant == "unconnected_conn_point":
            node.y % SchemConnPoint(pos=Vec2R(4, 7))


        node.outline = Rect4R(lx=0, ly=1, ux=10, uy=13)
        helpers.schem_check(node, add_conn_points=self.params.add_conn_points, add_terminal_taps=self.params.add_terminal_taps)

        return node

class RingoscTb(Cell):
    @generate
    def schematic(self):
        node = Schematic(cell=self)

        node.vdd = Net()
        node.vss = Net()
        node.y = Net()
        
        vdc = Vdc().symbol
        node.i0 = SchemInstance(pos=Vec2R(0, 2), ref=vdc,
            portmap={vdc.m:node.vss, vdc.p:node.vdd})

        ro = Ringosc().symbol
        node.dut = SchemInstance(pos=Vec2R(5, 2), ref=ro,
            portmap={ro.vdd:node.vdd, ro.vss:node.vss, ro.y:node.y})

        nc = NoConn().symbol
        node.i1 = SchemInstance(pos=Vec2R(10, 2), ref=nc,
            portmap={nc.a:node.y})

        g = Gnd().symbol
        node.i2 = SchemInstance(pos=Vec2R(0, -4), ref=g,
            portmap={g.p:node.vss})

        #node.ref = self.symbol

        node.outline = Rect4R(lx=0, ly=-4, ux=15, uy=7)

        node.vss % SchemWire(vertices=[Vec2R(2, 2), Vec2R(2, 1), Vec2R(2, 0)])
        node.vss % SchemWire(vertices=[Vec2R(2, 1), Vec2R(7, 1), Vec2R(7, 2)])
        node.vdd % SchemWire(vertices=[Vec2R(2, 6), Vec2R(2, 7), Vec2R(7, 7), Vec2R(7, 6)])
        node.y % SchemWire(vertices=[Vec2R(9, 4), Vec2R(10, 4)])
        
        helpers.schem_check(node, add_conn_points=True)

        return node

class ResdivFlatTb(Cell):
    @generate
    def schematic(self):
        node = Schematic(cell=self)

        node.vdd = Net()
        node.vss = Net()
        node.a = Net()
        node.b = Net()

        s_vdc = Vdc(dc=R(1)).symbol
        s_gnd = Gnd().symbol
        s_res = Res(r=R(100)).symbol

        node.I0 = SchemInstance(s_gnd.portmap(p=node.vss), pos=Vec2R(5, 0))
        node.I1 = SchemInstance(s_vdc.portmap(m=node.vss, p=node.vdd), pos=Vec2R(0, 6))
        node.I2 = SchemInstance(s_res.portmap(m=node.vss, p=node.a), pos=Vec2R(5, 6))
        node.I3 = SchemInstance(s_res.portmap(m=node.a, p=node.b), pos=Vec2R(5, 11))
        node.I4 = SchemInstance(s_res.portmap(m=node.b, p=node.vdd), pos=Vec2R(5, 16))
        
        node.vss % SchemWire(vertices=[Vec2R(7, 4), Vec2R(7, 5), Vec2R(7, 6)])
        node.vss % SchemWire(vertices=[Vec2R(2, 6), Vec2R(2, 5), Vec2R(7, 5)])
        node.vdd % SchemWire(vertices=[Vec2R(2, 10), Vec2R(2, 21), Vec2R(7, 21), Vec2R(7, 20)])
        node.a % SchemWire(vertices=[Vec2R(7, 10), Vec2R(7, 11)])
        node.b % SchemWire(vertices=[Vec2R(7, 15), Vec2R(7, 16)])
        
        node.outline = Rect4R(lx=0, ly=0, ux=9, uy=21)

        helpers.schem_check(node, add_conn_points=True)

        return node

    @generate
    def sim_dc(self):
        node = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, node)
        sim.op()
        return node


class ResdivHier2(Cell):
    @generate
    def symbol(self):
        node = Symbol(cell=self)

        node.t = Pin(pintype=PinType.Inout, align=Orientation.North)
        node.r = Pin(pintype=PinType.Inout, align=Orientation.East)
        node.b = Pin(pintype=PinType.Inout, align=Orientation.South)
        helpers.symbol_place_pins(node, vpadding=2, hpadding=2)

        return node

    @generate
    def schematic(self):
        node = Schematic(cell=self, symbol=self.symbol)

        node.t = Net(pin=self.symbol.t)
        node.r = Net(pin=self.symbol.r)
        node.b = Net(pin=self.symbol.b)
        node.m = Net()

        node.t % SchemPort(pos=Vec2R(2, 12), align=Orientation.South)
        node.r % SchemPort(pos=Vec2R(10, 6), align=Orientation.West)
        node.b % SchemPort(pos=Vec2R(2, 0), align=Orientation.North)

        s_res = Res(r=self.params.r).symbol

        node.I0 = SchemInstance(s_res.portmap(m=node.b, p=node.m), pos=Vec2R(0, 1))
        node.I1 = SchemInstance(s_res.portmap(m=node.m, p=node.t), pos=Vec2R(0, 7))
        node.I2 = SchemInstance(s_res.portmap(m=node.r, p=node.m), pos=Vec2R(9, 4), orientation=Orientation.R90)

        node.outline = Rect4R(lx=0, ly=0, ux=10, uy=12)

        node.t % SchemWire(vertices=[Vec2R(2, 12), Vec2R(2, 11)])
        node.b % SchemWire(vertices=[Vec2R(2, 0), Vec2R(2, 1)])
        node.m % SchemWire(vertices=[Vec2R(2, 5), Vec2R(2, 6), Vec2R(2, 7)])
        node.m % SchemWire(vertices=[Vec2R(2, 6), Vec2R(5, 6)])
        node.r % SchemWire(vertices=[Vec2R(9, 6), Vec2R(10, 6)])

        helpers.schem_check(node, add_conn_points=True)

        return node

class ResdivHier1(Cell):
    @generate
    def symbol(self):
        node = Symbol(cell=self)

        node.t = Pin(pintype=PinType.Inout, align=Orientation.North)
        node.r = Pin(pintype=PinType.Inout, align=Orientation.East)
        node.b = Pin(pintype=PinType.Inout, align=Orientation.South)
        helpers.symbol_place_pins(node, vpadding=2, hpadding=2)

        return node

    @generate
    def schematic(self):
        node = Schematic(cell=self, symbol=self.symbol)

        node.t = Net(pin=self.symbol.t)
        node.r = Net(pin=self.symbol.r)
        node.b = Net(pin=self.symbol.b)
        node.tr = Net()
        node.br = Net()
        node.m = Net()

        node.t % SchemPort(pos=Vec2R(7, 11), align=Orientation.South)
        node.r % SchemPort(pos=Vec2R(15, 5), align=Orientation.West)
        node.b % SchemPort(pos=Vec2R(7, -1), align=Orientation.North)

        s_1 = ResdivHier2(r=R(100)).symbol
        s_2 = ResdivHier2(r=R(200)).symbol
    
        #node % SchemInstance(pos=Vec2R(5, 0), ref=s_1, portmap={s_1.t: node.m, s_1.b:node.gnd, s_1.r:node.br})
        node.I0 = SchemInstance(s_1.portmap(t=node.m, b=node.b, r=node.br), pos=Vec2R(5, 0))
        node.I1 = SchemInstance(s_2.portmap(t=node.t, b=node.m, r=node.tr), pos=Vec2R(5, 6))
        node.I2 = SchemInstance(s_1.portmap(t=node.tr, b=node.br, r=node.r), pos=Vec2R(10, 3))
        
        node.outline = Rect4R(lx=5, ly=-1, ux=15, uy=12)

        node.b % SchemWire(vertices=[Vec2R(7, -1), Vec2R(7, 0)])
        node.m % SchemWire(vertices=[Vec2R(7, 4), Vec2R(7, 6)])
        node.t % SchemWire(vertices=[Vec2R(7, 10), Vec2R(7, 11)])
        node.tr % SchemWire(vertices=[Vec2R(9, 8), Vec2R(12, 8), Vec2R(12, 7)])
        node.br % SchemWire(vertices=[Vec2R(9, 2), Vec2R(12, 2), Vec2R(12, 3)])
        node.r % SchemWire(vertices=[Vec2R(14, 5), Vec2R(15, 5)])

        helpers.schem_check(node, add_conn_points=True)

        return node

class ResdivHierTb(Cell):
    @generate
    def schematic(self):
        node = Schematic(cell=self)

        node.t = Net()
        node.r = Net()
        node.gnd = Net()
    
        node.I0 = SchemInstance(ResdivHier1().symbol.portmap(t=node.t, b=node.gnd, r=node.r), pos=Vec2R(5, 0))
        node.I1 = SchemInstance(NoConn().symbol.portmap(a=node.r), pos=Vec2R(10, 0))
        node.I2 = SchemInstance(Vdc(dc=R(1)).symbol.portmap(m=node.gnd, p=node.t), pos=Vec2R(0, 0))
        node.I3 = SchemInstance(Gnd().symbol.portmap(p=node.gnd), pos=Vec2R(0, -6))

        node.outline = Rect4R(lx=0, ly=-6, ux=14, uy=5)

        node.gnd % SchemWire(vertices=[Vec2R(2, -2), Vec2R(2, -1), Vec2R(2, 0)])
        node.gnd % SchemWire(vertices=[Vec2R(2, -1), Vec2R(7, -1), Vec2R(7, 0)])
        node.t % SchemWire(vertices=[Vec2R(7, 4), Vec2R(7, 5), Vec2R(2, 5), Vec2R(2, 4)])
        node.r % SchemWire(vertices=[Vec2R(9, 2), Vec2R(10, 2)])

        helpers.schem_check(node, add_conn_points=True)

        return node

    @generate
    def sim_hierarchy(self):
        node = SimHierarchy(cell=self)
        # Build SimHierarchy, but runs no simulations.
        HighlevelSim(self.schematic, node)
        return node

    @generate
    def sim_dc(self):
        node = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, node)
        sim.op()
        return node

class NmosSourceFollowerTb(Cell):
    """Nmos (generic_mos) source follower with optional parameter vin."""
    @generate
    def schematic(self):
        node = Schematic(cell=self)

        node.vdd = Net()
        node.i = Net()
        node.o = Net()
        node.vss = Net()
        try:
            vin = self.params.vin
        except AttributeError:
            vin = R(2)

        node.I0 = SchemInstance(Nmos(w=R('5u'), l=R('1u')).symbol.portmap(d=node.vdd, s=node.o, g=node.i, b=node.vss), pos=Vec2R(11, 12))
        
        node.I1 = SchemInstance(Gnd().symbol.portmap(p=node.vss), pos=Vec2R(11, 0))
        node.I2 = SchemInstance(Vdc(dc=R('5')).symbol.portmap(m=node.vss, p=node.vdd), pos=Vec2R(0, 6))
        node.I3 = SchemInstance(Vdc(dc=vin).symbol.portmap(m=node.vss, p=node.i), pos=Vec2R(5, 6))
        node.I4 = SchemInstance(Idc(dc=R('5u')).symbol.portmap(m=node.vss, p=node.o), pos=Vec2R(11, 6))
        
        node.outline = Rect4R(lx=0, ly=0, ux=16, uy=22)
        
        helpers.schem_check(node, add_conn_points=True, add_terminal_taps=True)

        return node

    @generate
    def sim_dc(self):
        node = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, node)
        sim.op()
        return node

class InvTb(Cell):
    @generate
    def schematic(self):
        node = Schematic(cell=self)
        node.vdd = Net()
        node.i = Net()
        node.o = Net()
        node.vss = Net()
        try:
            vin = self.params.vin
        except AttributeError:
            vin = R(0)

        node.I0 = SchemInstance(Inv().symbol.portmap(vdd = node.vdd, vss=node.vss, a=node.i, y=node.o), pos=Vec2R(11, 9))
        node.I1 = SchemInstance(NoConn().symbol.portmap(a=node.o), pos=Vec2R(16, 9))
        node.I2 = SchemInstance(Gnd().symbol.portmap(p=node.vss), pos=Vec2R(11, 0))
        node.I3 = SchemInstance(Vdc(dc=R('5')).symbol.portmap(m=node.vss, p = node.vdd), pos=Vec2R(0, 6))
        node.I4 = SchemInstance(Vdc(dc=vin).symbol.portmap(m=node.vss, p = node.i), pos=Vec2R(5, 6))
        
        node.outline = Rect4R(lx=0, ly=0, ux=20, uy=14)
        
        helpers.schem_check(node, add_conn_points=True, add_terminal_taps=True)

        return node

    @generate
    def sim_dc(self):
        node = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, node)
        sim.op()
        return node

class InvSkyTb(Cell):
    @generate
    def schematic(self):
        node = Schematic(cell=self)

        node.vdd = Net()
        node.i = Net()
        node.o = Net()
        node.vss = Net()
        try:
            vin = self.params.vin
        except AttributeError:
            vin = R(0)

        s_inv = sky130.Inv().symbol
        s_nc = NoConn().symbol
        s_gnd = Gnd().symbol
        s_vdc_vdd = Vdc(dc=R('5')).symbol
        s_vdc_in = Vdc(dc=vin).symbol

        node.i_inv = SchemInstance(s_inv.portmap(vdd=node.vdd, vss=node.vss, a=node.i, y=node.o), pos=Vec2R(11, 9))
        node.i_nc = SchemInstance(s_nc.portmap(a=node.o), pos=Vec2R(16, 9))

        node.i_gnd = SchemInstance(s_gnd.portmap(p=node.vss), pos=Vec2R(11, 0))
        node.i_vdd = SchemInstance(s_vdc_vdd.portmap(m=node.vss, p=node.vdd), pos=Vec2R(0, 6))
        node.i_in = SchemInstance(s_vdc_in.portmap(m=node.vss, p=node.i), pos=Vec2R(5, 6))

        node.outline = Rect4R(lx=0, ly=0, ux=20, uy=14)

        helpers.schem_check(node, add_conn_points=True, add_terminal_taps=True)

        return node

    @generate
    def sim_dc(self):
        node = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, node)
        sim.op()
        return node
