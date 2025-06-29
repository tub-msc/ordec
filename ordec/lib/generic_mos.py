# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..schema import *
from ..cell import Cell, generate
from ..rational import R
from ..geoprim import *
from .. import helpers
 
def setup_generic_mos(netlister):
    vt0 = 1.0
    common_args = [
        'KP=2.0e-5', # Transconductance parameter
        'LAMBDA=0.0', # Channel length modulation parameter
        'PHI=0.6', # Surface potential
        'GAMMA=0.0', # Bulk threshold parameter
    ]
    netlister.add('.model', 'nmosgeneric', 'NMOS', 'level=1', f'VTO={vt0}', *common_args)
    netlister.add('.model', 'pmosgeneric', 'PMOS', 'level=1', f'VTO={-vt0}', *common_args)

def params_to_spice(params, allowed_keys=('l', 'w', 'ad', 'as', 'm')):
    spice_params = []
    for k, v in params.items():
        if k not in allowed_keys:
            continue
        spice_params.append(f"{k}={v}")
    return spice_params

class Nmos(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.g = Pin(pos=Vec2R(x=0, y=2), pintype=PinType.In, align=Orientation.West)
        node.s = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.d = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        node.b = Pin(pos=Vec2R(x=4, y=2), pintype=PinType.In, align=Orientation.East)
        
        node % SymbolPoly(vertices=[Vec2R(x=2, y=0), Vec2R(x=2, y=1.25), Vec2R(x=1.3, y=1.25), Vec2R(x=1.3, y=2.75), Vec2R(x=2, y=2.75), Vec2R(x=2, y=4)])
        node % SymbolPoly(vertices=[Vec2R(x=1, y=1.25), Vec2R(x=1, y=2.75)])
        node % SymbolPoly(vertices=[Vec2R(x=0, y=2), Vec2R(x=1, y=2)])
        node % SymbolPoly(vertices=[Vec2R(x=4, y=2), Vec2R(x=1.3, y=2)])
        node % SymbolPoly(vertices=[Vec2R(x=1.7, y=1.8), Vec2R(x=1.3, y=2), Vec2R(x=1.7, y=2.2)])
        node % SymbolPoly(vertices=[Vec2R(x=1.6, y=1.05), Vec2R(x=2, y=1.25), Vec2R(x=1.6, y=1.45)])

        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)

    def netlist_ngspice(self, netlister, inst, schematic):
        netlister.require_setup(setup_generic_mos)
        pins = [inst.symbol.d, inst.symbol.g, inst.symbol.s, inst.symbol.b]
        netlister.add(netlister.name_obj(inst, schematic, prefix="m"), netlister.portmap(inst, pins), 'nmosgeneric', *params_to_spice(self.params))

class Pmos(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.g = Pin(pos=Vec2R(x=0, y=2), pintype=PinType.In, align=Orientation.West)
        node.d = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.s = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        node.b = Pin(pos=Vec2R(x=4, y=2), pintype=PinType.In, align=Orientation.East)
        
        node % SymbolPoly(vertices=[Vec2R(x=2, y=0), Vec2R(x=2, y=1.25), Vec2R(x=1.3, y=1.25), Vec2R(x=1.3, y=2.75), Vec2R(x=2, y=2.75), Vec2R(x=2, y=4)])
        node % SymbolPoly(vertices=[Vec2R(x=1, y=1.25), Vec2R(x=1, y=2.75)])
        node % SymbolPoly(vertices=[Vec2R(x=0, y=2), Vec2R(x=1, y=2)])
        node % SymbolPoly(vertices=[Vec2R(x=4, y=2), Vec2R(x=1.3, y=2)])
        node % SymbolPoly(vertices=[Vec2R(x=1.7, y=2.55), Vec2R(x=1.3, y=2.75), Vec2R(x=1.7, y=2.95)])
        node % SymbolPoly(vertices=[Vec2R(x=1.6, y=1.8), Vec2R(x=2, y=2), Vec2R(x=1.6, y=2.2)])

        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)

    def netlist_ngspice(self, netlister, inst, schematic):
        netlister.require_setup(setup_generic_mos)
        pins = [inst.symbol.d, inst.symbol.g, inst.symbol.s, inst.symbol.b]
        netlister.add(netlister.name_obj(inst, schematic, prefix="m"), netlister.portmap(inst, pins), 'pmosgeneric', *params_to_spice(self.params))

