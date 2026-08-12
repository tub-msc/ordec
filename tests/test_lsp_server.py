# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import io
import json
import queue
import subprocess
import sys

from ordec.lsp.server import OrdLanguageServer, read_messages, serve


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
        "typeDefinitionProvider",
        "hoverProvider",
        "referencesProvider",
        "renameProvider",
        "completionProvider",
        "signatureHelpProvider",
        "codeActionProvider",
        "foldingRangeProvider",
        "selectionRangeProvider",
        "semanticTokensProvider",
        "inlayHintProvider",
        "callHierarchyProvider",
    ):
        assert capability in capabilities

    assert capabilities["completionProvider"]["triggerCharacters"] == [".", "$"]
    assert capabilities["signatureHelpProvider"]["triggerCharacters"] == ["(", ","]
    assert capabilities["textDocumentSync"]["change"] == 2
    assert capabilities["positionEncoding"] == "utf-16"


def test_lsp_document_lifecycle_and_diagnostics(tmp_path):
    server = initialize_server(tmp_path)
    uri = (tmp_path / "broken.ord").resolve().as_uri()
    broken_source = "from .missing import Foo\n"

    diagnostics = open_document(server, uri, broken_source)
    assert [diagnostic["code"] for diagnostic in diagnostics] == ["unresolved-import"]

    fixed_source = "cell Inv:\n    viewgen symbol(self) -> Symbol:\n        path a\n"
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
        "    viewgen symbol(self) -> Symbol:\n"
        "        input a\n"
    )
    top_source = (
        "from .device import Device\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic(self) -> Schematic:\n"
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
        "    viewgen symbol(self) -> Symbol:\n"
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


def test_lsp_deleted_file_with_cold_index_refreshes_open_documents(tmp_path):
    device_path = tmp_path / "device.ord"
    device_path.write_text(
        "cell Device:\n"
        "    viewgen symbol(self) -> Symbol:\n"
        "        input a\n"
    )
    top_source = (
        "from .device import Device\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic(self) -> Schematic:\n"
        "        Device inst:\n"
        "            .a -- net_a\n"
    )
    top_path = tmp_path / "top.ord"
    top_path.write_text(top_source)

    server = initialize_server(tmp_path)
    top_uri = top_path.resolve().as_uri()
    device_uri = device_path.resolve().as_uri()
    assert open_document(server, top_uri, top_source) == []

    # An import graph built only after the deletion has no edge to the
    # missing file, so the importer must be refreshed regardless.
    device_path.unlink()
    server.session.invalidate_workspace_index()
    responses = notify(
        server,
        "workspace/didChangeWatchedFiles",
        {
            "changes": [{
                "uri": device_uri,
                "type": 3,
            }],
        },
    )

    assert [response["params"]["uri"] for response in responses] == [top_uri]
    assert "unresolved-import" in {
        diagnostic["code"]
        for diagnostic in responses[0]["params"]["diagnostics"]
    }


def test_lsp_navigation_references_rename_and_symbols(tmp_path):
    mux_path = tmp_path / "mux2.ord"
    mux_path.write_text(
        "cell Mux2:\n"
        "    viewgen symbol(self) -> Symbol:\n"
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
    # Three Stage tokens, the imported Mux2 token, and the definition.
    assert len(references) == 5

    highlights = request(
        server,
        "textDocument/documentHighlight",
        {
            "textDocument": text_document(uri),
            "position": position,
        },
    )
    assert len(highlights) == 4

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
        "    viewgen symbol(self) -> Symbol:\n"
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
        "    viewgen symbol(self) -> Symbol:\n"
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
        "    viewgen schematic(self) -> Schematic:\n"
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
    # No identifier prefix is typed after the dot, so the replacement edit
    # collapses to the cursor position.
    cursor = source_offset_after(edited, "            .")
    assert completions[0]["textEdit"]["range"] == {
        "start": cursor,
        "end": cursor,
    }

    broken_symbol = (
        "cell Inv:\n"
        "  viewgen symbol(self) -> Symbol:\n"
        "    input a\n"
        "  viewgen schematic(self) -> Schematic:\n"
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


def test_lsp_applies_incremental_did_change(tmp_path):
    server = initialize_server(tmp_path)
    uri = (tmp_path / "incremental.ord").resolve().as_uri()
    source = "cell Inv:\n    viewgen symbol(self) -> Symbol:\n        input a\n"
    assert open_document(server, uri, source) == []

    responses = notify(
        server,
        "textDocument/didChange",
        {
            "textDocument": {
                "uri": uri,
                "version": 2,
            },
            "contentChanges": [
                {
                    "range": {
                        "start": {
                            "line": 0,
                            "character": 5,
                        },
                        "end": {
                            "line": 0,
                            "character": 8,
                        },
                    },
                    "text": "Buf",
                },
                {
                    "range": {
                        "start": {
                            "line": 3,
                            "character": 0,
                        },
                        "end": {
                            "line": 3,
                            "character": 0,
                        },
                    },
                    "text": "        input b\n",
                },
            ],
        },
    )

    assert responses[0]["method"] == "textDocument/publishDiagnostics"
    assert responses[0]["params"]["diagnostics"] == []
    assert server.session.documents[uri]["text"] == (
        "cell Buf:\n"
        "    viewgen symbol(self) -> Symbol:\n"
        "        input a\n"
        "        input b\n"
    )


def test_lsp_hover_markdown_and_completion_documentation(tmp_path):
    (tmp_path / "helpers.py").write_text(
        'def scale(value, factor=2):\n'
        '    """Scale a value by a factor."""\n'
        '    return value * factor\n'
    )
    source = (
        "from helpers import scale\n"
        "\n"
        "def wrap():\n"
        "    return scale\n"
    )
    user_path = tmp_path / "user.ord"
    user_path.write_text(source)

    server = initialize_server(
        tmp_path,
        capabilities={
            "textDocument": {
                "hover": {
                    "contentFormat": ["markdown", "plaintext"],
                },
            },
        },
    )
    uri = user_path.resolve().as_uri()
    assert open_document(server, uri, source) == []

    hover = request(
        server,
        "textDocument/hover",
        {
            "textDocument": text_document(uri),
            "position": source_offset(source, "scale", 2),
        },
    )
    assert hover["contents"]["kind"] == "markdown"
    assert "def scale(value, factor=2)" in hover["contents"]["value"]
    assert "Scale a value by a factor." in hover["contents"]["value"]

    completions = request(
        server,
        "textDocument/completion",
        {
            "textDocument": text_document(uri),
            "position": source_offset_after(source, "    return scale"),
        },
    )
    scale_items = [item for item in completions if item["label"] == "scale"]
    assert scale_items[0]["documentation"]["value"] == "Scale a value by a factor."
    assert all("sortText" in item for item in completions)

    # Items replace the typed identifier prefix through an explicit edit.
    assert scale_items[0]["textEdit"] == {
        "range": {
            "start": source_offset(source, "scale", 2),
            "end": source_offset_after(source, "    return scale"),
        },
        "newText": "scale",
    }


def test_lsp_document_symbols_hierarchical_and_flat(tmp_path):
    source = (
        "cell Inv:\n"
        "    viewgen symbol(self) -> Symbol:\n"
        "        input a\n"
        "        output y\n"
    )
    uri = (tmp_path / "inv.ord").resolve().as_uri()

    flat_server = initialize_server(tmp_path)
    assert open_document(flat_server, uri, source) == []
    flat_symbols = request(
        flat_server,
        "textDocument/documentSymbol",
        {
            "textDocument": text_document(uri),
        },
    )
    assert flat_symbols[0]["location"]["uri"] == uri

    server = initialize_server(
        tmp_path,
        capabilities={
            "textDocument": {
                "documentSymbol": {
                    "hierarchicalDocumentSymbolSupport": True,
                },
            },
        },
    )
    assert open_document(server, uri, source) == []
    symbols = request(
        server,
        "textDocument/documentSymbol",
        {
            "textDocument": text_document(uri),
        },
    )

    assert [symbol["name"] for symbol in symbols] == ["Inv"]
    viewgens = symbols[0]["children"]
    assert [symbol["name"] for symbol in viewgens] == ["symbol"]
    assert [symbol["name"] for symbol in viewgens[0]["children"]] == [
        "input a",
        "output y",
    ]


def test_lsp_signature_help(tmp_path):
    source = (
        "from ordec.core import *\n"
        "from ordec.lib.generic_mos import Nmos\n"
        "\n"
        "cell Inv:\n"
        "    viewgen schematic(self) -> Schematic:\n"
        "        net vss\n"
        "        Nmos(w=4u, l=400n) pd:\n"
        "            .s -- vss\n"
        "        x = helper(4u)\n"
        "\n"
        "def helper(gain, offset=1):\n"
        "    return gain\n"
    )
    uri = (tmp_path / "inv.ord").resolve().as_uri()
    server = initialize_server(tmp_path)
    assert open_document(server, uri, source) == []

    signature_help = request(
        server,
        "textDocument/signatureHelp",
        {
            "textDocument": text_document(uri),
            "position": source_offset_after(source, "Nmos(w="),
        },
    )
    signature = signature_help["signatures"][0]
    assert signature["label"] == "Nmos(l=R('1u'), w=R('1u'))"
    assert [parameter["label"] for parameter in signature["parameters"]] == [
        "l=R('1u')",
        "w=R('1u')",
    ]
    assert signature_help["activeParameter"] == 1

    signature_help = request(
        server,
        "textDocument/signatureHelp",
        {
            "textDocument": text_document(uri),
            "position": source_offset_after(source, "helper(4"),
        },
    )
    signature = signature_help["signatures"][0]
    assert signature["label"] == "helper(gain, offset)"
    assert signature_help["activeParameter"] == 0

    outside_call = request(
        server,
        "textDocument/signatureHelp",
        {
            "textDocument": text_document(uri),
            "position": source_offset(source, "net vss"),
        },
        message_id=2,
    )
    assert outside_call is None


def test_lsp_type_definition_and_inlay_hints(tmp_path):
    device_source = (
        "cell Device:\n"
        "    viewgen symbol(self) -> Symbol:\n"
        "        input a\n"
    )
    (tmp_path / "device.ord").write_text(device_source)
    top_source = (
        "from .device import Device\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic(self) -> Schematic:\n"
        "        net vdd\n"
        "        Device inst:\n"
        "            .a -- vdd\n"
        "\n"
        "def helper():\n"
        "    d = Device()\n"
        "    return d\n"
    )
    (tmp_path / "top.ord").write_text(top_source)
    server = initialize_server(tmp_path)
    top_uri = (tmp_path / "top.ord").resolve().as_uri()
    device_uri = (tmp_path / "device.ord").resolve().as_uri()
    assert open_document(server, top_uri, top_source) == []

    type_definition = request(
        server,
        "textDocument/typeDefinition",
        {
            "textDocument": text_document(top_uri),
            "position": source_offset(top_source, "inst"),
        },
    )
    assert type_definition["uri"] == device_uri
    assert type_definition["range"]["start"] == source_offset(device_source, "Device")

    hints = request(
        server,
        "textDocument/inlayHint",
        {
            "textDocument": text_document(top_uri),
            "range": {
                "start": {
                    "line": 0,
                    "character": 0,
                },
                "end": {
                    "line": 20,
                    "character": 0,
                },
            },
        },
    )
    assert len(hints) == 1
    assert hints[0]["label"] == ": Device"
    assert hints[0]["position"] == source_offset_after(top_source, "    d")


def test_lsp_call_hierarchy(tmp_path):
    (tmp_path / "device.ord").write_text(
        "cell Device:\n"
        "    viewgen symbol(self) -> Symbol:\n"
        "        input a\n"
    )
    top_source = (
        "from .device import Device\n"
        "\n"
        "cell Top:\n"
        "    viewgen schematic(self) -> Schematic:\n"
        "        net vdd\n"
        "        Device inst:\n"
        "            .a -- vdd\n"
        "\n"
        "def helper():\n"
        "    d = Device()\n"
        "    return d\n"
    )
    (tmp_path / "top.ord").write_text(top_source)
    server = initialize_server(tmp_path)
    top_uri = (tmp_path / "top.ord").resolve().as_uri()
    device_uri = (tmp_path / "device.ord").resolve().as_uri()
    assert open_document(server, top_uri, top_source) == []

    items = request(
        server,
        "textDocument/prepareCallHierarchy",
        {
            "textDocument": text_document(top_uri),
            "position": source_offset(top_source, "Device", 2),
        },
    )
    assert len(items) == 1
    assert items[0]["name"] == "Device"
    assert items[0]["uri"] == device_uri

    incoming = request(
        server,
        "callHierarchy/incomingCalls",
        {
            "item": items[0],
        },
    )
    callers = [call["from"]["name"] for call in incoming]
    assert "Top" in callers
    assert "helper" in callers
    top_call = next(call for call in incoming if call["from"]["name"] == "Top")
    assert top_call["fromRanges"][0]["start"] == source_offset(top_source, "Device", 2)

    top_items = request(
        server,
        "textDocument/prepareCallHierarchy",
        {
            "textDocument": text_document(top_uri),
            "position": source_offset(top_source, "Top"),
        },
    )
    outgoing = request(
        server,
        "callHierarchy/outgoingCalls",
        {
            "item": top_items[0],
        },
    )
    assert [call["to"]["name"] for call in outgoing] == ["Device"]
    assert outgoing[0]["fromRanges"][0]["start"] == source_offset(top_source, "Device", 2)


def test_lsp_workspace_folding_selection_and_semantic_tokens(tmp_path):
    source = (
        "import math\n"
        "\n"
        "cell Mux2:\n"
        "    viewgen symbol(self) -> Symbol:\n"
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
    # Folds end at the last content line of each block: trailing blank
    # lines and the next construct's header stay visible.
    assert folding_ranges == [
        {"startLine": 2, "endLine": 4},
        {"startLine": 3, "endLine": 4},
        {"startLine": 6, "endLine": 8},
    ]

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


def test_lsp_workspace_scan_skips_hidden_and_dependency_dirs(tmp_path):
    def cell_source(name):
        return (
            "cell {}:\n"
            "    viewgen symbol(self) -> Symbol:\n"
            "        input a\n"
        ).format(name)

    (tmp_path / "device.ord").write_text(cell_source("Device"))
    nested = tmp_path / "designs"
    nested.mkdir()
    (nested / "buf.ord").write_text(cell_source("Buf"))

    hidden = tmp_path / ".git"
    hidden.mkdir()
    (hidden / "junk.ord").write_text(cell_source("HiddenJunk"))
    dependency = tmp_path / "node_modules" / "pkg"
    dependency.mkdir(parents=True)
    (dependency / "junk.ord").write_text(cell_source("DependencyJunk"))

    server = initialize_server(tmp_path)
    symbols = request(server, "workspace/symbol", {"query": ""})
    assert sorted(symbol["name"] for symbol in symbols) == ["Buf", "Device"]


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


def test_lsp_subprocess_exit_does_not_abort():
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "shutdown"},
        {"jsonrpc": "2.0", "method": "exit"},
    ]
    framed = b""
    for message in messages:
        body = json.dumps(message).encode("utf-8")
        framed += b"Content-Length: %d\r\n\r\n" % len(body) + body

    result = subprocess.run(
        [sys.executable, "-c", "from ordec.lsp import main; main()"],
        input=framed,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert b"fatal python error" not in result.stderr.lower()
    assert b"Content-Length:" in result.stdout


def decode_messages(data):
    """Decode framed server output into a list of messages."""
    decoded = []
    while data:
        header, separator, rest = data.partition(b"\r\n\r\n")
        assert separator
        length = int(header.split(b":")[1])
        decoded.append(json.loads(rest[:length]))
        data = rest[length:]
    return decoded


def run_serve(messages):
    """Run serve() over prefilled messages and return the decoded output."""
    message_queue = queue.SimpleQueue()
    for message in messages:
        message_queue.put(message)
    message_queue.put(None)

    output_stream = io.BytesIO()
    serve(OrdLanguageServer(), message_queue, output_stream)
    return decode_messages(output_stream.getvalue())


def test_lsp_serve_cancels_queued_requests():
    output = run_serve([
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "textDocument/documentSymbol",
            "params": {"textDocument": {"uri": "file:///tmp/missing.ord"}},
        },
        {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 1}},
        {"jsonrpc": "2.0", "id": 2, "method": "shutdown"},
    ])

    responses = {message.get("id"): message for message in output}
    assert responses[1]["error"]["code"] == -32800
    assert "result" not in responses[1]
    assert responses[2]["result"] is None


def test_lsp_selection_range_missing_document_returns_empty_ranges(tmp_path):
    server = initialize_server(tmp_path)
    uri = (tmp_path / "missing.ord").resolve().as_uri()
    position = {"line": 2, "character": 4}

    selection_ranges = request(
        server,
        "textDocument/selectionRange",
        {
            "textDocument": text_document(uri),
            "positions": [position],
        },
    )

    # Null items crash vscode-languageclient, so unresolvable positions
    # yield empty ranges at the requested position instead.
    assert selection_ranges == [{"range": {"start": position, "end": position}}]


def test_lsp_serve_drops_cancels_for_answered_requests():
    def document_symbol_request():
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "textDocument/documentSymbol",
            "params": {"textDocument": {"uri": "file:///tmp/missing.ord"}},
        }

    class BatchedMessageQueue:
        """Deliver scripted batches so a cancel arrives after dispatch."""
        def __init__(self, batches):
            self.batches = batches
            self.current = []

        def get(self):
            if not self.current:
                self.current = self.batches.pop(0)
            return self.current.pop(0)

        def get_nowait(self):
            if not self.current:
                raise queue.Empty
            return self.current.pop(0)

    message_queue = BatchedMessageQueue([
        [document_symbol_request()],
        [{"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 1}}],
        [document_symbol_request(), None],
    ])
    output_stream = io.BytesIO()
    serve(OrdLanguageServer(), message_queue, output_stream)

    # The late cancel is dropped, so the request legally reusing id 1
    # is answered normally instead of being rejected as canceled.
    responses = decode_messages(output_stream.getvalue())
    assert [message.get("id") for message in responses] == [1, 1]
    assert all("error" not in message for message in responses)


def test_lsp_serve_coalesces_did_change_bursts():
    uri = "file:///tmp/burst.ord"

    def did_change(version, text):
        return {
            "jsonrpc": "2.0",
            "method": "textDocument/didChange",
            "params": {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": [{"text": text}],
            },
        }

    output = run_serve([
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "ord",
                    "version": 1,
                    "text": "",
                },
            },
        },
        did_change(2, "cell (\n"),
        did_change(3, ""),
    ])

    published = [
        message for message in output
        if message.get("method") == "textDocument/publishDiagnostics"
    ]
    # One publish for didOpen, then one for the newest change only. The
    # newest version is clean, so a stale analysis of the broken
    # intermediate version would show up as leftover diagnostics here.
    assert len(published) == 2
    assert published[1]["params"]["diagnostics"] == []


