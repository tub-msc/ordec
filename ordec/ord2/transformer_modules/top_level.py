# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports
from lark import Transformer
import ast


class TopTransformer(Transformer):

    def __init__(self):
        pass

    single_input = lambda self, nodes: nodes[0]
    file_input = lambda self, nodes: ast.Module(body=nodes, type_ignores=[])
    eval_input = lambda self, nodes: nodes[0]
