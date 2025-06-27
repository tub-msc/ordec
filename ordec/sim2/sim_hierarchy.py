# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..schema import *
from .ngspice import Ngspice, Netlister

def build_hier_symbol(node, symbol):
    for pin in symbol.traverse(Pin):
        # TODO: implement hierarchical construction within schematic
        setattr(node, pin.name, SimNet(ref=pin))

def build_hier_schematic(node, schematic):
    for net in schematic.traverse(Net):
        # TODO: implement hierarchical construction within schematic
        setattr(node, net.name, SimNet(ref=net))

    for inst in schematic.traverse(SchemInstance):
        setattr(node, inst.name, SimInstance(ref=inst))
        subnode = getattr(node, inst.name)
        try:
            subschematic = inst.ref.parent.schematic
        except AttributeError:
            build_hier_symbol(subnode, inst.ref)
        else:
            build_hier_schematic(subnode, subschematic)

class HighlevelSim:
    def __init__(self, top: Schematic, node: SimHierarchy):
        self.top = top

        self.netlister = Netlister()
        self.netlister.netlist_hier(self.top)

        self.node = node
        self.node.ref = self.top
        build_hier_schematic(self.node, self.node.ref)
        self.str_to_simnet = {}
        for sn in node.traverse(SimNet):
            self.str_to_simnet[self.netlister.name_simnet(sn)] = sn

    def op(self):
        with Ngspice.launch(debug=False) as sim:
            sim.load_netlist(self.netlister.out())
            for name, value in sim.op():
                try:
                    sn = self.str_to_simnet[name]
                except KeyError:
                    print(f"warning: ignoring {name}")
                else:
                    sn.dc_voltage = value
