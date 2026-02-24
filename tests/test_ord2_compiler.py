# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.ord2.parser import ord2_to_py
import ast

def compare_asts(ord2_code_string):
    or2_ast = ord2_to_py(ord2_code_string)
    python_ast = ast.parse(ord2_code_string)
    assert (ast.dump(or2_ast) ==
            ast.dump(python_ast))

def test_class_empty():
    ord_string = "class A():\n   pass"
    compare_asts(ord_string)

def test_class_inherit():
    ord_string = "class A(B, C):\n   pass"
    compare_asts(ord_string)

def test_class_keyword():
    ord_string = "class A(B, metaclass=Meta):\n   pass"
    compare_asts(ord_string)

def test_funcdef():
    ord_string = "def f():\n    pass"
    compare_asts(ord_string)

def test_function_with_return():
    ord_string = "def func():\n    return 1"
    compare_asts(ord_string)

def test_return_string():
    ord_string = "def f():\n    return 'Hello'"
    compare_asts(ord_string)

def test_funcdef_return_type():
    ord_string = "def f() -> int:\n    return 1"
    compare_asts(ord_string)

def test_funcdef_oneline():
    ord_string = "def f(): x = 1; return x"
    compare_asts(ord_string)

def test_funcdef_posargs():
    ord_string = "def f(a, /, b):\n    return 'Hello'"
    compare_asts(ord_string)

def test_funcdef_star():
    ord_string = "def func(*, a):\n    pass"
    compare_asts(ord_string)

def test_funcdef_star_args():
    ord_string = "def f(*args):\n    pass"
    compare_asts(ord_string)

def test_funcdef_kwargs():
    ord_string = "def f(**kwargs):\n    pass"
    compare_asts(ord_string)

def test_funcdef_complex():
    ord_string = "def func(x:int = 2, *argc, **kwargs):\n   pass"
    compare_asts(ord_string)

def test_async_await():
    ord_string = "await sleep(1)"
    compare_asts(ord_string)

def test_funcdef_with_async():
    ord_string = "async def func():\n    await asyncio.sleep(1)"
    compare_asts(ord_string)

def test_funccall_arg():
    ord_string = "func(1)"
    compare_asts(ord_string)

def test_funccall_keyword():
    ord_string = "func(a=3)"
    compare_asts(ord_string)

def test_funccall_starargs():
    ord_string = "func(*args)"
    compare_asts(ord_string)

def test_funccall_kwargs():
    ord_string = "func(**kwargs)"
    compare_asts(ord_string)

def test_funccall_comprehension():
    ord_string = "func([x*2 for x in range(10)])"
    compare_asts(ord_string)

def test_funccall_comprehension_nested():
    ord_string = "b''.join(string.tostring(val) for val in lst)"
    compare_asts(ord_string)

def test_funccall_complex():
    ord_string = "func(*args, a=1, b=2, **kwargs)"
    compare_asts(ord_string)

def test_function_with_yield():
    ord_string = "def gen():\n    yield 1"
    compare_asts(ord_string)

def test_function_with_yield_from():
    ord_string = "yield from x"
    compare_asts(ord_string)

def test_decorator():
    ord_string = "@decorator\ndef func():\n  pass"
    compare_asts(ord_string)

def test_decorator_multiple():
    ord_string = "@decorator\n@test\ndef func():\n  pass"
    compare_asts(ord_string)

def test_decorator_argument():
    ord_string = "@decorator(1)\ndef func():\n  pass"
    compare_asts(ord_string)

def test_decorator_keyword():
    ord_string = "@decorator(x=2)\ndef func():\n  pass"
    compare_asts(ord_string)

def test_simple_stmt():
    ord_string = "x=0;y=1"
    compare_asts(ord_string)

def test_list():
    ord_string = "[1, 2, 3]"
    compare_asts(ord_string)

def test_tuple():
    ord_string = "(1, 2, 3)"
    compare_asts(ord_string)

def test_set():
    ord_string = "{1, 2, 3}"
    compare_asts(ord_string)

def test_dict():
    ord_string = "{'a': 1, 'b': 2, 'c': 3}"
    compare_asts(ord_string)

def test_dict_star():
    ord_string = "{**star_dict}"
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

def test_for_multi_targets():
    ord_string = "for x, y in val_dict.items():\n pass"
    compare_asts(ord_string)

def test_async_for_loop():
    ord_string = "async for i in range(10):\n  pass\nelse:\n  pass"
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

def test_try_finally():
    ord_string = "try:\n  pass\nfinally:\n  pass"
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

def test_with_as_tuple_target():
    ord_string = "with ctx() as (a, b):\n    pass"
    compare_asts(ord_string)

def test_with_as_attribute_target():
    ord_string = "with ctx() as a.b:\n    pass"
    compare_asts(ord_string)

def test_with_as_subscript_target():
    ord_string = "with ctx() as a[0]:\n    pass"
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

def test_testlist():
    ord_string = "x < 1, y > 2,"
    compare_asts(ord_string)

def test_bitwise_expr():
    ord_string = "x = a & b | c ^ d << 2 >> 1"
    compare_asts(ord_string)

