# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from textwrap import dedent

import pytest

from ordec.lsp.analysis import (
    AnalysisPosition,
    AnalysisSession,
    analyze_ord,
    file_uri_to_path,
)
from ordec.lsp.analysis.python_index import PythonModuleIndex
from ordec.lsp.server import OrdLanguageServer
import ordec


def position_at(source, needle, occurrence=1):
    """Return the one-based analysis position of text in source."""
    start = 0
    for _ in range(occurrence):
        offset = source.index(needle, start)
        start = offset + len(needle)

    line = source.count("\n", 0, offset) + 1
    previous_newline = source.rfind("\n", 0, offset)
    return AnalysisPosition(line=line, character=offset - previous_newline)


def position_after(source, needle, occurrence=1):
    """Return the one-based analysis position directly after text in source."""
    start = 0
    for _ in range(occurrence):
        offset = source.index(needle, start)
        start = offset + len(needle)

    offset += len(needle)
    line = source.count("\n", 0, offset) + 1
    previous_newline = source.rfind("\n", 0, offset)
    return AnalysisPosition(line=line, character=offset - previous_newline)


def completion_labels(session, uri, position):
    """Return completion labels at a position."""
    return {
        item["label"]
        for item in session.completions(uri, position)
    }


def diagnostic_codes(session, uri):
    """Return diagnostic codes for a document."""
    return [
        diagnostic.code
        for diagnostic in session.diagnostics(uri)
    ]


def test_structure_and_syntax_errors():
    source = dedent("""\
        import math
        from .helpers import foo as bar

        cell Inv:
            viewgen layout(self) -> Layout:
                output bus[0].y:
                    .align = East
                path vdd, vss

        def helper(x):
            return bar
        """)

    analysis = analyze_ord(source, uri="file:///tmp/test.ord", version=3)

    assert analysis.diagnostics == []
    assert analysis.version == 3
    assert analysis.imports == ["math", "from .helpers import foo as bar"]
    assert analysis.exports == ["Inv", "helper"]
    assert [(symbol.kind, symbol.name) for symbol in analysis.symbols] == [
        ("class", "Inv"),
        ("function", "layout"),
        ("context", "output bus[0].y"),
        ("path", "vdd, vss"),
        ("function", "helper"),
    ]

    broken = analyze_ord(dedent("""\
        cell Inv:
            viewgen layout("""))
    assert broken.symbols == []
    assert broken.diagnostics[0].code == "unexpected-token"

    dedented = analyze_ord(dedent("""\
        cell Inv:
                path a
            path b
        """))
    assert dedented.symbols == []
    assert dedented.diagnostics[0].code == "inconsistent-dedent"


def test_document_versions():
    session = AnalysisSession(workspace_root="/tmp/workspace")
    uri = "file:///tmp/test.ord"
    session.open_document(
        uri,
        dedent("""\
            cell Inv:
                viewgen symbol(self) -> Symbol:
                    path a
            """),
        version=1,
    )

    assert session.analyze(uri).version == 1
    assert [symbol.name for symbol in session.analyze(uri).symbols] == ["Inv", "symbol", "a"]

    session.update_document(uri, dedent("""\
        cell Inv:
            viewgen symbol(
        """), version=2)

    analysis = session.analyze(uri)
    assert analysis.version == 2
    assert analysis.diagnostics[0].code == "unexpected-token"
    assert [symbol.name for symbol in analysis.symbols] == ["Inv", "symbol", "a"]
    assert session.definition(uri, position_at("cell Inv:\n", "Inv"))["name"] == "Inv"

    session.close_document(uri)
    assert session.documents == {}


def test_error_snapshots_not_aliased():
    session = AnalysisSession(workspace_root="/tmp/workspace")
    uri = "file:///tmp/snapshot.ord"
    session.open_document(
        uri,
        dedent("""\
            cell Inv:
                viewgen symbol(self) -> Symbol:
                    path a
            """),
        version=1,
    )

    good = session.analyze(uri)
    session.update_document(uri, dedent("""\
        cell Inv:
            viewgen symbol(
        """), version=2)
    broken = session.analyze(uri)
    broken.symbols.clear()

    assert [symbol.name for symbol in good.symbols] == ["Inv", "symbol", "a"]
    assert [symbol.name for symbol in session.documents[uri]["last_good_analysis"].symbols] == [
        "Inv",
        "symbol",
        "a",
    ]


def test_find_spec_failure_unresolved(monkeypatch):
    index = PythonModuleIndex()

    def broken_find_spec(module_name):
        raise SystemExit("bad package")

    monkeypatch.setattr("importlib.util.find_spec", broken_find_spec)

    assert index.resolve_module_path("bad.package") is None
    assert not index.module_exists("bad.package")


def test_semantic_diagnostics(tmp_path):
    (tmp_path / "helper.ord").write_text(dedent("""\
        cell Other:
            viewgen symbol(self) -> Symbol:
                input a
        """))
    source = dedent("""\
        from .missing import Foo
        from .helper import Missing
        from ordec.lib.generic_mos import Nmos

        cell Inv:
            viewgen symbol(self) -> Symbol:
                input a
            viewgen schematic(self) -> Schematic:
                port b: .align=West
                ! b.pos.x == 0
                MissingCell inst:
                    .x -- b
                Nmos pd:
                    .missing -- b
                    .$bogus = 1u
            viewgen bad(self) -> Nmos:
                pass
        """)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = (tmp_path / "broken.ord").resolve().as_uri()
    session.open_document(uri, source)

    assert set(diagnostic_codes(session, uri)) == {
        "unresolved-import",
        "unresolved-import-member",
        "unresolved-node-type",
        "invalid-viewgen-return",
        "unknown-member",
        "unknown-parameter",
        "unknown-symbol-port",
    }


