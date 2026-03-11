# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from contextlib import contextmanager
import time

from ..core import *
from ..core.rational import R
from ..core.schema import SimType
from .ngspice import Ngspice
from ..schematic.netlister import Netlister
from ..core.simarray import Quantity
from .ngspice_common import strip_raw_name

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
        pin_map = getattr(cell, 'ngspice_current_pins', {})
        if subname not in pin_map:
            return None
        pin_attr = pin_map[subname]
        pin = getattr(siminstance.eref.symbol, pin_attr)
        return self.simhier % SimPin(instance=siminstance, eref=pin)

    def _create_simparam(self, siminstance, param_name):
        """Create a SimParam for a device parameter."""
        return self.simhier % SimParam(instance=siminstance, name=param_name)

    def _extract_device_subname(self, stripped):
        """Extract (device_name, subname) from a stripped field name."""
        if stripped.startswith("@") and "[" in stripped:
            bracket_pos = stripped.index("[")
            device_name = stripped[1:bracket_pos]
            subname = stripped[bracket_pos + 1:-1]
            return device_name, subname
        elif stripped.endswith("#branch"):
            device_name = stripped.removesuffix("#branch")
            return device_name, "branch"
        return None, None

    def _save_params(self, sim):
        """Issue ngspice save commands for all known device parameters."""
        for si in self.simhier.all(SimInstance):
            if si.schematic is not None:
                continue
            cell = si.eref.symbol.cell
            params = getattr(cell, 'ngspice_save_params', [])
            if not params:
                continue
            device_name = self.netlister.name_hier_simobj(si)
            for param in params:
                sim.command(f"save @{device_name}[{param}]")

    def _query_op_params(self, sim):
        """Query device parameters after op and store as SimParam dc_value."""
        import re
        from .ngspice_common import NgspiceError
        for si in self.simhier.all(SimInstance):
            if si.schematic is not None:
                continue
            cell = si.eref.symbol.cell
            params = getattr(cell, 'ngspice_save_params', [])
            if not params:
                continue
            device_name = self.netlister.name_hier_simobj(si)
            for param in params:
                try:
                    result = sim.command(f"print @{device_name}[{param}]")
                except NgspiceError:
                    continue
                for line in result.split("\n"):
                    m = re.match(
                        r"@[^\[]+\[[^\]]+\]\s*=\s*([0-9.\-+e]+)", line)
                    if m:
                        simparam = self._create_simparam(
                            si, param)
                        simparam.dc_value = float(m.group(1))
                        break

    def op(self, save_params=False):
        self.simhier.sim_type = SimType.DC

        with self.launch_ngspice() as sim:
            sim.load_netlist(self.netlister.out())
            for qty, name, subname, value in sim.op():
                if qty == Quantity.VOLTAGE:
                    try:
                        simnet = self.hier_simobj_of_name(name)
                    except KeyError:
                        continue
                    else:
                        simnet.dc_voltage = value
                elif qty == Quantity.CURRENT:
                    try:
                        siminstance = self.hier_simobj_of_name(name)
                    except KeyError:
                        continue
                    simpin = self._create_simpin(siminstance, subname)
                    if simpin is not None:
                        simpin.dc_current = value
                elif qty == Quantity.PARAMETER:
                    try:
                        siminstance = self.hier_simobj_of_name(name)
                    except KeyError:
                        continue
                    simparam = self._create_simparam(
                        siminstance, subname)
                    simparam.dc_value = value

            if save_params:
                self._query_op_params(sim)

    def hier_simobj_of_name(self, name: str) -> SimInstance|SimNet:
        return self.netlister.hier_simobj_of_name(self.simhier, name)


    def _run_simulation(self, sim_type, sim_method, *sim_args,
                        save_params=False, **sim_kwargs):
        """Common simulation execution logic for tran/ac/dc-sweep analyses."""
        self.simhier.sim_type = sim_type

        with self.launch_ngspice() as sim:
            sim.load_netlist(self.netlister.out())
            if save_params:
                self._save_params(sim)
            sim_array = getattr(sim, sim_method)(*sim_args, **sim_kwargs)

        # Store SimArray and axis field names on the SimHierarchy root
        self.simhier.sim_data = sim_array
        for f in sim_array.fields:
            if f.quantity == Quantity.TIME:
                self.simhier.time_field = f.fid
            elif f.quantity == Quantity.FREQUENCY:
                self.simhier.freq_field = f.fid
        if sim_type == SimType.DCSWEEP:
            if not sim_array.fields:
                raise ValueError("DC sweep returned no fields")
            # First field in ngspice DC rawfiles is the swept source value.
            self.simhier.sweep_field = sim_array.fields[0].fid

        # Assign field names to SimNet/SimPin/SimParam nodes.
        for f in sim_array.fields:
            if f.quantity in (Quantity.TIME, Quantity.FREQUENCY):
                continue
            if sim_type == SimType.DCSWEEP and f.fid == self.simhier.sweep_field:
                continue

            stripped = strip_raw_name(f.fid)
            try:
                if f.quantity == Quantity.VOLTAGE:
                    simnet = self.hier_simobj_of_name(stripped)
                    simnet.voltage_field = f.fid
                elif f.quantity == Quantity.CURRENT:
                    device_name, subname = self._extract_device_subname(stripped)
                    if device_name is None:
                        continue
                    siminstance = self.hier_simobj_of_name(device_name)
                    simpin = self._create_simpin(siminstance, subname)
                    if simpin is not None:
                        simpin.current_field = f.fid
                elif f.quantity == Quantity.PARAMETER:
                    device_name, subname = self._extract_device_subname(stripped)
                    if device_name is None:
                        continue
                    siminstance = self.hier_simobj_of_name(device_name)
                    simparam = self._create_simparam(
                        siminstance, subname)
                    simparam.field = f.fid
            except KeyError:
                continue

    def tran(self, tstep, tstop, save_params=False):
        self._run_simulation(SimType.TRAN, "tran", tstep, tstop,
                             save_params=save_params)

    def ac(self, *args, save_params=False):
        self._run_simulation(SimType.AC, "ac", *args, save_params=save_params)

    def dc_sweep(self, source, vstart, vstop, step_count: int, save_params=False):
        if step_count < 2:
            raise ValueError("step_count must be >= 2")
        source_name = self.directory.existing_name_node(source)
        vstart = R(vstart)
        vstop = R(vstop)
        vstep = (vstop - vstart) / R(step_count - 1)
        self._run_simulation(
            SimType.DCSWEEP,
            "dc",
            source_name,
            vstart,
            vstop,
            vstep,
            save_params=save_params,
        )

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
