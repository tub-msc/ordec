# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import re

def ord_version_resolver(source_data):
    """
    Checks for the version string and compiles with the recognized ORD compiler

    Args:
        source_data (str): Loaded ORD string
    Returns:
        None
    """
    split_data = source_data.splitlines()
    first_line = split_data[0] if len(split_data) > 0 else ""
    match = re.search(r'#.*version\s*[:=]\s*([A-Za-z0-9_.\-]+)', first_line, re.IGNORECASE)
    ord_version = match.group(1).lower() if match else None
    if ord_version == "ord2":
        from .ord2.parser import ord2py
    elif ord_version == "ord1":
        from .ord1.parser import ord2py
    else:
        from .ord1.parser import ord2py
    code = compile(ord2py(source_data), "<string>", "exec")
    return code