# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from .. import Cell, Vec2R, Rect4R, Pin, PinArray, PinStruct, Symbol, Schematic, PinType, Rational as R, SchemPoly, SchemArc, SchemRect, SchemInstance, SchemPort, Net, Orientation, SchemConnPoint, SchemTapPoint, generate, helpers
 

class Nmos(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.g = Pin(pos=Vec2R(x=0, y=2), pintype=PinType.In, align=Orientation.West)
        node.s = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.d = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        node.b = Pin(pos=Vec2R(x=4, y=2), pintype=PinType.In, align=Orientation.East)
        
        node % SchemPoly(vertices=[Vec2R(x=2, y=0), Vec2R(x=2, y=1.25), Vec2R(x=1.3, y=1.25), Vec2R(x=1.3, y=2.75), Vec2R(x=2, y=2.75), Vec2R(x=2, y=4)])
        node % SchemPoly(vertices=[Vec2R(x=1, y=1.25), Vec2R(x=1, y=2.75)])
        node % SchemPoly(vertices=[Vec2R(x=0, y=2), Vec2R(x=1, y=2)])
        node % SchemPoly(vertices=[Vec2R(x=4, y=2), Vec2R(x=1.3, y=2)])
        node % SchemPoly(vertices=[Vec2R(x=1.7, y=1.8), Vec2R(x=1.3, y=2), Vec2R(x=1.7, y=2.2)])
        node % SchemPoly(vertices=[Vec2R(x=1.6, y=1.05), Vec2R(x=2, y=1.25), Vec2R(x=1.6, y=1.45)])

        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=4, uy=4))

class Pmos(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.g = Pin(pos=Vec2R(x=0, y=2), pintype=PinType.In, align=Orientation.West)
        node.d = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.s = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        node.b = Pin(pos=Vec2R(x=4, y=2), pintype=PinType.In, align=Orientation.East)
        
        node % SchemPoly(vertices=[Vec2R(x=2, y=0), Vec2R(x=2, y=1.25), Vec2R(x=1.3, y=1.25), Vec2R(x=1.3, y=2.75), Vec2R(x=2, y=2.75), Vec2R(x=2, y=4)])
        node % SchemPoly(vertices=[Vec2R(x=1, y=1.25), Vec2R(x=1, y=2.75)])
        node % SchemPoly(vertices=[Vec2R(x=0, y=2), Vec2R(x=1, y=2)])
        node % SchemPoly(vertices=[Vec2R(x=4, y=2), Vec2R(x=1.3, y=2)])
        node % SchemPoly(vertices=[Vec2R(x=1.7, y=2.55), Vec2R(x=1.3, y=2.75), Vec2R(x=1.7, y=2.95)])
        node % SchemPoly(vertices=[Vec2R(x=1.6, y=1.8), Vec2R(x=2, y=2), Vec2R(x=1.6, y=2.2)])

        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=4, uy=4))

