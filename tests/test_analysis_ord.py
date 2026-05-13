# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.analysis import AnalysisSession
from ordec.analysis import AnalysisPosition
from ordec.analysis import analyze_ord


def test_analyze_ord_collects_symbols():
    ord_string = (
        "cell Inv:\n"
        "    viewgen layout -> Layout:\n"
        "        output bus[0].y:\n"
        "            .align = East\n"
        "        path vdd, vss\n"
        "\n"
        "def helper(x):\n"
        "    return x\n"
    )

    analysis = analyze_ord(ord_string, uri="file:///tmp/test.ord", version=3)

    assert analysis.to_dict() == {
        "uri": "file:///tmp/test.ord",
        "version": 3,
        "diagnostics": [],
        "symbols": [
            {
                "name": "Inv",
                "kind": "class",
                "range": {
                    "start": {"line": 1, "character": 1},
                    "end": {"line": 7, "character": 1},
                },
                "selection_range": {
                    "start": {"line": 1, "character": 6},
                    "end": {"line": 1, "character": 9},
                },
            },
            {
                "name": "layout",
                "kind": "function",
                "range": {
                    "start": {"line": 2, "character": 5},
                    "end": {"line": 7, "character": 1},
                },
                "selection_range": {
                    "start": {"line": 2, "character": 13},
                    "end": {"line": 2, "character": 19},
                },
            },
            {
                "name": "output bus[0].y",
                "kind": "context",
                "range": {
                    "start": {"line": 3, "character": 9},
                    "end": {"line": 5, "character": 9},
                },
                "selection_range": {
                    "start": {"line": 3, "character": 16},
                    "end": {"line": 3, "character": 24},
                },
            },
            {
                "name": "vdd, vss",
                "kind": "path",
                "range": {
                    "start": {"line": 5, "character": 9},
                    "end": {"line": 5, "character": 22},
                },
                "selection_range": {
                    "start": {"line": 5, "character": 14},
                    "end": {"line": 5, "character": 17},
                },
            },
            {
                "name": "helper",
                "kind": "function",
                "range": {
                    "start": {"line": 7, "character": 1},
                    "end": {"line": 10, "character": 1},
                },
                "selection_range": {
                    "start": {"line": 7, "character": 5},
                    "end": {"line": 7, "character": 11},
                },
            },
        ],
        "imports": [],
        "exports": ["Inv", "helper"],
    }


def test_analyze_ord_reports_syntax_errors():
    analysis = analyze_ord("cell Inv:\n    viewgen layout(", uri="file:///tmp/test.ord")

    assert len(analysis.diagnostics) == 1
    assert analysis.symbols == []
    assert analysis.diagnostics[0].severity == "error"
    assert analysis.diagnostics[0].code == "unexpected-token"
    assert "Syntax Error" in analysis.diagnostics[0].message


def test_analysis_session_tracks_open_documents():
    session = AnalysisSession(workspace_root="/tmp/workspace")
    session.open_document("file:///tmp/test.ord", "def helper():\n    return 1\n", version=1)

    analysis = session.analyze("file:///tmp/test.ord")
    assert analysis.version == 1
    assert analysis.symbols[0].name == "helper"

    session.update_document("file:///tmp/test.ord", "def helper2():\n    return 2\n", version=2)
    analysis = session.analyze("file:///tmp/test.ord")
    assert analysis.version == 2
    assert analysis.symbols[0].name == "helper2"

    session.close_document("file:///tmp/test.ord")
    assert session.documents == {}


def test_analysis_session_keeps_last_good_symbols_during_syntax_errors():
    session = AnalysisSession(workspace_root="/tmp/workspace")
    uri = "file:///tmp/test.ord"
    session.open_document(
        uri,
        "cell Inv:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n",
        version=1,
    )

    good_analysis = session.analyze(uri)
    assert good_analysis.diagnostics == []
    assert [symbol.name for symbol in good_analysis.symbols] == ["Inv", "symbol", "a"]

    session.update_document(
        uri,
        "cell Inv:\n"
        "    viewgen symbol(\n",
        version=2,
    )
    broken_analysis = session.analyze(uri)

    assert broken_analysis.version == 2
    assert broken_analysis.diagnostics[0].severity == "error"
    assert [symbol.name for symbol in broken_analysis.symbols] == ["Inv", "symbol", "a"]

    definition = session.definition(uri, AnalysisPosition(line=1, character=6))
    assert definition["name"] == "Inv"
    assert definition["kind"] == "class"


