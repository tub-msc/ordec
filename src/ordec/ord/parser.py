# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from lark import Lark, UnexpectedToken, UnexpectedCharacters, UnexpectedInput, Token
from lark.exceptions import VisitError
from pathlib import Path
import argparse
from lark.indenter import PythonIndenter
from .ord_transformer import OrdTransformer
import ast


class PythonTokenAwareIndenter(PythonIndenter):
    """
    PythonIndenter with accounting for grammar-specific Python tokens.

    The stock Lark indenter only balances the standard close-token names. This
    grammar has extra hidden close tokens for f-strings and with-as lookahead,
    so newline suppression must account for them explicitly.
    """

    CLOSE_PAREN_types = PythonIndenter.CLOSE_PAREN_types + ["_RPAREN_AS"]
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
            # Gutter must be as wide as the "> NNNN " prefix above so the
            # pipes line up and the caret points at the right column.
            error.append(f"{'':6} | {'':{column-1}}^")
    return "\n".join(error)


def syntax_error(msg, code, line, column, end_column=None):
    """
    Builds a SyntaxError carrying a structured error position. The filename
    is left as None and filled in by the caller of the ORD compiler (see
    ordec.language.ord_to_code). Python's standard traceback rendering then
    produces the usual "File ..., line N" display with a correctly aligned
    caret, and the web UI can point the editor at the error position.

    Args:
        msg (str): Error message (without position information)
        code (str): String containing ORD code
        line (int): Error line number (1-based)
        column (int): Error column (1-based)
        end_column (int): Exclusive end column of the offending range
    Returns:
        SyntaxError to be raised by the caller
    """
    lines = code.splitlines()
    if line > len(lines) and lines:
        # Error on the virtual newline/EOF appended by parse_with_errors:
        # point at the end of the last real line instead.
        line = len(lines)
        column = len(lines[line - 1]) + 1
        end_column = None
    text = lines[line - 1] if 0 < line <= len(lines) else None
    return SyntaxError(msg, (None, line, column, text, line, end_column))


def expected_summary(parser, expected, limit=12):
    """
    Human-readable display of a lark expected-terminals set: literal
    terminals (keywords, punctuation) show their text, a few common
    terminals get friendly names, anonymous/internal ones are dropped,
    and long lists are capped.

    Returns the summary string, or None if nothing is worth showing.
    """
    # Friendly names for regex/synthetic terminals. All other non-literal
    # terminal names are shown as-is (internal ones are dropped).
    expected_names = {
        "_NEWLINE": "newline",
        "_INDENT": "indented block",
        "_DEDENT": "end of block",
        "$END": "end of input",
        "NAME": "identifier",
    }
    literals = {t.name: t.pattern.value for t in parser.terminals
        if t.pattern.type == "str"}
    names = set()
    for name in expected:
        if name in literals:
            names.add(repr(literals[name]))
        elif name in expected_names:
            names.add(expected_names[name])
        elif not name.startswith("_"):
            names.add(name)
    # Words (keywords, friendly names) before punctuation: when the list is
    # capped, they are the more helpful suggestions.
    names = sorted(names,
        key=lambda n: (not n.lstrip("'")[:1].isalpha(), n))
    if not names:
        return None
    shown = ", ".join(names[:limit])
    if len(names) > limit:
        shown += f", … ({len(names) - limit} more)"
    return shown


def parse_with_errors(parser, code):
    """
    Function which parses an ORD string, converting lark parse errors into
    SyntaxErrors that carry a structured error position (see syntax_error).

    Args:
        parser: ORD Lark parser
        code (str): String containing ORD code
    Returns:
        AST of the parsed string
    """
    try:
        return parser.parse(code + "\n")
    except UnexpectedToken as e:
        if e.token.type == "$END":
            msg = "unexpected end of input"
        else:
            # Lexemes can be long or multi-line; keep the message one line.
            tok = str(e.token).split("\n")[0]
            if len(tok) > 20:
                tok = tok[:20] + "…"
            msg = f"unexpected token {tok!r}" if tok else "unexpected token"
        expected = expected_summary(parser, e.expected)
        if expected:
            msg += f" (expected: {expected})"
        # Underline the offending token, but only if it ends on its line.
        end_column = None
        if (getattr(e.token, "end_line", None) == e.line
                and e.token.end_column > e.column):
            end_column = e.token.end_column
        raise syntax_error(msg, code, e.line, e.column,
            end_column=end_column) from None

    except UnexpectedCharacters as e:
        raise syntax_error(f"unexpected character {e.char!r}", code,
            e.line, e.column, end_column=e.column + 1) from None

    # fallback
    except UnexpectedInput as e:
        raise syntax_error("invalid syntax", code, e.line, e.column) from None


parser = Lark.open_from_package(
    __package__,
    "ord.lark",
    parser="lalr",
    postlex=PythonTokenAwareIndenter(),
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
    try:
        transformed_ast = ord_transformer.transform(parsed_result)
    except VisitError as e:
        # Surface SyntaxErrors raised by transformer callbacks (e.g. an
        # invalid assignment target) directly, like parse errors.
        if isinstance(e.orig_exc, SyntaxError):
            raise e.orig_exc from None
        raise
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
