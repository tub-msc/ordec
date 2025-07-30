# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from public import public

from ..core import *
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

@public
class Nmos(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.g = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=Orientation.West)
        s.s = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.d = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)
        s.b = Pin(pos=Vec2R(4, 2), pintype=PinType.In, align=Orientation.East)
        
        s % SymbolPoly(vertices=[Vec2R(2, 0), Vec2R(2, 1.25), Vec2R(1.3, 1.25), Vec2R(1.3, 2.75), Vec2R(2, 2.75), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(1, 1.25), Vec2R(1, 2.75)])
        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1, 2)])
        s % SymbolPoly(vertices=[Vec2R(4, 2), Vec2R(1.3, 2)])
        s % SymbolPoly(vertices=[Vec2R(1.7, 1.8), Vec2R(1.3, 2), Vec2R(1.7, 2.2)])
        s % SymbolPoly(vertices=[Vec2R(1.6, 1.05), Vec2R(2, 1.25), Vec2R(1.6, 1.45)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def netlist_ngspice(self, netlister, inst, schematic):
        netlister.require_setup(setup_generic_mos)
        pins = [inst.symbol.d, inst.symbol.g, inst.symbol.s, inst.symbol.b]
        netlister.add(netlister.name_obj(inst, schematic, prefix="m"), netlister.portmap(inst, pins), 'nmosgeneric', *params_to_spice(self.params))

@public
class Pmos(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.g = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=Orientation.West)
        s.d = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.s = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)
        s.b = Pin(pos=Vec2R(4, 2), pintype=PinType.In, align=Orientation.East)
        
        s % SymbolPoly(vertices=[Vec2R(2, 0), Vec2R(2, 1.25), Vec2R(1.3, 1.25), Vec2R(1.3, 2.75), Vec2R(2, 2.75), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(1, 1.25), Vec2R(1, 2.75)])
        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1, 2)])
        s % SymbolPoly(vertices=[Vec2R(4, 2), Vec2R(1.3, 2)])
        s % SymbolPoly(vertices=[Vec2R(1.7, 2.55), Vec2R(1.3, 2.75), Vec2R(1.7, 2.95)])
        s % SymbolPoly(vertices=[Vec2R(1.6, 1.8), Vec2R(2, 2), Vec2R(1.6, 2.2)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def netlist_ngspice(self, netlister, inst, schematic):
        netlister.require_setup(setup_generic_mos)
        pins = [inst.symbol.d, inst.symbol.g, inst.symbol.s, inst.symbol.b]
        netlister.add(netlister.name_obj(inst, schematic, prefix="m"), netlister.portmap(inst, pins), 'pmosgeneric', *params_to_spice(self.params))

@public
class Inv(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vdd = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)
        s.vss = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.a = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=Orientation.West)
        s.y = Pin(pos=Vec2R(4, 2), pintype=PinType.Out, align=Orientation.East)

        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1, 2)])
        s % SymbolPoly(vertices=[Vec2R(3.25, 2), Vec2R(4, 2)])
        s % SymbolPoly(vertices=[Vec2R(1, 1), Vec2R(1, 3), Vec2R(2.75, 2), Vec2R(1, 1)])
        s % SymbolArc(pos=Vec2R(3, 2), radius=R(0.25))

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.a = Net(pin=self.symbol.a)
        s.y = Net(pin=self.symbol.y)
        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)

        nmos = Nmos(w=R("500n"), l=R("250n")).symbol
        pmos = Pmos(w=R("500n"), l=R("250n")).symbol

        s.pd = SchemInstance(nmos.portmap(s=s.vss, b=s.vss, g=s.a, d=s.y), pos=Vec2R(3, 2))
        s.pu = SchemInstance(pmos.portmap(s=s.vdd, b=s.vdd, g=s.a, d=s.y), pos=Vec2R(3, 8))

        s.vdd % SchemPort(pos=Vec2R(2, 13), align=Orientation.East, ref=self.symbol.vdd)
        s.vss % SchemPort(pos=Vec2R(2, 1), align=Orientation.East, ref=self.symbol.vss)
        s.a % SchemPort(pos=Vec2R(1, 7), align=Orientation.East, ref=self.symbol.a)
        s.y % SchemPort(pos=Vec2R(9, 7), align=Orientation.West, ref=self.symbol.y)
        
        s.vss % SchemWire([Vec2R(2, 1), Vec2R(5, 1), Vec2R(8, 1), Vec2R(8, 4), Vec2R(7, 4)])
        s.vss % SchemWire([Vec2R(5, 1), s.pd.pos + nmos.s.pos])
        s.vdd % SchemWire([Vec2R(2, 13), Vec2R(5, 13), Vec2R(8, 13), Vec2R(8, 10), Vec2R(7, 10)])
        s.vdd % SchemWire([Vec2R(5, 13), s.pu.pos + pmos.s.pos])
        s.a % SchemWire([Vec2R(3, 4), Vec2R(2, 4), Vec2R(2, 7), Vec2R(2, 10), Vec2R(3, 10)])
        s.a % SchemWire([Vec2R(1, 7), Vec2R(2, 7)])
        s.y % SchemWire([Vec2R(5, 6), Vec2R(5, 7), Vec2R(5, 8)])
        s.y % SchemWire([Vec2R(5, 7), Vec2R(9, 7)])

        s.outline = Rect4R(lx=0, ly=1, ux=10, uy=13)

        helpers.schem_check(s, add_conn_points=True)
        return s