def test_ord_imports(tmp_path):
    (tmp_path / "mux2.ord").write_text(dedent("""\
        cell Mux2:
            viewgen symbol(self) -> Symbol:
                input a
        """))
    package_path = tmp_path / "ordcells"
    package_path.mkdir()
    (package_path / "__init__.ord").write_text(dedent("""\
        cell Exported:
            viewgen symbol(self) -> Symbol:
                input a
        """))
    top_source = dedent("""\
        from .mux2 import Mux2 as Stage
        from .ordcells import Exported

        cell Top:
            viewgen schematic(self) -> Schematic:
                Stage child:
                    .a -- net_a
                Exported exp:
                    .a -- net_a

        def helper(x=Stage):
            return x
        """)
    top_path = tmp_path / "top.ord"
    top_path.write_text(top_source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(top_path))

    assert session.diagnostics(uri) == []
    assert session.resolve_import_uris(uri) == [
        (tmp_path / "mux2.ord").resolve().as_uri(),
        (package_path / "__init__.ord").resolve().as_uri(),
    ]
    assert session.definition(uri, position_at(top_source, "Stage child"))["name"] == "Mux2"
    assert session.definition(uri, position_at(top_source, "Exported exp"))["name"] == "Exported"


def test_ord_star_imports(tmp_path):
    (tmp_path / "mux2.ord").write_text(dedent("""\
        cell Mux2:
            viewgen symbol(self) -> Symbol:
                input a
        """))
    star_source = dedent("""\
        from .mux2 import *

        cell Top:
            viewgen schematic(self) -> Schematic:
                Mux2 child:
                    .a -- net_a
        """)
    star_path = tmp_path / "star_user.ord"
    star_path.write_text(star_source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    star_uri = session.open_path(str(star_path))

    assert session.diagnostics(star_uri) == []
    assert session.definition(star_uri, position_at(star_source, "Mux2 child"))["name"] == "Mux2"


def test_python_import_variants(tmp_path):
    (tmp_path / "counter_yosys.py").write_text(dedent("""\
        class ExtLib:
            pass

        def report_digital_design():
            pass
        """))
    source = dedent("""\
        import math
        from counter_yosys import ExtLib, report_digital_design
        from ordec.layout import helpers
        from ordec.lib.generic_mos import Nmos

        cell Top:
            viewgen schematic(self) -> Schematic:
                value = math.log(2)
                Nmos m:
                    .d -- net_a

        def helper(x=ExtLib):
            return helpers, report_digital_design
        """)
    path = tmp_path / "top.ord"
    path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(path))

    assert session.diagnostics(uri) == []
    assert session.resolve_name(uri, "ExtLib")["kind"] == "class"
    assert session.resolve_name(uri, "helpers")["kind"] == "module"
    assert session.definition(uri, position_at(source, "Nmos m"))["name"] == "Nmos"


def test_python_members_and_completions():
    source = dedent("""\
        from ordec.core import *
        from ordec.lib.generic_mos import Nmos

        cell Inv:
            viewgen schematic(self) -> Schematic:
                net vss
                Nmos pd:
                    .s -- vss
                    .pos = (0, 0)
                pd.$l = 1u
                for inst in (pd,):
                    inst.g -- vss
        """)
    session = AnalysisSession()
    uri = "file:///tmp/python_members.ord"
    session.open_document(uri, source, version=1)

    assert session.diagnostics(uri) == []
    assert session.definition(uri, position_at(source, "s --"))["name"] == "s"
    assert session.definition(uri, position_after(source, "$"))["name"] == "l"
    assert session.definition(uri, position_at(source, "pos"))["name"] == "pos"
    assert session.definition(uri, position_at(source, "g --"))["name"] == "g"

    edited = source.replace(".s -- vss", ".")
    session.update_document(uri, edited, version=2)
    assert {"s", "d", "l"} <= completion_labels(
        session,
        uri,
        position_after(edited, "            ."),
    )


def test_reused_symbol_members():
    source = dedent("""\
        from ordec.core import *
        from ordec.lib.ihp130 import Nmos

        cell Inv:
            viewgen schematic(self) -> Schematic:
                net a, y, vss
                Nmos(w=1u, l=130n) pd:
                    .g -- a
                    .d -- y
                    .s -- vss
                    .b -- vss
        """)
    session = AnalysisSession()
    uri = "file:///tmp/parameterized_reused_symbol.ord"
    session.open_document(uri, source)

    assert session.diagnostics(uri) == []
    assert session.definition(uri, position_at(source, "Nmos(w"))["name"] == "Nmos"
    assert session.definition(uri, position_at(source, "g --"))["name"] == "g"


def test_cell_member_sources():
    source = dedent("""\
        from ordec.core import *

        cell Stage:
            viewgen symbol(self) -> Symbol:
                output q
            viewgen schematic(self) -> Schematic:
                return Schematic()
            viewgen layout(self) -> Layout:
                local = self.schematic
                LayoutRect bodybar

        cell Top:
            viewgen schematic(self) -> Schematic:
                net out
                Stage inst[0]:
                    .q -- out
                inst[0].q -- out
            viewgen layout(self) -> Layout:
                Stage lay:
                    ! .bodybar.width == 1
        """)
    session = AnalysisSession()
    uri = "file:///tmp/ord_members.ord"
    session.open_document(uri, source)

    assert session.diagnostics(uri) == []
    assert session.definition(uri, position_at(source, "schematic", 2))["name"] == "schematic"
    assert session.definition(uri, position_at(source, "q -- out"))["name"] == "q"
    assert session.definition(uri, position_at(source, "bodybar"))["name"] == "bodybar"


