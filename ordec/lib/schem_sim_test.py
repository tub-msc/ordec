# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..base import *
from . import Nmos, Pmos, Inv, And2, Or2, Ringosc, Vdc, Res, Cap, Ind, SinusoidalVoltageSource, Gnd, PieceWiseLinearVoltageSource, SinusoidalCurrentSource
from .. import helpers

class TestCell1(Cell):

    @generate(Symbol)
    def symbol(self, node):
        node.a = PinArray()
        node.a[0]=Pin(pintype=PinType.Inout, align=Orientation.South)
        node.a[1]=Pin(pintype=PinType.Inout, align=Orientation.South)
        
        node.b = PinArray()
        node.b[0] = Pin(pintype=PinType.Out, align=Orientation.North)
        node.b[1] = Pin(pintype=PinType.Out, align=Orientation.North)

        helpers.symbol_place_pins(node, vpadding=2, hpadding=2)
    
    @generate(Schematic)
    def schematic(self, node):
        node.a = NetArray()
        node.b = NetArray()
        node.a[0] = Net()
        node.a[1] = Net()
        node.b[0] = Net()
        node.b[1] = Net()

        r_inst = Res(R=R("1000")).symbol
        r_inst2 = Res(R=R("2000")).symbol
        node.res1 = SchemInstance(pos=Vec2R(x=3, y=8), ref=r_inst, portmap={r_inst.p:node.a[0], r_inst.m:node.b[0]})
        node.res2 = SchemInstance(pos=Vec2R(x=10, y=8), ref=r_inst2, portmap={r_inst2.p:node.a[1], r_inst2.m:node.b[1]})
        
        helpers.schem_check(node, add_conn_points=True,add_terminal_taps=True)

        node.outline = Rect4R(lx=3, ly=7, ux=15, uy=13)

