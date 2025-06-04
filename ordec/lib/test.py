# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from .. import Cell, Vec2R, Rect4R, Pin, Symbol, Schematic, PinType, Rational as R, SchemPoly, SchemArc, SchemRect, SchemInstance, SchemPort, Net, Orientation, SchemConnPoint, SchemTapPoint, PathArray, PathStruct, generate, SimHierarchy, helpers
from ..helpers import qinst
from ..sim2.sim_hierarchy import HighlevelSim

from .generic_mos import Or2, Nmos, Pmos, Ringosc
from .base import Gnd, NoConn, Res, Vdc

class RotateTest(Cell):
    @generate(Schematic)
    def schematic(self, node):
        c = Or2().symbol

        node.R0 = SchemInstance(pos=Vec2R(x=1, y=1), ref=c, portmap={}, orientation=Orientation.R0)
        node.R90 = SchemInstance(pos=Vec2R(x=12, y=1), ref=c, portmap={}, orientation=Orientation.R90)
        node.R180 = SchemInstance(pos=Vec2R(x=18, y=6), ref=c, portmap={}, orientation=Orientation.R180)
        node.R270 = SchemInstance(pos=Vec2R(x=19, y=6), ref=c, portmap={}, orientation=Orientation.R270)

        node.MY = SchemInstance(pos=Vec2R(x=6, y=7), ref=c, portmap={}, orientation=Orientation.MY)
        node.MY90 = SchemInstance(pos=Vec2R(x=12, y=12), ref=c, portmap={}, orientation=Orientation.MY90)
        node.MX = SchemInstance(pos=Vec2R(x=13, y=12), ref=c, portmap={}, orientation=Orientation.MX)
        node.MX90 = SchemInstance(pos=Vec2R(x=19, y=7), ref=c, portmap={}, orientation=Orientation.MX90)
        
        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=25, uy=13))

class PortAlignTest(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.north = Pin(pintype=PinType.In, align=Orientation.North)
        node.south = Pin(pintype=PinType.In, align=Orientation.South)
        node.west = Pin(pintype=PinType.In, align=Orientation.West)
        node.east = Pin(pintype=PinType.In, align=Orientation.East)
        helpers.symbol_place_pins(node)

    @generate(Schematic)
    def schematic(self, node):
        node.n1 = Net()
        node.n2 = Net()
        node.n3 = Net()
        node.n4 = Net()

        node.ref = self.symbol
        node.port_north = SchemPort(pos=Vec2R(x=4, y=2), align=Orientation.North, ref=self.symbol.north, net=node.n1)
        node.port_south = SchemPort(pos=Vec2R(x=4, y=6), align=Orientation.South, ref=self.symbol.south, net=node.n2)
        node.port_west = SchemPort(pos=Vec2R(x=6, y=4), align=Orientation.West, ref=self.symbol.west, net=node.n4)
        node.port_east = SchemPort(pos=Vec2R(x=2, y=4), align=Orientation.East, ref=self.symbol.east, net=node.n3)

        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=8, uy=8))

class TapAlignTest(Cell):
    @generate(Schematic)
    def schematic(self, node):
        node.north = Net()
        node.south = Net()
        node.east = Net()
        node.west = Net()

        node.north % SchemTapPoint(pos=Vec2R(x=4, y=6), align=Orientation.North)
        node.south % SchemTapPoint(pos=Vec2R(x=4, y=2), align=Orientation.South)
        node.west % SchemTapPoint(pos=Vec2R(x=2, y=4), align=Orientation.West)
        node.east % SchemTapPoint(pos=Vec2R(x=6, y=4), align=Orientation.East)

        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=8, uy=8))


