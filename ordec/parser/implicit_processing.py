# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports
from dataclasses import dataclass, field

#ordec imports
from ..schema import Pin, Net, SchemPort, Orientation, SchemRect, Rect4R, Vec2R, PinType
from ..parser.optimize_position import get_pos_with_constraints
from ..helpers import symbol_place_pins, schem_check
from ..routing import schematic_routing, check_outline_rescaling

@dataclass
class PostProcess:
    constraints: list = field(default_factory=list)
    routing: dict = field(default_factory=dict)
    called_instances: dict = field(default_factory=dict)
    external_dictionary: dict = field(default_factory=dict)

def symbol_process(node):
    """
    Function which adds node transformations to the symbol function
    :param node: current node instance
    :returns: None
    """
    symbol_place_pins(node, vpadding=2, hpadding=2)


def preprocess(self, node, outline, port_positions):
    """
    Function which preprocesses the schematic transformation
    :param self: self cell reference
    :param node: current node instance
    :param outline: outline parameters of the schematic
    :param port_positions: port ref dictionary
    :returns: None
    """
    """Add ref to symbol"""
    node.ref = self.symbol
    for x in self.symbol.traverse():
        if type(x) is Pin:
            name = x.name
            setattr(node, name, Net())
            """Add port references"""
            if x.pintype == PinType.In or x.pintype == PinType.Inout:
                setattr(node, "port_" + name, SchemPort(align=Orientation.East,
                                                          ref=getattr(self.symbol, name),
                                                          net=getattr(node, name)))
            else:
                setattr(node, "port_" + name, SchemPort(align=Orientation.West,
                                                          ref=getattr(self.symbol, name),
                                                          net=getattr(node, name)))
            """Add positions of ports and adjust outline if necessary"""
            if name in port_positions.keys():
                position = port_positions[name]
                if position[0] is not None and position[1] is not None:
                    position = (int(position[0]), int(position[1]))
                    check_outline_rescaling(position[0], position[1], outline)
                    setattr(getattr(node, "port_" + name), "pos", Vec2R(x=position[0], y=position[1]))

def add_positions_from_constraints(constraints, outline, called_instances, node, ext):
    """
    Add positions from constraints if the user defined them
    :param constraints: constraints as a list of tuples
    :param outline: outline coordinates
    :param called_instances: instances in the schematic
    :param node: current node
    :param ext: external dictionary of instances
    :returns: None
    """
    positioned_instances = set()
    # check if not just a net for branching
    for _, values in constraints:
        positioned_instances.add(values[0])
        positioned_instances.add(values[1])

    for name, value in node.children.items():
        if isinstance(value, Net) and name in positioned_instances and not name.startswith("ordec_unique_net"):
            called_instances[name] = None

    name_pos_dict = get_pos_with_constraints(constraints, called_instances, ext)
    """Add positions defined via constraints and adjust outline if necessary"""
    for ref_name, position in name_pos_dict.items():
        if called_instances[ref_name] is not None:
            instance = getattr(node, ref_name)
            instance.pos = Vec2R(x=position[0], y=position[1])
            instance_transform = instance.loc_transform()
            converted_pos = instance_transform * instance.ref.outline.pos
            # Get the inverted position in this case
            position = (int(2 * position[0] - converted_pos.lx), int(2 * position[1] - converted_pos.ly))
        if position[0] > outline[0]:
            outline[0] = position[0]
        if position[1] > outline[1]:
            outline[1] = position[1]
        if called_instances[ref_name] is not None:
            setattr(getattr(node, str(ref_name)), "pos", Vec2R(x=position[0], y=position[1]))
        else:
            setattr(getattr(node, str("port_" + ref_name)), "pos", Vec2R(x=position[0], y=position[1]))


def prelim_to_real_instance(called_instances, ext, node):
    """
    Convert preliminary to real instances
    :param called_instances: schematic instances
    :param node: current node
    :param ext: external dictionary of instances
    :returns: None
    """
    for _, prelim_instance in called_instances.items():
        if prelim_instance is not None:
            prelim_instance[0].from_prelim(ext, node)

def postprocess(self, node, outline, postprocess_data: PostProcess):
    """
    Function which postprocesses the schematic transformation
    :param self: self cell reference
    :param node: current node instance
    :param outline: outline of the grid
    :param postprocess_data: dataclass for postprocess
    :returns: None
    """
    # Convert preliminary instances to real instances
    prelim_to_real_instance(postprocess_data.called_instances,
                            postprocess_data.external_dictionary,
                            node)
    #add positions from constraints if available
    add_positions_from_constraints(postprocess_data.constraints,
                                   outline,
                                   postprocess_data.called_instances,
                                   node,
                                   postprocess_data.external_dictionary)
    #do the routing
    if postprocess_data.routing.get("__self__", True) is not False:
        schematic_routing(node, outline, postprocess_data.routing)
    #Add helpers
    schem_check(node, add_conn_points=True, add_terminal_taps=True)
    #Add helpers
    # WARNING/TODO: Temporarily disabled schem_check here for better interactivity (web):
    #schem_check(node, add_conn_points=True, add_terminal_taps=True)
    node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=outline[0], uy=outline[1]))