class Inv(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.vdd = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        node.vss = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.a = Pin(pos=Vec2R(x=0, y=2), pintype=PinType.In, align=Orientation.West)
        node.y = Pin(pos=Vec2R(x=4, y=2), pintype=PinType.Out, align=Orientation.East)

        node % SymbolPoly(vertices=[Vec2R(x=0, y=2), Vec2R(x=1, y=2)])
        node % SymbolPoly(vertices=[Vec2R(x=3.25, y=2), Vec2R(x=4, y=2)])
        node % SymbolPoly(vertices=[Vec2R(x=1, y=1), Vec2R(x=1, y=3), Vec2R(x=2.75,y=2), Vec2R(x=1, y=1)])
        node % SymbolArc(pos=Vec2R(x=3,y=2), radius=R(0.25))

        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)

    @generate(Schematic)
    def schematic(self, node):
        node.a = Net(pin=self.symbol.a)
        node.y = Net(pin=self.symbol.y)
        node.vdd = Net(pin=self.symbol.vdd)
        node.vss = Net(pin=self.symbol.vss)

        nmos = Nmos(w=R("500n"), l=R("250n")).symbol
        pmos = Pmos(w=R("500n"), l=R("250n")).symbol

        node.pd = SchemInstance(nmos.portmap(s=node.vss, b=node.vss, g=node.a, d=node.y), pos=Vec2R(3, 2))
        node.pu = SchemInstance(pmos.portmap(s=node.vdd, b=node.vdd, g=node.a, d=node.y), pos=Vec2R(3, 8))

        
        node.symbol = self.symbol
        node.vdd % SchemPort(pos=Vec2R(x=2, y=13), align=Orientation.East, ref=self.symbol.vdd)
        node.vss % SchemPort(pos=Vec2R(x=2, y=1), align=Orientation.East, ref=self.symbol.vss)
        node.a % SchemPort(pos=Vec2R(x=1, y=7), align=Orientation.East, ref=self.symbol.a)
        node.y % SchemPort(pos=Vec2R(x=9, y=7), align=Orientation.West, ref=self.symbol.y)
        
        node.vss % SchemWire([Vec2R(2, 1), Vec2R(5, 1), Vec2R(8, 1), Vec2R(8, 4), Vec2R(7, 4)])
        node.vss % SchemWire([Vec2R(5, 1), node.pd.pos + nmos.s.pos])
        node.vdd % SchemWire([Vec2R(2, 13), Vec2R(5, 13), Vec2R(8, 13), Vec2R(8, 10), Vec2R(7, 10)])
        node.vdd % SchemWire([Vec2R(5, 13), node.pu.pos + pmos.s.pos])
        node.a % SchemWire([Vec2R(3, 4), Vec2R(2, 4), Vec2R(2, 7), Vec2R(2, 10), Vec2R(3, 10)])
        node.a % SchemWire([Vec2R(1, 7), Vec2R(2, 7)])
        node.y % SchemWire([Vec2R(5, 6), Vec2R(5, 7), Vec2R(5, 8)])
        node.y % SchemWire([Vec2R(5, 7), Vec2R(9, 7)])

        helpers.schem_check(node, add_conn_points=True)

        node.outline = Rect4R(lx=0, ly=1, ux=10, uy=13)

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
        node.y2 = Net(pin=self.symbol.y)
        node.vdd = Net(pin=self.symbol.vdd)
        node.vss = Net(pin=self.symbol.vss)

        inv = Inv().symbol
        node.i0 = SchemInstance(inv.portmap(vdd=node.vdd, vss=node.vss, a=node.y2, y=node.y0), pos=Vec2R(x=4, y=2))
        node.i1 = SchemInstance(inv.portmap(vdd=node.vdd, vss=node.vss, a=node.y0, y=node.y1), pos=Vec2R(x=10, y=2))
        node.i2 = SchemInstance(inv.portmap(vdd=node.vdd, vss=node.vss, a=node.y1, y=node.y2), pos=Vec2R(x=16, y=2))
        node.symbol = self.symbol
        node.vdd % SchemPort(pos=Vec2R(x=2, y=7), align=Orientation.East)
        node.vss % SchemPort(pos=Vec2R(x=2, y=1), align=Orientation.East)
        node.y2 % SchemPort(pos=Vec2R(x=22, y=4), align=Orientation.West)
        
        node.outline = Rect4R(lx=0, ly=0, ux=24, uy=8)

        node.y0 % SchemWire(vertices=[node.i0.pos+inv.y.pos, node.i1.pos+inv.a.pos])
        node.y1 % SchemWire(vertices=[node.i1.pos+inv.y.pos, node.i2.pos+inv.a.pos])
        node.y2 % SchemWire(vertices=[node.i2.pos+inv.y.pos, Vec2R(x=21,y=4), Vec2R(x=22, y=4)])
        node.y2 % SchemWire(vertices=[Vec2R(x=21,y=4), Vec2R(x=21,y=8), Vec2R(x=3,y=8), Vec2R(x=3,y=4), node.i0.pos+inv.a.pos])

        node.vss % SchemWire(vertices=[Vec2R(x=2, y=1), Vec2R(x=6, y=1), Vec2R(x=12, y=1), Vec2R(x=18, y=1), Vec2R(x=18, y=2)])
        node.vss % SchemWire(vertices=[Vec2R(x=6, y=1), Vec2R(x=6, y=2)])
        node.vss % SchemWire(vertices=[Vec2R(x=12, y=1), Vec2R(x=12, y=2)])

        node.vdd % SchemWire(vertices=[Vec2R(x=2, y=7), Vec2R(x=6, y=7), Vec2R(x=12, y=7), Vec2R(x=18, y=7), Vec2R(x=18, y=6)])
        node.vdd % SchemWire(vertices=[Vec2R(x=6, y=7), Vec2R(x=6, y=6)])
        node.vdd % SchemWire(vertices=[Vec2R(x=12, y=7), Vec2R(x=12, y=6)])

        helpers.schem_check(node, add_conn_points=True)

