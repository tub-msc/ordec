# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports
from dataclasses import dataclass, field

#ordec imports
from ..core import *
from ..ord1.optimize_position import get_pos_with_constraints
from ..schematic import helpers
from ..schematic.routing import schematic_routing

@dataclass
class PostProcess:
    constraints: list = field(default_factory=list)
    routing: dict = field(default_factory=dict)
    called_instances: dict = field(default_factory=dict)
    schem_check: bool = field(default_factory=bool)

def symbol_process(node):
    """
    Function which adds node transformations to the symbol function

    Args:
        node (: current node instance
    Returns:
        None
    """
    helpers.symbol_place_pins(node, vpadding=2, hpadding=2)


def preprocess(self, node, outline, port_positions):
    """
    Function which preprocesses the schematic transformation

    Args:
        self (Cell): self cell reference
        node (Node): current node instance
        outline (Vec2R): outline parameters of the schematic
        port_positions (dict): port ref dictionary
    Returns:
        None
    """
    """Add ref to symbol"""
    node.symbol = self.symbol
    for x in self.symbol.all(Pin):
        name = x.full_path_str()
        setattr(node, name, Net(pin=x))

        net = getattr(node, name)

        port = net % SchemPort()

        """Add port references"""
        if x.pintype == PinType.In or x.pintype == PinType.Inout:
            port.align=Orientation.East
        else:
            port.align=Orientation.West
            
        # Add positions of ports and adjust outline if necessary:
        if name in port_positions:
            position = port_positions[name]
            if position[0] is not None and position[1] is not None:
                port.pos = Vec2R(x=int(position[0]), y=int(position[1]))
                outline = outline.extend(port.pos)
    return outline


def add_positions_from_constraints(constraints, outline, called_instances, node):
    """
    Add positions from constraints if the user defined them

    Args:
        constraints (list): constraints as a list of tuples
        outline (Vec2R): outline coordinates
        called_instances (dict): instances in the schematic
        node (Node): current node
    Returns:
        None
    """
    positioned_instances = set()
    # check if not just a net for branching
    for _, values in constraints:
        positioned_instances.add(values[0])
        positioned_instances.add(values[1])

    for value in node.all(Net):
        name = value.full_path_str()
        if name in positioned_instances and not name.startswith("ordec_unique_net"):
            called_instances[name] = None

    name_pos_dict = get_pos_with_constraints(constraints, called_instances)
    """Add positions defined via constraints and adjust outline if necessary"""
    for ref_name, position in name_pos_dict.items():
        if called_instances[ref_name] is not None:
            instance = getattr(node, ref_name)
            instance.pos = Vec2R(x=position[0], y=position[1])
            instance_transform = instance.loc_transform()
            converted_pos = instance_transform * instance.symbol.outline
            # Get the inverted position in this case
            position = (int(2 * position[0] - converted_pos.lx), int(2 * position[1] - converted_pos.ly))

        low_pos = Vec2R(x=converted_pos.lx, y=converted_pos.ly)
        outline = outline.extend(low_pos)
        up_pos = Vec2R(x=converted_pos.ux, y=converted_pos.uy)
        outline = outline.extend(up_pos)

        if called_instances[ref_name] is not None:
            x = getattr(node, ref_name)
        else:
            net = getattr(node, ref_name)
            x = node.one(SchemPort.ref_idx.query(net))
        x.pos = Vec2R(x=position[0], y=position[1])
        outline = outline.extend(x.pos)

    return outline


def prelim_to_real_instance(called_instances, node):
    """
    Convert preliminary to real instances

    Args:
        called_instances (dict): schematic instances
        node (Node): current node
    Returns:
        None
    """
    for _, prelim_instance in called_instances.items():
        if prelim_instance is not None:
            prelim_instance[0].from_prelim(node)

def adjust_outline_after_instanciation(node, outline):
    """
    Adjust the outline according to the schematic instances

    Args:
        node (Node): node instance
        outline (Vec2R): current outline
    Returns:
        Vec2R: Converted outline
    """
    for instance in node.all(SchemInstance):
        instance_transform = instance.loc_transform()
        instance_geometry = instance_transform * instance.symbol.outline
        low_pos = Vec2R(x=instance_geometry.lx , y=instance_geometry.ly)
        up_pos = Vec2R(x=instance_geometry.ux , y=instance_geometry.uy)
        outline = outline.extend(low_pos)
        outline = outline.extend(up_pos)
    return outline


def postprocess(self, node, outline, postprocess_data: PostProcess):
    """
    Function which postprocesses the schematic transformation

    Args:
        self (Cell): self cell reference
        node (Node): current node instance
        outline (Vec2R): outline of the grid
        postprocess_data (Postprocess): dataclass for postprocess
    Returns:
        None
    """
    # Convert preliminary instances to real instances
    prelim_to_real_instance(postprocess_data.called_instances,
                            node)
    # Adjust the outline according to the size of the sub cells
    outline = adjust_outline_after_instanciation(node, outline)

    #add positions from constraints if available
    outline = add_positions_from_constraints(postprocess_data.constraints,
                                   outline,
                                   postprocess_data.called_instances,
                                   node)
    #do the routing
    if postprocess_data.routing.get("__self__", True) is not False:
        outline = schematic_routing(node, outline, postprocess_data.routing)

    #Add helpers
    if postprocess_data.schem_check:
        helpers.schem_check(node, add_conn_points=True, add_terminal_taps=True)

    helpers.add_conn_points(node)
    node.outline = outline
