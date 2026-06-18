# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for instance source-location tracking (click-to-source navigation).

Schematic instances defined in ORD code record the (filename, line, column) of
their defining statement in SchemInstance.src_loc (a SourceLocInfo). This is
rendered into the web SVG as data-srcfile/data-srcline/data-srccol so the web UI
can jump the editor to that location.
"""

import re
from pathlib import Path
from importlib import import_module

import ordec.importer
from ordec.core.schema import SchemInstance, SourceLocInfo
from ordec.lib.generic_mos import Inv as PyInv
from ordec.language import compile_ord


def _loc_of(text, needle):
    """Return (line, column), both 1-based, of the statement containing needle.

    The column points at the first non-whitespace character (the statement's
    first token, matching lark's reported start column).
    """
    for i, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return i, len(line) - len(line.lstrip()) + 1
    raise AssertionError(f"{needle!r} not found in source")


def test_srcloc_ord_local_module():
    """Instances of an ORD-defined schematic record their defining statement's
    file, line and column (local mode: the real .ord file path)."""
    mod = import_module('tests.lib.ord.inverter')
    src = Path(mod.__file__).read_text()
    locs = {i.full_path_str(): i.src_loc for i in mod.Inv().schematic.all(SchemInstance)}

    assert locs['pd'] == SourceLocInfo(mod.__file__, *_loc_of(src, 'Nmos pd:'))
    assert locs['pu'] == SourceLocInfo(mod.__file__, *_loc_of(src, 'Pmos pu:'))


def test_srcloc_integrated_mode_filename():
    """In integrated mode the source filename is the virtual '<webeditor>'
    (see server.build_cells); line/column still map to the entered source."""
    src = Path(import_module('tests.lib.ord.inverter').__file__).read_text()
    g = {}
    exec(compile_ord(src, g, filename='<webeditor>'), g, g)
    locs = {i.full_path_str(): i.src_loc for i in g['Inv']().schematic.all(SchemInstance)}

    assert locs['pd'] == SourceLocInfo('<webeditor>', *_loc_of(src, 'Nmos pd:'))
    assert locs['pu'] == SourceLocInfo('<webeditor>', *_loc_of(src, 'Pmos pu:'))


def test_srcloc_in_rendered_svg():
    """The web rendering (include_nids=True) exposes data-srcfile/data-srcline/
    data-srccol on instance groups; the comparison rendering (include_nids=False)
    does not."""
    sch = import_module('tests.lib.ord.inverter').Inv().schematic

    svg = sch.render().svg().decode()
    assert 'data-srcfile=' in svg
    assert len(re.findall(r'data-srcline="\d+"', svg)) == 2  # pd and pu
    assert len(re.findall(r'data-srccol="\d+"', svg)) == 2  # pd and pu

    svg_nonids = sch.render(include_nids=False).svg().decode()
    # '=' matches the attribute, not the CSS selector g[data-srcline].
    assert 'data-srcline=' not in svg_nonids
    assert 'data-srcfile=' not in svg_nonids


def test_srcloc_python_schematic_is_none():
    """Schematics built directly in Python (not ORD) carry no source location
    and emit no data-srcline."""
    sch = PyInv().schematic
    assert all(i.src_loc is None for i in sch.all(SchemInstance))
    assert 'data-srcline=' not in sch.render().svg().decode()
