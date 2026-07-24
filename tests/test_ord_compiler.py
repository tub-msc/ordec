# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.ord import ord_to_py
import ast
import pytest

def compare_asts(ord_code_string):
    ord_ast = ord_to_py(ord_code_string)
    python_ast = ast.parse(ord_code_string)
    assert (ast.dump(ord_ast) ==
            ast.dump(python_ast))

def compare_syntax_errors(ord_code_string):
    with pytest.raises(SyntaxError):
        ast.parse(ord_code_string)
    # SyntaxErrors raised by transformer callbacks must surface as plain
    # SyntaxError, not wrapped in lark's VisitError (ord_to_py unwraps).
    with pytest.raises(SyntaxError):
        ord_to_py(ord_code_string)

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

def test_with_as_list_target():
    ord_string = "with ctx() as [a, *b]:\n    pass"
    compare_asts(ord_string)

def test_with_as_invalid_call_target():
    ord_string = "with ctx() as f():\n    pass"
    compare_syntax_errors(ord_string)

def test_with_as_invalid_expression_target():
    ord_string = "with ctx() as (a + b):\n    pass"
    compare_syntax_errors(ord_string)

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
    ord_string = "from ...ord import parser"
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

def test_match_empty_class_pattern():
    ord_string = "match point:\n    case Point():\n        pass"
    compare_asts(ord_string)

def test_match_empty_class_as_pattern():
    ord_string = "match point:\n    case Point() as p:\n        pass"
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

def test_f_string_debug_with_spaces():
    ord_string = "f\"{value = !r}\""
    compare_asts(ord_string)

def test_f_string_debug_parenthesized():
    ord_string = "f\"{(x+y)=}\""
    compare_asts(ord_string)

def test_f_string_debug_spacing_preserved():
    ord_string = "f\"{x   +   y=}\""
    compare_asts(ord_string)

def test_f_string_debug_not_equal_edge():
    ord_string = "f\"{x!=y=}\""
    compare_asts(ord_string)

def test_f_string_debug_ifexpr_not_equal():
    ord_string = "f\"{x if y!=z else t=}\""
    compare_asts(ord_string)

def test_f_string_debug_subscript_not_equal():
    ord_string = "f\"{a[1!=2]=}\""
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

def test_bytes_escape_unicode_literal():
    ord_string = "x = b'\\\\u0041'"
    compare_asts(ord_string)

def test_long_string_escape_newline():
    ord_string = "x = '''line1\\nline2'''"
    compare_asts(ord_string)

def test_string_escape_hex_invalid():
    ord_string = "x = '\\x4'"
    compare_syntax_errors(ord_string)

def test_string_escape_unicode_short_invalid():
    ord_string = "x = '\\u12'"
    compare_syntax_errors(ord_string)

def test_string_escape_unicode_name_invalid():
    ord_string = "x = '\\N{NO_SUCH_NAME}'"
    compare_syntax_errors(ord_string)

def test_bytes_escape_hex_invalid():
    ord_string = "x = b'\\x4'"
    compare_syntax_errors(ord_string)

def test_bytes_non_ascii_invalid():
    ord_string = "x = b'ä'"
    compare_syntax_errors(ord_string)

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

def test_lineno_propagation():
    code = "x = 1\ny = 2\nz = 3"
    tree = ord_to_py(code)
    assert tree.body[0].lineno == 1
    assert tree.body[1].lineno == 2
    assert tree.body[2].lineno == 3

def test_lineno_celldef():
    code = "cell Foo:\n    pass"
    tree = ord_to_py(code)
    assert tree.body[0].lineno == 1

def test_except_star():
    ord_string = "try:\n    pass\nexcept* ValueError:\n    pass"
    compare_asts(ord_string)

def test_type_alias_stmt():
    ord_string = "type Vec[T] = list[T]"
    compare_asts(ord_string)

def test_funcdef_type_params():
    ord_string = "def identity[T](x: T) -> T:\n    return x"
    compare_asts(ord_string)

