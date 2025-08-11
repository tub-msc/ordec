# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from .. import helpers
from ..core import *
from ..sim2.sim_hierarchy import HighlevelSim, SimHierarchy, SimNet, SimInstance
from ..sim2.ngspice import Ngspice

from .generic_mos import Or2, Nmos, Pmos, Ringosc, Inv
from .base import Gnd, NoConn, Res, Vdc, Idc
from . import sky130

class ResdivFlatTb(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.vss = Net()
        s.a = Net()
        s.b = Net()

        sym_vdc = Vdc(dc=R(1)).symbol
        sym_gnd = Gnd().symbol
        sym_res = Res(r=R(100)).symbol

        s.I0 = SchemInstance(sym_gnd.portmap(p=s.vss), pos=Vec2R(5, 0))
        s.I1 = SchemInstance(sym_vdc.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 6))
        s.I2 = SchemInstance(sym_res.portmap(m=s.vss, p=s.a), pos=Vec2R(5, 6))
        s.I3 = SchemInstance(sym_res.portmap(m=s.a, p=s.b), pos=Vec2R(5, 11))
        s.I4 = SchemInstance(sym_res.portmap(m=s.b, p=s.vdd), pos=Vec2R(5, 16))

        s.vss % SchemWire(vertices=[Vec2R(7, 4), Vec2R(7, 5), Vec2R(7, 6)])
        s.vss % SchemWire(vertices=[Vec2R(2, 6), Vec2R(2, 5), Vec2R(7, 5)])
        s.vdd % SchemWire(vertices=[Vec2R(2, 10), Vec2R(2, 21), Vec2R(7, 21), Vec2R(7, 20)])
        s.a % SchemWire(vertices=[Vec2R(7, 10), Vec2R(7, 11)])
        s.b % SchemWire(vertices=[Vec2R(7, 15), Vec2R(7, 16)])

        s.outline = Rect4R(lx=0, ly=0, ux=9, uy=21)

        helpers.schem_check(s, add_conn_points=True)

        return s

    @generate
    def sim_dc(self):
        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s, backend='ffi')
        sim.op()
        return s

    def sim_tran_async(self, tstep, tstop, backend='ffi', callback=None, throttle_interval=0.1):
        """Run async transient simulation."""
        # Create hierarchical simulation
        from ..sim2.sim_hierarchy import SimHierarchy
        node = SimHierarchy()
        highlevel_sim = HighlevelSim(self.schematic, node, backend=backend)

        # Create result wrapper class
        class TranResult:
            def __init__(self, data_dict, sim_hierarchy, netlister, progress):
                self._data = data_dict
                self._node = sim_hierarchy
                self._netlister = netlister
                self.time = data_dict.get('time', 0.0)
                self.progress = progress

                # Create hierarchical access
                for net in sim_hierarchy.all(SimNet):
                    net_name = netlister.name_hier_simobj(net)
                    if net_name in data_dict:
                        setattr(self, net.npath.name, type('NetData', (), {'voltage': data_dict[net_name]})())

                for inst in sim_hierarchy.all(SimInstance):
                    inst_name = netlister.name_hier_simobj(inst)
                    if inst_name in data_dict:
                        setattr(self, inst.npath.name, type('InstData', (), {'voltage': data_dict[inst_name]})())

        # Run simulation
        with Ngspice.launch(backend=backend) as sim:
            sim.load_netlist(highlevel_sim.netlister.out())

            for data_point in sim.tran_async(tstep, tstop, callback=callback, throttle_interval=throttle_interval):
                data = data_point.get('data', {})
                progress = data_point.get('progress', 0.0)
                yield TranResult(data, node, highlevel_sim.netlister, progress)


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

        sym_res = Res(r=self.params.r).symbol

        s.I0 = SchemInstance(sym_res.portmap(m=s.b, p=s.m), pos=Vec2R(0, 1))
        s.I1 = SchemInstance(sym_res.portmap(m=s.m, p=s.t), pos=Vec2R(0, 7))
        s.I2 = SchemInstance(sym_res.portmap(m=s.r, p=s.m), pos=Vec2R(9, 4), orientation=Orientation.R90)

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
        s.tr = Net()
        s.br = Net()
        s.m = Net()

        s.t % SchemPort(pos=Vec2R(7, 11), align=Orientation.South)
        s.r % SchemPort(pos=Vec2R(15, 5), align=Orientation.West)
        s.b % SchemPort(pos=Vec2R(7, -1), align=Orientation.North)

        sym_1 = ResdivHier2(r=R(100)).symbol
        sym_2 = ResdivHier2(r=R(200)).symbol

        #s % SchemInstance(pos=Vec2R(5, 0), ref=sym_1, portmap={sym_1.t: s.m, sym_1.b:s.gnd, sym_1.r:s.br})
        s.I0 = SchemInstance(sym_1.portmap(t=s.m, b=s.b, r=s.br), pos=Vec2R(5, 0))
        s.I1 = SchemInstance(sym_2.portmap(t=s.t, b=s.m, r=s.tr), pos=Vec2R(5, 6))
        s.I2 = SchemInstance(sym_1.portmap(t=s.tr, b=s.br, r=s.r), pos=Vec2R(10, 3))

        s.outline = Rect4R(lx=5, ly=-1, ux=15, uy=12)

        s.b % SchemWire(vertices=[Vec2R(7, -1), Vec2R(7, 0)])
        s.m % SchemWire(vertices=[Vec2R(7, 4), Vec2R(7, 6)])
        s.t % SchemWire(vertices=[Vec2R(7, 10), Vec2R(7, 11)])
        s.tr % SchemWire(vertices=[Vec2R(9, 8), Vec2R(12, 8), Vec2R(12, 7)])
        s.br % SchemWire(vertices=[Vec2R(9, 2), Vec2R(12, 2), Vec2R(12, 3)])
        s.r % SchemWire(vertices=[Vec2R(14, 5), Vec2R(15, 5)])

        helpers.schem_check(s, add_conn_points=True)
        return s