@public
class Ringosc(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vdd = Pin(pintype=PinType.Inout, align=Orientation.North)
        s.vss = Pin(pintype=PinType.Inout, align=Orientation.South)
        s.y = Pin(pintype=PinType.Out, align=Orientation.East)

        helpers.symbol_place_pins(s, vpadding=2, hpadding=2)
        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.y0 = Net()
        s.y1 = Net()
        s.y2 = Net(pin=self.symbol.y)
        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)

        inv = Inv().symbol
        s.i0 = SchemInstance(inv.portmap(vdd=s.vdd, vss=s.vss, a=s.y2, y=s.y0), pos=Vec2R(4, 2))
        s.i1 = SchemInstance(inv.portmap(vdd=s.vdd, vss=s.vss, a=s.y0, y=s.y1), pos=Vec2R(10, 2))
        s.i2 = SchemInstance(inv.portmap(vdd=s.vdd, vss=s.vss, a=s.y1, y=s.y2), pos=Vec2R(16, 2))
        s.vdd % SchemPort(pos=Vec2R(2, 7), align=Orientation.East)
        s.vss % SchemPort(pos=Vec2R(2, 1), align=Orientation.East)
        s.y2 % SchemPort(pos=Vec2R(22, 4), align=Orientation.West)
        
        s.outline = Rect4R(lx=0, ly=0, ux=24, uy=8)

        s.y0 % SchemWire(vertices=[s.i0.pos+inv.y.pos, s.i1.pos+inv.a.pos])
        s.y1 % SchemWire(vertices=[s.i1.pos+inv.y.pos, s.i2.pos+inv.a.pos])
        s.y2 % SchemWire(vertices=[s.i2.pos+inv.y.pos, Vec2R(21, 4), Vec2R(22, 4)])
        s.y2 % SchemWire(vertices=[Vec2R(21, 4), Vec2R(21, 8), Vec2R(3, 8), Vec2R(3, 4), s.i0.pos+inv.a.pos])

        s.vss % SchemWire(vertices=[Vec2R(2, 1), Vec2R(6, 1), Vec2R(12, 1), Vec2R(18, 1), Vec2R(18, 2)])
        s.vss % SchemWire(vertices=[Vec2R(6, 1), Vec2R(6, 2)])
        s.vss % SchemWire(vertices=[Vec2R(12, 1), Vec2R(12, 2)])

        s.vdd % SchemWire(vertices=[Vec2R(2, 7), Vec2R(6, 7), Vec2R(12, 7), Vec2R(18, 7), Vec2R(18, 6)])
        s.vdd % SchemWire(vertices=[Vec2R(6, 7), Vec2R(6, 6)])
        s.vdd % SchemWire(vertices=[Vec2R(12, 7), Vec2R(12, 6)])

        helpers.schem_check(s, add_conn_points=True)
        return s

@public
class And2(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vdd = Pin(pos=Vec2R(2.5, 5), pintype=PinType.Inout, align=Orientation.North)
        s.vss = Pin(pos=Vec2R(2.5, 0), pintype=PinType.Inout, align=Orientation.South)
        s.a = Pin(pos=Vec2R(0, 3), pintype=PinType.In, align=Orientation.West)
        s.b = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=Orientation.West)
        s.y = Pin(pos=Vec2R(5, 2.5), pintype=PinType.Out, align=Orientation.East)

        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1, 2)])
        s % SymbolPoly(vertices=[Vec2R(0, 3), Vec2R(1, 3)])
        s % SymbolPoly(vertices=[Vec2R(4, 2.5), Vec2R(5, 2.5)])
        s % SymbolPoly(vertices=[Vec2R(2.75, 1.25), Vec2R(1, 1.25), Vec2R(1, 3.75), Vec2R(2.75, 3.75)])
        s % SymbolArc(pos=Vec2R(2.75, 2.5), radius=R(1.25), angle_start=R(-0.25), angle_end=R(0.25))
        s.outline = Rect4R(lx=0, ly=0, ux=5, uy=5)

        return s

@public
class Or2(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vdd = Pin(pos=Vec2R(2.5, 5), pintype=PinType.Inout, align=Orientation.North)
        s.vss = Pin(pos=Vec2R(2.5, 0), pintype=PinType.Inout, align=Orientation.South)
        s.a = Pin(pos=Vec2R(0, 3), pintype=PinType.In, align=Orientation.West)
        s.b = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=Orientation.West)
        s.y = Pin(pos=Vec2R(5, 2.5), pintype=PinType.Out, align=Orientation.East)

        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1.3, 2)])
        s % SymbolPoly(vertices=[Vec2R(0, 3), Vec2R(1.3, 3)])
        s % SymbolPoly(vertices=[Vec2R(4, 2.5), Vec2R(5, 2.5)])
        s % SymbolPoly(vertices=[Vec2R(1, 3.75), Vec2R(1.95, 3.75)])
        s % SymbolPoly(vertices=[Vec2R(1, 1.25), Vec2R(1.95, 1.25)])
        s % SymbolArc(pos=Vec2R(-1.02, 2.5), radius=R(2.4), angle_start=R(-0.085), angle_end=R(0.085))
        s % SymbolArc(pos=Vec2R(1.95, 1.35), radius=R(2.4), angle_start=R(0.08), angle_end=R(0.25))
        s % SymbolArc(pos=Vec2R(1.95, 3.65), radius=R(2.4), angle_start=R(-0.25), angle_end=R(-0.08))
        s.outline = Rect4R(lx=0, ly=0, ux=5, uy=5)

        return s
