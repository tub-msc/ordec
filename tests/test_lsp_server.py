# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.lsp.server import OrdLanguageServer


def source_offset(source, needle, occurrence=1):
    """Return zero-based line and character for text in source."""
    start = 0
    for _ in range(occurrence):
        offset = source.index(needle, start)
        start = offset + len(needle)

    line = source.count("\n", 0, offset)
    previous_newline = source.rfind("\n", 0, offset)
    return {
        "line": line,
        "character": offset - previous_newline - 1,
    }


def source_offset_after(source, needle, occurrence=1):
    """Return zero-based line and character directly after text in source."""
    start = 0
    for _ in range(occurrence):
        offset = source.index(needle, start)
        start = offset + len(needle)

    offset += len(needle)
    line = source.count("\n", 0, offset)
    previous_newline = source.rfind("\n", 0, offset)
    return {
        "line": line,
        "character": offset - previous_newline - 1,
    }


def utf16_source_offset(source, needle, occurrence=1):
    """Return zero-based LSP UTF-16 line and character for text in source."""
    position = source_offset(source, needle, occurrence=occurrence)
    line_text = source.splitlines()[position["line"]]
    character = len(line_text[:position["character"]].encode("utf-16-le")) // 2
    return {
        "line": position["line"],
        "character": character,
    }


def initialize_server(tmp_path, capabilities=None):
    """Create and initialize an ORD language server for a temporary workspace."""
    server = OrdLanguageServer()
    params = {
        "rootUri": tmp_path.resolve().as_uri(),
    }
    if capabilities is not None:
        params["capabilities"] = capabilities

    result = request(
        server,
        "initialize",
        params,
    )
    assert result["serverInfo"]["name"] == "ordec-lsp"
    return server


def request(server, method, params=None, message_id=1):
    """Send an LSP request and return its result."""
    responses = server.handle_message({
        "jsonrpc": "2.0",
        "id": message_id,
        "method": method,
        "params": params or {},
    })
    assert len(responses) == 1
    assert "error" not in responses[0]
    return responses[0]["result"]


def notify(server, method, params=None):
    """Send an LSP notification and return the server responses."""
    return server.handle_message({
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
    })


def open_document(server, uri, text, version=1):
    """Open a document and return published diagnostics."""
    responses = notify(
        server,
        "textDocument/didOpen",
        {
            "textDocument": {
                "uri": uri,
                "version": version,
                "text": text,
            },
        },
    )
    assert len(responses) == 1
    assert responses[0]["method"] == "textDocument/publishDiagnostics"
    return responses[0]["params"]["diagnostics"]


def change_document(server, uri, text, version=2):
    """Replace a document and return published diagnostics."""
    responses = notify(
        server,
        "textDocument/didChange",
        {
            "textDocument": {
                "uri": uri,
                "version": version,
            },
            "contentChanges": [{
                "text": text,
            }],
        },
    )
    assert len(responses) == 1
    return responses[0]["params"]["diagnostics"]


def text_document(uri):
    """Return an LSP textDocument parameter."""
    return {
        "uri": uri,
    }


def test_lsp_initialize_exposes_core_capabilities(tmp_path):
    server = OrdLanguageServer()
    result = request(
        server,
        "initialize",
        {
            "rootUri": tmp_path.resolve().as_uri(),
        },
    )

    capabilities = result["capabilities"]
    for capability in (
        "documentSymbolProvider",
        "definitionProvider",
        "hoverProvider",
        "referencesProvider",
        "renameProvider",
        "completionProvider",
        "codeActionProvider",
        "foldingRangeProvider",
        "selectionRangeProvider",
        "semanticTokensProvider",
    ):
        assert capability in capabilities

    assert capabilities["completionProvider"]["triggerCharacters"] == [".", "$"]
    assert capabilities["positionEncoding"] == "utf-16"


def test_lsp_document_lifecycle_and_diagnostics(tmp_path):
    server = initialize_server(tmp_path)
    uri = (tmp_path / "broken.ord").resolve().as_uri()
    broken_source = "from .missing import Foo\n"

    diagnostics = open_document(server, uri, broken_source)
    assert [diagnostic["code"] for diagnostic in diagnostics] == ["unresolved-import"]

    fixed_source = "cell Inv:\n    viewgen symbol -> Symbol:\n        path a\n"
    assert change_document(server, uri, fixed_source) == []

    close_responses = notify(
        server,
        "textDocument/didClose",
        {
            "textDocument": text_document(uri),
        },
    )
    assert close_responses[0]["params"]["diagnostics"] == []


