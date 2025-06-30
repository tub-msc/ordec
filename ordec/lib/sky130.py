# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..base import *
from .. import helpers
from . import Nmos, Pmos
from ..parser.implicit_processing import schematic_routing
from pathlib import Path
_MODULE_DIR = Path(__file__).parent
_PROJECT_ROOT = _MODULE_DIR.parent.parent
_SKY130_MODEL_PATH_STR = "sky130A/libs.tech/ngspice/corners/tt.spice"
_SKY130_MODEL_FULL_PATH = (_PROJECT_ROOT / _SKY130_MODEL_PATH_STR).resolve()


if not _SKY130_MODEL_FULL_PATH.is_file():
    print(f"WARNING: Sky130 model file not found at expected path derived from project structure: {_SKY130_MODEL_FULL_PATH}")
    print(f"Ensure the path '{_SKY130_MODEL_PATH_STR}' exists relative to the project root '{_PROJECT_ROOT}' and models are downloaded.")

class NmosSky130(Nmos):
    @staticmethod
    def transistorTechnology() -> str:
        """Returns the resolved, absolute path to the Sky130 TT model file."""
        if not _SKY130_MODEL_FULL_PATH.is_file():
            raise FileNotFoundError(f"Sky130 model file missing: {_SKY130_MODEL_FULL_PATH}")
        return str(_SKY130_MODEL_FULL_PATH)

    @staticmethod
    def model_name() -> str:
        return "sky130_fd_pr__nfet_01v8"

    @staticmethod
    def add_to_circuit(scircuit, component):
        ports = component.portmap.copy()
        for pin, node in ports.items():
            if isinstance(node, str) and 'gnd' in node:
                ports[pin] = scircuit.gnd

        params = component.params.copy()

        scircuit.X(
            component.name,  
            NmosSky130.model_name(),  
            *[ports['d'], ports['g'], ports['s'], ports['b']],  # Ports: drain, gate, source, bulk
            **params 
        )

    @staticmethod
    def circuit_global(circuit):
        circuit.include(NmosSky130.transistorTechnology())
        circuit.parameter("mc_mm_switch", 0)
        
class PmosSky130(Pmos):
    @staticmethod
    def transistorTechnology() -> str:
        """Returns the resolved, absolute path to the Sky130 TT model file."""
        if not _SKY130_MODEL_FULL_PATH.is_file():
            raise FileNotFoundError(f"Sky130 model file missing: {_SKY130_MODEL_FULL_PATH}")
        return str(_SKY130_MODEL_FULL_PATH)

    @staticmethod
    def model_name() -> str:
        return "sky130_fd_pr__pfet_01v8"

    @staticmethod
    def add_to_circuit(scircuit, component):

        ports = component.portmap.copy()
        for pin, node in ports.items():
            if isinstance(node, str) and 'gnd' in node:
                ports[pin] = scircuit.gnd
        params = component.params.copy()

        scircuit.X(
            component.name,
            PmosSky130.model_name(), 
            *[ports['d'], ports['g'], ports['s'], ports['b']],  # Ports: drain, gate, source, bulk
            **params  
        )

    @staticmethod
    def circuit_global(circuit):
        circuit.include(PmosSky130.transistorTechnology())
        circuit.parameter("mc_mm_switch", 0)

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
        # Create nets for internal connections
        node.a = Net()
        node.y = Net()
        node.vdd = Net()
        node.vss = Net()
        node.ref = self.symbol
       #l=0.15  w=0.99  as=0.26235  ad=0.26235  ps=2.51   pd=2.51

        nmos_params = {
            "l": "0.15",
            "w": "0.495",
            "as": "0.131175",
            "ad": "0.131175",
            "ps": "1.52",
            "pd": "1.52"
        }
        nmos = NmosSky130(**nmos_params).symbol
        #l=0.15  w=0.495 as=0.131175 ad=0.131175 ps=1.52   pd=1.52
        pmos_params = {
            "l": "0.15",
            "w": "0.99",
            "as": "0.26235",
            "ad": "0.26235",
            "ps": "2.51",
            "pd": "2.51"
        }
        pmos = PmosSky130(**pmos_params).symbol

        # Place NMOS and PMOS transistors in the schematic
        node.nmos = SchemInstance(
            pos=Vec2R(x=3, y=2),  # Position of NMOS
            ref=nmos,  # NMOS symbol
            portmap={
                nmos.d: node.y,  # Drain connected to output
                nmos.g: node.a,  # Gate connected to input
                nmos.s: node.vss,  # Source connected to ground
                nmos.b: node.vss  # Bulk connected to ground
            }
        )

        node.pmos = SchemInstance(
            pos=Vec2R(x=3, y=8),  # Position of PMOS
            ref=pmos,  # PMOS symbol
            portmap={
                pmos.d: node.y,  # Drain connected to output
                pmos.g: node.a,  # Gate connected to input
                pmos.s: node.vdd,  # Source connected to Vdd
                pmos.b: node.vdd  # Bulk connected to Vdd
            }
        )

        # Connect pins to nets
        node.port_vdd = SchemPort(
            pos=Vec2R(x=1, y=13), align=Orientation.East, ref=self.symbol.vdd, net=node.vdd
        )
        node.port_vss = SchemPort(
            pos=Vec2R(x=2, y=1), align=Orientation.East, ref=self.symbol.vss, net=node.vss
        )
        node.port_a = SchemPort(
            pos=Vec2R(x=1, y=7), align=Orientation.East, ref=self.symbol.a, net=node.a
        )
        node.port_y = SchemPort(
            pos=Vec2R(x=9, y=7), align=Orientation.West, ref=self.symbol.y, net=node.y
        )

        # Draw connections
        #node.vss % SchemPoly(vertices=[node.port_vss.pos, Vec2R(x=5, y=1), Vec2R(x=8, y=1), node.nmos.pos + nmos.s.pos])
        #node.vdd % SchemPoly(vertices=[node.port_vdd.pos, Vec2R(x=5, y=13), Vec2R(x=8, y=13), node.pmos.pos + pmos.s.pos])
        #node.a % SchemPoly(vertices=[node.port_a.pos, node.port_a.pos + Vec2R(x=1, y=0), node.nmos.pos + nmos.g.pos, node.pmos.pos + pmos.g.pos])
        #node.y % SchemPoly(vertices=[node.nmos.pos + nmos.d.pos, Vec2R(x=5, y=7), node.pmos.pos + pmos.d.pos, node.port_y.pos])
        asd=[0,0]
        schematic_routing(node,asd)
        helpers.schem_check(node, add_conn_points=True)
        # Add outline
        node.outline = Rect4R(lx=0, ly=1, ux=asd[0], uy=asd[1])
