# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest

from ordec.lsp.analysis import (
    AnalysisPosition,
    AnalysisSession,
    analyze_ord,
    file_uri_to_path,
)
from ordec.lsp.analysis.python_index import PythonModuleIndex
from ordec.lsp.server import OrdLanguageServer


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


def test_analyze_ord_collects_public_structure_and_syntax_errors():
    source = (
        "import math\n"
        "from .helpers import foo as bar\n"
        "\n"
        "cell Inv:\n"
        "    viewgen layout -> Layout:\n"
        "        output bus[0].y:\n"
        "            .align = East\n"
        "        path vdd, vss\n"
        "\n"
        "def helper(x):\n"
        "    return bar\n"
    )

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

    broken = analyze_ord("cell Inv:\n    viewgen layout(")
    assert broken.symbols == []
    assert broken.diagnostics[0].code == "unexpected-token"

    dedented = analyze_ord("cell Inv:\n        path a\n    path b\n")
    assert dedented.symbols == []
    assert dedented.diagnostics[0].code == "inconsistent-dedent"


def test_analysis_session_tracks_document_versions_and_last_good_analysis():
    session = AnalysisSession(workspace_root="/tmp/workspace")
    uri = "file:///tmp/test.ord"
    session.open_document(
        uri,
        "cell Inv:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n",
        version=1,
    )

    assert session.analyze(uri).version == 1
    assert [symbol.name for symbol in session.analyze(uri).symbols] == ["Inv", "symbol", "a"]

    session.update_document(uri, "cell Inv:\n    viewgen symbol(\n", version=2)

    analysis = session.analyze(uri)
    assert analysis.version == 2
    assert analysis.diagnostics[0].code == "unexpected-token"
    assert [symbol.name for symbol in analysis.symbols] == ["Inv", "symbol", "a"]
    assert session.definition(uri, position_at("cell Inv:\n", "Inv"))["name"] == "Inv"

    session.close_document(uri)
    assert session.documents == {}


def test_analysis_error_snapshots_do_not_alias_last_good_analysis():
    session = AnalysisSession(workspace_root="/tmp/workspace")
    uri = "file:///tmp/snapshot.ord"
    session.open_document(
        uri,
        "cell Inv:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n",
        version=1,
    )

    good = session.analyze(uri)
    session.update_document(uri, "cell Inv:\n    viewgen symbol(\n", version=2)
    broken = session.analyze(uri)
    broken.symbols.clear()

    assert [symbol.name for symbol in good.symbols] == ["Inv", "symbol", "a"]
    assert [symbol.name for symbol in session.documents[uri]["last_good_analysis"].symbols] == [
        "Inv",
        "symbol",
        "a",
    ]


def test_python_index_find_spec_failures_are_unresolved(monkeypatch):
    index = PythonModuleIndex()

    def broken_find_spec(module_name):
        raise SystemExit("bad package")

    monkeypatch.setattr("importlib.util.find_spec", broken_find_spec)

    assert index.resolve_module_path("bad.package") is None
    assert not index.module_exists("bad.package")


def test_python_index_exports_select_name_ranges(tmp_path):
    (tmp_path / "devices.py").write_text(
        "class ExtLib:\n"
        "    pass\n"
    )

    definition = PythonModuleIndex(workspace_root=str(tmp_path)).definition(
        "devices",
        export_name="ExtLib",
    )

    assert definition["selection_range"].start.character == 7


def test_analysis_session_reports_core_semantic_diagnostics(tmp_path):
    (tmp_path / "helper.ord").write_text(
        "cell Other:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    source = (
        "from .missing import Foo\n"
        "from .helper import Missing\n"
        "from ordec.lib.generic_mos import Nmos\n"
        "\n"
        "cell Inv:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
        "    viewgen schematic -> Schematic:\n"
        "        port b: .align=West\n"
        "        ! b.pos.x == 0\n"
        "        MissingCell inst:\n"
        "            .x -- b\n"
        "        Nmos pd:\n"
        "            .missing -- b\n"
        "            .$bogus = 1u\n"
        "    viewgen bad -> Nmos:\n"
        "        pass\n"
    )

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


