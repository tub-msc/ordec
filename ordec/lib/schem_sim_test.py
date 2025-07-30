# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..core import *
from . import Nmos, Pmos, Inv, And2, Or2, Ringosc, Vdc, Res, Cap, Ind, SinusoidalVoltageSource, Gnd, PieceWiseLinearVoltageSource, SinusoidalCurrentSource
from .. import helpers

class TestCell1(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.a = PinArray()
        s.a[0]=Pin(pintype=PinType.Inout, align=Orientation.South)
        s.a[1]=Pin(pintype=PinType.Inout, align=Orientation.South)
        
        s.b = PinArray()
        s.b[0] = Pin(pintype=PinType.Out, align=Orientation.North)
        s.b[1] = Pin(pintype=PinType.Out, align=Orientation.North)

        helpers.symbol_place_pins(s, vpadding=2, hpadding=2)
        return s
    
    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.a = NetArray()
        s.b = NetArray()
        s.a[0] = Net()
        s.a[1] = Net()
        s.b[0] = Net()
        s.b[1] = Net()

        r_inst = Res(R=R("1000")).symbol
        r_inst2 = Res(R=R("2000")).symbol
        s.res1 = SchemInstance(pos=Vec2R(3, 8), ref=r_inst, portmap={r_inst.p:s.a[0], r_inst.m:s.b[0]})
        s.res2 = SchemInstance(pos=Vec2R(10, 8), ref=r_inst2, portmap={r_inst2.p:s.a[1], r_inst2.m:s.b[1]})
        
        s.outline = Rect4R(lx=3, ly=7, ux=15, uy=13)

        helpers.schem_check(s, add_conn_points=True,add_terminal_taps=True)
        return s

class TestCell2(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.mkpath('a')
        s.a.left=Pin(pintype=PinType.Inout, align=Orientation.South)
        s.a.right=Pin(pintype=PinType.Inout, align=Orientation.South)
        
        s.mkpath('b')
        s.b.left = Pin(pintype=PinType.Out, align=Orientation.North)
        s.b.right = Pin(pintype=PinType.Out, align=Orientation.North)

        helpers.symbol_place_pins(s, vpadding=2, hpadding=2)
        return s
    
    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.mkpath('a')
        s.mkpath('b')
        s.a.left = Net()
        s.a.right = Net()
        s.b.left = Net()
        s.b.right = Net()

        r_inst = Res(R=R("1000")).symbol
        r_inst2 = Res(R=R("2000")).symbol
        s.res1 = SchemInstance(pos=Vec2R(3, 8), ref=r_inst, portmap={r_inst.p:s.a.left, r_inst.m:s.b.left})
        s.res2 = SchemInstance(pos=Vec2R(10, 8), ref=r_inst2, portmap={r_inst2.p:s.a.right, r_inst2.m:s.b.right})
        
        s.outline = Rect4R(lx=3, ly=5, ux=15, uy=15)

        helpers.schem_check(s, add_conn_points=True,add_terminal_taps=True)
        return s

class TestBenchNestedCell(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.y = Net()
        #s.vdd = Net()
        s.gnd = Net()
        s.k = Net()

        vdc_inst = Vdc(V=R("1")).symbol 
        tb_inst = TestCell1().symbol 
        tb_inst2 = TestCell2().symbol 

        s.vdc = SchemInstance(pos=Vec2R(3, 2), ref=vdc_inst, portmap={vdc_inst.m:s.gnd, vdc_inst.p:s.y})
        s.tb1 = SchemInstance(pos=Vec2R(3, 8), ref=tb_inst, portmap={tb_inst.a[0]:s.y,tb_inst.a[1]:s.y, tb_inst.b[0]:s.k,tb_inst.b[1]:s.k})
        s.tb2 = SchemInstance(pos=Vec2R(12, 8), ref=tb_inst2, portmap={tb_inst2.a.left:s.gnd,tb_inst2.a.right:s.gnd, tb_inst2.b.left:s.k,tb_inst2.b.right:s.k})
        s.default_ground=s.gnd

        gnd_inst = Gnd().symbol
        s.gnd_inst = SchemInstance(pos=Vec2R(12, 16), ref=gnd_inst,portmap={gnd_inst.p:s.gnd})
        helpers.schem_check(s, add_conn_points=True,add_terminal_taps=True)

        s.outline = Rect4R(lx=0, ly=1, ux=25, uy=13)

        return s

class LowPassFilterTB(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.input_node = Net()
        s.gnd = Net()
        s.out = Net()

        # Instantiate SinusoidalVoltageSource
        sinusoidal_params = {
            'offset': R(0),
            'amplitude': R(5),
            'frequency': R(1e3),  # 1 kHz
            'delay': R(0),
            'damping_factor': R(0)
        }
        sinusoidal_source = SinusoidalVoltageSource(**sinusoidal_params).symbol
        s.sinusoidal = SchemInstance(
            pos=Vec2R(2, 5),
            ref=sinusoidal_source,
            portmap={
                sinusoidal_source.p: s.input_node,
                sinusoidal_source.m: s.gnd
            }
        )


        # Instantiate Resistor (R)
        resistor_params = {'R': R(1e3)}  # 1 kOhm
        resistor = Res(**resistor_params).symbol
        s.resistor = SchemInstance(
            pos=Vec2R(8, 5),
            ref=resistor,
            portmap={
                resistor.p: s.input_node,
                resistor.m: s.out
            }
        )

        # Instantiate Capacitor (C)
        capacitor_params = {'C': R(100e-9)}  # 100 nF
        capacitor = Cap(**capacitor_params).symbol
        s.capacitor = SchemInstance(
            pos=Vec2R(14, 5),
            ref=capacitor,
            portmap={
                capacitor.p: s.out,
                capacitor.m: s.gnd
            }
        )

        s.default_ground=s.gnd

        gnd_inst = Gnd().symbol
        s.gnd_inst = SchemInstance(pos=Vec2R(12, 16), ref=gnd_inst,portmap={gnd_inst.p:s.gnd})
        s.outline = Rect4R(lx=0, ly=2, ux=20, uy=12)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)
        return s

class PieceWiseVoltageLinearTB(Cell):
    """
    Testbench for the PieceWiseLinearVoltageSource.
    Connects the PWL source across a resistor to ground.
    Uses string representations for R().
    """
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.source_output = Net()
        s.gnd = Net()

        # (time_seconds, voltage_volts)
        pwl_points = [
            (R("0"), R("0")),  
            (R("1m"), R("1")), 
            (R("2m"), R("1")), 
            (R("3m"), R("0")), 
            (R("4m"), R("0"))  
        ]

        pwl_source_ref = PieceWiseLinearVoltageSource(V=pwl_points).symbol
        s.pwl_source = SchemInstance(
            pos=Vec2R(2, 5),
            ref=pwl_source_ref,
            portmap={
                pwl_source_ref.p: s.source_output, 
                pwl_source_ref.m: s.gnd
            }
        )

        resistor_ref = Res(R=R("1k")).symbol
        s.load_resistor = SchemInstance(
            pos=Vec2R(8, 5),
            ref=resistor_ref,
            portmap={
                resistor_ref.p: s.source_output, 
                resistor_ref.m: s.gnd
            }
        )

        s.default_ground = s.gnd

        gnd_inst = Gnd().symbol
        s.gnd_inst = SchemInstance(pos=Vec2R(12, 16), ref=gnd_inst,portmap={gnd_inst.p:s.gnd})

        s.outline = Rect4R(lx=0, ly=2, ux=14, uy=9)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)
        return s

class TestSineCurrentSourceTB(Cell):
    """Testbench for the SinusoidalCurrentSource."""
    @generate
    def schematic(self):
        s.gnd = Net()
        s.load_node = Net()

        sine_current_params = {
            'offset': R(0),
            'amplitude': R("1m"), # 1mA amplitude
            'frequency': R("1k"), # 1kHz frequency
            'delay': R(0)
        }
        sine_current_ref = SinusoidalCurrentSource(**sine_current_params).symbol
        s.sine_current = SchemInstance(
            pos=Vec2R(2, 5),
            ref=sine_current_ref,
            portmap={
                sine_current_ref.p: s.load_node, # Current flows m -> p
                sine_current_ref.m: s.gnd
            }
        )

        sine_load_ref = Res(R=R("100")).symbol # 100 Ohm load
        s.sine_load = SchemInstance(
            pos=Vec2R(8, 5),
            ref=sine_load_ref,
            portmap={
                sine_load_ref.p: s.load_node,
                sine_load_ref.m: s.gnd
            }
        )

        s.default_ground = s.gnd
        gnd_inst_ref = Gnd().symbol
        s.gnd_inst = SchemInstance(pos=Vec2R(5, 0), ref=gnd_inst_ref, portmap={gnd_inst_ref.p: s.gnd})

        s.outline = Rect4R(lx=0, ly=0, ux=12, uy=10)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)
        return s
