# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from typing import List
from typing import NamedTuple
from typing import Optional


_MISSING = object()


class AnalysisPosition(NamedTuple):
    line: int
    character: int

    def to_dict(self):
        return {
            "line": self.line,
            "character": self.character,
        }


class AnalysisRange(NamedTuple):
    start: AnalysisPosition
    end: AnalysisPosition

    def to_dict(self):
        return {
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
        }


class AnalysisDiagnostic(NamedTuple):
    range: AnalysisRange
    severity: str
    message: str
    code: Optional[str] = None

    def to_dict(self):
        return {
            "range": self.range.to_dict(),
            "severity": self.severity,
            "message": self.message,
            "code": self.code,
        }


class AnalysisSymbol(NamedTuple):
    name: str
    kind: str
    range: AnalysisRange
    selection_range: AnalysisRange

    def to_dict(self):
        return {
            "name": self.name,
            "kind": self.kind,
            "range": self.range.to_dict(),
            "selection_range": self.selection_range.to_dict(),
        }


class AnalysisImport(NamedTuple):
    kind: str
    module: str
    export_name: Optional[str]
    local_name: str
    range: AnalysisRange
    selection_range: AnalysisRange

    def to_dict(self):
        return {
            "kind": self.kind,
            "module": self.module,
            "export_name": self.export_name,
            "local_name": self.local_name,
            "range": self.range.to_dict(),
            "selection_range": self.selection_range.to_dict(),
        }


class DocumentAnalysis:
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
        self.uri = uri
        self.version = version
        self.diagnostics = diagnostics
        self.symbols = symbols
        self.imports = imports if imports is not None else []
        self.import_entries = import_entries if import_entries is not None else []
        self.exports = exports if exports is not None else []
        self.scopes = scopes if scopes is not None else dict()
        self.bindings = bindings if bindings is not None else []
        self.binding_map = dict((binding["id"], binding) for binding in self.bindings)
        self.occurrences = occurrences if occurrences is not None else []
        self.member_occurrences = member_occurrences if member_occurrences is not None else []
        self.viewgen_returns = viewgen_returns if viewgen_returns is not None else []
        self.node_contexts = node_contexts if node_contexts is not None else []
        self.constraints = constraints if constraints is not None else []

    def to_dict(self):
        return {
            "uri": self.uri,
            "version": self.version,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "symbols": [symbol.to_dict() for symbol in self.symbols],
            "imports": list(self.imports),
            "exports": list(self.exports),
        }

    def has_errors(self):
        return any(
            diagnostic.severity == "error"
            for diagnostic in self.diagnostics
        )

    def with_diagnostics(self, diagnostics, uri: Optional[str] = None, version=_MISSING):
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
    if left.line != right.line:
        return left.line < right.line
    return left.character < right.character


def position_before_or_equal(left: AnalysisPosition, right: AnalysisPosition):
    return not position_before(right, left)


def range_contains(value_range: AnalysisRange, position: AnalysisPosition):
    if not position_before_or_equal(value_range.start, position):
        return False
    return position_before(position, value_range.end)