def test_unary_expr():
    ord_string = "x = -y"
    compare_asts(ord_string)

def test_lambda():
    ord_string = "x = lambda : 1"
    compare_asts(ord_string)

def test_lambda_keyword():
    ord_string = "x = lambda x = 2: x"
    compare_asts(ord_string)

def test_lambda_arg():
    ord_string = "f = lambda x: x"
    compare_asts(ord_string)

def test_lambda_arg_keyword():
    ord_string = "f = lambda x, y=2: x + y"
    compare_asts(ord_string)

def test_lambda_posonly():
    ord_string = "f = lambda x, /, y: x + y"
    compare_asts(ord_string)

def test_lambda_posonly_with_defaults():
    ord_string = "f = lambda x=1, /, y=2: x + y"
    compare_asts(ord_string)

def test_lambda_posonly_with_kwonly():
    ord_string = "f = lambda x, /, *, y: x + y"
    compare_asts(ord_string)

def test_lambda_keyword_after_star():
    ord_string = "f = lambda *args, y=2: y"
    compare_asts(ord_string)

def test_lambda_star_args():
    ord_string = "f = lambda *args, **kwargs: (args, kwargs)"
    compare_asts(ord_string)

def test_lambda_complex():
    ord_string = "f = lambda **kwargs: show_info(**{k: v for k, v in kwargs.items()})"
    compare_asts(ord_string)

def test_lambda_list_stararg():
    ord_string = "f = lambda *args: show_numbers(*[x for x in args if x > 0])"
    compare_asts(ord_string)

def test_list_comprehension():
    ord_string = "[x * 2 for x in range(5) if x % 2 == 0]"
    compare_asts(ord_string)

def test_list_comprehension_multiple_ifs():
    ord_string = "[x for x in range(10) if x > 1 if x < 8]"
    compare_asts(ord_string)

def test_dict_comprehension():
    ord_string = "{x: x**2 for x in range(5)}"
    compare_asts(ord_string)

def test_dict_comprehension_multiple_ifs():
    ord_string = "{x: x**2 for x in range(10) if x > 1 if x < 8}"
    compare_asts(ord_string)

def test_set_comprehension():
    ord_string = "{x for x in range(10)}"
    compare_asts(ord_string)

def test_async_comprehension():
    ord_string = "[x async for x in range(10)]"
    compare_asts(ord_string)

def test_generator_expression():
    ord_string = "(x * x for x in range(5))"
    compare_asts(ord_string)

def test_import_simple():
    ord_string = "import math"
    compare_asts(ord_string)

def test_import_all():
    ord_string = "from math import *"
    compare_asts(ord_string)

def test_import_multiple():
    ord_string = "import math, numpy, os.path"
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

def test_from_relative_nested():
    ord_string = "from ...ord2 import parser"
    compare_asts(ord_string)

def test_relative_import():
    ord_string = "from . import utils"
    compare_asts(ord_string)

def test_walrus_operator():
    ord_string = "if (n := len(items)) > 0:\n    print(n)"
    compare_asts(ord_string)

def test_nonlocal():
    ord_string = "nonlocal y"
    compare_asts(ord_string)

def test_global_var():
    ord_string = "global x"
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
    
def test_raise_from():
    ord_string = "raise RuntimeError('Failed to parse number') from e"
    compare_asts(ord_string)

def test_posonly_args():
    ord_string = "def f(a, /, b, *, c):\n    pass"
    compare_asts(ord_string)

def test_complex_numbers():
    ord_string = "z = 1 + 2j"
    compare_asts(ord_string)

def test_literal():
    ord_string = "r'hello'"
    compare_asts(ord_string)

def test_bytes_literal_r():
    ord_string = "rb'hello'"
    compare_asts(ord_string)

def test_bytes_literal_b():
    ord_string = "br'hello'"
    compare_asts(ord_string)

def test_bytes_literal_u():
    ord_string = "u'hello'"
    compare_asts(ord_string)

def test_set_literal_empty():
    ord_string = "s = set()"
    compare_asts(ord_string)

def test_docstring_module():
    ord_string = "\"\"\"This is a docstring\"\"\""
    compare_asts(ord_string)

def test_docstring_module_binary():
    ord_string = "b\"\"\"This is a docstring\"\"\""
    compare_asts(ord_string)

def test_match_case():
    ord_string = "match x:\n    case 1:\n        pass\n    case _:\n        pass"
    compare_asts(ord_string)

def test_match_case_singleton():
    ord_string = "match x:\n    case True:\n        pass"
    compare_asts(ord_string)

def test_match_case_sequence():
    ord_string = "match x:\n    case 1, 2:\n        pass"
    compare_asts(ord_string)

def test_match_case_or():
    ord_string = "match x:\n    case 1 | 2:\n        pass"
    compare_asts(ord_string)

def test_match_case_as():
    ord_string = "match x:\n    case test as t:\n        pass"
    compare_asts(ord_string)

def test_match_case_if():
    ord_string = "match x:\n    case test if False:\n        pass"
    compare_asts(ord_string)