def test_funcdef_type_param_default():
    ord_string = "def identity[T = int](x: T) -> T:\n    return x"
    compare_asts(ord_string)

def test_funcdef_bounded_type_param_default():
    ord_string = "def identity[T: int = bool](x: T) -> T:\n    return x"
    compare_asts(ord_string)

def test_classdef_type_params():
    ord_string = "class Box[T]:\n    pass"
    compare_asts(ord_string)

def test_classdef_type_param_defaults():
    ord_string = "class Box[T = int, *Ts = tuple[int, ...], **P = [int, str]]:\n    pass"
    compare_asts(ord_string)

def test_decorator_call_expression():
    ord_string = "@(decorator_factory())\ndef f():\n    pass"
    compare_asts(ord_string)

def test_decorator_subscript_expression():
    ord_string = "@decorators[0]\ndef f():\n    pass"
    compare_asts(ord_string)

def test_decorator_dotted_call_ast():
    ord_string = "@pkg.decorator(arg=1)\ndef f():\n    pass"
    compare_asts(ord_string)

def test_decorator_nonconstant_argument():
    ord_string = "@decorator(x)\ndef f():\n    pass"
    compare_asts(ord_string)

def test_decorator_kwargs():
    ord_string = "@decorator(**kw)\ndef f():\n    pass"
    compare_asts(ord_string)

def test_compare_not_in():
    ord_string = "x = a not in b"
    compare_asts(ord_string)

def test_compare_is_not():
    ord_string = "x = a is not b"
    compare_asts(ord_string)

def test_call_positional_after_stararg():
    ord_string = "func(*args, 1)"
    compare_asts(ord_string)

def test_call_multiple_kwargs_unpacking():
    ord_string = "func(**a, **b)"
    compare_asts(ord_string)

def test_class_starred_base():
    ord_string = "class A(*bases):\n    pass"
    compare_asts(ord_string)

def test_class_kwargs_base():
    ord_string = "class A(**kw):\n    pass"
    compare_asts(ord_string)

def test_parenthesized_with_items():
    ord_string = "with (a as x, b as y):\n    pass"
    compare_asts(ord_string)

def test_comprehension_filter_before_second_for():
    ord_string = "[(x, y) for x in xs if x for y in ys]"
    compare_asts(ord_string)

def test_triple_quoted_f_string():
    ord_string = "f'''hello {name}'''"
    compare_asts(ord_string)

def test_uppercase_f_string_prefix():
    ord_string = "F'{name}'"
    compare_asts(ord_string)

def test_match_negative_literal_pattern():
    ord_string = "match x:\n    case -1:\n        pass"
    compare_asts(ord_string)

def test_match_dotted_value_pattern():
    ord_string = "match x:\n    case Color.RED:\n        pass"
    compare_asts(ord_string)

def test_match_star_wildcard_pattern():
    ord_string = "match x:\n    case [*_]:\n        pass"
    compare_asts(ord_string)

def test_parenthesized_annotation_simple_flag():
    ord_string = "(x): int"
    compare_asts(ord_string)

def test_invalid_bare_walrus():
    ord_string = "x := 1"
    compare_syntax_errors(ord_string)

def test_invalid_old_not_equal_operator():
    ord_string = "x = a <> b"
    compare_syntax_errors(ord_string)

def test_assignment_starred_target():
    ord_string = "*a, = b"
    compare_asts(ord_string)

def test_assignment_empty_tuple_target():
    ord_string = "() = values"
    compare_asts(ord_string)

def test_invalid_assignment_literal_target():
    ord_string = "1 = x"
    compare_syntax_errors(ord_string)

def test_invalid_assignment_expression_target():
    ord_string = "a + b = x"
    compare_syntax_errors(ord_string)

def test_invalid_assignment_call_target():
    ord_string = "f() = x"
    compare_syntax_errors(ord_string)

