# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass

from ordec.core import *
from ordec.schematic import helpers
from ordec.schematic.routing import schematic_routing
from ordec.sim.sim_hierarchy import HighlevelSim, SimHierarchy
from ordec.sim.ngspice import Ngspice
from ordec.sim.ngspice_common import Quantity, SignalArray
from ordec.lib.base import PulseVoltageSource

from ordec.lib.generic_mos import Or2, Nmos, Pmos, Ringosc, Inv
from ordec.lib.base import Gnd, NoConn, Res, Vdc, Idc, Cap, SinusoidalVoltageSource
from ordec.lib import sky130
from ordec.lib import ihp130

import queue as _queue
import time as _time
import concurrent.futures as _futures

class SimBase(Cell):
    @generate
    def sim_hierarchy(self):
        s = SimHierarchy(cell=self)
        # Build SimHierarchy, but runs no simulations.
        HighlevelSim(self.schematic, s)
        return s

    @generate
    def sim_dc(self):
        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s)
        sim.op()
        return s

    def sim_ac(self, *args, **kwargs):
        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s)
        sim.ac(*args, **kwargs)
        return s

    def sim_tran(self, tstep: R, tstop: R, **kwargs):
        """Run sync transient simulation.

        Args:
            tstep: Time step for the simulation
            tstop: Stop time for the simulation
            enable_savecurrents: If True (default), enables .option savecurrents
        """

        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s, **kwargs)
        sim.tran(tstep, tstop)
        return s

class RcFilterTb(SimBase):
    r = Parameter(R, default=R(1e3))
    c = Parameter(R, default=R(1e-9))

    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.inp = Net()
        s.out = Net()
        s.vss = Net()

        vac = SinusoidalVoltageSource(
            amplitude=R(1), frequency=R(1)
        ).symbol  # frequency is a dummy value
        res = Res(r=self.r).symbol
        cap = Cap(c=self.c).symbol
        gnd = Gnd().symbol

        s.I0 = SchemInstance(gnd.portmap(p=s.vss), pos=Vec2R(0, -4))
        s.I1 = SchemInstance(vac.portmap(p=s.inp, m=s.vss), pos=Vec2R(0, 4))
        s.I2 = SchemInstance(res.portmap(p=s.inp, m=s.out), pos=Vec2R(5, 4))
        s.I3 = SchemInstance(cap.portmap(p=s.out, m=s.vss), pos=Vec2R(10, 4))

        s.inp % SchemWire(vertices=[s.I1.pos + vac.p.pos, s.I2.pos + res.p.pos])
        s.out % SchemWire(vertices=[s.I2.pos + res.m.pos, s.I3.pos + cap.p.pos])

        vss_bus_y = R(-2)
        s.vss % SchemWire(vertices=[Vec2R(2, vss_bus_y), Vec2R(12, vss_bus_y)])
        s.vss % SchemWire(vertices=[s.I0.pos + gnd.p.pos, Vec2R(2, vss_bus_y)])
        s.vss % SchemWire(vertices=[s.I1.pos + vac.m.pos, Vec2R(2, vss_bus_y)])
        s.vss % SchemWire(vertices=[s.I3.pos + cap.m.pos, Vec2R(12, vss_bus_y)])

        helpers.schem_check(s, add_conn_points=True)
        return s