class Inv(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.vdd = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        node.vss = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.a = Pin(pos=Vec2R(x=0, y=2), pintype=PinType.In, align=Orientation.West)
        node.y = Pin(pos=Vec2R(x=4, y=2), pintype=PinType.Out, align=Orientation.East)

        node % SchemPoly(vertices=[Vec2R(x=0, y=2), Vec2R(x=1, y=2)])
        node % SchemPoly(vertices=[Vec2R(x=3.25, y=2), Vec2R(x=4, y=2)])
        node % SchemPoly(vertices=[Vec2R(x=1, y=1), Vec2R(x=1, y=3), Vec2R(x=2.75,y=2), Vec2R(x=1, y=1)])
        node % SchemArc(pos=Vec2R(x=3,y=2), radius=R(0.25))

        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=4, uy=4))

    @generate(Schematic)
    def schematic(self, node):
        node.a = Net()
        node.y = Net()
        node.vdd = Net()
        node.vss = Net()

        nmos = Nmos(w=R("500n"), l=R("250n")).symbol
        pmos = Pmos(w=R("500n"), l=R("250n")).symbol

        node.pd = SchemInstance(pos=Vec2R(x=3, y=2), ref=nmos, portmap={nmos.s:node.vss, nmos.b:node.vss, nmos.g:node.a, nmos.d:node.y})
        node.pu = SchemInstance(pos=Vec2R(x=3, y=8), ref=pmos, portmap={pmos.s:node.vdd, pmos.b:node.vdd, pmos.g:node.a, pmos.d:node.y})
        
        node.ref = self.symbol
        node.port_vdd = SchemPort(pos=Vec2R(x=2, y=13), align=Orientation.East, ref=self.symbol.vdd, net=node.vdd)
        node.port_vss = SchemPort(pos=Vec2R(x=2, y=1), align=Orientation.East, ref=self.symbol.vss, net=node.vss)
        node.port_a = SchemPort(pos=Vec2R(x=1, y=7), align=Orientation.East, ref=self.symbol.a, net=node.a)
        node.port_y = SchemPort(pos=Vec2R(x=9, y=7), align=Orientation.West, ref=self.symbol.y, net=node.y)
        
        node.vss % SchemPoly(vertices=[node.port_vss.pos, Vec2R(x=5, y=1), Vec2R(x=8, y=1), Vec2R(x=8, y=4), Vec2R(x=7, y=4)])
        node.vss % SchemPoly(vertices=[Vec2R(x=5, y=1), node.pd.pos + nmos.s.pos])
        node.vdd % SchemPoly(vertices=[node.port_vdd.pos, Vec2R(x=5, y=13), Vec2R(x=8, y=13), Vec2R(x=8, y=10), Vec2R(x=7, y=10)])
        node.vdd % SchemPoly(vertices=[Vec2R(x=5, y=13), node.pu.pos + pmos.s.pos])
        node.a % SchemPoly(vertices=[Vec2R(x=3, y=4), Vec2R(x=2, y=4), Vec2R(x=2, y=7), Vec2R(x=2, y=10), Vec2R(x=3, y=10)])
        node.a % SchemPoly(vertices=[Vec2R(x=1, y=7), Vec2R(x=2, y=7)])
        node.y % SchemPoly(vertices=[Vec2R(x=5, y=6), Vec2R(x=5, y=7), Vec2R(x=5, y=8)])
        node.y % SchemPoly(vertices=[Vec2R(x=5, y=7), Vec2R(x=9, y=7)])
        
        helpers.schem_check(node, add_conn_points=True)

        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=1, ux=10, uy=13))

class Ringosc(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.vdd = Pin(pintype=PinType.Inout, align=Orientation.North)
        node.vss = Pin(pintype=PinType.Inout, align=Orientation.South)
        node.y = Pin(pintype=PinType.Out, align=Orientation.East)

        helpers.symbol_place_pins(node, vpadding=2, hpadding=2)

    @generate(Schematic)
    def schematic(self, node):
        node.y0 = Net()
        node.y1 = Net()
        node.y2 = Net()
        node.vdd = Net()
        node.vss = Net()

        inv = Inv().symbol
        node.i0 = SchemInstance(pos=Vec2R(x=4, y=2), ref=inv,
            portmap={inv.vdd:node.vdd, inv.vss:node.vss, inv.a:node.y2, inv.y:node.y0})
        node.i1 = SchemInstance(pos=Vec2R(x=10, y=2), ref=inv,
            portmap={inv.vdd:node.vdd, inv.vss:node.vss, inv.a:node.y0, inv.y:node.y1})
        node.i2 = SchemInstance(pos=Vec2R(x=16, y=2), ref=inv,
            portmap={inv.vdd:node.vdd, inv.vss:node.vss, inv.a:node.y1, inv.y:node.y2})
        node.ref = self.symbol
        node.port_vdd = SchemPort(pos=Vec2R(x=2, y=7), align=Orientation.East, ref=self.symbol.vdd, net=node.vdd)
        node.port_vss = SchemPort(pos=Vec2R(x=2, y=1), align=Orientation.East, ref=self.symbol.vss, net=node.vss)
        node.port_y = SchemPort(pos=Vec2R(x=22, y=4), align=Orientation.West, ref=self.symbol.y, net=node.y2)
        
        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=24, uy=8))

        node.y0 % SchemPoly(vertices=[node.i0.pos+inv.y.pos, node.i1.pos+inv.a.pos])
        node.y1 % SchemPoly(vertices=[node.i1.pos+inv.y.pos, node.i2.pos+inv.a.pos])
        node.y2 % SchemPoly(vertices=[node.i2.pos+inv.y.pos, Vec2R(x=21,y=4), node.port_y.pos])
        node.y2 % SchemPoly(vertices=[Vec2R(x=21,y=4), Vec2R(x=21,y=8), Vec2R(x=3,y=8), Vec2R(x=3,y=4), node.i0.pos+inv.a.pos])

        node.vss % SchemPoly(vertices=[node.port_vss.pos, Vec2R(x=6, y=1), Vec2R(x=12, y=1), Vec2R(x=18, y=1), Vec2R(x=18, y=2)])
        node.vss % SchemPoly(vertices=[Vec2R(x=6, y=1), Vec2R(x=6, y=2)])
        node.vss % SchemPoly(vertices=[Vec2R(x=12, y=1), Vec2R(x=12, y=2)])

        node.vdd % SchemPoly(vertices=[node.port_vdd.pos, Vec2R(x=6, y=7), Vec2R(x=12, y=7), Vec2R(x=18, y=7), Vec2R(x=18, y=6)])
        node.vdd % SchemPoly(vertices=[Vec2R(x=6, y=7), Vec2R(x=6, y=6)])
        node.vdd % SchemPoly(vertices=[Vec2R(x=12, y=7), Vec2R(x=12, y=6)])

        helpers.schem_check(node, add_conn_points=True)