class TestCell2(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.mkpath('a')
        node.a.left=Pin(pintype=PinType.Inout, align=Orientation.South)
        node.a.right=Pin(pintype=PinType.Inout, align=Orientation.South)
        
        node.mkpath('b')
        node.b.left = Pin(pintype=PinType.Out, align=Orientation.North)
        node.b.right = Pin(pintype=PinType.Out, align=Orientation.North)

        helpers.symbol_place_pins(node, vpadding=2, hpadding=2)
    
    @generate(Schematic)
    def schematic(self, node):
        node.mkpath('a')
        node.mkpath('b')
        node.a.left = Net()
        node.a.right = Net()
        node.b.left = Net()
        node.b.right = Net()

        r_inst = Res(R=R("1000")).symbol
        r_inst2 = Res(R=R("2000")).symbol
        node.res1 = SchemInstance(pos=Vec2R(x=3, y=8), ref=r_inst, portmap={r_inst.p:node.a.left, r_inst.m:node.b.left})
        node.res2 = SchemInstance(pos=Vec2R(x=10, y=8), ref=r_inst2, portmap={r_inst2.p:node.a.right, r_inst2.m:node.b.right})
        
        helpers.schem_check(node, add_conn_points=True,add_terminal_taps=True)

        node.outline = Rect4R(lx=3, ly=5, ux=15, uy=15)

class TestBenchNestedCell(Cell):
    @generate(Schematic)
    def schematic(self, node):
        node.y = Net()
        #node.vdd = Net()
        node.gnd = Net()
        node.k = Net()

        vdc_inst = Vdc(V=R("1")).symbol 
        tb_inst = TestCell1().symbol 
        tb_inst2 = TestCell2().symbol 

        node.vdc = SchemInstance(pos=Vec2R(x=3, y=2), ref=vdc_inst, portmap={vdc_inst.m:node.gnd, vdc_inst.p:node.y})
        node.tb1 = SchemInstance(pos=Vec2R(x=3, y=8), ref=tb_inst, portmap={tb_inst.a[0]:node.y,tb_inst.a[1]:node.y, tb_inst.b[0]:node.k,tb_inst.b[1]:node.k})
        node.tb2 = SchemInstance(pos=Vec2R(x=12, y=8), ref=tb_inst2, portmap={tb_inst2.a.left:node.gnd,tb_inst2.a.right:node.gnd, tb_inst2.b.left:node.k,tb_inst2.b.right:node.k})
        node.default_ground=node.gnd

        gnd_inst = Gnd().symbol
        node.gnd_inst = SchemInstance(pos=Vec2R(x=12, y=16), ref=gnd_inst,portmap={gnd_inst.p:node.gnd})
        helpers.schem_check(node, add_conn_points=True,add_terminal_taps=True)

        node.outline = Rect4R(lx=0, ly=1, ux=25, uy=13)

class LowPassFilterTB(Cell):
    @generate(Schematic)
    def schematic(self, node):
        node.input_node = Net()
        node.gnd = Net()
        node.out = Net()

        # Instantiate SinusoidalVoltageSource
        sinusoidal_params = {
            'offset': R(0),
            'amplitude': R(5),
            'frequency': R(1e3),  # 1 kHz
            'delay': R(0),
            'damping_factor': R(0)
        }
        sinusoidal_source = SinusoidalVoltageSource(**sinusoidal_params).symbol
        node.sinusoidal = SchemInstance(
            pos=Vec2R(x=2, y=5),
            ref=sinusoidal_source,
            portmap={
                sinusoidal_source.p: node.input_node,
                sinusoidal_source.m: node.gnd
            }
        )


        # Instantiate Resistor (R)
        resistor_params = {'R': R(1e3)}  # 1 kOhm
        resistor = Res(**resistor_params).symbol
        node.resistor = SchemInstance(
            pos=Vec2R(x=8, y=5),
            ref=resistor,
            portmap={
                resistor.p: node.input_node,
                resistor.m: node.out
            }
        )

        # Instantiate Capacitor (C)
        capacitor_params = {'C': R(100e-9)}  # 100 nF
        capacitor = Cap(**capacitor_params).symbol
        node.capacitor = SchemInstance(
            pos=Vec2R(x=14, y=5),
            ref=capacitor,
            portmap={
                capacitor.p: node.out,
                capacitor.m: node.gnd
            }
        )

        node.default_ground=node.gnd

        gnd_inst = Gnd().symbol
        node.gnd_inst = SchemInstance(pos=Vec2R(x=12, y=16), ref=gnd_inst,portmap={gnd_inst.p:node.gnd})
        helpers.schem_check(node, add_conn_points=True, add_terminal_taps=True)
        node.outline = Rect4R(lx=0, ly=2, ux=20, uy=12)

class PieceWiseVoltageLinearTB(Cell):
    """
    Testbench for the PieceWiseLinearVoltageSource.
    Connects the PWL source across a resistor to ground.
    Uses string representations for R().
    """
    @generate(Schematic)
    def schematic(self, node):
        node.source_output = Net()
        node.gnd = Net()

        # (time_seconds, voltage_volts)
        pwl_points = [
            (R("0"), R("0")),  
            (R("1m"), R("1")), 
            (R("2m"), R("1")), 
            (R("3m"), R("0")), 
            (R("4m"), R("0"))  
        ]

        pwl_source_ref = PieceWiseLinearVoltageSource(V=pwl_points).symbol
        node.pwl_source = SchemInstance(
            pos=Vec2R(x=2, y=5),
            ref=pwl_source_ref,
            portmap={
                pwl_source_ref.p: node.source_output, 
                pwl_source_ref.m: node.gnd
            }
        )

        resistor_ref = Res(R=R("1k")).symbol
        node.load_resistor = SchemInstance(
            pos=Vec2R(x=8, y=5),
            ref=resistor_ref,
            portmap={
                resistor_ref.p: node.source_output, 
                resistor_ref.m: node.gnd
            }
        )

        node.default_ground = node.gnd

        gnd_inst = Gnd().symbol
        node.gnd_inst = SchemInstance(pos=Vec2R(x=12, y=16), ref=gnd_inst,portmap={gnd_inst.p:node.gnd})

        helpers.schem_check(node, add_conn_points=True, add_terminal_taps=True)

        node.outline = Rect4R(lx=0, ly=2, ux=14, uy=9)

class TestSineCurrentSourceTB(Cell):
    """Testbench for the SinusoidalCurrentSource."""
    @generate(Schematic)
    def schematic(self, node):
        node.gnd = Net()
        node.load_node = Net()

        sine_current_params = {
            'offset': R(0),
            'amplitude': R("1m"), # 1mA amplitude
            'frequency': R("1k"), # 1kHz frequency
            'delay': R(0)
        }
        sine_current_ref = SinusoidalCurrentSource(**sine_current_params).symbol
        node.sine_current = SchemInstance(
            pos=Vec2R(x=2, y=5),
            ref=sine_current_ref,
            portmap={
                sine_current_ref.p: node.load_node, # Current flows m -> p
                sine_current_ref.m: node.gnd
            }
        )

        sine_load_ref = Res(R=R("100")).symbol # 100 Ohm load
        node.sine_load = SchemInstance(
            pos=Vec2R(x=8, y=5),
            ref=sine_load_ref,
            portmap={
                sine_load_ref.p: node.load_node,
                sine_load_ref.m: node.gnd
            }
        )

        node.default_ground = node.gnd
        gnd_inst_ref = Gnd().symbol
        node.gnd_inst = SchemInstance(pos=Vec2R(x=5, y=0), ref=gnd_inst_ref, portmap={gnd_inst_ref.p: node.gnd})

        helpers.schem_check(node, add_conn_points=True, add_terminal_taps=True)
        node.outline = Rect4R(lx=0, ly=0, ux=12, uy=10)
