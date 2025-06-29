# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports
from lark import Lark
import ast

from pathlib import Path
import sys
import astor
try:
    import black
except ImportError:
    black = None

#ordec imports
from ..parser.ast_transformer import SchematicModifier
from ..parser.lark_transformer import OrdecTransformer, TreeIndenter

def save_ast_to_file(ast_node, filename):
    """
    Function which saves the ast to a file

    :param ast_node: root node of the ast
    :param filename: name of the saved file
    :return: None
    """
    source_code = astor.to_source(ast_node)
    with open(filename, 'w') as f:
        f.write(source_code)


def main():
    lark_fn = Path(__file__).parent / "ord_grammar.lark"
    parser = Lark.open(lark_fn, parser="lalr", lexer="basic", postlex=TreeIndenter())
    with open(sys.argv[1]) as f:
        inp = f.read()

    if len(inp) == 0:
        parsed = ast.Module([], [])
    else:
        parsed = parser.parse(inp + "\n")
    # print the parsed tree
    ordec_transformer = OrdecTransformer()
    transformed = ordec_transformer.transform(parsed)
    # Pass outline information and the called instances
    modifier = SchematicModifier(ordec_transformer.port_positions)
    modified_transformed = modifier.visit(transformed)
    # Add line number and other meta information to the ast
    ast.fix_missing_locations(modified_transformed)
    # Print ast
    # print(ast.dump(modified_transformed, indent=4))

    # Print the unparsed result
    code_str = ast.unparse(modified_transformed)
    print(code_str)

    # Save the ast to file
    # save_ast_to_file(modified_transformed, 'inv_class.py')

def load_ord_from_string(ord_string):
    """
    Function which parses an ORD string and returns the parsed result.

    :param ord_string: string containing ORD code
    :return: ast of the parsed string
    """
    # Load the grammar file
    lark_fn = Path(__file__).parent / "ord_grammar.lark"
    parser = Lark.open(lark_fn, parser="lalr", lexer="basic", postlex=TreeIndenter())
    
    # Parse the string directly
    if len(ord_string) == 0:
        parsed = ast.Module([], [])
    else:
        parsed = parser.parse(ord_string + "\n")
    
    # Transform using OrdecTransformer
    ordec_transformer = OrdecTransformer()
    transformed = ordec_transformer.transform(parsed)

    # Modify with SchematicModifier
    modifier = SchematicModifier(ordec_transformer.port_positions)
    modified_transformed = modifier.visit(transformed)
    
    # Fix AST locations and return
    ast.fix_missing_locations(modified_transformed)
    return modified_transformed

def execute_in_environment(cell_code, environment, update_environment=True):
    """
    Execute the code in the environment with optional environment update

    :param: cell_code
    :param: environment
    :param: update_environment
    """
    before_keys = set(environment.keys())
    exec(cell_code, environment)
    # Find new entries
    after_keys = set(environment.keys())
    new_keys = after_keys - before_keys
    if update_environment:
        for key in new_keys:
            new_cell = str(key)
            environment['ext'][new_cell] = environment[new_cell]

def print_compiled_ord(cell_code):
    """
    Print function for compiled ord code

    :param: cell code
    """
    if black:
        formatted = black.format_str(cell_code, mode=black.Mode())
        print(formatted)
    else:
        print(cell_code)
    
def load_ord(file_path):
    """
    Function which loads an ord file and returns the parsed result

    :param file_path: path of the .ord file
    :return: ast of the parsed file
    """
    with open(file_path, 'r') as f:
        inp = f.read()
    return ast.unparse(load_ord_from_string(inp))


# TODO: Make parser encapsulation consistent. ordec/importer.py and 
# ordec/ws_server.py use ord2py() for now.
def ord2py(source_data: str) -> ast.Module:
    module = ast.parse(
        "from ordec.base import *\n" +
        "from ordec.sim2.sim_hierarchy import HighlevelSim\n"+
        "from ordec.lib import Inv, Res, Gnd, Vdc, Idc, Nmos, Pmos, NoConn\n"+
        "from ordec.parser.implicit_processing import symbol_process, preprocess, PostProcess, postprocess\n" +
        "from ordec.parser.prelim_schem_instance import PrelimSchemInstance\n"+
        "ext = globals()\n" # <-- TODO: bad hack, this is not how it is intended...
        )
    x = load_ord_from_string(source_data)
    x = ast.fix_missing_locations(x)
    module.body += x.body

    #print(ast.dump(module, indent=4, include_attributes=False))
    return module

if __name__ == '__main__':
    main()