class DFF(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.vss = Pin(pintype=PinType.In, align=Orientation.South)
        node.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        node.d = Pin(pintype=PinType.In, align=Orientation.West)
        node.q = Pin(pintype=PinType.Out, align=Orientation.East)
        node.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(node, vpadding=2, hpadding=3)

class MultibitReg_Arrays(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.vss = Pin(pintype=PinType.In, align=Orientation.South)
        node.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        node.d = PathArray()
        node.q = PathArray()
        for i in range(self.params.bits):
            node.d[i] = Pin(pintype=PinType.In, align=Orientation.West)
            node.q[i] = Pin(pintype=PinType.Out, align=Orientation.East)
        node.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(node)

    @generate(Schematic)
    def schematic(self, node):
        node.vss = Net()
        node.vdd = Net()
        node.clk = Net()
        node.d = PathArray()
        node.q = PathArray()

        node % SchemPort(pos=Vec2R(x=1, y=0), align=Orientation.East, ref=self.symbol.vss, net=node.vss)
        node % SchemPort(pos=Vec2R(x=1, y=1), align=Orientation.East, ref=self.symbol.vdd, net=node.vdd)
        node % SchemPort(pos=Vec2R(x=1, y=2), align=Orientation.East, ref=self.symbol.clk, net=node.clk)
        node.ref = self.symbol
        for i in range(self.params.bits):
            node.d[i] = Net()
            node.q[i] = Net()
            inst = node % SchemInstance(pos=Vec2R(x=2, y=3 + 8*i), ref=DFF().symbol, orientation=Orientation.R0)
            inst.portmap={
                DFF().symbol.vss: node.vss,
                DFF().symbol.vdd: node.vdd,
                DFF().symbol.clk: node.clk,
                DFF().symbol.d: node.d[i],
                DFF().symbol.q: node.q[i],
            }

            node % SchemPort(pos=Vec2R(x=1, y=5+8*i), align=Orientation.East, ref=self.symbol.d[i], net=node.d[i])
            node.d[i] % SchemPoly(vertices=[Vec2R(x=1, y=5+8*i), Vec2R(x=2, y=5+8*i)])
            node % SchemPort(pos=Vec2R(x=9, y=5+8*i), align=Orientation.West, ref=self.symbol.q[i], net=node.q[i])
            node.q[i] % SchemPoly(vertices=[Vec2R(x=8, y=5+8*i), Vec2R(x=9, y=5+8*i)])

        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=10, uy=2+8*self.params.bits))

        helpers.schem_check(node, add_conn_points=True, add_terminal_taps=True)


