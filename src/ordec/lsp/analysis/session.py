# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from bisect import bisect_right
import importlib
import os
import re
from pathlib import Path
from typing import Optional

# ordec imports
from . import completions, diagnostics, hierarchy, rename, signatures
from .import_resolver import ImportResolver, from_import_module_name
from .model import (
    AnalysisDefinition,
    AnalysisPosition,
    AnalysisRange,
    DocumentAnalysis,
    context_type_names_for_kind,
    file_uri_to_path,
    position_before_or_equal,
    range_contains,
    split_source_lines,
)
from .model import normalize_type_names as normalize_type_name_list
from .parser_pass import analyze_ord, edited_line_numbers, stand_in_source
from .python_index import PythonModuleIndex
from .revisions import Revisions

# Dependency and build-output directories that never hold workspace design
# sources (build outputs would surface stale duplicates). Hidden directories
# (leading dot) are pruned by name, so .git and .venv need no entries here.
WORKSPACE_SCAN_EXCLUDED_DIRS = frozenset({
    "node_modules",
    "__pycache__",
    "build",
    "dist",
})

CORE_TYPE_ALIASES = {
    "Simulation": "SimHierarchy",
}

# Semantic token types of definition kinds; other kinds read as variables.
KIND_TOKEN_TYPES = {
    "class": "class",
    "function": "function",
    "parameter": "parameter",
    "module": "namespace",
}


