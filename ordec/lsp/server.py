# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from pathlib import Path
import json
import sys
from urllib.parse import unquote, urlparse

# ordec imports
from ..analysis import AnalysisPosition
from ..analysis import AnalysisSession
from .code_actions import code_actions


SEMANTIC_TOKEN_TYPES = [
    "namespace",
    "class",
    "function",
    "parameter",
    "variable",
    "property",
]
SEMANTIC_TOKEN_MODIFIERS = [
    "definition",
]

SEMANTIC_TOKEN_TYPE_MAP = {name: i for i, name in enumerate(SEMANTIC_TOKEN_TYPES)}
SEMANTIC_TOKEN_MODIFIER_MAP = {name: i for i, name in enumerate(SEMANTIC_TOKEN_MODIFIERS)}


class OrdecLanguageServer:
    """Minimal stdio LSP server backed by an ``AnalysisSession``."""

    def __init__(self):
        """Initialize server state and LSP method dispatch."""
        self.shutdown_requested = False
        self.session = AnalysisSession()
        self.handlers = {
            "initialize": self.handle_initialize,
            "initialized": self.handle_noop,
            "$/cancelRequest": self.handle_noop,
            "shutdown": self.handle_shutdown,
            "exit": self.handle_exit,
            "textDocument/didOpen": self.handle_did_open,
            "textDocument/didChange": self.handle_did_change,
            "textDocument/didClose": self.handle_did_close,
            "textDocument/didSave": self.handle_did_save,
            "workspace/didChangeWatchedFiles": self.handle_did_change_watched_files,
            "textDocument/documentSymbol": self.handle_document_symbol,
            "textDocument/documentHighlight": self.handle_document_highlight,
            "textDocument/definition": self.handle_definition,
            "textDocument/hover": self.handle_hover,
            "textDocument/references": self.handle_references,
            "textDocument/completion": self.handle_completion,
            "textDocument/codeAction": self.handle_code_action,
            "textDocument/foldingRange": self.handle_folding_range,
            "textDocument/selectionRange": self.handle_selection_range,
            "textDocument/semanticTokens/full": self.handle_semantic_tokens_full,
            "workspace/symbol": self.handle_workspace_symbol,
            "textDocument/prepareRename": self.handle_prepare_rename,
            "textDocument/rename": self.handle_rename,
        }

    def handle_message(self, message):
        """Route one decoded JSON-RPC message to its LSP handler."""
        method = message.get("method")
        if method is None:
            return []

        handler = self.handlers.get(method)
        if handler is None:
            return self.method_not_found(message)

        return handler(message)

    def result_response(self, message, result):
        """Build a JSON-RPC success response for a request message."""
        return [{
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": result,
        }]

    def error_response(self, message, code, value):
        """Build a JSON-RPC error response for a request message."""
        return [{
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": code,
                "message": value,
            },
        }]

    def method_not_found(self, message):
        """Return an unknown-method error for requests and ignore notifications."""
        if message.get("id") is None:
            return []

        return self.error_response(
            message,
            -32601,
            "Method not found: {}".format(message.get("method")),
        )

    def handle_noop(self, message):
        """Handle notifications that require no server action."""
        return []

    def handle_initialize(self, message):
        params = message.get("params", {})
        root_path = None
        if params.get("rootUri"):
            parsed_uri = urlparse(params["rootUri"])
            if parsed_uri.scheme == "file":
                root_path = str(Path(unquote(parsed_uri.path)))
        elif params.get("rootPath"):
            root_path = params["rootPath"]

        self.session = AnalysisSession(workspace_root=root_path)
        return self.result_response(message, {
            "serverInfo": {
                "name": "ordec-lsp",
            },
            "capabilities": {
                "textDocumentSync": {
                    "openClose": True,
                    "change": 1,
                    "save": {
                        "includeText": True,
                    },
                },
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
                    "triggerCharacters": [".", "$"],
                },
                "codeActionProvider": True,
                "foldingRangeProvider": True,
                "selectionRangeProvider": True,
                "semanticTokensProvider": {
                    "legend": {
                        "tokenTypes": list(SEMANTIC_TOKEN_TYPES),
                        "tokenModifiers": list(SEMANTIC_TOKEN_MODIFIERS),
                    },
                    "full": True,
                },
            },
        })

    def handle_shutdown(self, message):
        self.shutdown_requested = True
        return self.result_response(message, None)

    def handle_exit(self, message):
        raise SystemExit(0 if self.shutdown_requested else 1)

    def handle_did_open(self, message):
        params = message.get("params", {})
        text_document = params["textDocument"]
        self.session.open_document(
            text_document["uri"],
            text_document["text"],
            version=text_document.get("version"),
        )
        return [self.publish_diagnostics(text_document["uri"])]

    def handle_did_change(self, message):
        params = message.get("params", {})
        text_document = params["textDocument"]
        content_changes = params.get("contentChanges", [])
        if not content_changes:
            return []

        self.session.update_document(
            text_document["uri"],
            content_changes[-1]["text"],
            version=text_document.get("version"),
        )
        return [self.publish_diagnostics(text_document["uri"])]

    def handle_did_close(self, message):
        text_document = message.get("params", {})["textDocument"]
        self.session.close_document(text_document["uri"])
        return [{
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": text_document["uri"],
                "diagnostics": [],
            },
        }]

    def handle_did_save(self, message):
        params = message.get("params", {})
        text_document = params["textDocument"]
        uri = text_document["uri"]
        if "text" in params:
            self.session.update_document(
                uri,
                params["text"],
                version=text_document.get("version"),
            )
        else:
            self.session.invalidate_uri(uri)
        return [self.publish_diagnostics(uri)]

    def handle_did_change_watched_files(self, message):
        for change in message.get("params", {}).get("changes", []):
            self.session.invalidate_uri(change["uri"])
        return []

    def handle_document_symbol(self, message):
        uri = message.get("params", {})["textDocument"]["uri"]
        analysis = self.session.analyze(uri)
        result = []
        for symbol in analysis.symbols:
            result.append({
                "name": symbol.name,
                "kind": self.symbol_kind(symbol.kind),
                "range": self.lsp_range(symbol.range),
                "selectionRange": self.lsp_range(symbol.selection_range),
            })

        return self.result_response(message, result)

    def handle_document_highlight(self, message):
        params = message.get("params", {})
        uri = params["textDocument"]["uri"]
        position = self.analysis_position(params["position"])
        result = []
        for highlight in self.session.document_highlights(uri, position):
            result.append({
                "range": self.lsp_range(highlight["range"]),
                "kind": self.document_highlight_kind(highlight["kind"]),
            })
        return self.result_response(message, result)

    def handle_definition(self, message):
        params = message.get("params", {})
        uri = params["textDocument"]["uri"]
        position = self.analysis_position(params["position"])
        definition = self.session.definition(uri, position)
        result = None
        if definition is not None:
            result = {
                "uri": definition["uri"],
                "range": self.lsp_range(definition["selection_range"]),
            }
        return self.result_response(message, result)

    def handle_hover(self, message):
        params = message.get("params", {})
        uri = params["textDocument"]["uri"]
        position = self.analysis_position(params["position"])
        hover = self.session.hover(uri, position)
        result = None
        if hover is not None:
            result = {
                "contents": {
                    "kind": "plaintext",
                    "value": hover["contents"],
                },
                "range": self.lsp_range(hover["range"]),
            }
        return self.result_response(message, result)

    def handle_references(self, message):
        params = message.get("params", {})
        uri = params["textDocument"]["uri"]
        position = self.analysis_position(params["position"])
        references = self.session.references(uri, position)
        result = []
        for reference in references:
            result.append({
                "uri": reference["uri"],
                "range": self.lsp_range(reference["range"]),
            })
        return self.result_response(message, result)

    def handle_completion(self, message):
        params = message.get("params", {})
        uri = params["textDocument"]["uri"]
        position = self.analysis_position(params["position"])
        completions = self.session.completions(uri, position)
        result = []
        for completion in completions:
            result.append({
                "label": completion["label"],
                "kind": self.completion_kind(completion["kind"]),
                "detail": completion["detail"],
            })
        return self.result_response(message, result)

    def handle_code_action(self, message):
        params = message.get("params", {})
        uri = params["textDocument"]["uri"]
        diagnostics = params.get("context", {}).get("diagnostics", [])
        return self.result_response(
            message,
            code_actions(self.session, uri, diagnostics),
        )

    def handle_folding_range(self, message):
        uri = message.get("params", {})["textDocument"]["uri"]
        result = []
        for folding_range in self.session.folding_ranges(uri):
            entry = {
                "startLine": folding_range["start_line"] - 1,
                "endLine": folding_range["end_line"] - 1,
            }
            if folding_range["kind"] == "imports":
                entry["kind"] = "imports"
            elif folding_range["kind"] == "comment":
                entry["kind"] = "comment"
            result.append(entry)
        return self.result_response(message, result)

    def lsp_selection_range_chain(self, node):
        """Convert a nested analysis selection range chain to LSP shape."""
        lsp_node = {
            "range": self.lsp_range(node["range"]),
        }
        if node["parent"] is not None:
            lsp_node["parent"] = self.lsp_selection_range_chain(node["parent"])
        return lsp_node

    def handle_selection_range(self, message):
        params = message.get("params", {})
        uri = params["textDocument"]["uri"]
        positions = [
            self.analysis_position(pos)
            for pos in params["positions"]
        ]
        selection_ranges = self.session.selection_ranges(uri, positions)
        result = []
        for chain in selection_ranges:
            if chain is None:
                result.append(None)
                continue

            result.append(self.lsp_selection_range_chain(chain))
        return self.result_response(message, result)

    def handle_semantic_tokens_full(self, message):
        uri = message.get("params", {})["textDocument"]["uri"]
        tokens = self.session.semantic_tokens(uri)
        data = []
        prev_line = 0
        prev_char = 0
        for token in tokens:
            line = token["range"].start.line - 1
            char = token["range"].start.character - 1
            length = (
                token["range"].end.character - token["range"].start.character
            )
            token_type = SEMANTIC_TOKEN_TYPE_MAP.get(token["type"], 0)
            modifier_bits = 0
            for modifier in token["modifiers"]:
                bit = SEMANTIC_TOKEN_MODIFIER_MAP.get(modifier)
                if bit is not None:
                    modifier_bits |= 1 << bit

            delta_line = line - prev_line
            delta_char = char if delta_line != 0 else char - prev_char
            data.extend([delta_line, delta_char, length, token_type, modifier_bits])
            prev_line = line
            prev_char = char

        return self.result_response(message, {
            "data": data,
        })

    def handle_workspace_symbol(self, message):
        params = message.get("params", {})
        result = []
        for symbol in self.session.workspace_symbols(params.get("query", "")):
            result.append({
                "name": symbol["name"],
                "kind": self.symbol_kind(symbol["kind"]),
                "location": {
                    "uri": symbol["uri"],
                    "range": self.lsp_range(symbol["selection_range"]),
                },
            })
        return self.result_response(message, result)

    def handle_prepare_rename(self, message):
        params = message.get("params", {})
        uri = params["textDocument"]["uri"]
        position = self.analysis_position(params["position"])
        result = self.session.prepare_rename(uri, position)
        if result is not None:
            result = {
                "range": self.lsp_range(result["range"]),
                "placeholder": result["placeholder"],
            }
        return self.result_response(message, result)

    def handle_rename(self, message):
        params = message.get("params", {})
        uri = params["textDocument"]["uri"]
        position = self.analysis_position(params["position"])
        try:
            changes = self.session.rename(uri, position, params["newName"])
        except ValueError as exc:
            return self.error_response(message, -32602, str(exc))

        result = None
        if changes is not None:
            result = {
                "changes": dict(
                    (change_uri, [
                        {
                            "range": self.lsp_range(change["range"]),
                            "newText": change["new_text"],
                        }
                        for change in uri_changes
                    ])
                    for change_uri, uri_changes in changes.items()
                ),
            }
        return self.result_response(message, result)

    def publish_diagnostics(self, uri: str):
        """Build a publishDiagnostics notification for a document URI."""
        analysis = self.session.analyze(uri)
        diagnostics = []
        for diagnostic in self.session.diagnostics(uri):
            diagnostics.append({
                "range": self.lsp_range(diagnostic.range),
                "severity": self.diagnostic_severity(diagnostic.severity),
                "message": diagnostic.message,
                "code": diagnostic.code,
            })

        params = {
            "uri": uri,
            "diagnostics": diagnostics,
        }
        if analysis.version is not None:
            params["version"] = analysis.version

        return {
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": params,
        }

    def analysis_position(self, position):
        """Convert a zero-based LSP position to a one-based analysis position."""
        return AnalysisPosition(
            line=position["line"] + 1,
            character=position["character"] + 1,
        )

    def lsp_position(self, position):
        """Convert a one-based analysis position to a zero-based LSP position."""
        return {
            "line": position.line - 1,
            "character": position.character - 1,
        }

    def lsp_range(self, value_range):
        """Convert an analysis range to an LSP range."""
        return {
            "start": self.lsp_position(value_range.start),
            "end": self.lsp_position(value_range.end),
        }

    def diagnostic_severity(self, severity: str):
        """Map analysis diagnostic severities to LSP severity constants."""
        if severity == "error":
            return 1
        if severity == "warning":
            return 2
        if severity == "information":
            return 3
        if severity == "hint":
            return 4
        return 3

    def symbol_kind(self, kind: str):
        """Map analysis symbol kinds to LSP symbol kind constants."""
        if kind == "class":
            return 5
        if kind == "function":
            return 12
        if kind == "context":
            return 13
        if kind in ("path", "net"):
            return 13
        return 13

    def completion_kind(self, kind: str):
        """Map analysis completion kinds to LSP completion item constants."""
        if kind == "class":
            return 7
        if kind == "function":
            return 3
        if kind in ("parameter", "variable"):
            return 6
        if kind == "module":
            return 9
        if kind == "keyword":
            return 14
        if kind in ("path", "net", "context"):
            return 6
        return 1

    def document_highlight_kind(self, kind: str):
        """Map analysis highlight kinds to LSP highlight constants."""
        if kind == "read":
            return 2
        if kind == "write":
            return 3
        return 1


