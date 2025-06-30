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
from ordec.parser.implicit_processing import schematic_routing


class TBMosfetLoad(Cell):
    @generate(Schematic)
    def schematic(self, node):
        node.vdd = Net()
        node.gnd = Net()
        node.vin = Net()
        node.vout = Net()
        nmos_params = {"l": "2", "w": "2"}
        nmos = NmosSky130(**nmos_params).symbol
        node.mosfet = SchemInstance(
            pos=Vec2R(x=10, y=5),
            ref=nmos,
            portmap={
                nmos.d: node.vout,
                nmos.g: node.vin,
                nmos.s: node.gnd,
                nmos.b: node.gnd,
            },
        )

        resistor_params = {"R": R("9e3")}
        resistor = Res(**resistor_params).symbol
        node.rl = SchemInstance(
            pos=Vec2R(x=10, y=10),
            ref=resistor,
            portmap={resistor.p: node.vdd, resistor.m: node.vout},
        )

        capacitor_params = {"C": R("20e-12")}
        capacitor = Cap(**capacitor_params).symbol
        node.cl = SchemInstance(
            pos=Vec2R(x=15, y=5),
            ref=capacitor,
            portmap={capacitor.p: node.vout, capacitor.m: node.gnd},
        )

        vdc_vdd_params = {"V": R("1.8")}
        vdc_vdd = Vdc(**vdc_vdd_params).symbol
        node.vdd_source = SchemInstance(
            pos=Vec2R(x=5, y=15),
            ref=vdc_vdd,
            portmap={vdc_vdd.p: node.vdd, vdc_vdd.m: node.gnd},
        )

        sin_params = {
            "offset": R("0.52"),
            "amplitude": R("1e-3"),
            "frequency": R("1e3"),
            "delay": R("0"),
        }
        sin_source = SinusoidalVoltageSource(**sin_params).symbol
        node.vac = SchemInstance(
            pos=Vec2R(x=2, y=5),
            ref=sin_source,
            portmap={
                sin_source.p: node.vin,
                sin_source.m: node.gnd,
            },
        )
        helpers.schem_check(node, add_conn_points=True, add_terminal_taps=True)
        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=25, uy=20))


class TBInv(Cell):
    @generate(Schematic)
    def schematic(self, node):
        node.input_node = Net()
        node.vdd = Net()
        node.gnd = Net()
        node.out = Net()

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
        node.pulse = SchemInstance(
            pos=Vec2R(x=2, y=5),
            ref=pulse_source,
            portmap={pulse_source.p: node.input_node, pulse_source.m: node.gnd},
        )

        vdc_inst = Vdc(V=R("1.8")).symbol

        node.vdc = SchemInstance(
            pos=Vec2R(x=3, y=10),
            ref=vdc_inst,
            portmap={vdc_inst.m: node.gnd, vdc_inst.p: node.vdd},
        )

        inv = Inv().symbol
        node.inv = SchemInstance(
            pos=Vec2R(x=8, y=5),
            ref=inv,
            portmap={
                inv.a: node.input_node,
                inv.vdd: node.vdd,
                inv.vss: node.gnd,
                inv.y: node.out,
            },
        )
        node.default_ground = node.gnd

        gnd_inst = Gnd().symbol
        node.gnd_inst = SchemInstance(
            pos=Vec2R(x=12, y=16), ref=gnd_inst, portmap={gnd_inst.p: node.gnd}
        )
        helpers.schem_check(node, add_conn_points=True, add_terminal_taps=True)
        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=2, ux=25, uy=16))