def test_lsp_watched_file_changes_republish_dependent_diagnostics(tmp_path):
    device_path = tmp_path / "device.ord"
    device_path.write_text(
        "cell Device:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    top_source = (
        "from .device import Device\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic -> Schematic:\n"
        "        Device inst:\n"
        "            .a -- net_a\n"
    )
    top_path = tmp_path / "top.ord"
    top_path.write_text(top_source)

    server = initialize_server(tmp_path)
    top_uri = top_path.resolve().as_uri()
    device_uri = device_path.resolve().as_uri()
    assert open_document(server, top_uri, top_source) == []

    device_path.write_text(
        "cell Other:\n"
        "    viewgen symbol -> Symbol:\n"
        "        input a\n"
    )
    responses = notify(
        server,
        "workspace/didChangeWatchedFiles",
        {
            "changes": [{
                "uri": device_uri,
                "type": 2,
            }],
        },
    )

    assert [response["params"]["uri"] for response in responses] == [top_uri]
    assert "unresolved-import-member" in {
        diagnostic["code"]
        for diagnostic in responses[0]["params"]["diagnostics"]
    }


def test_lsp_navigation_references_rename_and_symbols(tmp_path):
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

    server = initialize_server(tmp_path)
    uri = user_path.resolve().as_uri()
    assert open_document(server, uri, source) == []

    position = source_offset(source, "Stage", 2)
    definition = request(
        server,
        "textDocument/definition",
        {
            "textDocument": text_document(uri),
            "position": position,
        },
    )
    assert definition["uri"] == mux_path.resolve().as_uri()

    hover = request(
        server,
        "textDocument/hover",
        {
            "textDocument": text_document(uri),
            "position": position,
        },
    )
    assert "Mux2" in hover["contents"]["value"]

    references = request(
        server,
        "textDocument/references",
        {
            "textDocument": text_document(uri),
            "position": position,
        },
    )
    assert len(references) == 4

    highlights = request(
        server,
        "textDocument/documentHighlight",
        {
            "textDocument": text_document(uri),
            "position": position,
        },
    )
    assert len(highlights) == 3

    symbols = request(
        server,
        "textDocument/documentSymbol",
        {
            "textDocument": text_document(uri),
        },
    )
    assert [symbol["name"] for symbol in symbols] == ["helper"]

    assert request(
        server,
        "textDocument/prepareRename",
        {
            "textDocument": text_document(uri),
            "position": position,
        },
    )["placeholder"] == "Stage"
    rename = request(
        server,
        "textDocument/rename",
        {
            "textDocument": text_document(uri),
            "position": position,
            "newName": "Driver",
        },
    )
    assert uri in rename["changes"]


def test_lsp_definition_uses_location_link_when_supported(tmp_path):
    mux_source = (
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )
    mux_path = tmp_path / "mux2.ord"
    mux_path.write_text(mux_source)
    source = (
        "from .mux2 import Mux2 as Stage\n"
        "\n"
        "def helper(x=Stage):\n"
        "    return Stage\n"
    )
    user_path = tmp_path / "user.ord"
    user_path.write_text(source)

    server = initialize_server(
        tmp_path,
        capabilities={
            "textDocument": {
                "definition": {
                    "linkSupport": True,
                },
            },
        },
    )
    uri = user_path.resolve().as_uri()
    assert open_document(server, uri, source) == []

    position = source_offset(source, "Stage", 2)
    definition = request(
        server,
        "textDocument/definition",
        {
            "textDocument": text_document(uri),
            "position": position,
        },
    )

    assert len(definition) == 1
    assert definition[0]["targetUri"] == mux_path.resolve().as_uri()
    assert definition[0]["originSelectionRange"] == {
        "start": position,
        "end": source_offset_after(source, "Stage", 2),
    }
    assert definition[0]["targetSelectionRange"] == {
        "start": source_offset(mux_source, "Mux2"),
        "end": source_offset_after(mux_source, "Mux2"),
    }


def test_lsp_positions_use_utf16_offsets(tmp_path):
    mux_path = tmp_path / "mux2.ord"
    mux_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol -> Symbol:\n"
        "        path a\n"
    )
    source = (
        "from .mux2 import Mux2 as Stage\n"
        "\n"
        "def helper():\n"
        "    return \"😀\", Stage\n"
    )
    user_path = tmp_path / "utf16.ord"
    user_path.write_text(source)

    server = initialize_server(tmp_path)
    uri = user_path.resolve().as_uri()
    assert open_document(server, uri, source) == []

    hover = request(
        server,
        "textDocument/hover",
        {
            "textDocument": text_document(uri),
            "position": utf16_source_offset(source, "Stage", 2),
        },
    )

    assert "Mux2" in hover["contents"]["value"]
    assert hover["range"]["start"] == utf16_source_offset(source, "Stage", 2)


