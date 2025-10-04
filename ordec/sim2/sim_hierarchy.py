# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from typing import Optional
from contextlib import contextmanager
import time

from ..core import *
from ..core.rational import R
from ..core.schema import SimType
from .ngspice import Ngspice, Netlister
from .ngspice_common import SignalKind


def build_hier_symbol(simhier, symbol):
    simhier.schematic = symbol
    for pin in symbol.all(Pin):
        full = pin.full_path_str()
        parts = full.split(".")
        node = simhier
        for part in parts[:-1]:
            if not hasattr(node, part):
                setattr(node, part, SimHierarchy())
            node = getattr(node, part)
        setattr(node, parts[-1], SimNet(eref=pin))


def build_hier_schematic(simhier, schematic):
    simhier.schematic = schematic
    for net in schematic.all(Net):
        full = net.full_path_str()
        parts = full.split(".")
        node = simhier
        for part in parts[:-1]:
            if not hasattr(node, part):
                setattr(node, part, SimHierarchy())
            node = getattr(node, part)
        setattr(node, parts[-1], SimNet(eref=net))

    for inst in schematic.all(SchemInstance):
        full = inst.full_path_str()
        parts = full.split(".")
        node = simhier
        for part in parts[:-1]:
            if not hasattr(node, part):
                setattr(node, part, SimHierarchy())
            node = getattr(node, part)
        setattr(node, parts[-1], SimInstance(eref=inst))
        subnode = getattr(node, parts[-1])
        try:
            subschematic = inst.symbol.cell.schematic
        except AttributeError:
            build_hier_symbol(subnode, inst.symbol)
        else:
            build_hier_schematic(subnode, subschematic)


class AlterSession:
    def __init__(self, highlevel_sim, ngspice_sim):
        self.highlevel_sim = highlevel_sim
        self.ngspice_sim = ngspice_sim
        highlevel_sim._active_sim = ngspice_sim
        ngspice_sim.load_netlist(highlevel_sim.netlister.out())

    def alter_component(self, component_instance, **parameters):
        if not hasattr(component_instance, "eref"):
            sim_instance = self.highlevel_sim.find_sim_instance_from_schem_instance(
                component_instance
            )
            if not sim_instance:
                raise ValueError(
                    f"Could not find simulation instance for component {component_instance!r}"
                )
            component_instance = sim_instance

        netlist_name = self.highlevel_sim.get_component_netlist_name(component_instance)
        for param_name, param_value in parameters.items():
            alter_cmd = f"alter {netlist_name} {param_name}={param_value}"
            self.ngspice_sim.command(alter_cmd)
        return True

    def show_component(self, component_instance):
        if not hasattr(component_instance, "eref"):
            sim_instance = self.highlevel_sim.find_sim_instance_from_schem_instance(
                component_instance
            )
            if not sim_instance:
                raise ValueError(
                    f"Could not find simulation instance for component {component_instance!r}"
                )
            component_instance = sim_instance

        netlist_name = self.highlevel_sim.get_component_netlist_name(component_instance)
        return self.ngspice_sim.command(f"show {netlist_name}")

    def op(self):
        self.highlevel_sim.simhier.sim_type = SimType.DC
        for hook in self.highlevel_sim.sim_setup_hooks:
            hook(self.ngspice_sim)

        for vtype, name, subname, value in self.ngspice_sim.op():
            if vtype == "voltage":
                try:
                    simnet = self.highlevel_sim.str_to_simobj[name]
                    simnet.dc_voltage = value
                except KeyError:
                    # ignore internal nodes we can't map
                    continue
            elif vtype == "current":
                if subname not in ("id", "branch", "i"):
                    continue
                try:
                    siminstance = self.highlevel_sim.str_to_simobj[name]
                    siminstance.dc_current = value
                except KeyError:
                    continue

    def start_async_tran(self, tstep, tstop, **kwargs):
        return self.ngspice_sim.tran_async(tstep, tstop, **kwargs)

    def halt_simulation(self, timeout=1.0):
        if hasattr(self.ngspice_sim, "safe_halt_simulation"):
            return self.ngspice_sim.safe_halt_simulation(wait_time=timeout)
        raise NotImplementedError(
            f"Backend {type(self.ngspice_sim).__name__} does not support safe_halt_simulation"
        )

    def resume_simulation(self, timeout=2.0):
        if hasattr(self.ngspice_sim, "safe_resume_simulation"):
            return self.ngspice_sim.safe_resume_simulation(wait_time=timeout)
        raise NotImplementedError(
            f"Backend {type(self.ngspice_sim).__name__} does not support safe_resume_simulation"
        )

    def is_running(self):
        return self.ngspice_sim.is_running()


