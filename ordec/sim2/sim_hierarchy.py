# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from typing import Optional
from contextlib import contextmanager

from ..core import *
from ..core.schema import SimType
from .ngspice import Ngspice, Netlister

def build_hier_symbol(simhier, symbol):
    simhier.schematic = symbol
    for pin in symbol.all(Pin):
        # TODO: implement hierarchical construction within schematic
        setattr(simhier, pin.full_path_str(), SimNet(eref=pin))

def build_hier_schematic(simhier, schematic):
    simhier.schematic = schematic
    for net in schematic.all(Net):
        # TODO: implement hierarchical construction within schematic
        setattr(simhier, net.full_path_str(), SimNet(eref=net))

    for inst in schematic.all(SchemInstance):
        # TODO: implement hierarchical construction
        setattr(simhier, inst.full_path_str(), SimInstance(eref=inst))
        subnode = getattr(simhier, inst.full_path_str())
        try:
            subschematic = inst.symbol.cell.schematic
        except AttributeError:
            build_hier_symbol(subnode, inst.symbol)
        else:
            build_hier_schematic(subnode, subschematic)

class HighlevelSim:
    def __init__(self, top: Schematic, simhier: SimHierarchy, enable_savecurrents: bool = True, backend: str = 'subprocess'):
        self.top = top
        self.backend = backend

        self.netlister = Netlister(enable_savecurrents=enable_savecurrents)
        self.netlister.netlist_hier(self.top)

        self.simhier = simhier
        #self.simhier.schematic = self.top
        build_hier_schematic(self.simhier, self.top)
        self.str_to_simobj = {}
        for sn in simhier.all(SimNet):
            name = self.netlister.name_hier_simobj(sn)
            self.str_to_simobj[name] = sn

        for sn in simhier.all(SimInstance):
            name = self.netlister.name_hier_simobj(sn)
            self.str_to_simobj[name] = sn

        # Collect simulation setup hooks from netlister
        self.sim_setup_hooks = []
        if hasattr(self.netlister, '_sim_setup_hooks'):
            self.sim_setup_hooks = list(self.netlister._sim_setup_hooks)

        self._active_sim = None

    def op(self):
        self.simhier.sim_type = SimType.DC
        with Ngspice.launch(debug=False, backend=self.backend) as sim:
            # Run simulation setup hooks
            for hook in self.sim_setup_hooks:
                hook(sim)

            sim.load_netlist(self.netlister.out())
            for vtype, name, subname, value in sim.op():
                if vtype == 'voltage':
                    try:
                        simnet = self.str_to_simobj[name]
                        simnet.dc_voltage = value
                    except KeyError:
                        # Silently ignore internal subcircuit voltages that can't be mapped to hierarchy
                        # These are typically internal nodes within subcircuits (e.g. device body nodes)
                        continue
                elif vtype == 'current':
                    if subname not in ('id', 'branch', 'i'):
                        continue
                    try:
                        siminstance = self.str_to_simobj[name]
                        siminstance.dc_current = value
                    except KeyError:
                        # Silently ignore internal subcircuit device currents that can't be mapped to hierarchy
                        # These are typically internal devices within subcircuits (e.g. MOSFET models)
                        continue

    def tran(self, tstep, tstop):
        self.simhier.sim_type = SimType.TRAN
        with Ngspice.launch(debug=False, backend=self.backend) as sim:
            # Run simulation setup hooks
            for hook in self.sim_setup_hooks:
                hook(sim)

            sim.load_netlist(self.netlister.out())
            data = sim.tran(tstep, tstop)
            self.simhier.time = tuple(data.time)
            for name, value in data.voltages.items():
                try:
                    simnet = self.str_to_simobj[name]
                    simnet.trans_voltage = tuple(value)
                except KeyError:
                    continue
            for name, value in data.currents.items():
                try:
                    siminstance = self.str_to_simobj[name]
                    siminstance.trans_current = tuple(value)
                except KeyError:
                    continue

    def ac(self, *args, wrdata_file: Optional[str] = None):
        self.simhier.sim_type = SimType.AC
        with Ngspice.launch(debug=False, backend=self.backend) as sim:
            for hook in self.sim_setup_hooks:
                hook(sim)

            sim.load_netlist(self.netlister.out())
            data = sim.ac(*args, wrdata_file=wrdata_file)
            self.simhier.freq = tuple(data.freq)
            for name, value in data.voltages.items():
                try:
                    simnet = self.str_to_simobj[name]
                    simnet.ac_voltage = tuple([(c.real, c.imag) for c in value])
                except KeyError:
                    continue

            for name, currents in data.currents.items():
                try:
                    siminstance = self.str_to_simobj[name]
                    if 'id' in currents:
                        main_current = currents['id']
                    elif 'branch' in currents:
                        main_current = currents['branch']
                    elif currents:
                        main_current = next(iter(currents.values()))
                    else:
                        continue # No currents available for this instance

                    siminstance.ac_current = tuple([(c.real, c.imag) for c in main_current])
                except (KeyError, StopIteration):
                    continue

    def export_to_vcd(self, filename="simulation.vcd", signal_names=None, timescale="1us"):
        import time

        if self.simhier.sim_type is None:
            raise ValueError("No simulation results available. Run a simulation first.")

        if self.simhier.sim_type != SimType.TRAN:
            raise ValueError(f"VCD export only supported for transient simulations. Current simulation type: {self.simhier.sim_type}")

        if not hasattr(self.simhier, 'time') or not self.simhier.time:
            raise ValueError("No time data available for VCD export")

        try:
            with open(filename, 'w') as vcd_file:
                # VCD header
                vcd_file.write("$date\n")
                vcd_file.write(f"   {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                vcd_file.write("$end\n")
                vcd_file.write("$version\n")
                vcd_file.write("   ORDeC VCD Generator\n")
                vcd_file.write("$end\n")
                vcd_file.write(f"$timescale {timescale} $end\n")

                # Collect signals to export
                signals_to_export = []
                signal_chars = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"  # VCD variable characters

                for i, simnet in enumerate(self.simhier.all(SimNet)):
                    signal_name = simnet.full_path_str().split('.')[-1]  # Get base name

                    # Filter by signal_names if provided
                    if signal_names is not None and signal_name not in signal_names:
                        continue

                    if hasattr(simnet, 'trans_voltage') and simnet.trans_voltage is not None:
                        if i < len(signal_chars):
                            char = signal_chars[i]
                            signals_to_export.append((signal_name, char, simnet.trans_voltage))
                        else:
                            # Fallback for many signals - use extended character set
                            char = f"signal{i}"
                            signals_to_export.append((signal_name, char, simnet.trans_voltage))

                if not signals_to_export:
                    raise ValueError("No signals with transient voltage data found for VCD export")

                # Variable definitions
                vcd_file.write("$scope module top $end\n")
                for signal_name, char, _ in signals_to_export:
                    vcd_file.write(f"$var real 64 {char} {signal_name} $end\n")
                vcd_file.write("$upscope $end\n")
                vcd_file.write("$enddefinitions $end\n")

                # Initial values at time 0
                vcd_file.write("#0\n")
                for signal_name, char, voltage_data in signals_to_export:
                    if voltage_data and len(voltage_data) > 0:
                        vcd_file.write(f"r{voltage_data[0]} {char}\n")

                # Value changes at each time point
                time_data = self.simhier.time
                for time_idx in range(1, len(time_data)):
                    time_units = int(time_data[time_idx] * 1e6)  # Convert to microseconds
                    vcd_file.write(f"#{time_units}\n")
                    for signal_name, char, voltage_data in signals_to_export:
                        if len(voltage_data) > time_idx:
                            vcd_file.write(f"r{voltage_data[time_idx]} {char}\n")

            return True

        except Exception as e:
            raise ValueError(f"Error generating VCD file: {e}")

    def get_component_netlist_name(self, component_instance):
        """Get the netlist name for a component instance using existing mapping."""
        return self.netlister.name_hier_simobj(component_instance)

    def find_component_by_ref_name(self, ref_name):
        """Find a component instance by its reference name (e.g., 'r1', 'c1')."""
        for sim_instance in self.simhier.all(SimInstance):
            if hasattr(sim_instance, 'eref') and hasattr(sim_instance.eref, 'full_path_str') and sim_instance.eref.full_path_str().endswith(ref_name):
                return sim_instance

        return None

    def find_sim_instance_from_schem_instance(self, schem_instance):
        """Find a SimInstance that corresponds to a SchemInstance from the schematic."""
        for sim_instance in self.simhier.all(SimInstance):
            if hasattr(sim_instance, 'eref') and sim_instance.eref == schem_instance:
                return sim_instance
        return None

    @contextmanager
    def alter_session(self, backend=None, debug=False):
        """Context manager for alter operations that maintains ngspice session."""
        use_backend = backend or self.backend

        class AlterSession:
            def __init__(self, highlevel_sim, ngspice_sim):
                self.highlevel_sim = highlevel_sim
                self.ngspice_sim = ngspice_sim
                highlevel_sim._active_sim = ngspice_sim
                ngspice_sim.load_netlist(highlevel_sim.netlister.out())

            def alter_component(self, component_instance, **parameters):
                """Alter component parameters using component instance."""
                # If we get a SchemInstance, find the corresponding SimInstance
                if not hasattr(component_instance, 'eref'):
                    sim_instance = self.highlevel_sim.find_sim_instance_from_schem_instance(component_instance)
                    if not sim_instance:
                        raise ValueError(f"Could not find simulation instance for component {component_instance}")
                    component_instance = sim_instance

                netlist_name = self.highlevel_sim.get_component_netlist_name(component_instance)
                for param_name, param_value in parameters.items():
                    alter_cmd = f"alter {netlist_name} {param_name}={param_value}"
                    self.ngspice_sim.command(alter_cmd)
                return True

            def show_component(self, component_instance):
                """Show component parameters using component instance."""
                # If we get a SchemInstance, find the corresponding SimInstance
                if not hasattr(component_instance, 'eref'):
                    sim_instance = self.highlevel_sim.find_sim_instance_from_schem_instance(component_instance)
                    if not sim_instance:
                        raise ValueError(f"Could not find simulation instance for component {component_instance}")
                    component_instance = sim_instance

                netlist_name = self.highlevel_sim.get_component_netlist_name(component_instance)
                return self.ngspice_sim.command(f"show {netlist_name}")

            def op(self):
                """Run operating point analysis and update hierarchy."""
                self.highlevel_sim.simhier.sim_type = SimType.DC
                for hook in self.highlevel_sim.sim_setup_hooks:
                    hook(self.ngspice_sim)
                for vtype, name, subname, value in self.ngspice_sim.op():
                    if vtype == 'voltage':
                        try:
                            simnet = self.highlevel_sim.str_to_simobj[name]
                            simnet.dc_voltage = value
                        except KeyError:
                            continue
                    elif vtype == 'current':
                        if subname not in ('id', 'branch', 'i'):
                            continue
                        try:
                            siminstance = self.highlevel_sim.str_to_simobj[name]
                            siminstance.dc_current = value
                        except KeyError:
                            continue

            def start_async_tran(self, tstep, tstop, **kwargs):
                """Start async transient simulation."""
                return self.ngspice_sim.tran_async(tstep, tstop, **kwargs)

            def halt_simulation(self, timeout=1.0):
                if hasattr(self.ngspice_sim, 'safe_halt_simulation'):
                    return self.ngspice_sim.safe_halt_simulation(wait_time=timeout)
                else:
                    raise NotImplementedError(f"Backend {type(self.ngspice_sim).__name__} does not support safe_halt_simulation")

            def resume_simulation(self, timeout=2.0):
                if hasattr(self.ngspice_sim, 'safe_resume_simulation'):
                    return self.ngspice_sim.safe_resume_simulation(wait_time=timeout)
                else:
                    raise NotImplementedError(f"Backend {type(self.ngspice_sim).__name__} does not support safe_resume_simulation")

            def is_running(self):
                return self.ngspice_sim.is_running()

        with Ngspice.launch(debug=debug, backend=use_backend) as ngspice_sim:
            try:
                yield AlterSession(self, ngspice_sim)
            finally:
                self._active_sim = None
