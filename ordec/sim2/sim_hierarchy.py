# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..schema import *
from .ngspice import Ngspice, Netlister

def build_hier_symbol(node, symbol):
    node.schematic = symbol
    for pin in symbol.all(Pin):
        # TODO: implement hierarchical construction within schematic
        setattr(node, pin.full_path_str(), SimNet(eref=pin))

def build_hier_schematic(node, schematic):
    node.schematic = schematic
    for net in schematic.all(Net):
        # TODO: implement hierarchical construction within schematic
        setattr(node, net.full_path_str(), SimNet(eref=net))

    for inst in schematic.all(SchemInstance):
        # TODO: implement hierarchical construction
        setattr(node, inst.full_path_str(), SimInstance(eref=inst))
        subnode = getattr(node, inst.full_path_str())
        try:
            subschematic = inst.symbol.cell.schematic
        except AttributeError:
            build_hier_symbol(subnode, inst.symbol)
        else:
            build_hier_schematic(subnode, subschematic)

class HighlevelSim:
    def __init__(self, top: Schematic, node: SimHierarchy):
        self.top = top

        self.netlister = Netlister()
        self.netlister.netlist_hier(self.top)

        self.node = node
        #self.node.schematic = self.top
        build_hier_schematic(self.node, self.top)
        self.str_to_simobj = {}
        for sn in node.all(SimNet):
            name = self.netlister.name_hier_simobj(sn)
            self.str_to_simobj[name] = sn

        for sn in node.all(SimInstance):
            name = self.netlister.name_hier_simobj(sn)
            self.str_to_simobj[name] = sn

    def op(self):
        with Ngspice.launch(debug=False) as sim:
            sim.load_netlist(self.netlister.out())
            for vtype, name, subname, value in sim.op():
                if vtype == 'voltage':
                    try:
                        simnet = self.str_to_simobj[name]
                    except KeyError:
                        print(f"warning: ignoring {name}")
                    else:
                        simnet.dc_voltage = value
                elif vtype == 'current':
                    if subname not in ('id', 'branch', 'i'):
                        continue
                    siminstance = self.str_to_simobj[name]
                    siminstance.dc_current = value