class MultibitReg_ArrayOfStructs(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.vss = Pin(pintype=PinType.In, align=Orientation.South)
        node.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        node.bit = PathArray()
        for i in range(self.params.bits):
            node.bit[i] = PathStruct()
            node.bit[i].d = Pin(pintype=PinType.In, align=Orientation.West)
            node.bit[i].q = Pin(pintype=PinType.Out, align=Orientation.East)
        node.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(node)

class MultibitReg_StructOfArrays(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.vss = Pin(pintype=PinType.In, align=Orientation.South)
        node.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        node.data = PathStruct()
        node.data.d = PathArray()
        node.data.q = PathArray()
        for i in range(self.params.bits):
            node.data.d[i] = Pin(pintype=PinType.In, align=Orientation.West)
            node.data.q[i] = Pin(pintype=PinType.Out, align=Orientation.East)
        node.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(node)

class TestNmosInv(Cell):
    """
    For testing schem_check.
    """
    @generate(Symbol)
    def symbol(self, node):
        node.vdd = Pin(pintype=PinType.Inout, align=Orientation.North)
        node.vss = Pin(pintype=PinType.Inout, align=Orientation.South)
        node.a = Pin(pintype=PinType.In, align=Orientation.West)
        node.y = Pin(pintype=PinType.Out, align=Orientation.East)
        helpers.symbol_place_pins(node)
        
    @generate(Schematic)
    def schematic(self, node):
        node.a = Net()
        node.y = Net()
        node.vdd = Net()
        node.vss = Net()

        nmos = Nmos(w=R("500n"), l=R("250n")).symbol

        node.pd = SchemInstance(pos=Vec2R(x=3, y=2), ref=nmos, portmap={nmos.s:node.vss, nmos.b:node.vss, nmos.g:node.a, nmos.d:node.y})
        if self.params.variant == "portmap_missing_key":
            del node.pd.portmap[nmos.d]
        if self.params.variant == "portmap_stray_key":
            node.pd.portmap[123] = 456
        if self.params.variant == "portmap_bad_value":
            node.pd.portmap[nmos.d] = 456
        if self.params.variant == "incorrect_pin_conn":
            node.pd.portmap[nmos.b] = node.vdd

        node.pu = SchemInstance(pos=Vec2R(x=3, y=8), ref=nmos, portmap={nmos.d:node.vdd, nmos.b:node.vss, nmos.g:node.vdd, nmos.s:node.y})
        if self.params.variant=="double_instance":
            node.pu2 = SchemInstance(pos=Vec2R(x=3, y=8), ref=nmos, portmap={nmos.d:node.vdd, nmos.b:node.vss, nmos.g:node.vdd, nmos.s:node.y})

        node.ref = self.symbol
        node.port_vdd = SchemPort(pos=Vec2R(x=1, y=13), align=Orientation.East, ref=self.symbol.vdd, net=node.vdd)
        node.port_vss = SchemPort(pos=Vec2R(x=1, y=1), align=Orientation.East, ref=self.symbol.vss, net=node.vss)
        node.port_a = SchemPort(pos=Vec2R(x=1, y=4), align=Orientation.East, ref=self.symbol.a, net=node.a)
        node.port_y = SchemPort(pos=Vec2R(x=9, y=7), align=Orientation.West, ref=self.symbol.y, net=node.y)
        if self.params.variant == 'incorrect_port_conn':
            node.port_y.net = node.a
        
        if self.params.variant == "no_wiring":
            node.default_supply = node.vdd
            node.default_ground = node.vss
        else:
            node.vss % SchemPoly(vertices=[node.port_vss.pos, Vec2R(x=5, y=1), node.pd.pos + nmos.s.pos])
            if self.params.variant == 'skip_single_pin':
                node.vss % SchemPoly(vertices=[Vec2R(x=7, y=4), Vec2R(x=8, y=4)])
            else:
                node.vss % SchemPoly(vertices=[Vec2R(x=7, y=4), Vec2R(x=8, y=4), Vec2R(x=8, y=10), Vec2R(x=7, y=10)])
            if self.params.variant not in ('net_partitioned', 'net_partitioned_tapped'):
                node.vss % SchemPoly(vertices=[Vec2R(x=8, y=4), Vec2R(x=8, y=1), Vec2R(x=5, y=1)])

            if self.params.variant == 'net_partitioned_tapped':
                node.vss % SchemTapPoint(pos=Vec2R(x=8,y=4), align=Orientation.South)
                node.vss % SchemTapPoint(pos=Vec2R(x=5,y=1), align=Orientation.East)

            if self.params.variant == 'vdd_bad_wiring':
                node.vdd % SchemPoly(vertices=[node.port_vdd.pos, Vec2R(x=2, y=13)])
            elif self.params.variant != 'skip_vdd_wiring':
                node.vdd % SchemPoly(vertices=[node.port_vdd.pos, Vec2R(x=2, y=13), Vec2R(x=5, y=13), node.pu.pos + nmos.d.pos])
                if self.params.variant == "terminal_multiple_wires":
                    node.vdd % SchemPoly(vertices=[Vec2R(x=1, y=13), Vec2R(x=1, y=10), Vec2R(x=3, y=10)])
                else:
                    node.vdd % SchemPoly(vertices=[Vec2R(x=2, y=13), Vec2R(x=2, y=10), Vec2R(x=3, y=10)])

            if self.params.variant == "terminal_connpoint":
                node.vdd % SchemConnPoint(pos=node.port_vdd.pos)

            if self.params.variant == "stray_conn_point":
                node.vdd % SchemConnPoint(pos=Vec2R(x=5, y=13))
            if self.params.variant == "tap_short":
                node.vss % SchemTapPoint(pos=Vec2R(x=5, y=13))

            if self.params.variant == 'poly_short':
                node.vdd % SchemPoly(vertices=[Vec2R(x=2, y=10), Vec2R(x=2, y=4),])

            node.a % SchemPoly(vertices=[node.port_a.pos, Vec2R(x=2, y=4), Vec2R(x=3, y=4)])
            node.y % SchemPoly(vertices=[Vec2R(x=5, y=6), Vec2R(x=5, y=7), Vec2R(x=5, y=8)])
            node.y % SchemPoly(vertices=[Vec2R(x=5, y=7), Vec2R(x=9, y=7)])
            
        if self.params.variant in ("manual_conn_points", "double_connpoint"):
            node.vss % SchemConnPoint(pos=Vec2R(x=5, y=1))
            node.vss % SchemConnPoint(pos=Vec2R(x=8, y=4))
            node.vdd % SchemConnPoint(pos=Vec2R(x=2, y=13))
            node.y % SchemConnPoint(pos=Vec2R(x=5, y=7))
            if self.params.variant == "double_connpoint":
                node.y % SchemConnPoint(pos=Vec2R(x=5, y=7))

        if self.params.variant == "unconnected_conn_point":
            node.y % SchemConnPoint(pos=Vec2R(x=4, y=7))


        helpers.schem_check(node, add_conn_points=self.params.add_conn_points, add_terminal_taps=self.params.add_terminal_taps)

        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=1, ux=10, uy=13))