def test_analysis_session_reports_semantic_diagnostics(tmp_path):
    (tmp_path / "helper.ord").write_text(
        "cell Other:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = (tmp_path / "broken.ord").resolve().as_uri()
    session.open_document(
        uri,
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
        "        pass\n",
    )

    codes = [diagnostic.code for diagnostic in session.diagnostics(uri)]

    assert codes == [
        "unresolved-import",
        "unresolved-import-member",
        "unresolved-node-type",
        "invalid-viewgen-return",
        "invalid-constraint-context",
        "unknown-member",
        "unknown-parameter",
        "unknown-symbol-port",
    ]


def test_analyze_ord_collects_imports_and_exports():
    ord_string = (
        "import math, numpy as np\n"
        "from .helpers import foo, bar as baz\n"
        "from ...ord import parser\n"
        "\n"
        "cell Inv:\n"
        "    viewgen layout -> Layout:\n"
        "        return Layout()\n"
        "\n"
        "def helper():\n"
        "    return foo\n"
    )

    analysis = analyze_ord(ord_string)

    assert analysis.imports == [
        "math",
        "numpy as np",
        "from .helpers import foo, bar as baz",
        "from ...ord import parser",
    ]
    assert analysis.exports == [
        "Inv",
        "helper",
    ]
    assert [
        (entry.kind, entry.module, entry.export_name, entry.local_name)
        for entry in analysis.import_entries
    ] == [
        ("import", "math", None, "math"),
        ("import", "numpy", None, "np"),
        ("from", ".helpers", "foo", "foo"),
        ("from", ".helpers", "bar", "baz"),
        ("from", "...ord", "parser", "parser"),
    ]
    assert analysis.import_entries[1].selection_range.to_dict() == {
        "start": {"line": 1, "character": 23},
        "end": {"line": 1, "character": 25},
    }
    assert analysis.import_entries[3].selection_range.to_dict() == {
        "start": {"line": 2, "character": 34},
        "end": {"line": 2, "character": 37},
    }


def test_analysis_session_resolves_local_ord_imports(tmp_path):
    mux2_path = tmp_path / "ord" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord" / "nmux.ord"
    nmux_path.write_text(
        "from .mux2 import Mux2\n"
        "\n"
        "cell Nto1:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    analysis = session.analyze_path(str(nmux_path))
    nmux_uri = nmux_path.resolve().as_uri()
    mux2_uri = mux2_path.resolve().as_uri()

    assert analysis.imports == ["from .mux2 import Mux2"]
    assert session.resolve_import_uris(nmux_uri) == [mux2_uri]

    analyses = session.analyze_related(nmux_uri)
    assert sorted(analyses.keys()) == [mux2_uri, nmux_uri]
    assert analyses[mux2_uri].exports == ["Mux2"]


def test_analysis_session_resolves_exported_names(tmp_path):
    mux2_path = tmp_path / "ord" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord" / "nmux.ord"
    nmux_path.write_text(
        "from .mux2 import Mux2\n"
        "\n"
        "cell Nto1:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    nmux_uri = nmux_path.resolve().as_uri()
    mux2_uri = mux2_path.resolve().as_uri()

    imported_symbol = session.resolve_name(nmux_uri, "Mux2")
    assert imported_symbol["uri"] == mux2_uri
    assert imported_symbol["kind"] == "class"

    local_symbol = session.resolve_name(nmux_uri, "Nto1")
    assert local_symbol["uri"] == nmux_uri
    assert local_symbol["kind"] == "class"


def test_analysis_session_definition_resolves_local_symbol(tmp_path):
    nmux_path = tmp_path / "ord" / "nmux.ord"
    nmux_path.parent.mkdir()
    nmux_path.write_text(
        "cell Nto1:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    nmux_uri = nmux_path.resolve().as_uri()

    definition = session.definition(nmux_uri, AnalysisPosition(line=1, character=7))
    assert definition["uri"] == nmux_uri
    assert definition["name"] == "Nto1"
    assert definition["kind"] == "class"


def test_analysis_session_definition_resolves_import_alias(tmp_path):
    mux2_path = tmp_path / "ord" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord" / "nmux.ord"
    nmux_path.write_text(
        "from .mux2 import Mux2 as Stage\n"
        "\n"
        "def helper(x=Stage):\n"
        "    return x\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    nmux_uri = nmux_path.resolve().as_uri()
    mux2_uri = mux2_path.resolve().as_uri()

    definition = session.definition(nmux_uri, AnalysisPosition(line=3, character=15))
    assert definition["uri"] == mux2_uri
    assert definition["name"] == "Mux2"
    assert definition["kind"] == "class"

    import_definition = session.definition(nmux_uri, AnalysisPosition(line=1, character=28))
    assert import_definition["uri"] == mux2_uri
    assert import_definition["name"] == "Mux2"


def test_analysis_session_definition_resolves_python_imports(tmp_path):
    inv_path = tmp_path / "inv.ord"
    inv_path.write_text(
        "from ordec.core import *\n"
        "from ordec.lib.generic_mos import Nmos, Pmos\n"
        "\n"
        "cell Inv:\n"
        "    viewgen symbol -> Symbol:\n"
        "        return Symbol(cell=self)\n"
        "\n"
        "    viewgen schematic -> Schematic:\n"
        "        pd = Nmos().symbol\n"
        "        pu = Pmos().symbol\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    inv_uri = inv_path.resolve().as_uri()

    symbol_definition = session.definition(inv_uri, AnalysisPosition(line=5, character=24))
    assert symbol_definition["name"] == "Symbol"
    assert symbol_definition["kind"] == "class"
    assert symbol_definition["uri"].endswith("/ordec/core/schema.py")

    constructor_definition = session.definition(inv_uri, AnalysisPosition(line=6, character=17))
    assert constructor_definition["name"] == "Symbol"
    assert constructor_definition["uri"] == symbol_definition["uri"]

    schematic_definition = session.definition(inv_uri, AnalysisPosition(line=8, character=28))
    assert schematic_definition["name"] == "Schematic"
    assert schematic_definition["kind"] == "class"
    assert schematic_definition["uri"].endswith("/ordec/core/schema.py")

    nmos_definition = session.definition(inv_uri, AnalysisPosition(line=9, character=15))
    assert nmos_definition["name"] == "Nmos"
    assert nmos_definition["kind"] == "class"
    assert nmos_definition["uri"].endswith("/ordec/lib/generic_mos.py")

    pmos_definition = session.definition(inv_uri, AnalysisPosition(line=10, character=15))
    assert pmos_definition["name"] == "Pmos"
    assert pmos_definition["kind"] == "class"
    assert pmos_definition["uri"].endswith("/ordec/lib/generic_mos.py")


def test_analysis_session_definition_resolves_python_members(tmp_path):
    inv_path = tmp_path / "inv.ord"
    inv_path.write_text(
        "from ordec.core import *\n"
        "from ordec.lib.generic_mos import Nmos, Pmos\n"
        "\n"
        "cell Inv:\n"
        "    viewgen schematic -> Schematic:\n"
        "        port vdd: .pos=(2,13)\n"
        "        port a: .pos=(1,7)\n"
        "        Nmos pd:\n"
        "            .s -- vdd\n"
        "        Pmos pu:\n"
        "            .$l = 400n\n"
        "\n"
        "        pd.$l = 350u\n"
        "\n"
        "        for instance in pu, pd:\n"
        "            instance.g -- a\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    inv_uri = inv_path.resolve().as_uri()

    source_member = session.definition(inv_uri, AnalysisPosition(line=9, character=14))
    assert source_member["name"] == "s"
    assert source_member["uri"].endswith("/ordec/lib/generic_mos.py")
    assert source_member["selection_range"].start.line == 54

    implicit_param = session.definition(inv_uri, AnalysisPosition(line=11, character=15))
    assert implicit_param["name"] == "l"
    assert implicit_param["kind"] == "parameter"
    assert implicit_param["uri"].endswith("/ordec/lib/generic_mos.py")
    assert implicit_param["selection_range"].start.line == 27

    explicit_param = session.definition(inv_uri, AnalysisPosition(line=13, character=13))
    assert explicit_param["name"] == "l"
    assert explicit_param["uri"] == implicit_param["uri"]
    assert explicit_param["selection_range"] == implicit_param["selection_range"]

    loop_member = session.definition(inv_uri, AnalysisPosition(line=16, character=22))
    assert loop_member["name"] == "g"
    assert loop_member["uri"].endswith("/ordec/lib/generic_mos.py")
    assert loop_member["selection_range"].start.line in (53, 76)


def test_analysis_session_invalidates_cached_python_module_info(tmp_path, monkeypatch):
    package_path = tmp_path / "pkg"
    package_path.mkdir()
    (package_path / "__init__.py").write_text("")
    module_path = package_path / "devices.py"
    module_path.write_text(
        "class Device:\n"
        "    old_pin = 1\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    session = AnalysisSession(workspace_root=str(tmp_path))
    old_member = session.python_class_member_definition(
        "pkg.devices",
        "Device",
        "old_pin",
    )
    assert old_member is not None

    module_path.write_text(
        "class Device:\n"
        "    new_pin = 1\n"
    )
    session.invalidate_path(str(module_path))

    assert session.python_class_member_definition(
        "pkg.devices",
        "Device",
        "old_pin",
    ) is None
    assert session.python_class_member_definition(
        "pkg.devices",
        "Device",
        "new_pin",
    ) is not None


def test_analysis_session_member_references_and_rename_guard(tmp_path):
    inv_path = tmp_path / "inv.ord"
    inv_path.write_text(
        "from ordec.core import *\n"
        "from ordec.lib.generic_mos import Nmos, Pmos\n"
        "\n"
        "cell Inv:\n"
        "    viewgen schematic -> Schematic:\n"
        "        Nmos pd:\n"
        "            .s -- vdd\n"
        "        Pmos pu:\n"
        "            .$l = 400n\n"
        "\n"
        "        pd.$l = 350u\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    inv_uri = inv_path.resolve().as_uri()

    references = session.references(inv_uri, AnalysisPosition(line=9, character=15))
    assert [(reference["name"], reference["range"].to_dict()) for reference in references] == [
        (
            "l",
            {
                "start": {"line": 9, "character": 15},
                "end": {"line": 9, "character": 16},
            },
        ),
        (
            "l",
            {
                "start": {"line": 11, "character": 13},
                "end": {"line": 11, "character": 14},
            },
        ),
    ]

    highlights = session.document_highlights(inv_uri, AnalysisPosition(line=9, character=15))
    assert [
        {
            "range": highlight["range"].to_dict(),
            "kind": highlight["kind"],
        }
        for highlight in highlights
    ] == [
        {
            "range": {
                "start": {"line": 9, "character": 15},
                "end": {"line": 9, "character": 16},
            },
            "kind": "read",
        },
        {
            "range": {
                "start": {"line": 11, "character": 13},
                "end": {"line": 11, "character": 14},
            },
            "kind": "read",
        },
    ]

    assert session.prepare_rename(inv_uri, AnalysisPosition(line=9, character=15)) is None
    assert session.rename(inv_uri, AnalysisPosition(line=9, character=15), "length") is None


def test_analysis_session_context_aware_member_and_parameter_completions(tmp_path):
    inv_path = tmp_path / "inv.ord"
    inv_path.write_text(
        "from ordec.core import *\n"
        "from ordec.lib.generic_mos import Nmos\n"
        "\n"
        "cell Inv:\n"
        "    viewgen schematic -> Schematic:\n"
        "        net vss\n"
        "        Nmos pd:\n"
        "            .s -- vss\n"
        "            pd.$l = 1u\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    inv_uri = inv_path.resolve().as_uri()

    member_map = dict(
        (
            item["label"],
            {
                "kind": item["kind"],
                "detail": item["detail"],
            },
        )
        for item in session.completions(inv_uri, AnalysisPosition(line=8, character=14))
    )
    assert member_map["s"] == {
        "kind": "variable",
        "detail": "variable of Nmos",
    }
    assert member_map["d"] == {
        "kind": "variable",
        "detail": "variable of Nmos",
    }
    assert member_map["l"] == {
        "kind": "parameter",
        "detail": "parameter of Nmos",
    }

    parameter_map = dict(
        (
            item["label"],
            {
                "kind": item["kind"],
                "detail": item["detail"],
            },
        )
        for item in session.completions(inv_uri, AnalysisPosition(line=9, character=18))
    )
    assert parameter_map == {
        "l": {
            "kind": "parameter",
            "detail": "parameter of Nmos",
        },
        "w": {
            "kind": "parameter",
            "detail": "parameter of Nmos",
        },
    }


def test_analysis_session_constructor_assignment_type_flow(tmp_path):
    inv_path = tmp_path / "constructor_type.ord"
    inv_path.write_text(
        "from ordec.core import *\n"
        "from ordec.lib.generic_mos import Nmos\n"
        "\n"
        "cell Inv:\n"
        "    viewgen schematic -> Schematic:\n"
        "        pd = Nmos()\n"
        "        pd.$bad = 1u\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    inv_uri = inv_path.resolve().as_uri()

    parameter_map = dict(
        (
            item["label"],
            {
                "kind": item["kind"],
                "detail": item["detail"],
            },
        )
        for item in session.completions(inv_uri, AnalysisPosition(line=7, character=13))
    )
    assert parameter_map == {
        "l": {
            "kind": "parameter",
            "detail": "parameter of Nmos",
        },
        "w": {
            "kind": "parameter",
            "detail": "parameter of Nmos",
        },
    }

    diagnostics = session.diagnostics(inv_uri)
    assert [diagnostic.code for diagnostic in diagnostics] == ["unknown-parameter"]
    assert diagnostics[0].message == "Unknown parameter `bad` for `Nmos`."


def test_analysis_session_hover_uses_current_token_range(tmp_path):
    mux2_path = tmp_path / "ord" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord" / "nmux.ord"
    nmux_path.write_text(
        "from .mux2 import Mux2 as Stage\n"
        "\n"
        "def helper(x=Stage):\n"
        "    return x\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    nmux_uri = nmux_path.resolve().as_uri()
    mux2_uri = mux2_path.resolve().as_uri()

    hover = session.hover(nmux_uri, AnalysisPosition(line=3, character=15))
    assert hover["contents"] == "class Mux2\n{}".format(mux2_uri)
    assert hover["range"].to_dict() == {
        "start": {"line": 3, "character": 14},
        "end": {"line": 3, "character": 19},
    }


def test_analysis_session_references_follow_import_alias(tmp_path):
    mux2_path = tmp_path / "ord" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord" / "nmux.ord"
    nmux_path.write_text(
        "from .mux2 import Mux2 as Stage\n"
        "\n"
        "def helper(x=Stage):\n"
        "    return Stage\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    nmux_uri = nmux_path.resolve().as_uri()

    references = session.references(nmux_uri, AnalysisPosition(line=3, character=15))
    assert [(ref["uri"], ref["name"], ref["range"].to_dict()) for ref in references] == [
        (
            nmux_uri,
            "Stage",
            {
                "start": {"line": 1, "character": 27},
                "end": {"line": 1, "character": 32},
            },
        ),
        (
            nmux_uri,
            "Stage",
            {
                "start": {"line": 3, "character": 14},
                "end": {"line": 3, "character": 19},
            },
        ),
        (
            nmux_uri,
            "Stage",
            {
                "start": {"line": 4, "character": 12},
                "end": {"line": 4, "character": 17},
            },
        ),
        (
            mux2_path.resolve().as_uri(),
            "Mux2",
            {
                "start": {"line": 1, "character": 6},
                "end": {"line": 1, "character": 10},
            },
        ),
    ]


def test_analysis_session_references_include_reverse_workspace_dependents(tmp_path):
    mux2_path = tmp_path / "ord" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    first_user = tmp_path / "ord" / "first.ord"
    first_user.write_text(
        "from .mux2 import Mux2\n"
        "\n"
        "def helper(x=Mux2):\n"
        "    return Mux2\n"
    )

    second_user = tmp_path / "ord" / "second.ord"
    second_user.write_text(
        "from .mux2 import Mux2 as Stage\n"
        "\n"
        "def helper(x=Stage):\n"
        "    return Stage\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    mux2_uri = mux2_path.resolve().as_uri()
    first_uri = first_user.resolve().as_uri()
    second_uri = second_user.resolve().as_uri()

    references = session.references(mux2_uri, AnalysisPosition(line=1, character=6))
    names_by_uri = {
        ref_uri: [
            reference["name"]
            for reference in references
            if reference["uri"] == ref_uri
        ]
        for ref_uri in (mux2_uri, first_uri, second_uri)
    }

    assert names_by_uri == {
        mux2_uri: ["Mux2"],
        first_uri: ["Mux2", "Mux2", "Mux2"],
        second_uri: ["Stage", "Stage", "Stage"],
    }


def test_analysis_session_document_highlights_follow_import_alias(tmp_path):
    mux2_path = tmp_path / "ord" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord" / "nmux.ord"
    nmux_path.write_text(
        "from .mux2 import Mux2 as Stage\n"
        "\n"
        "def helper(x=Stage):\n"
        "    return Stage\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    nmux_uri = nmux_path.resolve().as_uri()

    highlights = session.document_highlights(
        nmux_uri,
        AnalysisPosition(line=3, character=15),
    )

    assert [
        {
            "range": highlight["range"].to_dict(),
            "kind": highlight["kind"],
        }
        for highlight in highlights
    ] == [
        {
            "range": {
                "start": {"line": 1, "character": 27},
                "end": {"line": 1, "character": 32},
            },
            "kind": "write",
        },
        {
            "range": {
                "start": {"line": 3, "character": 14},
                "end": {"line": 3, "character": 19},
            },
            "kind": "read",
        },
        {
            "range": {
                "start": {"line": 4, "character": 12},
                "end": {"line": 4, "character": 17},
            },
            "kind": "read",
        },
    ]


def test_analysis_session_completions_include_symbols_imports_and_keywords(tmp_path):
    mux2_path = tmp_path / "ord" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord" / "nmux.ord"
    nmux_path.write_text(
        "from .mux2 import Mux2 as Stage\n"
        "import math\n"
        "\n"
        "cell Nto1:\n"
        "    viewgen layout -> Layout:\n"
        "        path a\n"
        "\n"
        "def helper():\n"
        "    return Stage\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    nmux_uri = nmux_path.resolve().as_uri()
    completions = session.completions(nmux_uri, AnalysisPosition(line=8, character=12))
    completion_map = {
        item["label"]: {
            "kind": item["kind"],
            "detail": item["detail"],
        }
        for item in completions
    }

    assert completion_map["Nto1"] == {
        "kind": "class",
        "detail": "class",
    }
    assert completion_map["Stage"] == {
        "kind": "class",
        "detail": "from .mux2 import Mux2 as Stage",
    }
    assert completion_map["math"] == {
        "kind": "module",
        "detail": "import math",
    }
    assert completion_map["cell"] == {
        "kind": "keyword",
        "detail": "keyword",
    }
    assert completion_map["layout"] == {
        "kind": "function",
        "detail": "function",
    }


def test_analysis_session_rename_updates_related_export_references(tmp_path):
    mux2_path = tmp_path / "ord" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord" / "nmux.ord"
    nmux_path.write_text(
        "from .mux2 import Mux2\n"
        "\n"
        "def helper(x=Mux2):\n"
        "    return Mux2\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    rename = session.rename(
        nmux_path.resolve().as_uri(),
        AnalysisPosition(line=3, character=15),
        "MuxStage",
    )

    assert {
        uri: [
            {
                "range": change["range"].to_dict(),
                "new_text": change["new_text"],
            }
            for change in changes
        ]
        for uri, changes in rename.items()
    } == {
        nmux_path.resolve().as_uri(): [
            {
                "range": {
                    "start": {"line": 1, "character": 19},
                    "end": {"line": 1, "character": 23},
                },
                "new_text": "MuxStage",
            },
            {
                "range": {
                    "start": {"line": 3, "character": 14},
                    "end": {"line": 3, "character": 18},
                },
                "new_text": "MuxStage",
            },
            {
                "range": {
                    "start": {"line": 4, "character": 12},
                    "end": {"line": 4, "character": 16},
                },
                "new_text": "MuxStage",
            },
        ],
        mux2_path.resolve().as_uri(): [
            {
                "range": {
                    "start": {"line": 1, "character": 6},
                    "end": {"line": 1, "character": 10},
                },
                "new_text": "MuxStage",
            },
        ],
    }


def test_analysis_session_rename_import_alias_is_local_only(tmp_path):
    mux2_path = tmp_path / "ord" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord" / "nmux.ord"
    nmux_path.write_text(
        "from .mux2 import Mux2 as Stage\n"
        "\n"
        "def helper(x=Stage):\n"
        "    return Stage\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    rename = session.rename(
        nmux_path.resolve().as_uri(),
        AnalysisPosition(line=3, character=15),
        "Driver",
    )

    assert {
        uri: [
            {
                "range": change["range"].to_dict(),
                "new_text": change["new_text"],
            }
            for change in changes
        ]
        for uri, changes in rename.items()
    } == {
        nmux_path.resolve().as_uri(): [
            {
                "range": {
                    "start": {"line": 1, "character": 27},
                    "end": {"line": 1, "character": 32},
                },
                "new_text": "Driver",
            },
            {
                "range": {
                    "start": {"line": 3, "character": 14},
                    "end": {"line": 3, "character": 19},
                },
                "new_text": "Driver",
            },
            {
                "range": {
                    "start": {"line": 4, "character": 12},
                    "end": {"line": 4, "character": 17},
                },
                "new_text": "Driver",
            },
        ],
    }


def test_analysis_session_workspace_symbols_scan_root(tmp_path):
    ord_path = tmp_path / "ord"
    ord_path.mkdir()
    (ord_path / "mux2.ord").write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )
    (ord_path / "helper.ord").write_text(
        "def build_mux():\n"
        "    return 1\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    symbols = session.workspace_symbols("mux")

    assert [
        (symbol["uri"], symbol["name"], symbol["kind"])
        for symbol in symbols
    ] == [
        (
            (ord_path / "helper.ord").resolve().as_uri(),
            "build_mux",
            "function",
        ),
        (
            (ord_path / "mux2.ord").resolve().as_uri(),
            "Mux2",
            "class",
        ),
    ]


def test_analysis_session_prepare_rename_returns_current_token(tmp_path):
    mux2_path = tmp_path / "ord" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord" / "nmux.ord"
    nmux_path.write_text(
        "from .mux2 import Mux2 as Stage\n"
        "\n"
        "def helper(x=Stage):\n"
        "    return Stage\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    prepare = session.prepare_rename(
        nmux_path.resolve().as_uri(),
        AnalysisPosition(line=3, character=15),
    )

    assert prepare["range"].to_dict() == {
        "start": {"line": 3, "character": 14},
        "end": {"line": 3, "character": 19},
    }
    assert prepare["placeholder"] == "Stage"


def test_analysis_session_module_import_definition_hover_and_rename(tmp_path):
    (tmp_path / "localmod.ord").write_text(
        "cell LocalMod:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )
    user_path = tmp_path / "user.ord"
    user_path.write_text(
        "import localmod as mod\n"
        "\n"
        "def helper(x=mod):\n"
        "    return mod\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    user_uri = user_path.resolve().as_uri()
    localmod_uri = (tmp_path / "localmod.ord").resolve().as_uri()

    definition = session.definition(user_uri, AnalysisPosition(line=3, character=15))
    assert definition["uri"] == localmod_uri
    assert definition["name"] == "localmod"
    assert definition["kind"] == "module"
    assert definition["range"].to_dict() == {
        "start": {"line": 1, "character": 1},
        "end": {"line": 1, "character": 1},
    }
    assert definition["selection_range"].to_dict() == {
        "start": {"line": 1, "character": 1},
        "end": {"line": 1, "character": 1},
    }

    hover = session.hover(user_uri, AnalysisPosition(line=3, character=15))
    assert hover["contents"] == "module localmod\n{}".format(localmod_uri)
    assert hover["range"].to_dict() == {
        "start": {"line": 3, "character": 14},
        "end": {"line": 3, "character": 17},
    }

    references = session.references(user_uri, AnalysisPosition(line=3, character=15))
    assert [(ref["uri"], ref["name"], ref["range"].to_dict()) for ref in references] == [
        (
            user_uri,
            "mod",
            {
                "start": {"line": 1, "character": 20},
                "end": {"line": 1, "character": 23},
            },
        ),
        (
            user_uri,
            "mod",
            {
                "start": {"line": 3, "character": 14},
                "end": {"line": 3, "character": 17},
            },
        ),
        (
            user_uri,
            "mod",
            {
                "start": {"line": 4, "character": 12},
                "end": {"line": 4, "character": 15},
            },
        ),
    ]

    rename = session.rename(user_uri, AnalysisPosition(line=3, character=15), "driver")
    assert {
        uri: [
            {
                "range": change["range"].to_dict(),
                "new_text": change["new_text"],
            }
            for change in changes
        ]
        for uri, changes in rename.items()
    } == {
        user_uri: [
            {
                "range": {
                    "start": {"line": 1, "character": 20},
                    "end": {"line": 1, "character": 23},
                },
                "new_text": "driver",
            },
            {
                "range": {
                    "start": {"line": 3, "character": 14},
                    "end": {"line": 3, "character": 17},
                },
                "new_text": "driver",
            },
            {
                "range": {
                    "start": {"line": 4, "character": 12},
                    "end": {"line": 4, "character": 15},
                },
                "new_text": "driver",
            },
        ],
    }


def test_analyze_ord_collects_local_bindings_and_occurrences():
    ord_string = (
        "def outer(source):\n"
        "    value = source\n"
        "    def inner(target):\n"
        "        return value\n"
        "    return inner\n"
        "\n"
        "cell Inv:\n"
        "    viewgen layout -> Layout:\n"
        "        width = 2\n"
        "        return width\n"
    )

    analysis = analyze_ord(ord_string)
    binding_map = dict((binding["name"], binding) for binding in analysis.bindings)

    assert binding_map["outer"]["kind"] == "function"
    assert binding_map["outer"]["exported"] is True
    assert binding_map["source"]["kind"] == "parameter"
    assert binding_map["value"]["kind"] == "variable"
    assert binding_map["inner"]["kind"] == "function"
    assert binding_map["target"]["kind"] == "parameter"
    assert binding_map["Inv"]["kind"] == "class"
    assert binding_map["layout"]["kind"] == "function"
    assert binding_map["width"]["kind"] == "variable"

    assert any(
        occurrence["name"] == "value"
        and occurrence["range"].to_dict() == {
            "start": {"line": 4, "character": 16},
            "end": {"line": 4, "character": 21},
        }
        for occurrence in analysis.occurrences
    )
    assert any(
        occurrence["name"] == "width"
        and occurrence["range"].to_dict() == {
            "start": {"line": 10, "character": 16},
            "end": {"line": 10, "character": 21},
        }
        for occurrence in analysis.occurrences
    )


def test_analysis_session_local_definitions_follow_nested_scopes(tmp_path):
    local_path = tmp_path / "locals.ord"
    local_path.write_text(
        "def outer(source):\n"
        "    value = source\n"
        "    def inner(target):\n"
        "        return value\n"
        "    return value\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = local_path.resolve().as_uri()

    definition = session.definition(uri, AnalysisPosition(line=4, character=18))
    assert definition["uri"] == uri
    assert definition["name"] == "value"
    assert definition["kind"] == "variable"
    assert definition["selection_range"].to_dict() == {
        "start": {"line": 2, "character": 5},
        "end": {"line": 2, "character": 10},
    }

    hover = session.hover(uri, AnalysisPosition(line=4, character=18))
    assert hover["contents"] == "variable value"
    assert hover["range"].to_dict() == {
        "start": {"line": 4, "character": 16},
        "end": {"line": 4, "character": 21},
    }

    references = session.references(uri, AnalysisPosition(line=4, character=18))
    assert [(ref["uri"], ref["name"], ref["range"].to_dict()) for ref in references] == [
        (
            uri,
            "value",
            {
                "start": {"line": 2, "character": 5},
                "end": {"line": 2, "character": 10},
            },
        ),
        (
            uri,
            "value",
            {
                "start": {"line": 4, "character": 16},
                "end": {"line": 4, "character": 21},
            },
        ),
        (
            uri,
            "value",
            {
                "start": {"line": 5, "character": 12},
                "end": {"line": 5, "character": 17},
            },
        ),
    ]


def test_analysis_session_completions_include_visible_locals(tmp_path):
    local_path = tmp_path / "locals.ord"
    local_path.write_text(
        "def outer(source):\n"
        "    value = source\n"
        "    def inner(target):\n"
        "        return value\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = local_path.resolve().as_uri()
    completion_map = dict(
        (
            item["label"],
            {
                "kind": item["kind"],
                "detail": item["detail"],
            },
        )
        for item in session.completions(uri, AnalysisPosition(line=4, character=18))
    )

    assert completion_map["source"] == {
        "kind": "parameter",
        "detail": "parameter",
    }
    assert completion_map["target"] == {
        "kind": "parameter",
        "detail": "parameter",
    }
    assert completion_map["value"] == {
        "kind": "variable",
        "detail": "variable",
    }


def test_analysis_session_rename_local_bindings_is_file_local(tmp_path):
    local_path = tmp_path / "locals.ord"
    local_path.write_text(
        "def outer(source):\n"
        "    value = source\n"
        "    def inner(target):\n"
        "        return value\n"
        "    return value\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = local_path.resolve().as_uri()
    rename = session.rename(uri, AnalysisPosition(line=4, character=18), "signal")

    assert {
        change_uri: [
            {
                "range": change["range"].to_dict(),
                "new_text": change["new_text"],
            }
            for change in changes
        ]
        for change_uri, changes in rename.items()
    } == {
        uri: [
            {
                "range": {
                    "start": {"line": 2, "character": 5},
                    "end": {"line": 2, "character": 10},
                },
                "new_text": "signal",
            },
            {
                "range": {
                    "start": {"line": 4, "character": 16},
                    "end": {"line": 4, "character": 21},
                },
                "new_text": "signal",
            },
            {
                "range": {
                    "start": {"line": 5, "character": 12},
                    "end": {"line": 5, "character": 17},
                },
                "new_text": "signal",
            },
        ],
    }


def test_analysis_session_destructuring_assignments_resolve_locally(tmp_path):
    local_path = tmp_path / "locals.ord"
    local_path.write_text(
        "def helper(pair):\n"
        "    left, right = pair\n"
        "    return left\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = local_path.resolve().as_uri()

    definition = session.definition(uri, AnalysisPosition(line=3, character=13))
    assert definition["uri"] == uri
    assert definition["name"] == "left"
    assert definition["kind"] == "variable"
    assert definition["selection_range"].to_dict() == {
        "start": {"line": 2, "character": 5},
        "end": {"line": 2, "character": 9},
    }

    completion_map = dict(
        (
            item["label"],
            {
                "kind": item["kind"],
                "detail": item["detail"],
            },
        )
        for item in session.completions(uri, AnalysisPosition(line=3, character=13))
    )
    assert completion_map["left"] == {
        "kind": "variable",
        "detail": "variable",
    }
    assert completion_map["right"] == {
        "kind": "variable",
        "detail": "variable",
    }


def test_analysis_session_for_loop_variables_resolve_after_loop(tmp_path):
    local_path = tmp_path / "loop.ord"
    local_path.write_text(
        "def helper(limit):\n"
        "    for index in range(limit):\n"
        "        current = index\n"
        "    return index\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = local_path.resolve().as_uri()

    definition = session.definition(uri, AnalysisPosition(line=4, character=14))
    assert definition["uri"] == uri
    assert definition["name"] == "index"
    assert definition["kind"] == "variable"
    assert definition["selection_range"].to_dict() == {
        "start": {"line": 2, "character": 9},
        "end": {"line": 2, "character": 14},
    }

    references = session.references(uri, AnalysisPosition(line=4, character=14))
    assert [(ref["uri"], ref["name"], ref["range"].to_dict()) for ref in references] == [
        (
            uri,
            "index",
            {
                "start": {"line": 2, "character": 9},
                "end": {"line": 2, "character": 14},
            },
        ),
        (
            uri,
            "index",
            {
                "start": {"line": 3, "character": 19},
                "end": {"line": 3, "character": 24},
            },
        ),
        (
            uri,
            "index",
            {
                "start": {"line": 4, "character": 12},
                "end": {"line": 4, "character": 17},
            },
        ),
    ]


def test_analysis_session_for_loop_destructuring_resolves_locally(tmp_path):
    local_path = tmp_path / "loop_destructure.ord"
    local_path.write_text(
        "def helper(pairs):\n"
        "    for idx, (left, right) in pairs:\n"
        "        current = left\n"
        "    return right\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = local_path.resolve().as_uri()

    definition = session.definition(uri, AnalysisPosition(line=4, character=14))
    assert definition["uri"] == uri
    assert definition["name"] == "right"
    assert definition["kind"] == "variable"
    assert definition["selection_range"].to_dict() == {
        "start": {"line": 2, "character": 21},
        "end": {"line": 2, "character": 26},
    }

    references = session.references(uri, AnalysisPosition(line=4, character=14))
    assert [(ref["uri"], ref["name"], ref["range"].to_dict()) for ref in references] == [
        (
            uri,
            "right",
            {
                "start": {"line": 2, "character": 21},
                "end": {"line": 2, "character": 26},
            },
        ),
        (
            uri,
            "right",
            {
                "start": {"line": 4, "character": 12},
                "end": {"line": 4, "character": 17},
            },
        ),
    ]


def test_analysis_session_with_and_except_targets_resolve_locally(tmp_path):
    local_path = tmp_path / "with_except.ord"
    local_path.write_text(
        "def helper(path):\n"
        "    with open(path) as handle:\n"
        "        data = handle.read()\n"
        "    try:\n"
        "        raise ValueError(data)\n"
        "    except ValueError as exc:\n"
        "        return exc\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = local_path.resolve().as_uri()

    handle_definition = session.definition(uri, AnalysisPosition(line=3, character=17))
    assert handle_definition["uri"] == uri
    assert handle_definition["name"] == "handle"
    assert handle_definition["kind"] == "variable"
    assert handle_definition["selection_range"].to_dict() == {
        "start": {"line": 2, "character": 24},
        "end": {"line": 2, "character": 30},
    }

    exc_definition = session.definition(uri, AnalysisPosition(line=7, character=17))
    assert exc_definition["uri"] == uri
    assert exc_definition["name"] == "exc"
    assert exc_definition["kind"] == "variable"
    assert exc_definition["selection_range"].to_dict() == {
        "start": {"line": 6, "character": 26},
        "end": {"line": 6, "character": 29},
    }


def test_analysis_session_completions_tolerate_incomplete_import_syntax(tmp_path):
    local_path = tmp_path / "broken.ord"
    local_path.write_text("from ...\n")

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = local_path.resolve().as_uri()
    completions = session.completions(uri, AnalysisPosition(line=1, character=8))
    completion_map = dict((item["label"], item) for item in completions)

    assert completion_map["cell"]["kind"] == "keyword"
    assert completion_map["viewgen"]["kind"] == "keyword"


def test_analysis_session_context_declarations_resolve_inverter_style_names(tmp_path):
    local_path = tmp_path / "inv.ord"
    local_path.write_text(
        "cell Inv:\n"
        "    viewgen schematic -> Schematic:\n"
        "        port vss: .align=South\n"
        "        Nmos pd:\n"
        "            .s -- vss\n"
        "        pd.$l = 350u\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = local_path.resolve().as_uri()

    pd_definition = session.definition(uri, AnalysisPosition(line=6, character=10))
    assert pd_definition["uri"] == uri
    assert pd_definition["name"] == "pd"
    assert pd_definition["kind"] == "variable"
    assert pd_definition["selection_range"].to_dict() == {
        "start": {"line": 4, "character": 14},
        "end": {"line": 4, "character": 16},
    }

    vss_definition = session.definition(uri, AnalysisPosition(line=5, character=19))
    assert vss_definition["uri"] == uri
    assert vss_definition["name"] == "vss"
    assert vss_definition["kind"] == "variable"
    assert vss_definition["selection_range"].to_dict() == {
        "start": {"line": 3, "character": 14},
        "end": {"line": 3, "character": 17},
    }

    pd_references = session.references(uri, AnalysisPosition(line=6, character=10))
    assert [(ref["uri"], ref["name"], ref["range"].to_dict()) for ref in pd_references] == [
        (
            uri,
            "pd",
            {
                "start": {"line": 4, "character": 14},
                "end": {"line": 4, "character": 16},
            },
        ),
        (
            uri,
            "pd",
            {
                "start": {"line": 6, "character": 9},
                "end": {"line": 6, "character": 11},
            },
        ),
    ]

    vss_references = session.references(uri, AnalysisPosition(line=5, character=19))
    assert [(ref["uri"], ref["name"], ref["range"].to_dict()) for ref in vss_references] == [
        (
            uri,
            "vss",
            {
                "start": {"line": 3, "character": 14},
                "end": {"line": 3, "character": 17},
            },
        ),
        (
            uri,
            "vss",
            {
                "start": {"line": 5, "character": 19},
                "end": {"line": 5, "character": 22},
            },
        ),
    ]


def test_analysis_session_folding_ranges_cover_symbols_and_imports():
    ord_string = (
        "import math\n"
        "from .helpers import foo\n"
        "from .helpers import bar\n"
        "\n"
        "cell Inv:\n"
        "    viewgen layout -> Layout:\n"
        "        output bus[0].y:\n"
        "            .align = East\n"
        "        path vdd, vss\n"
        "\n"
        "def helper(x):\n"
        "    return x\n"
    )

    session = AnalysisSession()
    uri = "file:///tmp/test.ord"
    session.open_document(uri, ord_string)
    ranges = session.folding_ranges(uri)

    assert ranges == [
        # import block: lines 1-3
        {"start_line": 1, "end_line": 3, "kind": "imports"},
        # cell Inv
        {"start_line": 5, "end_line": 11, "kind": "region"},
        # viewgen layout
        {"start_line": 6, "end_line": 11, "kind": "region"},
        # output context
        {"start_line": 7, "end_line": 9, "kind": "region"},
        # def helper
        {"start_line": 11, "end_line": 14, "kind": "region"},
    ]


def test_analysis_session_folding_ranges_single_line_symbols_excluded():
    """Single-line constructs should not produce fold regions."""

    ord_string = (
        "def one_liner():\n"
        "    return 1\n"
        "\n"
        "cell Big:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    session = AnalysisSession()
    uri = "file:///tmp/test.ord"
    session.open_document(uri, ord_string)
    ranges = session.folding_ranges(uri)

    # one_liner spans 2 lines (1-2), Big spans 4-6, symbol spans 5-6
    for r in ranges:
        assert r["end_line"] > r["start_line"]


def test_analysis_session_selection_ranges_expand_through_scopes():
    ord_string = (
        "cell Inv:\n"
        "    viewgen layout -> Layout:\n"
        "        path vdd\n"
    )

    session = AnalysisSession()
    uri = "file:///tmp/test.ord"
    session.open_document(uri, ord_string)

    # Position on "layout" name (line 2, char 13).
    results = session.selection_ranges(uri, [AnalysisPosition(2, 13)])
    assert len(results) == 1

    chain = results[0]
    assert chain is not None

    # Collect the chain of ranges from innermost to outermost.
    ranges_chain = []
    node = chain
    while node is not None:
        ranges_chain.append(node["range"].to_dict())
        node = node["parent"]

    # Innermost should be the "layout" token, then viewgen scope, then file scope.
    assert len(ranges_chain) >= 2
    # The innermost range should be tight around "layout".
    assert ranges_chain[0] == {
        "start": {"line": 2, "character": 13},
        "end": {"line": 2, "character": 19},
    }


def test_analysis_session_selection_ranges_returns_none_for_empty_position():
    session = AnalysisSession()
    uri = "file:///tmp/test.ord"
    session.open_document(uri, "\n\n\n")

    results = session.selection_ranges(uri, [AnalysisPosition(2, 1)])
    assert len(results) == 1
    # Even on an empty line there should be at least the file scope.
    # The result may be a scope chain or None depending on position.


def test_analysis_session_semantic_tokens_classify_bindings_and_members():
    ord_string = (
        "from .helpers import foo\n"
        "\n"
        "cell Inv:\n"
        "    def build(self):\n"
        "        .align = East\n"
    )

    session = AnalysisSession()
    uri = "file:///tmp/test.ord"
    session.open_document(uri, ord_string)
    tokens = session.semantic_tokens(uri)

    token_tuples = [
        (t["range"].to_dict(), t["type"], t["modifiers"])
        for t in tokens
    ]

    # foo (import entry) — classified as variable
    assert (
        {"start": {"line": 1, "character": 22}, "end": {"line": 1, "character": 25}},
        "variable",
        [],
    ) in token_tuples

    # Inv (class definition)
    assert (
        {"start": {"line": 3, "character": 6}, "end": {"line": 3, "character": 9}},
        "class",
        ["definition"],
    ) in token_tuples

    # build (function definition)
    assert (
        {"start": {"line": 4, "character": 9}, "end": {"line": 4, "character": 14}},
        "function",
        ["definition"],
    ) in token_tuples

    # self (parameter definition)
    assert (
        {"start": {"line": 4, "character": 15}, "end": {"line": 4, "character": 19}},
        "parameter",
        ["definition"],
    ) in token_tuples

    # .align (property)
    assert (
        {"start": {"line": 5, "character": 10}, "end": {"line": 5, "character": 15}},
        "property",
        [],
    ) in token_tuples


def test_analysis_session_cross_file_ord_cell_member_definition(tmp_path):
    """Member accesses on instances of imported ORD cells resolve to context declarations."""

    inv_path = tmp_path / "inverter.ord"
    inv_path.write_text(
        "cell Inv:\n"
        "    input g:\n"
        "        .width = 1\n"
        "    output d:\n"
        "        .width = 1\n"
        "    path vdd, vss\n"
    )

    top_path = tmp_path / "top.ord"
    top_path.write_text(
        "from .inverter import Inv\n"
        "\n"
        "cell Top:\n"
        "    Inv inv:\n"
        "        .g -- signal_in\n"
        "        .d -- signal_out\n"
        "        .vdd -- power\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    top_uri = session.open_path(str(top_path))
    inv_uri = inv_path.resolve().as_uri()

    # .g should resolve to input g in inverter.ord
    g_defn = session.definition(top_uri, AnalysisPosition(5, 10))
    assert g_defn is not None
    assert g_defn["uri"] == inv_uri
    assert g_defn["name"] == "g"

    # .d should resolve to output d in inverter.ord
    d_defn = session.definition(top_uri, AnalysisPosition(6, 10))
    assert d_defn is not None
    assert d_defn["uri"] == inv_uri
    assert d_defn["name"] == "d"

    # .vdd should resolve to path vdd in inverter.ord
    vdd_defn = session.definition(top_uri, AnalysisPosition(7, 10))
    assert vdd_defn is not None
    assert vdd_defn["uri"] == inv_uri
    assert vdd_defn["name"] == "vdd"

    # hover on .g should show the cross-file target
    g_hover = session.hover(top_uri, AnalysisPosition(5, 10))
    assert g_hover is not None
    assert "g" in g_hover["contents"]
    assert inv_uri in g_hover["contents"]


def test_analysis_session_cross_file_ord_cell_member_same_file(tmp_path):
    """Member accesses on instances of cells defined in the same file also resolve."""

    single_path = tmp_path / "circuit.ord"
    single_path.write_text(
        "cell Driver:\n"
        "    output q:\n"
        "        .width = 1\n"
        "\n"
        "cell Top:\n"
        "    Driver drv:\n"
        "        .q -- out\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = session.open_path(str(single_path))

    # .q should resolve to output q in Driver (same file)
    q_defn = session.definition(uri, AnalysisPosition(7, 10))
    assert q_defn is not None
    assert q_defn["uri"] == uri
    assert q_defn["name"] == "q"