class AnalysisSession:
    """Stateful ORD analysis facade for open documents and workspace files.

    The LSP server should treat this class as its public boundary. Its
    LSP-facing methods are:

    - document lifecycle: ``open_document()``, ``update_document()``,
      ``close_document()``, ``invalidate_uri()``
    - diagnostics and symbols: ``analyze()``, ``diagnostics()``,
      ``workspace_symbols()``
    - navigation: ``definition()``, ``type_definition()``, ``hover()``,
      ``references()``, ``document_highlights()``,
      ``call_hierarchy_item()``, ``incoming_calls()``, ``outgoing_calls()``
    - editing and assists: ``completions()``, ``signature_help()``,
      ``inlay_hints()``, ``prepare_rename()``, ``rename()``,
      ``folding_ranges()``, ``selection_ranges()``, ``semantic_tokens()``

    Completions, diagnostics, rename, signature help and call hierarchy are
    implemented as functions taking the session as first argument in their
    own modules; the corresponding methods here delegate to them.
    """
    def __init__(
        self,
        workspace_root: Optional[str] = None,
        max_closed_documents: int = 512,
    ):
        """Initialize an analysis session for the optional workspace root."""
        if workspace_root:
            self.workspace_root = os.path.abspath(workspace_root)
        else:
            self.workspace_root = None
        self.max_closed_documents = max_closed_documents
        self.documents = dict()
        self.document_access_counter = 0
        self.canonical_uri_cache = dict()
        self.revisions = Revisions()
        self.diagnostics_cache = dict()
        self.resolver = ImportResolver(self.workspace_root, self.revisions)
        self.python_index = PythonModuleIndex(self.resolver)
        self.workspace_uri_cache = None
        self.workspace_index = None

    def canonical_uri(self, uri: str):
        """Return the canonical session key for a URI.

        Position conversion and reference resolution canonicalize the same
        URIs over and over (per token in semantic tokens responses), so the
        deterministic mapping is memoized.
        """
        canonical = self.canonical_uri_cache.get(uri)
        if canonical is None:
            path = self.file_uri_path(uri)
            canonical = uri if path is None else path.as_uri()
            self.canonical_uri_cache[uri] = canonical
        return canonical

    def file_uri_path(self, uri: str):
        """Return the resolved path for a file URI, or None."""
        return file_uri_to_path(uri)

    def file_uri_suffix(self, uri: str):
        """Return a file URI suffix, or None for non-file URIs."""
        path = self.file_uri_path(uri)
        if path is None:
            return None

        return path.suffix

    def display_uri(self, uri: str):
        """Return a user-facing location string for a URI."""
        path = self.file_uri_path(uri)
        if path is None:
            return uri

        if self.workspace_root:
            try:
                return str(path.relative_to(Path(self.workspace_root)))
            except ValueError:
                pass

        return str(path)

    def document_lines(self, uri: str):
        """Return the cached line list for a tracked document, or None.

        Position encoding conversion runs per token in semantic tokens
        responses, so the split is cached on the document record, which
        store_document() replaces wholesale on every text change.
        """
        doc = self.documents.get(self.canonical_uri(uri))
        if doc is None:
            return None

        lines = doc.get("lines")
        if lines is None:
            lines = split_source_lines(doc["text"])
            doc["lines"] = lines
        return lines

    def document_version(self, uri: str):
        """Return the version of a tracked document, or None."""
        doc = self.documents.get(self.canonical_uri(uri))
        if doc is None:
            return None
        return doc.get("version")

    def record_document_access(self, uri: str):
        """Record recent use for closed-document eviction."""
        doc = self.documents.get(uri)
        if doc is None:
            return
        self.document_access_counter += 1
        doc["last_access"] = self.document_access_counter

    def evict_closed_documents(self):
        """Evict least-recently-used closed file documents beyond the limit."""
        if self.max_closed_documents is None or self.max_closed_documents < 0:
            return

        closed = [
            (doc.get("last_access", 0), uri)
            for uri, doc in self.documents.items()
            if not doc.get("is_open") and uri.startswith("file:")
        ]
        overflow = len(closed) - self.max_closed_documents
        if overflow <= 0:
            return

        for _, uri in sorted(closed)[:overflow]:
            self.documents.pop(uri, None)
            self.diagnostics_cache.pop(uri, None)

    def last_good_analysis(self, doc):
        """Return the latest error-free analysis of a document record and its text."""
        if doc is None:
            return None, None

        analysis = doc.get("analysis")
        if analysis is not None and not analysis.has_errors():
            return analysis, doc["text"]

        return doc.get("last_good_analysis"), doc.get("last_good_text")

    def invalidate_workspace_index(self):
        """Clear cached workspace dependency information."""
        self.workspace_index = None

    def uri_in_workspace(self, uri: str):
        """Return whether a file URI is inside the configured workspace."""
        if not self.workspace_root:
            return True

        path = self.file_uri_path(uri)
        if path is None:
            return False

        try:
            path.relative_to(Path(self.workspace_root))
        except ValueError:
            return False
        return True

    def normalize_type_names(self, type_names):
        """Return unique non-empty type names while preserving order."""
        return normalize_type_name_list(type_names)

    def open_document(
        self,
        uri: str,
        text: str,
        version: Optional[int] = None,
        is_open: bool = True,
    ):
        """Register a newly opened document."""
        self.store_document(uri, text, version=version, is_open=is_open)

    def update_document(
        self,
        uri: str,
        text: str,
        version: Optional[int] = None,
        is_open: bool = True,
    ):
        """Replace a document snapshot and invalidate dependent caches."""
        self.store_document(uri, text, version=version, is_open=is_open)

    def store_document(
        self,
        uri: str,
        text: str,
        version: Optional[int] = None,
        is_open: bool = True,
    ):
        """Store a document snapshot, bumping its revision when the text changed."""
        uri = self.canonical_uri(uri)
        previous = self.documents.get(uri)
        # A document evicted while closed has no previous record.
        if previous is None or previous["text"] != text:
            self.revisions.bump(("doc", uri))
        last_good_analysis, last_good_text = self.last_good_analysis(previous)
        self.documents[uri] = {
            "text": text,
            "version": version,
            "analysis": None,
            "last_good_analysis": last_good_analysis,
            "last_good_text": last_good_text,
            "stand_in": None if previous is None else previous.get("stand_in"),
            "is_open": is_open,
            "last_access": 0,
        }
        self.record_document_access(uri)
        # The import index covers the documents it was built from.
        index = self.workspace_index
        if (
            index is not None
            and uri not in index["uris"]
            and self.is_ord_uri(uri)
            and self.uri_in_workspace(uri)
        ):
            self.invalidate_workspace_index()
        return uri

    def close_document(self, uri: str):
        """Close a document and restore its on-disk snapshot."""
        uri = self.canonical_uri(uri)
        document = self.documents.pop(uri, None)
        if document is None:
            return

        # The file on disk replaces the editor text.
        self.revisions.bump(("doc", uri))

        path = self.file_uri_path(uri)
        if path is None or not path.is_file():
            return

        try:
            self.open_path(str(path))
        except (OSError, UnicodeDecodeError):
            # Unreadable files are loaded again on their next use.
            return

    def ensure_document(self, uri: str):
        """Load a file-backed document when it is not already tracked."""
        uri = self.canonical_uri(uri)
        # Read before loading, so that a file that cannot be read yet is an
        # input of the results that depend on it.
        self.revisions.read(("doc", uri))
        if uri not in self.documents and uri.startswith("file:"):
            path = self.file_uri_path(uri)
            try:
                self.open_path(str(path))
            except (OSError, TypeError, UnicodeDecodeError):
                return False
        if uri in self.documents:
            self.record_document_access(uri)
            return True
        return False

    def is_ord_uri(self, uri: str):
        """Return whether a URI points to an ORD source file."""
        return self.file_uri_suffix(uri) == ".ord"

    def invalidate_path(self, path: str, created_or_deleted: bool = True):
        """Invalidate cached state for a filesystem path.

        ``created_or_deleted`` is false for content changes, which cannot
        change the file an import names.
        """
        path = Path(os.path.abspath(path))
        # The Python index reads files under their path and their
        # symlink-resolved path.
        self.revisions.bump(("file", path))
        self.revisions.bump(("file", path.resolve()))
        if created_or_deleted:
            # foo.py shadows foo.ord and __init__ files set the package
            # context, so a file that comes or goes can change any import.
            importlib.invalidate_caches()
            self.revisions.bump("files")

        if path.suffix != ".ord":
            return None

        uri = path.as_uri()
        if self.workspace_uri_cache is not None and self.uri_in_workspace(uri):
            if path.is_file():
                self.workspace_uri_cache.add(uri)
            else:
                self.workspace_uri_cache.discard(uri)

        doc = self.documents.get(uri)
        if doc is not None and doc.get("is_open"):
            doc["analysis"] = None
            return uri

        self.revisions.bump(("doc", uri))
        if path.exists():
            return self.update_path(str(path))

        self.documents.pop(uri, None)
        return uri

    def invalidate_uri(self, uri: str, created_or_deleted: bool = True):
        """Invalidate cached state for a file URI."""
        uri = self.canonical_uri(uri)
        path = self.file_uri_path(uri)
        if path is None:
            return None

        return self.invalidate_path(str(path), created_or_deleted)

    def resolve_module_uri(self, uri: str, module_name: str):
        """Resolve an ORD import name relative to a document URI."""
        return self.resolver.ord_module_uri(uri, module_name)

    def resolve_from_import(self, uri: str, module_name: str, export_name: str):
        """Resolve a from-import export or submodule definition."""
        module_uri = self.resolve_module_uri(uri, module_name)
        if module_uri is not None and export_name != "*":
            match = self.find_export(module_uri, export_name)
            if match is not None:
                return match

        submodule_name = from_import_module_name(module_name, export_name)
        if submodule_name is not None:
            submodule_uri = self.resolve_module_uri(uri, submodule_name)
            if submodule_uri is not None:
                return self.module_definition(uri, submodule_name)

        if module_uri is not None:
            return None

        module_path = self.resolve_python_module_path(uri, module_name)
        if module_path is None and submodule_name is not None:
            # A directory without __init__ has no module to look the
            # submodule up in, as in ``from . import helper``.
            return self.python_definition(self.resolve_python_module_path(uri, submodule_name))
        return self.python_definition(module_path, export_name=export_name)

    def star_import_definitions(self, uri: str, module_name: str):
        """Return the definitions that ``from module import *`` binds, by name."""
        module_uri = self.resolve_module_uri(uri, module_name)
        if module_uri is not None:
            # Most exports are symbols of the module itself; find_export
            # would search all related documents for each of them.
            analysis = self.analyze(module_uri)
            symbols = {symbol.name: symbol for symbol in reversed(analysis.symbols)}
            definitions = dict()
            for name in analysis.exports:
                symbol = symbols.get(name)
                if symbol is None:
                    definitions[name] = self.find_export(module_uri, name)
                    continue
                definitions[name] = AnalysisDefinition(
                    uri=module_uri,
                    name=name,
                    kind=symbol.kind,
                    range=symbol.range,
                    selection_range=symbol.selection_range,
                )
            return definitions

        module_path = self.resolve_python_module_path(uri, module_name)
        return {
            name: self.python_definition(module_path, export_name=name)
            for name in self.python_index.star_names(module_path)
        }

    def resolve_python_module_path(self, uri: str, module_name: str):
        """Resolve a possibly relative import name to a module source path."""
        return self.resolver.module_path(uri, module_name)

    def module_exists(self, uri: str, module_name: str):
        """Return whether an import name resolves to an ORD or Python module."""
        return self.resolver.module_exists(uri, module_name)

    def imported_by_python(self, uri: str):
        """Return whether a workspace Python module imports from an ORD document.

        The workspace import graph has no edges from Python modules, so the
        Python files are scanned, parsing only those naming the module.
        """
        path = self.file_uri_path(uri)
        if path is None or not self.workspace_root:
            return False

        target = path.resolve()
        module_name = target.parent.name if target.stem == "__init__" else target.stem
        module_name_re = re.compile(r"\b{}\b".format(re.escape(module_name)))
        for python_path in self.workspace_source_paths(Path(self.workspace_root), ".py"):
            try:
                if not module_name_re.search(python_path.read_text(encoding="utf-8")):
                    continue
            except (OSError, UnicodeDecodeError):
                continue
            imported = self.python_index.imported_paths(python_path)
            if any(imported_path.resolve() == target for imported_path in imported):
                return True
        return False

    def python_module_info(self, module_path: Optional[Path]):
        """Analyze a Python module enough for ORD import and member lookup."""
        return self.python_index.module_info(module_path)

    def python_definition(
        self,
        module_path: Optional[Path],
        export_name: Optional[str] = None,
        seen=None,
    ):
        """Resolve a Python module or exported member definition."""
        return self.python_index.definition(
            module_path,
            export_name=export_name,
            seen=seen,
        )


    def python_class_members(self, module_path: Optional[Path], class_name: str, seen=None):
        """Collect Python class members, including inherited members."""
        return self.python_index.class_members(module_path, class_name, seen=seen)

    def analyze(self, uri: str):
        """Return cached document analysis, parsing the document when needed."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return DocumentAnalysis(uri=uri, version=None, diagnostics=[], symbols=[])

        self.revisions.read(("doc", uri))
        doc = self.documents[uri]
        if doc["analysis"] is None:
            analysis = analyze_ord(doc["text"], uri=uri, version=doc["version"])
            if analysis.has_errors():
                # The last good analysis fits while just one line changed;
                # otherwise its ranges can be off below the edit.
                fallback = doc.get("last_good_analysis")
                good_text = doc.get("last_good_text")
                same_lines = good_text is not None and (
                    len(split_source_lines(good_text)) == len(split_source_lines(doc["text"]))
                    and len(edited_line_numbers(doc["text"], good_text)) <= 1
                )
                if not same_lines:
                    fallback = self.stand_in_analysis(doc, analysis) or fallback
                if fallback is not None:
                    analysis = fallback.with_diagnostics(
                        analysis.diagnostics,
                        uri=uri,
                        version=doc["version"],
                    )
            else:
                doc["last_good_analysis"] = analysis
                doc["last_good_text"] = doc["text"]
            doc["analysis"] = analysis
        return doc["analysis"]

    def stand_in_analysis(self, doc, analysis):
        """Return an analysis of a broken document with stand-ins, or None.

        The lines being edited are replaced by ``pass``: first the line of
        the syntax error, then the lines changed since the last error-free
        text, then both. The result keeps the current line numbers.
        """
        error_lines = {analysis.diagnostics[0].range.start.line}
        attempts = [error_lines]
        good_text = doc.get("last_good_text")
        if good_text is not None:
            edited_lines = edited_line_numbers(doc["text"], good_text)
            attempts += [edited_lines, edited_lines | error_lines]

        for line_numbers in attempts:
            source = stand_in_source(doc["text"], line_numbers)
            # Typing on a broken line keeps its stand-in, and with it the
            # analysis, unchanged from one keystroke to the next.
            previous = doc.get("stand_in")
            if previous is not None and previous[0] == source:
                return previous[1]

            candidate = analyze_ord(source, uri=analysis.uri, version=doc["version"])
            if not candidate.has_errors():
                doc["stand_in"] = (source, candidate)
                return candidate
        return None

    def analysis_cache(self, uri: str, analysis):
        """Return a cache dict scoped to one analysis result of a document.

        The dict lives on the document record and is replaced whenever a
        different analysis object is served, so entries derived from an
        analysis never need explicit invalidation.
        """
        doc = self.documents[uri]
        cache = doc.get("analysis_cache")
        if cache is None or cache.get("analysis") is not analysis:
            cache = {"analysis": analysis}
            doc["analysis_cache"] = cache
        return cache

    def diagnostics(self, uri: str):
        """Return parser and semantic diagnostics for a document.

        The result is reused while the revisions it read are unchanged.
        """
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return []

        cached = self.diagnostics_cache.get(uri)
        if cached is not None and self.revisions.current(cached[1]):
            return cached[0]

        with self.revisions.track() as reads:
            analysis = self.analyze(uri)
            result = analysis.diagnostics
            if not analysis.has_errors():
                result = result + diagnostics.semantic_diagnostics(self, uri)
        self.diagnostics_cache[uri] = (result, reads)
        return result

    def diagnostics_outdated(self, uri: str):
        """Return whether a document's diagnostics changed since last computed."""
        cached = self.diagnostics_cache.get(self.canonical_uri(uri))
        return cached is None or not self.revisions.current(cached[1])

    def open_path(self, path: str, version: Optional[int] = None):
        """Open a filesystem ORD file as a closed session document."""
        path = Path(os.path.abspath(path))
        uri = path.as_uri()
        if uri in self.documents and self.documents[uri].get("is_open"):
            return uri

        text = path.read_text(encoding="utf-8")
        self.open_document(uri, text, version=version, is_open=False)
        return uri

    def update_path(self, path: str, version: Optional[int] = None):
        """Refresh a filesystem ORD file in the session."""
        path = Path(os.path.abspath(path))
        uri = path.as_uri()
        if uri in self.documents and self.documents[uri].get("is_open"):
            self.documents[uri]["analysis"] = None
            return uri

        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Watched-file races and non-UTF-8 files must not abort
            # invalidation: drop the cached copy instead.
            self.documents.pop(uri, None)
            return uri
        self.update_document(uri, text, version=version, is_open=False)
        return uri

    def workspace_source_paths(self, root_path: Path, suffix: str = ".ord"):
        """Yield workspace source files, pruning hidden and dependency directories.

        A blind recursive glob crawls .git, virtualenvs, and node_modules,
        which dominates cold workspace scans on real projects. Design
        sources do not live in hidden or dependency directories, so those
        subtrees are skipped entirely.
        """
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = sorted(
                name for name in dirnames
                if not name.startswith(".")
                and name not in WORKSPACE_SCAN_EXCLUDED_DIRS
            )
            for filename in sorted(filenames):
                if filename.endswith(suffix):
                    yield Path(dirpath) / filename

    def workspace_uris(self):
        """Return ORD file URIs known to the current workspace."""
        if self.workspace_root:
            if self.workspace_uri_cache is None:
                root_path = Path(self.workspace_root)
                self.workspace_uri_cache = set()
                if root_path.exists():
                    self.workspace_uri_cache.update(
                        path.as_uri()
                        for path in self.workspace_source_paths(root_path)
                        if path.is_file()
                    )

            uris = []
            for uri in sorted(self.workspace_uri_cache):
                if uri not in self.documents:
                    try:
                        self.open_path(str(self.file_uri_path(uri)))
                    except (OSError, UnicodeDecodeError):
                        continue
                uris.append(uri)
            return uris

        uris = []
        for uri in sorted(self.documents):
            if uri.startswith("file:"):
                uris.append(uri)
        return uris

    def workspace_import_index(self):
        """Build or return cached ORD import dependency indexes.

        A document's row is recomputed when the revisions its imports were
        resolved from changed. Files that come or go rebuild the index.
        """
        files = self.revisions.read("files")
        index = self.workspace_index
        if index is None or index["files"] != files:
            index = {
                "files": files,
                "uris": set(self.workspace_uris()),
                "imports": dict(),
                "reads": dict(),
                "dependents": dict(),
            }
            self.workspace_index = index

        changed = False
        for uri in sorted(index["uris"]):
            reads = index["reads"].get(uri)
            if reads is not None and self.revisions.current(reads):
                continue
            with self.revisions.track() as reads:
                index["imports"][uri] = set(self.resolve_import_uris(uri))
            index["reads"][uri] = reads
            changed = True

        if changed:
            dependents = dict()
            for uri, import_uris in index["imports"].items():
                for import_uri in import_uris:
                    dependents.setdefault(import_uri, set()).add(uri)
            index["dependents"] = dependents

        self.evict_closed_documents()
        return index

    def workspace_dependents(self, uri: str):
        """Return workspace URIs that directly or indirectly import a URI."""
        uri = self.canonical_uri(uri)
        index = self.workspace_import_index()
        dependents = set()
        pending = list(index["dependents"].get(uri, set()))

        while pending:
            dependent_uri = pending.pop()
            if dependent_uri in dependents:
                continue

            dependents.add(dependent_uri)
            pending.extend(index["dependents"].get(dependent_uri, set()))

        return dependents

    def resolve_import_uris(self, uri: str):
        """Resolve ORD imports in a document to imported document URIs."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri) or not uri.startswith("file:"):
            return []

        return self.resolver.ord_import_uris(uri, self.analyze(uri).import_entries)

    def analyze_related(self, uri: str):
        """Analyze a document and its reachable ORD imports."""
        uri = self.canonical_uri(uri)
        analyses = dict()
        pending = [uri]

        while pending:
            current_uri = pending.pop()
            if current_uri in analyses:
                continue

            # ensure_document tolerates unreadable or non-UTF-8 files, so
            # one broken import cannot abort analysis of its importers.
            if not self.ensure_document(current_uri):
                continue

            analyses[current_uri] = self.analyze(current_uri)

            for import_uri in self.resolve_import_uris(current_uri):
                if import_uri not in analyses:
                    pending.append(import_uri)

        return analyses

    def local_definition(self, uri: str, position: AnalysisPosition):
        """Resolve a local binding or occurrence at a document position."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return None

        analysis = self.analyze(uri)

        for binding in analysis.bindings:
            if not range_contains(binding.selection_range, position):
                continue

            return AnalysisDefinition(
                uri=uri,
                name=binding.name,
                kind=binding.kind,
                range=binding.range,
                selection_range=binding.selection_range,
                origin_range=binding.selection_range,
                binding_id=binding.id,
                exported=binding.exported,
            )

        for occurrence in analysis.occurrences:
            if not range_contains(occurrence.range, position):
                continue

            binding = analysis.binding_map.get(occurrence.binding_id)
            if binding is None:
                continue

            return AnalysisDefinition(
                uri=uri,
                name=binding.name,
                kind=binding.kind,
                range=binding.range,
                selection_range=binding.selection_range,
                origin_range=occurrence.range,
                binding_id=binding.id,
                exported=binding.exported,
            )

        return None

    def visible_bindings(self, uri: str, position: AnalysisPosition):
        """Return bindings visible from a document position."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return []

        analysis = self.analyze(uri)
        if 0 not in analysis.scopes:
            return []

        scope = analysis.scopes[0]

        for current_scope in analysis.scopes.values():
            if not range_contains(current_scope.range, position):
                continue

            if current_scope.depth <= scope.depth:
                continue

            scope = current_scope

        visible_bindings = []
        visible_names = set()

        while scope is not None:
            for binding_id in reversed(scope.bindings):
                binding = analysis.binding_map[binding_id]
                if binding.name in visible_names:
                    continue

                if not position_before_or_equal(binding.selection_range.start, position):
                    continue

                visible_bindings.append(binding)
                visible_names.add(binding.name)

            parent_id = scope.parent_id
            if parent_id is None:
                scope = None
            else:
                scope = analysis.scopes[parent_id]

        return visible_bindings

    def reference_candidates(self, uri: str):
        """Return named ranges that can participate in reference searches."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return []

        analysis = self.analyze(uri)
        candidates = []

        for import_entry in analysis.import_entries:
            candidates.append({
                "name": import_entry.local_name,
                "range": import_entry.selection_range,
            })
            # Aliased from-imports carry a second name token for the
            # exported name, which references and rename must see too.
            if (
                import_entry.export_range is not None
                and import_entry.export_range != import_entry.selection_range
            ):
                candidates.append({
                    "name": import_entry.export_name,
                    "range": import_entry.export_range,
                })

        for occurrence in analysis.occurrences:
            candidates.append({
                "name": occurrence.name,
                "range": occurrence.range,
                "binding_id": occurrence.binding_id,
            })

        for occurrence in analysis.member_occurrences:
            candidates.append({
                "name": occurrence.name,
                "range": occurrence.range,
            })

        return candidates

    def is_local_definition(self, definition):
        """Return whether only the document of a definition can refer to it."""
        return (
            definition.binding_id is not None
            and not definition.exported
            and not self.member_reachable_definition(definition)
        )

    def definition_key(self, definition):
        """Return a stable key used to compare resolved definitions."""
        if definition.binding_id is not None and not definition.exported:
            return (definition.uri, definition.binding_id)

        selection_range = definition.selection_range
        return (
            definition.uri,
            selection_range.start.line,
            selection_range.start.character,
            selection_range.end.line,
            selection_range.end.character,
        )

    def member_reachable_definition(self, definition):
        """Return whether a definition is also exposed as an ORD cell member.

        Pin, net, and viewgen declarations resolve to plain bindings, while
        their ``.name`` access sites resolve through the cell member table.
        Both spellings must compare and search alike for references and
        rename to see one symbol.
        """
        if definition.cell_member:
            return True
        if definition.binding_id is None:
            return False

        uri = definition.uri
        if not self.is_ord_uri(uri):
            return False

        analysis = self.analyze(uri)
        start = definition.selection_range.start
        for symbol in analysis.symbols:
            if symbol.kind != "class":
                continue
            if not range_contains(symbol.range, start):
                continue

            member = self.ord_cell_members(uri, symbol.name).get(definition.name)
            return (
                member is not None
                and member.selection_range == definition.selection_range
            )
        return False

    def definition_with_origin(self, definition, origin_range):
        """Return a definition copy annotated with the source identifier range."""
        if definition is None:
            return None

        return definition._replace(origin_range=origin_range)

    def find_export(self, uri: str, name: str):
        """Find an exported ORD symbol in a document and its imports."""
        for analysis_uri, analysis in self.analyze_related(uri).items():
            if name not in analysis.exports:
                continue

            for symbol in analysis.symbols:
                if symbol.name == name:
                    return AnalysisDefinition(
                        uri=analysis_uri,
                        name=symbol.name,
                        kind=symbol.kind,
                        range=symbol.range,
                        selection_range=symbol.selection_range,
                    )

        return None

    def module_definition(self, uri: str, module_name: str):
        """Resolve an ORD or Python module definition from an import name."""
        uri = self.canonical_uri(uri)
        module_uri = self.resolve_module_uri(uri, module_name)
        if module_uri is None:
            return self.python_definition(self.resolve_python_module_path(uri, module_name))

        module_base = module_name.split(".")[-1]
        return AnalysisDefinition(
            uri=module_uri,
            name=module_base,
            kind="module",
            range=AnalysisRange(
                start=AnalysisPosition(1, 1),
                end=AnalysisPosition(1, 1),
            ),
            selection_range=AnalysisRange(
                start=AnalysisPosition(1, 1),
                end=AnalysisPosition(1, 1),
            ),
        )

    def import_entry_at_position(self, uri: str, position: AnalysisPosition):
        """Return the import entry whose selected name contains a position."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return None

        for import_entry in self.analyze(uri).import_entries:
            name_ranges = [import_entry.selection_range]
            if import_entry.export_range is not None:
                name_ranges.append(import_entry.export_range)

            for name_range in name_ranges:
                start = name_range.start
                end = name_range.end

                if start.line != position.line or end.line != position.line:
                    continue

                if start.character <= position.character < end.character:
                    return import_entry

        return None

    def name_at_position(self, uri: str, position: AnalysisPosition):
        """Return the identifier token at or immediately before a position."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return None

        lines = self.document_lines(uri)
        if position.line < 1 or position.line > len(lines):
            return None

        line = lines[position.line - 1]
        if line == "":
            return None

        offset = position.character - 1
        if offset >= len(line):
            offset = len(line) - 1

        if offset < 0:
            return None

        if not (line[offset].isalnum() or line[offset] == "_"):
            if offset == 0 or not (line[offset - 1].isalnum() or line[offset - 1] == "_"):
                return None
            offset -= 1

        start = offset
        while start > 0 and (line[start - 1].isalnum() or line[start - 1] == "_"):
            start -= 1

        end = offset + 1
        while end < len(line) and (line[end].isalnum() or line[end] == "_"):
            end += 1

        name = line[start:end]
        if name == "":
            return None

        return {
            "name": name,
            "range": AnalysisRange(
                start=AnalysisPosition(position.line, start + 1),
                end=AnalysisPosition(position.line, end + 1),
            ),
        }

    def resolve_name(self, uri: str, name: str):
        """Resolve a top-level ORD or Python name visible from a document."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return None

        analysis = self.analyze(uri)

        if name in analysis.exports:
            return self.find_export(uri, name)

        for import_entry in reversed(analysis.import_entries):
            if import_entry.local_name != name:
                continue

            if import_entry.kind == "from":
                match = self.resolve_from_import(
                    uri,
                    import_entry.module,
                    import_entry.export_name,
                )
            elif import_entry.is_alias:
                match = self.module_definition(uri, import_entry.module)
            else:
                # import a.b binds the package a, not the module a.b.
                match = self.module_definition(uri, import_entry.local_name)
            if match is not None:
                return match

        # A star import binds the names of the module's __all__, or else
        # its public names.
        for import_entry in reversed(analysis.import_entries):
            if import_entry.kind != "from" or import_entry.export_name != "*":
                continue

            module_name = import_entry.module
            import_uri = self.resolve_module_uri(uri, module_name)
            if import_uri is None:
                module_path = self.resolve_python_module_path(uri, module_name)
                if name not in self.python_index.star_names(module_path):
                    continue
                match = self.python_definition(module_path, export_name=name)
            elif name.startswith("_"):
                continue
            else:
                match = self.find_export(import_uri, name)
            if match is not None:
                return match

        # Module-scope assignments below the use site still resolve:
        # viewgens execute deferred, like Python globals read at call time.
        module_scope = analysis.scopes.get(0)
        for binding_id in module_scope.bindings if module_scope is not None else []:
            binding = analysis.binding_map.get(binding_id)
            if binding is None or binding.name != name:
                continue

            return AnalysisDefinition(
                uri=uri,
                name=binding.name,
                kind=binding.kind,
                range=binding.range,
                selection_range=binding.selection_range,
                binding_id=binding.id,
                exported=binding.exported,
            )

        return None

    def hover(self, uri: str, position: AnalysisPosition):
        """Return hover contents for the definition at a position."""
        uri = self.canonical_uri(uri)
        definition = self.definition(uri, position)
        if definition is None:
            return None

        name_info = self.name_at_position(uri, position)
        hover_range = definition.selection_range
        if name_info is not None:
            hover_range = name_info["range"]

        contents = "{} {}".format(definition.kind, definition.name)
        if definition.uri != uri:
            contents += "\n{}".format(self.display_uri(definition.uri))

        return {
            "contents": contents,
            "markdown": self.hover_markdown(uri, definition),
            "range": hover_range,
        }

    def hover_markdown(self, uri: str, definition):
        """Return markdown hover contents for a resolved definition."""
        parts = [
            "```ord\n{}\n```".format(self.definition_header(uri, definition)),
        ]
        if definition.uri != uri:
            parts.append("*{}*".format(self.display_uri(definition.uri)))

        docstring = definition.docstring
        if docstring:
            parts.append(docstring)

        return "\n\n".join(parts)

    def definition_header(self, uri: str, definition):
        """Return the signature-style header line for a definition."""
        kind = definition.kind
        name = definition.name

        if kind == "class":
            signature = signatures.callable_signature(self, uri, definition)
            parameters = signature["parameters"] if signature is not None else []
            # Classes that declare cell parameters, and everything defined in
            # ORD source, read as cells to ORD users.
            keyword = "class"
            if parameters or self.is_ord_uri(definition.uri):
                keyword = "cell"
            if parameters:
                return "{} {}({})".format(
                    keyword,
                    name,
                    ", ".join(parameter["label"] for parameter in parameters),
                )
            return "{} {}".format(keyword, name)

        if kind == "function":
            signature = signatures.callable_signature(self, uri, definition)
            if signature is not None:
                return "def {}".format(signature["label"])
            return "function {}".format(name)

        if kind == "parameter" and definition.default:
            return "parameter {} = {}".format(name, definition.default)

        return "{} {}".format(kind, name)

    def node_target_binding_ids(self, uri: str, analysis):
        """Return the ids of bindings that are node statement targets.

        Built once per analysis. Pairing every binding with every node
        statement is quadratic, so target ranges are sorted and each
        binding start is checked against its bisection candidate only.
        Target ranges are disjoint source spans, making that candidate
        the only one that can contain the binding.
        """
        cache = self.analysis_cache(uri, analysis)
        binding_ids = cache.get("node_target_binding_ids")
        if binding_ids is not None:
            return binding_ids

        target_ranges = sorted(
            (statement.target_range for statement in analysis.node_statements),
            key=lambda target_range: target_range.start,
        )
        target_starts = [target_range.start for target_range in target_ranges]

        binding_ids = set()
        for binding in analysis.bindings:
            position = binding.selection_range.start
            index = bisect_right(target_starts, position) - 1
            if index >= 0 and range_contains(target_ranges[index], position):
                binding_ids.add(binding.id)

        cache["node_target_binding_ids"] = binding_ids
        return binding_ids

    def ord_cell_members(self, cell_uri: str, cell_name: str):
        """Collect members exposed by an ORD cell.

        Runs once per member occurrence during semantic diagnostics, so
        results are memoized for the lifetime of the document analysis.
        """
        cell_uri = self.canonical_uri(cell_uri)
        if not self.ensure_document(cell_uri):
            return dict()

        analysis = self.analyze(cell_uri)
        members_by_cell = self.analysis_cache(cell_uri, analysis).setdefault(
            "cell_members", dict()
        )
        if cell_name in members_by_cell:
            return members_by_cell[cell_name]

        members_by_cell[cell_name] = self.collect_ord_cell_members(
            cell_uri, analysis, cell_name
        )
        return members_by_cell[cell_name]

    def collect_ord_cell_members(self, cell_uri: str, analysis, cell_name: str):
        """Walk an analysis for the members exposed by one ORD cell."""
        cell_symbol = None
        for symbol in analysis.symbols:
            if symbol.name == cell_name and symbol.kind == "class":
                cell_symbol = symbol
                break

        if cell_symbol is None:
            return dict()

        members = dict()

        def add_binding_member(binding):
            kind = binding.kind
            # ORD cell parameters are `name = Parameter(...)` assignments in
            # the cell body. The inferred value type identifies them.
            if "Parameter" in (binding.type_names or []):
                kind = "parameter"

            members.setdefault(binding.name, AnalysisDefinition(
                uri=cell_uri,
                name=binding.name,
                kind=kind,
                range=binding.range,
                selection_range=binding.selection_range,
                binding_id=binding.id,
                cell_member=True,
            ))

        # Include directly declared cell members and view generators. This
        # covers self.schematic/self.layout and compact tests that declare pins
        # directly in the cell body.
        for scope in analysis.scopes.values():
            if scope.depth != 1:
                continue
            if not range_contains(scope.range, cell_symbol.selection_range.start):
                continue

            for binding_id in scope.bindings:
                binding = analysis.binding_map.get(binding_id)
                if binding is None or binding.name == "self":
                    continue
                add_binding_member(binding)

        # Normal ORD cells expose schematic instance members through their
        # symbol view. Layout instances additionally expose named layout
        # nodes. Only node statement targets become members: plain viewgen
        # locals such as loop counters stay invisible to instances.
        # Bindings are matched to targets by containment rather than range
        # equality, since a target range may span more than the bound name.
        # Ids are assigned in visit order, so sorting keeps document order
        # and the first declaration of a name wins setdefault as before.
        node_binding_ids = sorted(self.node_target_binding_ids(cell_uri, analysis))
        for symbol in analysis.symbols:
            if symbol.name not in ("symbol", "layout") or symbol.kind != "function":
                continue
            if not range_contains(cell_symbol.range, symbol.selection_range.start):
                continue

            for binding_id in node_binding_ids:
                binding = analysis.binding_map.get(binding_id)
                if binding is None or binding.kind != "variable":
                    continue
                if not range_contains(symbol.range, binding.selection_range.start):
                    continue
                add_binding_member(binding)

        return members

    def allows_dynamic_members(self, type_name: str):
        """Return whether the named type can expose runtime-defined members."""
        type_definition = self.resolve_core_type(type_name)
        if type_definition is None:
            return False
        return "view_builder" in self.type_members(type_definition)

    def resolve_core_type(self, type_name: str):
        """Resolve an ORDeC core type exported by ``ordec.core``."""
        core_type_name = CORE_TYPE_ALIASES.get(type_name, type_name)
        type_definition = self.python_definition(
            self.resolver.installed_module_path("ordec.core"),
            export_name=core_type_name,
        )
        if type_definition is None or type_definition.kind != "class":
            return None
        return type_definition

    def context_type_names_at_position(self, uri: str, position: AnalysisPosition):
        """Return type names implied by the innermost ORD context at ``position``."""
        analysis = self.analyze(uri)

        best_symbol = None
        for symbol in analysis.symbols:
            if symbol.kind != "context":
                continue
            if not range_contains(symbol.range, position):
                continue
            if best_symbol is None or range_contains(best_symbol.range, symbol.range.start):
                best_symbol = symbol

        if best_symbol is None:
            return []

        kind_name = best_symbol.name.split(" ", 1)[0]
        return context_type_names_for_kind(kind_name)

    def resolve_completion_type(self, uri: str, type_name: str):
        """Resolve ``type_name`` to an ORD or Python definition, or None."""
        type_definition = self.resolve_name(uri, type_name)
        if type_definition is not None:
            return type_definition

        core_definition = self.resolve_core_type(type_name)
        if core_definition is not None:
            return core_definition

        return None

    def cell_instance_members(self):
        """Return members common to schematic and layout cell instances.

        A cell instantiation may live in a schematic or a layout view and
        the static analysis cannot always tell which, so the union keeps
        member checks and completions valid for both.
        """
        schema_path = self.resolver.installed_module_path("ordec.core.schema")
        members = dict(self.python_class_members(schema_path, "SchemInstance"))
        members.update(self.python_class_members(schema_path, "LayoutInstance"))
        return members

    def type_members(self, type_definition):
        """Return a name→metadata mapping for members of a resolved type."""
        if type_definition.python_class is not None:
            members = self.python_class_members(
                type_definition.python_module,
                type_definition.python_class,
            )
            if self.resolve_core_type(type_definition.python_class) is None:
                members = dict(members)
                members.update(self.cell_instance_members())
            return members

        if type_definition.kind == "class":
            members = self.ord_cell_members(
                type_definition.uri,
                type_definition.name,
            )
            members = dict(members)
            members.update(self.cell_instance_members())
            return members

        return dict()

    def member_definition(self, uri: str, position: AnalysisPosition):
        """Resolve a member or parameter access at a document position."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return None

        analysis = self.analyze(uri)

        for occurrence in analysis.member_occurrences:
            if not range_contains(occurrence.range, position):
                continue

            type_names = list(occurrence.type_names)
            if occurrence.binding_id is not None:
                binding = analysis.binding_map.get(occurrence.binding_id)
                if binding is not None:
                    type_names = list(binding.type_names) + type_names

            seen_type_names = set()
            for type_name in type_names:
                if not type_name or type_name in seen_type_names:
                    continue
                seen_type_names.add(type_name)

                type_definition = self.resolve_completion_type(uri, type_name)
                if type_definition is None:
                    continue

                match = self.type_members(type_definition).get(occurrence.name)
                if match is not None:
                    return self.definition_with_origin(match, occurrence.range)

        return None

    def member_occurrence_at_position(self, uri: str, position: AnalysisPosition):
        """Return a member occurrence that contains a document position."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return None

        for occurrence in self.analyze(uri).member_occurrences:
            if range_contains(occurrence.range, position):
                return occurrence

        return None

    def folding_ranges(self, uri: str):
        """Return foldable symbol and import ranges for a document."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return []

        analysis = self.analyze(uri)
        ranges = []

        # Fold each multi-line symbol (cell, viewgen, function, class, context, path, net).
        # The parse tree range end spills past the last statement, so folds
        # stop at the symbol's last content-bearing line instead.
        for symbol in analysis.symbols:
            start_line = symbol.range.start.line
            end_line = symbol.content_end_line or symbol.range.end.line
            if end_line > start_line:
                ranges.append({
                    "start_line": start_line,
                    "end_line": end_line,
                    "kind": "region",
                })

        # Fold consecutive import blocks.
        if analysis.import_entries:
            import_lines = set()
            for entry in analysis.import_entries:
                for line in range(entry.range.start.line, entry.range.end.line + 1):
                    import_lines.add(line)

            sorted_lines = sorted(import_lines)
            block_start = sorted_lines[0]
            block_end = sorted_lines[0]
            for line in sorted_lines[1:]:
                if line == block_end + 1:
                    block_end = line
                else:
                    if block_end > block_start:
                        ranges.append({
                            "start_line": block_start,
                            "end_line": block_end,
                            "kind": "imports",
                        })
                    block_start = line
                    block_end = line

            if block_end > block_start:
                ranges.append({
                    "start_line": block_start,
                    "end_line": block_end,
                    "kind": "imports",
                })

        ranges.sort(key=lambda r: (r["start_line"], r["end_line"]))
        return ranges

    def selection_ranges(self, uri: str, positions):
        """Return nested selection ranges for document positions."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return [None for _ in positions]

        analysis = self.analyze(uri)

        # Build a sorted list of candidate containers from scopes and symbols.
        containers = []
        for scope in analysis.scopes.values():
            containers.append(scope.range)
        for symbol in analysis.symbols:
            containers.append(symbol.range)
            containers.append(symbol.selection_range)
        for binding in analysis.bindings:
            containers.append(binding.range)
            containers.append(binding.selection_range)

        # Deduplicate and sort by size descending (outermost first).
        unique_containers = sorted(
            set(containers),
            key=lambda r: (
                -(r.end.line - r.start.line) * 10000 - (r.end.character - r.start.character),
                r.start.line,
                r.start.character,
            ),
        )

        results = []
        for position in positions:
            # Find all containers that contain this position, sorted outermost first.
            matching = []
            for container in unique_containers:
                if range_contains(container, position) or (
                    position_before_or_equal(container.start, position)
                    and position_before_or_equal(position, container.end)
                ):
                    matching.append(container)

            # Also include the name token at the position as the innermost range.
            name_info = self.name_at_position(uri, position)
            if name_info is not None:
                matching.append(name_info["range"])

            if not matching:
                results.append(None)
                continue

            # Deduplicate and sort from outermost to innermost (largest to smallest).
            seen = set()
            deduplicated = []
            for r in matching:
                key = (r.start.line, r.start.character, r.end.line, r.end.character)
                if key not in seen:
                    seen.add(key)
                    deduplicated.append(r)

            deduplicated.sort(
                key=lambda r: (
                    -(r.end.line - r.start.line) * 10000 - (r.end.character - r.start.character),
                    r.start.line,
                    r.start.character,
                ),
            )

            # Build the chain from outermost to innermost.
            chain = None
            for r in deduplicated:
                chain = {
                    "range": r,
                    "parent": chain,
                }

            results.append(chain)

        return results

    def semantic_tokens(self, uri: str):
        """Return semantic token records for a document."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return []

        analysis = self.analyze(uri)
        tokens = []

        # Classify occurrences by their resolved binding kind. Names bound
        # outside the document, such as imported cells, take the kind of
        # the definition they resolve to.
        resolved_kinds = dict()
        for occurrence in analysis.occurrences:
            binding = analysis.binding_map.get(occurrence.binding_id)
            modifiers = []
            if binding is not None:
                kind = binding.kind
                if occurrence.range == binding.selection_range:
                    modifiers.append("definition")
            else:
                name = occurrence.name
                if name not in resolved_kinds:
                    definition = self.resolve_name(uri, name)
                    resolved_kinds[name] = None if definition is None else definition.kind
                kind = resolved_kinds[name]
                if kind is None:
                    continue

            tokens.append({
                "range": occurrence.range,
                "type": KIND_TOKEN_TYPES.get(kind, "variable"),
                "modifiers": modifiers,
            })

        # Classify member occurrences as properties.
        for occurrence in analysis.member_occurrences:
            tokens.append({
                "range": occurrence.range,
                "type": "property",
                "modifiers": [],
            })

        # Classify import names.
        for entry in analysis.import_entries:
            if entry.export_name == "*":
                continue

            kind = "module"
            if entry.kind == "from":
                definition = self.resolve_from_import(uri, entry.module, entry.export_name)
                kind = None if definition is None else definition.kind
            tokens.append({
                "range": entry.selection_range,
                "type": KIND_TOKEN_TYPES.get(kind, "variable"),
                "modifiers": [],
            })

        # Sort by position for delta encoding.
        tokens.sort(key=lambda t: (t["range"].start.line, t["range"].start.character))

        # Deduplicate: if a binding definition and an import entry cover the
        # same range, keep the first (occurrence-based) entry.
        deduplicated = []
        seen = set()
        for token in tokens:
            key = (
                token["range"].start.line,
                token["range"].start.character,
                token["range"].end.line,
                token["range"].end.character,
            )
            if key not in seen:
                seen.add(key)
                deduplicated.append(token)

        return deduplicated

    def workspace_symbols(self, query: str = ""):
        """Return exported workspace symbols matching an optional query."""
        query = query.lower()
        result = []

        for uri in self.workspace_uris():
            analysis = self.analyze(uri)
            for symbol in analysis.symbols:
                if symbol.name not in analysis.exports:
                    continue

                if query and query not in symbol.name.lower():
                    continue

                result.append(AnalysisDefinition(
                    uri=uri,
                    name=symbol.name,
                    kind=symbol.kind,
                    range=symbol.range,
                    selection_range=symbol.selection_range,
                ))

        self.evict_closed_documents()
        return result

    def references(self, uri: str, position: AnalysisPosition, search_uris=None):
        """Return references to the definition at a document position.

        search_uris restricts the searched documents. Highlights pass
        their own document to avoid a workspace-wide search.
        """
        uri = self.canonical_uri(uri)
        definition = self.definition(uri, position)
        if definition is None:
            return []

        references = []
        seen = set()
        target = self.definition_key(definition)
        if search_uris is None:
            search_uris = self.reference_search_uris(uri, definition)

        for ref_uri in search_uris:
            # All tokens of one binding resolve alike, so the verdict is
            # computed once per binding instead of once per token.
            binding_matches = {}
            for candidate in self.reference_candidates(ref_uri):
                binding_id = candidate.get("binding_id")
                if binding_id is not None and binding_id in binding_matches:
                    matches = binding_matches[binding_id]
                else:
                    resolved = self.definition(ref_uri, candidate["range"].start)
                    matches = (
                        resolved is not None
                        and self.definition_key(resolved) == target
                    )
                    if binding_id is not None:
                        binding_matches[binding_id] = matches

                if not matches:
                    continue

                key = (
                    ref_uri,
                    candidate["range"].start.line,
                    candidate["range"].start.character,
                    candidate["range"].end.line,
                    candidate["range"].end.character,
                )
                if key in seen:
                    continue
                seen.add(key)

                references.append({
                    "uri": ref_uri,
                    "name": candidate["name"],
                    "range": candidate["range"],
                })

        return references

    def reference_search_uris(self, uri: str, definition):
        """Return the documents that may contain references to a definition."""
        uri = self.canonical_uri(uri)
        if self.is_local_definition(definition):
            return [uri]

        target_uri = definition.uri
        if self.is_ord_uri(target_uri):
            uris = [uri, target_uri]
            uris.extend(sorted(self.workspace_dependents(target_uri)))
            if not self.workspace_root:
                uris.extend(sorted(self.analyze_related(uri).keys()))
        else:
            # Non-ORD definitions can still be referenced from the
            # requesting document, which may lie outside the workspace.
            uris = [uri]
            uris.extend(self.workspace_uris())

        result = []
        seen = set()
        for candidate_uri in uris:
            if candidate_uri in seen:
                continue
            seen.add(candidate_uri)
            result.append(candidate_uri)
        return result

    def document_highlights(self, uri: str, position: AnalysisPosition):
        """Return same-document highlights for the symbol at a position."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return []

        definition = self.definition(uri, position)
        if definition is None:
            return []

        definition_range = None
        if definition.uri == uri:
            definition_range = definition.selection_range

        name_info = self.name_at_position(uri, position)
        if name_info is not None:
            for import_entry in self.analyze(uri).import_entries:
                if import_entry.local_name != name_info["name"]:
                    continue

                definition_range = import_entry.selection_range
                break

        highlights = []
        for reference in self.references(uri, position, search_uris=[uri]):
            highlight = {
                "range": reference["range"],
                "kind": "read",
            }
            if definition_range is not None and reference["range"] == definition_range:
                highlight["kind"] = "write"

            highlights.append(highlight)

        return highlights

    def type_definition(self, uri: str, position: AnalysisPosition):
        """Resolve the defining type for the symbol at a document position."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return None

        analysis = self.analyze(uri)
        type_names = []
        origin_range = None

        local = self.local_definition(uri, position)
        if local is not None and local.binding_id is not None:
            binding = analysis.binding_map.get(local.binding_id)
            if binding is not None:
                type_names = list(binding.type_names)
                origin_range = local.origin_range

        for type_name in self.normalize_type_names(type_names):
            resolved = self.resolve_completion_type(uri, type_name)
            if resolved is not None and resolved.kind == "class":
                return self.definition_with_origin(resolved, origin_range)

        # On a type name itself, the type definition is the definition.
        definition = self.definition(uri, position)
        if definition is not None and definition.kind == "class":
            return definition

        return None

    def inlay_hints(self, uri: str, value_range: Optional[AnalysisRange] = None):
        """Return inferred-type inlay hints, optionally limited to a range."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return []

        analysis = self.analyze(uri)
        hints = []
        for record in analysis.type_hints:
            position = record.range.end
            if value_range is not None:
                if not position_before_or_equal(value_range.start, position):
                    continue
                if not position_before_or_equal(position, value_range.end):
                    continue

            # Only show hints whose type name resolves to a real cell or
            # class, so heuristic guesses do not turn into noise.
            for type_name in record.type_names:
                resolved = self.resolve_completion_type(uri, type_name)
                if resolved is None or resolved.kind != "class":
                    continue

                hints.append({
                    "position": position,
                    "label": type_name,
                    "kind": "type",
                })
                break

        return hints

    def definition(self, uri: str, position: AnalysisPosition):
        """Resolve the best definition for a document position."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return None

        name_info = self.name_at_position(uri, position)
        lookup_position = position
        if name_info is not None and name_info["range"].end == position:
            lookup_position = AnalysisPosition(position.line, position.character - 1)

        local_definition = self.local_definition(uri, lookup_position)
        if local_definition is not None:
            return local_definition

        member_definition = self.member_definition(uri, lookup_position)
        if member_definition is not None:
            return member_definition

        analysis = self.analyze(uri)
        for symbol in analysis.symbols:
            if range_contains(symbol.selection_range, lookup_position):
                return AnalysisDefinition(
                    uri=uri,
                    name=symbol.name,
                    kind=symbol.kind,
                    range=symbol.range,
                    selection_range=symbol.selection_range,
                    origin_range=symbol.selection_range,
                )

        import_entry = self.import_entry_at_position(uri, lookup_position)
        if import_entry is not None:
            origin_range = import_entry.selection_range
            if (
                import_entry.export_range is not None
                and range_contains(import_entry.export_range, lookup_position)
            ):
                origin_range = import_entry.export_range

            if import_entry.kind == "from":
                match = self.resolve_from_import(
                    uri,
                    import_entry.module,
                    import_entry.export_name,
                )
                if match is not None:
                    return self.definition_with_origin(match, origin_range)

            else:
                match = self.module_definition(uri, import_entry.module)
                if match is not None:
                    return self.definition_with_origin(match, origin_range)

        if name_info is None:
            return None

        definition = self.resolve_name(uri, name_info["name"])
        if definition is not None:
            return self.definition_with_origin(definition, name_info["range"])

        return self.definition_with_origin(
            self.resolve_completion_type(uri, name_info["name"]),
            name_info["range"],
        )

    # Delegators to the feature modules, which hold the docstrings.

    def completion_replace_range(self, uri: str, position: AnalysisPosition):
        return completions.completion_replace_range(self, uri, position)

    def completions(self, uri: str, position: AnalysisPosition):
        return completions.completions(self, uri, position)

    def signature_help(self, uri: str, position: AnalysisPosition):
        return signatures.signature_help(self, uri, position)

    def prepare_rename(self, uri: str, position: AnalysisPosition):
        return rename.prepare_rename(self, uri, position)

    def rename(self, uri: str, position: AnalysisPosition, new_name: str):
        return rename.rename(self, uri, position, new_name)

    def call_hierarchy_item(self, uri: str, position: AnalysisPosition):
        return hierarchy.call_hierarchy_item(self, uri, position)

    def incoming_calls(self, uri: str, position: AnalysisPosition):
        return hierarchy.incoming_calls(self, uri, position)

    def outgoing_calls(self, uri: str, position: AnalysisPosition):
        return hierarchy.outgoing_calls(self, uri, position)
