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

    SI_SUFFIX = lambda self, token: token.value