def test_invalid_augassign_tuple_target():
    ord_string = "a, b += c"
    compare_syntax_errors(ord_string)

def test_invalid_augassign_starred_target():
    ord_string = "*a += b"
    compare_syntax_errors(ord_string)

def test_invalid_annassign_tuple_target():
    ord_string = "a, b: int"
    compare_syntax_errors(ord_string)

def test_invalid_annassign_call_target():
    ord_string = "f(): int"
    compare_syntax_errors(ord_string)

def test_invalid_del_literal_target():
    ord_string = "del 1"
    compare_syntax_errors(ord_string)

def test_invalid_del_starred_target():
    ord_string = "del *items"
    compare_syntax_errors(ord_string)

def test_invalid_for_literal_target():
    ord_string = "for 1 in values:\n    pass"
    compare_syntax_errors(ord_string)

def test_invalid_for_expression_target():
    ord_string = "for a + b in values:\n    pass"
    compare_syntax_errors(ord_string)

def test_invalid_function_default_order():
    ord_string = "def f(a=1, b):\n    pass"
    compare_syntax_errors(ord_string)

def test_invalid_ur_string_prefix():
    ord_string = "ur'x'"
    compare_syntax_errors(ord_string)

def test_subscript_starred_single():
    ord_string = "tuple[*Ts]"
    compare_asts(ord_string)

def test_subscript_starred_tuple():
    ord_string = "tuple[int, *Ts]"
    compare_asts(ord_string)

def test_type_alias_typevartuple_used():
    ord_string = "type TupleAlias[*Ts] = tuple[*Ts]"
    compare_asts(ord_string)

def test_type_alias_type_param_default():
    ord_string = "type Alias[T = int] = list[T]"
    compare_asts(ord_string)

def test_type_alias_bounded_type_param_default():
    ord_string = "type Alias[T: int = bool] = list[T]"
    compare_asts(ord_string)

def test_type_alias_typevartuple_default():
    ord_string = "type TupleAlias[*Ts = tuple[int, ...]] = tuple[*Ts]"
    compare_asts(ord_string)

def test_type_alias_typevartuple_starred_default():
    ord_string = "type TupleAlias[*Ts = *default] = tuple[*Ts]"
    compare_asts(ord_string)

def test_type_alias_paramspec_default():
    ord_string = "type CallableAlias[**P = [int, str]] = Callable[P, int]"
    compare_asts(ord_string)

def test_funcdef_typevartuple_annotation():
    ord_string = "def f[*Ts](*args: *Ts):\n    pass"
    compare_asts(ord_string)

def test_parenthesized_with_bare_items():
    ord_string = "with (a, b):\n    pass"
    compare_asts(ord_string)

def test_parenthesized_with_mixed_items():
    ord_string = "with (a, b as y):\n    pass"
    compare_asts(ord_string)

def test_parenthesized_with_single_as_target():
    ord_string = "with (a) as t:\n    pass"
    compare_asts(ord_string)

def test_parenthesized_tuple_with_as_target():
    ord_string = "with (a, b) as t:\n    pass"
    compare_asts(ord_string)

def test_parenthesized_with_trailing_comma():
    ord_string = "with (a,):\n    pass"
    compare_asts(ord_string)

def test_parenthesized_with_as_trailing_comma():
    ord_string = "with (a as x,):\n    pass"
    compare_asts(ord_string)

def test_invalid_parenthesized_with_item_and_outer_as():
    ord_string = "with (a as x, b) as t:\n    pass"
    compare_syntax_errors(ord_string)

def test_invalid_walrus_assignment_rhs():
    ord_string = "a = x := 1"
    compare_syntax_errors(ord_string)

def test_invalid_walrus_return_value():
    ord_string = "def f():\n    return x := 1"
    compare_syntax_errors(ord_string)

def test_invalid_walrus_lambda_body():
    ord_string = "lambda: x := 1"
    compare_syntax_errors(ord_string)

