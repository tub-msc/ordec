# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from contextlib import contextmanager
import time

from ..core import *
from ..core.rational import R
from ..core.schema import SimType
from .ngspice import Ngspice
from ..schematic.netlister import Netlister
from .ngspice_common import parse_signal_name

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

    def _create_simpin(self, siminstance, subname):
        """Create a SimPin for a ngspice current subname, or return None."""
        cell = siminstance.eref.symbol.cell
        pin_map = cell.ngspice_current_pins()
        if subname not in pin_map:
            return None
        pin = getattr(siminstance.eref.symbol, pin_map[subname])
        return self.simhier % SimPin(instance=siminstance, eref=pin)

    def _create_simparam(self, siminstance, param_name):
        """Create a SimParam for a device parameter."""
        return self.simhier % SimParam(instance=siminstance, name=param_name)

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
                    simpin = self._create_simpin(siminstance, subname)
                    if simpin is not None:
                        simpin.current_field = fid
                    else:
                        simparam = self._create_simparam(
                            siminstance, subname)
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

    def _parse_timescale_factor(self, timescale: str) -> float:
        if not isinstance(timescale, str) or not timescale.strip():
            raise ValueError(
                "timescale must be a non-empty string like '1us' or '10 ns'"
            )

        try:
            ts_rational = R(timescale)
        except Exception as e:
            raise ValueError(f"Invalid timescale '{timescale}': {e}")

        try:
            timescale_seconds = float(ts_rational)
        except Exception as e:
            raise ValueError(f"Could not convert parsed timescale to float: {e}")

        if timescale_seconds <= 0:
            raise ValueError("Timescale must be greater than zero")
        return 1.0 / timescale_seconds

    def export_to_vcd(
        self, filename="simulation.vcd", signal_names=None, timescale="1u"
    ):
        if self.simhier.sim_type is None:
            raise ValueError("No simulation results available. Run a simulation first.")

        if self.simhier.sim_type != SimType.TRAN:
            raise ValueError(
                f"VCD export only supported for transient simulations. Current simulation type: {self.simhier.sim_type}"
            )

        if not hasattr(self.simhier, "time") or not self.simhier.time:
            raise ValueError("No time data available for VCD export")

        # determine conversion factor from seconds to requested units
        try:
            time_to_units = self._parse_timescale_factor(timescale)
        except ValueError as e:
            raise ValueError(f"Invalid timescale: {e}")

        try:
            with open(filename, "w") as vcd_file:
                # Header
                vcd_file.write("$date\n")
                vcd_file.write(f"   {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                vcd_file.write("$end\n")
                vcd_file.write("$version\n")
                vcd_file.write("   ORDeC VCD Generator\n")
                vcd_file.write("$end\n")
                vcd_file.write(f"$timescale {timescale} $end\n")

                # Collect signals with transient voltage data
                signals_to_export = []
                # limited set of single-char VCD identifiers
                signal_chars = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"

                for i, simnet in enumerate(self.simhier.all(SimNet)):
                    base_name = simnet.full_path_str().split(".")[-1]

                    if signal_names is not None and base_name not in signal_names:
                        continue

                    if simnet.voltage is not None:
                        if i < len(signal_chars):
                            ident = signal_chars[i]
                        else:
                            ident = f"sig{i}"
                        signals_to_export.append(
                            (base_name, ident, simnet.voltage)
                        )

                if not signals_to_export:
                    raise ValueError(
                        "No signals with transient voltage data found for VCD export"
                    )

                # Definitions
                vcd_file.write("$scope module top $end\n")
                for name, ident, _ in signals_to_export:
                    vcd_file.write(f"$var real 64 {ident} {name} $end\n")
                vcd_file.write("$upscope $end\n")
                vcd_file.write("$enddefinitions $end\n")

                # Initial values at time 0
                vcd_file.write("#0\n")
                for _, ident, voltage_data in signals_to_export:
                    if voltage_data and len(voltage_data) > 0:
                        # Represent real value with default float formatting
                        vcd_file.write(f"r{voltage_data[0]} {ident}\n")

                # Value changes at each time point, converted to requested timescale
                time_data = self.simhier.time
                for time_idx in range(1, len(time_data)):
                    # convert seconds -> requested timescale integer units
                    time_units = int(time_data[time_idx] * time_to_units)
                    vcd_file.write(f"#{time_units}\n")
                    for _, ident, voltage_data in signals_to_export:
                        if len(voltage_data) > time_idx:
                            vcd_file.write(f"r{voltage_data[time_idx]} {ident}\n")

            return True

        except Exception as e:
            raise ValueError(f"Error generating VCD file: {e}")

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
