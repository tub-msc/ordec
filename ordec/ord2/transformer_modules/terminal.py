# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports
from lark import Transformer
import ast

class Terminal(Transformer):

    def DEC_NUMBER(self, nodes):
        value = nodes.value.replace("_", "")
        return ast.Constant(value=int(value, 10))

    def HEX_NUMBER(self, nodes):
        value = nodes.value.replace("_", "")
        return ast.Constant(value=int(value, 16))

    def OCT_NUMBER(self, nodes):
        value = nodes.value.replace("_", "")
        return ast.Constant(value=int(value, 8))

    def BIN_NUMBER(self, nodes) -> ast.Constant:
        value = nodes.value.replace("_", "")
        return ast.Constant(value=int(value, 2))

    IMAG_NUMBER = lambda self, token: ast.Constant(value=complex(token.value))
    FLOAT_NUMBER = lambda self, token: ast.Constant(value=float(token.value))
    DECIMAL = lambda self, token: ast.Constant(value=float(token.value))
    NAME = lambda self, token: token.value
    ASYNC = lambda self, token: token.value
    AWAIT = lambda self, token: token.value
    MARK = lambda self, token: token.value
    FSTRING_TEXT_SINGLE = lambda self, token: token.value
    FSTRING_TEXT_DOUBLE = lambda self, token: token.value
    FSTRING_SINGLE_START = lambda self, token: token.value
    FSTRING_DOUBLE_START = lambda self, token: token.value
    FSTRING_SINGLE_END = lambda self, token: token.value
    FSTRING_DOUBLE_END = lambda self, token: token.value
    SLASH = lambda self, token: token.value
    STRING_OTHER_PREFIX = lambda self, token: token.value