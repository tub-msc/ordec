# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""High-level simulation interface bridging ORDB and ngspice.

Simulator takes a SimHierarchy, netlists it, drives ngspice via the
low-level Ngspice wrapper, and maps rawfile results back onto SimNet,
SimPin and SimParam nodes."""

import logging
import os
from contextlib import contextmanager
from typing import Literal

logger = logging.getLogger(__name__)

from ..core import *
from ..core.context import NodeContext
from .ngspice import Ngspice, NgspiceSetup, ngspice_batch
from ..schematic import Netlister


def parse_signal_name(name):
    """Parse a rawfile-style ngspice signal name into (node_name, subname).

    Returns (node_name, subname) where subname is None for voltage nodes,
    or a string like "branch" / "is" for currents and device parameters.
    """
    def strip_type_prefix(s):
        """Strip single-letter SPICE device type prefix (e.g. 'm.', 'n.')."""
        if len(s) > 2 and s[1] == '.' and s[0].isalpha():
            return s[2:]
        return s

    if name.startswith("v(") and name.endswith(")"):
        inner = name[2:-1]
        if inner.startswith("@") and "[" in inner:
            bracket = inner.index("[")
            return (strip_type_prefix(inner[1:bracket]), inner[bracket+1:-1])
        if "#" in inner:
            inner = strip_type_prefix(inner)
            path, param = inner.rsplit("#", 1)
            return (path, param)
        return (inner, None)
    if name.startswith("i(") and name.endswith(")"):
        inner = name[2:-1]
        if inner.startswith("@") and "[" in inner:
            bracket = inner.index("[")
            return (strip_type_prefix(inner[1:bracket]), inner[bracket+1:-1])
        if ":" in inner:
            inst, port = inner.rsplit(":", 1)
            return (inst, port)
        return (inner, "branch")
    if name.startswith("@") and "[" in name:
        bracket = name.index("[")
        return (strip_type_prefix(name[1:bracket]), name[bracket+1:-1])
    return (name, None)


def Simulator(simhier: SimHierarchy, enable_savecurrents: bool = True,
              batch: bool = True) -> 'SimulatorBase':
    """Create a Simulator for the given SimHierarchy.

    Prefer the :meth:`SimHierarchy.simulate` convenience method over calling
    this directly, e.g. ``simhier.simulate(batch=True).op()`` instead of
    ``Simulator(simhier, batch=True).op()``.

    Args:
        simhier: The simulation hierarchy to simulate.
        enable_savecurrents: Enable .option savecurrents in the netlist.
        batch: If True (default), use ngspice batch mode which streams
            results to disk. If False, use piped mode which keeps all
            data in RAM.
    """
    cls = SimulatorNgspiceBatch if batch else SimulatorNgspicePiped
    return cls(simhier, enable_savecurrents=enable_savecurrents)


class SimulatorBase:
    """Shared netlisting, result storage, and query logic."""

    def __init__(self, simhier: SimHierarchy, enable_savecurrents: bool = True):
        self.simhier = simhier
        self.top = self.simhier.schematic

        self.directory = Directory()

        self.netlister = Netlister(
            self.directory, enable_savecurrents=enable_savecurrents)
        self.netlister.netlist_hier(self.top)

    def hier_simobj_of_name(self, name: str) -> SimInstance|SimNet:
        return self.netlister.hier_simobj_of_name(self.simhier, name)

    def ctx(self):
        """Return a context for ORD simulation view generators."""
        return NodeContext(self)

    def collect_ngspice_setup(self):
        commands = []
        env = dict(os.environ)
        for func in self.netlister.ngspice_setup_funcs:
            setup = func()
            commands.extend(setup.commands)
            for k, v in setup.env.items():
                if k in env and env[k] != v:
                    raise ValueError(
                        f"Conflicting ngspice env for {k!r}: "
                        f"{env[k]!r} vs {v!r}")
                env[k] = v
        return commands, env

    def _store_results(self, sim_array: SimArray):
        """Store SimArray and assign field names to SimNet/SimPin/SimParam."""
        sim_type = self.simhier.sim_type
        self.simhier.sim_data = sim_array

        if sim_type == SimType.DCSWEEP:
            if not sim_array.fields:
                raise ValueError("DC sweep returned no fields")
            self.simhier.sweep_field = sim_array.fields[0].fid

        for f in sim_array.fields:
            fid = f.fid
            if fid == "time":
                self.simhier.time_field = fid
                continue
            if fid.startswith("frequency"):
                self.simhier.freq_field = fid
                continue
            if sim_type == SimType.DCSWEEP and fid == self.simhier.sweep_field:
                continue

            node_name, subname = parse_signal_name(fid)
            try:
                if subname is None:
                    simnet = self.hier_simobj_of_name(node_name)
                    simnet.voltage_field = fid
                else:
                    # Try progressively shorter paths for internal model nodes
                    siminstance = None
                    remaining_path = []
                    parts = node_name.split(".")
                    for i in range(len(parts), 0, -1):
                        try_path = ".".join(parts[:i])
                        try:
                            siminstance = self.hier_simobj_of_name(try_path)
                            remaining_path = parts[i:]
                            break
                        except KeyError:
                            continue
                    if siminstance is None:
                        continue

                    if remaining_path:
                        full_subname = ".".join(remaining_path) + "#" + subname
                    else:
                        full_subname = subname

                    cell = siminstance.eref.symbol.cell
                    pin_map = cell.ngspice_current_pins() if hasattr(cell, 'ngspice_current_pins') else {}

                    if subname in pin_map and not remaining_path:
                        pin = getattr(siminstance.eref.symbol, pin_map[subname])
                        existing = list(self.simhier.all(
                            SimPin.instance_eref_idx.query((siminstance, pin))))
                        if existing:
                            logger.warning(
                                "duplicate current signal %r for %s, skipping",
                                fid, node_name)
                            continue
                        simpin = self.simhier % SimPin(instance=siminstance, eref=pin)
                        simpin.current_field = fid
                    elif siminstance.schematic is not None and not remaining_path:
                        pin = None
                        try:
                            net = siminstance.schematic[subname]
                            if hasattr(net, 'pin') and net.pin is not None:
                                pin = net.pin
                        except (KeyError, AttributeError, QueryException):
                            pass
                        if pin is None:
                            continue
                        existing = list(self.simhier.all(
                            SimPin.instance_eref_idx.query((siminstance, pin))))
                        if existing:
                            continue
                        simpin = self.simhier % SimPin(instance=siminstance, eref=pin)
                        simpin.current_field = fid
                    elif ":" in fid:
                        # Port currents (i(inst:port)) that couldn't be mapped to SimPins
                        continue
                    else:
                        simparam = self.simhier % SimParam(
                            instance=siminstance, name=full_subname)
                        simparam.field = fid
            except KeyError:
                continue


class SimulatorNgspiceBatch(SimulatorBase):
    """Batch-mode simulator: streams results to disk via ``ngspice -b``."""

    def _save_all_params(self):
        """Add .save directives to the netlist for device parameters."""
        self.netlister.add(".save all")
        for si in self.simhier.all(SimInstance):
            if si.schematic is not None:
                continue
            cell = si.eref.symbol.cell
            params = cell.ngspice_save_params()
            if not params:
                continue
            device_name = self.netlister.name_hier_simobj(si)
            for param in params:
                self.netlister.add(f".save @{device_name}[{param}]")

    def _run(self) -> SimArray:
        commands, env = self.collect_ngspice_setup()
        return ngspice_batch(
            self.netlister.out(),
            spiceinit_commands=commands,
            env=env,
        )

    def op(self, save_params=False):
        self.simhier.sim_type = SimType.OP
        if save_params:
            self._save_all_params()
        self.netlister.add(".op")
        self._store_results(self._run())

    def tran(self, tstep, tstop, tstart=R(0), tmax=None, uic=False,
             save_params=False):
        """
        Run a transient analysis (ngspice ``.tran``).

        Args:
            tstep: Output/save interval in seconds (not the internal step).
            tstop: Stop time in seconds.
            tstart: Time at which output recording starts; the simulation
                itself always begins at t=0.
            tmax: Optional cap on the internal timestep in seconds.
            uic: "Use initial conditions": skip the initial DC operating
                point and start from the ``ic=`` values of capacitors and
                inductors (e.g. Cap.ic, Cmim.ic); all other node voltages
                start at 0. Useful to precharge a state deterministically
                or when the DC solution is ill-defined (oscillators).
            save_params: Also record the device parameters listed by each
                cell's ngspice_save_params().
        """
        self.simhier.sim_type = SimType.TRAN
        if save_params:
            self._save_all_params()
        args = [R(tstep).compat_str(), R(tstop).compat_str(),
                R(tstart).compat_str()]
        if tmax is not None:
            args.append(R(tmax).compat_str())
        if uic:
            args.append("uic")
        self.netlister.add(".tran", *args)
        self._store_results(self._run())

    def ac(self, scheme: Literal["dec", "oct", "lin"], n: int,
           fstart: R, fstop: R, save_params=False):
        self.simhier.sim_type = SimType.AC
        if save_params:
            self._save_all_params()
        self.netlister.add(
            ".ac", scheme, str(n),
            R(fstart).compat_str(), R(fstop).compat_str())
        self._store_results(self._run())

    def dc_sweep(self, source, vstart, vstop, step_count: int, save_params=False):
        if step_count < 2:
            raise ValueError("step_count must be >= 2")
        source_name = self.directory.existing_name_node(source)
        vstart = R(vstart)
        vstop = R(vstop)
        vstep = (vstop - vstart) / R(step_count - 1)
        self.simhier.sim_type = SimType.DCSWEEP
        if save_params:
            self._save_all_params()
        self.netlister.add(
            ".dc", source_name,
            vstart.compat_str(), vstop.compat_str(), vstep.compat_str())
        self._store_results(self._run())


class SimulatorNgspicePiped(SimulatorBase):
    """Piped-mode simulator: keeps a persistent ``ngspice -p`` process.

    All simulation data accumulates in RAM, so this is not suitable
    for simulations with very large results.
    """

    @contextmanager
    def _launch(self, save_params=False):
        commands, env = self.collect_ngspice_setup()
        with Ngspice.launch(env=env) as sim:
            for cmd in commands:
                sim.command(cmd)
            sim.load_netlist(self.netlister.out())
            if save_params:
                self._save_all_params(sim)
            yield sim

    def _save_all_params(self, sim):
        """Issue ngspice save commands for all known device parameters."""
        sim.command("save all")
        for si in self.simhier.all(SimInstance):
            if si.schematic is not None:
                continue
            cell = si.eref.symbol.cell
            params = cell.ngspice_save_params()
            if not params:
                continue
            device_name = self.netlister.name_hier_simobj(si)
            for param in params:
                sim.command(f"save @{device_name}[{param}]")

    def op(self, save_params=False):
        self.simhier.sim_type = SimType.OP
        with self._launch(save_params) as sim:
            self._store_results(sim.op())

    def tran(self, tstep, tstop, tstart=R(0), tmax=None, uic=False,
             save_params=False):
        """
        Run a transient analysis; see SimulatorNgspiceBatch.tran for the
        meaning of the arguments.
        """
        self.simhier.sim_type = SimType.TRAN
        with self._launch(save_params) as sim:
            self._store_results(
                sim.tran(tstep, tstop, tstart=tstart, tmax=tmax, uic=uic))

    def ac(self, scheme: Literal["dec", "oct", "lin"], n: int,
           fstart: R, fstop: R, save_params=False):
        self.simhier.sim_type = SimType.AC
        with self._launch(save_params) as sim:
            self._store_results(sim.ac(scheme, n, fstart, fstop))

    def dc_sweep(self, source, vstart, vstop, step_count: int, save_params=False):
        if step_count < 2:
            raise ValueError("step_count must be >= 2")
        source_name = self.directory.existing_name_node(source)
        vstart = R(vstart)
        vstop = R(vstop)
        vstep = (vstop - vstart) / R(step_count - 1)
        self.simhier.sim_type = SimType.DCSWEEP
        with self._launch(save_params) as sim:
            self._store_results(sim.dc(source_name, vstart, vstop, vstep))
