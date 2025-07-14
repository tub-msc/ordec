# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports
from lark import Transformer
from lark.indenter import Indenter
import uuid
import ast

#ordec imports
from ..parser.ast_conversion import convert_to_ast_call, convert_to_ast_class_function, convert_to_ast_name_load, \
    convert_to_ast_function_def, convert_to_ast_assignment, convert_to_ast_name_store, convert_to_ast_attribute_load, \
    convert_to_ast_attribute_store, convert_to_ast_subscript_store, convert_to_ast_constant, convert_to_ast_tuple_load, \
    convert_to_ast_module, convert_to_ast_expr, convert_to_ast_for_loop, convert_to_ast_bin_op, convert_to_ast_unary_op


class TreeIndenter(Indenter):
    NL_type = '_NL'
    OPEN_PAREN_types = []
    CLOSE_PAREN_types = []
    INDENT_type = '_INDENT'
    DEDENT_type = '_DEDENT'
    tab_len = 4

STRUCTURED_SPACING = 8
STRUCTURED_OFFSET = 2
PORT_OFFSET_Y_DEFAULT = 0
PORT_OFFSET_X_DEFAULT = 0
STRUCTURED_LIOP = True

class OrdecTransformer(Transformer):
    def __init__(self):
        # port refs, Layout: name = (position_x, position_y)
        self.port_positions = dict()
        self.additional_nets = dict()

    def cell(self, items):
        """
        Convert to the cell class definition
        :param items: items in this hierarchy level
        :returns: ast converted items
        """

        return convert_to_ast_class_function(items[0], ["Cell"],
                                             body = items[1:])

    def schematic(self, items):
        """
        Convert to the schematic function declaration
        :param items: items in this hierarchy level
        :returns: ast converted items
        """
        decorator = convert_to_ast_call(function_name=convert_to_ast_name_load("generate"),
                                        args=[convert_to_ast_name_load("Schematic")])
        return convert_to_ast_function_def("schematic",
                                           ["self", "node"],
                                           items,
                                           [decorator])

    def symbol(self, items):
        """
        Convert to the symbol function declaration
        :param items: items in this hierarchy level
        :returns: ast converted items
        """
        decorator = convert_to_ast_call(function_name=convert_to_ast_name_load("generate"),
                                        args=[convert_to_ast_name_load("Symbol")])
        return convert_to_ast_function_def("symbol",
                                           ["self", "node"],
                                           items,
                                           [decorator])

    def port_declaration(self, items):
        """
        port declaration: safe in port refs for later insertion and add declaration to symbol
        Later insertion because only in schematic or symbol possible at the same time.
        Grammar: port_declaration: (INPUT|OUTPUT) NAME tuple_expr? (_COMMA NAME tuple_expr?)* _NL
        :param items: items in this hierarchy level
        :returns: ast converted items
        """
        inout_type = items[0]
        # Safe the referenced ports
        ref = items[1]
        # check if this definition has a position assigned
        if len(items) > 2:
            self.port_positions[ref] = items[2]
        else:
            self.port_positions[ref] = (None, None)

        # Check if input or output and assignment
        alignment = "East"
        if inout_type == "Input" or inout_type == "Inout":
            alignment = "West"
            # Special case for specific words
            if ref == "gnd" or ref == "vss":
                alignment = "South"
            if ref == "vdd":
                alignment = "North"
            if inout_type == "Input":
                direction = "In"
            else:
                direction = "Inout"
        else:
            direction = "Out"
        pin_assignment = convert_to_ast_assignment(convert_to_ast_name_store("pintype"),
                                                   convert_to_ast_attribute_load(
                                                       convert_to_ast_name_load("PinType"), direction))
        align_assignment = convert_to_ast_assignment(convert_to_ast_name_store("align"),
                                                     convert_to_ast_attribute_load(
                                                         convert_to_ast_name_load("Orientation"),
                                                         alignment
                                                     ))
        # combine to full assign and insert
        lhs = convert_to_ast_attribute_store(convert_to_ast_name_load("node"), ref)
        rhs = convert_to_ast_call(
            function_name=convert_to_ast_name_load("Pin"),
            args=[
                pin_assignment,
                align_assignment
            ]
        )
        full_assign = convert_to_ast_assignment(lhs, rhs)
        return full_assign

    @staticmethod
    def declaration_helper(instance_name, instance_type, instance_declarations):
        """
        Converts declaration like Nmos pd
        :param instance_name: name of the instance
        :param instance_type: type of the instance
        :param instance_declarations: list of declaration return statements
        :returns: None
        """
        called_instances_append = convert_to_ast_assignment(
            convert_to_ast_subscript_store(
                convert_to_ast_attribute_store(
                    convert_to_ast_name_store("postprocess_data"),
                    "called_instances"
                ),
                convert_to_ast_constant(instance_name)
            ),
            convert_to_ast_tuple_load([convert_to_ast_name_load(instance_name),
                                       convert_to_ast_constant(instance_type)])


        )

        instance = convert_to_ast_assignment(
            convert_to_ast_name_store(instance_name),
            convert_to_ast_call(function_name=convert_to_ast_name_load('PrelimSchemInstance'), args=[
                convert_to_ast_assignment(convert_to_ast_name_store('prelim_name'),
                                          convert_to_ast_constant(instance_name)),
                convert_to_ast_assignment(convert_to_ast_name_store('prelim_ref'),
                                          convert_to_ast_constant(instance_type))
            ]))
        instance_declarations.append(instance)
        instance_declarations.append(called_instances_append)

    def declaration(self, items):
        """
        instance declarations: safe in instance refs for later insertion and add declaration to schematic
        Later insertion because instances could get params assigned somewhere in the code.
        Grammar: declaration: NAME NAME _nested_declaration?
        :param items: items in this hierarchy level
        :returns: ast converted items
        """
        # Save the name of the instance as a key
        # Save the potential parameters it could have in a list
        # --> tuples with (param_name, param_value)
        instance_declarations = list()
        instance_type = items[0]
        instance_name = items[1]
        self.declaration_helper(instance_name, instance_type, instance_declarations)

        # if multiple comma separated instance declarations
        if len(items) <= 2 or not isinstance(items[2], list):
            for item in items[2:]:
                self.declaration_helper(item, instance_type, instance_declarations)
        else:
            # declaration with nested assignments/connections
            # comes from _inner_assignments
            for assignment in items[2:]:
                if isinstance(assignment, list):
                    assignment_type = assignment[0]
                    # Combine the instance plus the access
                    instance_access = (instance_name, assignment[1])
                    if assignment_type == "POS":
                        assign = "="
                        # create the item_list so the transformer methods can process them
                        passed_items = [instance_name, assignment[1], assign] + assignment[2:]
                        instance_declarations.append(self.assign_pos(passed_items))
                    elif assignment_type == "CONNECT":
                        assign = "--"
                        passed_items = [instance_access, assign] + assignment[2:]
                        instance_declarations.append(self.assign_map(passed_items))
                    elif assignment_type == "ATTRIBUTE":
                        assign = "="
                        passed_items = [instance_access, assign] + assignment[2:]
                        instance_declarations.append(self.assign_attribute(passed_items))
                    elif assignment_type == "ORIENTATION":
                        assign = "="
                        passed_items = [instance_name, assignment[1], assign] + assignment[2:]
                        instance_declarations.append(self.assign_orientation(passed_items))

        if STRUCTURED_LIOP:
            return f"{instance_name}", [], convert_to_ast_module(instance_declarations)
        else:
            return f"{instance_name}", [0,0], convert_to_ast_module(instance_declarations)

    def tuple_expr(self, items):
        """
        Convert a tuple expression and get the resulting tuple.
        Grammar: tuple_expr: _LPAR NUMBER (_COMMA NUMBER)+ _RPAR
        :param items: items in this hierarchy level
        :returns: ast converted items
        """
        # Currently only two values tuples are allowed, the list is only for future purposes
        tuple_val = (items[0], items[1])
        return tuple_val

    def assign_pos(self, items):
        """
        Save position as Vec2R call
        Grammar: assign_pos: instance_access _ASSIGN tuple_expr _NL
        :param items: items in this hierarchy level
        :returns: ast converted items
        """
        instance_name = items[0]
        position = items[3]
        position_x = position[0] if isinstance(position[0], ast.AST) else convert_to_ast_constant(position[0])
        position_y = position[1] if isinstance(position[1], ast.AST) else convert_to_ast_constant(position[1])

        arg_x = convert_to_ast_assignment(convert_to_ast_name_store('x'), position_x)
        arg_y = convert_to_ast_assignment(convert_to_ast_name_store('y'), position_y)
        attribute = convert_to_ast_attribute_store(convert_to_ast_name_load(instance_name), "prelim_pos")

        pos_assignment = convert_to_ast_assignment(attribute,
                                                    convert_to_ast_call(
                                                        function_name=convert_to_ast_name_load("Vec2R"),
                                                         args=[arg_x, arg_y]
                                                        )
                                                    )
        return pos_assignment

    def assign_map(self, items):
        """
        Example setup: node.pu.portmap[node.pu.ref.s] = node.vdd
        Correctly assign the port mapping
        Grammar: assign_map: instance_access _CONNECT NAME _NL
        :param items: items in this hierarchy level
        :returns: ast converted items
        """
        access_tuple = items[0]
        mapped_name = items[2]
        attribute = convert_to_ast_attribute_store(
            convert_to_ast_name_load(access_tuple[0]), "prelim_portmap")
        lhs = convert_to_ast_subscript_store(attribute, convert_to_ast_constant(access_tuple[1]))

        # if it is an position expression between two instances
        if len(mapped_name) > 1:
            #new_net_declaration = str(access_tuple[1] + access_tuple[0][-1])
            return_values = list()

            if not (self.additional_nets.get(access_tuple) and self.additional_nets.get(mapped_name)):
                new_net_declaration = 'ordec_unique_net_' + uuid.uuid4().hex
                net = convert_to_ast_assignment(
                    convert_to_ast_attribute_store(
                        convert_to_ast_name_load("node"),
                        new_net_declaration),
                    convert_to_ast_call(function_name=convert_to_ast_name_load("Net"))
                )
                for key in (access_tuple, mapped_name):
                    self.additional_nets.setdefault(key, new_net_declaration)
                return_values.append(net)

            # Get the index access (node.pu.ref.s)
            rhs = convert_to_ast_attribute_load(convert_to_ast_name_load('node'),
                                                  self.additional_nets.get(access_tuple))
            map_assignment = convert_to_ast_assignment(lhs, rhs)
            return_values.append(map_assignment)
            map_assignment = convert_to_ast_module(return_values)
        else:
            # Get rhs and lhs of assignment
            rhs = convert_to_ast_attribute_load(convert_to_ast_name_load('node'), mapped_name[0])
            map_assignment = convert_to_ast_assignment(lhs, rhs)

        return map_assignment

    def instance_access(self, items):
        """
        get the port accesses and wrap them in a tuple
        :param items: items in this hierarchy level
        :returns: port access items in a tuple
        """
        access_list = list()
        for item in items:
            if item != ".":
                if type(item) == int:
                    access_list.append([item])
                else:
                    access_list.append(item)
        return tuple(access_list)

    def attribute_access(self, items):
        """
        get the port accesses and wrap them in a tuple
        :param items: items in this hierarchy level
        :returns: port access items in a tuple
        """
        return items[0], items[2]

    # Positons defined via constraints need to be inserted in post-processing
    def constraint(self, items):
        """
        constraint: (ABOVE|BELOW|LEFT|RIGHT) _LPAR NAME _COMMA NAME (_COMMA NUMBER)? _RPAR _NL
        :param items: items in this hierarchy level
        :returns: ast converted items
        """
        constraint_type = items[0]
        access_1 = items[1]
        access_2 = items[2]
        # check if the user defined a specific offset spacing
        if len(items) > 3:
            offset_number = items[3]
        else:
            offset_number = 0

        constraints_append = convert_to_ast_expr(
            convert_to_ast_call(
                function_name=convert_to_ast_attribute_load(
                    convert_to_ast_attribute_load(
                        convert_to_ast_name_load("postprocess_data"),
                        "constraints"
                    ),
                    "append"
                ),
                args=[
                    convert_to_ast_tuple_load([
                        convert_to_ast_constant(constraint_type),
                        convert_to_ast_tuple_load([convert_to_ast_constant(access_1),
                                                   convert_to_ast_constant(access_2),
                                                   convert_to_ast_constant(offset_number)
                                                  ])
                    ])
                ]
            )
        )
        return constraints_append

    # Get rid of the nested list for the multi stmts
    def multi_schematic_stmt(self, items):
        """
        Flatten any nested lists in `items` (one level deeper)

        :param items: current items in the hierarchy
        :returns: flattened list of statements
        """
        flat_items = []
        for item in items:
            if isinstance(item, list):
                flat_items.extend(item)  # If item is a list, extend flat_items with its contents
            else:
                flat_items.append(item)  # Otherwise, add the item itself
        return flat_items

    # Get rid of the nested list for the multi stmts
    def multi_symbol_stmt(self, items):
        """
        Flatten any nested lists in `items` (one level deeper)

        :param items: current items in the hierarchy
        :returns: flattened list of statements
        """
        flat_items = []
        for item in items:
            if isinstance(item, list):
                flat_items.extend(item)  # If item is a list, extend flat_items with its contents
            else:
                flat_items.append(item)  # Otherwise, add the item itself
        return flat_items


    def assign_attribute(self, items):
        """
        Process the statement from a normal assign value statement
        t.w = 60nm
        :param items: current items in the hierarchy
        :returns: attribute assignment
        """
        attribute_access = items[0]
        value = items[2]
        if len(items) == 4:
            si_value = items[3]
        else:
            si_value = ""
        # check if the attribute is related to an instance name
        attribute = convert_to_ast_attribute_store(convert_to_ast_name_load(attribute_access[0]), "prelim_params")
        lhs = convert_to_ast_subscript_store(attribute, convert_to_ast_constant(attribute_access[1]))
        rhs = convert_to_ast_call(function_name=convert_to_ast_name_load("Rational"),
                                  args=[convert_to_ast_constant(f"{value}{si_value}")])
        assignment = convert_to_ast_assignment(lhs, rhs)
        return assignment

    def assign_orientation(self, items):
        """
        Process the statement for an orientation
        assign_orientation: NAME _DOT ORIENTATION ASSIGN NUMBER _NL
        :param items: current items in the hierarchy
        :returns: returns a normal python for loop
        """
        instance = items[0]
        value = items[3]
        assignment = convert_to_ast_assignment(
            convert_to_ast_attribute_store(
                    convert_to_ast_name_load(instance),
            "prelim_orientation"),
            # Orientation.R90
            convert_to_ast_attribute_load(
                convert_to_ast_name_load("Orientation"),
                f"{value}"
            )
        )
        return assignment


    def for_loop(self, items):
        """
        Process the statement from a for loop
        for t in x1,x2:
        :param items: current items in the hierarchy
        :returns: returns a normal python for loop
        """
        target = items[0]
        iterator_values = items[1]
        body = items[2]
        return convert_to_ast_for_loop(target, iterator_values, body)

    def name_expr(self, items):
        return [convert_to_ast_name_load(item) for item in items]

    def range_expr(self, items):
        return convert_to_ast_call(
            function_name=convert_to_ast_name_load("range"),
            args=[convert_to_ast_constant(item) for item in items]
        )

    def inner_assignment_option(self, items):
        if items[0] == "$":
            accessed_value = items[1]
            value = items[3]
            if len(items) == 5:
                si_value = items[4]
            else:
                si_value = ""
            return ["ATTRIBUTE", accessed_value, value, si_value]
        elif items[0] == "pos":
            accessed_value = items[0]
            pos = items[2]
            return ["POS", accessed_value, pos]
        elif items[0] == "orientation":
            accessed_value = items[0]
            orientation = items[2]
            return ["ORIENTATION", accessed_value, orientation]
        else:
            accessed_value = items[0]
            connected_to = items[2]
            return ["CONNECT", accessed_value, connected_to]

    def net_declaration(self, items):
        """
        Nets for connections which are not point to point
        :param items: current items in the hierarchy
        :returns: returns all net declarations
        """
        nets = []
        for item in items:
            # save as an additional net
            net = convert_to_ast_assignment(
                convert_to_ast_attribute_store(
                    convert_to_ast_name_load("node"),
                    item),
                convert_to_ast_call(function_name=convert_to_ast_name_load("Net"))
            )
            nets.append(net)
        return convert_to_ast_module(nets)

    def assign_route(self, items):
        """
        Route from net to instance
        :param items: current items in the hierarchy
        :returns: returns all net declarations
        """
        net_name = items[0]
        if net_name == "route":
            net_name = "__self__"
            state = items[2]
        else:
            state = items[3]
        routing_net_state  = convert_to_ast_assignment(
            convert_to_ast_subscript_store(
                convert_to_ast_attribute_store(
                    convert_to_ast_name_load("postprocess_data"),
                    "routing"
                ),
                convert_to_ast_constant(net_name)),
            convert_to_ast_constant(state)
        )
        return routing_net_state

    """
    ########### BASIC MATH FUNCTIONS ############
    """
    def math_expr(self, items):
        if len(items) == 3:
            left, op_token, right = items
            op = {
                '+': ast.Add(),
                '-': ast.Sub()
            }[op_token]
            return convert_to_ast_bin_op(
                convert_to_ast_constant(left),
                op,
                convert_to_ast_constant(right))
        return items[0]

    def term(self, items):
        if len(items) == 3:
            left, op_token, right = items
            op = {
                '*': ast.Mult(),
                '/': ast.Div()
            }[op_token]
            return convert_to_ast_bin_op(
                convert_to_ast_constant(left),
                op,
                convert_to_ast_constant(right))
        return items[0]

    def factor(self, items):
        if len(items) == 2:
            op_token, value = items
            op = ast.USub() if op_token == '-' else ast.UAdd()
            return convert_to_ast_unary_op(op, convert_to_ast_constant(value))
        return items[0]

    """
    ############################################
    """

    def flatten(self, lst):
        for item in lst:
            if isinstance(item, list):
                yield from self.flatten(item)
            else:
                yield item

    def get_max_xy_from_layout(self, node):
        def recursive_search(n):
            if isinstance(n, tuple) and not n[1]:
                return 0, 0

            if isinstance(n, tuple) and isinstance(n[1], list) and len(n[1]) == 2 \
                    and not isinstance(n[1][0], tuple):
                x, y = n[1]
                return x, y

            max_x, max_y = 0, 0
            if isinstance(n, tuple) and n[0] in ('series', 'parallel'):
                for child in n[1]:
                    cx, cy = recursive_search(child)
                    if cx > max_x: max_x = cx
                    if cy > max_y: max_y = cy

            return max_x, max_y
        return recursive_search(node)

    def collect_positions(self, node, statements=None, max_coordinates=None):
        if statements is None:
            statements = []
        if max_coordinates is None:
            max_coordinates = [0, 0]

        if isinstance(node, tuple):
            if node[0] in ('series', 'parallel') and isinstance(node[1], list):
                for child in node[1]:
                    self.collect_positions(child, statements, max_coordinates)
            elif isinstance(node[1], list) and isinstance(node[1][0], int):
                # This is a node with a position
                if len(node) == 3:
                    name = node[0]
                    pos = node[1]
                    declaration = node[2]
                    # for declarations
                    statements.append(declaration)
                    arg_x = convert_to_ast_assignment(convert_to_ast_name_store('x'),
                          convert_to_ast_constant(pos[0] * STRUCTURED_SPACING + 2))
                    arg_y = convert_to_ast_assignment(convert_to_ast_name_store('y'),
                        convert_to_ast_constant((max_coordinates[1] - pos[1]) * STRUCTURED_SPACING + STRUCTURED_OFFSET))
                    pos_statement = convert_to_ast_assignment(
                        convert_to_ast_attribute_store(
                            convert_to_ast_name_load(name),
                            "prelim_pos"
                        ),
                        convert_to_ast_call(
                            function_name=convert_to_ast_name_load('Vec2R'),
                            args=[arg_x, arg_y]
                        )
                    )
                    statements.append(pos_statement)
                else:
                    # for ports
                    name = node[0]
                    pos = node[1]
                    self.port_positions[name] = (pos[0] * STRUCTURED_SPACING +
                                                 (STRUCTURED_OFFSET + PORT_OFFSET_X_DEFAULT),
                                 (max_coordinates[1] - pos[1]) * STRUCTURED_SPACING +
                                                 (PORT_OFFSET_Y_DEFAULT + STRUCTURED_OFFSET))
        return convert_to_ast_module(statements)

    def flatten_rows(self, node):
        """
        Flattens a subtree into visual rows.
        Each row is a list of labels that are horizontally aligned.
        """
        kind, children = node[0], node[1]
        if not children:
            return [[node[0]]]

        if kind == 'series':
            rows = []
            for child in children:
                # add the length of the children
                rows += self.flatten_rows(child)
            return rows

        if kind == 'parallel':
            child_rows = [self.flatten_rows(child) for child in children]
            # get the max height of the child rows
            max_height = max(len(rows) for rows in child_rows)
            # merge the rows
            merged_rows = [[] for _ in range(max_height)]
            for rows in child_rows:
                for i, row in enumerate(rows):
                    merged_rows[i].extend(row)
            return merged_rows

        return [[node[0]]]  # fallback

    def extract_constraints(self, tree, distance=4):
        constraints = []
        modules = []

        def recurse_tree(node):
            kind, children = node[0], node[1]
            leaf_groups = []

            for child in children:
                if isinstance(child, tuple) and child[1]:
                    # recursive append
                    leaf_groups.append(recurse_tree(child))
                elif isinstance(child, tuple):
                    # if it is a leaf append the name
                    leaf_groups.append([child[0]])
                    # add to modules if instance not port
                    if len(child) > 2:
                        modules.append(child[2])
                else:
                    leaf_groups.append([])

            if kind == 'series':
                # always get next group and set below, second group, first group
                for i in range(len(leaf_groups) - 1):
                    for upper_leaf in leaf_groups[i]:
                        for lower_leaf in leaf_groups[i + 1]:
                            constraints.append(['below', lower_leaf, upper_leaf, distance])
                return [leaf for group in leaf_groups for leaf in group]

            if kind == 'parallel':
                # LEFT constraints: set left group 1 group 2
                for i in range(len(leaf_groups) - 1):
                    for left_leaf in leaf_groups[i]:
                        for right_leaf in leaf_groups[i+1]:
                            constraints.append(['left', left_leaf, right_leaf, distance])

                # ABOVE constraints: align shorter branches to talest reference
                branch_rows = [self.flatten_rows(child) for child in children]
                branch_heights = [len(rows) for rows in branch_rows]
                # alignment according to max height
                max_height = max(branch_heights)
                tallest_index = branch_heights.index(max_height)
                tallest_rows = branch_rows[tallest_index]

                seen_pairs = set()
                for branch_index, rows in enumerate(branch_rows):
                    # don't set above for the highest branch
                    if len(rows) >= max_height:
                        continue  # skip tallest
                    offset = 1  # start from second row in tallest
                    for row_idx, row in enumerate(rows):
                        target_row = tallest_rows[row_idx + offset]
                        for src_label in row:
                            for tgt_label in target_row:
                                # dont set constraints for same value
                                if src_label == tgt_label:
                                    continue
                                pair = (src_label, tgt_label)
                                if pair in seen_pairs:
                                    continue
                                seen_pairs.add(pair)
                                constraints.append(['above', src_label, tgt_label, distance])

                return [leaf for group in leaf_groups for leaf in group]
            return []
        recurse_tree(tree[0])
        return constraints, modules

    def collect_constraints(self, constraints, modules):
        statements = []
        statements.extend(modules)
        for constraint in constraints:
            statements.append(self.constraint(constraint))
        return convert_to_ast_module(statements)


    def structured(self, items):
        # Call layout to assign positions and get the final layout
        # import pprint
        if STRUCTURED_LIOP:
            constraints, modules = self.extract_constraints(items)
            #pp = pprint.PrettyPrinter(indent=4)
            #pp.pprint(constraints)
            layout = self.collect_constraints(constraints, modules)
        else:
            layout, _, _ = self.layout(items[0], x=0, y=0)
            max_coordinates = self.get_max_xy_from_layout(layout)
            #pp = pprint.PrettyPrinter(indent=4)
            #pp.pprint(layout)
            layout = self.collect_positions(layout, [], max_coordinates)
        return layout

    def layout(self, node, x=0, y=0):
        """
        Calculate the layout of the fixed positioned structured positions
        """
        if isinstance(node, tuple) and node[0] == 'series':
            kind, children = node
            new_children = []
            x_max = x
            y_curr = y

            for child in children:
                laid_out, x_inner, y_inner = self.layout(child, x, y_curr)
                new_children.append(laid_out)
                # also get the max x in the structured layout
                x_max = max(x_max, x_inner)
                y_curr = y_inner + 1  # move to next row

            return ('series', new_children), x_max, y_curr - 1

        elif isinstance(node, tuple) and node[0] == 'parallel':
            kind, children = node
            new_children = []
            x_curr = x
            y_max = y

            for child in children:
                laid_out, x_inner, y_inner = self.layout(child, x_curr, y)
                new_children.append(laid_out)
                # how many columns child took
                width = x_inner - x_curr + 1
                # shift x by width
                x_curr += width
                # track deepest y in the parallel setup
                y_max = max(y_max, y_inner)

            return ('parallel', new_children), x_curr - 1, y_max

        elif isinstance(node, tuple) and len(node) >= 2 and isinstance(node[1], list):
            name = node[0]
            meta = node[2:] if len(node) > 2 else []
            return (name, [x, y], *meta), x, y

        else:
            return (node, [x, y]), x, y

    def series(self, items):
        """
        Serial statements are saved in tuples with first element named "serial"
        """
        for index in range(0, len(items)):
            if isinstance(items[index], str):
                if STRUCTURED_LIOP:
                    items[index] = items[index], []
                else:
                    items[index] = items[index], [0, 0]
        return 'series', items

    def parallel(self, items):
        """
        Parallel statements are saved in tuples with first element named "parallel"
        """
        for index in range(0, len(items)):
            if isinstance(items[index], str):
                if STRUCTURED_LIOP:
                    items[index] = items[index], []
                else:
                    items[index] = items[index], [0, 0]
        return 'parallel', items

    def number(self, items):
        """
        Return the number as a string
        """
        if len(items) == 2:
            return f"-{items[1]}"
        return str(items[0])

    # Simple return and transform nodes
    start = lambda self, items: convert_to_ast_module(items)
    schematic_stmt = lambda self, items: items
    symbol_stmt = lambda self, items: items
    direction = lambda self, items: items[0]
    orientations = lambda self, items: items[0]
    bool = lambda  self, items: items[0]
    NET = lambda self, token: "Net"
    INPUT = lambda self, token: "Input"
    OUTPUT = lambda self, token: "Output"
    INOUT = lambda self, token: "Inout"
    NAME = lambda self, token: token.value
    INSTANCE = lambda self, token: "Instance"
    UNSIGNED = lambda self, number: int(number)
    PASS = lambda self, token: ast.Pass()
    ABOVE = lambda self, token: "above"
    BELOW = lambda self, token: "below"
    RIGHT = lambda self, token: "right"
    LEFT = lambda self, token: "left"
    BULK = lambda  self, token: token.value
    ASSIGN = lambda self, token: token.value
    CONNECT = lambda self, token: token.value
    DOLLAR = lambda self, token: token.value
    POS = lambda self, token: token.value
    FLOAT = lambda self, number: float(number)
    ORIENTATION = lambda self, token: token.value
    EAST = lambda  self, token: "R270"
    NORTH = lambda  self, token: "R0"
    WEST = lambda  self, token: "R90"
    SOUTH = lambda  self, token: "R180"
    FLIPPED_NORTH = lambda  self, token: "MX"
    FLIPPED_SOUTH = lambda  self, token: "MY"
    FLIPPED_WEST = lambda  self, token: "MX90"
    FLIPPED_EAST = lambda  self, token: "MY90"
    TRUE = lambda self, token: True
    FALSE = lambda self, token: False
    ROUTE = lambda self, token: token.value
    PLUS = lambda self, token: token.value
    MINUS = lambda self, token: token.value
    DIV = lambda self, token: token.value
    TIMES = lambda self, token: token.value