def test_relative_python_cells(tmp_path):
    package_path = tmp_path / "pkg"
    ord_path = package_path / "ord"
    ord_path.mkdir(parents=True)
    (package_path / "__init__.py").write_text("")
    (ord_path / "__init__.py").write_text("")
    (package_path / "devices.py").write_text(dedent("""\
        from ordec.core import *

        class DFF(Cell):
            @generate
            def symbol(self) -> Symbol:
                s = Symbol(cell=self)
                s.d = Pin()
                s.q = Pin()
                return s
        """))
    reg_path = ord_path / "reg.ord"
    reg_path.write_text(dedent("""\
        from ordec.core import *
        from ..devices import DFF

        cell Reg:
            bits = Parameter(int)
            viewgen schematic(self) -> Schematic:
                path d
                path I
                for i in range(self.bits):
                    net d[i]
                    DFF I[i]:
                        .d -- d[i]
                        .q -- d[i]
                    I[i].pos = (6, 3 + 8 * i)
                    I[i].q -- d[i]
        """))

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(reg_path))

    assert session.diagnostics(uri) == []


def test_dynamic_ordb_members():
    source = dedent("""\
        from ordec.core import *
        from ordec.sim import Simulator

        def helper():
            root = Symbol()
            with root.ctx():
                input a
                assert .a == a
            assert root.a == a
            assert root.all(Pin)
            assert Pin().parent
            return Simulator(SimHierarchy()).netlister
        """)
    session = AnalysisSession()
    uri = "file:///tmp/dynamic_runtime_patterns.ord"
    session.open_document(uri, source)

    assert session.diagnostics(uri) == []


def test_navigation_and_rename(tmp_path):
    mux_path = tmp_path / "mux2.ord"
    mux_path.write_text(dedent("""\
        cell Mux2:
            viewgen symbol(self) -> Symbol:
                path a
        """))
    source = dedent("""\
        from .mux2 import Mux2 as Stage

        def helper(x=Stage):
            return Stage
        """)
    user_path = tmp_path / "user.ord"
    user_path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(user_path))
    position = position_at(source, "Stage", 2)

    assert session.definition(uri, position)["name"] == "Mux2"
    assert "Mux2" in session.hover(uri, position)["contents"]
    # Three Stage tokens, the imported Mux2 token, and the definition.
    assert len(session.references(uri, position)) == 5
    assert len(session.document_highlights(uri, position)) == 4
    assert session.prepare_rename(uri, position)["placeholder"] == "Stage"
    assert uri in session.rename(uri, position, "Driver")


def test_python_scopes(tmp_path):
    source = dedent("""\
        def helper(items, value):
            left, right = value
            for idx, pin in items:
                current = pin
            with open('x') as handle:
                data = handle.read()
            try:
                raise ValueError(data)
            except ValueError as exc:
                return left, right, idx, pin, handle, exc
        """)
    path = tmp_path / "scopes.ord"
    path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = path.resolve().as_uri()

    for name in ("left", "right", "idx", "pin", "handle", "exc"):
        definition = session.definition(uri, position_at(source, name, 2))
        assert definition["name"] == name
        assert definition["uri"] == uri

    assert "current" in completion_labels(session, uri, position_at(source, "return"))


def test_assignment_targets_not_bindings(tmp_path):
    source = dedent("""\
        def helper(idx, value):
            unknown[idx] = value
            target.field = value
            return idx, unknown, target
        """)
    path = tmp_path / "assignment_targets.ord"
    path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = path.resolve().as_uri()

    assert session.definition(uri, position_at(source, "idx]"))["name"] == "idx"
    assert session.definition(uri, position_at(source, "unknown", 2)) is None
    assert session.definition(uri, position_at(source, "target", 2)) is None


def test_workspace_cache(tmp_path):
    source = dedent("""\
        import math

        cell Mux2:
            viewgen symbol(self) -> Symbol:
                path a

        def helper():
            .align = East
            return math
        """)
    path = tmp_path / "mux2.ord"
    path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(path))

    assert [symbol["name"] for symbol in session.workspace_symbols("mux")] == ["Mux2"]
    assert session.folding_ranges(uri)
    assert session.selection_ranges(uri, [position_at(source, "symbol")])[0] is not None
    assert {
        token["type"]
        for token in session.semantic_tokens(uri)
    } >= {"class", "function", "property"}

    path.write_text(source.replace("Mux2", "Mux4"))
    session.invalidate_path(str(path))
    assert [symbol["name"] for symbol in session.workspace_symbols("mux")] == ["Mux4"]


def test_dirty_rows_refresh_without_rescan(tmp_path, monkeypatch):
    (tmp_path / "a.ord").write_text(dedent("""\
        cell A:
            viewgen symbol(self) -> Symbol:
                input a
        """))
    (tmp_path / "b.ord").write_text(dedent("""\
        cell B:
            viewgen symbol(self) -> Symbol:
                input a
        """))
    path = tmp_path / "top.ord"
    source = dedent("""\
        from .a import A

        cell Top:
            viewgen schematic(self) -> Schematic:
                A inst:
                    .a -- net_a
        """)
    path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(path))
    first_index = session.workspace_import_index()
    assert (tmp_path / "a.ord").resolve().as_uri() in first_index["imports"][uri]

    def fail_workspace_uris():
        raise AssertionError("workspace_uris should not run for dirty-row refresh")

    monkeypatch.setattr(session, "workspace_uris", fail_workspace_uris)
    edited = source.replace("from .a import A", "from .b import B").replace("A inst", "B inst")
    session.update_document(uri, edited)

    refreshed_index = session.workspace_import_index()
    assert (tmp_path / "b.ord").resolve().as_uri() in refreshed_index["imports"][uri]


def test_unopened_file_uris(tmp_path):
    source = dedent("""\
        cell Mux2:
            viewgen symbol(self) -> Symbol:
                path a

        def helper():
            return Mux2
        """)
    path = tmp_path / "unopened.ord"
    path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    analysis = session.analyze(path.resolve().as_uri())

    assert [symbol.name for symbol in analysis.symbols] == [
        "Mux2",
        "symbol",
        "a",
        "helper",
    ]


