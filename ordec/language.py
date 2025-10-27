# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0


# standard imports
import re
import ast

# ordec imports
from .ord1.parser import ord1_to_py
from .ord2.parser import ord2_to_py

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
        module = ord1_to_py(source_data)
    return module
