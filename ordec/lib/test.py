# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass

from ..schematic import helpers
from ..core import *
from ..sim.sim_hierarchy import HighlevelSim, SimHierarchy
from ..sim.ngspice import Ngspice
from ..sim.ngspice_common import SignalKind, SignalArray

from .generic_mos import Or2, Nmos, Pmos, Ringosc, Inv
from .base import Gnd, NoConn, Res, Vdc, Idc, Cap, SinusoidalVoltageSource
from . import sky130
from . import ihp130

import queue as _queue
import time as _time
import concurrent.futures as _futures

@dataclass
class SignalValue:
    value: float
    kind: SignalKind

class TranResult:
    def __init__(
        self,
        data_dict,
        sim_hierarchy,
        netlister,
        progress,
        signal_kinds=None,
        mappings=None,
    ):
        self._data = data_dict
        self._node = sim_hierarchy
        self._netlister = netlister
        self.progress = progress

        # Use provided signal_kinds or fall back to heuristics
        signal_kinds = signal_kinds or {}

        # Precomputed mappings allow us to avoid repeated name lookups.
        if mappings:
            for attr_name, sim_name, default_kind in mappings:
                if sim_name == "time" and sim_name in data_dict:
                    kind = signal_kinds.get(sim_name, SignalKind.TIME)
                    self.time = SignalValue(value=data_dict[sim_name], kind=kind)
                    continue
                if sim_name in data_dict:
                    kind = signal_kinds.get(sim_name, default_kind)
                    setattr(self, attr_name, SignalValue(value=data_dict[sim_name], kind=kind))
            return

        if "time" in data_dict:
            time_kind = signal_kinds.get("time", SignalKind.TIME)
            self.time = SignalValue(value=data_dict["time"], kind=time_kind)

        for net in sim_hierarchy.all(SimNet):
            net_name = netlister.name_hier_simobj(net)
            if net_name in data_dict and net_name != "time":
                net_kind = signal_kinds.get(net_name, SignalKind.VOLTAGE)
                setattr(self, net.full_path_list()[-1],
                    SignalValue(value=data_dict[net_name], kind=net_kind))

        for inst in sim_hierarchy.all(SimInstance):
            inst_name = netlister.name_hier_simobj(inst)
            if inst_name in data_dict:
                inst_kind = signal_kinds.get(inst_name, SignalKind.CURRENT)
                setattr(self, inst.full_path_list()[-1],
                    SignalValue(value=data_dict[inst_name], kind=inst_kind))