def test_invalid_walrus_keyword_argument():
    ord_string = "func(a=x := 1)"
    compare_syntax_errors(ord_string)

def test_match_complex_literal_pattern():
    ord_string = "match x:\n    case 1+2j:\n        pass"
    compare_asts(ord_string)

def test_match_negative_complex_literal_pattern():
    ord_string = "match x:\n    case -1-2j:\n        pass"
    compare_asts(ord_string)

def test_invalid_keyword_as_name():
    ord_string = "and = 1"
    compare_syntax_errors(ord_string)

def test_invalid_keyword_in_call_argument_name():
    ord_string = "func(if=1)"
    compare_syntax_errors(ord_string)

def test_invalid_keyword_as_parameter_name():
    ord_string = "def f(if):\n    pass"
    compare_syntax_errors(ord_string)

def test_funcdef_stararg_trailing_comma():
    ord_string = "def f(*args,):\n    pass"
    compare_asts(ord_string)

def test_funcdef_kwonly_trailing_comma():
    ord_string = "def f(*, a,):\n    pass"
    compare_asts(ord_string)

def test_funcdef_kwonly_after_arg_trailing_comma():
    ord_string = "def f(a, *, b,):\n    pass"
    compare_asts(ord_string)

def test_funcdef_kwargs_trailing_comma():
    ord_string = "def f(**kw,):\n    pass"
    compare_asts(ord_string)

def test_funcdef_stararg_kwargs_trailing_comma():
    ord_string = "def f(*args, **kw,):\n    pass"
    compare_asts(ord_string)

def test_invalid_funcdef_bare_star():
    ord_string = "def f(*):\n    pass"
    compare_syntax_errors(ord_string)

def test_invalid_funcdef_kwargs_double_trailing_comma():
    ord_string = "def f(*args, **kw,,):\n    pass"
    compare_syntax_errors(ord_string)

def test_invalid_lambda_bare_star():
    ord_string = "lambda *: 1"
    compare_syntax_errors(ord_string)

def test_invalid_lambda_bare_star_trailing_comma():
    ord_string = "lambda *,: 1"
    compare_syntax_errors(ord_string)

def test_invalid_call_positional_after_keyword():
    ord_string = "func(a=1, 2)"
    compare_syntax_errors(ord_string)

def test_invalid_call_positional_after_kwargs():
    ord_string = "func(**kw, 1)"
    compare_syntax_errors(ord_string)

def test_invalid_call_stararg_after_kwargs():
    ord_string = "func(**kw, *args)"
    compare_syntax_errors(ord_string)

def test_invalid_class_positional_after_keyword():
    ord_string = "class A(metaclass=Meta, B):\n    pass"
    compare_syntax_errors(ord_string)

def test_invalid_class_stararg_after_kwargs():
    ord_string = "class A(**kw, *bases):\n    pass"
    compare_syntax_errors(ord_string)

def test_invalid_walrus_function_default():
    ord_string = "def f(a=x:=1):\n    pass"
    compare_syntax_errors(ord_string)

def test_invalid_walrus_augassign_value():
    ord_string = "a += x := 1"
    compare_syntax_errors(ord_string)

def test_invalid_walrus_annassign_value():
    ord_string = "x: int = y := 1"
    compare_syntax_errors(ord_string)

def test_invalid_walrus_raise_cause():
    ord_string = "raise err from x := cause"
    compare_syntax_errors(ord_string)

def test_invalid_walrus_with_item():
    ord_string = "with x := cm():\n    pass"
    compare_syntax_errors(ord_string)

def test_invalid_walrus_for_iter():
    ord_string = "for x in y := z:\n    pass"
    compare_syntax_errors(ord_string)

def test_invalid_walrus_tuple_assignment_value():
    ord_string = "a = b, c := 1"
    compare_syntax_errors(ord_string)

def test_walrus_list_expression_statement():
    ord_string = "[x := 1]"
    compare_asts(ord_string)