def test_analysis_session_resolves_ord_imports_and_exported_symbols(tmp_path):
    (tmp_path / "mux2.ord").write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    package_path = tmp_path / "ordcells"
    package_path.mkdir()
    (package_path / "__init__.ord").write_text(
        "cell Exported:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    top_source = (
        "from .mux2 import Mux2 as Stage\n"
        "from .ordcells import Exported\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic -> Schematic:\n"
        "        Stage child:\n"
        "            .a -- net_a\n"
        "        Exported exp:\n"
        "            .a -- net_a\n"
        "\n"
        "def helper(x=Stage):\n"
        "    return x\n"
    )
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


def test_analysis_session_resolves_ord_star_imports(tmp_path):
    (tmp_path / "mux2.ord").write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    star_source = (
        "from .mux2 import *\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic -> Schematic:\n"
        "        Mux2 child:\n"
        "            .a -- net_a\n"
    )
    star_path = tmp_path / "star_user.ord"
    star_path.write_text(star_source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    star_uri = session.open_path(str(star_path))

    assert session.diagnostics(star_uri) == []
    assert session.definition(star_uri, position_at(star_source, "Mux2 child"))["name"] == "Mux2"


def test_analysis_session_resolves_python_import_variants(tmp_path):
    (tmp_path / "counter_yosys.py").write_text(
        "class ExtLib:\n"
        "    pass\n"
        "\n"
        "def report_digital_design():\n"
        "    pass\n"
    )
    source = (
        "import math\n"
        "from counter_yosys import ExtLib, report_digital_design\n"
        "from ordec.layout import helpers\n"
        "from ordec.lib.generic_mos import Nmos\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic -> Schematic:\n"
        "        value = math.log(2)\n"
        "        Nmos m:\n"
        "            .d -- net_a\n"
        "\n"
        "def helper(x=ExtLib):\n"
        "    return helpers, report_digital_design\n"
    )
    path = tmp_path / "top.ord"
    path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(path))

    assert session.diagnostics(uri) == []
    assert session.resolve_name(uri, "ExtLib")["kind"] == "class"
    assert session.resolve_name(uri, "helpers")["kind"] == "module"
    assert session.definition(uri, position_at(source, "Nmos m"))["name"] == "Nmos"


def test_analysis_session_resolves_python_members_parameters_and_completions():
    source = (
        "from ordec.core import *\n"
        "from ordec.lib.generic_mos import Nmos\n"
        "\n"
        "cell Inv:\n"
        "    viewgen schematic -> Schematic:\n"
        "        net vss\n"
        "        Nmos pd:\n"
        "            .s -- vss\n"
        "            .pos = (0, 0)\n"
        "        pd.$l = 1u\n"
        "        for inst in (pd,):\n"
        "            inst.g -- vss\n"
    )
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


def test_analysis_session_resolves_parameterized_reused_symbol_members():
    source = (
        "from ordec.core import *\n"
        "from ordec.lib.ihp130 import Nmos\n"
        "\n"
        "cell Inv:\n"
        "    viewgen schematic -> Schematic:\n"
        "        net a, y, vss\n"
        "        Nmos(w=1u, l=130n) pd:\n"
        "            .g -- a\n"
        "            .d -- y\n"
        "            .s -- vss\n"
        "            .b -- vss\n"
    )
    session = AnalysisSession()
    uri = "file:///tmp/parameterized_reused_symbol.ord"
    session.open_document(uri, source)

    assert session.diagnostics(uri) == []
    assert session.definition(uri, position_at(source, "Nmos(w"))["name"] == "Nmos"
    assert session.definition(uri, position_at(source, "g --"))["name"] == "g"