class RingoscTb(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.vss = Net()
        s.y = Net()

        vac = SinusoidalVoltageSource(amplitude=R(1), frequency=R(1)).symbol
        s.i0 = SchemInstance(
            pos=Vec2R(0, 2), ref=vac, portmap={vac.m: s.vss, vac.p: s.vdd}
        )

        ro = Ringosc().symbol
        s.dut = SchemInstance(
            pos=Vec2R(5, 2), ref=ro, portmap={ro.vdd: s.vdd, ro.vss: s.vss, ro.y: s.y}
        )

        nc = NoConn().symbol
        s.i1 = SchemInstance(pos=Vec2R(10, 2), ref=nc, portmap={nc.a: s.y})

        g = Gnd().symbol
        s.i2 = SchemInstance(pos=Vec2R(0, -4), ref=g, portmap={g.p: s.vss})

        # s.ref = self.symbol

        s.outline = Rect4R(lx=0, ly=-4, ux=15, uy=7)

        s.vss % SchemWire(vertices=[Vec2R(2, 2), Vec2R(2, 1), Vec2R(2, 0)])
        s.vss % SchemWire(vertices=[Vec2R(2, 1), Vec2R(7, 1), Vec2R(7, 2)])
        s.vdd % SchemWire(vertices=[Vec2R(2, 6), Vec2R(2, 7), Vec2R(7, 7), Vec2R(7, 6)])
        s.y % SchemWire(vertices=[Vec2R(9, 4), Vec2R(10, 4)])

        helpers.schem_check(s, add_conn_points=True)

        return s


# not reentrant
def stream_from_queue(simbase, sim, data_queue, highlevel_sim, node, callback):
    # Minimal grace window to let fallback or buffered points land after ngspice stops.
    callbacks = getattr(sim, "_normal_callbacks_received", 0)
    fallback_grace_period = 0.1 if callbacks > 0 else 0.5

    last_progress = 0.0
    completion_time = None

    # Precompute mappings from sim objects to attribute names to avoid per-sample lookups.
    mappings = [("time", "time", SignalKind.TIME)]
    for net in node.all(SimNet):
        attr_name = net.full_path_list()[-1]
        mappings.append((attr_name, highlevel_sim.netlister.name_hier_simobj(net), SignalKind.VOLTAGE))
    for inst in node.all(SimInstance):
        attr_name = inst.full_path_list()[-1]
        mappings.append((attr_name, highlevel_sim.netlister.name_hier_simobj(inst), SignalKind.CURRENT))

    while True:
        try:
            data_point = data_queue.get(timeout=0.05)
        except _queue.Empty:
            data_point = None

        if data_point is not None:
            # Handle MP backend sentinel
            if data_point == "---ASYNC_SIM_SENTINEL---":
                return

            if not isinstance(data_point, dict):
                continue

            if "status" in data_point or "error" in data_point:
                if data_point.get("status") in ("completed", "halted"):
                    return
                continue

            if callback:
                callback(data_point)

            data = data_point.get("data", {})
            signal_kinds = data_point.get("signal_kinds", {})
            
            progress = data_point.get("progress", 0.0)

            simbase._sim_tran_last_progress = last_progress

            yield TranResult(
                data,
                node,
                highlevel_sim.netlister,
                progress,
                signal_kinds,
                mappings,
            )
            last_progress = progress

        # Check for completion and drain any remaining items after grace period.
        if not sim.is_running():
            if completion_time is None:
                completion_time = _time.time()
            if _time.time() - completion_time >= fallback_grace_period:
                while True:
                    try:
                        data_point = data_queue.get_nowait()
                    except _queue.Empty:
                        return

                    if data_point == "---ASYNC_SIM_SENTINEL---":
                        return

                    if not isinstance(data_point, dict):
                        continue

                    if "status" in data_point or "error" in data_point:
                        if data_point.get("status") in ("completed", "halted"):
                            return
                        continue

                    if callback:
                        callback(data_point)

                    data = data_point.get("data", {})
                    signal_kinds = data_point.get("signal_kinds", {})
                    progress = data_point.get("progress", 0.0)
                    simbase._sim_tran_last_progress = last_progress
                    yield TranResult(
                        data,
                        node,
                        highlevel_sim.netlister,
                        progress,
                        signal_kinds,
                    )
                    last_progress = progress


class SimBase(Cell):
    backend = Parameter(str, default="subprocess")

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

    def sim_ac(self, *args, backend=None, **kwargs):
        s = SimHierarchy(cell=self)
        backend = backend if backend is not None else self.backend
        sim = HighlevelSim(self.schematic, s, backend=backend)
        sim.ac(*args, **kwargs)
        return s

    def sim_tran_async(
        self,
        tstep,
        tstop,
        callback=None,
        buffer_size=10,
        enable_savecurrents=True,
        backend=None,
        fallback_sampling_ratio=100,
        disable_buffering=True,
    ):
        """Run async transient simulation.

        Args:
            tstep: Time step for the simulation
            tstop: Stop time for the simulation
            callback: Optional callback function for data updates
            buffer_size: Number of data points to buffer before sending
        """

        node = SimHierarchy()
        hl_backend = backend if backend is not None else self.backend
        highlevel_sim = HighlevelSim(
            self.schematic,
            node,
            enable_savecurrents=enable_savecurrents,
            backend=hl_backend,
        )

        with highlevel_sim.launch_ngspice() as sim:
            sim.load_netlist(highlevel_sim.netlister.out())

            data_queue = sim.tran_async(
                tstep, tstop, buffer_size=buffer_size, fallback_sampling_ratio=fallback_sampling_ratio, disable_buffering=disable_buffering
            )

            yield from stream_from_queue(
                self, sim, data_queue, highlevel_sim, node, callback
            )

    def sim_tran(self, tstep, tstop, backend=None, **kwargs):
        """Run sync transient simulation.

        Args:
            tstep: Time step for the simulation
            tstop: Stop time for the simulation
            enable_savecurrents: If True (default), enables .option savecurrents
        """

        s = SimHierarchy(cell=self)
        chosen_backend = backend if backend is not None else self.backend
        sim = HighlevelSim(self.schematic, s, backend=chosen_backend, **kwargs)
        sim.tran(tstep, tstop)
        return s


class LargeRingoscTb(SimBase):
    """51-stage ring oscillator testbench."""

    stages = Parameter(int, default=51)

    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.vss = Net()

        # Precreate stage nets and expose them as attributes for easier probing.
        net_names = [f"y{idx}" for idx in range(self.stages)]
        for name in net_names:
            s[name] = Net()

        inv_sym = Inv().symbol

        # Connect in a ring: each inverter drives the next, last feeds first.
        for idx in range(self.stages):
            a_name = net_names[idx - 1] if idx > 0 else net_names[-1]
            y_name = net_names[idx]
            a_net = s[a_name]
            y_net = s[y_name]
            pos = Vec2R(4 * idx, 2)
            inst = SchemInstance(inv_sym.portmap(vdd=s.vdd, vss=s.vss, a=a_net, y=y_net), pos=pos)
            setattr(s, f"inv{idx}", inst)

        # Supply and reference
        vdc = Vdc(dc=R("5")).symbol
        s.vsup = SchemInstance(vdc.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, -2))
        gnd = Gnd().symbol
        s.g = SchemInstance(gnd.portmap(p=s.vss), pos=Vec2R(-4, -2))

        s.outline = Rect4R(lx=-6, ly=-6, ux=4 * self.stages + 2, uy=8)

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