def test_walrus_comprehension_expression_statement():
    ord_string = "[y := x for x in xs]"
    compare_asts(ord_string)

def test_walrus_assignment_nested_container():
    ord_string = "a = [x := 1]"
    compare_asts(ord_string)

def test_walrus_assignment_parenthesized_tuple():
    ord_string = "a = (b, c := 1)"
    compare_asts(ord_string)

def test_walrus_call_positional_argument():
    ord_string = "func(x := 1)"
    compare_asts(ord_string)

def test_walrus_keyword_nested_container():
    ord_string = "func(a=[x := 1])"
    compare_asts(ord_string)

def test_walrus_return_nested_container():
    ord_string = "def f():\n    return [x := 1]"
    compare_asts(ord_string)

def test_walrus_class_base():
    ord_string = "class C(x := Base):\n    pass"
    compare_asts(ord_string)

def test_f_string_empty_format_spec():
    ord_string = "f'{x:}'"
    compare_asts(ord_string)

def test_f_string_conversion_empty_format_spec():
    ord_string = "f'{x!r:}'"
    compare_asts(ord_string)

def test_f_string_nested_format_spec_trailing_empty():
    ord_string = "f'{x:{width}}'"
    compare_asts(ord_string)

def test_f_string_nested_format_spec_conversion():
    ord_string = "f'{x:{width!r}}'"
    compare_asts(ord_string)

def test_f_string_nested_format_spec_nested_spec():
    ord_string = "f'{x:{width:{precision}}}'"
    compare_asts(ord_string)

def test_invalid_f_string_single_close_brace():
    ord_string = "f'}'"
    compare_syntax_errors(ord_string)

def test_invalid_match_class_positional_after_keyword():
    ord_string = "match x:\n    case Point(x=1, y):\n        pass"
    compare_syntax_errors(ord_string)

def test_invalid_match_as_wildcard_target():
    ord_string = "match x:\n    case y as _:\n        pass"
    compare_syntax_errors(ord_string)

def test_name_type_assignment():
    ord_string = "type = None"
    compare_asts(ord_string)

def test_name_path_assignment():
    ord_string = "path = 1"
    compare_asts(ord_string)

def test_name_cell_assignment():
    ord_string = "cell = 1"
    compare_asts(ord_string)

def test_name_net_assignment():
    ord_string = "net = 1"
    compare_asts(ord_string)

def test_name_viewgen_assignment():
    ord_string = "viewgen = 1"
    compare_asts(ord_string)

def test_name_type_aug_assignment():
    ord_string = "type += 1"
    compare_asts(ord_string)

def test_name_path_annotation():
    ord_string = "path: int = 1"
    compare_asts(ord_string)

def test_name_type_loop_target():
    ord_string = "for i, type in x: pass"
    compare_asts(ord_string)

def test_name_type_call_statement():
    ord_string = "type(x).y()"
    compare_asts(ord_string)

def test_fstring_tuple_field():
    ord_string = 's = f"{x,}"'
    compare_asts(ord_string)

def test_with_call_as_name_multi_stmt():
    ord_string = "with f() as b:\n    x\n    y"
    compare_asts(ord_string)

def test_with_parenthesized_call_as():
    ord_string = "with (f()) as b:\n    x\n    y"
    compare_asts(ord_string)

def test_with_multiple_call_as_items():
    ord_string = "with f() as b, g() as c:\n    x\n    y"
    compare_asts(ord_string)

def test_funcdef_kwargs_trailing_comma_after_param():
    ord_string = "def f(a, **kw,): pass"
    compare_asts(ord_string)

def test_funcdef_annotated_kwargs_trailing_comma():
    ord_string = "def f(a, **kw: int,): pass"
    compare_asts(ord_string)

@pytest.mark.filterwarnings("ignore:invalid escape sequence.*:SyntaxWarning")
def test_fstring_backslash_before_field():
    ord_string = 's = f"a\\{b}"'
    compare_asts(ord_string)