def test_analysis_session_resolves_ord_cell_members_from_symbol_layout_and_self():
    source = (
        "from ordec.core import *\n"
        "\n"
        "cell Stage:\n"
        "    viewgen symbol -> Symbol:\n"
        "        output q\n"
        "    viewgen schematic -> Schematic:\n"
        "        return Schematic()\n"
        "    viewgen layout -> Layout:\n"
        "        local = self.schematic\n"
        "        LayoutRect bodybar\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic -> Schematic:\n"
        "        net out\n"
        "        Stage inst[0]:\n"
        "            .q -- out\n"
        "        inst[0].q -- out\n"
        "    viewgen layout -> Layout:\n"
        "        Stage lay:\n"
        "            ! .bodybar.width == 1\n"
    )
    session = AnalysisSession()
    uri = "file:///tmp/ord_members.ord"
    session.open_document(uri, source)

    assert session.diagnostics(uri) == []
    assert session.definition(uri, position_at(source, "schematic", 2))["name"] == "schematic"
    assert session.definition(uri, position_at(source, "q -- out"))["name"] == "q"
    assert session.definition(uri, position_at(source, "bodybar"))["name"] == "bodybar"


def test_analysis_session_resolves_relative_python_cell_instances(tmp_path):
    package_path = tmp_path / "pkg"
    ord_path = package_path / "ord"
    ord_path.mkdir(parents=True)
    (package_path / "__init__.py").write_text("")
    (ord_path / "__init__.py").write_text("")
    (package_path / "devices.py").write_text(
        "from ordec.core import *\n"
        "\n"
        "class DFF(Cell):\n"
        "    @generate\n"
        "    def symbol(self) -> Symbol:\n"
        "        s = Symbol(cell=self)\n"
        "        s.d = Pin()\n"
        "        s.q = Pin()\n"
        "        return s\n"
    )
    reg_path = ord_path / "reg.ord"
    reg_path.write_text(
        "from ordec.core import *\n"
        "from ..devices import DFF\n"
        "\n"
        "cell Reg:\n"
        "    bits = Parameter(int)\n"
        "    viewgen schematic -> Schematic:\n"
        "        path d\n"
        "        path I\n"
        "        for i in range(self.bits):\n"
        "            net d[i]\n"
        "            DFF I[i]:\n"
        "                .d -- d[i]\n"
        "                .q -- d[i]\n"
        "            I[i].pos = (6, 3 + 8 * i)\n"
        "            I[i].q -- d[i]\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(reg_path))

    assert session.diagnostics(uri) == []


def test_analysis_session_accepts_dynamic_ordb_and_factory_members():
    source = (
        "from ordec.core import *\n"
        "from ordec.sim import Simulator\n"
        "\n"
        "def helper():\n"
        "    root = Symbol()\n"
        "    with root.ctx():\n"
        "        input a\n"
        "        assert .a == a\n"
        "    assert root.a == a\n"
        "    assert root.all(Pin)\n"
        "    assert Pin().parent\n"
        "    return Simulator(SimHierarchy()).netlister\n"
    )
    session = AnalysisSession()
    uri = "file:///tmp/dynamic_runtime_patterns.ord"
    session.open_document(uri, source)

    assert session.diagnostics(uri) == []


def test_analysis_session_navigation_references_highlights_and_rename(tmp_path):
    mux_path = tmp_path / "mux2.ord"
    mux_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )
    source = (
        "from .mux2 import Mux2 as Stage\n"
        "\n"
        "def helper(x=Stage):\n"
        "    return Stage\n"
    )
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


def test_analysis_session_python_scope_constructs_resolve_locally(tmp_path):
    source = (
        "def helper(items, value):\n"
        "    left, right = value\n"
        "    for idx, pin in items:\n"
        "        current = pin\n"
        "    with open('x') as handle:\n"
        "        data = handle.read()\n"
        "    try:\n"
        "        raise ValueError(data)\n"
        "    except ValueError as exc:\n"
        "        return left, right, idx, pin, handle, exc\n"
    )
    path = tmp_path / "scopes.ord"
    path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = path.resolve().as_uri()

    for name in ("left", "right", "idx", "pin", "handle", "exc"):
        definition = session.definition(uri, position_at(source, name, 2))
        assert definition["name"] == name
        assert definition["uri"] == uri

    assert "current" in completion_labels(session, uri, position_at(source, "return"))