class ResdivFlatTb(SimBase):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.vss = Net()
        s.vdd_ac = Net()
        s.a = Net()
        s.b = Net()

        sym_vdc = Vdc(dc=R(1)).symbol
        sym_vac = SinusoidalVoltageSource(amplitude=R(1), frequency=R("1e6")).symbol
        sym_gnd = Gnd().symbol
        sym_res = Res(r=R(100)).symbol

        s.I0 = SchemInstance(sym_gnd.portmap(p=s.vss), pos=Vec2R(5, 0))
        s.I1 = SchemInstance(sym_vdc.portmap(m=s.vss, p=s.vdd_ac), pos=Vec2R(0, 6))
        s.I1_ac = SchemInstance(sym_vac.portmap(m=s.vdd_ac, p=s.vdd), pos=Vec2R(0, 12))
        s.I2 = SchemInstance(sym_res.portmap(m=s.vss, p=s.a), pos=Vec2R(5, 6))
        s.I3 = SchemInstance(sym_res.portmap(m=s.a, p=s.b), pos=Vec2R(5, 11))
        s.I4 = SchemInstance(sym_res.portmap(m=s.b, p=s.vdd), pos=Vec2R(5, 16))

        s.vss % SchemWire(vertices=[Vec2R(7, 4), Vec2R(7, 5), Vec2R(7, 6)])
        s.vss % SchemWire(vertices=[Vec2R(2, 6), Vec2R(2, 5), Vec2R(7, 5)])
        s.vdd_ac % SchemWire(vertices=[Vec2R(2, 10), Vec2R(2, 12)])
        s.vdd % SchemWire(
            vertices=[Vec2R(2, 16), Vec2R(2, 21), Vec2R(7, 21), Vec2R(7, 20)]
        )
        s.a % SchemWire(vertices=[Vec2R(7, 10), Vec2R(7, 11)])
        s.b % SchemWire(vertices=[Vec2R(7, 15), Vec2R(7, 16)])

        s.outline = Rect4R(lx=0, ly=0, ux=9, uy=21)

        helpers.schem_check(s, add_conn_points=True)

        return s


class ResdivHier2(Cell):
    r = Parameter(R)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.t = Pin(pintype=PinType.Inout, align=Orientation.North)
        s.r = Pin(pintype=PinType.Inout, align=Orientation.East)
        s.b = Pin(pintype=PinType.Inout, align=Orientation.South)
        helpers.symbol_place_pins(s, vpadding=2, hpadding=2)

        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.t = Net(pin=self.symbol.t)
        s.r = Net(pin=self.symbol.r)
        s.b = Net(pin=self.symbol.b)
        s.m = Net()

        s.t % SchemPort(pos=Vec2R(2, 12), align=Orientation.South)
        s.r % SchemPort(pos=Vec2R(10, 6), align=Orientation.West)
        s.b % SchemPort(pos=Vec2R(2, 0), align=Orientation.North)

        sym_res = Res(r=self.r).symbol

        s.I0 = SchemInstance(sym_res.portmap(m=s.b, p=s.m), pos=Vec2R(0, 1))
        s.I1 = SchemInstance(sym_res.portmap(m=s.m, p=s.t), pos=Vec2R(0, 7))
        s.I2 = SchemInstance(sym_res.portmap(m=s.r, p=s.m), pos=Vec2R(9, 4),
            orientation=Orientation.R90)

        s.outline = Rect4R(lx=0, ly=0, ux=10, uy=12)

        s.t % SchemWire(vertices=[Vec2R(2, 12), Vec2R(2, 11)])
        s.b % SchemWire(vertices=[Vec2R(2, 0), Vec2R(2, 1)])
        s.m % SchemWire(vertices=[Vec2R(2, 5), Vec2R(2, 6), Vec2R(2, 7)])
        s.m % SchemWire(vertices=[Vec2R(2, 6), Vec2R(5, 6)])
        s.r % SchemWire(vertices=[Vec2R(9, 6), Vec2R(10, 6)])

        helpers.schem_check(s, add_conn_points=True)
        return s


