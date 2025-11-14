# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports
from lark import Lark
import ast

from pathlib import Path

#ordec imports
from ..ord1.ast_transformer import SchematicModifier
from ..ord1.lark_transformer import OrdecTransformer, TreeIndenter

def load_ord_from_string(ord_string):
    """
    Function which parses an ORD string and returns the parsed result.

    :param ord_string: string containing ORD code
    :return: ast of the parsed string
    """
    # Load the grammar file
    parser = Lark.open_from_package(__name__, "ord_grammar.lark", parser="lalr", lexer="basic", postlex=TreeIndenter())
    
    # Parse the string directly
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

# TODO: Make ord1 encapsulation consistent. ordec/importer.py and
# ordec/ws_server.py use ord2py() for now.
def ord1_to_py(source_data: str) -> ast.Module:
    """
    Compile ORD to Python

    :param source_data: ORD source code
    """
    module = ast.parse(
        "from ordec.core import *\n" +
        "from ordec.sim.sim_hierarchy import HighlevelSim\n"+
        "from ordec.ord1.implicit_processing import symbol_process, preprocess, PostProcess, postprocess\n" +
        "from ordec.ord1.prelim_schem_instance import PrelimSchemInstance\n")
    x = load_ord_from_string(source_data)
    x = ast.fix_missing_locations(x)
    module.body += x.body
    return module