def test_analysis_session_assignment_targets_do_not_create_fake_bindings(tmp_path):
    source = (
        "def helper(idx, value):\n"
        "    unknown[idx] = value\n"
        "    target.field = value\n"
        "    return idx, unknown, target\n"
    )
    path = tmp_path / "assignment_targets.ord"
    path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = path.resolve().as_uri()

    assert session.definition(uri, position_at(source, "idx]"))["name"] == "idx"
    assert session.definition(uri, position_at(source, "unknown", 2)) is None
    assert session.definition(uri, position_at(source, "target", 2)) is None


def test_analysis_session_workspace_cache_and_document_features(tmp_path):
    source = (
        "import math\n"
        "\n"
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
        "\n"
        "def helper():\n"
        "    .align = East\n"
        "    return math\n"
    )
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


def test_analysis_session_refreshes_dirty_workspace_rows_without_rescan(tmp_path, monkeypatch):
    (tmp_path / "a.ord").write_text(
        "cell A:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    (tmp_path / "b.ord").write_text(
        "cell B:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    path = tmp_path / "top.ord"
    source = (
        "from .a import A\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic -> Schematic:\n"
        "        A inst:\n"
        "            .a -- net_a\n"
    )
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


def test_analysis_session_analyzes_unopened_file_uris(tmp_path):
    source = (
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
        "\n"
        "def helper():\n"
        "    return Mux2\n"
    )
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


def test_analysis_session_simulation_alias_resolves_like_schema_type():
    source = (
        "from ordec.core import *\n"
        "\n"
        "cell Tb:\n"
        "    viewgen sim -> Simulation:\n"
        "        pass\n"
    )
    session = AnalysisSession()
    uri = "file:///tmp/sim_alias.ord"
    session.open_document(uri, source)

    assert session.diagnostics(uri) == []
    assert session.definition(uri, position_at(source, "Simulation"))["name"] == "SimHierarchy"


def test_file_uri_to_path_strips_windows_drive_prefix():
    for uri in ("file:///C:/designs/inv.ord", "file:///c%3A/designs/inv.ord"):
        path = file_uri_to_path(uri)
        assert not str(path).startswith(("/C:", "/c:"))
        assert str(path).endswith(":/designs/inv.ord")

    assert str(file_uri_to_path("file:///tmp/inv.ord")) == "/tmp/inv.ord"
    assert file_uri_to_path("untitled:Untitled-1") is None


def test_document_lines_cache_follows_document_updates():
    session = AnalysisSession()
    uri = "file:///tmp/lines.ord"
    session.open_document(uri, "net a\nnet b\n")

    lines = session.document_lines(uri)
    assert lines == ["net a", "net b"]
    assert session.document_lines(uri) is lines

    session.update_document(uri, "net a\nnet b\nnet c\n")
    assert session.document_lines(uri) == ["net a", "net b", "net c"]
    assert session.document_lines("file:///tmp/untracked.ord") is None

    session.update_document(uri, "net a\u2028b\nnet c\n")
    assert session.document_lines(uri) == ["net a\u2028b", "net c"]


def test_workspace_scan_skips_undecodable_files(tmp_path):
    (tmp_path / "good.ord").write_text(
        "cell Inv:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    (tmp_path / "bad.ord").write_bytes(b"cell Caf\xe9:\n")

    session = AnalysisSession(workspace_root=str(tmp_path))

    assert session.workspace_uris() == [(tmp_path / "good.ord").as_uri()]
    assert session.ensure_document((tmp_path / "bad.ord").as_uri()) is False


def test_rename_refuses_python_defined_symbols(tmp_path):
    (tmp_path / "extlib.py").write_text(
        "class Stage:\n"
        "    pass\n"
    )
    source = (
        "from extlib import Stage\n"
        "\n"
        "def helper(x=Stage):\n"
        "    return x\n"
    )
    path = tmp_path / "top.ord"
    path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(path))
    position = position_at(source, "Stage", occurrence=2)

    assert session.definition(uri, position)["uri"].endswith("extlib.py")
    assert session.prepare_rename(uri, position) is None
    assert session.rename(uri, position, "Driver") is None


def test_session_uris_preserve_symlinked_workspace_spelling(tmp_path):
    real_root = tmp_path / "real"
    real_root.mkdir()
    (real_root / "top.ord").write_text(
        "cell Inv:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root)

    session = AnalysisSession(workspace_root=str(linked_root))
    uri = (linked_root / "top.ord").as_uri()

    assert session.canonical_uri(uri) == uri
    assert session.workspace_uris() == [uri]


def test_import_member_resolves_ord_submodules(tmp_path):
    package_path = tmp_path / "pkg"
    package_path.mkdir()
    (package_path / "__init__.ord").write_text("")
    (package_path / "sub.ord").write_text(
        "cell Inner:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    top_path = tmp_path / "top.ord"
    source = "from .pkg import sub\n"
    top_path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(top_path))

    assert session.diagnostics(uri) == []
    assert session.definition(uri, position_at(source, "sub"))["uri"] == (
        package_path / "sub.ord"
    ).as_uri()


def test_absolute_imports_resolve_against_document_directory(tmp_path):
    sub_path = tmp_path / "sub"
    sub_path.mkdir()
    (sub_path / "lib.ord").write_text(
        "cell Inv:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    top_source = "from lib import Inv\n"
    top_path = sub_path / "top.ord"
    top_path.write_text(top_source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    lib_uri = session.open_path(str(sub_path / "lib.ord"))
    top_uri = session.open_path(str(top_path))

    # The runtime importer searches the script's own directory, so the
    # sibling import must resolve and appear in the import graph.
    assert session.diagnostics(top_uri) == []
    assert session.definition(top_uri, position_at(top_source, "Inv"))["uri"] == lib_uri
    assert top_uri in session.workspace_dependents(lib_uri)


def test_dots_only_import_prefers_package_over_sibling_module(tmp_path):
    sub_path = tmp_path / "sub"
    sub_path.mkdir()
    (tmp_path / "sub.ord").write_text("cell Decoy:\n    pass\n")
    (sub_path / "__init__.ord").write_text("cell Inner:\n    pass\n")
    top_source = "from . import Inner\n"
    top_path = sub_path / "top.ord"
    top_path.write_text(top_source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    init_uri = session.open_path(str(sub_path / "__init__.ord"))
    top_uri = session.open_path(str(top_path))

    # "from . import X" names the package, never the sibling sub.ord.
    assert session.diagnostics(top_uri) == []
    assert session.definition(top_uri, position_at(top_source, "Inner"))["uri"] == init_uri


def test_python_index_resolves_init_ord_packages(tmp_path, monkeypatch):
    package_path = tmp_path / "pkg"
    package_path.mkdir()
    init_path = package_path / "__init__.ord"
    init_path.write_text("")
    sub_path = package_path / "sub.ord"
    sub_path.write_text("cell Inner:\n    pass\n")

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


def test_python_export_name_ranges_avoid_keywords(tmp_path):
    (tmp_path / "shortnames.py").write_text(
        "def f(x):\n"
        "    return x\n"
        "\n"
        "class C:\n"
        "    def d(self):\n"
        "        pass\n"
    )
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


def test_missing_port_action_survives_stale_analysis():
    session = AnalysisSession(workspace_root="/tmp/workspace")
    uri = "file:///tmp/stale.ord"
    session.open_document(
        uri,
        "cell Inv:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
        "        input b\n",
        version=1,
    )
    session.analyze(uri)
    session.update_document(uri, "cell Inv:\n    viewgen symbol(\n", version=2)
    session.analyze(uri)

    diagnostic = {
        "range": {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 0},
        },
        "data": {"portName": "c"},
    }
    server = OrdLanguageServer()
    server.session = session
    action = server.missing_symbol_port_action(uri, diagnostic)
    assert "input c" in action["edit"]["changes"][uri][0]["newText"]


def test_workspace_rename_updates_cell_members_and_refuses_stale_ranges(tmp_path):
    mux_source = (
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    mux_path = tmp_path / "mux2.ord"
    mux_path.write_text(mux_source)
    top_source = (
        "from .mux2 import Mux2\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic -> Schematic:\n"
        "        net n1\n"
        "        Mux2 inst:\n"
        "            .a -- n1\n"
    )
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


def test_rename_refuses_stale_sources_and_unaliased_dotted_imports(tmp_path):
    session = AnalysisSession()
    uri = "file:///tmp/stale_rename.ord"
    source = (
        "def helper():\n"
        "    value = 1\n"
        "    return value\n"
    )
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
    import_source = (
        "import pkg.sub\n"
        "import pkg.sub as module_alias\n"
        "\n"
        "def helper():\n"
        "    return pkg, module_alias\n"
    )
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


def test_dotted_viewgen_return_types_resolve_and_allow_constraints(tmp_path):
    (tmp_path / "viewlib.py").write_text(
        "class CustomView:\n"
        "    def view_context(self):\n"
        "        pass\n"
    )
    source = (
        "from ordec import core\n"
        "import viewlib\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic -> core.Schematic:\n"
        "        net n1\n"
        "        net n2\n"
        "        ! n1 == n2\n"
        "    viewgen custom -> viewlib.CustomView:\n"
        "        pass\n"
    )
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


def test_rename_preserves_alias_of_aliased_from_import(tmp_path):
    lib_source = (
        "cell Inv:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    lib_path = tmp_path / "lib.ord"
    lib_path.write_text(lib_source)
    top_source = (
        "from lib import Inv as I\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic -> Schematic:\n"
        "        net n1\n"
        "        I inst:\n"
        "            .a -- n1\n"
    )
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


def test_node_kind_subtrees_and_comprehensions_track_bindings():
    source = (
        "def helper(width, lib, items):\n"
        "    values = [item for item in items if item]\n"
        "    Res(r=width) r1:\n"
        "        pass\n"
        "    lib.Inv i1:\n"
        "        pass\n"
        "    return values\n"
    )
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


def test_relative_from_imports_resolve_exports_and_submodules(tmp_path):
    package_path = tmp_path / "pkg"
    package_path.mkdir()
    init_source = (
        "cell Root:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    (package_path / "__init__.ord").write_text(init_source)
    device_source = (
        "cell Device:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    device_path = package_path / "device.ord"
    device_path.write_text(device_source)
    source = (
        "from . import device\n"
        "from . import Root\n"
        "\n"
        "def helper():\n"
        "    return device, Root\n"
    )
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


def test_unreadable_imports_and_excess_relative_dots_do_not_crash(tmp_path):
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


def test_decorated_exports_and_forward_module_constants_resolve(tmp_path):
    library_source = (
        "@decorator\n"
        "cell Decorated:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    (tmp_path / "library.ord").write_text(library_source)
    source = (
        "from .library import Decorated\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic -> Schematic:\n"
        "        net d[WIDTH]\n"
        "        Decorated inst:\n"
        "            .a -- d[0]\n"
        "\n"
        "WIDTH = 4\n"
    )
    path = tmp_path / "top.ord"
    path.write_text(source)

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(path))

    assert session.diagnostics(uri) == []


def test_indexed_member_navigation_and_nested_completion_contexts():
    source = (
        "from ordec.core import *\n"
        "\n"
        "cell Stage:\n"
        "    viewgen symbol -> Symbol:\n"
        "        output q\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic -> Schematic:\n"
        "        net out\n"
        "        path I\n"
        "        Stage I[0]:\n"
        "            .q -- out\n"
        "        I[0].q -- out\n"
    )
    session = AnalysisSession()
    uri = "file:///tmp/indexed_member.ord"
    session.open_document(uri, source, version=1)

    definition = session.definition(uri, position_at(source, "q -- out", occurrence=2))
    assert definition["name"] == "q"

    completion_source = (
        "from ordec.lib.generic_mos import Nmos\n"
        "\n"
        "def helper():\n"
        "    pd = Nmos()\n"
        "    return pd.d\n"
    )
    completion_uri = "file:///tmp/nested_completion.ord"
    session.open_document(completion_uri, completion_source, version=1)
    edited = completion_source.replace("pd.d\n", "pd.d.\n")
    session.update_document(completion_uri, edited, version=2)

    assert session.completions(
        completion_uri,
        position_after(edited, "pd.d."),
    ) == []


def test_lambda_parenthesized_with_and_except_star_bindings():
    source = (
        "def helper(factory):\n"
        "    callback = lambda first, *, second=1, **kwargs: first + second + kwargs[\"x\"]\n"
        "    with (factory()) as handle:\n"
        "        local = handle\n"
        "    with (factory() as first_handle, factory()) as group:\n"
        "        pair = first_handle, group\n"
        "    try:\n"
        "        pass\n"
        "    except* ValueError as grouped:\n"
        "        error = grouped\n"
        "    return callback, handle, first_handle, group, grouped\n"
    )
    session = AnalysisSession()
    uri = "file:///tmp/scope_variants.ord"
    session.open_document(uri, source)

    for name in ("first", "second", "kwargs"):
        definition = session.definition(uri, position_at(source, name, occurrence=2))
        assert definition["name"] == name
        assert definition["kind"] == "parameter"
    for name in ("handle", "first_handle", "group", "grouped"):
        assert session.definition(uri, position_at(source, name, occurrence=2))["name"] == name


def test_python_index_parse_errors_reexports_and_ord_invalidation(tmp_path, monkeypatch):
    (tmp_path / "broken.py").write_text("VALUE = 1\n")
    index = PythonModuleIndex(workspace_root=str(tmp_path))

    def invalid_tree(*args, **kwargs):
        raise ValueError("source contains null bytes")

    with monkeypatch.context() as context:
        context.setattr("ast.parse", invalid_tree)
        assert index.module_info("broken") is None

    first_path = tmp_path / "first.py"
    first_path.write_text("class Choice:\n    pass\n")
    second_path = tmp_path / "second.py"
    second_path.write_text("class Choice:\n    pass\n")
    (tmp_path / "bridge.py").write_text(
        "from first import Choice as Selected\n"
        "from second import Choice as Selected\n"
    )
    index = PythonModuleIndex(workspace_root=str(tmp_path))
    assert index.definition("bridge", export_name="Selected")["uri"] == second_path.as_uri()

    ord_path = tmp_path / "celllib.ord"
    ord_path.write_text("cell Old:\n    pass\n")
    session = AnalysisSession(workspace_root=str(tmp_path))
    assert "Old" in session.python_module_info("celllib")["exports"]
    ord_path.write_text("cell New:\n    pass\n")
    session.invalidate_path(str(ord_path))
    assert set(session.python_module_info("celllib")["exports"]) == {"New"}


def test_new_workspace_file_rebuilds_import_dependents(tmp_path):
    top_path = tmp_path / "top.ord"
    top_path.write_text("from .new_cell import NewCell\n")
    session = AnalysisSession(workspace_root=str(tmp_path))
    top_uri = session.open_path(str(top_path))
    assert session.workspace_import_index()["imports"][top_uri] == set()

    new_path = tmp_path / "new_cell.ord"
    new_path.write_text("cell NewCell:\n    pass\n")
    new_uri = session.invalidate_path(str(new_path))

    assert session.workspace_dependents(new_uri) == {top_uri}


def test_analysis_session_checked_in_ord_files_have_no_lsp_diagnostics():
    root_path = Path(__file__).resolve().parents[1]
    session = AnalysisSession(workspace_root=str(root_path))

    # Runtime-error tests deliberately contain invalid constructs inside
    # pytest.raises blocks, which the analyzer rightly diagnoses.
    expected_codes = {
        "tests/test_ord_runtime.ord": {"unknown-member"},
    }

    # Enumerate via the session's own scanner so the file set stays in
    # sync with what the workspace scan actually indexes.
    for path in session.workspace_ord_paths(root_path):
        relative_path = str(path.relative_to(root_path))
        uri = session.open_path(str(path))
        diagnostics = [
            diagnostic for diagnostic in session.diagnostics(uri)
            if diagnostic.code not in expected_codes.get(relative_path, set())
        ]
        assert diagnostics == [], relative_path