class RingoscTb(Cell):
    @generate(Schematic)
    def schematic(self, node):
        node.vdd = Net()
        node.vss = Net()
        node.y = Net()
        
        vdc = Vdc().symbol
        node.i0 = SchemInstance(pos=Vec2R(x=0, y=2), ref=vdc,
            portmap={vdc.m:node.vss, vdc.p:node.vdd})

        ro = Ringosc().symbol
        node.dut = SchemInstance(pos=Vec2R(x=5, y=2), ref=ro,
            portmap={ro.vdd:node.vdd, ro.vss:node.vss, ro.y:node.y})

        nc = NoConn().symbol
        node.i1 = SchemInstance(pos=Vec2R(x=10, y=2), ref=nc,
            portmap={nc.a:node.y})

        g = Gnd().symbol
        node.i2 = SchemInstance(pos=Vec2R(x=0, y=-4), ref=g,
            portmap={g.p:node.vss})

        #node.ref = self.symbol

        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=-4, ux=15, uy=7))

        node.vss % SchemPoly(vertices=[Vec2R(x=2, y=2), Vec2R(x=2, y=1), Vec2R(x=2, y=0)])
        node.vss % SchemPoly(vertices=[Vec2R(x=2, y=1), Vec2R(x=7, y=1), Vec2R(x=7, y=2)])
        node.vdd % SchemPoly(vertices=[Vec2R(x=2, y=6), Vec2R(x=2, y=7), Vec2R(x=7, y=7), Vec2R(x=7, y=6)])
        node.y % SchemPoly(vertices=[Vec2R(x=9, y=4), Vec2R(x=10, y=4)])
        
        helpers.schem_check(node, add_conn_points=True)