class RCAlterTestbench(Cell):
    """RC circuit for testing HighlevelSim alter operations"""

    @generate
    def schematic(self):
        s = Schematic(cell=self, outline=Rect4R(lx=0, ly=0, ux=10, uy=10))

        s.vin = Net()
        s.vout = Net()
        s.gnd = Net()

        s.v1 = SchemInstance(
            Vdc(dc=R(1)).symbol.portmap(p=s.vin, m=s.gnd), pos=Vec2R(0, 5)
        )
        s.r1 = SchemInstance(
            Res(r=R(1000)).symbol.portmap(p=s.vin, m=s.vout), pos=Vec2R(5, 5)
        )
        s.c1 = SchemInstance(
            Cap(c=R("1u")).symbol.portmap(p=s.vout, m=s.gnd), pos=Vec2R(8, 3)
        )
        s.gnd_conn = SchemInstance(Gnd().symbol.portmap(p=s.gnd), pos=Vec2R(0, 0))

        return s

@generate_func
def layoutgl_example() -> Layout:
    from ordec.lib.ihp130 import SG13G2
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)

    l % LayoutPoly(
        layer=layers.Metal1,
        vertices=[
            Vec2I(0, 0),
            Vec2I(0, 1000),
            Vec2I(1000, 1000),
            Vec2I(1000, 500),
            Vec2I(500, 500),
            Vec2I(500, 0),
        ],
    )
    l % LayoutPoly(
        layer=layers.Metal3.pin,
        vertices=[
            Vec2I(250, 250),
            Vec2I(250, 750),
            Vec2I(750, 750),
            Vec2I(750, 250),
        ],
    )
    l % LayoutLabel(
        layer=layers.Metal3.pin,
        pos=Vec2I(500,500),
        text='This example tests layout-gl.js!'
    )

    l % LayoutLabel(
        layer=layers.Metal4.pin,
        pos=Vec2I(1000, 0),
        text='Another label here'
    )
    return l
