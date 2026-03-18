# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""High-level simulation interface bridging ORDB and ngspice.

Simulator takes a SimHierarchy, netlists it, drives ngspice via the
low-level Ngspice wrapper, and maps rawfile results back onto SimNet,
SimPin and SimParam nodes."""

import logging
from contextlib import contextmanager
from typing import Literal

logger = logging.getLogger(__name__)

from ..core import *
from ..core.rational import R
from ..core.schema import SimType
from .ngspice import Ngspice, ngspice_batch
from ..schematic.netlister import Netlister


def parse_signal_name(name):
    """Parse a rawfile-style ngspice signal name into (node_name, subname).

    Returns (node_name, subname) where subname is None for voltage nodes,
    or a string like "branch" / "is" for currents and device parameters.

    Examples:
        v(a)                -> ("a", None)
        i(vgnd)             -> ("vgnd", "branch")
        i(@m.xdut.mm2[is]) -> ("xdut.mm2", "is")
        @m.xdut.mm2[is]    -> ("xdut.mm2", "is")
    """
    def strip_type_prefix(s):
        """Strip single-letter SPICE device type prefix (e.g. 'm.' for
        MOSFET, 'r.' for resistor) if present."""
        if len(s) > 2 and s[1] == '.' and s[0].isalpha():
            return s[2:]
        return s

    if name.startswith("v(") and name.endswith(")"):
        return (name[2:-1], None)
    if name.startswith("i(") and name.endswith(")"):
        inner = name[2:-1]
        if inner.startswith("@") and "[" in inner:
            bracket = inner.index("[")
            return (strip_type_prefix(inner[1:bracket]),
                    inner[bracket+1:-1])
        return (inner, "branch")
    if name.startswith("@") and "[" in name:
        bracket = name.index("[")
        return (strip_type_prefix(name[1:bracket]),
                name[bracket+1:-1])
    return (name, None)


def Simulator(simhier: SimHierarchy, enable_savecurrents: bool = True,
              batch: bool = True) -> 'SimulatorBase':
    """Create a Simulator for the given SimHierarchy.

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

    def _store_results(self, sim_array: SimArray):
        """Store SimArray and assign field names to SimNet/SimPin/SimParam."""
        sim_type = self.simhier.sim_type
        self.simhier.sim_data = sim_array

        if sim_type == SimType.DCSWEEP:
            if not sim_array.fields:
                raise ValueError("DC sweep returned no fields")
            # First field in ngspice DC rawfiles is the swept source value.
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
                    siminstance = self.hier_simobj_of_name(node_name)
                    pin_map = siminstance.eref.symbol.cell.ngspice_current_pins()
                    if subname in pin_map:
                        pin = getattr(siminstance.eref.symbol, pin_map[subname])
                        existing = list(self.simhier.all(
                            SimPin.instance_eref_idx.query((siminstance, pin))))
                        if existing:
                            # TODO: avoid duplicate signals in the rawfile
                            # instead of skipping them here.
                            logger.warning(
                                "duplicate current signal %r for %s, skipping",
                                fid, node_name)
                            continue
                        simpin = self.simhier % SimPin(instance=siminstance, eref=pin)
                        simpin.current_field = fid
                    else:
                        simparam = self.simhier % SimParam(
                            instance=siminstance, name=subname)
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
        commands = []
        for func in self.netlister.ngspice_setup_funcs:
            commands.extend(func())
        return ngspice_batch(
            self.netlister.out(),
            spiceinit_commands=commands,
        )

    def op(self, save_params=False):
        self.simhier.sim_type = SimType.DC
        if save_params:
            self._save_all_params()
        self.netlister.add(".op")
        self._store_results(self._run())

    def tran(self, tstep, tstop, save_params=False):
        self.simhier.sim_type = SimType.TRAN
        if save_params:
            self._save_all_params()
        self.netlister.add(
            ".tran", R(tstep).compat_str(), R(tstop).compat_str())
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
        with Ngspice.launch() as sim:
            for func in self.netlister.ngspice_setup_funcs:
                for cmd in func():
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
        self.simhier.sim_type = SimType.DC
        with self._launch(save_params) as sim:
            self._store_results(sim.op())

    def tran(self, tstep, tstop, save_params=False):
        self.simhier.sim_type = SimType.TRAN
        with self._launch(save_params) as sim:
            self._store_results(sim.tran(tstep, tstop))

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