def test_match_args_pattern():
    ord_string = "match point:\n    case Point(x, y):\n        pass"
    compare_asts(ord_string)

def test_match_get_pattern():
    ord_string = "match point:\n    case pointclass.Point(x, y):\n        pass"
    compare_asts(ord_string)

def test_match_keywords_pattern():
    ord_string = "match point:\n    case Point(width=x, height=y):\n        pass"
    compare_asts(ord_string)

def test_match_arg_keyword_mixed():
    ord_string = "match point:\n    case Point(x, height=y):\n        pass"
    compare_asts(ord_string)

def test_match_list_pattern():
    ord_string = "match lst:\n    case [first, *rest]:\n        pass"
    compare_asts(ord_string)

def test_match_binary():
    ord_string = "match x:\n    case b'test':\n        pass"
    compare_asts(ord_string)

def test_match_unicode():
    ord_string = "match x:\n    case u'test':\n        pass"
    compare_asts(ord_string)

def test_match_raw():
    ord_string = "match x:\n    case r'test':\n        pass"
    compare_asts(ord_string)

def test_match_dict():
    ord_string = "match x:\n    case {'key': value}:\n        pass"
    compare_asts(ord_string)

def test_match_dict_star_pattern():
    ord_string = "match x:\n    case {'key': value, **rest}:\n        pass"
    compare_asts(ord_string)

def test_fstring():
    ord_string = "msg = f'Hello {name}!'"
    compare_asts(ord_string)

def test_f_string_escaped():
    ord_string = "multi_complex = f\"{{{{\'hello\'}}}}\""
    compare_asts(ord_string)

def test_f_string_format_complex_single():
    ord_string = "f'{a:>5.2f}, {b:<5.2f}, {c:^10.3e}'"
    compare_asts(ord_string)

def test_f_string_format_complex_double():
    ord_string = "f\"{a:>5.2f}, {b:<5.2f}, {c:^10.3e}\""
    compare_asts(ord_string)

def test_f_string_arith():
    ord_string = "f\"Value: {1 + 2}\""
    compare_asts(ord_string)

def test_f_string_double_quote():
    ord_string = "f\"{1}\""
    compare_asts(ord_string)

def test_f_string_single_quote():
    ord_string = "f'{1}'"
    compare_asts(ord_string)

def test_f_string_spec_double():
    ord_string = "f\"{test!r}\""
    compare_asts(ord_string)

def test_f_string_debug():
    ord_string = "f\"{value=}\""
    compare_asts(ord_string)

def test_f_string_debug_with_conversion():
    ord_string = "f\"{value=!r}\""
    compare_asts(ord_string)

def test_f_string_debug_with_spec():
    ord_string = "f\"{value=:>10}\""
    compare_asts(ord_string)

def test_f_string_escaped_call():
    ord_string = "f\"Value: {{{print(3 + 4)}}}\""
    compare_asts(ord_string)

def test_f_string_escape_newline():
    ord_string = "f\"line1\\n{value}\\nline2\""
    compare_asts(ord_string)

def test_raw_f_string_escape_newline():
    ord_string = "fr\"line1\\n{value}\\nline2\""
    compare_asts(ord_string)

def test_string_concat():
    ord_string = "'Hello ' + 'World'"
    compare_asts(ord_string)

def test_string_concat_implicit():
    ord_string = "'Hello ' 'World'"
    compare_asts(ord_string)

def test_string_escape_single_quote():
    ord_string = "x = 'a\\'b'"
    compare_asts(ord_string)

def test_bytes_escape_hex():
    ord_string = "x = b'\\xff'"
    compare_asts(ord_string)

def test_long_string_escape_newline():
    ord_string = "x = '''line1\\nline2'''"
    compare_asts(ord_string)

def test_string_mod():
    ord_string = "'Hello %s %s' % (1,2)"
    compare_asts(ord_string)

def test_list_subscript():
    ord_string = "lst[1]"
    compare_asts(ord_string)

def test_subscript_numpy():
    ord_string = "lst[1,:]"
    compare_asts(ord_string)

def test_hex_number():
    ord_string = "0x12AB"
    compare_asts(ord_string)

def test_octal_number():
    ord_string = "0o1234"
    compare_asts(ord_string)

def test_binary_number():
    ord_string = "0b1010"
    compare_asts(ord_string)

def test_scientific_notation_float():
    ord_string = "1e-9"
    compare_asts(ord_string)

def test_slice():
    ord_string = "lst[1:2]"
    compare_asts(ord_string)

def test_slice_reverse():
    ord_string = "lst[::-1]"
    compare_asts(ord_string)

def test_slice_and_step():
    ord_string = "lst[1:10:2]"
    compare_asts(ord_string)

def test_comment():
    ord_string = "# This is a comment"
    compare_asts(ord_string)

def test_match_mapping_attr_key():
    ord_string = "match x:\n    case {Color.RED: y}:\n        pass"
    compare_asts(ord_string)

def test_match_mapping_singleton_keys():
    ord_string = "match x:\n    case {True: y, None: z}:\n        pass"
    compare_asts(ord_string)
