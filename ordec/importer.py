# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Import hook making .ord files importable with the same semantics as .py files.

Rather than adding a custom MetaPathFinder, ".ord" is registered as an
additional source suffix in the standard FileFinder path-hook machinery.
Python's own PathFinder then discovers .ord modules, so sys.path order,
package __path__ resolution, __init__.ord packages, module specs with a
real origin/__file__, importlib.reload() and importlib.invalidate_caches()
all behave exactly as they do for .py files.

This is analogous to how Hy (https://hylang.org) makes its .hy modules
importable: a FileFinder-hooked loader transforms the source to a Python AST,
compiles and executes it. As in Hy, get_source() returns the untransformed
source (ORD, not the generated Python) so tracebacks and inspect map to .ord
lines; consumers expecting Python source must use __ord_py_source__ instead.
"""

import sys
from importlib.abc import FileLoader
from importlib.machinery import (
    FileFinder, ExtensionFileLoader, SourceFileLoader, SourcelessFileLoader,
    EXTENSION_SUFFIXES, SOURCE_SUFFIXES, BYTECODE_SUFFIXES,
)
from .language import compile_ord

class OrdFileLoader(FileLoader):
    def get_source(self, fullname):
        return self.get_data(self.path).decode('utf-8')

    def exec_module(self, module):
        source = self.get_source(module.__name__)
        code = compile_ord(source, module.__dict__, self.path)
        exec(code, module.__dict__)

# A FileFinder path hook claims every directory it is asked about, so it must
# be first in sys.path_hooks and carry the standard loaders as well. Standard
# loaders come first: foo.py shadows foo.ord within the same directory.
sys.path_hooks.insert(0, FileFinder.path_hook(
    (ExtensionFileLoader, EXTENSION_SUFFIXES),
    (SourceFileLoader, SOURCE_SUFFIXES),
    (SourcelessFileLoader, BYTECODE_SUFFIXES),
    (OrdFileLoader, ['.ord']),
))
# Already-visited directories are cached with the standard hook; rescan them.
sys.path_importer_cache.clear()
