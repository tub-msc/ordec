# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from .. import helpers
from ..core import *
from ..sim2.sim_hierarchy import HighlevelSim

from .generic_mos import Or2, Nmos, Pmos, Ringosc, Inv
from .base import Gnd, NoConn, Res, Vdc, Idc, Cap, SinusoidalVoltageSource
from . import sky130
from . import ihp130

class RotateTest(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)
        c = Or2().symbol

        s.R0   = SchemInstance(c.portmap(), pos=Vec2R(1, 1), orientation=Orientation.R0)
        s.R90  = SchemInstance(c.portmap(), pos=Vec2R(12, 1), orientation=Orientation.R90)
        s.R180 = SchemInstance(c.portmap(), pos=Vec2R(18, 6), orientation=Orientation.R180)
        s.R270 = SchemInstance(c.portmap(), pos=Vec2R(19, 6), orientation=Orientation.R270)

        s.MY   = SchemInstance(c.portmap(), pos=Vec2R(6, 7), orientation=Orientation.MY)
        s.MY90 = SchemInstance(c.portmap(), pos=Vec2R(12, 12), orientation=Orientation.MY90)
        s.MX   = SchemInstance(c.portmap(), pos=Vec2R(13, 12), orientation=Orientation.MX)
        s.MX90 = SchemInstance(c.portmap(), pos=Vec2R(19, 7), orientation=Orientation.MX90)

        s.outline = Rect4R(lx=0, ly=0, ux=25, uy=13)
        return s

