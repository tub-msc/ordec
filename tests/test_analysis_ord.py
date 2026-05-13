# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from ordec.analysis import AnalysisPosition
from ordec.analysis import AnalysisSession
from ordec.analysis import analyze_ord


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
        "invalid-constraint-context",
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
    assert len(session.references(uri, position)) == 4
    assert len(session.document_highlights(uri, position)) == 3
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


def test_analysis_session_checked_in_ord_files_have_no_lsp_diagnostics():
    root_path = Path(__file__).resolve().parents[1]
    session = AnalysisSession(workspace_root=str(root_path))

    for path in sorted(root_path.rglob("*.ord")):
        if any(part.startswith(".") for part in path.relative_to(root_path).parts):
            continue
        uri = session.open_path(str(path))
        assert session.diagnostics(uri) == [], str(path.relative_to(root_path))
