# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.lsp.server import OrdecLanguageServer


def test_lsp_initialize_exposes_core_capabilities(tmp_path):
    server = OrdecLanguageServer()
    responses = server.handle_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "rootUri": tmp_path.resolve().as_uri(),
        },
    })

    assert responses == [{
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "serverInfo": {
                "name": "ordec-lsp",
            },
            "capabilities": {
                "textDocumentSync": 1,
                "documentSymbolProvider": True,
                "documentHighlightProvider": True,
                "workspaceSymbolProvider": True,
                "definitionProvider": True,
                "hoverProvider": True,
                "referencesProvider": True,
                "renameProvider": {
                    "prepareProvider": True,
                },
                "completionProvider": {
                    "resolveProvider": False,
                },
            },
        },
    }]


def test_lsp_open_definition_hover_and_references(tmp_path):
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

    server = OrdecLanguageServer()
    server.handle_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "rootUri": tmp_path.resolve().as_uri(),
        },
    })

    uri = nmux_path.resolve().as_uri()
    open_messages = server.handle_message({
        "jsonrpc": "2.0",
        "method": "textDocument/didOpen",
        "params": {
            "textDocument": {
                "uri": uri,
                "version": 1,
                "text": nmux_path.read_text(),
            },
        },
    })
    assert open_messages == [{
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {
            "uri": uri,
            "diagnostics": [],
        },
    }]

    definition_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "textDocument/definition",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 2, "character": 14},
        },
    })
    assert definition_messages == [{
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "uri": mux2_path.resolve().as_uri(),
            "range": {
                "start": {"line": 0, "character": 5},
                "end": {"line": 0, "character": 9},
            },
        },
    }]

    hover_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "textDocument/hover",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 2, "character": 14},
        },
    })
    assert hover_messages == [{
        "jsonrpc": "2.0",
        "id": 3,
        "result": {
            "contents": {
                "kind": "plaintext",
                "value": "class Mux2\n{}".format(mux2_path.resolve().as_uri()),
            },
            "range": {
                "start": {"line": 2, "character": 13},
                "end": {"line": 2, "character": 18},
            },
        },
    }]

    reference_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "textDocument/references",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 2, "character": 14},
        },
    })
    assert reference_messages == [{
        "jsonrpc": "2.0",
        "id": 4,
        "result": [
            {
                "uri": uri,
                "range": {
                    "start": {"line": 0, "character": 26},
                    "end": {"line": 0, "character": 31},
                },
            },
            {
                "uri": uri,
                "range": {
                    "start": {"line": 2, "character": 13},
                    "end": {"line": 2, "character": 18},
                },
            },
            {
                "uri": uri,
                "range": {
                    "start": {"line": 3, "character": 11},
                    "end": {"line": 3, "character": 16},
                },
            },
            {
                "uri": mux2_path.resolve().as_uri(),
                "range": {
                    "start": {"line": 0, "character": 5},
                    "end": {"line": 0, "character": 9},
                },
            },
        ],
    }]

    highlight_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 5,
        "method": "textDocument/documentHighlight",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 2, "character": 14},
        },
    })
    assert highlight_messages == [{
        "jsonrpc": "2.0",
        "id": 5,
        "result": [
            {
                "range": {
                    "start": {"line": 0, "character": 26},
                    "end": {"line": 0, "character": 31},
                },
                "kind": 3,
            },
            {
                "range": {
                    "start": {"line": 2, "character": 13},
                    "end": {"line": 2, "character": 18},
                },
                "kind": 2,
            },
            {
                "range": {
                    "start": {"line": 3, "character": 11},
                    "end": {"line": 3, "character": 16},
                },
                "kind": 2,
            },
        ],
    }]

    completion_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 6,
        "method": "textDocument/completion",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 2, "character": 14},
        },
    })
    completion_map = {
        item["label"]: {
            "kind": item["kind"],
            "detail": item["detail"],
        }
        for item in completion_messages[0]["result"]
    }
    assert completion_map["Stage"] == {
        "kind": 7,
        "detail": "from .mux2 import Mux2 as Stage",
    }
    assert completion_map["helper"] == {
        "kind": 3,
        "detail": "function",
    }
    assert completion_map["cell"] == {
        "kind": 14,
        "detail": "keyword",
    }

    prepare_rename_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 7,
        "method": "textDocument/prepareRename",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 2, "character": 14},
        },
    })
    assert prepare_rename_messages == [{
        "jsonrpc": "2.0",
        "id": 7,
        "result": {
            "range": {
                "start": {"line": 2, "character": 13},
                "end": {"line": 2, "character": 18},
            },
            "placeholder": "Stage",
        },
    }]

    rename_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 8,
        "method": "textDocument/rename",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 2, "character": 14},
            "newName": "Driver",
        },
    })
    assert rename_messages == [{
        "jsonrpc": "2.0",
        "id": 8,
        "result": {
            "changes": {
                uri: [
                    {
                        "range": {
                            "start": {"line": 0, "character": 26},
                            "end": {"line": 0, "character": 31},
                        },
                        "newText": "Driver",
                    },
                    {
                        "range": {
                            "start": {"line": 2, "character": 13},
                            "end": {"line": 2, "character": 18},
                        },
                        "newText": "Driver",
                    },
                    {
                        "range": {
                            "start": {"line": 3, "character": 11},
                            "end": {"line": 3, "character": 16},
                        },
                        "newText": "Driver",
                    },
                ],
            },
        },
    }]


