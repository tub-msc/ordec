# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import re
from typing import List, NamedTuple, Optional


_MISSING = object()
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LEADING_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
TRAILING_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def is_identifier(value: str):
    """Return whether a value is an ORD/Python-style identifier.

    Args:
        value: String to validate.

    Returns:
        True when value is a single ASCII identifier.
    """
    return IDENTIFIER_RE.match(value) is not None


def leading_identifier(value: str):
    """Return the leading identifier in a string.

    Args:
        value: String to inspect.

    Returns:
        Leading identifier, or None when the string does not start with one.
    """
    match = LEADING_IDENTIFIER_RE.match(value)
    if match is None:
        return None
    return match.group(0)


def trailing_identifier(value: str):
    """Return the trailing identifier in a string.

    Args:
        value: String to inspect.

    Returns:
        Trailing identifier, or None when the string does not end with one.
    """
    match = TRAILING_IDENTIFIER_RE.search(value)
    if match is None:
        return None
    return match.group(0)


class AnalysisPosition(NamedTuple):
    """One-based source position used by the ORD analysis layer."""

    line: int
    character: int

    def to_dict(self):
        """Convert the position to a plain dictionary.

        Returns:
            Dictionary with line and character fields.
        """
        return {
            "line": self.line,
            "character": self.character,
        }


class AnalysisRange(NamedTuple):
    """Half-open source range using ORD analysis positions."""

    start: AnalysisPosition
    end: AnalysisPosition

    def to_dict(self):
        """Convert the range to a plain dictionary.

        Returns:
            Dictionary containing serialized start and end positions.
        """
        return {
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
        }


class AnalysisDiagnostic(NamedTuple):
    """Diagnostic emitted by the parser or semantic analysis passes."""

    range: AnalysisRange
    severity: str
    message: str
    code: Optional[str] = None
    data: Optional[dict] = None

    def to_dict(self):
        """Convert the diagnostic to a plain dictionary.

        Returns:
            Dictionary containing range, severity, message, code, and data.
        """
        result = {
            "range": self.range.to_dict(),
            "severity": self.severity,
            "message": self.message,
            "code": self.code,
        }
        if self.data is not None:
            result["data"] = self.data
        return result


class AnalysisSymbol(NamedTuple):
    """Named symbol discovered in an ORD document."""

    name: str
    kind: str
    range: AnalysisRange
    selection_range: AnalysisRange

    def to_dict(self):
        """Convert the symbol to a dictionary for protocol responses.

        Returns:
            Dictionary containing the symbol name, kind, and ranges.
        """
        return {
            "name": self.name,
            "kind": self.kind,
            "range": self.range.to_dict(),
            "selection_range": self.selection_range.to_dict(),
        }


class AnalysisImport(NamedTuple):
    """Import statement captured from an ORD document."""

    kind: str
    module: str
    export_name: Optional[str]
    local_name: str
    range: AnalysisRange
    selection_range: AnalysisRange

    def to_dict(self):
        """Convert the import entry to a dictionary.

        Returns:
            Dictionary containing import metadata and source ranges.
        """
        return {
            "kind": self.kind,
            "module": self.module,
            "export_name": self.export_name,
            "local_name": self.local_name,
            "range": self.range.to_dict(),
            "selection_range": self.selection_range.to_dict(),
        }


