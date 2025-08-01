# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec import (
    Cell,
    Vec2R,
    Rect4R,
    Pin,
    PinArray,
    PinStruct,
    Symbol,
    Schematic,
    PinType,
    Rational as R,
    SchemPoly,
    SymbolArc,
    SchemRect,
    SchemInstance,
    SchemPort,
    Net,
    NetArray,
    NetStruct,
    Orientation,
    SchemConnPoint,
    SchemTapPoint,
)
from ordec.lib import (
    And2,
    Or2,
    Ringosc,
    Vdc,
    Res,
    Cap,
    Ind,
    SinusoidalVoltageSource,
    PulseVoltageSource,
    Gnd,
)
from IPython.core.display import HTML
from pyrsistent import PMap, field
from ordec import helpers
from ordec.sim import create_circuit_from_dict, get_portmaps
from ordec.lib.sky130 import NmosSky130, PmosSky130, Inv
from ordec.ord1.implicit_processing import schematic_routing


class TBMosfetLoad(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.gnd = Net()
        s.vin = Net()
        s.vout = Net()
        nmos_params = {"l": "2", "w": "2"}
        nmos = NmosSky130(**nmos_params).symbol
        s.mosfet = SchemInstance(
            pos=Vec2R(10, 5),
            ref=nmos,
            portmap={
                nmos.d: s.vout,
                nmos.g: s.vin,
                nmos.s: s.gnd,
                nmos.b: s.gnd,
            },
        )

        resistor_params = {"R": R("9e3")}
        resistor = Res(**resistor_params).symbol
        s.rl = SchemInstance(
            pos=Vec2R(10, 10),
            ref=resistor,
            portmap={resistor.p: s.vdd, resistor.m: s.vout},
        )

        capacitor_params = {"C": R("20e-12")}
        capacitor = Cap(**capacitor_params).symbol
        s.cl = SchemInstance(
            pos=Vec2R(15, 5),
            ref=capacitor,
            portmap={capacitor.p: s.vout, capacitor.m: s.gnd},
        )

        vdc_vdd_params = {"V": R("1.8")}
        vdc_vdd = Vdc(**vdc_vdd_params).symbol
        s.vdd_source = SchemInstance(
            pos=Vec2R(5, 15),
            ref=vdc_vdd,
            portmap={vdc_vdd.p: s.vdd, vdc_vdd.m: s.gnd},
        )

        sin_params = {
            "offset": R("0.52"),
            "amplitude": R("1e-3"),
            "frequency": R("1e3"),
            "delay": R("0"),
        }
        sin_source = SinusoidalVoltageSource(**sin_params).symbol
        s.vac = SchemInstance(
            pos=Vec2R(2, 5),
            ref=sin_source,
            portmap={
                sin_source.p: s.vin,
                sin_source.m: s.gnd,
            },
        )
        s.outline = s % SchemRect(pos=Rect4R(lx=0, ly=0, ux=25, uy=20))
        
        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)
        return s

class TBInv(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.input_node = Net()
        s.vdd = Net()
        s.gnd = Net()
        s.out = Net()

        pulse_params = {
            "initial_value": R("0"),
            "pulsed_value": R("1.8"),
            "delay_time": R("0"),
            "rise_time": R("200e-12"),
            "fall_time": R("100e-12"),
            "pulse_width": R("1e-9"),
            "period": R("2e-9"),
        }
        pulse_source = PulseVoltageSource(**pulse_params).symbol
        s.pulse = SchemInstance(
            pos=Vec2R(2, 5),
            ref=pulse_source,
            portmap={pulse_source.p: s.input_node, pulse_source.m: s.gnd},
        )

        vdc_inst = Vdc(V=R("1.8")).symbol

        s.vdc = SchemInstance(
            pos=Vec2R(3, 10),
            ref=vdc_inst,
            portmap={vdc_inst.m: s.gnd, vdc_inst.p: s.vdd},
        )

        inv = Inv().symbol
        s.inv = SchemInstance(
            pos=Vec2R(8, 5),
            ref=inv,
            portmap={
                inv.a: s.input_node,
                inv.vdd: s.vdd,
                inv.vss: s.gnd,
                inv.y: s.out,
            },
        )
        s.default_ground = s.gnd

        gnd_inst = Gnd().symbol
        s.gnd_inst = SchemInstance(
            pos=Vec2R(12, 16), ref=gnd_inst, portmap={gnd_inst.p: s.gnd}
        )
        s.outline = s % SchemRect(pos=Rect4R(lx=0, ly=2, ux=25, uy=16))

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)
        return s