class ResdivFlatTb(Cell):
    @generate(Schematic)
    def schematic(self, node):
        node.vdd = Net()
        node.vss = Net()
        node.a = Net()
        node.b = Net()

        s_vdc = Vdc(dc=R(1)).symbol
        s_gnd = Gnd().symbol
        s_res = Res(r=R(100)).symbol

        node % SchemInstance(pos=Vec2R(x=5,y=0), ref=s_gnd, portmap={s_gnd.p: node.vss})
        node % SchemInstance(pos=Vec2R(x=0,y=6), ref=s_vdc, portmap={s_vdc.m: node.vss, s_vdc.p: node.vdd})
        node % SchemInstance(pos=Vec2R(x=5,y=6), ref=s_res, portmap={s_res.m: node.vss, s_res.p: node.a})
        node % SchemInstance(pos=Vec2R(x=5,y=11), ref=s_res, portmap={s_res.m: node.a,  s_res.p: node.b})
        node % SchemInstance(pos=Vec2R(x=5,y=16), ref=s_res, portmap={s_res.m: node.b,  s_res.p: node.vdd})
        
        node.vss % SchemPoly(vertices=[Vec2R(x=7, y=4), Vec2R(x=7, y=5), Vec2R(x=7, y=6)])
        node.vss % SchemPoly(vertices=[Vec2R(x=2, y=6), Vec2R(x=2, y=5), Vec2R(x=7, y=5)])
        node.vdd % SchemPoly(vertices=[Vec2R(x=2, y=10), Vec2R(x=2, y=21), Vec2R(x=7, y=21), Vec2R(x=7, y=20)])
        node.a % SchemPoly(vertices=[Vec2R(x=7, y=10), Vec2R(x=7, y=11)])
        node.b % SchemPoly(vertices=[Vec2R(x=7, y=15), Vec2R(x=7, y=16)])
        
        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=9, uy=21))

        helpers.schem_check(node, add_conn_points=True)

    @generate(SimHierarchy)
    def sim_dc(self, node):
        sim = HighlevelSim(self.schematic, node)
        sim.op()


class ResdivHier2(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.t = Pin(pintype=PinType.Inout, align=Orientation.North)
        node.r = Pin(pintype=PinType.Inout, align=Orientation.East)
        node.b = Pin(pintype=PinType.Inout, align=Orientation.South)
        helpers.symbol_place_pins(node, vpadding=2, hpadding=2)

    @generate(Schematic)
    def schematic(self, node):
        node.ref = self.symbol
        node.t = Net()
        node.r = Net()
        node.b = Net()
        node.m = Net()

        node % SchemPort(pos=Vec2R(x=2, y=12), align=Orientation.South, ref=self.symbol.t, net=node.t)
        node % SchemPort(pos=Vec2R(x=10, y=6), align=Orientation.West, ref=self.symbol.r, net=node.r)
        node % SchemPort(pos=Vec2R(x=2, y=0), align=Orientation.North, ref=self.symbol.b, net=node.b)

        s_res = Res(r=self.params.r).symbol

        node % qinst(pos=Vec2R(x=0,y=1), ref=s_res, m=node.b, p=node.m)
        node % qinst(pos=Vec2R(x=0,y=7), ref=s_res, m=node.m, p=node.t)
        node % qinst(pos=Vec2R(x=9,y=4), orientation=Orientation.R90, ref=s_res, m=node.r, p=node.m)

        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=10, uy=12))

        node.t % SchemPoly(vertices=[Vec2R(x=2, y=12), Vec2R(x=2, y=11)])
        node.b % SchemPoly(vertices=[Vec2R(x=2, y=0), Vec2R(x=2, y=1)])
        node.m % SchemPoly(vertices=[Vec2R(x=2, y=5), Vec2R(x=2, y=6), Vec2R(x=2, y=7)])
        node.m % SchemPoly(vertices=[Vec2R(x=2, y=6), Vec2R(x=5, y=6)])

        node.r % SchemPoly(vertices=[Vec2R(x=9, y=6), Vec2R(x=10, y=6)])

        helpers.schem_check(node, add_conn_points=True)

