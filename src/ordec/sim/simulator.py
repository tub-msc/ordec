# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""High-level simulation interface bridging ORDB and ngspice.

Simulator takes a SimHierarchy, netlists it, runs ngspice in batch mode,
and maps rawfile results back onto SimNet, SimPin and SimParam nodes."""

import logging
import os
from typing import Literal

logger = logging.getLogger(__name__)

from ..core import *
from ..core.context import NodeContext
from .ngspice import NgspiceSetup, ngspice_batch
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


class Simulator:
    """Batch-mode ngspice simulator.

    Netlists a SimHierarchy, runs ngspice in batch mode (streaming results
    to disk), and maps rawfile results back onto SimNet, SimPin and
    SimParam nodes. Prefer the :meth:`SimHierarchy.simulate` convenience
    method over constructing this directly, e.g. ``simhier.simulate().op()``
    instead of ``Simulator(simhier).op()``.

    Args:
        simhier: The simulation hierarchy to simulate.
        enable_savecurrents: Enable .option savecurrents in the netlist.
        corner: Process corner, interpreted by the PDK in use (e.g.
            :class:`ordec.lib.ihp130.Corner` for ihp130 or a string auch as
            ``'ss'`` for sky130). None selects the PDK's typical corner.
        temp: Simulation temperature in degrees C. None keeps ngspice's
            default of 27 degrees C.
    """

    def __init__(self, simhier: SimHierarchy, enable_savecurrents: bool = True,
                 corner=None, temp=None):
        self.simhier = simhier
        self.top = self.simhier.schematic

        self.directory = Directory()

        progress("Netlisting")
        self.netlister = Netlister(
            self.directory, enable_savecurrents=enable_savecurrents,
            corner=corner, temp=temp)
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

    def _param_save_directives(self):
        """
        Yield ngspice save directives for all device parameters known to the
        instantiated cells (via ngspice_save_params).

        Devices below the top level must be referenced with their device
        type letter prefixed (e.g. ``@m.xdut.mm1[gm]``). PDK cells that
        wrap the actual device in a model subcircuit report the inner
        device name via ngspice_internal_device (e.g. ihp130's
        ``nsg13_lv_nmos``), which is appended to the path.
        """
        for si in self.simhier.all(SimInstance):
            if si.schematic is not None:
                continue
            cell = si.eref.symbol.cell
            params = cell.ngspice_save_params()
            if not params:
                continue
            name = self.netlister.name_hier_simobj(si)
            internal = cell.ngspice_internal_device()
            if internal is not None:
                name = f"{internal[0]}.{name}.{internal}"
            elif "." in name:
                name = f"{name.split('.')[-1][0]}.{name}"
            for param in params:
                yield f"@{name}[{param}]"

    def _store_results(self, sim_array: SimArray):
        """Assign result columns to SimNet/SimPin/SimParam nodes."""
        sim_type = self.simhier.sim_type
        if not sim_array.fields:
            raise ValueError("Simulation returned no fields")

        # The independent variable is field 0 in the rawfile, except for
        # op results, which have none. All result columns of the run
        # share this axis; it is stored once, as a SimScale node.
        if sim_type == SimType.OP:
            data_fields = list(enumerate(sim_array.fields))
        else:
            scale = sim_array.column(0)
            # AC rawfiles store the frequency scale as complex with zero
            # imaginary part; .real is a zero-copy f8 view into the same
            # buffer.
            if scale.dtype == 'c16':
                scale = scale.real
            self.simhier % SimScale(pos=0, column=scale)
            data_fields = list(enumerate(sim_array.fields))[1:]

        for i, f in data_fields:
            fid = f.fid
            column = sim_array.column(i)
            node_name, subname = parse_signal_name(fid)
            try:
                if subname is None:
                    simnet = self.hier_simobj_of_name(node_name)
                    simnet.voltage = column
                else:
                    # Try progressively shorter paths for internal model nodes
                    siminstance = None
                    remaining_path = []
                    parts = node_name.split(".")
                    for plen in range(len(parts), 0, -1):
                        try_path = ".".join(parts[:plen])
                        try:
                            siminstance = self.hier_simobj_of_name(try_path)
                            remaining_path = parts[plen:]
                            break
                        except KeyError:
                            continue
                    if siminstance is None:
                        continue

                    if remaining_path:
                        full_subname = ".".join(remaining_path) + "#" + subname
                    else:
                        full_subname = subname

                    # siminstance can be a hierarchical cell here; only leaf
                    # cells carry the ngspice_* hooks.
                    cell = siminstance.eref.symbol.cell
                    is_leaf = isinstance(cell, SimLeafCell)
                    if is_leaf:
                        pin_map = cell.ngspice_current_pins()
                    else:
                        pin_map = {}

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
                        simpin.current = column
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
                        simpin.current = column
                    elif ":" in fid:
                        # Port currents (i(inst:port)) that couldn't be mapped to SimPins
                        continue
                    else:
                        # Parameters of a device wrapped in a PDK model
                        # subcircuit belong to the wrapping instance:
                        if is_leaf:
                            internal = cell.ngspice_internal_device()
                            if internal is not None and remaining_path == [internal]:
                                full_subname = subname
                        simparam = self.simhier % SimParam(
                            instance=siminstance, name=full_subname)
                        simparam.value = column
            except KeyError:
                continue

    def _save_all_params(self):
        """Add .save directives to the netlist for device parameters."""
        self.netlister.add(".save all")
        for directive in self._param_save_directives():
            self.netlister.add(f".save {directive}")

    def _run(self, tran_tstop=None) -> SimArray:
        commands, env = self.collect_ngspice_setup()
        return ngspice_batch(
            self.netlister.out(),
            spiceinit_commands=commands,
            env=env,
            tran_tstop=tran_tstop,
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
        self._store_results(self._run(tran_tstop=R(tstop)))

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

    def temp_sweep(self, start, stop, step_count: int, save_params=False):
        """
        DC sweep over temperate variable (ngspice ``.dc temp``) from ``start``
        to ``stop`` degrees C in ``step_count`` points. The optional ``temp``
        given to :class:`Simulator` is overridden by this sweep.
        """
        if step_count < 2:
            raise ValueError("step_count must be >= 2")
        start = R(start)
        stop = R(stop)
        step = (stop - start) / R(step_count - 1)
        self.simhier.sim_type = SimType.DCSWEEP
        if save_params:
            self._save_all_params()
        self.netlister.add(
            ".dc", "temp",
            start.compat_str(), stop.compat_str(), step.compat_str())
        self._store_results(self._run())
