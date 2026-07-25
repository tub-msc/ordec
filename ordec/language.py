# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0


# standard imports
import ast
import importlib

# ordec imports
from .ord import ord_to_py


def prepare_ord_globals(g: dict):
    """Populate g with the implicit globals that ORD-generated code expects."""
    g.setdefault("__ordec_core__", importlib.import_module("ordec.core"))
    g.setdefault("__ord_context__", importlib.import_module("ordec.ord.context"))


def ord_to_code(source_data: str, filename: str = "<string>"):
    """
    Transpile and compile ORD source, returning (code object, unparsed
    Python source). Pure function of its arguments, which makes the result
    cacheable (see ordec.importer).
    """
    try:
        module = ord_to_py(source_data)
    except SyntaxError as e:
        if e.filename is None:
            e.msg = f"In {filename}:\n{e.msg}"
        raise
    return compile(module, filename, "exec"), ast.unparse(module)


def compile_ord(source_data: str, g: dict, filename: str = "<string>"):
    """Compile ORD source, prepare globals, return compiled code object."""
    prepare_ord_globals(g)
    code, py_source = ord_to_code(source_data, filename)
    g["__ord_py_source__"] = py_source
    return code
