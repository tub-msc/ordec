# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports

#ordec imports
from . import Pin, SchemPort, Vec2R, SchemInstance, Net, SchemPoly
from .geoprim import D4
from .parser import schematic_routing as routing_module

def check_outline_rescaling(x, y, outline):
    """
    Check if the outline should be rescaled
    :param x: x coord
    :param y: y coord
    :param outline: outline coordinates
    :returns: None
    """
    if x > outline[0]:
        outline[0] = x
    if y > outline[1]:
        outline[1] = y

def schematic_routing(node, outline=None, routing=None):
    """
    Calculate the vertices for routing via a-star pathfinding
    :param node: current node
    :param outline: outline coordinates
    :param routing: port dict if routing should be done
    :returns: None
    """
    # Get all the connections of ports and instances
    if routing is None:
        routing = dict()
    if outline is None:
        outline = [0, 0]
    padding = 3
    ports = dict()
    cells = dict()
    # mapping between net and name
    array_mapping_list = dict()

    for instance in node.traverse():
        if isinstance(instance, SchemPort) or isinstance(instance, SchemInstance):
            if isinstance(instance, SchemInstance):
                instance_transform = instance.loc_transform()
                # Add instance for cells
                symbol_size = instance_transform * instance.ref.outline.pos
                pos = Vec2R(x=symbol_size.lx, y=symbol_size.ly)
                x_size = symbol_size.ux - symbol_size.lx
                y_size = symbol_size.uy - symbol_size.ly
                instance_name = instance.name
                # print("CELL_POS: ", pos.x, pos.y)
                # Add inner connections for the cell (symbol)
                inner_connections = dict()
                for pin in instance.ref.traverse():
                    if type(pin) is Pin:
                        inst_orientation = D4(instance.loc_transform().set(transl=Vec2R(x=0, y=0)))
                        alignment = (inst_orientation * pin.align).unflip().lefdef()
                        inner_pos = instance_transform * pin.pos
                        # pin arrays have pin connections with names as ints
                        # get the parent name to get a unique assignment
                        if type(pin.name) == int:
                            inner_name = str(pin.parent.name) + str(pin.name)
                        else:
                            inner_name = str(pin.name)
                        inner_x = int(inner_pos.x)
                        inner_y = int(inner_pos.y)
                        # print("INNER_POS: ", inner_x, inner_y)
                        inner_connections[inner_name] = (inner_x,
                                                         inner_y,
                                                         alignment,
                                                         instance_name)
                        # set the outline again
                        check_outline_rescaling(inner_x, inner_y, outline)
                # add to cells dictionary
                cells[instance_name] = routing_module.Cell(int(pos.x),
                                                int(pos.y),
                                                int(x_size) + 1,
                                                int(y_size) + 1,
                                                instance_name,
                                                inner_connections)
            else:
                # Add instances for ports
                port_alignment = instance.align.lefdef()
                pos = instance.pos
                name = str(instance.name)
                # net and name mapping for pinarrays
                array_mapping_list[instance.net] = name
                # add to ports dictionary
                inner_x = int(pos.x)
                inner_y = int(pos.y)
                check_outline_rescaling(inner_x, inner_y, outline)
                ports[name] = routing_module.Port(inner_x,
                                       inner_y,
                                       name,
                                       port_alignment)

    # Get the connections defined via the portmap
    connections = list()
    inter_instance_connections = list()
    for instance in node.traverse():
        if isinstance(instance, SchemPort) or isinstance(instance, SchemInstance):
            if isinstance(instance, SchemInstance):
                instance_name = instance.name
                # Connections of Cells and ports
                for inner_connection, connected_to in instance.portmap.items():
                    # pin arrays have pin connections with names as ints
                    # get the parent name to get a unique assignment
                    if type(inner_connection.name) == int:

                        inner_connection_name = (str(inner_connection.parent.name) +
                                                 str(inner_connection.name))
                    else:
                        inner_connection_name = str(inner_connection.name)
                    # Currently only working for ports to instances not instances to instances
                    connected_name = array_mapping_list.get(connected_to, None)
                    connection_position = cells[instance_name].connections[inner_connection_name]
                    # only if the ports have the connection and if it's not an inter cell connection
                    if connected_name in ports.keys():
                        if routing.get(connected_name.removeprefix("port_"), True) is not False:
                            connections.append((ports[connected_name], connection_position))
                        # print("normal_conn", connected_name, connection_position)
                        # connection not in ports <=> inter instance connection
                    else:
                        # get the connection position
                        connected_name = connected_to.name
                        if connected_name not in inter_instance_connections:
                            # Create the new port for first appearance and save the inter instance connection
                            inter_instance_connections.append(connected_name)
                            ports[connected_name] = routing_module.Port(int(connection_position[0]),
                                                             int(connection_position[1]),
                                                             connected_name, connection_position[2])
                            # print("save", connected_name, connection_position)
                            array_mapping_list[connected_to] = connected_name
                        else:
                            # Save the path after the inter instance connection is established
                            # print("append", connected_name, connection_position)
                            connections.append((ports[connected_name], connection_position))

    outline[0] = outline[0] + padding
    outline[1] = outline[1] + padding
    # Calculate the vertices and add them to the schematic
    vertices_dict = routing_module.calculate_vertices(outline, cells, ports, connections)
    i = 0
    for name, vertices_lists in vertices_dict.items():
        # Example: node.vss % SchemPoly(vertices=[Vec2R(x=6, y=1), Vec2R(x=6, y=2)])
        for vertices in vertices_lists:
            # Set the vertices from the ports
            # Case for internal nets
            schem_part = getattr(node, name)
            if isinstance(schem_part, Net):
                setattr(getattr(node, name),  f"vert_{i}",
                        SchemPoly(vertices=[Vec2R(x=vert[0], y=vert[1]) for vert in vertices]))
            # case for external ports
            else:
                setattr(getattr(node, name).net, f"vert_{i}",
                        SchemPoly(vertices=[Vec2R(x=vert[0], y=vert[1]) for vert in vertices]))
            i += 1