def test_lsp_completion_and_code_actions(tmp_path):
    source = (
        "from ordec.core import *\n"
        "from ordec.lib.generic_mos import Nmos\n"
        "\n"
        "cell Inv:\n"
        "    viewgen schematic -> Schematic:\n"
        "        net vss\n"
        "        Nmos pd:\n"
        "            .s -- vss\n"
    )
    uri = (tmp_path / "inv.ord").resolve().as_uri()
    server = initialize_server(tmp_path)
    assert open_document(server, uri, source) == []

    edited = source.replace(".s -- vss", ".")
    change_document(server, uri, edited)
    completions = request(
        server,
        "textDocument/completion",
        {
            "textDocument": text_document(uri),
            "position": source_offset_after(edited, "            ."),
        },
    )
    assert {"s", "d", "l"} <= {
        item["label"]
        for item in completions
    }

    broken_symbol = (
        "cell Inv:\n"
        "  viewgen symbol -> Symbol:\n"
        "    input a\n"
        "  viewgen schematic -> Schematic:\n"
        "    port a\n"
        "    port y\n"
    )
    broken_uri = (tmp_path / "missing_symbol_port.ord").resolve().as_uri()
    diagnostics = open_document(server, broken_uri, broken_symbol)
    diagnostics[0]["message"] = "wording changed"
    actions = request(
        server,
        "textDocument/codeAction",
        {
            "textDocument": text_document(broken_uri),
            "context": {
                "diagnostics": diagnostics,
            },
        },
    )
    assert [action["title"] for action in actions] == ["Declare `y` in symbol view"]
    assert actions[0]["edit"]["changes"][broken_uri][0]["newText"] == "    input y\n"


def test_lsp_rejects_incremental_did_change(tmp_path):
    server = initialize_server(tmp_path)
    uri = (tmp_path / "incremental.ord").resolve().as_uri()
    source = "cell Inv:\n    viewgen symbol -> Symbol:\n        input a\n"
    assert open_document(server, uri, source) == []

    responses = notify(
        server,
        "textDocument/didChange",
        {
            "textDocument": {
                "uri": uri,
                "version": 2,
            },
            "contentChanges": [{
                "range": {
                    "start": {
                        "line": 0,
                        "character": 0,
                    },
                    "end": {
                        "line": 0,
                        "character": 0,
                    },
                },
                "text": "broken",
            }],
        },
    )

    assert responses[0]["method"] == "window/showMessage"
    assert server.session.documents[uri]["text"] == source


def test_lsp_workspace_folding_selection_and_semantic_tokens(tmp_path):
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

    server = initialize_server(tmp_path)
    uri = path.resolve().as_uri()
    assert open_document(server, uri, source) == []

    workspace_symbols = request(server, "workspace/symbol", {"query": "mux"})
    assert [symbol["name"] for symbol in workspace_symbols] == ["Mux2"]

    folding_ranges = request(
        server,
        "textDocument/foldingRange",
        {
            "textDocument": text_document(uri),
        },
    )
    assert folding_ranges

    selection_ranges = request(
        server,
        "textDocument/selectionRange",
        {
            "textDocument": text_document(uri),
            "positions": [source_offset(source, "symbol")],
        },
    )
    assert selection_ranges[0] is not None

    semantic_tokens = request(
        server,
        "textDocument/semanticTokens/full",
        {
            "textDocument": text_document(uri),
        },
    )
    assert semantic_tokens["data"]

    new_source = source.replace("Mux2", "Mux4")
    path.write_text(new_source)
    notify(
        server,
        "textDocument/didSave",
        {
            "textDocument": {
                "uri": uri,
                "version": 2,
            },
            "text": new_source,
        },
    )
    workspace_symbols = request(server, "workspace/symbol", {"query": "mux"})
    assert [symbol["name"] for symbol in workspace_symbols] == ["Mux4"]


def test_lsp_shutdown_and_unknown_method(tmp_path):
    server = initialize_server(tmp_path)

    unknown = server.handle_message({
        "jsonrpc": "2.0",
        "id": 10,
        "method": "ordec/missing",
        "params": {},
    })[0]
    assert unknown["error"]["code"] == -32601

    assert request(server, "shutdown") is None
    try:
        notify(server, "exit")
    except SystemExit as exc:
        assert exc.code == 0
