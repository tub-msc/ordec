# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from lark import Lark, UnexpectedToken, UnexpectedCharacters, UnexpectedInput
from pathlib import Path
import argparse
from lark.indenter import PythonIndenter
from .ord2_transformer import Ord2Transformer
import ast


def format_error(code, line, column, window=2):
    """
    Function which formats the error message with correct
    position and window size

    Args:
        code (str): String containing ORD code
        line (int): Error line number
        column (int): Error line column
        window (int): Window size of the occurred error
    Returns:
        Error message
    """
    lines = code.splitlines()
    error_line = line - 1
    start = error_line - window
    if start < 0:
        start = 0
    end = line + window
    if end > len(lines):
        end = len(lines)

    error = []
    for i in range(start, end):
        prefix = ">" if i == error_line else " "
        error.append(f"{prefix} {i+1:4} | {lines[i]}")
        if i == error_line:
            error.append(f"     | {'':{column-1}}^")
    return "\n".join(error)


def parse_with_errors(parser, code):
    """
    Function which parses an ORD string with improved
    error messages

    Args:
        parser: ORD Lark parser
        code (str): String containing ORD code
    Returns:
        AST of the parsed string
    """
    try:
        return parser.parse(code + "\n")
    except UnexpectedToken as e:
        expected = ", ".join(e.expected)
        error = format_error(code, e.line, e.column)
        error_message = (
            f"Syntax Error: Unexpected token `{e.token}`\n\n"
            f"Expected one of: {expected}\n"
            f"At line {e.line}, column {e.column}:\n\n"
            f"{error}"
        )
        raise SyntaxError(error_message) from None

    except UnexpectedCharacters as e:
        error = format_error(code, e.line, e.column)
        error_message = (
            f"Syntax Error: Unexpected character `{e.char}`\n\n"
            f"At line {e.line}, column {e.column}:\n\n"
            f"{error}"
        )
        raise SyntaxError(error_message) from None

    # fallback
    except UnexpectedInput as e:
        error = format_error(code, e.line, e.column)
        error_message = (
            "Syntax Error\n\n"
            f"At line {e.line}, column {e.column}:\n\n"
            f"{error}"
        )
        raise SyntaxError(error_message) from None


lark_fn = Path(__file__).parent / "ord2.lark"
parser = Lark.open(
    lark_fn,
    parser="lalr",
    postlex=PythonIndenter(),
    start="file_input",
    maybe_placeholders=False
)

def ord2_to_py(ord_string: str) -> ast.Module:
    """
    Function which parses an ORD string and returns the transformed result.

    Args:
        ord_string (str): String containing ORD code
    Returns:
        AST of the parsed and transformed string
    """
    # Parse the string directly
    parsed_result = parse_with_errors(parser, ord_string)
    ord2_transformer = Ord2Transformer()
    transformed_ast = ord2_transformer.transform(parsed_result)
    ast.fix_missing_locations(transformed_ast)
    return transformed_ast

if __name__ == "__main__":
    #Function which parses an ORD string and executes the transformed Python result.

    # Parse the string directly
    arg_parser = argparse.ArgumentParser(description="Parse Python code from file or string")
    group = arg_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--p", type=str, help="Path to the file to parse")
    group.add_argument("--s", type=str, help="String to parse directly")
    args = arg_parser.parse_args()

    # Determine input
    if args.p:
        file_path = Path(args.p)
        if not file_path.is_file():
            print(f"Error: file {file_path} does not exist")
            exit(1)
        code = file_path.read_text()
    else:
        code = args.s

    parsed = parse_with_errors(parser, code)
    print(parsed)

    ordec_transformer = Ord2Transformer()
    transformed = ordec_transformer.transform(parsed)
    transformed = ast.fix_missing_locations(transformed)
    print(ast.dump(transformed, indent=4))

    code_obj = compile(transformed, "<ast>", "exec")
    print(ast.unparse(transformed))
    exec(code_obj, globals(), locals())