def test_lsp_serve_keeps_incremental_did_change_bursts():
    uri = "file:///tmp/burst.ord"

    def did_change(version, changes):
        return {
            "jsonrpc": "2.0",
            "method": "textDocument/didChange",
            "params": {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": changes,
            },
        }

    start_of_document = {
        "start": {"line": 0, "character": 0},
        "end": {"line": 0, "character": 0},
    }
    output = run_serve([
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "ord",
                    "version": 1,
                    "text": "cell (\n",
                },
            },
        },
        did_change(2, [{"text": ""}]),
        did_change(3, [{"range": start_of_document, "text": "cell (\n"}]),
    ])

    published = [
        message for message in output
        if message.get("method") == "textDocument/publishDiagnostics"
    ]
    # The incremental change builds on the full replacement before it, so
    # neither may be skipped: broken open, clean replacement, broken edit.
    assert len(published) == 3
    assert published[0]["params"]["diagnostics"] != []
    assert published[1]["params"]["diagnostics"] == []
    assert published[2]["params"]["diagnostics"] != []


def test_lsp_malformed_frame_reports_parse_error_and_keeps_serving():
    body = b"{not json}"
    shutdown = json.dumps(
        {"jsonrpc": "2.0", "id": 2, "method": "shutdown"}
    ).encode("utf-8")
    stream = io.BytesIO(
        "Content-Length: {}\r\n\r\n".format(len(body)).encode("ascii") + body
        + "Content-Length: {}\r\n\r\n".format(len(shutdown)).encode("ascii")
        + shutdown
    )
    message_queue = queue.SimpleQueue()
    read_messages(stream, message_queue)

    output_stream = io.BytesIO()
    serve(OrdLanguageServer(), message_queue, output_stream)

    # The malformed body is answered with a parse error (id null, as
    # JSON-RPC prescribes for unknown request ids) and the well-formed
    # frame behind it is still served instead of shutting down.
    responses = decode_messages(output_stream.getvalue())
    assert responses[0]["id"] is None
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["id"] == 2


def test_lsp_incremental_change_handles_cr_line_breaks():
    server = OrdLanguageServer()
    text = "line0\rline1\rline2\r"
    change = {
        "range": {
            "start": {"line": 2, "character": 0},
            "end": {"line": 2, "character": 5},
        },
        "text": "third",
    }
    # Lone \r counts as a line break everywhere else in the package, so
    # change offsets must agree or the buffer diverges from the editor.
    assert server.apply_incremental_change(text, change) == "line0\rline1\rthird\r"


def test_lsp_did_save_keeps_document_version(tmp_path):
    server = initialize_server(tmp_path)
    uri = (tmp_path / "keep.ord").resolve().as_uri()
    source = (
        "cell Keep:\n"
        "    viewgen symbol(self) -> Symbol:\n"
        "        input a\n"
    )
    open_document(server, uri, source, version=7)

    responses = notify(
        server,
        "textDocument/didSave",
        {
            "textDocument": {"uri": uri},
            "text": source,
        },
    )
    # didSave identifies the document without a version, so the version
    # from didOpen/didChange must survive the save.
    assert responses[0]["params"]["version"] == 7
