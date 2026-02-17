# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from typing import Optional
from contextlib import contextmanager
import time

from ..core import *
from ..core.rational import R
from ..core.schema import SimType
from .ngspice import Ngspice
from ..schematic.netlister import Netlister
from .ngspice_common import Quantity, quantity_from_unit, strip_raw_name


def build_hier_schematic(simhier: SimHierarchy, schematic: Schematic):
    simhier.schematic = schematic

    build_hier_schematic_recursive(simhier, schematic, None)

def build_hier_schematic_recursive(simhier: SimHierarchy, schematic: Schematic, parent_inst: Optional[SimInstance]):
    for net in schematic.all(Net):
        simhier % SimNet(eref=net, parent_inst=parent_inst)

    for scheminst in schematic.all(SchemInstance):
        inst = simhier % SimInstance(eref=scheminst, parent_inst=parent_inst)
        try:
            subschematic = scheminst.symbol.cell.schematic
        except AttributeError:
            build_hier_symbol(simhier, scheminst.symbol, inst)
        else:
            inst.schematic = subschematic
            build_hier_schematic_recursive(simhier, subschematic, inst)

def build_hier_symbol(simhier: SimHierarchy, symbol: Symbol, parent_inst: SimInstance):
    for pin in symbol.all(Pin):
        simhier % SimNet(eref=pin, parent_inst=parent_inst)

class HighlevelSim:
    def __init__(
        self,
        top: Schematic,
        simhier: SimHierarchy,
        enable_savecurrents: bool = True,
    ):
        self.top = top

        self.directory = Directory()

        self.netlister = Netlister(self.directory, enable_savecurrents=enable_savecurrents)
        self.netlister.netlist_hier(self.top)

        print(self.netlister.out())

        self.simhier = simhier
        # build hierarchical simulation nodes
        build_hier_schematic(self.simhier, self.top)

        self._active_sim = None

    @contextmanager
    def launch_ngspice(self):
        with Ngspice.launch() as sim:
            for func in self.netlister.ngspice_setup_funcs:
                func(sim)
            yield sim

    def op(self):
        self.simhier.sim_type = SimType.DC
        
        with self.launch_ngspice() as sim:
            sim.load_netlist(self.netlister.out())
            for vtype, name, subname, value in sim.op():
                if vtype == "voltage":
                    try:
                        simnet = self.hier_simobj_of_name(name)
                    except KeyError:
                        # ignore internal nodes we don't map
                        continue
                    else:
                        simnet.dc_voltage = value
                elif vtype == "current":
                    if subname not in ("id", "branch", "i"):
                        continue
                    try:
                        siminstance = self.hier_simobj_of_name(name)
                    except KeyError:
                        continue
                    else:
                        siminstance.dc_current = value

    def hier_simobj_of_name(self, name: str) -> SimInstance|SimNet:
        return self.netlister.hier_simobj_of_name(self.simhier, name)


    def _run_simulation(self, sim_type, sim_method, *sim_args, **sim_kwargs):
        """Common simulation execution logic for tran and ac analyses."""
        self.simhier.sim_type = sim_type
        is_tran = sim_type == SimType.TRAN

        with self.launch_ngspice() as sim:
            sim.load_netlist(self.netlister.out())
            sim_array, info_vars = getattr(sim, sim_method)(*sim_args, **sim_kwargs)

        # Store SimArray and axis field names on the SimHierarchy root
        self.simhier.sim_data = sim_array
        for var in info_vars:
            qty = quantity_from_unit(var.unit, var.name)
            if qty == Quantity.TIME:
                self.simhier.time_field = var.name
            elif qty == Quantity.FREQUENCY:
                self.simhier.freq_field = var.name

        # Assign field names to SimNet/SimInstance nodes
        field_attr = 'trans_field' if is_tran else 'ac_field'

        for var in info_vars:
            qty = quantity_from_unit(var.unit, var.name)
            if qty in (Quantity.TIME, Quantity.FREQUENCY):
                continue

            stripped = strip_raw_name(var.name)
            try:
                if qty == Quantity.VOLTAGE:
                    simnet = self.hier_simobj_of_name(stripped)
                    setattr(simnet, field_attr, var.name)
                elif qty == Quantity.CURRENT:
                    if stripped.startswith("@") and "[" in stripped:
                        device_name = stripped.split("[")[0][1:]
                        siminstance = self.hier_simobj_of_name(device_name)
                    else:
                        siminstance = self.hier_simobj_of_name(stripped)
                    setattr(siminstance, field_attr, var.name)
            except KeyError:
                continue

    def tran(self, tstep, tstop):
        self._run_simulation(SimType.TRAN, "tran", tstep, tstop)

    def ac(self, *args):
        self._run_simulation(SimType.AC, "ac", *args)

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

                    if (
                        hasattr(simnet, "trans_voltage")
                        and simnet.trans_voltage is not None
                    ):
                        if i < len(signal_chars):
                            ident = signal_chars[i]
                        else:
                            ident = f"sig{i}"
                        signals_to_export.append(
                            (base_name, ident, simnet.trans_voltage)
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