def test_lsp_document_symbol_and_diagnostics(tmp_path):
    server = OrdecLanguageServer()
    server.handle_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "rootUri": tmp_path.resolve().as_uri(),
        },
    })

    uri = (tmp_path / "test.ord").resolve().as_uri()
    open_messages = server.handle_message({
        "jsonrpc": "2.0",
        "method": "textDocument/didOpen",
        "params": {
            "textDocument": {
                "uri": uri,
                "version": 1,
                "text": "cell Inv:\n    viewgen layout(\n",
            },
        },
    })
    assert open_messages[0]["params"]["diagnostics"][0]["severity"] == 1

    server.handle_message({
        "jsonrpc": "2.0",
        "method": "textDocument/didChange",
        "params": {
            "textDocument": {
                "uri": uri,
                "version": 2,
            },
            "contentChanges": [{
                "text": "cell Inv:\n    viewgen layout() -> Layout:\n        path a\n",
            }],
        },
    })

    symbol_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "textDocument/documentSymbol",
        "params": {
            "textDocument": {"uri": uri},
        },
    })
    assert symbol_messages == [{
        "jsonrpc": "2.0",
        "id": 2,
        "result": [
            {
                "name": "Inv",
                "kind": 5,
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 4, "character": 0},
                },
                "selectionRange": {
                    "start": {"line": 0, "character": 5},
                    "end": {"line": 0, "character": 8},
                },
            },
            {
                "name": "layout",
                "kind": 12,
                "range": {
                    "start": {"line": 1, "character": 4},
                    "end": {"line": 4, "character": 0},
                },
                "selectionRange": {
                    "start": {"line": 1, "character": 12},
                    "end": {"line": 1, "character": 18},
                },
            },
            {
                "name": "a",
                "kind": 13,
                "range": {
                    "start": {"line": 2, "character": 8},
                    "end": {"line": 2, "character": 14},
                },
                "selectionRange": {
                    "start": {"line": 2, "character": 13},
                    "end": {"line": 2, "character": 14},
                },
            },
        ],
    }]


def test_lsp_workspace_symbol_scans_workspace_root(tmp_path):
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

    server = OrdecLanguageServer()
    server.handle_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "rootUri": tmp_path.resolve().as_uri(),
        },
    })

    symbol_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "workspace/symbol",
        "params": {
            "query": "mux",
        },
    })
    assert symbol_messages == [{
        "jsonrpc": "2.0",
        "id": 2,
        "result": [
            {
                "name": "build_mux",
                "kind": 12,
                "location": {
                    "uri": (ord2_path / "helper.ord").resolve().as_uri(),
                    "range": {
                        "start": {"line": 0, "character": 4},
                        "end": {"line": 0, "character": 13},
                    },
                },
            },
            {
                "name": "Mux2",
                "kind": 5,
                "location": {
                    "uri": (ord2_path / "mux2.ord").resolve().as_uri(),
                    "range": {
                        "start": {"line": 0, "character": 5},
                        "end": {"line": 0, "character": 9},
                    },
                },
            },
        ],
    }]


