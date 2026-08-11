# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import os.path
import re
from pathlib import Path
from typing import List, NamedTuple, Optional
from urllib.parse import unquote, urlparse

# Keywords that declare ORD nodes, grouped by the node type they create.
# The transformer's node statement handling (ordec.ord.ord_transformer)
# is the semantic authority these sets must follow.
PIN_KINDS = ("input", "output", "inout")
NET_KINDS = ("port", "net")
PATH_KINDS = ("path",)
NODE_KINDS = PIN_KINDS + NET_KINDS + PATH_KINDS


MISSING = object()
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LEADING_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
TRAILING_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
FILE_URI_DRIVE_RE = re.compile(r"^/[A-Za-z]:")
LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")


def file_uri_to_path(uri: str):
    """Return the absolute, normalized filesystem path for a file URI, or None.

    Symlinks are deliberately not resolved: session keys and response URIs
    must keep the spelling the client opened, or published diagnostics end
    up under URIs the editor does not associate with its buffers.

    Windows clients send drive-letter URIs such as ``file:///C:/x.ord``,
    whose URL path keeps a leading slash before the drive letter, so that
    slash is stripped before building the path.
    """
    parsed_uri = urlparse(uri)
    if parsed_uri.scheme != "file":
        return None

    path = unquote(parsed_uri.path)
    if FILE_URI_DRIVE_RE.match(path):
        path = path[1:]
    return Path(os.path.abspath(path))


def find_module_source(base_path: Path, suffixes, package_only: bool = False):
    """Return the source file that a module path resolves to, or None.

    The single resolver shared by ORD and Python import resolution, so
    both sides agree on which files an import names. Package ``__init__``
    files are probed before same-named module files, matching how Python
    prefers packages over modules.

    Args:
        base_path: Filesystem path of the module, without suffix.
        suffixes: Source suffixes to probe, in order of precedence.
        package_only: Restrict the probe to packages. A dots-only
            relative import such as ``from . import x`` names the
            package itself, never a same-named module file.
    """
    for suffix in suffixes:
        candidate = base_path / ("__init__" + suffix)
        if candidate.exists():
            return candidate

    # An empty final component means the import climbed past the
    # filesystem root, where with_suffix() would raise.
    if package_only or not base_path.name:
        return None

    for suffix in suffixes:
        candidate = base_path.with_suffix(suffix)
        if candidate.exists():
            return candidate

    return None


def split_source_lines(text: str):
    """Split source text on LSP line breaks only.

    ``str.splitlines()`` also breaks on form feed, NEL, and U+2028/U+2029,
    which neither LSP clients nor the ORD parser count as line breaks, so
    line indexes would drift on documents containing them. Like
    ``splitlines()``, a trailing line break produces no trailing empty entry.
    """
    lines = LINE_BREAK_RE.split(text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def is_identifier(value: str):
    """Return whether ``value`` is a single ASCII identifier."""
    return IDENTIFIER_RE.match(value) is not None


def leading_identifier(value: str):
    """Return the leading identifier in ``value``, or None if none is present."""
    match = LEADING_IDENTIFIER_RE.match(value)
    if match is None:
        return None
    return match.group(0)


def trailing_identifier(value: str):
    """Return the trailing identifier in ``value``, or None if none is present."""
    match = TRAILING_IDENTIFIER_RE.search(value)
    if match is None:
        return None
    return match.group(0)


def normalize_type_names(type_names):
    """Return unique non-empty type names while preserving order."""
    if not type_names:
        return []

    seen = set()
    result = []
    for type_name in type_names:
        if not type_name or type_name in seen:
            continue
        seen.add(type_name)
        result.append(type_name)
    return result


def context_type_names_for_kind(kind_name: str):
    """Map an ORD context keyword to candidate type names."""
    if kind_name in PIN_KINDS:
        return ["Pin"]
    if kind_name in NET_KINDS:
        return ["Net"]
    if kind_name in PATH_KINDS:
        return ["PathNode"]

    # Dotted kinds such as `lib.Inv` instantiate the trailing class.
    identifier = trailing_identifier(kind_name)
    if identifier is None:
        return []
    return [identifier]


class AnalysisPosition(NamedTuple):
    """One-based source position used by the ORD analysis layer."""
    line: int
    character: int



class AnalysisRange(NamedTuple):
    """Half-open source range using ORD analysis positions."""
    start: AnalysisPosition
    end: AnalysisPosition



class AnalysisDiagnostic(NamedTuple):
    """Diagnostic emitted by the parser or semantic analysis passes."""
    range: AnalysisRange
    severity: str
    message: str
    code: Optional[str] = None
    data: Optional[dict] = None



class AnalysisSymbol(NamedTuple):
    """Named symbol discovered in an ORD document.

    ``range`` follows the parse tree, whose block ends spill past the last
    statement up to the next construct. That looseness keeps cursor
    containment working on trailing blank lines, so line-precise consumers
    such as folding use ``content_end_line``, the last line holding an
    actual token of the symbol.
    """
    name: str
    kind: str
    range: AnalysisRange
    selection_range: AnalysisRange
    content_end_line: Optional[int] = None



class AnalysisImport(NamedTuple):
    """Import statement captured from an ORD document.

    For from-imports, ``export_range`` covers the exported-name token,
    which differs from ``selection_range`` when the import is aliased.
    """
    kind: str
    module: str
    export_name: Optional[str]
    local_name: str
    range: AnalysisRange
    selection_range: AnalysisRange
    is_alias: bool = False
    export_range: Optional[AnalysisRange] = None



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
        node_statements=None,
        constraints=None,
        type_hints=None,
        view_context_ranges=None,
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
            node_statements: ORD node statement records.
            constraints: Constraint syntax records.
            type_hints: Inferred-type records for assignment targets.
            view_context_ranges: Ranges of ``with`` blocks that open an
                ORDB view context outside a viewgen.
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
        self.node_statements = self.copy_records(node_statements if node_statements is not None else [])
        self.constraints = self.copy_records(constraints if constraints is not None else [])
        self.type_hints = self.copy_records(type_hints if type_hints is not None else [])
        self.view_context_ranges = list(
            view_context_ranges if view_context_ranges is not None else []
        )

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

    def has_errors(self):
        """Return whether this analysis contains an error diagnostic."""
        return any(
            diagnostic.severity == "error"
            for diagnostic in self.diagnostics
        )

    def with_diagnostics(self, diagnostics, uri: Optional[str] = None, version=MISSING):
        """Return a copy with replaced diagnostics and optional uri/version."""
        return DocumentAnalysis(
            uri=self.uri if uri is None else uri,
            version=self.version if version is MISSING else version,
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
            node_statements=self.node_statements,
            constraints=self.constraints,
            type_hints=self.type_hints,
            view_context_ranges=self.view_context_ranges,
        )


def position_before(left: AnalysisPosition, right: AnalysisPosition):
    """Return whether ``left`` sorts strictly before ``right``."""
    if left.line != right.line:
        return left.line < right.line
    return left.character < right.character


def position_before_or_equal(left: AnalysisPosition, right: AnalysisPosition):
    """Return whether ``left`` is before or equal to ``right``."""
    return not position_before(right, left)


def range_contains(value_range: AnalysisRange, position: AnalysisPosition):
    """Return whether the half-open ``value_range`` contains ``position``."""
    if not position_before_or_equal(value_range.start, position):
        return False
    return position_before(position, value_range.end)
