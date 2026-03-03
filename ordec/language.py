# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0


# standard imports
import re
import ast
import importlib

# ordec imports
from .ord1.parser import ord1_to_py
from .ord2.parser import ord2_to_py


def prepare_ord_globals(g: dict):
    """Populate g with the implicit globals that ORD2-generated code expects."""
    g.setdefault("__ordec_core__", importlib.import_module("ordec.core"))
    g.setdefault("__ord_context__", importlib.import_module("ordec.ord2.context"))


def compile_ord(source_data: str, g: dict):
    """Compile ORD source, prepare globals, return compiled code object."""
    prepare_ord_globals(g)
    module = ord_to_py(source_data)
    g["__ord_py_source__"] = ast.unparse(module)
    return compile(module, "<string>", "exec")


def ord_to_py(source_data: str) -> ast.Module:
    """
    Checks for the version string and compiles with the recognized ORD compiler

    Args:
        source_data (str): Loaded ORD string
    Returns:
        code: Compiled ORD code
    """
    split_data = source_data.splitlines()
    first_line = split_data[0] if len(split_data) > 0 else ""
    match = re.search(r'#.*version\s*[:=]\s*([A-Za-z0-9_.\-]+)', first_line, re.IGNORECASE)
    ord_version = match.group(1).lower() if match else None
    if ord_version == "ord2":
        module = ord2_to_py(source_data)
    elif ord_version == "ord1":
        module = ord1_to_py(source_data)
    else:
        module = ord2_to_py(source_data)
    return module