def test_lsp_module_imports_resolve_to_local_module(tmp_path):
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

    server = OrdecLanguageServer()
    server.handle_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "rootUri": tmp_path.resolve().as_uri(),
        },
    })

    uri = user_path.resolve().as_uri()
    server.handle_message({
        "jsonrpc": "2.0",
        "method": "textDocument/didOpen",
        "params": {
            "textDocument": {
                "uri": uri,
                "version": 1,
                "text": user_path.read_text(),
            },
        },
    })

    definition_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "textDocument/definition",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 2, "character": 14},
        },
    })
    assert definition_messages == [{
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "uri": (tmp_path / "localmod.ord").resolve().as_uri(),
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 0},
            },
        },
    }]

    hover_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "textDocument/hover",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 2, "character": 14},
        },
    })
    assert hover_messages == [{
        "jsonrpc": "2.0",
        "id": 3,
        "result": {
            "contents": {
                "kind": "plaintext",
                "value": "module localmod\n{}".format((tmp_path / "localmod.ord").resolve().as_uri()),
            },
            "range": {
                "start": {"line": 2, "character": 13},
                "end": {"line": 2, "character": 16},
            },
        },
    }]

    rename_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "textDocument/rename",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 2, "character": 14},
            "newName": "driver",
        },
    })
    assert rename_messages == [{
        "jsonrpc": "2.0",
        "id": 4,
        "result": {
            "changes": {
                uri: [
                    {
                        "range": {
                            "start": {"line": 0, "character": 19},
                            "end": {"line": 0, "character": 22},
                        },
                        "newText": "driver",
                    },
                    {
                        "range": {
                            "start": {"line": 2, "character": 13},
                            "end": {"line": 2, "character": 16},
                        },
                        "newText": "driver",
                    },
                    {
                        "range": {
                            "start": {"line": 3, "character": 11},
                            "end": {"line": 3, "character": 14},
                        },
                        "newText": "driver",
                    },
                ],
            },
        },
    }]


def test_lsp_definition_resolves_python_imports(tmp_path):
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

    server = OrdecLanguageServer()
    server.handle_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "rootUri": tmp_path.resolve().as_uri(),
        },
    })

    uri = inv_path.resolve().as_uri()
    server.handle_message({
        "jsonrpc": "2.0",
        "method": "textDocument/didOpen",
        "params": {
            "textDocument": {
                "uri": uri,
                "version": 1,
                "text": inv_path.read_text(),
            },
        },
    })

    symbol_definition = server.handle_message({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "textDocument/definition",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 4, "character": 23},
        },
    })
    assert symbol_definition[0]["result"]["uri"].endswith("/ordec/core/schema.py")

    nmos_definition = server.handle_message({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "textDocument/definition",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 8, "character": 14},
        },
    })
    assert nmos_definition[0]["id"] == 3
    assert nmos_definition[0]["result"] is not None
    assert nmos_definition[0]["result"]["uri"].endswith("/ordec/lib/generic_mos.py")


def test_lsp_definition_resolves_python_members(tmp_path):
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

    server = OrdecLanguageServer()
    server.handle_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "rootUri": tmp_path.resolve().as_uri(),
        },
    })

    uri = inv_path.resolve().as_uri()
    server.handle_message({
        "jsonrpc": "2.0",
        "method": "textDocument/didOpen",
        "params": {
            "textDocument": {
                "uri": uri,
                "version": 1,
                "text": inv_path.read_text(),
            },
        },
    })

    source_definition = server.handle_message({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "textDocument/definition",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 8, "character": 13},
        },
    })
    assert source_definition[0]["result"]["uri"].endswith("/ordec/lib/generic_mos.py")
    assert source_definition[0]["result"]["range"]["start"]["line"] == 53

    param_definition = server.handle_message({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "textDocument/definition",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 10, "character": 14},
        },
    })
    assert param_definition[0]["result"]["uri"].endswith("/ordec/lib/generic_mos.py")
    assert param_definition[0]["result"]["range"]["start"]["line"] == 26

    loop_definition = server.handle_message({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "textDocument/definition",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 15, "character": 21},
        },
    })
    assert loop_definition[0]["result"]["uri"].endswith("/ordec/lib/generic_mos.py")
    assert loop_definition[0]["result"]["range"]["start"]["line"] in (52, 75)