class And2(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.vdd = Pin(pos=Vec2R(x=2.5, y=5), pintype=PinType.Inout, align=Orientation.North)
        node.vss = Pin(pos=Vec2R(x=2.5, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.a = Pin(pos=Vec2R(x=0, y=3), pintype=PinType.In, align=Orientation.West)
        node.b = Pin(pos=Vec2R(x=0, y=2), pintype=PinType.In, align=Orientation.West)
        node.y = Pin(pos=Vec2R(x=5, y=2.5), pintype=PinType.Out, align=Orientation.East)

        node % SymbolPoly(vertices=[Vec2R(x=0, y=2), Vec2R(x=1, y=2)])
        node % SymbolPoly(vertices=[Vec2R(x=0, y=3), Vec2R(x=1, y=3)])
        node % SymbolPoly(vertices=[Vec2R(x=4, y=2.5), Vec2R(x=5, y=2.5)])
        node % SymbolPoly(vertices=[Vec2R(x=2.75, y=1.25), Vec2R(x=1, y=1.25), Vec2R(x=1, y=3.75), Vec2R(x=2.75, y=3.75)])
        node % SymbolArc(pos=Vec2R(x=2.75,y=2.5), radius=R(1.25), angle_start=R(-0.25), angle_end=R(0.25))
        node.outline = Rect4R(lx=0, ly=0, ux=5, uy=5)

class Or2(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.vdd = Pin(pos=Vec2R(x=2.5, y=5), pintype=PinType.Inout, align=Orientation.North)
        node.vss = Pin(pos=Vec2R(x=2.5, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.a = Pin(pos=Vec2R(x=0, y=3), pintype=PinType.In, align=Orientation.West)
        node.b = Pin(pos=Vec2R(x=0, y=2), pintype=PinType.In, align=Orientation.West)
        node.y = Pin(pos=Vec2R(x=5, y=2.5), pintype=PinType.Out, align=Orientation.East)

        node % SymbolPoly(vertices=[Vec2R(x=0, y=2), Vec2R(x=1.3, y=2)])
        node % SymbolPoly(vertices=[Vec2R(x=0, y=3), Vec2R(x=1.3, y=3)])
        node % SymbolPoly(vertices=[Vec2R(x=4, y=2.5), Vec2R(x=5, y=2.5)])
        node % SymbolPoly(vertices=[Vec2R(x=1, y=3.75), Vec2R(x=1.95, y=3.75)])
        node % SymbolPoly(vertices=[Vec2R(x=1, y=1.25), Vec2R(x=1.95, y=1.25)])
        node % SymbolArc(pos=Vec2R(x=-1.02,y=2.5), radius=R(2.4), angle_start=R(-0.085), angle_end=R(0.085))
        node % SymbolArc(pos=Vec2R(x=1.95,y=1.35), radius=R(2.4), angle_start=R(0.08), angle_end=R(0.25))
        node % SymbolArc(pos=Vec2R(x=1.95,y=3.65), radius=R(2.4), angle_start=R(-0.25), angle_end=R(-0.08))
        node.outline = Rect4R(lx=0, ly=0, ux=5, uy=5)

__all__ = ["Nmos", "Pmos", "Inv", "Ringosc", "And2", "Or2"]
