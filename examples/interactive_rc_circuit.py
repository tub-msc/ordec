# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import asyncio
import time
import anywidget
import traitlets
from IPython.display import display
import os

from ordec.core import *
from ordec import Rational as R
from ordec.lib.base import Vdc, Res, Cap, Gnd
from ordec.sim2.ngspice import Ngspice, NgspiceBackend
from ordec.sim2.sim_hierarchy import SimHierarchy, HighlevelSim
from ordec.widgets import AnimatedFnWidget, VdcSliderWidget

class InteractiveRCCircuit(Cell):
    vdc_initial = Parameter(R, default=R(1.0))
    resistance = Parameter(R, default=R(1000.0))
    capacitance = Parameter(R, default=R(100e-6))

    @generate
    def schematic(self):
        s = Schematic(cell=self, outline=Rect4R(lx=0, ly=0, ux=15, uy=8))

        s.vin = Net()
        s.vout = Net()
        s.gnd = Net()

        s.vdc = SchemInstance(
            Vdc(dc=R(self.vdc_initial)).symbol.portmap(p=s.vin, m=s.gnd),
            pos=Vec2R(2, 4)
        )

        s.resistor = SchemInstance(
            Res(r=R(self.resistance)).symbol.portmap(p=s.vin, m=s.vout),
            pos=Vec2R(6, 4)
        )

        s.capacitor = SchemInstance(
            Cap(c=R(self.capacitance), ic=R(0)).symbol.portmap(p=s.vout, m=s.gnd),
            pos=Vec2R(10, 4)
        )

        s.ground = SchemInstance(
            Gnd().symbol.portmap(p=s.gnd),
            pos=Vec2R(2, 1)
        )

        return s

