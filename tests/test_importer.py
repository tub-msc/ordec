# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import sys
import importlib

import ordec.importer

def import_fresh(name):
    sys.modules.pop(name, None)
    return importlib.import_module(name)

def test_import_via_sys_path(tmp_path, monkeypatch):
    """Top-level .ord modules are found via sys.path, not cwd (issue #68)."""
    (tmp_path / "ord_syspath_demo.ord").write_text('MARKER = "ord"\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    mod = import_fresh("ord_syspath_demo")
    assert mod.MARKER == "ord"
    assert mod.__file__ == str(tmp_path / "ord_syspath_demo.ord")

def test_pycache_roundtrip(tmp_path, monkeypatch):
    """Re-import is served from __pycache__; a source edit invalidates it."""
    src = tmp_path / "ord_cache_demo.ord"
    src.write_text('MARKER = "a"\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    import_fresh("ord_cache_demo")  # cold import populates the cache
    transpiles = []
    real_ord_to_code = ordec.importer.ord_to_code
    monkeypatch.setattr(ordec.importer, "ord_to_code",
        lambda *a: transpiles.append(a) or real_ord_to_code(*a))
    mod = import_fresh("ord_cache_demo")
    assert mod.MARKER == "a" and mod.__ord_py_source__ and not transpiles
    # Same length and typically same mtime: only the content hash catches this.
    src.write_text('MARKER = "b"\n')
    assert import_fresh("ord_cache_demo").MARKER == "b"
    assert len(transpiles) == 1

def test_init_ord_package(tmp_path, monkeypatch):
    """A directory with __init__.ord is a regular package."""
    pkg = tmp_path / "ord_pkg_demo"
    pkg.mkdir()
    (pkg / "__init__.ord").write_text("")
    (pkg / "sub.ord").write_text('MARKER = "sub"\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    assert import_fresh("ord_pkg_demo.sub").MARKER == "sub"
