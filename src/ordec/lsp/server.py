# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""Stdio LSP server for ORD, written against the protocol directly.

We are not using pygls for now, because it would replace only a small part
of this file (message framing, the serve loop, document sync; a few hundred
lines). Most of this file translates analysis results into LSP response
shapes, and that code would have to be written with pygls too. More
importantly, serve() handles one request at a time and drains the input
queue in between, which lets it cancel queued requests and collapse
didChange bursts without threads or async. That way, the AnalysisSession
stays single-threaded by construction. pygls would force a choice between
sync handlers (losing that) and asyncio handlers (making the session deal
with concurrency).

We are not using lsprotocol (the typed LSP classes, without pygls) for now,
because it would add two runtime dependencies (attrs, cattrs) where we
currently need none, and its main benefit, catching wrong response shapes
via types, needs a type checker, which this project does not run. Worth
revisiting if we start type-checking this package or the number of
supported LSP features grows a lot. Until then, plain dicts and tests cover
the same ground.
"""

# standard imports
from collections import deque
from pathlib import Path
import json
import queue
import sys
import threading

# ordec imports
from .analysis import AnalysisPosition, AnalysisRange, AnalysisSession, file_uri_to_path
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

DIAGNOSTIC_SEVERITY_MAP = {
    "error": 1,
    "warning": 2,
    "information": 3,
    "hint": 4,
}
SYMBOL_KIND_MAP = {
    "module": 2,
    "class": 5,
    "function": 12,
    "context": 13,
    "path": 13,
    "net": 13,
}
INLAY_HINT_KIND_TYPE = 1
COMPLETION_KIND_MAP = {
    "class": 7,
    "function": 3,
    "parameter": 6,
    "variable": 6,
    "module": 9,
    "keyword": 14,
    "path": 6,
    "net": 6,
    "context": 6,
}
DOCUMENT_HIGHLIGHT_KIND_MAP = {
    "read": 2,
    "write": 3,
}
SHOW_MESSAGE_SEVERITY_MAP = {
    "error": 1,
    "warning": 2,
    "info": 3,
    "log": 4,
}


class OrdLanguageServer:
    """Minimal stdio LSP server backed by an ``AnalysisSession``."""
    def __init__(self):
        """Initialize server state and LSP method dispatch."""
        self.shutdown_requested = False
        self.position_encoding = "utf-16"
        self.definition_link_support = False
        self.hover_markdown_support = False
        self.hierarchical_symbol_support = False
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
            "textDocument/typeDefinition": self.handle_type_definition,
            "textDocument/hover": self.handle_hover,
            "textDocument/references": self.handle_references,
            "textDocument/completion": self.handle_completion,
            "textDocument/signatureHelp": self.handle_signature_help,
            "textDocument/codeAction": self.handle_code_action,
            "textDocument/foldingRange": self.handle_folding_range,
            "textDocument/selectionRange": self.handle_selection_range,
            "textDocument/semanticTokens/full": self.handle_semantic_tokens_full,
            "textDocument/inlayHint": self.handle_inlay_hint,
            "textDocument/prepareCallHierarchy": self.handle_prepare_call_hierarchy,
            "callHierarchy/incomingCalls": self.handle_incoming_calls,
            "callHierarchy/outgoingCalls": self.handle_outgoing_calls,
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

    def canonical_uri(self, uri: str):
        """Return the session-canonical URI for file-backed documents."""
        return self.session.canonical_uri(uri)

    def text_document_uri(self, params):
        """Return the canonical URI from LSP textDocument params."""
        return self.canonical_uri(params["textDocument"]["uri"])

    def message_text_document_uri(self, message):
        """Return the canonical URI from an LSP message's textDocument params."""
        return self.text_document_uri(message.get("params", {}))

    def file_change_uri(self, change):
        """Return the canonical URI from a watched-file change entry."""
        return self.canonical_uri(change["uri"])

    def initialize_root_path(self, params):
        """Return the resolved workspace root path from initialize params."""
        if params.get("rootUri"):
            root_path = file_uri_to_path(params["rootUri"])
            if root_path is not None:
                return str(root_path)

        if params.get("rootPath"):
            return str(Path(params["rootPath"]).resolve())

        return None

    def handle_initialize(self, message):
        params = message.get("params", {})
        capabilities = params.get("capabilities", {})
        text_document_capabilities = capabilities.get("textDocument", {})
        definition_capabilities = text_document_capabilities.get("definition", {})
        self.definition_link_support = bool(definition_capabilities.get("linkSupport"))
        hover_capabilities = text_document_capabilities.get("hover", {})
        self.hover_markdown_support = "markdown" in (
            hover_capabilities.get("contentFormat") or []
        )
        symbol_capabilities = text_document_capabilities.get("documentSymbol", {})
        self.hierarchical_symbol_support = bool(
            symbol_capabilities.get("hierarchicalDocumentSymbolSupport")
        )
        self.session = AnalysisSession(workspace_root=self.initialize_root_path(params))
        return self.result_response(message, {
            "serverInfo": {
                "name": "ordec-lsp",
            },
            "capabilities": {
                "positionEncoding": self.position_encoding,
                "textDocumentSync": {
                    "openClose": True,
                    "change": 2,
                    "save": {
                        "includeText": True,
                    },
                },
                "documentSymbolProvider": True,
                "documentHighlightProvider": True,
                "workspaceSymbolProvider": True,
                "definitionProvider": True,
                "typeDefinitionProvider": True,
                "hoverProvider": True,
                "referencesProvider": True,
                "renameProvider": {
                    "prepareProvider": True,
                },
                "completionProvider": {
                    "resolveProvider": False,
                    "triggerCharacters": [".", "$"],
                },
                "signatureHelpProvider": {
                    "triggerCharacters": ["(", ","],
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
                "inlayHintProvider": True,
                "callHierarchyProvider": True,
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
        uri = self.text_document_uri(params)
        self.session.open_document(
            uri,
            text_document["text"],
            version=text_document.get("version"),
        )
        return [self.publish_diagnostics(uri)]

    def handle_did_change(self, message):
        params = message.get("params", {})
        text_document = params["textDocument"]
        uri = self.text_document_uri(params)
        content_changes = params.get("contentChanges", [])
        if not content_changes:
            return []

        doc = self.session.documents.get(uri)
        text = doc["text"] if doc is not None else None
        for change in content_changes:
            if "range" not in change:
                text = change["text"]
            elif text is None:
                return [self.show_message(
                    "error",
                    "ORDeC LSP received an incremental change for an unknown document.",
                )]
            else:
                text = self.apply_incremental_change(text, change)

        self.session.update_document(
            uri,
            text,
            version=text_document.get("version"),
        )
        return [self.publish_diagnostics(uri)]

    def apply_incremental_change(self, text: str, change):
        """Apply one range-based LSP content change to document text."""
        start_offset = self.change_offset(text, change["range"]["start"])
        end_offset = self.change_offset(text, change["range"]["end"])
        if end_offset < start_offset:
            end_offset = start_offset
        return text[:start_offset] + change["text"] + text[end_offset:]

    def change_offset(self, text: str, position):
        """Convert a zero-based LSP position to a character offset in text."""
        line_index = max(0, position["line"])
        lines = text.split("\n")
        if line_index >= len(lines):
            return len(text)

        line = lines[line_index]
        character = max(0, position["character"])
        if self.position_encoding == "utf-16":
            character = self.utf16_offset_to_codepoint_offset(line, character)
        character = min(character, len(line))

        offset = 0
        for prior_line in lines[:line_index]:
            offset += len(prior_line) + 1
        return offset + character

    def handle_did_close(self, message):
        uri = self.message_text_document_uri(message)
        self.session.close_document(uri)
        return [{
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": uri,
                "diagnostics": [],
            },
        }]

    def handle_did_save(self, message):
        params = message.get("params", {})
        text_document = params["textDocument"]
        uri = self.text_document_uri(params)
        if "text" in params:
            self.session.update_document(
                uri,
                params["text"],
                version=text_document.get("version"),
            )
        else:
            self.session.invalidate_uri(uri)
        return [self.publish_diagnostics(uri)]

    def open_document_uris(self):
        """Return open document URIs currently tracked by the analysis session."""
        return {
            uri
            for uri, doc in self.session.documents.items()
            if doc.get("is_open")
        }

    def is_python_uri(self, uri: str):
        """Return whether a URI points to a Python source file."""
        return self.session.file_uri_suffix(uri) == ".py"

    def handle_did_change_watched_files(self, message):
        affected_uris = set()
        open_uris = self.open_document_uris()
        changes = message.get("params", {}).get("changes", [])
        ord_uris = {
            self.file_change_uri(change)
            for change in changes
            if self.session.is_ord_uri(change["uri"])
        }

        for uri in ord_uris:
            if uri in open_uris:
                affected_uris.add(uri)
            affected_uris.update(self.session.workspace_dependents(uri))

        python_changed = False
        canonical_ord_uris = set()
        for change in changes:
            uri = self.file_change_uri(change)

            canonical_invalidated_uri = self.session.invalidate_uri(uri)
            if canonical_invalidated_uri is not None:
                if canonical_invalidated_uri in open_uris:
                    affected_uris.add(canonical_invalidated_uri)
                if self.session.is_ord_uri(canonical_invalidated_uri):
                    canonical_ord_uris.add(canonical_invalidated_uri)
            elif self.is_python_uri(uri):
                python_changed = True

        for uri in canonical_ord_uris:
            affected_uris.update(self.session.workspace_dependents(uri))

        if python_changed:
            affected_uris.update(open_uris)

        return [
            self.publish_diagnostics(uri)
            for uri in sorted(affected_uris & open_uris)
        ]

    def handle_document_symbol(self, message):
        uri = self.message_text_document_uri(message)
        analysis = self.session.analyze(uri)
        if self.hierarchical_symbol_support:
            return self.result_response(
                message,
                self.nested_document_symbols(uri, analysis.symbols),
            )

        result = []
        for symbol in analysis.symbols:
            result.append({
                "name": symbol.name,
                "kind": self.symbol_kind(symbol.kind),
                "location": {
                    "uri": uri,
                    "range": self.lsp_range(uri, symbol.range),
                },
            })

        return self.result_response(message, result)

    def nested_document_symbols(self, uri: str, symbols):
        """Nest source-ordered document symbols by range containment."""
        root = []
        stack = []
        for symbol in symbols:
            entry = {
                "name": symbol.name,
                "kind": self.symbol_kind(symbol.kind),
                "range": self.lsp_range(uri, symbol.range),
                "selectionRange": self.lsp_range(uri, symbol.selection_range),
                "children": [],
            }

            while stack and not self.range_encloses(stack[-1][0], symbol.range):
                stack.pop()

            if stack:
                stack[-1][1]["children"].append(entry)
            else:
                root.append(entry)
            stack.append((symbol.range, entry))

        return root

    def range_encloses(self, outer, inner):
        """Return whether one analysis range fully contains another."""
        return outer.start <= inner.start and inner.end <= outer.end

    def handle_document_highlight(self, message):
        params = message.get("params", {})
        uri = self.text_document_uri(params)
        position = self.analysis_position(uri, params["position"])
        result = []
        for highlight in self.session.document_highlights(uri, position):
            result.append({
                "range": self.lsp_range(uri, highlight["range"]),
                "kind": self.document_highlight_kind(highlight["kind"]),
            })
        return self.result_response(message, result)

    def handle_definition(self, message):
        params = message.get("params", {})
        uri = self.text_document_uri(params)
        position = self.analysis_position(uri, params["position"])
        definition = self.session.definition(uri, position)
        result = None
        if definition is not None:
            result = self.lsp_definition_result(uri, definition)
        return self.result_response(message, result)

    def handle_type_definition(self, message):
        params = message.get("params", {})
        uri = self.text_document_uri(params)
        position = self.analysis_position(uri, params["position"])
        definition = self.session.type_definition(uri, position)
        result = None
        if definition is not None:
            result = {
                "uri": definition["uri"],
                "range": self.lsp_range(definition["uri"], definition["selection_range"]),
            }
        return self.result_response(message, result)

    def handle_signature_help(self, message):
        params = message.get("params", {})
        uri = self.text_document_uri(params)
        position = self.analysis_position(uri, params["position"])
        signature = self.session.signature_help(uri, position)
        result = None
        if signature is not None:
            signature_info = {
                "label": signature["label"],
                "parameters": [
                    {
                        "label": parameter["label"],
                    }
                    for parameter in signature["parameters"]
                ],
            }
            if signature.get("documentation"):
                signature_info["documentation"] = {
                    "kind": "plaintext",
                    "value": signature["documentation"],
                }
            result = {
                "signatures": [signature_info],
                "activeSignature": 0,
            }
            if signature.get("active_parameter") is not None:
                result["activeParameter"] = signature["active_parameter"]
        return self.result_response(message, result)

    def handle_inlay_hint(self, message):
        params = message.get("params", {})
        uri = self.text_document_uri(params)
        requested_range = params.get("range")
        value_range = None
        if requested_range is not None:
            value_range = AnalysisRange(
                start=self.analysis_position(uri, requested_range["start"]),
                end=self.analysis_position(uri, requested_range["end"]),
            )

        result = []
        for hint in self.session.inlay_hints(uri, value_range):
            result.append({
                "position": self.lsp_position(uri, hint["position"]),
                "label": ": {}".format(hint["label"]),
                "kind": INLAY_HINT_KIND_TYPE,
            })
        return self.result_response(message, result)

    def lsp_hierarchy_item(self, item):
        """Convert an analysis call hierarchy item to LSP shape."""
        return {
            "name": item["name"],
            "kind": self.symbol_kind(item["kind"]),
            "uri": item["uri"],
            "range": self.lsp_range(item["uri"], item["range"]),
            "selectionRange": self.lsp_range(item["uri"], item["selection_range"]),
        }

    def hierarchy_request_location(self, message):
        """Return the canonical URI and position identified by an item param."""
        item = message.get("params", {})["item"]
        uri = self.canonical_uri(item["uri"])
        position = self.analysis_position(uri, item["selectionRange"]["start"])
        return uri, position

    def handle_prepare_call_hierarchy(self, message):
        params = message.get("params", {})
        uri = self.text_document_uri(params)
        position = self.analysis_position(uri, params["position"])
        item = self.session.call_hierarchy_item(uri, position)
        result = None
        if item is not None:
            result = [self.lsp_hierarchy_item(item)]
        return self.result_response(message, result)

    def handle_incoming_calls(self, message):
        uri, position = self.hierarchy_request_location(message)
        result = []
        for call in self.session.incoming_calls(uri, position):
            item = call["item"]
            result.append({
                "from": self.lsp_hierarchy_item(item),
                "fromRanges": [
                    self.lsp_range(item["uri"], from_range)
                    for from_range in call["from_ranges"]
                ],
            })
        return self.result_response(message, result)

    def handle_outgoing_calls(self, message):
        uri, position = self.hierarchy_request_location(message)
        result = []
        for call in self.session.outgoing_calls(uri, position):
            result.append({
                "to": self.lsp_hierarchy_item(call["item"]),
                "fromRanges": [
                    self.lsp_range(uri, from_range)
                    for from_range in call["from_ranges"]
                ],
            })
        return self.result_response(message, result)

    def handle_hover(self, message):
        params = message.get("params", {})
        uri = self.text_document_uri(params)
        position = self.analysis_position(uri, params["position"])
        hover = self.session.hover(uri, position)
        result = None
        if hover is not None:
            if self.hover_markdown_support:
                contents = {
                    "kind": "markdown",
                    "value": hover["markdown"],
                }
            else:
                contents = {
                    "kind": "plaintext",
                    "value": hover["contents"],
                }
            result = {
                "contents": contents,
                "range": self.lsp_range(uri, hover["range"]),
            }
        return self.result_response(message, result)

    def handle_references(self, message):
        params = message.get("params", {})
        uri = self.text_document_uri(params)
        position = self.analysis_position(uri, params["position"])
        references = self.session.references(uri, position)
        result = []
        for reference in references:
            result.append({
                "uri": reference["uri"],
                "range": self.lsp_range(reference["uri"], reference["range"]),
            })
        return self.result_response(message, result)

    def handle_completion(self, message):
        params = message.get("params", {})
        uri = self.text_document_uri(params)
        position = self.analysis_position(uri, params["position"])
        completions = self.session.completions(uri, position)
        replace_range = self.lsp_range(
            uri,
            self.session.completion_replace_range(uri, position),
        )
        result = []
        for index, completion in enumerate(completions):
            item = {
                "label": completion["label"],
                "kind": self.completion_kind(completion["kind"]),
                "detail": completion["detail"],
                "sortText": "{:04d}".format(index),
                "textEdit": {
                    "range": replace_range,
                    "newText": completion["label"],
                },
            }
            if completion.get("documentation"):
                item["documentation"] = {
                    "kind": "plaintext",
                    "value": completion["documentation"],
                }
            result.append(item)
        return self.result_response(message, result)

    def handle_code_action(self, message):
        params = message.get("params", {})
        uri = self.text_document_uri(params)
        diagnostics = params.get("context", {}).get("diagnostics", [])
        return self.result_response(
            message,
            code_actions(self.session, uri, diagnostics),
        )

    def handle_folding_range(self, message):
        uri = self.message_text_document_uri(message)
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

    def lsp_selection_range_chain(self, uri, node):
        """Convert a nested analysis selection range chain to LSP shape."""
        lsp_node = {
            "range": self.lsp_range(uri, node["range"]),
        }
        if node["parent"] is not None:
            lsp_node["parent"] = self.lsp_selection_range_chain(uri, node["parent"])
        return lsp_node

    def handle_selection_range(self, message):
        params = message.get("params", {})
        uri = self.text_document_uri(params)
        positions = [
            self.analysis_position(uri, pos)
            for pos in params["positions"]
        ]
        selection_ranges = self.session.selection_ranges(uri, positions)
        result = []
        for chain in selection_ranges:
            if chain is None:
                result.append(None)
                continue

            result.append(self.lsp_selection_range_chain(uri, chain))
        return self.result_response(message, result)

    def handle_semantic_tokens_full(self, message):
        uri = self.message_text_document_uri(message)
        tokens = self.session.semantic_tokens(uri)
        data = []
        prev_line = 0
        prev_char = 0
        for token in tokens:
            start = self.lsp_position(uri, token["range"].start)
            end = self.lsp_position(uri, token["range"].end)
            line = start["line"]
            char = start["character"]
            length = end["character"] - char
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
                    "range": self.lsp_range(symbol["uri"], symbol["selection_range"]),
                },
            })
        return self.result_response(message, result)

    def handle_prepare_rename(self, message):
        params = message.get("params", {})
        uri = self.text_document_uri(params)
        position = self.analysis_position(uri, params["position"])
        result = self.session.prepare_rename(uri, position)
        if result is not None:
            result = {
                "range": self.lsp_range(uri, result["range"]),
                "placeholder": result["placeholder"],
            }
        return self.result_response(message, result)

    def handle_rename(self, message):
        params = message.get("params", {})
        uri = self.text_document_uri(params)
        position = self.analysis_position(uri, params["position"])
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
                            "range": self.lsp_range(change_uri, change["range"]),
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
            lsp_diagnostic = {
                "range": self.lsp_range(uri, diagnostic.range),
                "severity": self.diagnostic_severity(diagnostic.severity),
                "message": diagnostic.message,
                "code": diagnostic.code,
            }
            if diagnostic.data is not None:
                lsp_diagnostic["data"] = diagnostic.data
            diagnostics.append(lsp_diagnostic)

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

    def show_message(self, severity: str, message: str):
        """Build a ``window/showMessage`` notification."""
        return {
            "jsonrpc": "2.0",
            "method": "window/showMessage",
            "params": {
                "type": SHOW_MESSAGE_SEVERITY_MAP.get(severity, 3),
                "message": message,
            },
        }

    def document_line(self, uri: str, one_based_line: int):
        """Return a document line for position encoding conversion."""
        lines = self.session.document_lines(uri)
        if lines is None:
            path = file_uri_to_path(uri)
            if path is None:
                return None
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                return None

        if one_based_line < 1 or one_based_line > len(lines):
            return None
        return lines[one_based_line - 1]

    def utf16_offset_to_codepoint_offset(self, line: str, utf16_offset: int):
        """Convert a UTF-16 code-unit offset to a Python string offset."""
        offset = 0
        consumed = 0
        for char in line:
            width = 2 if ord(char) > 0xFFFF else 1
            if consumed + width > utf16_offset:
                break
            consumed += width
            offset += 1
        return offset

    def codepoint_offset_to_utf16_offset(self, line: str, codepoint_offset: int):
        """Convert a Python string offset to a UTF-16 code-unit offset."""
        prefix = line[:max(0, min(codepoint_offset, len(line)))]
        return len(prefix.encode("utf-16-le")) // 2

    def analysis_position(self, uri: str, position):
        """Convert a zero-based LSP position to a one-based analysis position."""
        line_number = position["line"] + 1
        character = position["character"]
        if self.position_encoding == "utf-16":
            line = self.document_line(uri, line_number)
            if line is not None:
                character = self.utf16_offset_to_codepoint_offset(line, character)

        return AnalysisPosition(
            line=line_number,
            character=character + 1,
        )

    def lsp_position(self, uri: str, position):
        """Convert a one-based analysis position to a zero-based LSP position."""
        character = position.character - 1
        if self.position_encoding == "utf-16":
            line = self.document_line(uri, position.line)
            if line is not None:
                character = self.codepoint_offset_to_utf16_offset(line, character)

        return {
            "line": position.line - 1,
            "character": character,
        }

    def lsp_range(self, uri: str, value_range):
        """Convert an analysis range to an LSP range."""
        return {
            "start": self.lsp_position(uri, value_range.start),
            "end": self.lsp_position(uri, value_range.end),
        }

    def lsp_definition_result(self, source_uri: str, definition):
        """Convert an analysis definition to the client-supported LSP shape."""
        target_selection_range = self.lsp_range(
            definition["uri"],
            definition["selection_range"],
        )
        if not self.definition_link_support:
            return {
                "uri": definition["uri"],
                "range": target_selection_range,
            }

        result = {
            "targetUri": definition["uri"],
            "targetRange": self.lsp_range(definition["uri"], definition["range"]),
            "targetSelectionRange": target_selection_range,
        }
        if definition.get("origin_range") is not None:
            result["originSelectionRange"] = self.lsp_range(
                source_uri,
                definition["origin_range"],
            )

        return [result]

    def diagnostic_severity(self, severity: str):
        """Map an analysis diagnostic severity to an LSP severity constant."""
        return DIAGNOSTIC_SEVERITY_MAP.get(severity, 3)

    def symbol_kind(self, kind: str):
        """Map an analysis symbol kind to an LSP symbol kind constant."""
        return SYMBOL_KIND_MAP.get(kind, 13)

    def completion_kind(self, kind: str):
        """Map an analysis completion kind to an LSP completion item kind."""
        return COMPLETION_KIND_MAP.get(kind, 1)

    def document_highlight_kind(self, kind: str):
        """Map an analysis highlight kind to an LSP highlight kind constant."""
        return DOCUMENT_HIGHLIGHT_KIND_MAP.get(kind, 1)


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