class ResdivHier1(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        # Use paths to test path hierarchy handling:
        s.mkpath('inputs')
        s.mkpath('outputs')       

        s.inputs.t = Pin(pintype=PinType.Inout, align=Orientation.North)
        s.outputs.r = Pin(pintype=PinType.Inout, align=Orientation.East)
        s.inputs.b = Pin(pintype=PinType.Inout, align=Orientation.South)
        helpers.symbol_place_pins(s, vpadding=2, hpadding=2)

        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.t = Net(pin=self.symbol.inputs.t)
        s.r = Net(pin=self.symbol.outputs.r)
        s.b = Net(pin=self.symbol.inputs.b)

        # Use paths to test path hierarchy handling:
        s.mkpath('sub')
        s.mkpath('sub2')
        s.sub.mkpath('subsub')

        s.tr = Net()
        s.br = Net()
        s.sub.subsub.m = Net()

        s.t % SchemPort(pos=Vec2R(7, 11), align=Orientation.South)
        s.r % SchemPort(pos=Vec2R(15, 5), align=Orientation.West)
        s.b % SchemPort(pos=Vec2R(7, -1), align=Orientation.North)

        sym_1 = ResdivHier2(r=R(100)).symbol
        sym_2 = ResdivHier2(r=R(200)).symbol

        # s % SchemInstance(pos=Vec2R(5, 0), ref=sym_1, portmap={sym_1.t: s.m, sym_1.b:s.gnd, sym_1.r:s.br})
        
        s.I0 = SchemInstance(sym_1.portmap(t=s.sub.subsub.m, b=s.b, r=s.br), pos=Vec2R(5, 0))
        s.I1 = SchemInstance(sym_2.portmap(t=s.t, b=s.sub.subsub.m, r=s.tr), pos=Vec2R(5, 6))
        s.sub2.I2 = SchemInstance(sym_1.portmap(t=s.tr, b=s.br, r=s.r), pos=Vec2R(10, 3))

        s.outline = Rect4R(lx=5, ly=-1, ux=15, uy=12)

        s.b % SchemWire(vertices=[Vec2R(7, -1), Vec2R(7, 0)])
        s.sub.subsub.m % SchemWire(vertices=[Vec2R(7, 4), Vec2R(7, 6)])
        s.t % SchemWire(vertices=[Vec2R(7, 10), Vec2R(7, 11)])
        s.tr % SchemWire(vertices=[Vec2R(9, 8), Vec2R(12, 8), Vec2R(12, 7)])
        s.br % SchemWire(vertices=[Vec2R(9, 2), Vec2R(12, 2), Vec2R(12, 3)])
        s.r % SchemWire(vertices=[Vec2R(14, 5), Vec2R(15, 5)])

        helpers.schem_check(s, add_conn_points=True)
        return s


class ResdivHierTb(SimBase):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.t = Net()
        s.t_ac = Net()
        s.r = Net()
        s.gnd = Net()

        hier1sym = ResdivHier1().symbol
        # Cannot use portmap() here, as the symbol has hierarchical pin paths.
        s.I0 = SchemInstance(symbol=hier1sym, pos=Vec2R(5, 0))
        s.I0 % SchemInstanceConn(here=s.t,   there=hier1sym.inputs.t)
        s.I0 % SchemInstanceConn(here=s.gnd, there=hier1sym.inputs.b)
        s.I0 % SchemInstanceConn(here=s.r,   there=hier1sym.outputs.r)

        s.I1 = SchemInstance(NoConn().symbol.portmap(a=s.r), pos=Vec2R(10, 0))
        s.I2 = SchemInstance(
            Vdc(dc=R(1)).symbol.portmap(m=s.gnd, p=s.t_ac), pos=Vec2R(0, 0)
        )
        s.I2_ac = SchemInstance(
            SinusoidalVoltageSource(amplitude=R(1), frequency=R("1e6")).symbol.portmap(m=s.t_ac, p=s.t), pos=Vec2R(0, 6)
        )
        s.I3 = SchemInstance(Gnd().symbol.portmap(p=s.gnd), pos=Vec2R(0, -6))

        s.outline = Rect4R(lx=0, ly=-6, ux=14, uy=10)

        s.gnd % SchemWire(vertices=[Vec2R(2, -2), Vec2R(2, -1), Vec2R(2, 0)])
        s.gnd % SchemWire(vertices=[Vec2R(2, -1), Vec2R(7, -1), Vec2R(7, 0)])
        s.t_ac % SchemWire(vertices=[Vec2R(2, 4), Vec2R(2, 6)])
        s.t % SchemWire(vertices=[Vec2R(2, 10), Vec2R(2, 9), Vec2R(7, 9), Vec2R(7, 5), Vec2R(7, 4)])
        s.r % SchemWire(vertices=[Vec2R(9, 2), Vec2R(10, 2)])

        helpers.schem_check(s, add_conn_points=True)
        return s


class NmosSourceFollowerTb(SimBase):
    """Nmos (generic_mos) source follower with optional parameter vin."""

    vin = Parameter(R, optional=True, default=R(2))

    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.i = Net()
        s.i_ac = Net()
        s.o = Net()
        s.vss = Net()
        vin = self.vin

        s.I0 = SchemInstance(
            Nmos(w=R("5u"), l=R("1u")).symbol.portmap(d=s.vdd, s=s.o, g=s.i, b=s.vss),
            pos=Vec2R(11, 12),
        )

        s.I1 = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(11, 0))
        s.I2 = SchemInstance(
            Vdc(dc=R("5")).symbol.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 6)
        )
        s.I3 = SchemInstance(
            Vdc(dc=vin).symbol.portmap(m=s.vss, p=s.i_ac), pos=Vec2R(5, 6)
        )
        s.I3_ac = SchemInstance(
            SinusoidalVoltageSource(amplitude=R(1), frequency=R("1e6")).symbol.portmap(m=s.i_ac, p=s.i), pos=Vec2R(5, 12)
        )
        s.I4 = SchemInstance(
            Idc(dc=R("5u")).symbol.portmap(m=s.vss, p=s.o), pos=Vec2R(11, 6)
        )

        s.outline = Rect4R(lx=0, ly=0, ux=16, uy=22)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)

        return s


