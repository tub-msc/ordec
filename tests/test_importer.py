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

def test_init_ord_package(tmp_path, monkeypatch):
    """A directory with __init__.ord is a regular package."""
    pkg = tmp_path / "ord_pkg_demo"
    pkg.mkdir()
    (pkg / "__init__.ord").write_text("")
    (pkg / "sub.ord").write_text('MARKER = "sub"\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    assert import_fresh("ord_pkg_demo.sub").MARKER == "sub"