def read_messages(input_stream, message_queue):
    """Feed framed input messages to the queue until EOF or a read error."""
    while True:
        try:
            message = read_message(input_stream)
        except Exception:
            message = None
        message_queue.put(message)
        if message is None:
            return


def notification_method(message, method):
    """Return whether a decoded message is the named notification."""
    return isinstance(message, dict) and message.get("method") == method


def did_change_uri(message):
    """Return the raw target URI of a didChange notification, or None."""
    if not notification_method(message, "textDocument/didChange"):
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    text_document = params.get("textDocument")
    if not isinstance(text_document, dict):
        return None
    return text_document.get("uri")


def did_change_replaces_document(message):
    """Return whether a didChange notification only replaces the full text."""
    params = message.get("params")
    if not isinstance(params, dict):
        return False
    content_changes = params.get("contentChanges")
    if not isinstance(content_changes, list) or not content_changes:
        return False
    return all(
        isinstance(change, dict) and "range" not in change
        for change in content_changes
    )


def serve(server, message_queue, output_stream):
    """Dispatch queued messages until EOF, then return.

    Messages are dispatched strictly in arrival order by this single
    consumer. Draining the queue backlog before dispatching enables two
    shortcuts that preserve observable ordering: $/cancelRequest marks
    still-queued requests as canceled before they are computed, and a
    consecutive run of didChange notifications for one document collapses
    onto a newer full-document replacement, which supersedes whatever came
    before it. Incremental changes are never skipped because each one
    builds on the document state left by its predecessor.
    """
    pending = deque()
    canceled_ids = set()

    while True:
        if not pending:
            pending.append(message_queue.get())
        while True:
            try:
                pending.append(message_queue.get_nowait())
            except queue.Empty:
                break

        # Cancellations apply to queued requests independent of their
        # position, so collect them from the whole backlog first.
        remaining = deque()
        for message in pending:
            if notification_method(message, "$/cancelRequest"):
                params = message.get("params")
                if isinstance(params, dict) and "id" in params:
                    canceled_ids.add(params["id"])
            else:
                remaining.append(message)
        pending = remaining
        if not pending:
            continue

        message = pending.popleft()
        if message is None:
            return
        if not isinstance(message, dict):
            continue

        uri = did_change_uri(message)
        if uri is not None:
            while (
                pending
                and did_change_uri(pending[0]) == uri
                and did_change_replaces_document(pending[0])
            ):
                message = pending.popleft()

        message_id = message.get("id")
        if message_id is not None and message_id in canceled_ids:
            canceled_ids.discard(message_id)
            write_message(output_stream, {
                "jsonrpc": "2.0",
                "id": message_id,
                "error": {
                    "code": -32800,
                    "message": "Request canceled",
                },
            })
            continue

        try:
            responses = server.handle_message(message)
        except SystemExit as exc:
            raise exc
        except Exception as exc:  # pragma: no cover - safety net for stdio server
            if message_id is not None:
                responses = [{
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "error": {
                        "code": -32603,
                        "message": str(exc),
                    },
                }]
            else:
                responses = []

        if message_id is not None:
            canceled_ids.discard(message_id)

        for response in responses:
            write_message(output_stream, response)


def main():
    """Run the ORDeC language server over stdin/stdout.

    A daemon reader thread frames stdin onto a message queue, so cancels
    and newer edits become visible to serve() while earlier messages are
    still being handled. The daemon flag lets handle_exit terminate the
    process even though the reader blocks on stdin.
    """
    server = OrdLanguageServer()
    message_queue = queue.SimpleQueue()
    reader = threading.Thread(
        target=read_messages,
        args=(sys.stdin.buffer, message_queue),
        daemon=True,
    )
    reader.start()
    serve(server, message_queue, sys.stdout.buffer)
