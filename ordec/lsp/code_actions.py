# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import re

# ordec imports
from ..analysis.model import AnalysisPosition


def code_actions(session, uri: str, diagnostics):
    """Return code actions supported for diagnostics in one document.

    Args:
        session: Analysis session that owns the document text and symbols.
        uri: Document URI for the action request.
        diagnostics: LSP diagnostics supplied by the client.

    Returns:
        List of LSP code action dictionaries.
    """
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
    """Convert a zero-based LSP position into a one-based analysis position.

    Args:
        position: LSP position dictionary.

    Returns:
        Equivalent ``AnalysisPosition``.
    """
    return AnalysisPosition(
        line=position["line"] + 1,
        character=position["character"] + 1,
    )


def missing_symbol_port_action(session, uri: str, diagnostic):
    """Create a quick fix for schematic ports missing from a symbol view.

    Args:
        session: Analysis session used to inspect document symbols.
        uri: Document URI for the diagnostic.
        diagnostic: LSP diagnostic with an ``unknown-symbol-port`` code.

    Returns:
        LSP code action dictionary, or None when the fix cannot be placed.
    """
    message = diagnostic.get("message", "")
    match = re.search(r"Schematic port `([^`]+)`", message)
    if match is None:
        return None

    port_name = match.group(1)
    diagnostic_position = lsp_analysis_position(diagnostic["range"]["start"])
    analysis = session.analyze(uri)

    containing_cell = None
    for symbol in analysis.symbols:
        if symbol.kind != "class":
            continue
        if not (
            symbol.range.start.line <= diagnostic_position.line
            and diagnostic_position.line <= symbol.range.end.line
        ):
            continue
        containing_cell = symbol
        break

    if containing_cell is None:
        return None

    symbol_view = None
    for symbol in analysis.symbols:
        if symbol.name != "symbol" or symbol.kind != "function":
            continue
        if not (
            containing_cell.range.start.line <= symbol.selection_range.start.line
            and symbol.selection_range.start.line <= containing_cell.range.end.line
        ):
            continue
        symbol_view = symbol
        break

    if symbol_view is None:
        return None

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
                    "newText": "        input {}\n".format(port_name),
                }],
            },
        },
    }
