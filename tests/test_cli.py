# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Command line of ``ordec``: FILE / -m MODULE / --view resolution, mirroring
python's conventions (see resolve_local in ordec.server).
"""

import sys
import pytest

from ordec.server import build_argparser, resolve_local

@pytest.fixture
def resolve(tmp_path, monkeypatch):
    """Resolves a command line in tmp_path with a private copy of sys.path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    parser = build_argparser()
    def run(*argv):
        return resolve_local(parser.parse_args(argv), parser)
    return run

def test_file(resolve, tmp_path):
    # Like python FILE: the file's directory comes first on sys.path.
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'design.ord').write_text('')
    assert resolve('sub/design.ord:a', '-e', 'b', '--view', 'c') == ('design', ['a', 'b', 'c'])
    assert sys.path[0] == str((tmp_path / 'sub').resolve())

    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'pkg' / '__init__.py').write_text('')
    assert resolve('pkg/') == ('pkg', [])
    assert sys.path[0] == str(tmp_path.resolve())

def test_module(resolve, tmp_path):
    # Like python -m: the current directory comes first on sys.path.
    assert resolve() is None
    (tmp_path / 'design.py').write_text('')
    assert resolve('-m', 'design:a', '-e', 'b') == ('design', ['a', 'b'])
    assert sys.path[0] == str(tmp_path.resolve())

@pytest.mark.parametrize('argv, code', [
    (['missing.py'], 2),
    (['notes.txt'], 2),
    (['plain'], 1),   # directory without __init__
    (['-m', 'nosuch'], 1),
    (['os.py'], 1),   # would silently import the stdlib module
    (['-e', 'v'], 2), # --view without FILE / -m
])
def test_errors(resolve, tmp_path, argv, code):
    (tmp_path / 'notes.txt').write_text('')
    (tmp_path / 'plain').mkdir()
    (tmp_path / 'os.py').write_text('')
    with pytest.raises(SystemExit) as e:
        resolve(*argv)
    assert e.value.code == code
