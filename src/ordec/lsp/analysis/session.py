# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import os
from pathlib import Path
from typing import Optional

# ordec imports
from .completions import CompletionsMixin
from .diagnostics import DiagnosticsMixin
from .hierarchy import CallHierarchyMixin
from .model import (
    AnalysisPosition,
    AnalysisRange,
    DocumentAnalysis,
    context_type_names_for_kind,
    file_uri_to_path,
    find_module_source,
    position_before_or_equal,
    range_contains,
    split_source_lines,
)
from .model import normalize_type_names as normalize_type_name_list
from .parser_pass import analyze_ord
from .python_index import PythonModuleIndex
from .rename import RenameMixin
from .signatures import SignatureHelpMixin

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


class AnalysisSession(
    CompletionsMixin,
    DiagnosticsMixin,
    RenameMixin,
    SignatureHelpMixin,
    CallHierarchyMixin,
):
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

    The mixins keep feature-specific implementation code separated, but those
    methods remain part of this facade rather than independent public entry
    points.
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
        self.python_index = PythonModuleIndex(workspace_root=self.workspace_root)
        self.workspace_uri_cache = None
        self.workspace_index = None
        self.workspace_dirty_uris = set()

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

    def last_good_analysis(self, doc):
        """Return the latest error-free analysis for a document record."""
        if doc is None:
            return None

        analysis = doc.get("analysis")
        if analysis is not None and not analysis.has_errors():
            return analysis

        return doc.get("last_good_analysis")

    def invalidate_workspace_index(self):
        """Clear cached workspace dependency information."""
        self.workspace_index = None
        self.workspace_dirty_uris.clear()

    def mark_workspace_uri_dirty(self, uri: str):
        """Mark one ORD document's workspace-import row as stale."""
        uri = self.canonical_uri(uri)
        if not self.is_ord_uri(uri):
            return

        if not self.workspace_index_may_track(uri):
            return

        self.workspace_dirty_uris.add(uri)

    def workspace_index_may_track(self, uri: str):
        """Return whether a URI could affect the workspace import graph."""
        if self.workspace_index is None:
            return False

        if uri in self.workspace_index["uris"]:
            return True

        return self.uri_in_workspace(uri)

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
        """Store a document snapshot and mark related workspace state dirty."""
        uri = self.canonical_uri(uri)
        previous = self.documents.get(uri)
        self.documents[uri] = {
            "text": text,
            "version": version,
            "analysis": None,
            "last_good_analysis": self.last_good_analysis(previous),
            "is_open": is_open,
            "last_access": 0,
        }
        self.record_document_access(uri)
        self.mark_workspace_uri_dirty(uri)
        return uri

    def close_document(self, uri: str):
        """Close a document and restore its on-disk snapshot."""
        uri = self.canonical_uri(uri)
        document = self.documents.pop(uri, None)
        if document is None:
            return

        path = self.file_uri_path(uri)
        if path is None or not path.is_file():
            self.mark_workspace_uri_dirty(uri)
            return

        try:
            self.open_path(str(path))
        except (OSError, UnicodeDecodeError):
            self.mark_workspace_uri_dirty(uri)

    def ensure_document(self, uri: str):
        """Load a file-backed document when it is not already tracked."""
        uri = self.canonical_uri(uri)
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

    def invalidate_path(self, path: str):
        """Invalidate cached state for a filesystem path."""
        path = Path(os.path.abspath(path))
        if path.suffix == ".py":
            # The Python index tracks symlink-resolved module paths.
            self.invalidate_python_module_path(path.resolve())
            return None

        if path.suffix != ".ord":
            return None

        # The Python index also caches installed `.ord` modules resolved
        # through their parent Python package.
        self.invalidate_python_module_path(path.resolve())
        uri = path.as_uri()
        if self.workspace_uri_cache is not None and self.uri_in_workspace(uri):
            if path.is_file():
                self.workspace_uri_cache.add(uri)
            else:
                self.workspace_uri_cache.discard(uri)

        doc = self.documents.get(uri)
        if doc is not None and doc.get("is_open"):
            doc["analysis"] = None
            self.mark_workspace_uri_dirty(uri)
            return uri

        if path.exists():
            return self.update_path(str(path))

        self.documents.pop(uri, None)
        self.mark_workspace_uri_dirty(uri)
        return uri

    def invalidate_uri(self, uri: str):
        """Invalidate cached state for a file URI."""
        uri = self.canonical_uri(uri)
        path = self.file_uri_path(uri)
        if path is None:
            return None

        return self.invalidate_path(str(path))

    def resolve_module_uri(self, uri: str, module_name: str):
        """Resolve an ORD import name relative to a document URI."""
        uri = self.canonical_uri(uri)
        doc_path = self.file_uri_path(uri)
        if doc_path is None:
            return None

        if module_name.startswith("."):
            dot_count = 0
            while dot_count < len(module_name) and module_name[dot_count] == ".":
                dot_count += 1

            import_path = doc_path.parent
            for _ in range(dot_count - 1):
                import_path = import_path.parent

            module_tail = module_name[dot_count:]
            if module_tail:
                import_path = import_path.joinpath(*module_tail.split("."))

            resolved = find_module_source(
                import_path,
                (".ord",),
                package_only=not module_tail,
            )
            return resolved.as_uri() if resolved is not None else None

        # Absolute names resolve against the workspace root first, then
        # against the importing document's own directory, matching the
        # runtime importer which searches the script's directory.
        base_dirs = []
        if self.workspace_root:
            base_dirs.append(Path(self.workspace_root))
        if doc_path.parent not in base_dirs:
            base_dirs.append(doc_path.parent)

        module_parts = module_name.split(".")
        for base_dir in base_dirs:
            resolved = find_module_source(
                base_dir.joinpath(*module_parts),
                (".ord",),
            )
            if resolved is not None:
                return resolved.as_uri()

        return None

    def from_import_module_name(self, module_name: str, export_name: str):
        """Return the submodule candidate named by a from-import."""
        if not export_name or export_name == "*":
            return None

        separator = "" if module_name.endswith(".") else "."
        return module_name + separator + export_name

    def ord_from_import_uris(self, uri: str, module_name: str, export_name: str):
        """Return ORD module and submodule candidates for a from-import."""
        module_names = [module_name]
        submodule_name = self.from_import_module_name(module_name, export_name)
        if submodule_name is not None:
            module_names.append(submodule_name)

        uris = []
        for candidate_name in module_names:
            import_uri = self.resolve_module_uri(uri, candidate_name)
            if import_uri is None or import_uri in uris:
                continue
            uris.append(import_uri)
        return uris

    def resolve_from_import(self, uri: str, module_name: str, export_name: str):
        """Resolve a from-import export or submodule definition."""
        module_uri = self.resolve_module_uri(uri, module_name)
        if module_uri is not None and export_name != "*":
            match = self.find_export(module_uri, export_name)
            if match is not None:
                return match

        submodule_name = self.from_import_module_name(
            module_name,
            export_name,
        )
        if submodule_name is not None:
            submodule_uri = self.resolve_module_uri(uri, submodule_name)
            if submodule_uri is not None:
                return self.module_definition(uri, submodule_name)

        if module_uri is not None:
            return None

        python_module_name = self.resolve_python_import_name(uri, module_name)
        return self.python_definition(
            python_module_name,
            export_name=export_name,
        )

    def resolve_python_import_name(self, uri: str, module_name: str):
        """Resolve a possibly relative Python import name for a document."""
        return self.python_index.resolve_import_name(uri, module_name)

    def python_module_exists(self, module_name: str):
        """Return whether a Python module can be imported or found locally."""
        return self.python_index.module_exists(module_name)

    def invalidate_python_module_path(self, path: Path):
        """Invalidate cached Python analysis for modules backed by a path."""
        self.python_index.invalidate_module_path(path)

    def python_module_info(self, module_name: str):
        """Analyze a Python module enough for ORD import and member lookup."""
        return self.python_index.module_info(module_name)

    def python_definition(self, module_name: str, export_name: Optional[str] = None, seen=None):
        """Resolve a Python module or exported member definition."""
        return self.python_index.definition(
            module_name,
            export_name=export_name,
            seen=seen,
        )


    def python_class_members(self, module_name: str, class_name: str, seen=None):
        """Collect Python class members, including inherited members."""
        return self.python_index.class_members(module_name, class_name, seen=seen)

    def analyze(self, uri: str):
        """Return cached document analysis, parsing the document when needed."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return DocumentAnalysis(uri=uri, version=None, diagnostics=[], symbols=[])

        doc = self.documents[uri]
        if doc["analysis"] is None:
            analysis = analyze_ord(doc["text"], uri=uri, version=doc["version"])
            if analysis.has_errors():
                last_good = doc.get("last_good_analysis")
                if last_good is not None:
                    analysis = last_good.with_diagnostics(
                        analysis.diagnostics,
                        uri=uri,
                        version=doc["version"],
                    )
            else:
                doc["last_good_analysis"] = analysis
            doc["analysis"] = analysis
        return doc["analysis"]

    def diagnostics(self, uri: str):
        """Return parser and semantic diagnostics for a document."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return []

        analysis = self.analyze(uri)
        if analysis.has_errors():
            return analysis.diagnostics

        return analysis.diagnostics + self.semantic_diagnostics(uri)

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
            self.mark_workspace_uri_dirty(uri)
            return uri

        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Watched-file races and non-UTF-8 files must not abort
            # invalidation: drop the cached copy instead.
            self.documents.pop(uri, None)
            self.mark_workspace_uri_dirty(uri)
            return uri
        self.update_document(uri, text, version=version, is_open=False)
        return uri

    def workspace_ord_paths(self, root_path: Path):
        """Yield workspace ORD files, pruning hidden and dependency directories.

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
                if filename.endswith(".ord"):
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
                        for path in self.workspace_ord_paths(root_path)
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
        """Build or return cached ORD import dependency indexes."""
        if self.workspace_index is not None:
            self.refresh_workspace_import_rows()
            self.evict_closed_documents()
            if self.workspace_index is not None:
                return self.workspace_index

        uris = set(self.workspace_uris())
        imports_by_uri = dict()
        dependents_by_uri = dict()

        for uri in sorted(uris):
            import_uris = set(self.resolve_import_uris(uri))
            imports_by_uri[uri] = import_uris
            for import_uri in import_uris:
                dependents_by_uri.setdefault(import_uri, set()).add(uri)

        self.workspace_index = {
            "uris": uris,
            "imports": imports_by_uri,
            "dependents": dependents_by_uri,
        }
        self.evict_closed_documents()
        return self.workspace_index

    def refresh_workspace_import_rows(self):
        """Refresh stale rows in the cached workspace import graph."""
        if self.workspace_index is None or not self.workspace_dirty_uris:
            return

        dirty_uris = set(self.workspace_dirty_uris)
        self.workspace_dirty_uris.clear()

        for uri in sorted(dirty_uris):
            if not self.is_ord_uri(uri):
                continue

            path = self.file_uri_path(uri)
            if not path.exists() and uri not in self.documents:
                self.remove_workspace_import_row(uri)
                continue

            if uri not in self.workspace_index["uris"]:
                # A newly created file can change how unchanged documents
                # resolve their imports, so refreshing only dirty rows
                # would leave the dependents graph stale. Rebuild instead.
                self.invalidate_workspace_index()
                return

            old_imports = self.workspace_index["imports"].get(uri, set())
            import_uris = set(self.resolve_import_uris(uri))
            self.workspace_index["imports"][uri] = import_uris

            for import_uri in old_imports - import_uris:
                dependents = self.workspace_index["dependents"].get(import_uri)
                if dependents is None:
                    continue
                dependents.discard(uri)
                if not dependents:
                    self.workspace_index["dependents"].pop(import_uri, None)

            for import_uri in import_uris - old_imports:
                self.workspace_index["dependents"].setdefault(import_uri, set()).add(uri)
        self.evict_closed_documents()

    def remove_workspace_import_row(self, uri: str):
        """Remove one URI from the cached workspace import graph."""
        if self.workspace_index is None:
            return

        self.workspace_index["uris"].discard(uri)
        old_imports = self.workspace_index["imports"].pop(uri, set())
        for import_uri in old_imports:
            dependents = self.workspace_index["dependents"].get(import_uri)
            if dependents is None:
                continue
            dependents.discard(uri)
            if not dependents:
                self.workspace_index["dependents"].pop(import_uri, None)

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

        imports = []
        seen = set()

        for import_entry in self.analyze(uri).import_entries:
            if import_entry.kind == "from":
                import_uris = self.ord_from_import_uris(
                    uri,
                    import_entry.module,
                    import_entry.export_name,
                )
            else:
                import_uris = [self.resolve_module_uri(uri, import_entry.module)]

            for import_uri in import_uris:
                if import_uri is None or import_uri in seen:
                    continue
                seen.add(import_uri)
                imports.append(import_uri)

        return imports

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
            if not range_contains(binding["selection_range"], position):
                continue

            return {
                "uri": uri,
                "name": binding["name"],
                "kind": binding["kind"],
                "range": binding["range"],
                "selection_range": binding["selection_range"],
                "origin_range": binding["selection_range"],
                "binding_id": binding["id"],
                "scope_id": binding["scope_id"],
                "exported": binding["exported"],
            }

        for occurrence in analysis.occurrences:
            if not range_contains(occurrence["range"], position):
                continue

            binding = analysis.binding_map.get(occurrence["binding_id"])
            if binding is None:
                continue

            return {
                "uri": uri,
                "name": binding["name"],
                "kind": binding["kind"],
                "range": binding["range"],
                "selection_range": binding["selection_range"],
                "origin_range": occurrence["range"],
                "binding_id": binding["id"],
                "scope_id": binding["scope_id"],
                "exported": binding["exported"],
            }

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
            if not range_contains(current_scope["range"], position):
                continue

            if current_scope["depth"] <= scope["depth"]:
                continue

            scope = current_scope

        visible_bindings = []
        visible_names = set()

        while scope is not None:
            for binding_id in reversed(scope["bindings"]):
                binding = analysis.binding_map[binding_id]
                if binding["name"] in visible_names:
                    continue

                if not position_before_or_equal(binding["selection_range"].start, position):
                    continue

                visible_bindings.append(binding)
                visible_names.add(binding["name"])

            parent_id = scope["parent_id"]
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
                "name": occurrence["name"],
                "range": occurrence["range"],
                "binding_id": occurrence.get("binding_id"),
            })

        for occurrence in analysis.member_occurrences:
            candidates.append({
                "name": occurrence["name"],
                "range": occurrence["range"],
            })

        return candidates

    def definition_key(self, definition):
        """Return a stable key used to compare resolved definitions."""
        if definition.get("binding_id") is not None and not definition.get("exported"):
            return (definition["uri"], definition["binding_id"])

        selection_range = definition.get("selection_range")
        if selection_range is not None:
            return (
                definition["uri"],
                selection_range.start.line,
                selection_range.start.character,
                selection_range.end.line,
                selection_range.end.character,
            )

        return (
            definition["uri"],
            definition["name"],
            definition["kind"],
        )

    def member_reachable_definition(self, definition):
        """Return whether a definition is also exposed as an ORD cell member.

        Pin, net, and viewgen declarations resolve to plain bindings, while
        their ``.name`` access sites resolve through the cell member table.
        Both spellings must compare and search alike for references and
        rename to see one symbol.
        """
        if definition.get("cell_member"):
            return True
        if definition.get("binding_id") is None:
            return False

        uri = definition["uri"]
        if not self.is_ord_uri(uri):
            return False

        analysis = self.analyze(uri)
        start = definition["selection_range"].start
        for symbol in analysis.symbols:
            if symbol.kind != "class":
                continue
            if not range_contains(symbol.range, start):
                continue

            member = self.ord_cell_members(uri, symbol.name).get(definition["name"])
            return (
                member is not None
                and member["selection_range"] == definition["selection_range"]
            )
        return False

    def definition_with_origin(self, definition, origin_range):
        """Return a definition copy annotated with the source identifier range."""
        if definition is None:
            return None

        result = dict(definition)
        result["origin_range"] = origin_range
        return result

    def find_export(self, uri: str, name: str):
        """Find an exported ORD symbol in a document and its imports."""
        for analysis_uri, analysis in self.analyze_related(uri).items():
            if name not in analysis.exports:
                continue

            for symbol in analysis.symbols:
                if symbol.name == name:
                    return {
                        "uri": analysis_uri,
                        "name": symbol.name,
                        "kind": symbol.kind,
                        "range": symbol.range,
                        "selection_range": symbol.selection_range,
                    }

        return None

    def module_definition(self, uri: str, module_name: str):
        """Resolve an ORD or Python module definition from an import name."""
        uri = self.canonical_uri(uri)
        module_uri = self.resolve_module_uri(uri, module_name)
        python_module_name = self.resolve_python_import_name(uri, module_name)
        if module_uri is None:
            return self.python_definition(python_module_name)

        module_base = module_name.split(".")[-1]
        return {
            "uri": module_uri,
            "name": module_base,
            "kind": "module",
            "range": AnalysisRange(
                start=AnalysisPosition(1, 1),
                end=AnalysisPosition(1, 1),
            ),
            "selection_range": AnalysisRange(
                start=AnalysisPosition(1, 1),
                end=AnalysisPosition(1, 1),
            ),
        }

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
            else:
                match = self.module_definition(uri, import_entry.module)
            if match is not None:
                return match

        for import_entry in reversed(analysis.import_entries):
            if import_entry.kind != "from" or import_entry.export_name != "*":
                continue

            module_name = import_entry.module
            import_uri = self.resolve_module_uri(uri, module_name)
            if import_uri is None:
                python_module_name = self.resolve_python_import_name(uri, module_name)
                match = self.python_definition(python_module_name, export_name=name)
            else:
                match = self.find_export(import_uri, name)
            if match is not None:
                return match

        # Module-scope assignments below the use site still resolve:
        # viewgens execute deferred, like Python globals read at call time.
        for binding_id in analysis.scopes.get(0, {}).get("bindings", []):
            binding = analysis.binding_map.get(binding_id)
            if binding is None or binding["name"] != name:
                continue

            return {
                "uri": uri,
                "name": binding["name"],
                "kind": binding["kind"],
                "range": binding["range"],
                "selection_range": binding["selection_range"],
                "binding_id": binding["id"],
                "exported": binding.get("exported"),
            }

        return None

    def hover(self, uri: str, position: AnalysisPosition):
        """Return hover contents for the definition at a position."""
        uri = self.canonical_uri(uri)
        definition = self.definition(uri, position)
        if definition is None:
            return None

        name_info = self.name_at_position(uri, position)
        hover_range = definition["selection_range"]
        if name_info is not None:
            hover_range = name_info["range"]

        contents = "{} {}".format(definition["kind"], definition["name"])
        if definition["uri"] != uri:
            contents += "\n{}".format(self.display_uri(definition["uri"]))

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
        if definition["uri"] != uri:
            parts.append("*{}*".format(self.display_uri(definition["uri"])))

        docstring = definition.get("docstring")
        if docstring:
            parts.append(docstring)

        return "\n\n".join(parts)

    def definition_header(self, uri: str, definition):
        """Return the signature-style header line for a definition."""
        kind = definition["kind"]
        name = definition["name"]

        if kind == "class":
            signature = self.callable_signature(uri, definition)
            parameters = signature["parameters"] if signature is not None else []
            # Classes that declare cell parameters, and everything defined in
            # ORD source, read as cells to ORD users.
            keyword = "class"
            if parameters or self.is_ord_uri(definition["uri"]):
                keyword = "cell"
            if parameters:
                return "{} {}({})".format(
                    keyword,
                    name,
                    ", ".join(parameter["label"] for parameter in parameters),
                )
            return "{} {}".format(keyword, name)

        if kind == "function":
            signature = self.callable_signature(uri, definition)
            if signature is not None:
                return "def {}".format(signature["label"])
            return "function {}".format(name)

        if kind == "parameter" and definition.get("default"):
            return "parameter {} = {}".format(name, definition["default"])

        return "{} {}".format(kind, name)

    def ord_cell_members(self, cell_uri: str, cell_name: str):
        """Collect members exposed by an ORD cell."""
        cell_uri = self.canonical_uri(cell_uri)
        if not self.ensure_document(cell_uri):
            return dict()

        analysis = self.analyze(cell_uri)

        cell_symbol = None
        for symbol in analysis.symbols:
            if symbol.name == cell_name and symbol.kind == "class":
                cell_symbol = symbol
                break

        if cell_symbol is None:
            return dict()

        members = dict()

        def add_binding_member(binding):
            kind = binding["kind"]
            # ORD cell parameters are `name = Parameter(...)` assignments in
            # the cell body. The inferred value type identifies them.
            if "Parameter" in (binding.get("type_names") or []):
                kind = "parameter"

            members.setdefault(binding["name"], {
                "uri": cell_uri,
                "name": binding["name"],
                "kind": kind,
                "range": binding["range"],
                "selection_range": binding["selection_range"],
                "binding_id": binding["id"],
                "cell_member": True,
            })

        # Include directly declared cell members and view generators. This
        # covers self.schematic/self.layout and compact tests that declare pins
        # directly in the cell body.
        for scope in analysis.scopes.values():
            if scope["depth"] != 1:
                continue
            if not range_contains(scope["range"], cell_symbol.selection_range.start):
                continue

            for binding_id in scope["bindings"]:
                binding = analysis.binding_map.get(binding_id)
                if binding is None or binding["name"] == "self":
                    continue
                add_binding_member(binding)

        # Normal ORD cells expose schematic instance members through their
        # symbol view. Layout instances additionally expose named layout
        # nodes. Only node statement targets become members: plain viewgen
        # locals such as loop counters stay invisible to instances.
        # Multi-name declarations such as `path out_p, out_n` record one
        # statement whose target range spans all bound names, so bindings are
        # matched by containment rather than range equality.
        node_target_ranges = [
            statement["target_range"]
            for statement in analysis.node_statements
        ]
        for symbol in analysis.symbols:
            if symbol.name not in ("symbol", "layout") or symbol.kind != "function":
                continue
            if not range_contains(cell_symbol.range, symbol.selection_range.start):
                continue

            for binding in analysis.bindings:
                if binding["kind"] != "variable":
                    continue
                if not any(
                    range_contains(target_range, binding["selection_range"].start)
                    for target_range in node_target_ranges
                ):
                    continue
                if not range_contains(symbol.range, binding["selection_range"].start):
                    continue
                add_binding_member(binding)

        return members

    def allows_dynamic_members(self, type_name: str):
        """Return whether the named type can expose runtime-defined members."""
        type_definition = self.resolve_core_type(type_name)
        if type_definition is None:
            return False
        return "view_context" in self.type_members(type_definition)

    def resolve_core_type(self, type_name: str):
        """Resolve an ORDeC core type exported by ``ordec.core``."""
        core_type_name = CORE_TYPE_ALIASES.get(type_name, type_name)
        type_definition = self.python_definition("ordec.core", export_name=core_type_name)
        if type_definition is None or type_definition.get("kind") != "class":
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
        members = dict(self.python_class_members("ordec.core.schema", "SchemInstance"))
        members.update(self.python_class_members("ordec.core.schema", "LayoutInstance"))
        return members

    def type_members(self, type_definition):
        """Return a name→metadata mapping for members of a resolved type."""
        if "python_module" in type_definition and "python_class" in type_definition:
            members = self.python_class_members(
                type_definition["python_module"],
                type_definition["python_class"],
            )
            if self.resolve_core_type(type_definition["python_class"]) is None:
                members = dict(members)
                members.update(self.cell_instance_members())
            return members

        if type_definition.get("kind") == "class" and "uri" in type_definition:
            members = self.ord_cell_members(
                type_definition["uri"],
                type_definition["name"],
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
            if not range_contains(occurrence["range"], position):
                continue

            type_names = list(occurrence["type_names"])
            if occurrence["binding_id"] is not None:
                binding = analysis.binding_map.get(occurrence["binding_id"])
                if binding is not None:
                    type_names = list(binding.get("type_names", [])) + type_names

            seen_type_names = set()
            for type_name in type_names:
                if not type_name or type_name in seen_type_names:
                    continue
                seen_type_names.add(type_name)

                type_definition = self.resolve_completion_type(uri, type_name)
                if type_definition is None:
                    continue

                match = self.type_members(type_definition).get(occurrence["name"])
                if match is not None:
                    return self.definition_with_origin(match, occurrence["range"])

        return None

    def member_occurrence_at_position(self, uri: str, position: AnalysisPosition):
        """Return a member occurrence that contains a document position."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return None

        for occurrence in self.analyze(uri).member_occurrences:
            if range_contains(occurrence["range"], position):
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
            containers.append(scope["range"])
        for symbol in analysis.symbols:
            containers.append(symbol.range)
            containers.append(symbol.selection_range)
        for binding in analysis.bindings:
            containers.append(binding["range"])
            containers.append(binding["selection_range"])

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

        # Classify occurrences by their resolved binding kind.
        for occurrence in analysis.occurrences:
            binding = analysis.binding_map.get(occurrence["binding_id"])
            if binding is None:
                continue

            kind = binding["kind"]
            token_type = "variable"
            if kind == "class":
                token_type = "class"
            elif kind == "function":
                token_type = "function"
            elif kind == "parameter":
                token_type = "parameter"

            modifiers = []
            if occurrence["range"] == binding["selection_range"]:
                modifiers.append("definition")

            tokens.append({
                "range": occurrence["range"],
                "type": token_type,
                "modifiers": modifiers,
            })

        # Classify member occurrences as properties.
        for occurrence in analysis.member_occurrences:
            tokens.append({
                "range": occurrence["range"],
                "type": "property",
                "modifiers": [],
            })

        # Classify import names.
        for entry in analysis.import_entries:
            if entry.export_name == "*":
                continue

            token_type = "namespace" if entry.kind == "import" else "variable"
            tokens.append({
                "range": entry.selection_range,
                "type": token_type,
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

                result.append({
                    "uri": uri,
                    "name": symbol.name,
                    "kind": symbol.kind,
                    "range": symbol.range,
                    "selection_range": symbol.selection_range,
                })

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
        if (
            definition.get("binding_id") is not None
            and not definition.get("exported")
            and not self.member_reachable_definition(definition)
        ):
            return [uri]

        target_uri = definition["uri"]
        if self.is_ord_uri(target_uri):
            uris = [uri, target_uri]
            uris.extend(sorted(self.workspace_dependents(target_uri)))
            if not self.workspace_root:
                uris.extend(sorted(self.analyze_related(uri).keys()))

            result = []
            seen = set()
            for candidate_uri in uris:
                if candidate_uri in seen:
                    continue
                seen.add(candidate_uri)
                result.append(candidate_uri)
            return result

        return self.workspace_uris()

    def document_highlights(self, uri: str, position: AnalysisPosition):
        """Return same-document highlights for the symbol at a position."""
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return []

        definition = self.definition(uri, position)
        if definition is None:
            return []

        definition_range = None
        if definition["uri"] == uri:
            definition_range = definition["selection_range"]

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
        if local is not None and local.get("binding_id") is not None:
            binding = analysis.binding_map.get(local["binding_id"])
            if binding is not None:
                type_names = list(binding.get("type_names", []))
                origin_range = local.get("origin_range")

        for type_name in self.normalize_type_names(type_names):
            resolved = self.resolve_completion_type(uri, type_name)
            if resolved is not None and resolved.get("kind") == "class":
                return self.definition_with_origin(resolved, origin_range)

        # On a type name itself, the type definition is the definition.
        definition = self.definition(uri, position)
        if definition is not None and definition.get("kind") == "class":
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
            position = record["range"].end
            if value_range is not None:
                if not position_before_or_equal(value_range.start, position):
                    continue
                if not position_before_or_equal(position, value_range.end):
                    continue

            # Only show hints whose type name resolves to a real cell or
            # class, so heuristic guesses do not turn into noise.
            for type_name in record["type_names"]:
                resolved = self.resolve_completion_type(uri, type_name)
                if resolved is None or resolved.get("kind") != "class":
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
                return {
                    "uri": uri,
                    "name": symbol.name,
                    "kind": symbol.kind,
                    "range": symbol.range,
                    "selection_range": symbol.selection_range,
                    "origin_range": symbol.selection_range,
                }

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
