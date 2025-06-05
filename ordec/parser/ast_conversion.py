# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports
import ast

#ordec imports


"""
########################AST_CONVERT_FUNCTIONS##########################
"""

def convert_to_ast_constant(constant_val):
    return ast.Constant(value=constant_val)

def convert_to_ast_name_store(name):
    return ast.Name(id=name, ctx=ast.Store())


def convert_to_ast_name_load(name):
    return ast.Name(id=name, ctx=ast.Load())


def convert_to_ast_assignment(variable_name, value):
    assignment_node = ast.Assign(
        targets=[variable_name],
        value=value
    )
    return assignment_node


def convert_to_ast_expr(expr):
    expression = ast.Expr(expr)
    return expression


def convert_to_ast_keyword(keyword, value):
    return ast.keyword(arg=keyword, value=value)

def convert_to_ast_starred_load(parameter):
    return ast.Starred(value=convert_to_ast_name_load(parameter), ctx=ast.Load())


# Works for class call and function call
def convert_to_ast_call(function_name, args=None, keywords=None):
    if keywords is None:
        keywords = []
    if args is None:
        args = []
    function_call_node = ast.Call(
        func=function_name,
        args=args,
        keywords=keywords
    )
    return function_call_node

def convert_to_ast_tuple_load(values=None):
    if values is None:
        values = []
    return ast.Tuple(elts=[value for value in values], ctx=ast.Load())

def convert_to_ast_module(statements=None):
    if statements is not None:
        return ast.Module(body=[statement for statement in statements], type_ignores=[])

def convert_to_ast_class_function(class_name, derived_classes, body):
    # Get rid of the nested list
    if isinstance(body, list) and len(body) == 1 and isinstance(body[0], list):
        body = body[0]  # Unwrap the first list level
    class_def = ast.ClassDef(class_name,
                             bases=[convert_to_ast_name_load(derived_class)
                                    for derived_class in derived_classes],
                             body=body,
                             decorator_list=[],
                             keywords=[])
    return class_def


def convert_to_ast_attribute_store(parent_val, attribute_val):
    attribute = ast.Attribute(parent_val,
                              attr=attribute_val,
                              ctx=ast.Store())
    return attribute


def convert_to_ast_attribute_load(parent_val, attribute_val):
    attribute = ast.Attribute(parent_val,
                              attr=attribute_val,
                              ctx=ast.Load())
    return attribute

def convert_to_ast_list_load(values):
    return ast.List(elts=[convert_to_ast_constant(value) for value in values], ctx=ast.Load())

def convert_to_ast_attribute_load_list(attribute_list):
    if len(attribute_list) <= 0:
        print("convert_to_ast_attribute_load_list: Not a valid list")
        return
    elif len(attribute_list) > 1:
        return ast.Attribute(convert_to_ast_attribute_load_list(attribute_list[:-1]),
                              attr=attribute_list[-1],
                              ctx=ast.Load())
    else:
        return convert_to_ast_name_load(attribute_list[0])

def convert_to_ast_attribute_store_list(attribute_list):
    if len(attribute_list) <= 0:
        print("convert_to_ast_attribute_store_list: Not a valid list")
        return
    elif len(attribute_list) > 1:
        return ast.Attribute(convert_to_ast_attribute_load_list(attribute_list[:-1]),
                              attr=attribute_list[-1],
                              ctx=ast.Store())
    else:
        return convert_to_ast_name_load(attribute_list[0])


def convert_to_ast_op(op):
    if op == "%":
        return ast.Mod()
    elif op == "+":
        return ast.Add()
    elif op == "-":
        return ast.Sub()
    elif op == "/":
        return ast.Div()
    elif op == "*":
        return ast.Mult()


def convert_to_ast_bin_op(lhs, op, rhs):
    return ast.BinOp(lhs, op, rhs)

def convert_to_ast_unary_op(op, value):
    return ast.UnaryOp(op=op, operand=value)


