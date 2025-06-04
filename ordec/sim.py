# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass
from .schema import Net, SchemInstance, Symbol, Schematic, SchemConnPoint, SchemPort, Pin
from ordec.lib import Nmos, Pmos, Inv, And2, Or2, Ringosc, Vdc, Res, Cap, Ind,Gnd
from .base import Cell
from typing import Type, Any  # Import Type from typing
def escape_to_c_identifier(s):
    """Escapes a string to a valid C identifier by encoding bytes."""
    if not s:
        return "_"

    # Convert string to UTF-8 bytes
    bytes_data = s.encode('utf-8')

    # Start with underscore if first byte isn't valid identifier start
    result = "_" if not (bytes_data and (chr(bytes_data[0]).isalpha() or chr(bytes_data[0]) == '_')) else ""

    # Encode each byte
    for b in bytes_data:
        if b >= 128 or not chr(b).isalnum():  # Escape non-ASCII and non-alphanumeric
            result += f"_x{b:02X}_"  # Encode byte as 2-digit hex
        else:
            result += chr(b)  # ASCII alphanumeric passes through

    return result

def unescape_from_c_identifier(s):
    """Unescapes a C identifier back to the original string."""
    if s == "_":
        return ""

    # Skip leading underscore if it was added for invalid identifier start
    start = 1 if s.startswith('_') and len(s) > 1 and not s.startswith('_x') else 0

    # Build byte array
    bytes_data = bytearray()
    i = start
    while i < len(s):
        if s[i:i+2] == "_x" and i + 4 <= len(s) and s[i+4] == "_":
            # Extract and validate hex value
            hex_val = s[i+2:i+4]
            if all(c in '0123456789ABCDEFabcdef' for c in hex_val):
                bytes_data.append(int(hex_val, 16))
                i += 5  # Skip "_xHH_"
            else:
                bytes_data.append(ord('_'))
                i += 1
        else:
            bytes_data.append(ord(s[i]))
            i += 1

    # Convert bytes back to string
    try:
        return bytes(bytes_data).decode('utf-8')
    except UnicodeDecodeError:
        # Handle invalid UTF-8 sequences
        return ''.join(chr(b) if b < 128 else '?' for b in bytes_data)


def call_name_on_tuples(tuples):
    # why [2:]?
    # Otherwise there is a mismatch between symbol and schematic! their path is different!
    return [tuple(escape_to_c_identifier(element.path()[2:].__str__()) for element in t) for t in tuples]

def get_portmaps(schematic):
    if not isinstance(schematic, Schematic):
        raise TypeError("The input must be a Schematic object")
    
    result = {}
    current_class = schematic.parent
    nets = {}
    path_mapping = {}
    processed_classes = set()

    traverse_nodes(schematic, '', result, nets, path_mapping, processed_classes)
    
    return result, current_class, nets, path_mapping, {
    item.ref.parent.spiceSymbol + item.name: item 
    for item in schematic.traverse() 
    if isinstance(item, SchemInstance) and hasattr(item.ref.parent, "spiceSymbol")
    }

def is_primitive(class_name):
    #primitives = {Res, Cap, Vdc, Ind, Gnd, Nmos, Pmos}  # Set of primitive classes
    return hasattr(class_name,"add_to_circuit")
    #return any(isinstance(class_name, primitive) for primitive in primitives)

    
def build_hierarchical_name(instance_path, node_name):
    parts = []
    if instance_path:
        parts.append('x' + instance_path)
    if node_name:
        parts.append(node_name)
    return '.'.join(parts)

def process_net(item, current_class, instance_path, nets, path_mapping):
    net_name = escape_to_c_identifier(item.path()[2:].__str__())
    nets[current_class][net_name] = item
    if not instance_path:
        path_mapping[(item,)] = net_name

@dataclass
class InstanceData:
    name: str
    class_name: Cell  # Renamed to avoid conflict with Python's 'class' keyword
    params: object  
    portmap: dict


def process_instance(item, current_class, instance_path, result, nets, path_mapping, processed_classes):
    instance_data = InstanceData(
        name=item.name,
        class_name=(item.ref.parent),
        params=item.ref.parent.params,
        portmap=dict(call_name_on_tuples(list(item.portmap.iteritems())))
    )
    result.setdefault(current_class, []).append(instance_data)

    new_instance_path = (instance_path + '.' + item.name).lstrip('.')
    
    if not is_primitive(instance_data.class_name):  # Access class_name from the dataclass
        #print("this is not a primitive",instance_data.class_name,isinstance(instance_data.class_name,Res))
        map_subcircuit_nets(item, new_instance_path, path_mapping)  # Correct call

    if not is_primitive(instance_data.class_name) and instance_data.class_name not in processed_classes:
        processed_classes.add(instance_data.class_name)
        sub_schematic = item.ref.parent.schematic
        if sub_schematic:
            traverse_nodes(sub_schematic, new_instance_path, result, nets, path_mapping, processed_classes)