def test_lsp_local_variables_resolve_and_rename(tmp_path):
    local_path = tmp_path / "locals.ord"
    local_path.write_text(
        "def outer(source):\n"
        "    value = source\n"
        "    def inner(target):\n"
        "        return value\n"
        "    return value\n"
    )

    server = OrdecLanguageServer()
    server.handle_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "rootUri": tmp_path.resolve().as_uri(),
        },
    })

    uri = local_path.resolve().as_uri()
    server.handle_message({
        "jsonrpc": "2.0",
        "method": "textDocument/didOpen",
        "params": {
            "textDocument": {
                "uri": uri,
                "version": 1,
                "text": local_path.read_text(),
            },
        },
    })

    definition_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "textDocument/definition",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 3, "character": 17},
        },
    })
    assert definition_messages == [{
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "uri": uri,
            "range": {
                "start": {"line": 1, "character": 4},
                "end": {"line": 1, "character": 9},
            },
        },
    }]

    hover_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "textDocument/hover",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 3, "character": 17},
        },
    })
    assert hover_messages == [{
        "jsonrpc": "2.0",
        "id": 3,
        "result": {
            "contents": {
                "kind": "plaintext",
                "value": "variable value",
            },
            "range": {
                "start": {"line": 3, "character": 15},
                "end": {"line": 3, "character": 20},
            },
        },
    }]

    completion_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "textDocument/completion",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 3, "character": 17},
        },
    })
    completion_map = {
        item["label"]: {
            "kind": item["kind"],
            "detail": item["detail"],
        }
        for item in completion_messages[0]["result"]
    }
    assert completion_map["source"] == {
        "kind": 6,
        "detail": "parameter",
    }
    assert completion_map["target"] == {
        "kind": 6,
        "detail": "parameter",
    }
    assert completion_map["value"] == {
        "kind": 6,
        "detail": "variable",
    }

    rename_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 5,
        "method": "textDocument/rename",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 3, "character": 17},
            "newName": "signal",
        },
    })
    assert rename_messages == [{
        "jsonrpc": "2.0",
        "id": 5,
        "result": {
            "changes": {
                uri: [
                    {
                        "range": {
                            "start": {"line": 1, "character": 4},
                            "end": {"line": 1, "character": 9},
                        },
                        "newText": "signal",
                    },
                    {
                        "range": {
                            "start": {"line": 3, "character": 15},
                            "end": {"line": 3, "character": 20},
                        },
                        "newText": "signal",
                    },
                    {
                        "range": {
                            "start": {"line": 4, "character": 11},
                            "end": {"line": 4, "character": 16},
                        },
                        "newText": "signal",
                    },
                ],
            },
        },
    }]


def test_lsp_completion_tolerates_incomplete_import_syntax(tmp_path):
    local_path = tmp_path / "broken.ord"
    local_path.write_text("from ...\n")

    server = OrdecLanguageServer()
    server.handle_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "rootUri": tmp_path.resolve().as_uri(),
        },
    })

    uri = local_path.resolve().as_uri()
    open_messages = server.handle_message({
        "jsonrpc": "2.0",
        "method": "textDocument/didOpen",
        "params": {
            "textDocument": {
                "uri": uri,
                "version": 1,
                "text": local_path.read_text(),
            },
        },
    })
    assert open_messages[0]["params"]["diagnostics"][0]["severity"] == 1

    completion_messages = server.handle_message({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "textDocument/completion",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 0, "character": 7},
        },
    })
    completion_map = {
        item["label"]: {
            "kind": item["kind"],
            "detail": item["detail"],
        }
        for item in completion_messages[0]["result"]
    }

    assert completion_map["cell"] == {
        "kind": 14,
        "detail": "keyword",
    }
    assert completion_map["viewgen"] == {
        "kind": 14,
        "detail": "keyword",
    }


def test_lsp_definition_resolves_context_declared_names(tmp_path):
    local_path = tmp_path / "inv.ord"
    local_path.write_text(
        "cell Inv:\n"
        "    viewgen schematic -> Schematic:\n"
        "        port vss: .align=South\n"
        "        Nmos pd:\n"
        "            .s -- vss\n"
        "        pd.$l = 350u\n"
    )

    server = OrdecLanguageServer()
    server.handle_message({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "rootUri": tmp_path.resolve().as_uri(),
        },
    })

    uri = local_path.resolve().as_uri()
    server.handle_message({
        "jsonrpc": "2.0",
        "method": "textDocument/didOpen",
        "params": {
            "textDocument": {
                "uri": uri,
                "version": 1,
                "text": local_path.read_text(),
            },
        },
    })

    pd_definition = server.handle_message({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "textDocument/definition",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 5, "character": 9},
        },
    })
    assert pd_definition == [{
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "uri": uri,
            "range": {
                "start": {"line": 3, "character": 13},
                "end": {"line": 3, "character": 15},
            },
        },
    }]

    vss_definition = server.handle_message({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "textDocument/definition",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": 4, "character": 18},
        },
    })
    assert vss_definition == [{
        "jsonrpc": "2.0",
        "id": 3,
        "result": {
            "uri": uri,
            "range": {
                "start": {"line": 2, "character": 13},
                "end": {"line": 2, "character": 16},
            },
        },
    }]
