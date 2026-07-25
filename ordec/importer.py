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

Compiled modules are cached under __pycache__ (e.g. demo.cpython-313
.opt-ord.pyc; the fixed "ord" tag keeps the file distinct from the cache of
a shadowing demo.py). The PEP-552-inspired header encodes everything cache
validity depends on: interpreter (magic number), source content (hash, as
in hash-based pycs), transpiler state (newest mtime of the ordec.ord
sources, catching transpiler edits in development installs) and the ordec
version (kept explicit because reproducible-build installers normalize
mtimes). Any mismatch re-transpiles and overwrites the file in place, so
upgrades do not leave stale cache files behind. The payload carries
(code, __ord_py_source__) so cache hits restore the generated-Python view
without re-transpiling.
"""

import sys
import os
import struct
import marshal
from importlib import metadata
from importlib.abc import FileLoader
from importlib.machinery import (
    FileFinder, ExtensionFileLoader, SourceFileLoader, SourcelessFileLoader,
    EXTENSION_SUFFIXES, SOURCE_SUFFIXES, BYTECODE_SUFFIXES,
)
from importlib.util import cache_from_source, source_hash, MAGIC_NUMBER
from .language import ord_to_code, prepare_ord_globals
from . import ord as _ord_pkg

# Newest mtime of the ORD transpiler sources (grammar included). In release
# installs these are stable, so the check always passes there.
_transpiler_mtime_ns = max(e.stat().st_mtime_ns
    for e in os.scandir(os.path.dirname(_ord_pkg.__file__)) if e.is_file())

try:
    _version = metadata.version('ordec')
except metadata.PackageNotFoundError:
    _version = 'dev'
# Length-delimited: the header is compared with startswith(), so "0.4" must
# not prefix-match a file written by "0.4.1".
_version_bytes = _version.encode()
_version_header = struct.pack('<H', len(_version_bytes)) + _version_bytes

class OrdFileLoader(FileLoader):
    def get_source(self, fullname):
        return self.get_data(self.path).decode('utf-8')

    def _cached_code(self, fullname):
        """Return (code, py_source), served from __pycache__ when valid."""
        source = self.get_data(self.path)
        header = (MAGIC_NUMBER + source_hash(source)
            + struct.pack('<Q', _transpiler_mtime_ns) + _version_header)
        cache_path = cache_from_source(self.path, optimization='ord')
        try:
            with open(cache_path, 'rb') as f:
                data = f.read()
            if data.startswith(header):
                code, py_source = marshal.loads(data[len(header):])
                return code, py_source
        except (OSError, ValueError, EOFError, TypeError):
            pass  # missing or corrupt cache file
        code, py_source = ord_to_code(source.decode('utf-8'), self.path)
        if not sys.dont_write_bytecode:
            try:
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                tmp_path = f'{cache_path}.{os.getpid()}'
                with open(tmp_path, 'wb') as f:
                    f.write(header)
                    f.write(marshal.dumps((code, py_source)))
                os.replace(tmp_path, cache_path)
            except OSError:
                pass  # caching is best-effort (e.g. read-only source tree)
        return code, py_source

    def get_code(self, fullname):
        return self._cached_code(fullname)[0]

    def exec_module(self, module):
        code, py_source = self._cached_code(module.__name__)
        prepare_ord_globals(module.__dict__)
        module.__dict__['__ord_py_source__'] = py_source
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