def map_subcircuit_nets(instance, new_instance_path, path_mapping):
    if not hasattr(instance.ref.parent, 'schematic'):
        raise AttributeError(
            f"Schematic not found for instance '{instance.name}'. "
            f"Is this a subcircuit? Parent type: {type(instance.ref.parent).__name__}"
            f"If this isn't a subcircuit, then it seems it lacks simulation capabilities."
        )
    
    sub_schematic = instance.ref.parent.schematic
    if sub_schematic:
        sub_nets = {escape_to_c_identifier(net.path()[2:].__str__()): net for net in sub_schematic.traverse() if isinstance(net, Net)}
        for sub_net_name, sub_net in sub_nets.items():
            hierarchical_name = build_hierarchical_name(new_instance_path, sub_net_name)
            path_mapping[(instance, sub_net)] = hierarchical_name
        for port_name, connected_node in instance.portmap.iteritems():
            if isinstance(connected_node, Net):
                for sub_net_name, sub_net in sub_nets.items():
                    if sub_net.name == port_name:
                        key = (instance, connected_node)
                        hierarchical_name = build_hierarchical_name(new_instance_path, sub_net_name)
                        path_mapping[key] = hierarchical_name
                        break

def traverse_nodes(current_schematic, instance_path, result, nets, path_mapping, processed_classes):
    current_class = current_schematic.parent
    nets.setdefault(current_class, {})

    for item in current_schematic.traverse():
        if isinstance(item, Net):
            process_net(item, current_class, instance_path, nets, path_mapping)
        elif isinstance(item, SchemInstance):
            process_instance(item, current_class, instance_path, result, nets, path_mapping, processed_classes)

# TODO: Conditionally depend on PySpice, no hard dependency!?
from PySpice.Unit import u_V, u_Ω, u_F, u_H, u_A, u_s
from PySpice.Spice.Netlist import Circuit, SubCircuit
#import PySpice.Logging.Logging as Logging
#import logging
#logger = Logging.setup_logging()
#logger.setLevel(logging.DEBUG)

def create_subcircuit_class(name, components, external_ports):
    def init(self, name):
        unique_external_ports = sorted(set(external_ports), key=external_ports.index)
        SubCircuit.__init__(self, escape_to_c_identifier(name.__str__()), *unique_external_ports)
        
        for component in components:
            add_component_to_circuit(self, component)
    #print("This is the name",name)
    subcircuit_class = type(
        escape_to_c_identifier(name.__str__()),
        (SubCircuit,),
        {
            "__init__": init,
            "external_ports": external_ports
        }
    )
    return subcircuit_class

def add_component_to_circuit(circuit, component):
    # Check if the component class implements the required method
    if not hasattr(component.class_name, 'add_to_circuit'):
        raise NotImplementedError(
            f"Component type {component.class_name} does not implement required add_to_circuit method"
        )
    
    # Delegate to the component's class-specific implementation
    component.class_name.add_to_circuit(circuit, component)


class CircuitProxy:
    "This is used for debugging, you can see the commented comment on create_circuit_from_dict, not currently used."
    def __init__(self, circuit):
        self._circuit = circuit

    def __getattr__(self, name):
        # Get the attribute from the wrapped Circuit instance
        attr = getattr(self._circuit, name)
        
        # If the attribute is a method, wrap it to log calls
        if callable(attr):
            def wrapper(*args, **kwargs):
                # Log the method call
                print(f"Circuit method called: {name}, args: {args}, kwargs: {kwargs}")
                # Perform the original action
                return attr(*args, **kwargs)
            return wrapper
        else:
            # Log attribute access (optional)
            # print(f"Circuit attribute accessed: {name}")
            return attr

    # Optionally override __setattr__ to log attribute changes
    def __setattr__(self, name, value):
        if name == '_circuit':
            # Allow setting the _circuit attribute normally
            super().__setattr__(name, value)
        else:
            # Log and forward other attribute assignments
            print(f"Circuit attribute set: {name} = {value}")
            setattr(self._circuit, name, value)

            
