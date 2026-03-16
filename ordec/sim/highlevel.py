# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""High-level simulation interface bridging ORDB and ngspice.

HighlevelSim takes a SimHierarchy, netlists it, drives ngspice via the
low-level Ngspice wrapper, and maps rawfile results back onto SimNet,
SimPin and SimParam nodes."""

from contextlib import contextmanager

from ..core import *
from ..core.rational import R
from ..core.schema import SimType
from .ngspice import Ngspice
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


class HighlevelSim:
    def __init__(self, simhier: SimHierarchy, enable_savecurrents: bool = True):
        self.simhier = simhier
        self.top = self.simhier.schematic

        self.directory = Directory()

        self.netlister = Netlister(self.directory, enable_savecurrents=enable_savecurrents)
        self.netlister.netlist_hier(self.top)

    @contextmanager
    def launch_ngspice(self):
        with Ngspice.launch() as sim:
            for func in self.netlister.ngspice_setup_funcs:
                func(sim)
            yield sim

    def _save_params(self, sim):
        """Issue ngspice save commands for all known device parameters."""
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
        with self.launch_ngspice() as sim:
            sim.load_netlist(self.netlister.out())
            if save_params:
                self._save_params(sim)
            sim_array = sim.op()
        self._store_results(sim_array)

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
                        simpin = self.simhier % SimPin(instance=siminstance, eref=pin)
                        simpin.current_field = fid
                    else:
                        simparam = self.simhier % SimParam(
                            instance=siminstance, name=subname)
                        simparam.field = fid
            except KeyError:
                continue

    def tran(self, tstep, tstop, save_params=False):
        self.simhier.sim_type = SimType.TRAN
        with self.launch_ngspice() as sim:
            sim.load_netlist(self.netlister.out())
            if save_params:
                self._save_params(sim)
            sim_array = sim.tran(tstep, tstop)
        self._store_results(sim_array)

    def ac(self, *args, save_params=False):
        self.simhier.sim_type = SimType.AC
        with self.launch_ngspice() as sim:
            sim.load_netlist(self.netlister.out())
            if save_params:
                self._save_params(sim)
            sim_array = sim.ac(*args)
        self._store_results(sim_array)

    def dc_sweep(self, source, vstart, vstop, step_count: int, save_params=False):
        if step_count < 2:
            raise ValueError("step_count must be >= 2")
        source_name = self.directory.existing_name_node(source)
        vstart = R(vstart)
        vstop = R(vstop)
        vstep = (vstop - vstart) / R(step_count - 1)
        self.simhier.sim_type = SimType.DCSWEEP
        with self.launch_ngspice() as sim:
            sim.load_netlist(self.netlister.out())
            if save_params:
                self._save_params(sim)
            sim_array = sim.dc(source_name, vstart, vstop, vstep)
        self._store_results(sim_array)

    def get_component_netlist_name(self, component_instance):
        return self.netlister.name_hier_simobj(component_instance)

    def find_component_by_ref_name(self, ref_name):
        for sim_instance in self.simhier.all(SimInstance):
            if (
                hasattr(sim_instance, "eref")
                and hasattr(sim_instance.eref, "full_path_str")
                and sim_instance.eref.full_path_str().endswith(ref_name)
            ):
                return sim_instance
        return None

    def find_sim_instance_from_schem_instance(self, schem_instance):
        for sim_instance in self.simhier.all(SimInstance):
            if hasattr(sim_instance, "eref") and sim_instance.eref == schem_instance:
                return sim_instance
        return None