class DocumentAnalysis:
    """Analysis result for one ORD document.

    The object keeps both user-facing analysis data and internal indexes used
    by LSP features such as definition, references, rename, and completions.
    """

    def __init__(
        self,
        uri: str,
        version: Optional[int],
        diagnostics: List[AnalysisDiagnostic],
        symbols: List[AnalysisSymbol],
        imports: Optional[List[str]] = None,
        import_entries: Optional[List[AnalysisImport]] = None,
        exports: Optional[List[str]] = None,
        scopes=None,
        bindings=None,
        occurrences=None,
        member_occurrences=None,
        viewgen_returns=None,
        node_contexts=None,
        constraints=None,
    ):
        """Initialize a document analysis result.

        Args:
            uri: URI of the analyzed document.
            version: Optional document version from the LSP client.
            diagnostics: Parser or semantic diagnostics for the document.
            symbols: Top-level and structural symbols in source order.
            imports: Imported module names.
            import_entries: Detailed import records.
            exports: Names exported by the document.
            scopes: Scope table built by the parser pass.
            bindings: Name bindings built by the parser pass.
            occurrences: Name occurrences built by the parser pass.
            member_occurrences: Member or parameter occurrences.
            viewgen_returns: View generator return type records.
            node_contexts: ORD node context records.
            constraints: Constraint syntax records.
        """
        self.uri = uri
        self.version = version
        self.diagnostics = list(diagnostics)
        self.symbols = list(symbols)
        self.imports = list(imports) if imports is not None else []
        self.import_entries = list(import_entries) if import_entries is not None else []
        self.exports = list(exports) if exports is not None else []
        self.scopes = self.copy_scopes(scopes if scopes is not None else dict())
        self.bindings = self.copy_records(bindings if bindings is not None else [])
        self.binding_map = dict((binding["id"], binding) for binding in self.bindings)
        self.occurrences = self.copy_records(occurrences if occurrences is not None else [])
        self.member_occurrences = self.copy_records(
            member_occurrences if member_occurrences is not None else []
        )
        self.viewgen_returns = self.copy_records(viewgen_returns if viewgen_returns is not None else [])
        self.node_contexts = self.copy_records(node_contexts if node_contexts is not None else [])
        self.constraints = self.copy_records(constraints if constraints is not None else [])

    def copy_scopes(self, scopes):
        """Return copied scope records so analysis snapshots do not alias."""
        result = dict()
        for scope_id, scope in scopes.items():
            copied = dict(scope)
            if "bindings" in copied:
                copied["bindings"] = list(copied["bindings"])
            result[scope_id] = copied
        return result

    def copy_records(self, records):
        """Return copied analysis record dictionaries."""
        result = []
        for record in records:
            copied = dict(record)
            for key, value in list(copied.items()):
                if isinstance(value, list):
                    copied[key] = list(value)
                elif isinstance(value, set):
                    copied[key] = set(value)
                elif isinstance(value, dict):
                    copied[key] = dict(value)
            result.append(copied)
        return result

    def to_dict(self):
        """Convert the public analysis fields to a dictionary.

        Returns:
            Dictionary used by tests and LSP response helpers.
        """
        return {
            "uri": self.uri,
            "version": self.version,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "symbols": [symbol.to_dict() for symbol in self.symbols],
            "imports": list(self.imports),
            "exports": list(self.exports),
        }

    def has_errors(self):
        """Return whether this analysis contains an error diagnostic.

        Returns:
            True if any diagnostic has error severity.
        """
        return any(
            diagnostic.severity == "error"
            for diagnostic in self.diagnostics
        )

    def with_diagnostics(self, diagnostics, uri: Optional[str] = None, version=_MISSING):
        """Create a copy with replaced diagnostics.

        Args:
            diagnostics: Diagnostics to attach to the copied analysis.
            uri: Optional replacement URI.
            version: Optional replacement document version.

        Returns:
            New ``DocumentAnalysis`` with copied structural analysis data.
        """
        return DocumentAnalysis(
            uri=self.uri if uri is None else uri,
            version=self.version if version is _MISSING else version,
            diagnostics=diagnostics,
            symbols=self.symbols,
            imports=self.imports,
            import_entries=self.import_entries,
            exports=self.exports,
            scopes=self.scopes,
            bindings=self.bindings,
            occurrences=self.occurrences,
            member_occurrences=self.member_occurrences,
            viewgen_returns=self.viewgen_returns,
            node_contexts=self.node_contexts,
            constraints=self.constraints,
        )


def position_before(left: AnalysisPosition, right: AnalysisPosition):
    """Return whether one analysis position is strictly before another.

    Args:
        left: Position to compare first.
        right: Position to compare against.

    Returns:
        True if ``left`` sorts before ``right``.
    """
    if left.line != right.line:
        return left.line < right.line
    return left.character < right.character


def position_before_or_equal(left: AnalysisPosition, right: AnalysisPosition):
    """Return whether one analysis position is before or equal to another.

    Args:
        left: Position to compare first.
        right: Position to compare against.

    Returns:
        True if ``left`` is before or equal to ``right``.
    """
    return not position_before(right, left)


def range_contains(value_range: AnalysisRange, position: AnalysisPosition):
    """Return whether a half-open analysis range contains a position.

    Args:
        value_range: Range to test.
        position: Position that may fall inside the range.

    Returns:
        True if the position is inside ``value_range``.
    """
    if not position_before_or_equal(value_range.start, position):
        return False
    return position_before(position, value_range.end)