def test_simulation_alias():
    source = dedent("""\
        from ordec.core import *

        cell Tb:
            viewgen sim(self) -> Simulation:
                pass
        """)
    session = AnalysisSession()
    uri = "file:///tmp/sim_alias.ord"
    session.open_document(uri, source)

    assert session.diagnostics(uri) == []
    assert session.definition(uri, position_at(source, "Simulation"))["name"] == "SimHierarchy"


def test_windows_drive_uri():
    for uri in ("file:///C:/designs/inv.ord", "file:///c%3A/designs/inv.ord"):
        path = file_uri_to_path(uri)
        assert not str(path).startswith(("/C:", "/c:"))
        assert str(path).endswith(":/designs/inv.ord")

    assert str(file_uri_to_path("file:///tmp/inv.ord")) == "/tmp/inv.ord"
    assert file_uri_to_path("untitled:Untitled-1") is None


def test_lines_cache_updates():
    session = AnalysisSession()
    uri = "file:///tmp/lines.ord"
    session.open_document(uri, dedent("""\
        net a
        net b
        """))

    lines = session.document_lines(uri)
    assert lines == ["net a", "net b"]
    assert session.document_lines(uri) is lines

    session.update_document(uri, dedent("""\
        net a
        net b
        net c
        """))
    assert session.document_lines(uri) == ["net a", "net b", "net c"]
    assert session.document_lines("file:///tmp/untracked.ord") is None

    session.update_document(uri, dedent("""\
        net a\u2028b
        net c
        """))
    assert session.document_lines(uri) == ["net a\u2028b", "net c"]


def test_scan_skips_undecodable(tmp_path):
    (tmp_path / "good.ord").write_text(dedent("""\
        cell Inv:
            viewgen symbol(self) -> Symbol:
                input a
        """))
    (tmp_path / "bad.ord").write_bytes(b"cell Caf\xe9:\n")

    session = AnalysisSession(workspace_root=str(tmp_path))

    assert session.workspace_uris() == [(tmp_path / "good.ord").as_uri()]
    assert session.ensure_document((tmp_path / "bad.ord").as_uri()) is False


def test_rename_refuses_python_symbols(tmp_path):
    (tmp_path / "extlib.py").write_text(dedent("""\
        class Stage:
            pass
        """))
    source = dedent("""\
        from extlib import Stage

        def helper(x=Stage):
            return x
        """)
    path = tmp_path / "top.ord"
    path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(path))
    position = position_at(source, "Stage", occurrence=2)

    assert session.definition(uri, position)["uri"].endswith("extlib.py")
    assert session.prepare_rename(uri, position) is None
    assert session.rename(uri, position, "Driver") is None


def test_symlinked_workspace_uris(tmp_path):
    real_root = tmp_path / "real"
    real_root.mkdir()
    (real_root / "top.ord").write_text(dedent("""\
        cell Inv:
            viewgen symbol(self) -> Symbol:
                input a
        """))
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root)

    session = AnalysisSession(workspace_root=str(linked_root))
    uri = (linked_root / "top.ord").as_uri()

    assert session.canonical_uri(uri) == uri
    assert session.workspace_uris() == [uri]


def test_init_ord_packages(tmp_path, monkeypatch):
    package_path = tmp_path / "pkg"
    package_path.mkdir()
    init_path = package_path / "__init__.ord"
    init_path.write_text("")
    sub_path = package_path / "sub.ord"
    sub_path.write_text(dedent("""\
        cell Inner:
            viewgen symbol(self) -> Symbol:
                input a
        """))
    top_path = tmp_path / "top.ord"
    source = "from .pkg import sub\n"
    top_path.write_text(source)

    index = PythonModuleIndex(workspace_root=str(tmp_path))
    assert index.resolve_module_path("pkg") == init_path.resolve()
    assert index.resolve_module_path("pkg.sub") == sub_path.resolve()
    assert index.module_exists("pkg.sub")

    # Installed packages rooted by __init__.ord resolve their .ord
    # modules through the parent package, like __init__.py ones do.
    class InitOrdSpec:
        origin = str(init_path)

    installed_index = PythonModuleIndex()
    monkeypatch.setattr(
        installed_index,
        "find_spec",
        lambda name: InitOrdSpec() if name == "pkg" else None,
    )
    assert installed_index.resolve_module_path("pkg.sub") == sub_path.resolve()

    # The session navigates import members through the same resolution.
    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(top_path))
    assert session.diagnostics(uri) == []
    assert session.definition(uri, position_at(source, "sub"))["uri"] == sub_path.as_uri()