class InteractiveSimulation:
    def __init__(self, circuit, plot_widget, vdc_slider, plot_all_signals=False):
        self.circuit = circuit
        self.plot_widget = plot_widget
        self.vdc_slider = vdc_slider
        self.plot_all_signals = plot_all_signals
        self.alter_session = None
        self.is_running = False
        self._is_updating = False
        self._pending_voltage = None
        self._debounce_task = None
        self._last_update_time = 0
        self._vcd_signals_initialized = False
        self._vcd_recording = False
        self._vcd_file = None
        self._vcd_signals = set()
        self._vcd_signal_chars = {}
        self._vcd_header_buffer = []
        self._vcd_initial_values = []

        from ordec.sim2.ngspice import _FFIBackend
        _FFIBackend.find_library()

        self.vdc_slider.observe(self._on_voltage_change, names='value')

    def _on_voltage_change(self, change):
        new_voltage = change['new']
        self._pending_voltage = new_voltage
        self._last_update_time = time.time()

        if self._debounce_task is None or self._debounce_task.done():
            self._debounce_task = asyncio.create_task(
                self._debounce_voltage_update()
            )

    async def _debounce_voltage_update(self):
        try:
            while time.time() - self._last_update_time < 5.0:
                if self._pending_voltage is not None:
                    voltage_to_apply = self._pending_voltage
                    self._pending_voltage = None
                    await self._update_voltage_async(voltage_to_apply)
                await asyncio.sleep(0.1)
        finally:
            self._debounce_task = None

    async def _update_voltage_async(self, new_voltage):
        if self._is_updating or not self.alter_session:
            return

        self._is_updating = True
        try:
            if self.alter_session.is_running():
                self.alter_session.halt_simulation(timeout=1.0)

            self.alter_session.alter_component(
                self.circuit.schematic.vdc,
                dc=new_voltage
            )

            if not self.alter_session.is_running():
                self.alter_session.resume_simulation(timeout=2.0)

        except Exception as e:
            pass
        finally:
            self._is_updating = False

    async def start_simulation(self, sim_time="10m", time_step="1u"):
        if self.is_running:
            return

        try:
            self.is_running = True

            sim_hierarchy = SimHierarchy()
            highlevel_sim = HighlevelSim(
                self.circuit.schematic,
                sim_hierarchy,
                backend=NgspiceBackend.FFI
            )

            if self.plot_all_signals:
                self.plot_widget.update_config({
                    "xMin": 0,
                    "xMax": float(R(sim_time)),
                    "yMin": -10,
                    "yMax": 10,
                    "xLabel": "Time (s)",
                    "yLabel": "Voltage/Current",
                    "series": {}
                })
                self._series_colors = ["#ff6b6b", "#4ecdc4", "#f39c12", "#9b59b6", "#2ecc71", "#e74c3c"]
                self._series_count = 0
            else:
                self.plot_widget.update_config({
                    "xMin": 0,
                    "xMax": float(R(sim_time)),
                    "yMin": -0.5,
                    "yMax": 5.5,
                    "xLabel": "Time (s)",
                    "yLabel": "Voltage (V)",
                    "series": {
                        "vin": {"label": "Input Voltage", "color": "#ff6b6b"},
                        "vout": {"label": "Output Voltage", "color": "#4ecdc4"}
                    }
                })

            with highlevel_sim.alter_session(backend=NgspiceBackend.FFI) as alter:
                self.alter_session = alter

                async for data in self._run_async_simulation(time_step, sim_time, highlevel_sim):
                    if not self.is_running:
                        break

                    time_point = data['time']

                    if self.plot_all_signals:
                        # Plot all available signals
                        for signal_name, signal_value in data.items():
                            if signal_name == 'time':
                                continue

                            # Create series label
                            if signal_name.startswith('@'):
                                # Current signal
                                clean_name = signal_name[1:]  # Remove @
                                series_label = f"I({clean_name})"
                                unit = "A"
                            else:
                                # Voltage signal
                                series_label = f"V({signal_name})"
                                unit = "V"

                            # Get or create series color
                            series_config = self.plot_widget.config.get("series", {})
                            if signal_name not in series_config:
                                color = self._series_colors[self._series_count % len(self._series_colors)]
                                self._series_count += 1
                                self.plot_widget.update_config({
                                    "series": {
                                        signal_name: {"label": series_label, "color": color}
                                    }
                                })

                            self.plot_widget.add_points(signal_name, [time_point], [signal_value])
                    else:
                        # Original voltage-only plotting
                        vin_voltage = None
                        vout_voltage = None

                        for signal_name, voltage_value in data.items():
                            if signal_name == 'time':
                                continue

                            # Map signal name to SimNet using HighlevelSim mapping
                            if signal_name in highlevel_sim.str_to_simobj:
                                simnet = highlevel_sim.str_to_simobj[signal_name]
                                net_name = simnet.eref.full_path_str().split('.')[-1]

                                if net_name == 'vin':
                                    vin_voltage = voltage_value
                                elif net_name == 'vout':
                                    vout_voltage = voltage_value

                        # Use circuit VDC as fallback for vin if not found
                        if vin_voltage is None:
                            vin_voltage = float(self.circuit.vdc_initial)
                        if vout_voltage is None:
                            vout_voltage = 0.0

                        self.plot_widget.add_points("vin", [time_point], [vin_voltage])
                        self.plot_widget.add_points("vout", [time_point], [vout_voltage])

                    await asyncio.sleep(0.01)

                    # Record data for VCD if recording is enabled
                    if self._vcd_recording and self._vcd_file:
                        self._record_vcd_data(data)

                self.alter_session = None

        except Exception as e:
            raise
        finally:
            self.is_running = False

    async def _run_async_simulation(self, time_step, sim_time, highlevel_sim):
        import queue

        data_queue = self.alter_session.start_async_tran(time_step, sim_time)
        start_time = time.time()

        if 'm' in sim_time:
            sim_duration = float(sim_time.replace('m', '')) * 1e-3
        elif 'u' in sim_time:
            sim_duration = float(sim_time.replace('u', '')) * 1e-6
        elif 'n' in sim_time:
            sim_duration = float(sim_time.replace('n', '')) * 1e-9
        else:
            sim_duration = float(sim_time)

        timeout = max(30.0, sim_duration * 100)

        while self.is_running and (time.time() - start_time) < timeout:
            try:
                data_point = data_queue.get_nowait()

                if isinstance(data_point, dict) and 'data' in data_point:
                    data = data_point['data']

                    if self.plot_all_signals:
                        # Include all signals when plot_all_signals is True
                        filtered_data = {k: v for k, v in data.items() if '#branch' not in k}
                    else:
                        # Filter out current signals and keep only voltages
                        filtered_data = {k: v for k, v in data.items()
                                       if not k.startswith('@') and '#branch' not in k}

                    if 'time' in filtered_data:
                        yield filtered_data

            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            except Exception as e:
                break

            await asyncio.sleep(0.001)

    def stop_simulation(self):
        self.is_running = False

    def start_vcd_recording(self, filename="interactive_simulation.vcd", timescale="1us"):
        """
        Start recording simulation data for VCD export with streaming to file.

        Args:
            filename: Output VCD filename
            timescale: VCD timescale (e.g., "1us", "1ns")
        """
        try:
            self._vcd_file = open(filename, 'w')
            self._vcd_recording = True
            self._vcd_signals = set()
            self._vcd_signal_chars = {}
            self._vcd_header_buffer = []
            self._vcd_initial_values = []
            self._vcd_header_written = False

            # Buffer VCD header until all signals are discovered
            import time
            self._vcd_header_buffer = [
                "$date\n",
                f"   {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
                "$end\n",
                "$version\n",
                "   ORDeC Interactive VCD Generator\n",
                "$end\n",
                f"$timescale {timescale} $end\n",
                "$scope module top $end\n"
            ]
            self._vcd_initial_values = []

            print(f"VCD recording started: {filename}")
            return True

        except Exception as e:
            print(f"Error starting VCD recording: {e}")
            self._vcd_recording = False
            if self._vcd_file:
                self._vcd_file.close()
                self._vcd_file = None
            return False

    def stop_vcd_recording(self):
        """Stop VCD recording and close the VCD file."""
        self._vcd_recording = False
        if self._vcd_file:
            self._vcd_file.close()
            self._vcd_file = None
        print("VCD recording stopped")
        return True

    def _record_vcd_data(self, data_point):
        """Record a data point for VCD export with streaming to file."""
        if not self._vcd_file or not self._vcd_recording:
            return

        time_val = data_point.get('time', 0)

        # Process each signal
        for signal_name, value in data_point.items():
            if signal_name == 'time':
                continue

            # Add signal to tracking if new
            if signal_name not in self._vcd_signals:
                self._vcd_signals.add(signal_name)

                # Assign a character for this signal
                signal_chars = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
                if len(self._vcd_signal_chars) < len(signal_chars):
                    char = signal_chars[len(self._vcd_signal_chars)]
                    self._vcd_signal_chars[signal_name] = char

                    # Buffer variable definition for header
                    if signal_name.startswith('@'):
                        clean_name = signal_name[1:]  # Remove @ for current
                        var_def = f"$var real 64 {char} I({clean_name}) $end\n"
                    else:
                        var_def = f"$var real 64 {char} V({signal_name}) $end\n"

                    self._vcd_header_buffer.append(var_def)
                    self._vcd_initial_values.append(f"r{value} {char}\n")
                else:
                    print(f"Warning: Too many signals for VCD format, skipping {signal_name}")
                    continue

        # Write header and initial values when we have signals but haven't written header yet
        if self._vcd_signals and not self._vcd_header_written:
            # Complete the header
            self._vcd_header_buffer.extend([
                "$upscope $end\n",
                "$enddefinitions $end\n"
            ])

            # Write the complete header
            for line in self._vcd_header_buffer:
                self._vcd_file.write(line)

            # Write initial values at time 0
            self._vcd_file.write("#0\n")
            for initial_value in self._vcd_initial_values:
                self._vcd_file.write(initial_value)

            self._vcd_header_written = True

        # Write value changes for existing signals (after header is written)
        if self._vcd_header_written:
            for signal_name, value in data_point.items():
                if signal_name == 'time':
                    continue

                char = self._vcd_signal_chars.get(signal_name)
                if char:
                    # Write time stamp if this is a new time point
                    if time_val > 0:
                        time_units = int(time_val * 1e6)  # Convert to microseconds
                        self._vcd_file.write(f"#{time_units}\n")

                    self._vcd_file.write(f"r{value} {char}\n")

    def export_to_vcd(self, filename="interactive_simulation.vcd", timescale="1us"):
        return self.start_vcd_recording(filename, timescale)