class ResdivHier1(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.t = Pin(pintype=PinType.Inout, align=Orientation.North)
        node.r = Pin(pintype=PinType.Inout, align=Orientation.East)
        node.b = Pin(pintype=PinType.Inout, align=Orientation.South)
        helpers.symbol_place_pins(node, vpadding=2, hpadding=2)

    @generate(Schematic)
    def schematic(self, node):
        node.ref = self.symbol

        node.t = Net()
        node.r = Net()
        node.b = Net()
        node.tr = Net()
        node.br = Net()
        node.m = Net()

        node % SchemPort(pos=Vec2R(x=7, y=11), align=Orientation.South, ref=self.symbol.t, net=node.t)
        node % SchemPort(pos=Vec2R(x=15, y=5), align=Orientation.West, ref=self.symbol.r, net=node.r)
        node % SchemPort(pos=Vec2R(x=7, y=-1), align=Orientation.North, ref=self.symbol.b, net=node.b)

        s_1 = ResdivHier2(r=R(100)).symbol
        s_2 = ResdivHier2(r=R(200)).symbol
    
        #node % SchemInstance(pos=Vec2R(x=5,y=0), ref=s_1, portmap={s_1.t: node.m, s_1.b:node.gnd, s_1.r:node.br})
        node % qinst(pos=Vec2R(x=5,y=0), ref=s_1, t=node.m, b=node.b, r=node.br)
        node % qinst(pos=Vec2R(x=5,y=6), ref=s_2, t=node.t, b=node.m, r=node.tr)
        node % qinst(pos=Vec2R(x=10,y=3), ref=s_1, t=node.tr, b=node.br, r=node.r)
        
        node.outline = node % SchemRect(pos=Rect4R(lx=5, ly=-1, ux=15, uy=12))

        node.b % SchemPoly(vertices=[Vec2R(x=7, y=-1), Vec2R(x=7, y=0)])
        node.m % SchemPoly(vertices=[Vec2R(x=7, y=4), Vec2R(x=7, y=6)])
        node.t % SchemPoly(vertices=[Vec2R(x=7, y=10), Vec2R(x=7, y=11)])
        node.tr % SchemPoly(vertices=[Vec2R(x=9, y=8), Vec2R(x=12, y=8), Vec2R(x=12, y=7)])
        node.br % SchemPoly(vertices=[Vec2R(x=9, y=2), Vec2R(x=12, y=2), Vec2R(x=12, y=3)])
        node.r % SchemPoly(vertices=[Vec2R(x=14, y=5), Vec2R(x=15, y=5)])

        helpers.schem_check(node, add_conn_points=True)

class ResdivHierTb(Cell):
    @generate(Schematic)
    def schematic(self, node):
        node.t = Net()
        node.r = Net()
        node.gnd = Net()
    
        node % qinst(pos=Vec2R(x=5,y=0), ref=ResdivHier1().symbol, t=node.t, b=node.gnd, r=node.r)
        node % qinst(pos=Vec2R(x=10,y=0), ref=NoConn().symbol, a=node.r)
        node % qinst(pos=Vec2R(x=0,y=0), ref=Vdc(dc=R(1)).symbol, m=node.gnd, p=node.t)
        node % qinst(pos=Vec2R(x=0,y=-6), ref=Gnd().symbol, p=node.gnd)

        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=-6, ux=14, uy=5))

        node.gnd % SchemPoly(vertices=[Vec2R(x=2, y=-2), Vec2R(x=2, y=-1), Vec2R(x=2, y=0)])
        node.gnd % SchemPoly(vertices=[Vec2R(x=2, y=-1), Vec2R(x=7, y=-1), Vec2R(x=7, y=0)])
        node.t % SchemPoly(vertices=[Vec2R(x=7, y=4), Vec2R(x=7, y=5), Vec2R(x=2, y=5), Vec2R(x=2, y=4)])
        node.r % SchemPoly(vertices=[Vec2R(x=9, y=2), Vec2R(x=10, y=2)])

        helpers.schem_check(node, add_conn_points=True)

    @generate(SimHierarchy)
    def sim_hierarchy(self, node):
        HighlevelSim(self.schematic, node)
        # Build SimHierarchy, but runs no simulations.

    @generate(SimHierarchy)
    def sim_dc(self, node):
        sim = HighlevelSim(self.schematic, node)
        sim.op()
