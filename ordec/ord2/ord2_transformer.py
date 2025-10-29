# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import ast

# ordec imports
from .python_transformer import PythonTransformer


class Ord2Transformer(PythonTransformer):

    def celldef(self, nodes):
        cell_name = nodes[0]
        suite = nodes[1]
        base = ast.Name(id='Cell', ctx=ast.Load())

        return ast.ClassDef(
            name=cell_name,
            bases=[base],
            keywords=[],
            body=suite,
            decorator_list=[],
            type_params=[]
        )

    def rational_number(self, nodes):
        if len(nodes) > 2:
            rational_number = ast.Constant(str(nodes[0].value) + str(nodes[2].value))
        else:
            rational_number = ast.Constant(str(nodes[0].value) + nodes[1])
        return ast.Call(func=ast.Name(id="R", ctx=ast.Load()), args=[rational_number])

    def pin_stmt(self, nodes):
        pin_type = nodes[0]
        name = nodes[1]
        pos = nodes[2]
        orientation = nodes[3]
        if pin_type == "inout":
            pin_type = "Inout"
        elif pin_type == "output":
            pin_type = "Out"
        else:
            pin_type = "In"
        target = ast.Attribute(value=ast.Name(id='symbol', ctx=ast.Load()), attr=name, ctx=ast.Store())
        keywords = list()
        keywords.append(ast.keyword(arg='pos', value=pos))
        keywords.append(ast.keyword(arg='pintype', value=ast.Attribute(value=ast.Name(id='PinType',ctx=ast.Load()),
                                                                       attr=pin_type,
                                                                       ctx=ast.Load())))
        keywords.append(ast.keyword(arg='align', value=ast.Attribute(value=ast.Name(id='Orientation',ctx=ast.Load()),
                                                                     attr=orientation,
                                                                     ctx=ast.Load())))
        pin_call = ast.Call(func=ast.Name(id='Pin', ctx=ast.Load()),
                            args=[],
                            keywords=keywords)

        assignment = ast.Assign(targets=[target], value=pin_call)
        return assignment

    def port_stmt(self, nodes):
        name = nodes[0]
        pos = nodes[1]
        orientation = nodes[2]

        target = ast.Attribute(value=ast.Name(id='schematic', ctx=ast.Load()),
                               attr=name,
                               ctx=ast.Load())

        keywords = list()
        keywords.append(ast.keyword(arg='pos', value=pos))
        keywords.append(ast.keyword(arg='align', value=ast.Attribute(value=ast.Name(id='Orientation',
                                                                                    ctx=ast.Load()),
                                                                     attr=orientation,
                                                                     ctx=ast.Load())))
        keywords.append(ast.keyword(arg='ref', value=ast.Attribute(
           value=ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()), attr='symbol', ctx=ast.Load()),
            attr=name,
            ctx=ast.Load()
        )))

        port_call = ast.Call(func=ast.Name(id='SchemPort', ctx=ast.Load()),
                             keywords=keywords,
                             args=[])

        expression = ast.Expr(
            value = ast.BinOp(
                left = target,
                op = ast.Mod(),
                right = port_call
            )
        )
        return expression


    def cell_func_def(self, nodes):
        func_name = nodes[0]
        suite = nodes[1]
        suite_target = ast.Name(id=func_name, ctx=ast.Store())
        keywords = list()
        keywords.append(ast.keyword(arg='cell',
                                    value=ast.Name(id='self',
                                                   ctx=ast.Load())
                                    )
                        )

        suite_func_call = ast.Call(func=ast.Name(id=func_name.title(),
                                           ctx=ast.Load()),
                             args=[],
                             keywords=keywords)

        # combine to inner assignment
        suite_assignment = ast.Assign(
            targets=[suite_target],
            value=suite_func_call
        )

        # insert assignment before first inner assignment
        suite.insert(0, suite_assignment)

        # Combine to function definition
        func_def = ast.FunctionDef(
            name=func_name,
            args=ast.arguments(
                posonlyargs=[],
                args=[ast.arg(arg='self')],
                kwonlyargs=[],
                kw_defaults=[]
            ),
            body=suite,
            decorator_list=[],
            returns=ast.Name(id=func_name.title(),
                             ctx=ast.Load()),
            type_params=[]
        )
        return func_def



    SI_SUFFIX = lambda self, token: token.value
    PIN_TYPE = lambda self, token: token.value
    ORIENTATION = lambda self, token: token.value
