# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports
from lark import Transformer
import ast

#ordec imports
from .misc import Misc


class TopTransformer(Transformer, Misc):

    single_input = lambda self, nodes: nodes[0]
    file_input = lambda self, nodes: ast.Module(body=self._flatten_body(nodes),
                                                type_ignores=[])
    eval_input = lambda self, nodes: nodes[0]