def convert_to_ast_dict(keys=None, values=None):
    if values is None:
        values = []
    if keys is None:
        keys = []
    if len(keys) != len(values):
        raise ValueError("Not the same length of keys/values")

    key_nodes = [ast.Constant(value=key) for key in keys]
    value_nodes = [ast.Constant(value=value) for value in values]
    return ast.Dict(keys=key_nodes, values=value_nodes)

def convert_to_ast_for_loop(target, iterator_values, body):
    return ast.For(
        target = convert_to_ast_name_store(target),
        iter = convert_to_ast_tuple_load(iterator_values),
        body=body,
        orelse=[]
    )

# Index access like b = a[1]
def convert_to_ast_subscript_load(value, index_access):
    return ast.Subscript(value=value, slice=index_access, ctx=ast.Load())

def convert_to_ast_subscript_store(value, index_access):
    return ast.Subscript(value=value, slice=index_access, ctx=ast.Store())

def convert_to_ast_function_def(function_name, args, body, decorators, returns=None):
    # Flatten the body list if it's a nested list
    if isinstance(body, list) and len(body) == 1 and isinstance(body[0], list):
        body = body[0]  # Unwrap the first list level

    # Create function arguments
    arguments_node = ast.arguments(
        posonlyargs=[],
        args=[ast.arg(arg=arg, annotation=None) for arg in args],
        vararg=None,
        kwonlyargs=[],
        kw_defaults=[],
        kwarg=None,
        defaults=[]
    )
    # Create function definition
    if returns is None:
        function_def_node = ast.FunctionDef(
            name=function_name,
            args=arguments_node,
            body=body,
            decorator_list=decorators,
            returns=None,
            type_comment=None
        )
    else:
        function_def_node = ast.FunctionDef(
            name=function_name,
            args=arguments_node,
            body=body,
            decorator_list=decorators,
            returns=convert_to_ast_name_load(returns),
            type_comment=None
        )

    return function_def_node


"""
########################TRANSFORMER_FUNCTIONS##########################
"""


# Functions that every cell type needs
# outline should get parameters in the future depending on the amount of inner cells
# --> can be calculated via the x and y coordinates
def helpers_schem_check():
    """
    Function which adds some helper functions
    :return: schem check instance
    """
    schem_check = convert_to_ast_expr(
        convert_to_ast_call(function_name=convert_to_ast_attribute_store(convert_to_ast_name_store("helpers"),
                                                                         "schem_check"),
            args=[convert_to_ast_name_load("node")],
            keywords=[convert_to_ast_keyword("add_conn_points", convert_to_ast_constant(True)),
                      convert_to_ast_keyword("add_terminal_taps", convert_to_ast_constant(False))]))
    return schem_check


def outline(outline_x, outline_y):
    """
    Function which adds the outline border to the schematic and defines the grid size
    :param outline_x: x size of the grid
    :param outline_y: y size of the grid
    :return: ast converted values
    """
    outline_padding = 1
    outline_assignment = convert_to_ast_assignment(
        convert_to_ast_attribute_load(convert_to_ast_name_load("node"), "outline"),
        convert_to_ast_bin_op(
            convert_to_ast_name_load("node"),
            convert_to_ast_op("%"),
            convert_to_ast_call(
                function_name=convert_to_ast_name_load("SchemRect"),
                keywords=[
                    convert_to_ast_keyword("pos",
                       convert_to_ast_call(
                           convert_to_ast_name_load("Rect4R"),
                           keywords=[
                               convert_to_ast_keyword("lx", convert_to_ast_constant(0)),
                               convert_to_ast_keyword("ly", convert_to_ast_constant(1)),
                               convert_to_ast_keyword("ux", convert_to_ast_constant(outline_x +
                                                                                    outline_padding)),
                               convert_to_ast_keyword("uy", convert_to_ast_constant(outline_y +
                                                                                    outline_padding)),
                           ]
                       )
                       )
                ]
            )
        )
    )
    return outline_assignment