class InvTb(SimBase):
    vin = Parameter(R, optional=True, default=R(0))

    @generate
    def schematic(self):
        s = Schematic(cell=self)
        s.vdd = Net()
        s.i = Net()
        s.i_ac = Net()
        s.o = Net()
        s.vss = Net()
        vin = self.vin

        s.I0 = SchemInstance(
            Inv().symbol.portmap(vdd=s.vdd, vss=s.vss, a=s.i, y=s.o), pos=Vec2R(11, 9)
        )
        s.I1 = SchemInstance(NoConn().symbol.portmap(a=s.o), pos=Vec2R(16, 9))
        s.I2 = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(11, 0))
        s.I3 = SchemInstance(
            Vdc(dc=R("5")).symbol.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 6)
        )
        s.I4 = SchemInstance(
            Vdc(dc=vin).symbol.portmap(m=s.vss, p=s.i_ac), pos=Vec2R(5, 6)
        )
        s.I4_ac = SchemInstance(
            SinusoidalVoltageSource(amplitude=R(1), frequency=R("1e6")).symbol.portmap(m=s.i_ac, p=s.i), pos=Vec2R(5, 12)
        )

        s.outline = Rect4R(lx=0, ly=0, ux=20, uy=14)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)

        return s


class InvSkyTb(SimBase):
    vin = Parameter(R, optional=True, default=R(0))

    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.i = Net()
        s.i_ac = Net()
        s.o = Net()
        s.vss = Net()
        vin = self.vin

        sym_inv = sky130.Inv().symbol
        sym_nc = NoConn().symbol
        sym_gnd = Gnd().symbol
        sym_vdc_vdd = Vdc(dc=R("5")).symbol
        sym_vdc_in = Vdc(dc=vin).symbol
        sym_vac_in = SinusoidalVoltageSource(amplitude=R(1), frequency=R("1e6")).symbol

        s.i_inv = SchemInstance(
            sym_inv.portmap(vdd=s.vdd, vss=s.vss, a=s.i, y=s.o), pos=Vec2R(11, 9)
        )
        s.i_nc = SchemInstance(sym_nc.portmap(a=s.o), pos=Vec2R(16, 9))

        s.i_gnd = SchemInstance(sym_gnd.portmap(p=s.vss), pos=Vec2R(11, 0))
        s.i_vdd = SchemInstance(sym_vdc_vdd.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 6))
        s.i_in = SchemInstance(sym_vdc_in.portmap(m=s.vss, p=s.i_ac), pos=Vec2R(5, 6))
        s.i_in_ac = SchemInstance(sym_vac_in.portmap(m=s.i_ac, p=s.i), pos=Vec2R(5, 12))

        s.outline = Rect4R(lx=0, ly=0, ux=20, uy=14)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)

        return s


