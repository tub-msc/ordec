# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# ordec imports
from ..analysis.model import AnalysisPosition


def code_actions(session, uri: str, diagnostics):
    """Return LSP code actions for the given diagnostics in one document."""
    actions = []
    if uri not in session.documents:
        return actions

    for diagnostic in diagnostics:
        code = diagnostic.get("code")
        if code == "unknown-symbol-port":
            action = missing_symbol_port_action(session, uri, diagnostic)
            if action is not None:
                actions.append(action)

    return actions


def lsp_analysis_position(position):
    """Convert a zero-based LSP position into a one-based analysis position."""
    return AnalysisPosition(
        line=position["line"] + 1,
        character=position["character"] + 1,
    )


def line_in_range(value_range, line: int):
    """Return whether a one-based line falls inside an analysis range."""
    return value_range.start.line <= line <= value_range.end.line


def leading_indent(line: str):
    """Return the run of leading whitespace (spaces and tabs) on a line."""
    return line[:len(line) - len(line.lstrip(" \t"))]


def missing_symbol_port_action(session, uri: str, diagnostic):
    """Build a quick-fix action that declares a missing port in the symbol view."""
    data = diagnostic.get("data") or {}
    port_name = data.get("portName")
    if not port_name:
        return None

    diagnostic_position = lsp_analysis_position(diagnostic["range"]["start"])
    analysis = session.analyze(uri)

    containing_cell = None
    for symbol in analysis.symbols:
        if symbol.kind != "class":
            continue
        if not line_in_range(symbol.range, diagnostic_position.line):
            continue
        containing_cell = symbol
        break

    if containing_cell is None:
        return None

    symbol_view = None
    for symbol in analysis.symbols:
        if symbol.name != "symbol" or symbol.kind != "function":
            continue
        if not line_in_range(containing_cell.range, symbol.selection_range.start.line):
            continue
        symbol_view = symbol
        break

    if symbol_view is None:
        return None

    indent = symbol_body_indent(session, uri, analysis, symbol_view)
    insert_position = {
        "line": symbol_view.range.start.line,
        "character": 0,
    }
    return {
        "title": "Declare `{}` in symbol view".format(port_name),
        "kind": "quickfix",
        "diagnostics": [diagnostic],
        "edit": {
            "changes": {
                uri: [{
                    "range": {
                        "start": insert_position,
                        "end": insert_position,
                    },
                    "newText": "{}input {}\n".format(indent, port_name),
                }],
            },
        },
    }


def symbol_body_indent(session, uri: str, analysis, symbol_view):
    """Return the indentation to use for a new symbol-view body line."""
    text = session.documents[uri]["text"]
    lines = text.splitlines()

    for symbol in analysis.symbols:
        if symbol.kind != "context":
            continue
        if not line_in_range(symbol_view.range, symbol.selection_range.start.line):
            continue
        return leading_indent(lines[symbol.selection_range.start.line - 1])

    start_line_index = symbol_view.range.start.line
    end_line_index = min(symbol_view.range.end.line, len(lines))
    for line in lines[start_line_index:end_line_index]:
        if line.strip():
            return leading_indent(line)

    header = lines[symbol_view.range.start.line - 1]
    return leading_indent(header) + "    "
