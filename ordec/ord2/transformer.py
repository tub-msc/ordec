# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports

# ordec imports
from .transformer_modules.compound import CompoundTransformer
from .transformer_modules.definition import DefinitionTransformer
from .transformer_modules.expression import ExpressionTransformer
from .transformer_modules.match_case import MatchCaseTransformer
from .transformer_modules.param_and_arg import ParamArgTransformer
from .transformer_modules.statement import StatementTransformer
from .transformer_modules.terminal import Terminal
from .transformer_modules.top_level import TopTransformer

class Ord2Transformer(CompoundTransformer,
                      DefinitionTransformer,
                      ExpressionTransformer,
                      MatchCaseTransformer,
                      ParamArgTransformer,
                      StatementTransformer,
                      Terminal,
                      TopTransformer):
    def __init__(self):
        pass
