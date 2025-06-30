# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..core import *
from .. import helpers
#from . import Nmos, Pmos
from ..parser.implicit_processing import schematic_routing
#from .. import Cell, Vec2R, Rect4R, Pin, PinArray, PinStruct, Symbol, Schematic, PinType, Rational as R, SchemPoly, SchemArc, SchemRect, SchemInstance, SchemPort, Net, Orientation, SchemConnPoint, SchemTapPoint, generate, helpers
from . import generic_mos
from pathlib import Path
_MODULE_DIR = Path(__file__).parent
_PROJECT_ROOT = _MODULE_DIR.parent.parent
_SKY130_MODEL_PATH_STR = "sky130A/libs.tech/ngspice/corners/tt.spice"
_SKY130_MODEL_FULL_PATH = (_PROJECT_ROOT / _SKY130_MODEL_PATH_STR).resolve()


if not _SKY130_MODEL_FULL_PATH.is_file():
    print(f"WARNING: Sky130 model file not found at expected path derived from project structure: {_SKY130_MODEL_FULL_PATH}")
    print(f"Ensure the path '{_SKY130_MODEL_PATH_STR}' exists relative to the project root '{_PROJECT_ROOT}' and models are downloaded.")


def setup_sky(netlister):


    netlister.add(".include",f"\"{_SKY130_MODEL_FULL_PATH}\"")
    netlister.add(".param","mc_mm_switch=0")

def params_to_spice(params, allowed_keys=('l', 'w', 'ad', 'as', 'm',"pd","ps")):
    spice_params = []
    for k, v in params.items():
        if k not in allowed_keys:
            continue
        
        scale_factor = {'w':1e9, 'l':1e9}
        if isinstance(v, R):
            v = (v * scale_factor.get(k, 1)).compat_str()
        spice_params.append(f"{k}={v}")
    return spice_params

class Nmos(generic_mos.Nmos):
    @staticmethod
    def model_name() -> str:
        return "sky130_fd_pr__nfet_01v8"
    def netlist_ngspice(self, netlister, inst, schematic):
        netlister.require_setup(setup_sky)
        pins = [inst.ref.d, inst.ref.g, inst.ref.s, inst.ref.b]
        #netlister.add(netlister.name_obj(inst, schematic, prefix="m"), netlister.portmap(inst, pins), 'nmosgeneric', *params_to_spice(self.params))
        netlister.add(netlister.name_obj(inst, schematic, prefix="x"), netlister.portmap(inst, pins), self.model_name(), *params_to_spice(self.params))

class Pmos(generic_mos.Pmos):
    def netlist_ngspice(self, netlister, inst, schematic):
        netlister.require_setup(setup_sky)
        pins = [inst.ref.d, inst.ref.g, inst.ref.s, inst.ref.b]
        netlister.add(netlister.name_obj(inst, schematic, prefix="x"), netlister.portmap(inst, pins), 'sky130_fd_pr__pfet_01v8', *params_to_spice(self.params))
        #netlister.add(netlister.name_obj(inst, schematic, prefix="m"), netlister.portmap(inst, pins), 'pmosgeneric', *params_to_spice(self.params))

class Inv(Cell):
    @generate(Symbol)
    def symbol(self, node):
        # Define pins for the inverter
        node.vdd = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        node.vss = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.a = Pin(pos=Vec2R(x=0, y=2), pintype=PinType.In, align=Orientation.West)
        node.y = Pin(pos=Vec2R(x=4, y=2), pintype=PinType.Out, align=Orientation.East)

        # Draw the inverter symbol
        node % SchemPoly(vertices=[Vec2R(x=0, y=2), Vec2R(x=1, y=2)])  # Input line
        node % SchemPoly(vertices=[Vec2R(x=3.25, y=2), Vec2R(x=4, y=2)])  # Output line
        node % SchemPoly(vertices=[Vec2R(x=1, y=1), Vec2R(x=1, y=3), Vec2R(x=2.75, y=2), Vec2R(x=1, y=1)])  # Triangle
        node % SymbolArc(pos=Vec2R(x=3, y=2), radius=R(0.25))  # Output bubble

        # Outline
        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)

    @generate(Schematic)
    def schematic(self, node):
        node.a = Net()
        node.y = Net()
        node.vdd = Net()
        node.vss = Net()

        nmos_params = {
            "l": "0.15",
            "w": "0.495",
            "as": "0.131175",
            "ad": "0.131175",
            "ps": "1.52",
            "pd": "1.52"
        }
        nmos = Nmos(**nmos_params).symbol
        pmos_params = {
            "l": "0.15",
            "w": "0.99",
            "as": "0.26235",
            "ad": "0.26235",
            "ps": "2.51",
            "pd": "2.51"
        }
        pmos = Pmos(**pmos_params).symbol

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
        node.outline = Rect4R(lx=0, ly=1, ux=asd[0], uy=asd[1])


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
