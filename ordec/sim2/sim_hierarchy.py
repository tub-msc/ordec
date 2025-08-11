# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..core import *
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
    def __init__(self, top: Schematic, simhier: SimHierarchy, enable_savecurrents: bool = True, backend: str = None):
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

    def op(self):
        with Ngspice.launch(debug=False, backend=self.backend) as sim:
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