def test_imports_match_runtime_importer(tmp_path):
    sub_path = tmp_path / "sub"
    sub_path.mkdir()
    (tmp_path / "sub.ord").write_text(dedent("""\
        cell Decoy:
            pass
        """))
    (sub_path / "__init__.ord").write_text(dedent("""\
        cell Inner:
            pass
        """))
    (sub_path / "lib.ord").write_text(dedent("""\
        cell Inv:
            viewgen symbol(self) -> Symbol:
                input a
        """))
    top_source = dedent("""\
        from lib import Inv
        from . import Inner
        """)
    top_path = sub_path / "top.ord"
    top_path.write_text(top_source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    init_uri = session.open_path(str(sub_path / "__init__.ord"))
    lib_uri = session.open_path(str(sub_path / "lib.ord"))
    top_uri = session.open_path(str(top_path))
    assert session.diagnostics(top_uri) == []

    # The runtime importer searches the script's own directory, so the
    # sibling import must resolve and appear in the import graph.
    assert session.definition(top_uri, position_at(top_source, "Inv"))["uri"] == lib_uri
    assert top_uri in session.workspace_dependents(lib_uri)

    # "from . import X" names the package, never the sibling sub.ord.
    assert session.definition(top_uri, position_at(top_source, "Inner"))["uri"] == init_uri


def test_export_ranges_avoid_keywords(tmp_path):
    (tmp_path / "shortnames.py").write_text(dedent("""\
        def f(x):
            return x

        class C:
            def d(self):
                pass
        """))
    index = PythonModuleIndex(workspace_root=str(tmp_path))

    # A short name must not match inside the def or class keyword.
    assert index.definition("shortnames", export_name="f")[
        "selection_range"
    ].start == AnalysisPosition(line=1, character=5)
    assert index.definition("shortnames", export_name="C")[
        "selection_range"
    ].start == AnalysisPosition(line=4, character=7)
    assert index.class_members("shortnames", "C")["d"][
        "selection_range"
    ].start == AnalysisPosition(line=5, character=9)


def test_port_action_refuses_stale():
    session = AnalysisSession(workspace_root="/tmp/workspace")
    uri = "file:///tmp/stale.ord"
    session.open_document(
        uri,
        dedent("""\
            cell Inv:
                viewgen symbol(self) -> Symbol:
                    input a
                    input b
            """),
        version=1,
    )
    session.analyze(uri)
    session.update_document(uri, dedent("""\
        cell Inv:
            viewgen symbol(
        """), version=2)
    session.analyze(uri)

    diagnostic = {
        "code": "unknown-symbol-port",
        "range": {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 0},
        },
        "data": {"portName": "c"},
    }
    server = OrdLanguageServer()
    server.session = session
    # The broken document is served from its stale last-good analysis,
    # whose insert positions may point past the current text, so
    # code_actions must refuse for every action like rename does.
    assert server.code_actions(uri, [diagnostic]) == []


def test_workspace_rename(tmp_path):
    mux_source = dedent("""\
        cell Mux2:
            viewgen symbol(self) -> Symbol:
                input a
        """)
    mux_path = tmp_path / "mux2.ord"
    mux_path.write_text(mux_source)
    top_source = dedent("""\
        from .mux2 import Mux2

        cell Top:
            viewgen schematic(self) -> Schematic:
                net n1
                Mux2 inst:
                    .a -- n1
        """)
    top_path = tmp_path / "top.ord"
    top_path.write_text(top_source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    mux_uri = session.open_path(str(mux_path))
    top_uri = session.open_path(str(top_path))
    pin_position = position_at(mux_source, "a")

    changes = session.rename(mux_uri, pin_position, "b")
    assert set(changes) == {mux_uri, top_uri}
    assert [change["range"] for change in changes[top_uri]] == [
        session.name_at_position(top_uri, position_at(top_source, "a --"))["range"],
    ]

    broken_top = top_source.replace("        net n1\n", "        net n1(\n")
    session.open_document(top_uri, broken_top, version=2)
    with pytest.raises(ValueError, match="without syntax errors"):
        session.rename(mux_uri, pin_position, "b")


def test_rename_refusals(tmp_path):
    session = AnalysisSession()
    uri = "file:///tmp/stale_rename.ord"
    source = dedent("""\
        def helper():
            value = 1
            return value
        """)
    session.open_document(uri, source, version=1)
    session.analyze(uri)
    broken = source + "def broken(\n"
    session.update_document(uri, broken, version=2)

    assert session.prepare_rename(uri, position_at(broken, "value")) is None
    with pytest.raises(ValueError, match="without syntax errors"):
        session.rename(uri, position_at(broken, "value"), "count")

    package_path = tmp_path / "pkg"
    package_path.mkdir()
    (package_path / "__init__.py").write_text("")
    (package_path / "sub.py").write_text("VALUE = 1\n")
    import_source = dedent("""\
        import pkg.sub
        import pkg.sub as module_alias

        def helper():
            return pkg, module_alias
        """)
    import_path = tmp_path / "imports.ord"
    import_path.write_text(import_source)
    import_session = AnalysisSession(workspace_root=str(tmp_path))
    import_uri = import_session.open_path(str(import_path))

    assert import_session.prepare_rename(
        import_uri,
        position_at(import_source, "pkg", occurrence=3),
    ) is None
    alias_position = position_at(import_source, "module_alias", occurrence=2)
    assert import_session.prepare_rename(import_uri, alias_position) is not None
    alias_changes = import_session.rename(import_uri, alias_position, "module")
    assert len(alias_changes[import_uri]) == 2


def test_dotted_viewgen_returns(tmp_path):
    (tmp_path / "viewlib.py").write_text(dedent("""\
        class CustomView:
            view_builder = object
        """))
    source = dedent("""\
        from ordec import core
        import viewlib

        cell Top:
            viewgen schematic(self) -> core.Schematic:
                net n1
                net n2
                ! n1 == n2
            viewgen custom(self) -> viewlib.CustomView:
                pass
        """)
    top_path = tmp_path / "top.ord"
    top_path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(top_path))
    analysis = session.analyze(uri)

    # The rightmost name is the return type, so the constraint inside
    # the schematic viewgen is valid and no false error is reported.
    assert [record["return_type"] for record in analysis.viewgen_returns] == [
        "Schematic",
        "CustomView",
    ]
    assert session.diagnostics(uri) == []

    # An unresolved base of a qualified return type is still reported.
    session.open_document(uri, source.replace("import viewlib\n", ""), version=2)
    assert [diagnostic.code for diagnostic in session.diagnostics(uri)] == [
        "unresolved-viewgen-return",
    ]


def test_viewgen_oldform_diagnostic():
    # The legacy parenless spelling gets one targeted diagnostic mirroring
    # the compiler's fix-it; the body is not analyzed, so the unresolvable
    # node kind inside it stays unreported.
    source = dedent("""\
        cell Inv:
            viewgen symbol -> Symbol:
                UnknownKind x
        """)
    session = AnalysisSession()
    uri = "file:///tmp/oldform.ord"
    session.open_document(uri, source)

    diagnostics = session.diagnostics(uri)
    assert [diagnostic.code for diagnostic in diagnostics] == ["viewgen-parameter-list"]
    assert "viewgen symbol declares no parameter list" in diagnostics[0].message