class PortAlignTest(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.north = Pin(pintype=PinType.In, align=Orientation.North)
        s.south = Pin(pintype=PinType.In, align=Orientation.South)
        s.west = Pin(pintype=PinType.In, align=Orientation.West)
        s.east = Pin(pintype=PinType.In, align=Orientation.East)
        helpers.symbol_place_pins(s)

        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.n1 = Net(pin=self.symbol.north)
        s.n2 = Net(pin=self.symbol.south)
        s.n3 = Net(pin=self.symbol.east)
        s.n4 = Net(pin=self.symbol.west)

        s.n1 % SchemPort(pos=Vec2R(4, 2), align=Orientation.North)
        s.n2 % SchemPort(pos=Vec2R(4, 6), align=Orientation.South)
        s.n3 % SchemPort(pos=Vec2R(2, 4), align=Orientation.East)
        s.n4 % SchemPort(pos=Vec2R(6, 4), align=Orientation.West)

        s.outline = Rect4R(lx=0, ly=0, ux=8, uy=8)
        return s

class TapAlignTest(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.north = Net()
        s.south = Net()
        s.east = Net()
        s.west = Net()

        s.north % SchemTapPoint(pos=Vec2R(4, 6), align=Orientation.North)
        s.south % SchemTapPoint(pos=Vec2R(4, 2), align=Orientation.South)
        s.west % SchemTapPoint(pos=Vec2R(2, 4), align=Orientation.West)
        s.east % SchemTapPoint(pos=Vec2R(6, 4), align=Orientation.East)

        s.outline = Rect4R(lx=0, ly=0, ux=8, uy=8)
        return s


class DFF(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vss = Pin(pintype=PinType.In, align=Orientation.South)
        s.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        s.d = Pin(pintype=PinType.In, align=Orientation.West)
        s.q = Pin(pintype=PinType.Out, align=Orientation.East)
        s.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(s, vpadding=2, hpadding=3)

        return s

class MultibitReg_Arrays(Cell):
    bits = Parameter(int)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vss = Pin(pintype=PinType.In, align=Orientation.South)
        s.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        s.mkpath('d')
        s.mkpath('q')
        for i in range(self.bits):
            s.d[i] = Pin(pintype=PinType.In, align=Orientation.West)
            s.q[i] = Pin(pintype=PinType.Out, align=Orientation.East)
        s.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(s)

        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.vss = Net(pin=self.symbol.vss)
        s.vdd = Net(pin=self.symbol.vdd)
        s.clk = Net(pin=self.symbol.clk)
        s.mkpath('d')
        s.mkpath('q')
        s.mkpath("I")

        s.vss % SchemPort(pos=Vec2R(1, 0), align=Orientation.East)
        s.vdd % SchemPort(pos=Vec2R(1, 1), align=Orientation.East)
        s.clk % SchemPort(pos=Vec2R(1, 2), align=Orientation.East)
        for i in range(self.bits):
            s.d[i] = Net(pin=self.symbol.d[i])
            s.q[i] = Net(pin=self.symbol.q[i])
            s.I[i] = SchemInstance(DFF().symbol.portmap(
                    vss=s.vss,
                    vdd=s.vdd,
                    clk=s.clk,
                    d=s.d[i],
                    q=s.q[i],
                ), pos=Vec2R(2, 3 + 8*i), orientation=Orientation.R0)

            s.d[i] % SchemPort(pos=Vec2R(1, 5+8*i), align=Orientation.East)
            s.d[i] % SchemWire(vertices=[Vec2R(1, 5+8*i), Vec2R(2, 5+8*i)])
            s.q[i] % SchemPort(pos=Vec2R(9, 5+8*i), align=Orientation.West)
            s.q[i] % SchemWire(vertices=[Vec2R(8, 5+8*i), Vec2R(9, 5+8*i)])

        s.outline = Rect4R(lx=0, ly=0, ux=10, uy=2+8*self.bits)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)

        return s

class MultibitReg_ArrayOfStructs(Cell):
    bits = Parameter(int)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vss = Pin(pintype=PinType.In, align=Orientation.South)
        s.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        s.mkpath('bit')
        for i in range(self.bits):
            s.bit.mkpath(i)
            s.bit[i].d = Pin(pintype=PinType.In, align=Orientation.West)
            s.bit[i].q = Pin(pintype=PinType.Out, align=Orientation.East)
        s.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(s)

        return s

class MultibitReg_StructOfArrays(Cell):
    bits = Parameter(int)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vss = Pin(pintype=PinType.In, align=Orientation.South)
        s.vdd = Pin(pintype=PinType.In, align=Orientation.North)
        s.mkpath('data')
        s.data.mkpath('d')
        s.data.mkpath('q')
        for i in range(self.bits):
            s.data.d[i] = Pin(pintype=PinType.In, align=Orientation.West)
            s.data.q[i] = Pin(pintype=PinType.Out, align=Orientation.East)
        s.clk = Pin(pintype=PinType.In, align=Orientation.West)
        helpers.symbol_place_pins(s)

        return s

class TestNmosInv(Cell):
    """For testing schem_check."""

    variant = Parameter(str)
    add_conn_points = Parameter(bool)
    add_terminal_taps = Parameter(bool)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vdd = Pin(pintype=PinType.Inout, align=Orientation.North)
        s.vss = Pin(pintype=PinType.Inout, align=Orientation.South)
        s.a = Pin(pintype=PinType.In, align=Orientation.West)
        s.y = Pin(pintype=PinType.Out, align=Orientation.East)
        helpers.symbol_place_pins(s)

        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)

        s.a = Net(pin=self.symbol.a)
        s.y = Net(pin=self.symbol.y)
        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)


        nmos = Nmos(w=R("500n"), l=R("250n")).symbol

        portmap = nmos.portmap(s=s.vss, b=s.vss, g=s.a, d=s.y)
        if self.variant == "incorrect_pin_conn":
            portmap = nmos.portmap(s=s.vss, b=s.a, g=s.a, d=s.y)
        elif self.variant == "portmap_missing_key":
            portmap = nmos.portmap(s=s.vss, b=s.vss, d=s.y)

        s.pd = SchemInstance(portmap, pos=Vec2R(3, 2))
        if self.variant == "portmap_stray_key":
            s.stray = Net()
            s.pd % SchemInstanceConn(here=s.stray, there=0)
        elif self.variant == "portmap_bad_value":
            list(s.pd.conns)[0].there = 12345

        s.pu = SchemInstance(nmos.portmap(d=s.vdd, b=s.vss, g=s.vdd, s=s.y), pos=Vec2R(3, 8))
        if self.variant=="double_instance":
            s.pu2 = SchemInstance(nmos.portmap(d=s.vdd, b=s.vss, g=s.vdd, s=s.y), pos=Vec2R(3, 8))

        s.vdd % SchemPort(pos=Vec2R(1, 13), align=Orientation.East)
        s.vss % SchemPort(pos=Vec2R(1, 1), align=Orientation.East)
        s.a % SchemPort(pos=Vec2R(1, 4), align=Orientation.East)
        if self.variant == 'incorrect_port_conn':
            s.vss % SchemPort(pos=Vec2R(9, 7), align=Orientation.West)
        else:
            s.y % SchemPort(pos=Vec2R(9, 7), align=Orientation.West)

        if self.variant == "no_wiring":
            s.default_supply = s.vdd
            s.default_ground = s.vss
        else:
            s.vss % SchemWire(vertices=[Vec2R(1, 1), Vec2R(5, 1), s.pd.pos + nmos.s.pos])
            if self.variant == 'skip_single_pin':
                s.vss % SchemWire(vertices=[Vec2R(7, 4), Vec2R(8, 4)])
            else:
                s.vss % SchemWire(vertices=[Vec2R(7, 4), Vec2R(8, 4), Vec2R(8, 10), Vec2R(7, 10)])
            if self.variant not in ('net_partitioned', 'net_partitioned_tapped'):
                s.vss % SchemWire(vertices=[Vec2R(8, 4), Vec2R(8, 1), Vec2R(5, 1)])

            if self.variant == 'net_partitioned_tapped':
                s.vss % SchemTapPoint(pos=Vec2R(8, 4), align=Orientation.South)
                s.vss % SchemTapPoint(pos=Vec2R(5, 1), align=Orientation.East)

            if self.variant == 'vdd_bad_wiring':
                s.vdd % SchemWire(vertices=[Vec2R(1, 13), Vec2R(2, 13)])
            elif self.variant != 'skip_vdd_wiring':
                s.vdd % SchemWire(vertices=[Vec2R(1, 13), Vec2R(2, 13), Vec2R(5, 13), s.pu.pos + nmos.d.pos])
                if self.variant == "terminal_multiple_wires":
                    s.vdd % SchemWire(vertices=[Vec2R(1, 13), Vec2R(1, 10), Vec2R(3, 10)])
                else:
                    s.vdd % SchemWire(vertices=[Vec2R(2, 13), Vec2R(2, 10), Vec2R(3, 10)])

            if self.variant == "terminal_connpoint":
                s.vdd % SchemConnPoint(pos=Vec2R(1, 13))

            if self.variant == "stray_conn_point":
                s.vdd % SchemConnPoint(pos=Vec2R(5, 13))
            if self.variant == "tap_short":
                s.vss % SchemTapPoint(pos=Vec2R(5, 13))

            if self.variant == 'poly_short':
                s.vdd % SchemWire(vertices=[Vec2R(2, 10), Vec2R(2, 4),])

            s.a % SchemWire(vertices=[Vec2R(1, 4), Vec2R(2, 4), Vec2R(3, 4)])
            s.y % SchemWire(vertices=[Vec2R(5, 6), Vec2R(5, 7), Vec2R(5, 8)])
            s.y % SchemWire(vertices=[Vec2R(5, 7), Vec2R(9, 7)])

        if self.variant in ("manual_conn_points", "double_connpoint"):
            s.vss % SchemConnPoint(pos=Vec2R(5, 1))
            s.vss % SchemConnPoint(pos=Vec2R(8, 4))
            s.vdd % SchemConnPoint(pos=Vec2R(2, 13))
            s.y % SchemConnPoint(pos=Vec2R(5, 7))
            if self.variant == "double_connpoint":
                s.y % SchemConnPoint(pos=Vec2R(5, 7))

        if self.variant == "unconnected_conn_point":
            s.y % SchemConnPoint(pos=Vec2R(4, 7))


        s.outline = Rect4R(lx=0, ly=1, ux=10, uy=13)
        helpers.schem_check(s, add_conn_points=self.add_conn_points, add_terminal_taps=self.add_terminal_taps)

        return s