def test_raw_fstring_backslash_before_field():
    ord_string = 's = rf"\\{b}"'
    compare_asts(ord_string)

@pytest.mark.filterwarnings("ignore:invalid escape sequence.*:SyntaxWarning")
def test_fstring_backslash_before_field_single_quote():
    ord_string = "s = f'a\\{b}'"
    compare_asts(ord_string)

@pytest.mark.filterwarnings("ignore:invalid escape sequence.*:SyntaxWarning")
def test_fstring_backslash_before_field_multiple():
    ord_string = 's = f"\\{b}\\{c}"'
    compare_asts(ord_string)

def test_fstring_named_unicode_escape():
    ord_string = 's = f"\\N{BULLET}"'
    compare_asts(ord_string)

def test_fstring_named_unicode_escape_then_field():
    ord_string = 's = f"\\N{BULLET}{x}"'
    compare_asts(ord_string)

def test_fstring_valid_escape_before_field():
    ord_string = 's = f"\\n{b}"'
    compare_asts(ord_string)

def test_fstring_escaped_backslash_before_field():
    ord_string = 's = f"\\\\{b}"'
    compare_asts(ord_string)

def test_raw_fstring_named_escape_is_field():
    ord_string = 's = rf"\\N{x}"'
    compare_asts(ord_string)

def test_match_tuple_subject_trailing_comma():
    ord_string = "match x,:\n    case y:\n        z = 0"
    compare_asts(ord_string)

def test_match_soft_keyword_as_identifier():
    ord_string = "match.foo()"
    compare_asts(ord_string)

def test_for_target_single_elem_tuple():
    ord_string = "for x, in y:\n    pass"
    compare_asts(ord_string)

def test_fstring_format_spec_starting_eq():
    ord_string = "s = f'{x:=10}'"
    compare_asts(ord_string)

def test_string_backslash_newline_continuation():
    ord_string = "x = 'a\\\nb'"
    compare_asts(ord_string)

def test_return_starred_unparenthesized_tuple():
    ord_string = "def f():\n    return *a, b"
    compare_asts(ord_string)

def test_return_starred_trailing_comma():
    ord_string = "def f():\n    return *a,"
    compare_asts(ord_string)

def test_yield_starred_unparenthesized_tuple():
    ord_string = "def g():\n    yield *a, b"
    compare_asts(ord_string)

def test_return_starred_parenthesized_tuple():
    ord_string = "def f():\n    return (*a, b)"
    compare_asts(ord_string)

def test_assign_starred_unparenthesized_tuple():
    ord_string = "x = *a, b"
    compare_asts(ord_string)

def test_match_prefixed_identifier_annotation():
    ord_string = "match_tests: int"
    compare_asts(ord_string)

def test_match_prefixed_identifier_assignment_guard():
    ord_string = "match_x = 1"
    compare_asts(ord_string)

def test_anonymous_keyword_as_call():
    ord_string = "anonymous()"
    compare_asts(ord_string)

def test_path_keyword_as_call_guard():
    ord_string = "path()"
    compare_asts(ord_string)

def test_case_class_pattern_trailing_comma():
    ord_string = "match p:\n    case Foo(a,):\n        pass"
    compare_asts(ord_string)

def test_fstring_named_escape_after_text():
    ord_string = "s = f'2\\N{GREEK CAPITAL LETTER DELTA}'"
    compare_asts(ord_string)

def test_for_iter_starred_exprs():
    ord_string = "for x in *a, *b:\n    pass"
    compare_asts(ord_string)

def test_with_as_call_subscript_target():
    ord_string = "with c() as f()[0]:\n    pass"
    compare_asts(ord_string)

def test_fstring_concat_empty_str_empty_fstring():
    ord_string = "x = '' f''"
    compare_asts(ord_string)

def test_fstring_concat_empty_str_then_field():
    ord_string = "x = '' f'{y}'"
    compare_asts(ord_string)