class IhpInv(Cell):
    @generate
    def symbol(self) -> Symbol:
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
    def schematic(self) -> Schematic:
        s = Schematic(cell=self, symbol=self.symbol)
        s.a = Net(pin=self.symbol.a)
        s.y = Net(pin=self.symbol.y)
        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)

        # IHP130 specific parameters - using values from the old code
        nmos_params = {
            "l": R("0.13u"),
            "w": R("0.495u"),
            "m": 1,
            "ng": 1,
        }
        nmos = ihp130.Nmos(**nmos_params).symbol

        pmos_params = {
            "l": R("0.13u"),
            "w": R("0.99u"),
            "m": 1,
            "ng": 1,
        }
        pmos = ihp130.Pmos(**pmos_params).symbol

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


class InvIhpTb(SimBase):
    vin = Parameter(R, optional=True, default=R(0))

    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.i = Net()
        s.i_ac = Net()
        s.o = Net()
        s.vss = Net()
        vin = self.vin

        sym_inv = IhpInv().symbol
        sym_nc = NoConn().symbol
        sym_gnd = Gnd().symbol
        sym_vdc_vdd = Vdc(dc=R("5")).symbol
        sym_vdc_in = Vdc(dc=vin).symbol
        sym_vac_in = SinusoidalVoltageSource(amplitude=R(1), frequency=R("1e6")).symbol

        s.i_inv = SchemInstance(
            sym_inv.portmap(vdd=s.vdd, vss=s.vss, a=s.i, y=s.o), pos=Vec2R(11, 9)
        )
        s.i_nc = SchemInstance(sym_nc.portmap(a=s.o), pos=Vec2R(16, 9))

        s.i_gnd = SchemInstance(sym_gnd.portmap(p=s.vss), pos=Vec2R(11, 0))
        s.i_vdd = SchemInstance(sym_vdc_vdd.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 6))
        s.i_in = SchemInstance(sym_vdc_in.portmap(m=s.vss, p=s.i_ac), pos=Vec2R(5, 6))
        s.i_in_ac = SchemInstance(sym_vac_in.portmap(m=s.i_ac, p=s.i), pos=Vec2R(5, 12))

        s.outline = Rect4R(lx=0, ly=0, ux=20, uy=14)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)

        return s


class PulsedRC(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)
        s.vss = Net()
        s.inp = Net()
        s.out = Net()

        res = Res(r=R("100")).symbol
        cap = Cap(c=R("100n")).symbol

        vsrc = PulseVoltageSource(
            initial_value=R(0),
            pulsed_value=R(1),
            rise_time=R("10u"),
            fall_time=R("10u"),
            pulse_width=R("15u"),
            period=R("50u"),
        ).symbol

        s.gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(6, -1))
        s.vsrc = SchemInstance(vsrc.portmap(m=s.vss, p=s.inp), pos=Vec2R(0, 5))
        s.res = SchemInstance(res.portmap(m=s.out, p=s.inp), pos=Vec2R(10, 8), orientation = Orientation.West)
        s.cap = SchemInstance(cap.portmap(m=s.vss, p=s.out), pos=Vec2R(12, 5))

        s.outline = schematic_routing(s)
        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)
        return s

    @generate
    def sim_tran(self):
        s = SimHierarchy()
        sim = HighlevelSim(self.schematic, s)
        sim.tran(R('5u'), R('250u'))
        return s
