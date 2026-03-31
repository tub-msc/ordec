# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.analysis import AnalysisSession
from ordec.analysis import AnalysisPosition
from ordec.analysis import analyze_ord2


def test_analyze_ord2_collects_symbols():
    ord_string = (
        "cell Inv:\n"
        "    viewgen layout(layers=sky130) -> Layout:\n"
        "        output bus[0].y:\n"
        "            .align = East\n"
        "        path vdd, vss\n"
        "\n"
        "def helper(x):\n"
        "    return x\n"
    )

    analysis = analyze_ord2(ord_string, uri="file:///tmp/test.ord", version=3)

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


def test_analyze_ord2_reports_syntax_errors():
    analysis = analyze_ord2("cell Inv:\n    viewgen layout(", uri="file:///tmp/test.ord")

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


def test_analyze_ord2_collects_imports_and_exports():
    ord_string = (
        "import math, numpy as np\n"
        "from .helpers import foo, bar as baz\n"
        "from ...ord2 import parser\n"
        "\n"
        "cell Inv:\n"
        "    viewgen layout() -> Layout:\n"
        "        return Layout()\n"
        "\n"
        "def helper():\n"
        "    return foo\n"
    )

    analysis = analyze_ord2(ord_string)

    assert analysis.imports == [
        "math",
        "numpy as np",
        "from .helpers import foo, bar as baz",
        "from ...ord2 import parser",
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
        ("from", "...ord2", "parser", "parser"),
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
    mux2_path = tmp_path / "ord2" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord2" / "nmux.ord"
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
    mux2_path = tmp_path / "ord2" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord2" / "nmux.ord"
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
    nmux_path = tmp_path / "ord2" / "nmux.ord"
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
    mux2_path = tmp_path / "ord2" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord2" / "nmux.ord"
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


def test_analysis_session_hover_uses_current_token_range(tmp_path):
    mux2_path = tmp_path / "ord2" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord2" / "nmux.ord"
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
    mux2_path = tmp_path / "ord2" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord2" / "nmux.ord"
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


def test_analysis_session_completions_include_symbols_imports_and_keywords(tmp_path):
    mux2_path = tmp_path / "ord2" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord2" / "nmux.ord"
    nmux_path.write_text(
        "from .mux2 import Mux2 as Stage\n"
        "import math\n"
        "\n"
        "cell Nto1:\n"
        "    viewgen layout() -> Layout:\n"
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
    mux2_path = tmp_path / "ord2" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord2" / "nmux.ord"
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
    mux2_path = tmp_path / "ord2" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord2" / "nmux.ord"
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
    ord2_path = tmp_path / "ord2"
    ord2_path.mkdir()
    (ord2_path / "mux2.ord").write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )
    (ord2_path / "helper.ord").write_text(
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
            (ord2_path / "helper.ord").resolve().as_uri(),
            "build_mux",
            "function",
        ),
        (
            (ord2_path / "mux2.ord").resolve().as_uri(),
            "Mux2",
            "class",
        ),
    ]


def test_analysis_session_prepare_rename_returns_current_token(tmp_path):
    mux2_path = tmp_path / "ord2" / "mux2.ord"
    mux2_path.parent.mkdir()
    mux2_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )

    nmux_path = tmp_path / "ord2" / "nmux.ord"
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


def test_analyze_ord2_collects_local_bindings_and_occurrences():
    ord_string = (
        "def outer(source):\n"
        "    value = source\n"
        "    def inner(target):\n"
        "        return value\n"
        "    return inner\n"
        "\n"
        "cell Inv:\n"
        "    viewgen layout(width=2) -> Layout:\n"
        "        return width\n"
    )

    analysis = analyze_ord2(ord_string)
    binding_map = dict((binding["name"], binding) for binding in analysis.bindings)

    assert binding_map["outer"]["kind"] == "function"
    assert binding_map["outer"]["exported"] is True
    assert binding_map["source"]["kind"] == "parameter"
    assert binding_map["value"]["kind"] == "variable"
    assert binding_map["inner"]["kind"] == "function"
    assert binding_map["target"]["kind"] == "parameter"
    assert binding_map["Inv"]["kind"] == "class"
    assert binding_map["layout"]["kind"] == "function"
    assert binding_map["width"]["kind"] == "parameter"

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
            "start": {"line": 9, "character": 16},
            "end": {"line": 9, "character": 21},
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


def test_analysis_session_viewgen_parameters_resolve_locally(tmp_path):
    local_path = tmp_path / "view.ord"
    local_path.write_text(
        "cell Inv:\n"
        "    viewgen layout(width=2) -> Layout:\n"
        "        return width\n"
    )

    session = AnalysisSession(workspace_root=str(tmp_path))
    uri = local_path.resolve().as_uri()

    definition = session.definition(uri, AnalysisPosition(line=3, character=18))
    assert definition["uri"] == uri
    assert definition["name"] == "width"
    assert definition["kind"] == "parameter"
    assert definition["selection_range"].to_dict() == {
        "start": {"line": 2, "character": 20},
        "end": {"line": 2, "character": 25},
    }

    completion_map = dict(
        (
            item["label"],
            {
                "kind": item["kind"],
                "detail": item["detail"],
            },
        )
        for item in session.completions(uri, AnalysisPosition(line=3, character=18))
    )
    assert completion_map["width"] == {
        "kind": "parameter",
        "detail": "parameter",
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