class And2(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.vdd = Pin(pos=Vec2R(x=2.5, y=5), pintype=PinType.Inout, align=Orientation.North)
        node.vss = Pin(pos=Vec2R(x=2.5, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.a = Pin(pos=Vec2R(x=0, y=3), pintype=PinType.In, align=Orientation.West)
        node.b = Pin(pos=Vec2R(x=0, y=2), pintype=PinType.In, align=Orientation.West)
        node.y = Pin(pos=Vec2R(x=5, y=2.5), pintype=PinType.Out, align=Orientation.East)

        node % SchemPoly(vertices=[Vec2R(x=0, y=2), Vec2R(x=1, y=2)])
        node % SchemPoly(vertices=[Vec2R(x=0, y=3), Vec2R(x=1, y=3)])
        node % SchemPoly(vertices=[Vec2R(x=4, y=2.5), Vec2R(x=5, y=2.5)])
        node % SchemPoly(vertices=[Vec2R(x=2.75, y=1.25), Vec2R(x=1, y=1.25), Vec2R(x=1, y=3.75), Vec2R(x=2.75, y=3.75)])
        node % SchemArc(pos=Vec2R(x=2.75,y=2.5), radius=R(1.25), angle_start=R(-0.25), angle_end=R(0.25))
        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=5, uy=5))

class Or2(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.vdd = Pin(pos=Vec2R(x=2.5, y=5), pintype=PinType.Inout, align=Orientation.North)
        node.vss = Pin(pos=Vec2R(x=2.5, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.a = Pin(pos=Vec2R(x=0, y=3), pintype=PinType.In, align=Orientation.West)
        node.b = Pin(pos=Vec2R(x=0, y=2), pintype=PinType.In, align=Orientation.West)
        node.y = Pin(pos=Vec2R(x=5, y=2.5), pintype=PinType.Out, align=Orientation.East)

        node % SchemPoly(vertices=[Vec2R(x=0, y=2), Vec2R(x=1.3, y=2)])
        node % SchemPoly(vertices=[Vec2R(x=0, y=3), Vec2R(x=1.3, y=3)])
        node % SchemPoly(vertices=[Vec2R(x=4, y=2.5), Vec2R(x=5, y=2.5)])
        node % SchemPoly(vertices=[Vec2R(x=1, y=3.75), Vec2R(x=1.95, y=3.75)])
        node % SchemPoly(vertices=[Vec2R(x=1, y=1.25), Vec2R(x=1.95, y=1.25)])
        node % SchemArc(pos=Vec2R(x=-1.02,y=2.5), radius=R(2.4), angle_start=R(-0.085), angle_end=R(0.085))
        node % SchemArc(pos=Vec2R(x=1.95,y=1.35), radius=R(2.4), angle_start=R(0.08), angle_end=R(0.25))
        node % SchemArc(pos=Vec2R(x=1.95,y=3.65), radius=R(2.4), angle_start=R(-0.25), angle_end=R(-0.08))
        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=5, uy=5))

__all__ = ["Nmos", "Pmos", "Inv", "Ringosc", "And2", "Or2"]