class HighlevelSim:
    def __init__(
        self,
        top: Schematic,
        simhier: SimHierarchy,
        enable_savecurrents: bool = True,
        backend: str = "subprocess",
    ):
        self.top = top
        self.backend = backend

        self.netlister = Netlister(enable_savecurrents=enable_savecurrents)
        self.netlister.netlist_hier(self.top)

        self.simhier = simhier
        # build hierarchical simulation nodes
        build_hier_schematic(self.simhier, self.top)

        # map netlister names to sim objects for quick lookup
        self.str_to_simobj = {}
        for sn in simhier.all(SimNet):
            name = self.netlister.name_hier_simobj(sn)
            self.str_to_simobj[name] = sn

        for sn in simhier.all(SimInstance):
            name = self.netlister.name_hier_simobj(sn)
            self.str_to_simobj[name] = sn

        # Collect simulation setup hooks from netlister if present
        self.sim_setup_hooks = []
        if hasattr(self.netlister, "_sim_setup_hooks"):
            self.sim_setup_hooks = list(self.netlister._sim_setup_hooks)

        self._active_sim = None

    def op(self):
        self.simhier.sim_type = SimType.DC
        with Ngspice.launch(debug=False, backend=self.backend) as sim:
            for hook in self.sim_setup_hooks:
                hook(sim)

            sim.load_netlist(self.netlister.out())
            for vtype, name, subname, value in sim.op():
                if vtype == "voltage":
                    try:
                        simnet = self.str_to_simobj[name]
                        simnet.dc_voltage = value
                    except KeyError:
                        # ignore internal nodes we don't map
                        continue
                elif vtype == "current":
                    if subname not in ("id", "branch", "i"):
                        continue
                    try:
                        siminstance = self.str_to_simobj[name]
                        siminstance.dc_current = value
                    except KeyError:
                        continue

    def _run_simulation(
        self,
        sim_type,
        sim_method,
        time_field,
        voltage_attr,
        current_attr,
        process_signal_func,
        *sim_args,
        **sim_kwargs,
    ):
        """Common simulation execution logic for tran and ac analyses."""
        self.simhier.sim_type = sim_type
        with Ngspice.launch(debug=False, backend=self.backend) as sim:
            for hook in self.sim_setup_hooks:
                hook(sim)

            sim.load_netlist(self.netlister.out())
            data = getattr(sim, sim_method)(*sim_args, **sim_kwargs)
            setattr(
                self.simhier,
                time_field,
                tuple(data.time if hasattr(data, "time") else data.freq),
            )
            for name, signal_array in data.signals.items():
                try:
                    # Check if this is a voltage signal (node voltage)
                    if signal_array.kind == SignalKind.VOLTAGE:
                        simnet = self.str_to_simobj[name]
                        process_signal_func(
                            simnet,
                            voltage_attr,
                            signal_array.values,
                        )
                    # Check if this is a current signal (device current or branch current)
                    elif signal_array.kind == SignalKind.CURRENT:
                        # Try to find matching SimInstance for device currents
                        if name.startswith("@") and "[" in name:
                            # Device current like "@m.xi0.mpd[id]" - extract device name
                            device_name = name.split("[")[0][
                                1:
                            ]  # Remove @ and get device part
                            siminstance = self.str_to_simobj[device_name]
                            process_signal_func(
                                siminstance,
                                current_attr,
                                signal_array.values,
                            )
                        elif name.endswith("#branch"):
                            # Branch current like "vi3#branch" - extract branch name
                            branch_name = name.replace("#branch", "")
                            siminstance = self.str_to_simobj[branch_name]
                            process_signal_func(
                                siminstance,
                                current_attr,
                                signal_array.values,
                            )
                except KeyError:
                    continue

    def tran(self, tstep, tstop):
        def process_real(simobj, attr_name, values):
            setattr(simobj, attr_name, tuple(values))

        self._run_simulation(
            SimType.TRAN,
            "tran",
            "time",
            "trans_voltage",
            "trans_current",
            process_real,
            tstep,
            tstop,
        )

    def ac(self, *args, wrdata_file: Optional[str] = None):
        def process_complex(simobj, attr_name, values):
            setattr(simobj, attr_name, tuple((c.real, c.imag) for c in values))

        self._run_simulation(
            SimType.AC,
            "ac",
            "freq",
            "ac_voltage",
            "ac_current",
            process_complex,
            *args,
            wrdata_file=wrdata_file,
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

    @contextmanager
    def alter_session(self, backend=None, debug=False):
        use_backend = backend or self.backend
        with Ngspice.launch(debug=debug, backend=use_backend) as ngspice_sim:
            try:
                yield AlterSession(self, ngspice_sim)
            finally:
                self._active_sim = None