class ResdivHierTb(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.t = Net()
        s.r = Net()
        s.gnd = Net()

        s.I0 = SchemInstance(ResdivHier1().symbol.portmap(t=s.t, b=s.gnd, r=s.r), pos=Vec2R(5, 0))
        s.I1 = SchemInstance(NoConn().symbol.portmap(a=s.r), pos=Vec2R(10, 0))
        s.I2 = SchemInstance(Vdc(dc=R(1)).symbol.portmap(m=s.gnd, p=s.t), pos=Vec2R(0, 0))
        s.I3 = SchemInstance(Gnd().symbol.portmap(p=s.gnd), pos=Vec2R(0, -6))

        s.outline = Rect4R(lx=0, ly=-6, ux=14, uy=5)

        s.gnd % SchemWire(vertices=[Vec2R(2, -2), Vec2R(2, -1), Vec2R(2, 0)])
        s.gnd % SchemWire(vertices=[Vec2R(2, -1), Vec2R(7, -1), Vec2R(7, 0)])
        s.t % SchemWire(vertices=[Vec2R(7, 4), Vec2R(7, 5), Vec2R(2, 5), Vec2R(2, 4)])
        s.r % SchemWire(vertices=[Vec2R(9, 2), Vec2R(10, 2)])

        helpers.schem_check(s, add_conn_points=True)
        return s

    @generate
    def sim_hierarchy(self):
        s = SimHierarchy(cell=self)
        # Build SimHierarchy, but runs no simulations.
        HighlevelSim(self.schematic, s, backend='ffi')
        return s

    @generate
    def sim_dc(self):
        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s, backend='ffi')
        sim.op()
        return s

    def sim_tran_async(self, tstep, tstop, backend='ffi', callback=None, throttle_interval=0.1):
        """Run async transient simulation."""
        # Create hierarchical simulation
        from ..sim2.sim_hierarchy import SimHierarchy
        node = SimHierarchy()
        highlevel_sim = HighlevelSim(self.schematic, node, backend=backend)

        # Create result wrapper class
        class TranResult:
            def __init__(self, data_dict, sim_hierarchy, netlister, progress):
                self._data = data_dict
                self._node = sim_hierarchy
                self._netlister = netlister
                self.time = data_dict.get('time', 0.0)
                self.progress = progress

                # Create hierarchical access
                for net in sim_hierarchy.all(SimNet):
                    net_name = netlister.name_hier_simobj(net)
                    if net_name in data_dict:
                        setattr(self, net.npath.name, type('NetData', (), {'voltage': data_dict[net_name]})())

                for inst in sim_hierarchy.all(SimInstance):
                    inst_name = netlister.name_hier_simobj(inst)
                    if inst_name in data_dict:
                        setattr(self, inst.npath.name, type('InstData', (), {'voltage': data_dict[inst_name]})())

        # Run simulation
        with Ngspice.launch(backend=backend) as sim:
            netlist = highlevel_sim.netlister.out()
            print(f"Netlist for {self.__class__.__name__}:\n{netlist}")
            sim.load_netlist(netlist)

            for data_point in sim.tran_async(tstep, tstop, callback=callback, throttle_interval=throttle_interval):
                data = data_point.get('data', {})
                progress = data_point.get('progress', 0.0)
                yield TranResult(data, node, highlevel_sim.netlister, progress)


