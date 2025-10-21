# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.ord2.parser import load_ord2_from_string
import ast

def compare_asts(ord2_code_string):
    or2_ast = load_ord2_from_string(ord2_code_string)
    python_ast = ast.parse(ord2_code_string)
    assert (ast.dump(or2_ast, include_attributes=False) ==
            ast.dump(python_ast, include_attributes=False))


def test_class():
    ord_string = ("""class A(B, C):
        pass""")
    compare_asts(ord_string)