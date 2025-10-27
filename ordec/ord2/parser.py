# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from lark import Lark
from pathlib import Path
import argparse
from lark.indenter import PythonIndenter
from ..ord2.transformer import Ord2Transformer
import ast


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
    parsed_result = parser.parse(ord_string + "\n")
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

    parsed = parser.parse(code + "\n")
    print(parsed)

    ordec_transformer = Ord2Transformer()
    transformed = ordec_transformer.transform(parsed)
    transformed = ast.fix_missing_locations(transformed)
    print(ast.dump(transformed, indent=4))

    code_obj = compile(transformed, "<ast>", "exec")
    exec(code_obj, globals(), locals())


