# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from lark import Transformer
import ast

class DefinitionTransformer(Transformer):

    def __init__(self):
        pass

    def decorator(self, nodes):
        dotted_name = nodes[0]
        func_name = ast.Name(id=dotted_name, ctx=ast.Load())

        if len(nodes) > 1 and nodes[1]:
            args, keywords = nodes[1]
            return ast.Call(func=func_name, args=args, keywords=keywords)
        return func_name

    def decorated(self, nodes):
        decorators = nodes[0]
        definition = nodes[1]
        # classdef, funcdef, async funcdef
        definition.decorator_list = decorators
        return definition

    def funcdef(self, nodes):
        name = str(nodes[0])
        if isinstance(nodes[1], ast.arguments):
            parameters = nodes[1]
            rest = nodes[2:]
        else:
            parameters = ast.arguments(
                posonlyargs=[],
                args=[],
                vararg=None,
                kwonlyargs=[],
                kw_defaults=[],
                kwarg=None,
                defaults=[]
            )
            rest = nodes[1:]

        # Extract return type and suite
        if len(rest) == 2:
            return_type, suite = rest
        else:
            return_type = None
            suite = rest[0]

        if return_type is not None and isinstance(return_type, str):
            return_type = ast.Name(id=return_type, ctx=ast.Load())

        return ast.FunctionDef(
            name=name,
            args=parameters,
            body=suite,
            decorator_list=[],
            returns=return_type
        )

    def async_funcdef(self, nodes):
        funcdef = nodes[0] if isinstance(nodes, list) else nodes
        name = funcdef.name
        args = funcdef.args
        body = funcdef.body
        returns = funcdef.returns
        return ast.AsyncFunctionDef(
            name=name,
            args=args,
            body=body,
            decorator_list=[],
            returns=returns
        )

    def classdef(self, nodes):
        name = nodes[0]

        if len(nodes) == 3:
            bases_node = nodes[1]
            suite = nodes[2]
        else:
            bases_node = []
            suite = nodes[1]

        bases = bases_node if isinstance(bases_node, list) else []

        return ast.ClassDef(
            name=name,
            bases=bases,
            keywords=[],
            body=suite,
            decorator_list=[]
        )

    suite = lambda self, nodes: nodes
    decorators = lambda self, nodes: nodes
    arguments = lambda self, nodes: nodes