def test_unannotated_viewgen_constraint():
    # Without a return annotation the view type comes from `. = ...` at
    # runtime, so constraints in the body cannot be validated statically
    # and must not be flagged.
    source = dedent("""\
        cell Top:
            viewgen schematic(self):
                net n1
                net n2
                ! n1 == n2
        """)
    session = AnalysisSession()
    uri = "file:///tmp/unannotated_viewgen.ord"
    session.open_document(uri, source)

    assert session.diagnostics(uri) == []


def test_rename_preserves_import_alias(tmp_path):
    lib_source = dedent("""\
        cell Inv:
            viewgen symbol(self) -> Symbol:
                input a
        """)
    lib_path = tmp_path / "lib.ord"
    lib_path.write_text(lib_source)
    top_source = dedent("""\
        from lib import Inv as I

        cell Top:
            viewgen schematic(self) -> Schematic:
                net n1
                I inst:
                    .a -- n1
        """)
    top_path = tmp_path / "top.ord"
    top_path.write_text(top_source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    lib_uri = session.open_path(str(lib_path))
    top_uri = session.open_path(str(top_path))
    export_position = position_at(top_source, "Inv")

    # The exported-name token of an aliased from-import resolves to the
    # cell definition, like the alias token does.
    assert session.definition(top_uri, export_position)["uri"] == lib_uri

    # Renaming the cell must rewrite the exported name but keep the alias,
    # yielding "from lib import Nand as I".
    changes = session.rename(lib_uri, position_at(lib_source, "Inv"), "Nand")
    assert set(changes) == {lib_uri, top_uri}
    assert [change["range"] for change in changes[top_uri]] == [
        session.name_at_position(top_uri, export_position)["range"],
    ]


def test_subtree_bindings():
    source = dedent("""\
        def helper(width, lib, items):
            values = [item for item in items if item]
            Res(r=width) r1:
                pass
            lib.Inv i1:
                pass
            return values
        """)
    session = AnalysisSession()
    uri = "file:///tmp/node_kinds.ord"
    session.open_document(uri, source)
    analysis = session.analyze(uri)

    assert session.definition(uri, position_at(source, "width", occurrence=2))["name"] == "width"
    assert session.definition(uri, position_at(source, "lib", occurrence=2))["name"] == "lib"
    item_definition = session.definition(uri, position_at(source, "item for"))
    assert item_definition["selection_range"].start == position_at(source, "item in")
    i1_binding = next(binding for binding in analysis.bindings if binding["name"] == "i1")
    assert i1_binding["type_names"] == ["Inv"]
    assert any(member["name"] == "Inv" for member in analysis.member_occurrences)


def test_relative_from_imports(tmp_path):
    package_path = tmp_path / "pkg"
    package_path.mkdir()
    init_source = dedent("""\
        cell Root:
            viewgen symbol(self) -> Symbol:
                input a
        """)
    (package_path / "__init__.ord").write_text(init_source)
    device_source = dedent("""\
        cell Device:
            viewgen symbol(self) -> Symbol:
                input a
        """)
    device_path = package_path / "device.ord"
    device_path.write_text(device_source)
    source = dedent("""\
        from . import device
        from . import Root

        def helper():
            return device, Root
        """)
    top_path = package_path / "top.ord"
    top_path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(top_path))

    assert session.diagnostics(uri) == []
    device_definition = session.definition(
        uri,
        position_at(source, "device", occurrence=2),
    )
    assert device_definition["uri"] == device_path.as_uri()
    assert session.definition(uri, position_at(source, "Root", occurrence=2))["uri"] == (
        package_path / "__init__.ord"
    ).as_uri()
    assert set(session.resolve_import_uris(uri)) == {
        (package_path / "__init__.ord").as_uri(),
        device_path.as_uri(),
    }


def test_unreadable_imports_no_crash(tmp_path):
    bad_path = tmp_path / "bad.ord"
    bad_path.write_bytes(b"cell Caf\xe9:\n")
    source = "from .bad import Missing\n"
    top_path = tmp_path / "top.ord"
    top_path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(top_path))

    assert diagnostic_codes(session, uri) == ["unresolved-import-member"]
    assert set(session.analyze_related(uri)) == {uri}
    assert session.update_path(str(bad_path)) == bad_path.as_uri()
    assert session.resolve_module_uri(uri, "." * 100) is None


def test_decorated_exports(tmp_path):
    library_source = dedent("""\
        @decorator
        cell Decorated:
            viewgen symbol(self) -> Symbol:
                input a
        """)
    (tmp_path / "library.ord").write_text(library_source)
    source = dedent("""\
        from .library import Decorated

        cell Top:
            viewgen schematic(self) -> Schematic:
                net d[WIDTH]
                Decorated inst:
                    .a -- d[0]

        WIDTH = 4
        """)
    path = tmp_path / "top.ord"
    path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(path))

    assert session.diagnostics(uri) == []


def test_indexed_member_navigation():
    source = dedent("""\
        from ordec.core import *

        cell Stage:
            viewgen symbol(self) -> Symbol:
                output q

        cell Top:
            viewgen schematic(self) -> Schematic:
                net out
                path I
                Stage I[0]:
                    .q -- out
                I[0].q -- out
        """)
    session = AnalysisSession()
    uri = "file:///tmp/indexed_member.ord"
    session.open_document(uri, source, version=1)

    definition = session.definition(uri, position_at(source, "q -- out", occurrence=2))
    assert definition["name"] == "q"

    completion_source = dedent("""\
        from ordec.lib.generic_mos import Nmos

        def helper():
            pd = Nmos()
            return pd.d
        """)
    completion_uri = "file:///tmp/nested_completion.ord"
    session.open_document(completion_uri, completion_source, version=1)
    edited = completion_source.replace("pd.d\n", "pd.d.\n")
    session.update_document(completion_uri, edited, version=2)

    assert session.completions(
        completion_uri,
        position_after(edited, "pd.d."),
    ) == []