def main(plot_all_signals=False):
    circuit = InteractiveRCCircuit(vdc_initial=1.0, resistance=1000, capacitance=1e-6)

    vdc_slider = VdcSliderWidget(value=1.0, min=-5.0, max=5.0, step=0.1)

    plot_widget = AnimatedFnWidget(
        update_interval_ms=50,
        config={
            "maxDataPointsPerSeries": 10000,
            "enableZoom": True,
            "enablePan": True,
            "legendVisible": True,
            "legendPosition": "top-right"
        }
    )

    interactive_sim = InteractiveSimulation(circuit, plot_widget, vdc_slider, plot_all_signals)

    display(vdc_slider)
    display(plot_widget)

    async def run_demo():
        try:
            await interactive_sim.start_simulation(sim_time="5", time_step="10n")
        except Exception as e:
            print(f"Simulation failed: {e}")

    simulation_task = asyncio.create_task(run_demo())

    return interactive_sim, plot_widget, simulation_task

if __name__ == "__main__":
    # Set plot_all_signals=True to plot all voltages and currents
    interactive_sim, plot_widget, task = main(plot_all_signals=False)

    # Example usage for VCD recording:
    # interactive_sim.start_vcd_recording()  # Call this to start recording
    # # Run simulation...
    # interactive_sim.stop_vcd_recording()   # Call this to stop recording
    # interactive_sim.export_to_vcd("my_simulation.vcd")  # Export to VCD
