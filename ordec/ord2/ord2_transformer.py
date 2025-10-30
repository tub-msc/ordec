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

    def RATIONAL(self, token):
        si_suffixes = ('a','f','p','n','u','m','k','M','G','T')
        if token.endswith(si_suffixes) or '/' in token:
            token = ast.Constant(token.value)
            return ast.Call(func=ast.Name(id="R", ctx=ast.Load()), args=[token])
        else:
            if '.' in token:
                number = float(token)
            else:
                number = token.value.replace("_", "")
                number = int(number, 10)
            return ast.Constant(value=number)

    def pin_stmt(self, nodes):
        pin_type = nodes[0]
        name = nodes[1]
        pos = nodes[2]
        orientation = nodes[3]
        # Get correct pin type
        if pin_type == "inout":
            pin_type = "Inout"
        elif pin_type == "output":
            pin_type = "Out"
        else:
            pin_type = "In"
        # set symbol as reference
        target = ast.Attribute(value=ast.Name(id='symbol', ctx=ast.Load()), attr=name, ctx=ast.Store())
        # keywords: position, pin_type and alignment
        keywords = list()
        keywords.append(ast.keyword(arg='pos', value=pos))
        keywords.append(ast.keyword(arg='pintype', value=ast.Attribute(value=ast.Name(id='PinType',ctx=ast.Load()),
                                                                       attr=pin_type,
                                                                       ctx=ast.Load())))
        keywords.append(ast.keyword(arg='align', value=ast.Attribute(value=ast.Name(id='Orientation',ctx=ast.Load()),
                                                                     attr=orientation,
                                                                     ctx=ast.Load())))
        # wrap in Pin call
        pin_call = ast.Call(func=ast.Name(id='Pin', ctx=ast.Load()),
                            args=[],
                            keywords=keywords)
        # return assignment
        assignment = ast.Assign(targets=[target], value=pin_call)
        return assignment

    def port_stmt(self, nodes):
        name = nodes[0]
        pos = nodes[1]
        orientation = nodes[2]
        # set schematic as reference
        target = ast.Attribute(value=ast.Name(id='schematic', ctx=ast.Load()),
                               attr=name,
                               ctx=ast.Load())
        # keywords: position, reference and alignment
        keywords = list()
        keywords.append(ast.keyword(arg='pos', value=pos))
        keywords.append(ast.keyword(arg='align', value=ast.Attribute(value=ast.Name(id='Orientation',
                                                                                    ctx=ast.Load()),
                                                                     attr=orientation,
                                                                     ctx=ast.Load())))
        # Set symbol as reference
        keywords.append(ast.keyword(arg='ref', value=ast.Attribute(
           value=ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()), attr='symbol', ctx=ast.Load()),
            attr=name,
            ctx=ast.Load()
        )))
        # Wrap in port call
        port_call = ast.Call(func=ast.Name(id='SchemPort', ctx=ast.Load()),
                             keywords=keywords,
                             args=[])

        # Return binary expression
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
        # Create suite assignment rhs
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

        # combine to full suite assignment
        suite_assignment = ast.Assign(
            targets=[suite_target],
            value=suite_func_call
        )
        # insert assignment before first inner content
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



    SI = lambda self, token: token.value
    PIN_TYPE = lambda self, token: token.value
    ORIENTATION = lambda self, token: token.value
