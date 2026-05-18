# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from lark import Lark, UnexpectedToken, UnexpectedCharacters, UnexpectedInput, Token
from pathlib import Path
import argparse
from lark.indenter import PythonIndenter
from .ord_transformer import OrdTransformer
import ast


class FStringAwarePythonIndenter(PythonIndenter):
    """
    PythonIndenter with f-string brace accounting.

    The stock Lark indenter only balances the standard RBRACE token. This
    grammar uses _FSTRING_EXPR_END for both f-string expression closes and
    escaped literal close braces, so newline suppression must distinguish those
    two cases.
    """

    FSTRING_START_types = {"FSTRING_DOUBLE_START", "FSTRING_SINGLE_START"}
    FSTRING_END_types = {"FSTRING_DOUBLE_END", "FSTRING_SINGLE_END"}
    FSTRING_EXPR_END_type = "_FSTRING_EXPR_END"

    def _process(self, stream):
        token = None
        paren_stack = []
        fstring_brace_levels = []

        for token in stream:
            if token.type == self.NL_type:
                yield from self.handle_NL(token)
            else:
                yield token

            token_type = token.type
            if token_type in self.FSTRING_START_types:
                fstring_brace_levels.append(0)
                continue
            if token_type in self.FSTRING_END_types:
                if fstring_brace_levels and fstring_brace_levels[-1] == 0:
                    fstring_brace_levels.pop()
                continue

            if token_type in self.OPEN_PAREN_types:
                paren_stack.append(token_type)
                self.paren_level = len(paren_stack)
                if fstring_brace_levels and token_type == "LBRACE":
                    fstring_brace_levels[-1] += 1
                continue

            if token_type in self.CLOSE_PAREN_types:
                paren_stack.pop()
                self.paren_level = len(paren_stack)
                continue

            if token_type == self.FSTRING_EXPR_END_type:
                if fstring_brace_levels:
                    if fstring_brace_levels[-1] > 0:
                        paren_stack.pop()
                        self.paren_level = len(paren_stack)
                        fstring_brace_levels[-1] -= 1
                    continue
                if paren_stack and paren_stack[-1] == "LBRACE":
                    paren_stack.pop()
                    self.paren_level = len(paren_stack)

        while len(self.indent_level) > 1:
            self.indent_level.pop()
            if token:
                yield Token.new_borrow_pos(self.DEDENT_type, '', token)
            else:
                yield Token(self.DEDENT_type, '', 0, 0, 0, 0, 0, 0)

        assert self.indent_level == [0], self.indent_level


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


parser = Lark.open_from_package(
    __package__,
    "ord.lark",
    parser="lalr",
    postlex=FStringAwarePythonIndenter(),
    start="file_input",
    maybe_placeholders=False,
    propagate_positions=True
)

def ord_to_py(ord_string: str) -> ast.Module:
    """
    Function which parses an ORD string and returns the transformed result.

    Args:
        ord_string (str): String containing ORD code
    Returns:
        AST of the parsed and transformed string
    """
    # Parse the string directly
    parsed_result = parse_with_errors(parser, ord_string)
    ord_transformer = OrdTransformer(source_text=ord_string + "\n")
    transformed_ast = ord_transformer.transform(parsed_result)
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

    ordec_transformer = OrdTransformer()
    transformed = ordec_transformer.transform(parsed)
    transformed = ast.fix_missing_locations(transformed)
    print(ast.dump(transformed, indent=4))

    code_obj = compile(transformed, "<ast>", "exec")
    print(ast.unparse(transformed))
    exec(code_obj, globals(), locals())
