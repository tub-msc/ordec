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
from importlib.resources import files

import pytest

import ordec.importer
from ordec import server
from ordec.jobrunner import InlineJobRunner
from ordec.core import Vec2R
from ordec.core.schema import SchemInstance, SchemPort, SourceLocInfo
from ordec.lib.generic_mos import Inv as PyInv
from ordec.language import compile_ord
from ordec.ord.parser import move_pos


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
    ports = {p.ref.full_path_str(): p.src_loc for p in mod.Inv().schematic.all(SchemPort)}
    assert ports['vdd'] == SourceLocInfo(mod.__file__, *_loc_of(src, 'port vdd:'))


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
    assert len(re.findall(r'data-srcline="\d+"', svg)) == 6  # pd, pu and 4 ports
    assert len(re.findall(r'data-srccol="\d+"', svg)) == 6

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


def test_move_pos():
    """move_pos (drag-and-drop in the web UI) adds the offset to the
    coordinate expressions of a statement's .pos, which moves every instance
    the statement creates by the offset."""
    src = """from ordec.core import *
from ordec.lib import Res

cell Arr:
    viewgen schematic(self) -> Schematic:
        net a
        path r
        for i in range(2):
            Res r[i]: .$r = 1; .p -- a; .n -- a; .pos = (4 * i + 2, i if i else 10)
        Res t: .$r = 1; .p -- a; .n -- a; .pos=(0,-2)
"""
    def positions(src):
        g = {}
        exec(compile_ord(src, g), g, g)
        return {i.full_path_str(): i.pos for i in g['Arr']().schematic.all(SchemInstance)}

    before = positions(src)
    cases = [
        ('Res r[i]', '4 * i + 5, (i if i else 10) - 2', {'r[0]', 'r[1]'}),
        ('Res t', '3,-4', {'t'}),
    ]
    for needle, text, names in cases:
        start, end, new = move_pos(src, *_loc_of(src, needle), 3, -2)
        assert new == text
        after = positions(src[:start] + new + src[end:])
        assert {name for name in before if after[name] != before[name]} == names
        assert all(after[name] == before[name] + Vec2R(3, -2) for name in names)

    # Refused: a position that is no tuple, and one of a nested statement.
    with pytest.raises(ValueError):
        move_pos(src.replace('.pos=(0,-2)', '.pos=p'), *_loc_of(src, 'Res t'), 3, -2)
    nested = src.replace('Res t: .$r = 1; .p -- a; .n -- a; .pos=(0,-2)',
        'Res t:\n            Res u: .pos = (5, 5)')
    with pytest.raises(ValueError):
        move_pos(nested, *_loc_of(nested, 'Res t'), 3, -2)


def test_move_node_files(tmp_path):
    """In local mode, the server changes the watched files of the design,
    but not those of ordec or of installed packages, and not once they have
    changed since the build."""
    handler = server.ConnectionHandler(server.ServerKey(), {}, jobrunner=InlineJobRunner())
    example = Path(str(files('ordec.examples').joinpath('voltagedivider.ord')))
    design = tmp_path / 'design.ord'
    design.write_text(example.read_text())
    watch = {str(f): (f.stat().st_mtime_ns, f.stat().st_size) for f in (design, example)}
    srcfiles = server.source_files(watch)
    assert list(srcfiles) == [str(design)]
    # res_1 is defined in line 12 at (5,6). The move changes the file size,
    # so the change is seen whatever the resolution of mtime.
    move = {'file': str(design), 'line': 12, 'column': 9, 'dx': 5, 'dy': 0}
    assert 'exception' not in handler.move_node(move, None, srcfiles)
    assert '.pos = (10,6)' in design.read_text()
    reply = handler.move_node(move, None, srcfiles)
    assert 'changed since the last build' in reply['exception']['message']
    reply = handler.move_node(dict(move, file=str(example)), None, srcfiles)
    assert 'not a source file' in reply['exception']['message']