class RingoscTb(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.vss = Net()
        s.y = Net()

        vdc = Vdc().symbol
        s.i0 = SchemInstance(pos=Vec2R(0, 2), ref=vdc,
            portmap={vdc.m:s.vss, vdc.p:s.vdd})

        ro = Ringosc().symbol
        s.dut = SchemInstance(pos=Vec2R(5, 2), ref=ro,
            portmap={ro.vdd:s.vdd, ro.vss:s.vss, ro.y:s.y})

        nc = NoConn().symbol
        s.i1 = SchemInstance(pos=Vec2R(10, 2), ref=nc,
            portmap={nc.a:s.y})

        g = Gnd().symbol
        s.i2 = SchemInstance(pos=Vec2R(0, -4), ref=g,
            portmap={g.p:s.vss})

        #s.ref = self.symbol

        s.outline = Rect4R(lx=0, ly=-4, ux=15, uy=7)

        s.vss % SchemWire(vertices=[Vec2R(2, 2), Vec2R(2, 1), Vec2R(2, 0)])
        s.vss % SchemWire(vertices=[Vec2R(2, 1), Vec2R(7, 1), Vec2R(7, 2)])
        s.vdd % SchemWire(vertices=[Vec2R(2, 6), Vec2R(2, 7), Vec2R(7, 7), Vec2R(7, 6)])
        s.y % SchemWire(vertices=[Vec2R(9, 4), Vec2R(10, 4)])

        helpers.schem_check(s, add_conn_points=True)

        return s


# Cells for sim2 testing
# ----------------------

class SimBase(Cell):
    backend = Parameter(str, default='subprocess')

    @generate
    def sim_hierarchy(self):
        s = SimHierarchy(cell=self)
        # Build SimHierarchy, but runs no simulations.
        HighlevelSim(self.schematic, s, backend=self.backend)
        return s

    @generate
    def sim_dc(self):
        s = SimHierarchy(cell=self)
        sim = HighlevelSim(self.schematic, s, backend=self.backend)
        sim.op()
        return s

    def sim_ac(self, *args, **kwargs):
        s = SimHierarchy(cell=self)
        backend = kwargs.pop('backend', self.backend)
        sim = HighlevelSim(self.schematic, s, backend=backend)
        sim.ac(*args, **kwargs)
        return s

    def sim_tran_async(self, tstep, tstop, **kwargs):
        """Run async transient simulation.

        Args:
            tstep: Time step for the simulation
            tstop: Stop time for the simulation
            callback: Optional callback function for data updates
            throttle_interval: Minimum time between callbacks (seconds)
            enable_savecurrents: If True (default), enables .option savecurrents
        """
        # Create hierarchical simulation
        from ..sim2.sim_hierarchy import SimHierarchy
        from ..sim2.ngspice import Ngspice

        callback = kwargs.pop('callback', None)
        throttle_interval = kwargs.pop('throttle_interval', 0.1)
        enable_savecurrents = kwargs.pop('enable_savecurrents', True)

        node = SimHierarchy()
        highlevel_sim = HighlevelSim(self.schematic, node, enable_savecurrents=enable_savecurrents, backend=self.backend)

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
        with Ngspice.launch(backend=self.backend, debug=kwargs.get('debug', False)) as sim:
            sim.load_netlist(highlevel_sim.netlister.out())

            # Get the queue from the new queue-based tran_async
            data_queue = sim.tran_async(tstep, tstop, throttle_interval=throttle_interval)

            # Convert queue-based approach to generator for API compatibility
            import queue
            import time
            import threading
            import concurrent.futures

            # Use event-driven approach instead of wasteful polling
            fallback_grace_period = 2.0
            completion_time = None

            # Use threading for non-blocking queue operations
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:

                def get_data_with_timeout(timeout):
                    """Get data from queue with timeout, returns None if timeout"""
                    try:
                        return data_queue.get(timeout=timeout)
                    except queue.Empty:
                        return None

                def check_simulation_status():
                    """Check if simulation is still running"""
                    return sim.is_running()

                while True:
                    # Race condition: submit both data fetch and status check
                    data_future = executor.submit(get_data_with_timeout, 0.05)
                    status_future = executor.submit(check_simulation_status)

                    # Wait for either data or status with short timeout
                    done_futures = concurrent.futures.as_completed([data_future, status_future], timeout=0.1)

                    data_available = False

                    try:
                        for future in done_futures:
                            if future == data_future:
                                data_point = future.result()
                                if data_point is not None:
                                    data_available = True

                                    # Handle MP backend sentinel
                                    if data_point == "---ASYNC_SIM_SENTINEL---":
                                        return

                                    # Process valid data
                                    if isinstance(data_point, dict):
                                        if callback:
                                            callback(data_point)
                                        data = data_point.get('data', {})
                                        progress = data_point.get('progress', 0.0)
                                        yield TranResult(data, node, highlevel_sim.netlister, progress)

                            elif future == status_future:
                                is_running = future.result()
                                if not is_running and completion_time is None:
                                    completion_time = time.time()

                    except concurrent.futures.TimeoutError:
                        # No immediate results, check simulation status
                        if not sim.is_running() and completion_time is None:
                            completion_time = time.time()

                    # Clean up futures
                    if not data_future.done():
                        data_future.cancel()
                    if not status_future.done():
                        status_future.cancel()

                    # Check termination conditions
                    if not data_available:
                        # No data received, check if we should continue
                        if completion_time is not None:
                            # Simulation finished, check grace period
                            if time.time() - completion_time >= fallback_grace_period:
                                # Try to drain any remaining items quickly
                                remaining_items = 0
                                while remaining_items < 10:  # Limit to prevent infinite loop
                                    try:
                                        data_point = data_queue.get_nowait()
                                        if data_point == "---ASYNC_SIM_SENTINEL---":
                                            return
                                        if isinstance(data_point, dict):
                                            if callback:
                                                callback(data_point)
                                            data = data_point.get('data', {})
                                            progress = data_point.get('progress', 0.0)
                                            yield TranResult(data, node, highlevel_sim.netlister, progress)
                                        remaining_items += 1
                                    except queue.Empty:
                                        break
                                break
                        elif not sim.is_running():
                            # Just finished, start grace period
                            completion_time = time.time()



    def sim_tran(self, tstep, tstop, **kwargs):
        """Run sync transient simulation.

        Args:
            tstep: Time step for the simulation
            tstop: Stop time for the simulation
            backend: Simulation backend ('ffi' or 'subprocess')
            enable_savecurrents: If True (default), enables .option savecurrents
        """
        # Create hierarchical simulation
        from ..sim2.sim_hierarchy import SimHierarchy
        s = SimHierarchy(cell=self)
        backend = kwargs.pop('backend', self.backend)
        sim = HighlevelSim(self.schematic, s, backend=backend, **kwargs)
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

        vac = SinusoidalVoltageSource(amplitude=R(1), frequency=R(1)).symbol # frequency is a dummy value
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
        s.vss % SchemWire(vertices=[Vec2R(2, vss_bus_y), Vec2R(12, vss_bus_y)]) # vss bus
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

class ResdivHierTb(SimBase):
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

class NmosSourceFollowerTb(SimBase):
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

class InvTb(SimBase):
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

class InvSkyTb(SimBase):
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

class InvIhpTb(SimBase):
    vin = Parameter(R, optional=True, default=R(0))

    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.i = Net()
        s.o = Net()
        s.vss = Net()
        vin = self.vin

        sym_inv = ihp130.Inv().symbol
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


class RCAlterTestbench(Cell):
    """RC circuit for testing HighlevelSim alter operations"""

    @generate
    def schematic(self):
        s = Schematic(cell=self, outline=Rect4R(lx=0, ly=0, ux=10, uy=10))

        s.vin = Net()
        s.vout = Net()
        s.gnd = Net()

        s.v1 = SchemInstance(Vdc(dc=R(1)).symbol.portmap(p=s.vin, m=s.gnd), pos=Vec2R(0, 5))
        s.r1 = SchemInstance(Res(r=R(1000)).symbol.portmap(p=s.vin, m=s.vout), pos=Vec2R(5, 5))
        s.c1 = SchemInstance(Cap(c=R("1u")).symbol.portmap(p=s.vout, m=s.gnd), pos=Vec2R(8, 3))
        s.gnd_conn = SchemInstance(Gnd().symbol.portmap(p=s.gnd), pos=Vec2R(0, 0))

        return s