def create_circuit_from_dict(circuit_tuple):
    circuit_dict, root_name = circuit_tuple[:2]
    #print("root_name",root_name)
    circuit = Circuit(escape_to_c_identifier(root_name.__str__()))
    #circuit=CircuitProxy(circuit)
    subcircuit_classes = {}

    for class_name, components in circuit_dict.items():
        if class_name != root_name and components:
            external_ports = []
            for comp in circuit_dict[root_name]:  # Iterate through root components
                if comp.class_name == class_name:  # Access using .class_name
                    for port in comp.portmap: # Access using .portmap
                        if port not in external_ports:
                            external_ports.append(port)

            subcircuit_classes[class_name] = create_subcircuit_class(class_name, components, external_ports)
            for component in components:
                if hasattr(component.class_name,"circuit_global"):
                    component.class_name.circuit_global(circuit)
            circuit.subcircuit(subcircuit_classes[class_name](class_name))

    if root_name in circuit_dict:
        for component in circuit_dict[root_name]:
            if component.class_name in subcircuit_classes:
                portmap = component.portmap.copy()
                for pin, node in portmap.items():
                    if isinstance(node, str) and 'gnd' in node:
                        portmap[pin] = circuit.gnd

                circuit.X(
                    component.name,
                    escape_to_c_identifier(component.class_name.__str__()),
                    *[portmap[pin] for pin in subcircuit_classes[component.class_name].external_ports]
                )
            else:
                if hasattr(component.class_name,"circuit_global"):
                    component.class_name.circuit_global(circuit)
                add_component_to_circuit(circuit, component)  # Pass InstanceData object directly

    return circuit



import numpy as np
from typing import Dict, Union, Optional, Tuple
from ordec import Schematic, Cell, Net
from ordec import  SchemInstance

class SimulatorResult:
    """Base class for simulation results"""
    def __init__(self, analysis, portmaps):
        self.analysis = analysis
        self.portmaps = portmaps
        self.signal_dict = self._map_nodes()

    def _map_nodes(self) -> Dict[Tuple[Net], tuple]:
        """Map analysis nodes to schematic nets using portmaps (internal method)"""
        result = dict([(a.name, (str(a.unit), a.tolist())) for a in self.analysis.nodes.values()])
        invdict = {v: k for k, v in self.portmaps[3].items()}
        final_result = {}
        for k, v in result.items():
            if k in invdict:
                final_result[invdict[k]] = v
        return final_result

    def __getitem__(self, index: Tuple[Net]) -> np.ndarray:
        net = index
        if net not in self.signal_dict:
            raise KeyError(f"Signal path {net} not found in results")
        return np.array(self.signal_dict[net][1])

    def get_signal(self, path: Tuple[Net]) -> np.ndarray:
        """Get signal values by tuple path"""
        net = path
        if net not in self.signal_dict:
            raise KeyError(f"Signal path {net} not found in results")
        return np.array(self.signal_dict[net][1])

    def get_unit(self, path: Tuple[Net]) -> str:
        """Get unit of a signal by tuple path"""
        net = path
        if net not in self.signal_dict:
            raise KeyError(f"Signal path {net} not found in results")
        return self.signal_dict[net][0]

    def list_signals(self) -> list:
        """List all available signal paths in the simulation results"""
        return list(self.signal_dict.keys())

    def plot(self, signals: Optional[list] = None, title: str = "Simulation Results"):
        """Base plot method to be implemented by subclasses"""
        raise NotImplementedError("Plot method must be implemented by subclass")

class DCResult(SimulatorResult):
    """Result class for DC analysis"""
    def __init__(self, analysis, portmaps):
        super().__init__(analysis, portmaps)

    def plot(self, signals: Optional[list] = None, title: str = "DC Analysis Results"):
        import plotly.graph_objects as go
        result = dict([(a.name, (str(a.unit), a.tolist())) for a in self.analysis.nodes.values()])
        if hasattr(self.analysis, 'branches'):
            result.update([(b.name, (b.unit, b.tolist())) for b in self.analysis.branches.values()])
        sweep_key = next((key for key in result.keys() if key.endswith('-sweep')), None)
        if not sweep_key:
            raise ValueError("No sweep variable found in DC analysis")
        sweep_values = np.array(result[sweep_key][1])
        sweep_unit = result[sweep_key][0]
        if signals is None:
            signals = [key for key in result.keys() if key != sweep_key]
        else:
            signals = [str(s[0]) if isinstance(s, tuple) else str(s) for s in signals]
        fig = go.Figure()
        for signal_name in signals:
            if signal_name not in result:
                print(f"Warning: Signal '{signal_name}' not found in analysis results. Skipping.")
                continue
            signal_values = np.array(result[signal_name][1])
            signal_unit = result[signal_name][0]
            fig.add_trace(
                go.Scatter(
                    x=sweep_values,
                    y=signal_values,
                    mode='lines',
                    name=f"{signal_name} ({signal_unit})",
                    hovertemplate=f"{signal_name}: %{{y:.3f}} {signal_unit}<br>{sweep_key}: %{{x:.3f}} {sweep_unit}"
                )
            )
        fig.update_layout(
            title=title,
            xaxis_title=f"{sweep_key.replace('-sweep', '')} ({sweep_unit})",
            yaxis_title="Signal Value",
            legend_title="Signals",
            template="plotly_dark",
            hovermode="x unified"
        )
        fig.show()

