# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
from public import public

from ..core import *
from .. import helpers
from ..ord1.implicit_processing import schematic_routing
from . import generic_mos

_MODULE_DIR = Path(__file__).parent
_PROJECT_ROOT = _MODULE_DIR.parent.parent
_SKY130_RELATIVE_MODEL_PATH = "libs.tech/ngspice/corners/tt.spice"

env_var_path = os.getenv("ORDEC_PDK_SKY130A")

if env_var_path:
    _SKY130_MODEL_FULL_PATH = (Path(env_var_path) / _SKY130_RELATIVE_MODEL_PATH).resolve()
else:
    _SKY130_MODEL_FULL_PATH = (_PROJECT_ROOT / "sky130A" / _SKY130_RELATIVE_MODEL_PATH).resolve()


if not _SKY130_MODEL_FULL_PATH.is_file():
    print(f"WARNING: Sky130 model file not found at expected path derived from project structure: {_SKY130_MODEL_FULL_PATH}")
    print(f"Ensure the files exist, or set the enviromental variable ORDEC_PDK_SKY130A")


def setup_sky(netlister):
    netlister.add(".include",f"\"{_SKY130_MODEL_FULL_PATH}\"")
    netlister.add(".param","mc_mm_switch=0")

class Mos(Cell):
    l = Parameter(R) #: Length
    w = Parameter(R) #: Width
    nf = Parameter(int, default=1) #: Number of fingers
    ad = Parameter(R, default=R(0)) #: Drain area
    as_ = Parameter(R, default=R(0)) #: Source area; underscore added because 'as' is keyword in Python
    pd = Parameter(R, default=R(0)) #: Drain perimeter
    ps = Parameter(R, default=R(0)) #: Source perimeter
    nrd = Parameter(R, default=R(0)) #: Number of squares in drain
    nrs = Parameter(R, default=R(0)) #: Number of squares in source
    sa = Parameter(R, default=R(0)) #: Distance between OD edge to Poly
    sb = Parameter(R, default=R(0)) #: Distance between OD edge to Poly (other side)
    sd = Parameter(R, default=R(0)) #: Distance between neighboring fingers

    def netlist_ngspice(self, netlister, inst, schematic):
        netlister.require_setup(setup_sky)
        pins = [inst.symbol.d, inst.symbol.g, inst.symbol.s, inst.symbol.b]
        netlister.add(
            netlister.name_obj(inst, schematic, prefix="x"),
            netlister.portmap(inst, pins),
            self.model_name,
            *helpers.spice_params({
                # sky130 uses ".option scale=1.0u"
                'l': self.l * R('1e6'), 
                'w': self.w * R('1e6'),
                # how do the other parameters need to be scaled?
                'nf': self.nf,
                'ad': self.ad,
                'as': self.as_,
                'pd': self.pd,
                'ps': self.ps,
                'nrd': self.nrd,
                'nrs': self.nrs,
                'sa': self.sa,
                'sb': self.sb,
                'sd': self.sd,
            }))

@public
class Nmos(Mos, generic_mos.Nmos):
    model_name = "sky130_fd_pr__nfet_01v8"

@public
class Pmos(Mos, generic_mos.Pmos):
    model_name = "sky130_fd_pr__pfet_01v8"

@public
class Inv(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        # Define pins for the inverter
        s.vdd = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)
        s.vss = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.a = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=Orientation.West)
        s.y = Pin(pos=Vec2R(4, 2), pintype=PinType.Out, align=Orientation.East)

        # Draw the inverter symbol
        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1, 2)])  # Input line
        s % SymbolPoly(vertices=[Vec2R(3.25, 2), Vec2R(4, 2)])  # Output line
        s % SymbolPoly(vertices=[Vec2R(1, 1), Vec2R(1, 3), Vec2R(2.75, 2), Vec2R(1, 1)])  # Triangle
        s % SymbolArc(pos=Vec2R(3, 2), radius=R(0.25))  # Output bubble

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)

        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)
        s.a = Net(pin=self.symbol.a)
        s.y = Net(pin=self.symbol.y)
        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)

        nmos_params = {
            "l": R("0.15u"),
            "w": R("0.495u"),
            "as_": R("0.131175"),
            "ad": R("0.131175"),
            "ps": R("1.52"),
            "pd": R("1.52"),
        }
        nmos = Nmos(**nmos_params).symbol
        pmos_params = {
            "l": R("0.15u"),
            "w": R("0.99u"),
            "as_": R("0.26235"),
            "ad": R("0.26235"),
            "ps": R("2.51"),
            "pd": R("2.51"),
        }
        pmos = Pmos(**pmos_params).symbol

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
        s = Symbol(cell=self, symbol=self.symbol)

        s.y0 = Net()
        s.y1 = Net()
        s.y2 = Net()
        s.vdd = Net()
        s.vss = Net()

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