def test_fstring_concat_field_then_empty_str():
    ord_string = "x = f'{y}' ''"
    compare_asts(ord_string)

def test_fstring_concat_empty_fstring_alone_guard():
    ord_string = "x = f''"
    compare_asts(ord_string)

def test_fstring_concat_two_empty_plain_guard():
    ord_string = "x = '' ''"
    compare_asts(ord_string)

def test_fstring_concat_nonempty_str_empty_fstring_guard():
    ord_string = "x = 'a' f''"
    compare_asts(ord_string)

def test_fstring_concat_empty_str_nonempty_fstring_guard():
    ord_string = "x = '' f'b'"
    compare_asts(ord_string)

def test_fstring_concat_two_empty_fstrings_guard():
    ord_string = "x = f'' f''"
    compare_asts(ord_string)

def test_viewgen_docstring():
    # A leading docstring in a viewgen body must become the generated
    # function's docstring, not an inert statement.
    ord_string = (
        "cell Foo:\n"
        "    viewgen drc -> DrcReport:\n"
        '        """Run DRC on the layout."""\n'
        "        . = run_drc(self.layout)\n"
    )
    fn = ord_to_py(ord_string).body[0].body[0]
    assert ast.get_docstring(fn) == "Run DRC on the layout."

def test_viewgen_in_cell_is_method_form():
    # A viewgen that is a direct statement of a cell body compiles to a
    # method: `self` parameter plus the method-form decorator.
    ord_string = (
        "cell Foo:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    fn = ord_to_py(ord_string).body[0].body[0]
    assert isinstance(fn, ast.FunctionDef)
    assert [a.arg for a in fn.args.args] == ["self"]
    assert ast.unparse(fn.decorator_list[-1]) == "__ord_context__.viewgen"

def test_viewgen_toplevel_is_function_form():
    # A viewgen outside of a cell compiles to a no-argument function with
    # the function-form decorator.
    ord_string = (
        "viewgen top -> Report:\n"
        "    .markdown('x')\n"
    )
    fn = ord_to_py(ord_string).body[0]
    assert isinstance(fn, ast.FunctionDef)
    assert fn.args.args == []
    assert ast.unparse(fn.decorator_list[-1]) == "__ord_context__.viewgen_func"

def test_viewgen_nested_in_cell_body_is_method_form():
    # Like a def in a Python class body, a viewgen nested in a compound
    # statement of the cell suite still binds in the cell namespace, so it
    # compiles to method form (conditional method definition).
    ord_string = (
        "cell Foo:\n"
        "    if True:\n"
        "        viewgen symbol -> Symbol:\n"
        "            input a\n"
    )
    fn = ord_to_py(ord_string).body[0].body[0].body[0]
    assert isinstance(fn, ast.FunctionDef)
    assert [a.arg for a in fn.args.args] == ["self"]
    assert ast.unparse(fn.decorator_list[-1]) == "__ord_context__.viewgen"

def test_viewgen_in_def_inside_cell_body_is_function_form():
    # A def inside a cell body is its own binding scope: a viewgen there is
    # a function-form viewgen, as outside of cells.
    ord_string = (
        "cell Foo:\n"
        "    def helper(self):\n"
        "        viewgen inner -> Report:\n"
        "            .markdown('x')\n"
        "        return inner\n"
    )
    fn = ord_to_py(ord_string).body[0].body[0].body[0]
    assert isinstance(fn, ast.FunctionDef)
    assert fn.args.args == []
    assert ast.unparse(fn.decorator_list[-1]) == "__ord_context__.viewgen_func"

def test_viewgen_decorated_keeps_own_decorator():
    # User decorators must be prepended, not replace the viewgen's own
    # decorator.
    ord_string = (
        "cell Foo:\n"
        "    @mydec\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    fn = ord_to_py(ord_string).body[0].body[0]
    assert ast.unparse(fn.decorator_list[0]) == "mydec"
    assert ast.unparse(fn.decorator_list[-1]) == "__ord_context__.viewgen"
