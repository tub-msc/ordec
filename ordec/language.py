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
    from .ord import context
    g.setdefault("constrain", context.constrain)


def compile_ord(source_data: str, g: dict, filename: str = "<string>"):
    """Compile ORD source, prepare globals, return compiled code object."""
    prepare_ord_globals(g)
    try:
        module = ord_to_py(source_data)
    except SyntaxError as e:
        if e.filename is None:
            e.msg = f"In {filename}:\n{e.msg}"
        raise
    g["__ord_py_source__"] = ast.unparse(module)
    return compile(module, filename, "exec")