class NmosSourceFollowerTb(Cell):
    """Nmos (generic_mos) source follower with optional parameter vin."""
    vin = Parameter(R, optional=True, default=R(2))

    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.i = Net()
        s.o = Net()
        s.vss = Net()
        vin = self.vin

        s.I0 = SchemInstance(Nmos(w=R('5u'), l=R('1u')).symbol.portmap(d=s.vdd, s=s.o, g=s.i, b=s.vss), pos=Vec2R(11, 12))

        s.I1 = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(11, 0))
        s.I2 = SchemInstance(Vdc(dc=R('5')).symbol.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 6))
        s.I3 = SchemInstance(Vdc(dc=vin).symbol.portmap(m=s.vss, p=s.i), pos=Vec2R(5, 6))
        s.I4 = SchemInstance(Idc(dc=R('5u')).symbol.portmap(m=s.vss, p=s.o), pos=Vec2R(11, 6))

        s.outline = Rect4R(lx=0, ly=0, ux=16, uy=22)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)

        return s

    @generate
    def sim_dc(self):
        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s, backend='ffi')
        sim.op()
        return s

    def sim_tran_async(self, tstep, tstop, backend='ffi', callback=None, throttle_interval=0.1):
        """Run async transient simulation."""
        # Create hierarchical simulation
        from ..sim2.sim_hierarchy import SimHierarchy
        node = SimHierarchy()
        highlevel_sim = HighlevelSim(self.schematic, node, backend=backend)

        # Create result wrapper class
        class TranResult:
            def __init__(self, data_dict, sim_hierarchy, netlister, progress):
                self._data = data_dict
                self._node = sim_hierarchy
                self._netlister = netlister
                self.time = data_dict.get('time', 0.0)
                self.progress = progress

                # Create hierarchical access
                for net in sim_hierarchy.all(SimNet):
                    net_name = netlister.name_hier_simobj(net)
                    if net_name in data_dict:
                        setattr(self, net.npath.name, type('NetData', (), {'voltage': data_dict[net_name]})())

                for inst in sim_hierarchy.all(SimInstance):
                    inst_name = netlister.name_hier_simobj(inst)
                    if inst_name in data_dict:
                        setattr(self, inst.npath.name, type('InstData', (), {'voltage': data_dict[inst_name]})())

        # Run simulation
        with Ngspice.launch(backend=backend) as sim:
            sim.load_netlist(highlevel_sim.netlister.out())

            for data_point in sim.tran_async(tstep, tstop, callback=callback, throttle_interval=throttle_interval):
                data = data_point.get('data', {})
                progress = data_point.get('progress', 0.0)
                yield TranResult(data, node, highlevel_sim.netlister, progress)