def read_message(input_stream):
    """Read one Content-Length framed JSON-RPC message from a byte stream."""
    headers = dict()
    while True:
        header_line = input_stream.readline()
        if header_line == b"":
            return None

        header_line = header_line.decode("ascii").strip()
        if header_line == "":
            break

        key, value = header_line.split(":", 1)
        headers[key.lower()] = value.strip()

    content_length = int(headers["content-length"])
    body = input_stream.read(content_length)
    if body == b"":
        return None
    return json.loads(body.decode("utf-8"))


def write_message(output_stream, message):
    """Write one Content-Length framed JSON-RPC message to a byte stream."""
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    output_stream.write("Content-Length: {}\r\n\r\n".format(len(body)).encode("ascii"))
    output_stream.write(body)
    output_stream.flush()


def main():
    """Run the ORDeC language server over stdin/stdout."""
    server = OrdecLanguageServer()
    input_stream = sys.stdin.buffer
    output_stream = sys.stdout.buffer

    while True:
        message = read_message(input_stream)
        if message is None:
            break

        try:
            responses = server.handle_message(message)
        except SystemExit as exc:
            raise exc
        except Exception as exc:  # pragma: no cover - safety net for stdio server
            if message.get("id") is not None:
                responses = [{
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {
                        "code": -32603,
                        "message": str(exc),
                    },
                }]
            else:
                responses = []

        for response in responses:
            write_message(output_stream, response)
