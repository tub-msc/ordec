# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports
import ast

#ordec imports
from ..parser.ast_conversion import convert_to_ast_assignment, convert_to_ast_name_store, convert_to_ast_call, \
    convert_to_ast_name_load, convert_to_ast_attribute_store, convert_to_ast_expr, convert_to_ast_subscript_store, \
    convert_to_ast_constant, convert_to_ast_tuple_load, convert_to_ast_list_load, convert_to_ast_dict, \
    convert_to_ast_attribute_load, convert_to_ast_function_def


def flatten_list(nested_list):
    """
    Function which flattens a nested list on one level
    :param nested_list: list to be flattened
    :returns: flat list
    """
    flat_list = []
    for sub_element in nested_list:
        if type(sub_element) is list:
            for elem in sub_element:
                flat_list.append(elem)
        else:
            flat_list.append(sub_element)
    return flat_list

class SchematicModifier(ast.NodeTransformer):

    def __init__(self, port_positions):
        self.port_positions = port_positions

    def visit_FunctionDef(self, node):
        """
        Function which modifies the function_def ast
        -   Add missing statements which where not possible to add on the first transformation
        :param node: current ast node
        :returns: converted node
        """
        if node.name == "schematic":

            # Flatten list objects --> They result from adding new ast statements in the parser
            # node.body = flatten_list(node.body)
            # Remove dead code, empty lists[], in the function body
            node.body = list(filter(lambda elem: elem != [], node.body))
            for index in range(0, len(node.body)):
                value = node.body[index]
                if isinstance(value, tuple) and len(value) == 3:
                    node.body[index] = value[2]
            # Add dictionaries which are only necessary for postprocess and schematic
            postprocess_data = convert_to_ast_assignment(
                convert_to_ast_name_store("postprocess_data"),
                convert_to_ast_call(
                    function_name=convert_to_ast_name_load("PostProcess")
                )
            )

            postprocess_external = convert_to_ast_assignment(
                convert_to_ast_attribute_store(
                    convert_to_ast_name_load("postprocess_data"),
                    "external_dictionary"
                ),
                convert_to_ast_name_load("ext")
            )

            node.body.insert(0, postprocess_external)
            node.body.insert(0, postprocess_data)


            # Add pre and postprocess functions to the function
            preprocess = convert_to_ast_expr(
                convert_to_ast_call(function_name=convert_to_ast_name_load("preprocess"),
                                    args=[convert_to_ast_name_load("self"),
                                          convert_to_ast_name_load("node"),
                                          convert_to_ast_name_load("outline"),
                                          convert_to_ast_name_load("port_positions")
                                          ]
                                    )
            )

            postprocess = convert_to_ast_expr(
                convert_to_ast_call(function_name=convert_to_ast_name_load("postprocess"),
                                    args=[convert_to_ast_name_load("self"),
                                          convert_to_ast_name_load("node"),
                                          convert_to_ast_name_load("outline"),
                                          convert_to_ast_name_load("postprocess_data")]
                                    )
            )

            node.body.insert(0, preprocess)
            node.body.append(postprocess)

            # Add positions for ports

            for port_name, position in self.port_positions.items():

                port_positions_append = convert_to_ast_assignment(
                    convert_to_ast_subscript_store(
                        convert_to_ast_name_store("port_positions"),
                        convert_to_ast_constant(port_name)),
                    convert_to_ast_tuple_load([pos if isinstance(pos, ast.AST) else
                                               convert_to_ast_constant(pos) for pos in position])
                )
                node.body.insert(0, port_positions_append)

            # add all the dictionaries for transformation

            outline = convert_to_ast_assignment(convert_to_ast_name_store("outline"),
                convert_to_ast_list_load([0,0]))
            port_positions = convert_to_ast_assignment(convert_to_ast_name_store("port_positions"),
                convert_to_ast_dict())

            node.body.insert(0, port_positions)
            node.body.insert(0, outline)


        if node.name == "symbol":

            # add the symbol process function
            symbol_process = convert_to_ast_expr(
                convert_to_ast_call(function_name=convert_to_ast_name_load("symbol_process"),
                                    args=[convert_to_ast_name_load("node")]
                                    )
            )
            node.body.append(symbol_process)

        # Visit children of the class node, e.g., methods within the class
        for item in node.body:
            self.visit(item)
        return node

    def visit_ClassDef(self, node):
        """
        Function which modifies the class def of cell by adding the dc simulation
        :param node: current ast node
        :returns: converted node
        """
        sim_assignment = convert_to_ast_assignment(
            convert_to_ast_name_store("sim"),
            convert_to_ast_call(
                function_name=convert_to_ast_name_load("HighlevelSim"),
                args=[
                    convert_to_ast_attribute_load(convert_to_ast_name_load("self"), "schematic"),
                    convert_to_ast_name_load("node")
                ]
            )
        )
        sim_execution = convert_to_ast_expr(convert_to_ast_call(
            function_name=convert_to_ast_attribute_load(convert_to_ast_name_load("sim"), "op")
        ))
        decorator = convert_to_ast_call(function_name=convert_to_ast_name_load("generate"),
                                        args=[convert_to_ast_name_load("SimHierarchy")])
        dc_sim = convert_to_ast_function_def(
            function_name="sim_dc",
            args=["self", "node"],
            body=[sim_assignment, sim_execution],
            decorators=[decorator]
        )

        node.body.append(dc_sim)
        for item in node.body:
            self.visit(item)
        return node