class InvTb(Cell):
    vin = Parameter(R, optional=True, default=R(0))

    @generate
    def schematic(self):
        s = Schematic(cell=self)
        s.vdd = Net()
        s.i = Net()
        s.o = Net()
        s.vss = Net()
        vin = self.vin

        s.I0 = SchemInstance(Inv().symbol.portmap(vdd = s.vdd, vss=s.vss, a=s.i, y=s.o), pos=Vec2R(11, 9))
        s.I1 = SchemInstance(NoConn().symbol.portmap(a=s.o), pos=Vec2R(16, 9))
        s.I2 = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(11, 0))
        s.I3 = SchemInstance(Vdc(dc=R('5')).symbol.portmap(m=s.vss, p = s.vdd), pos=Vec2R(0, 6))
        s.I4 = SchemInstance(Vdc(dc=vin).symbol.portmap(m=s.vss, p = s.i), pos=Vec2R(5, 6))

        s.outline = Rect4R(lx=0, ly=0, ux=20, uy=14)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)

        return s

    @generate
    def sim_dc(self):
        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s, backend='ffi')
        sim.op()
        return s

    def sim_tran_async(self, tstep, tstop, backend='ffi', callback=None, throttle_interval=0.1, enable_savecurrents=True):
        """Run async transient simulation.

        Args:
            tstep: Time step for the simulation
            tstop: Stop time for the simulation
            backend: Simulation backend ('ffi' or 'subprocess')
            callback: Optional callback function for data updates
            throttle_interval: Minimum time between callbacks (seconds)
            enable_savecurrents: If True (default), enables .option savecurrents
        """
        # Create hierarchical simulation
        from ..sim2.sim_hierarchy import SimHierarchy
        node = SimHierarchy()
        highlevel_sim = HighlevelSim(self.schematic, node, enable_savecurrents=enable_savecurrents, backend=backend)

        # Create result wrapper class
        class TranResult:
            def __init__(self, data_dict, sim_hierarchy, netlister, progress):
                self._data = data_dict
                self._node = sim_hierarchy
                self._netlister = netlister
                self.time = data_dict.get('time', 0.0)
                self.progress = progress

                # Create hierarchical access
                for net in sim_hierarchy.all(SimNet):
                    net_name = netlister.name_hier_simobj(net)
                    if net_name in data_dict:
                        setattr(self, net.npath.name, type('NetData', (), {'voltage': data_dict[net_name]})())

                for inst in sim_hierarchy.all(SimInstance):
                    inst_name = netlister.name_hier_simobj(inst)
                    if inst_name in data_dict:
                        setattr(self, inst.npath.name, type('InstData', (), {'voltage': data_dict[inst_name]})())

        # Run simulation
        with Ngspice.launch(backend=backend) as sim:
            sim.load_netlist(highlevel_sim.netlister.out())

            for data_point in sim.tran_async(tstep, tstop, callback=callback, throttle_interval=throttle_interval):
                data = data_point.get('data', {})
                progress = data_point.get('progress', 0.0)
                yield TranResult(data, node, highlevel_sim.netlister, progress)


class InvSkyTb(Cell):
    vin = Parameter(R, optional=True, default=R(0))

    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.i = Net()
        s.o = Net()
        s.vss = Net()
        vin = self.vin

        sym_inv = sky130.Inv().symbol
        sym_nc = NoConn().symbol
        sym_gnd = Gnd().symbol
        sym_vdc_vdd = Vdc(dc=R('5')).symbol
        sym_vdc_in = Vdc(dc=vin).symbol

        s.i_inv = SchemInstance(sym_inv.portmap(vdd=s.vdd, vss=s.vss, a=s.i, y=s.o), pos=Vec2R(11, 9))
        s.i_nc = SchemInstance(sym_nc.portmap(a=s.o), pos=Vec2R(16, 9))

        s.i_gnd = SchemInstance(sym_gnd.portmap(p=s.vss), pos=Vec2R(11, 0))
        s.i_vdd = SchemInstance(sym_vdc_vdd.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 6))
        s.i_in = SchemInstance(sym_vdc_in.portmap(m=s.vss, p=s.i), pos=Vec2R(5, 6))

        s.outline = Rect4R(lx=0, ly=0, ux=20, uy=14)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)

        return s

    @generate
    def sim_dc(self):
        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s, backend='ffi')
        sim.op()
        return s

    def sim_tran_async(self, tstep, tstop, backend='ffi', callback=None, throttle_interval=0.1, enable_savecurrents=False):

        # Create hierarchical simulation
        from ..sim2.sim_hierarchy import SimHierarchy
        node = SimHierarchy()
        highlevel_sim = HighlevelSim(self.schematic, node, enable_savecurrents=enable_savecurrents, backend=backend)

        # Create result wrapper class
        class TranResult:
            def __init__(self, data_dict, sim_hierarchy, netlister, progress):
                self._data = data_dict
                self._node = sim_hierarchy
                self._netlister = netlister
                self.time = data_dict.get('time', 0.0)
                self.progress = progress

                # Create hierarchical access
                for net in sim_hierarchy.all(SimNet):
                    net_name = netlister.name_hier_simobj(net)
                    if net_name in data_dict:
                        setattr(self, net.npath.name, type('NetData', (), {'voltage': data_dict[net_name]})())

                for inst in sim_hierarchy.all(SimInstance):
                    inst_name = netlister.name_hier_simobj(inst)
                    if inst_name in data_dict:
                        setattr(self, inst.npath.name, type('InstData', (), {'voltage': data_dict[inst_name]})())

        # Run simulation
        with Ngspice.launch(backend=backend) as sim:
            sim.load_netlist(highlevel_sim.netlister.out())

            for data_point in sim.tran_async(tstep, tstop, callback=callback, throttle_interval=throttle_interval):
                data = data_point.get('data', {})
                progress = data_point.get('progress', 0.0)
                yield TranResult(data, node, highlevel_sim.netlister, progress)