def test_lambda_and_with_bindings():
    source = dedent("""\
        def helper(factory):
            callback = lambda first, *, second=1, **kwargs: first + second + kwargs["x"]
            with (factory()) as handle:
                local = handle
            with (factory() as first_handle, factory()) as group:
                pair = first_handle, group
            try:
                pass
            except* ValueError as grouped:
                error = grouped
            return callback, handle, first_handle, group, grouped
        """)
    session = AnalysisSession()
    uri = "file:///tmp/scope_variants.ord"
    session.open_document(uri, source)

    for name in ("first", "second", "kwargs"):
        definition = session.definition(uri, position_at(source, name, occurrence=2))
        assert definition["name"] == name
        assert definition["kind"] == "parameter"
    for name in ("handle", "first_handle", "group", "grouped"):
        assert session.definition(uri, position_at(source, name, occurrence=2))["name"] == name


def test_python_index_edge_cases(tmp_path, monkeypatch):
    (tmp_path / "broken.py").write_text("VALUE = 1\n")
    index = PythonModuleIndex(workspace_root=str(tmp_path))

    def invalid_tree(*args, **kwargs):
        raise ValueError("source contains null bytes")

    with monkeypatch.context() as context:
        context.setattr("ast.parse", invalid_tree)
        assert index.module_info("broken") is None

    first_path = tmp_path / "first.py"
    first_path.write_text(dedent("""\
        class Choice:
            pass
        """))
    second_path = tmp_path / "second.py"
    second_path.write_text(dedent("""\
        class Choice:
            pass
        """))
    (tmp_path / "bridge.py").write_text(dedent("""\
        from first import Choice as Selected
        from second import Choice as Selected
        """))
    index = PythonModuleIndex(workspace_root=str(tmp_path))
    assert index.definition("bridge", export_name="Selected")["uri"] == second_path.as_uri()

    ord_path = tmp_path / "celllib.ord"
    ord_path.write_text(dedent("""\
        cell Old:
            pass
        """))
    session = AnalysisSession(workspace_root=str(tmp_path))
    assert "Old" in session.python_module_info("celllib")["exports"]
    ord_path.write_text(dedent("""\
        cell New:
            pass
        """))
    session.invalidate_path(str(ord_path))
    assert set(session.python_module_info("celllib")["exports"]) == {"New"}


def test_new_file_rebuilds_dependents(tmp_path):
    top_path = tmp_path / "top.ord"
    top_path.write_text("from .new_cell import NewCell\n")
    session = AnalysisSession(workspace_root=str(tmp_path))
    top_uri = session.open_path(str(top_path))
    assert session.workspace_import_index()["imports"][top_uri] == set()

    new_path = tmp_path / "new_cell.ord"
    new_path.write_text(dedent("""\
        cell NewCell:
            pass
        """))
    new_uri = session.invalidate_path(str(new_path))

    assert session.workspace_dependents(new_uri) == {top_uri}


def test_function_header_bindings():
    source = dedent("""\
        T = object
        x = [1]
        def helper(x: T = x, *args: T, y=x, **kwargs: T) -> T:
            return args, kwargs
        """)
    session = AnalysisSession()
    uri = "file:///tmp/header_scopes.ord"
    session.open_document(uri, source)

    outer_x = session.definition(uri, position_at(source, "x", occurrence=1))
    parameter_x = session.definition(uri, position_at(source, "x", occurrence=2))
    assert parameter_x["binding_id"] != outer_x["binding_id"]
    for occurrence in (3, 4):
        definition = session.definition(uri, position_at(source, "x", occurrence))
        assert definition["binding_id"] == outer_x["binding_id"]

    outer_t = session.definition(uri, position_at(source, "T"))
    for occurrence in range(2, 6):
        definition = session.definition(uri, position_at(source, "T", occurrence))
        assert definition["binding_id"] == outer_t["binding_id"]

    for name in ("args", "kwargs"):
        definition = session.definition(uri, position_at(source, name, occurrence=2))
        assert definition["kind"] == "parameter"


def test_lone_carriage_returns():
    source = "value = 1\rdef helper():\r    return value\r"
    session = AnalysisSession()
    uri = "file:///tmp/lone_cr.ord"
    session.open_document(uri, source)

    assert session.diagnostics(uri) == []
    definition = session.definition(uri, AnalysisPosition(3, 12))
    assert definition["selection_range"].start == AnalysisPosition(1, 1)


def test_definition_at_identifier_end():
    source = dedent("""\
        def helper():
            local = 1
            return local
        """)
    session = AnalysisSession()
    uri = "file:///tmp/end_definition.ord"
    session.open_document(uri, source)

    definition = session.definition(
        uri,
        position_after(source, "local", occurrence=2),
    )
    assert definition["kind"] == "variable"
    assert definition["selection_range"].start == position_at(source, "local")


def test_rename_collision():
    source = dedent("""\
        cell Inv:
            pass

        cell Buf:
            pass
        """)
    session = AnalysisSession()
    uri = "file:///tmp/rename_collision.ord"
    session.open_document(uri, source)

    with pytest.raises(ValueError, match="conflicts with existing name"):
        session.rename(uri, position_at(source, "Inv"), "Buf")


def test_chained_member_completion():
    source = dedent("""\
        from ordec.core import *

        cell Stage:
            viewgen symbol(self) -> Symbol:
                output d

        cell Top:
            viewgen schematic(self) -> Schematic:
                Stage inst:
                    .d
        """)
    session = AnalysisSession()
    uri = "file:///tmp/implicit_chain.ord"
    session.open_document(uri, source, version=1)
    edited = source.replace("            .d\n", "            .d.\n")
    session.update_document(uri, edited, version=2)

    assert session.completions(uri, position_after(edited, ".d.")) == []