class ACResult(SimulatorResult):
    """Result class for AC analysis"""
    def __init__(self, analysis, portmaps):
        super().__init__(analysis, portmaps)

    def get_frequency(self) -> np.ndarray:
        """
        Returns the frequency points from the AC analysis as a NumPy array.

        Units are implicitly Hz (PySpice standard). Accesses the internal
        PySpice analysis object.

        Returns:
            np.ndarray: A NumPy array containing the numerical values of the
                        frequency points.

        Raises:
            AttributeError: If the underlying analysis result object does not have
                            a 'frequency' attribute or it lacks 'as_ndarray()'.
            TypeError: If the conversion to a NumPy array fails.
        """
        # self.analysis is available from the base class __init__
        if not hasattr(self.analysis, 'frequency'):
            raise AttributeError("The underlying analysis result object (type: {}) "
                                 "does not have a 'frequency' attribute. "
                                 "This method requires AC analysis results.".format(type(self.analysis).__name__))
        try:
            # Use the dedicated PySpice Waveform method
            return self.analysis.frequency.as_ndarray()
        except AttributeError:
            raise AttributeError("The 'frequency' attribute of the analysis result "
                                 "object does not have an 'as_ndarray()' method.")
        except Exception as e:
            raise TypeError(f"Could not get frequency as NumPy array using as_ndarray(): {e}")    

    def plot(self, signals: Optional[list] = None, title: str = "AC Analysis Results"):
        import plotly.graph_objects as go
        freq = self.analysis.frequency
        all_signals = list(self.analysis.nodes.keys())
        signals = signals or all_signals
        signals = [str(s[0]) if isinstance(s, tuple) else str(s) for s in signals]
        fig_mag = go.Figure()
        fig_phase = go.Figure()
        for signal in signals:
            if signal not in all_signals:
                print(f"Warning: Signal '{signal}' not found in analysis results. Skipping.")
                continue
            magnitude = 20 * np.log10(np.abs(self.analysis[signal]))
            phase = np.angle(self.analysis[signal], deg=True)
            fig_mag.add_trace(
                go.Scatter(
                    x=freq,
                    y=magnitude,
                    mode='lines',
                    name=f'{signal} (Magnitude)',
                    hovertemplate=f"{signal} Magnitude: %{{y:.3f}} dB<br>Frequency: %{{x:.3f}} Hz"
                )
            )
            fig_phase.add_trace(
                go.Scatter(
                    x=freq,
                    y=phase,
                    mode='lines',
                    name=f'{signal} (Phase)',
                    hovertemplate=f"{signal} Phase: %{{y:.3f}}°<br>Frequency: %{{x:.3f}} Hz"
                )
            )
        fig_mag.update_layout(
            title=f"{title} - Magnitude",
            xaxis_title="Frequency (Hz)",
            yaxis_title="Magnitude (dB)",
            legend_title="Signals",
            legend=dict(x=1.05, y=1),
            showlegend=True,
            template="plotly_dark",
            xaxis_type="log",
            yaxis_type="linear"
        )
        fig_phase.update_layout(
            title=f"{title} - Phase",
            xaxis_title="Frequency (Hz)",
            yaxis_title="Phase (degrees)",
            legend_title="Signals",
            legend=dict(x=1.05, y=1),
            showlegend=True,
            template="plotly_dark",
            xaxis_type="log",
            yaxis_type="linear"
        )
        print("List of all signals available in the AC analysis:")
        for i, signal in enumerate(all_signals, 1):
            print(f"{i}. {signal}")
        fig_mag.show()
        fig_phase.show()

