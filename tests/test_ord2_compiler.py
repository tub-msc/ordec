# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.ord2.parser import load_ord2_from_string
import ast

def compare_asts(ord2_code_string):
    or2_ast = load_ord2_from_string(ord2_code_string)
    python_ast = ast.parse(ord2_code_string)
    assert (ast.dump(or2_ast) ==
            ast.dump(python_ast))


def test_class():
    ord_string = "class A(B, C):\n   pass"
    compare_asts(ord_string)

def test_funcdef():
    ord_string = "def func(x:int = 2, *argc, **kwargs):\n   pass"
    compare_asts(ord_string)

def test_return_none():
    ord_string = "def f():\n    return"
    compare_asts(ord_string)

def test_funccall():
    ord_string = "func(1, 2, 3, {'a': 1})"
    compare_asts(ord_string)

def test_function_with_return():
    ord_string = "def func():\n    return 42"
    compare_asts(ord_string)

def test_function_with_yield():
    ord_string = "def gen():\n    yield 1"
    compare_asts(ord_string)

def test_function_with_async():
    ord_string = "async def afunc():\n    await asyncio.sleep(1)"
    compare_asts(ord_string)

def test_decorator():
    ord_string = "@decorator\ndef func():\n  pass"
    compare_asts(ord_string)

def test_list():
    ord_string = "[1, 2, 3]"
    compare_asts(ord_string)

def test_tuple():
    ord_string = "(1, 2, 3)"
    compare_asts(ord_string)

def test_dict():
    ord_string = "{'a': 1, 'b': 2, 'c': 3}"
    compare_asts(ord_string)

def test_if():
    ord_string = "if True:\n  pass"
    compare_asts(ord_string)

def test_if_else():
    ord_string = "if True:\n  pass\nelif False:\n  pass"
    compare_asts(ord_string)

def test_if_elif_else():
    ord_string = "if True:\n  pass\nelif False:\n  pass\nelse:\n  pass"
    compare_asts(ord_string)

def test_while_loop():
    ord_string = "while True:\n  pass\nelse:\n  pass"
    compare_asts(ord_string)

def test_for_loop():
    ord_string = "for i in range(10):\n  pass\nelse:\n  pass"
    compare_asts(ord_string)

def test_async_for_loop():
    ord_string = "async def f():\n    async for x in a:\n        await g(x)"
    compare_asts(ord_string)

def test_async_with_multiple_items():
    ord_string = "async with a as x, b as y:\n    pass"
    compare_asts(ord_string)

def test_nested_loops():
    ord_string = "for i in range(5):\n    while i < 3:\n        i += 1"
    compare_asts(ord_string)

def test_break_continue():
    ord_string = "for i in range(10):\n    if i == 5:\n        break\n    else:\n        continue"
    compare_asts(ord_string)

def test_try_except():
    ord_string = "try:\n  pass\nexcept:\n  pass\nelse:\n  pass\nfinally:\n  pass"
    compare_asts(ord_string)

def test_try_multiple_except():
    ord_string = "try:\n    pass\nexcept ValueError:\n    pass\nexcept TypeError:\n    pass"
    compare_asts(ord_string)

def test_try_except_as():
    ord_string = "try:\n    pass\nexcept Exception as e:\n    print(e)"
    compare_asts(ord_string)

def test_with_stmt():
    ord_string = "with stmt:\n  pass"
    compare_asts(ord_string)

def test_with_as():
    ord_string = "with open('file.txt') as f:\n    data = f.read()"
    compare_asts(ord_string)

def test_async_with():
    ord_string = "async with lock:\n    await do_work()"
    compare_asts(ord_string)

def test_assert():
    ord_string = "assert x > 0, 'x must be positive'"
    compare_asts(ord_string)

def test_del_stmt():
    ord_string = "del x, y"
    compare_asts(ord_string)

def test_pass():
    ord_string = "pass"
    compare_asts(ord_string)

def test_assign_stmt():
    ord_string = "a = 1"
    compare_asts(ord_string)