@pytest.mark.parametrize("suffix", [".py", ".ord"])
def test_python_index_unicode_attribute_ranges(tmp_path, suffix):
    source = dedent("""\
        class Device:
            def build(self):
                root = Symbol()
                root.élé = Pin()
        """)
    (tmp_path / ("device" + suffix)).write_text(source)
    member = PythonModuleIndex(workspace_root=str(tmp_path)).class_members(
        "device",
        "Device",
    )["élé"]

    assert member["selection_range"].start == AnalysisPosition(4, 14)
    assert member["selection_range"].end == AnalysisPosition(4, 17)


def test_close_keeps_import_index(tmp_path):
    source = dedent("""\
        cell Device:
            pass
        """)
    path = tmp_path / "device.ord"
    path.write_text(source)
    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = path.as_uri()
    session.open_document(uri, source, version=1)
    workspace_index = session.workspace_import_index()

    session.close_document(uri)

    assert session.documents[uri]["is_open"] is False
    assert session.workspace_import_index() is workspace_index


def test_workspace_symbols_reuse_scan(tmp_path, monkeypatch):
    (tmp_path / "first.ord").write_text(dedent("""\
        cell First:
            pass
        """))
    session = AnalysisSession(workspace_root=str(tmp_path))
    original = session.workspace_ord_paths
    calls = []

    def counted_paths(root_path):
        calls.append(root_path)
        yield from original(root_path)

    monkeypatch.setattr(session, "workspace_ord_paths", counted_paths)
    assert [item["name"] for item in session.workspace_symbols()] == ["First"]
    assert [item["name"] for item in session.workspace_symbols()] == ["First"]
    assert len(calls) == 1

    second_path = tmp_path / "second.ord"
    second_path.write_text(dedent("""\
        cell Second:
            pass
        """))
    session.invalidate_path(str(second_path))
    assert {item["name"] for item in session.workspace_symbols()} == {
        "First",
        "Second",
    }
    assert len(calls) == 1


def ord_files_in_ordec_package():
    """The .ord files inside the imported ordec package, relative to it."""
    root = Path(ordec.__file__).parent
    files = sorted(p.relative_to(root) for p in root.rglob("*.ord"))
    assert files
    return files


@pytest.mark.parametrize("path", ord_files_in_ordec_package(), ids=str)
def test_ord_file_clean(path):
    """Every .ord file shipped in the ordec package (courses, examples)
    must analyze without LSP diagnostics: catches analyzer false
    positives against real designs and shipped files left behind by
    language changes."""
    root = Path(ordec.__file__).parent
    session = AnalysisSession(workspace_root=str(root))
    uri = session.open_path(str(root / path))
    assert session.diagnostics(uri) == []


def test_multi_target_node_statements():
    source = dedent("""\
        cell Inv:
            viewgen symbol(self) -> Symbol:
                input a, b
            viewgen schematic(self) -> Schematic:
                port a
                port b
        """)
    session = AnalysisSession()
    uri = "file:///tmp/multi_target.ord"
    session.open_document(uri, source, version=1)
    analysis = session.analyze(uri)

    # One symbol per statement like path/net: per-target symbols would
    # share the statement range and read as nested in document outlines.
    assert [(symbol.kind, symbol.name) for symbol in analysis.symbols] == [
        ("class", "Inv"),
        ("function", "symbol"),
        ("context", "input a, b"),
        ("function", "schematic"),
        ("context", "port a"),
        ("context", "port b"),
    ]
    assert [
        statement["target_name"] for statement in analysis.node_statements
    ] == ["a", "b", "a", "b"]

    # Pin extraction reads the per-target node statements, so both names
    # of the combined declaration count as pins for the port check.
    assert session.diagnostics(uri) == []

    # Dropping a name from the combined declaration is still reported.
    session.update_document(uri, source.replace("input a, b", "input a"), version=2)
    assert [diagnostic.code for diagnostic in session.diagnostics(uri)] == [
        "unknown-symbol-port",
    ]


def test_container_literal_untyped():
    source = dedent("""\
        cell Adder:
            viewgen schematic(self) -> Schematic:
                port cin
                carry = [cin]
                carry.append(cin)
        """)
    session = AnalysisSession()
    uri = "file:///tmp/container.ord"
    session.open_document(uri, source, version=1)

    assert session.diagnostics(uri) == []

    # Unpacking targets still take the container's element types.
    unpacked = (source
        .replace("carry = [cin]", "first, second = [cin, cin]")
        .replace("carry.append(cin)", "first.append(cin)"))
    session.update_document(uri, unpacked, version=2)
    assert [diagnostic.code for diagnostic in session.diagnostics(uri)] == [
        "unknown-member",
    ]


def test_references_outside_workspace(tmp_path):
    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = "file:///outside/scratch.ord"
    source = dedent("""\
        from ordec.lib.generic_mos import Nmos
        cell Top:
            viewgen schematic(self) -> Schematic:
                Nmos inst:
                    .w = 1
        """)
    session.open_document(uri, source, version=1)

    # Nmos resolves to a Python definition, whose reference search must
    # still cover the requesting document outside the workspace root.
    references = session.references(uri, position_at(source, "Nmos inst"))
    assert len(references) == 2
    assert all(reference["uri"] == uri for reference in references)


def test_completion_ranking():
    session = AnalysisSession()
    uri = "file:///tmp/complete.ord"
    source = dedent("""\
        cell Amp:
            viewgen schematic(self) -> Schematic:
                net nmos_w
                net outp
        """)
    session.open_document(uri, source, version=1)

    labels = [
        item["label"]
        for item in session.completions(uri, position_after(source, "net outp"))
    ]
    assert labels.index("nmos_w") < labels.index("net")
    assert labels.index("outp") < labels.index("output")