class TransientResult(SimulatorResult):
    """Result class for Transient analysis"""
    def __init__(self, analysis, portmaps):
        super().__init__(analysis, portmaps)

    def get_time(self) -> np.ndarray:
        """
        Returns the time points from the Transient analysis as a NumPy array.

        Units are implicitly seconds (PySpice standard). Accesses the internal
        PySpice analysis object.

        Returns:
            np.ndarray: A NumPy array containing the numerical values of the
                        time points.

        Raises:
            AttributeError: If the underlying analysis result object does not have
                            a 'time' attribute or it lacks 'as_ndarray()'.
            TypeError: If the conversion to a NumPy array fails.
        """
        # self.analysis is available from the base class __init__
        if not hasattr(self.analysis, 'time'):
            raise AttributeError("The underlying analysis result object (type: {}) "
                                 "does not have a 'time' attribute. "
                                 "This method requires Transient analysis results.".format(type(self.analysis).__name__))
        try:
            # Use the dedicated PySpice Waveform method
            return self.analysis.time.as_ndarray()
        except AttributeError:
            raise AttributeError("The 'time' attribute of the analysis result "
                                 "object does not have an 'as_ndarray()' method.")
        except Exception as e:
            raise TypeError(f"Could not get time as NumPy array using as_ndarray(): {e}")    

    def plot(self, signals: Optional[list] = None, title: str = "Transient Analysis Results"):
        import plotly.graph_objects as go
        time = self.analysis.time
        all_signals = list(self.analysis.nodes.keys())
        signals = signals or all_signals
        signals = [str(s[0]) if isinstance(s, tuple) else str(s) for s in signals]
        fig = go.Figure()
        for signal in signals:
            if signal not in all_signals:
                print(f"Warning: Signal '{signal}' not found in analysis results. Skipping.")
                continue
            signal_data = self.analysis[signal]
            fig.add_trace(
                go.Scatter(
                    x=time,
                    y=signal_data,
                    mode='lines',
                    name=signal,
                    hovertemplate=f"{signal}: %{{y:.3f}}<br>Time: %{{x:.3f}} s"
                )
            )
        fig.update_layout(
            title=title,
            xaxis_title="Time (s)",
            yaxis_title="Amplitude",
            legend_title="Signals",
            legend=dict(x=1.05, y=1),
            showlegend=True,
            template="plotly_dark",
            xaxis_type="linear",
            yaxis_type="linear"
        )
        print("List of all signals available in the transient analysis:")
        for i, signal in enumerate(all_signals, 1):
            print(f"{i}. {signal}")
        fig.show()

class Simulator:
    """Main simulator wrapper class"""
    def __init__(self, cell: Union[Cell, Schematic], temperature: float = 25, nominal_temperature: float = 25):
        if isinstance(cell, Cell):
            self.schematic = cell.schematic
        else:
            self.schematic = cell
        self.portmaps = get_portmaps(self.schematic)
        self.circuit = create_circuit_from_dict(self.portmaps)
        self.simulator = self.circuit.simulator(
            temperature=temperature,
            nominal_temperature=nominal_temperature
        )

    def _get_component_name(self, component):
        """Helper method to get the spice symbol name of a component"""
        if not hasattr(component.ref.parent, 'spiceSymbol'):
            raise AttributeError(f"Component {component} does not have a defined spiceSymbol")
        return component.ref.parent.spiceSymbol + component.name

    def dc(self, sweep: Optional[Tuple[SchemInstance, slice]] = None, **kwargs) -> DCResult:
        """Perform DC analysis with given sweep parameters"""
        if sweep is not None:
            if not isinstance(sweep, tuple) or len(sweep) != 2 or not isinstance(sweep[1], slice):
                raise ValueError("sweep must be a tuple of (component, slice)")
            component, sweep_range = sweep
            sweep_key = self._get_component_name(component)
            kwargs[sweep_key] = sweep_range
            #print(f"Sweep key: {sweep_key}")
        analysis = self.simulator.dc(**kwargs)
        return DCResult(analysis, self.portmaps)

    def ac(self, start_frequency, stop_frequency, number_of_points, variation='dec', **kwargs) -> ACResult:
        """Perform AC analysis"""
        analysis = self.simulator.ac(
            start_frequency=start_frequency,
            stop_frequency=stop_frequency,
            number_of_points=number_of_points,
            variation=variation,
            **kwargs
        )
        return ACResult(analysis, self.portmaps)

    def transient(self, step_time, end_time, start_time=0, **kwargs) -> TransientResult:
        """Perform transient analysis"""
        analysis = self.simulator.transient(
            step_time=step_time,
            end_time=end_time,
            start_time=start_time,
            **kwargs
        )
        return TransientResult(analysis, self.portmaps)

    def operating_point(self, **kwargs) -> SimulatorResult:
        """Perform operating point analysis"""
        analysis = self.simulator.operating_point(**kwargs)
        return SimulatorResult(analysis, self.portmaps)


    