def test_annotated_assign():
    ord_string = "x: int = 10"
    compare_asts(ord_string)

def test_aug_assign():
    ord_string = "x += 1"
    compare_asts(ord_string)

def test_multiple_assign():
    ord_string = "a = b = c = 5"
    compare_asts(ord_string)

def test_unpack_assign():
    ord_string = "a, b = 1, 2"
    compare_asts(ord_string)

def test_assign_if_expr():
    ord_string = "x = 0 if True else 1"
    compare_asts(ord_string)

def test_arithmetic_expr():
    ord_string = "x = (1 + 2) * (3 - 4) / 5 % 6"
    compare_asts(ord_string)

def test_comparison_expr():
    ord_string = "result = a < b and b >= c or not d"
    compare_asts(ord_string)

def test_bitwise_expr():
    ord_string = "x = a & b | c ^ d << 2 >> 1"
    compare_asts(ord_string)

def test_unary_expr():
    ord_string = "x = -y"
    compare_asts(ord_string)

def test_lambda_expr():
    ord_string = "f = lambda x, y=2: x + y"
    compare_asts(ord_string)

def test_list_comprehension():
    ord_string = "[x * 2 for x in range(5) if x % 2 == 0]"
    compare_asts(ord_string)

def test_dict_comprehension():
    ord_string = "{x: x**2 for x in range(5)}"
    compare_asts(ord_string)

def test_set_comprehension():
    ord_string = "{x for x in range(10)}"
    compare_asts(ord_string)

def test_generator_expression():
    ord_string = "(x * x for x in range(5))"
    compare_asts(ord_string)

def test_import_simple():
    ord_string = "import math"
    compare_asts(ord_string)

def test_import_as():
    ord_string = "import numpy as np"
    compare_asts(ord_string)

def test_from_import():
    ord_string = "from os import path"
    compare_asts(ord_string)

def test_from_import_as():
    ord_string = "from sys import version as v"
    compare_asts(ord_string)

def test_relative_import():
    ord_string = "from . import utils"
    compare_asts(ord_string)

def test_fstring():
    ord_string = "msg = f'Hello {name}!'"
    compare_asts(ord_string)

def test_walrus_operator():
    ord_string = "if (n := len(items)) > 0:\n    print(n)"
    compare_asts(ord_string)

def test_match_case():
    ord_string = "match x:\n    case 1:\n        pass\n    case _:\n        pass"
    compare_asts(ord_string)

def test_global_nonlocal():
    ord_string = "def func():\n    global x\n    nonlocal y"
    compare_asts(ord_string)

def test_ellipsis():
    ord_string = "..."
    compare_asts(ord_string)

def test_raise_stmt():
    ord_string = "raise ValueError('error')"
    compare_asts(ord_string)

def test_raise_no_expr():
    ord_string = "raise"
    compare_asts(ord_string)

def test_posonly_args():
    ord_string = "def f(a, /, b, *, c):\n    pass"
    compare_asts(ord_string)

def test_complex_numbers():
    ord_string = "z = 1 + 2j"
    compare_asts(ord_string)

def test_bytes_literal_r():
    ord_string = "b = rb'hello'"
    compare_asts(ord_string)

def test_bytes_literal_b():
    ord_string = "b = br'hello'"
    compare_asts(ord_string)

def test_bytes_literal_u():
    ord_string = "b = u'hello'"
    compare_asts(ord_string)

def test_set_literal_empty():
    ord_string = "s = set()"
    compare_asts(ord_string)

def test_docstring_module():
    ord_string = "\"\"\"This is a docstring\"\"\""
    compare_asts(ord_string)

def test_match_class_pattern():
    ord_string = "match point:\n    case Point(x, y):\n        pass"
    compare_asts(ord_string)

def test_match_sequence_pattern():
    ord_string = "match lst:\n    case [first, *rest]:\n        pass"
    compare_asts(ord_string)

def test_match_mapping_pattern():
    ord_string = "match d:\n    case {'key': value}:\n        pass"
    compare_asts(ord_string)
