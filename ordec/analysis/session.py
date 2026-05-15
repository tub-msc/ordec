# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from pathlib import Path
from typing import Optional
from urllib.parse import unquote
from urllib.parse import urlparse

# ordec imports
from .completions import CompletionsMixin
from .diagnostics import DiagnosticsMixin
from .model import (
    AnalysisPosition,
    AnalysisRange,
    position_before_or_equal,
    range_contains,
)
from .parser_pass import analyze_ord
from .python_index import PythonModuleIndex
from .rename import RenameMixin
from .typeflow import TypeFlowMixin


class AnalysisSession(
    TypeFlowMixin,
    CompletionsMixin,
    DiagnosticsMixin,
    RenameMixin,
):
    """Stateful ORD analysis facade for open documents and workspace files.

    The LSP server should treat this class as its public boundary. Its
    LSP-facing methods are:

    - document lifecycle: ``open_document()``, ``update_document()``,
      ``close_document()``, ``invalidate_uri()``
    - diagnostics and symbols: ``analyze()``, ``diagnostics()``,
      ``workspace_symbols()``
    - navigation: ``definition()``, ``hover()``, ``references()``,
      ``document_highlights()``
    - editing and assists: ``completions()``, ``prepare_rename()``,
      ``rename()``, ``folding_ranges()``, ``selection_ranges()``,
      ``semantic_tokens()``

    The mixins keep feature-specific implementation code separated, but those
    methods remain part of this facade rather than independent public entry
    points.
    """

    def __init__(self, workspace_root: Optional[str] = None):
        """Initialize an analysis session.

        Args:
            workspace_root: Optional directory used to resolve workspace ORD
                modules and Python files.
        """
        self.workspace_root = workspace_root
        self.documents = dict()
        self.python_index = PythonModuleIndex(workspace_root=workspace_root)
        self.python_modules = self.python_index.python_modules
        self.workspace_index = None

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

    def clear_python_modules(self):
        """Clear cached Python module analysis and invalidate import caches."""
        self.python_index.clear()

    def normalize_type_names(self, type_names):
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

    def open_document(
        self,
        uri: str,
        text: str,
        version: Optional[int] = None,
        is_open: bool = True,
    ):
        """Register a newly opened document.

        Args:
            uri: Document URI.
            text: Full document text.
            version: Optional LSP document version.
            is_open: Whether the document is open in the editor.
        """
        previous = self.documents.get(uri)
        self.documents[uri] = {
            "text": text,
            "version": version,
            "analysis": None,
            "last_good_analysis": self.last_good_analysis(previous),
            "is_open": is_open,
        }
        self.invalidate_workspace_index()

    def update_document(
        self,
        uri: str,
        text: str,
        version: Optional[int] = None,
        is_open: bool = True,
    ):
        """Replace a document snapshot and invalidate dependent caches.

        Args:
            uri: Document URI.
            text: Full replacement document text.
            version: Optional LSP document version.
            is_open: Whether the document is open in the editor.
        """
        previous = self.documents.get(uri)
        self.documents[uri] = {
            "text": text,
            "version": version,
            "analysis": None,
            "last_good_analysis": self.last_good_analysis(previous),
            "is_open": is_open,
        }
        self.invalidate_workspace_index()

    def close_document(self, uri: str):
        """Remove a document from the session."""
        self.documents.pop(uri, None)
        self.invalidate_workspace_index()

    def ensure_document(self, uri: str):
        """Load a file-backed document when it is not already tracked."""
        if uri not in self.documents and uri.startswith("file:"):
            path = Path(unquote(urlparse(uri).path))
            try:
                self.open_path(str(path))
            except OSError:
                return False
        return uri in self.documents

    def is_ord_uri(self, uri: str):
        """Return whether a URI points to an ORD source file."""
        parsed_uri = urlparse(uri)
        if parsed_uri.scheme != "file":
            return False

        return Path(unquote(parsed_uri.path)).suffix == ".ord"

    def invalidate_path(self, path: str):
        """Invalidate cached state for a filesystem path."""
        path = Path(path).resolve()
        if path.suffix == ".py":
            self.invalidate_python_module_path(path)
            return None

        if path.suffix != ".ord":
            return None

        uri = path.as_uri()
        doc = self.documents.get(uri)
        if doc is not None and doc.get("is_open"):
            doc["analysis"] = None
            self.invalidate_workspace_index()
            return uri

        if path.exists():
            return self.update_path(str(path))

        self.documents.pop(uri, None)
        self.invalidate_workspace_index()
        return uri

    def invalidate_uri(self, uri: str):
        """Invalidate cached state for a file URI."""
        parsed_uri = urlparse(uri)
        if parsed_uri.scheme != "file":
            return None

        return self.invalidate_path(unquote(parsed_uri.path))

    def resolve_module_uri(self, uri: str, module_name: str):
        """Resolve an ORD import name relative to a document URI."""
        if not uri.startswith("file:"):
            return None

        parsed_uri = urlparse(uri)
        if parsed_uri.scheme != "file":
            return None

        doc_path = Path(unquote(parsed_uri.path)).resolve()
        workspace_root = Path(self.workspace_root).resolve() if self.workspace_root else doc_path.parent

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
        else:
            import_path = workspace_root.joinpath(*module_name.split("."))

        module_file_path = import_path.with_suffix(".ord")
        if module_file_path.exists():
            return module_file_path.resolve().as_uri()

        package_init_path = import_path / "__init__.ord"
        if package_init_path.exists():
            return package_init_path.resolve().as_uri()

        return None

    def resolve_python_module_path(self, module_name: str):
        """Resolve a Python module name to a source file path."""
        return self.python_index.resolve_module_path(module_name)

    def resolve_python_import_name(self, uri: str, module_name: str):
        """Resolve a possibly relative Python import name for a document."""
        return self.python_index.resolve_import_name(uri, module_name)

    def python_module_exists(self, module_name: str):
        """Return whether a Python module can be imported or found locally."""
        return self.python_index.module_exists(module_name)

    def python_module_names_for_path(self, path: Path):
        """Return cached or workspace module names that may map to a path."""
        return self.python_index.module_names_for_path(path)

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

    def python_base_class_refs(self, module_name: str, module_info, base_name: str):
        """Resolve a base class name from a parsed Python module."""
        return self.python_index.base_class_refs(module_name, module_info, base_name)

    def python_class_member_definition(
        self,
        module_name: str,
        class_name: str,
        member_name: str,
        seen=None,
    ):
        """Resolve a Python class member, including inherited members."""
        return self.python_index.class_member_definition(
            module_name,
            class_name,
            member_name,
            seen=seen,
        )

    def python_class_members(self, module_name: str, class_name: str, seen=None):
        """Collect Python class members, including inherited members."""
        return self.python_index.class_members(module_name, class_name, seen=seen)

    def analyze(self, uri: str):
        """Return cached document analysis, parsing the document when needed."""
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
        if not self.ensure_document(uri):
            return []

        analysis = self.analyze(uri)
        if analysis.has_errors():
            return analysis.diagnostics

        return analysis.diagnostics + self.semantic_diagnostics(uri)

    def open_path(self, path: str, version: Optional[int] = None):
        """Open a filesystem ORD file as a closed session document."""
        path = Path(path).resolve()
        uri = path.as_uri()
        if uri in self.documents and self.documents[uri].get("is_open"):
            return uri

        with open(path) as source_file:
            text = source_file.read()
        self.open_document(uri, text, version=version, is_open=False)
        return uri

    def update_path(self, path: str, version: Optional[int] = None):
        """Refresh a filesystem ORD file in the session."""
        path = Path(path).resolve()
        uri = path.as_uri()
        if uri in self.documents and self.documents[uri].get("is_open"):
            self.documents[uri]["analysis"] = None
            self.invalidate_workspace_index()
            return uri

        with open(path) as source_file:
            text = source_file.read()
        self.update_document(uri, text, version=version, is_open=False)
        return uri

    def analyze_path(self, path: str, version: Optional[int] = None):
        """Refresh and analyze a filesystem ORD file."""
        uri = self.update_path(path, version=version)
        return self.analyze(uri)

    def workspace_uris(self):
        """Return ORD file URIs known to the current workspace."""
        if self.workspace_root:
            root_path = Path(self.workspace_root).resolve()
            if root_path.exists():
                uris = []
                for path in sorted(root_path.rglob("*.ord")):
                    if not path.is_file():
                        continue

                    uri = path.resolve().as_uri()
                    if uri not in self.documents:
                        try:
                            self.open_path(str(path))
                        except OSError:
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
        return self.workspace_index

    def workspace_dependents(self, uri: str):
        """Return workspace URIs that directly or indirectly import a URI."""
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
        if not self.ensure_document(uri) or not uri.startswith("file:"):
            return []

        parsed_uri = urlparse(uri)
        if parsed_uri.scheme != "file":
            return []

        imports = []
        seen = set()

        for import_entry in self.analyze(uri).import_entries:
            module_name = import_entry.module
            if import_entry.kind == "from" and module_name and set(module_name) == {"."}:
                module_name = module_name + import_entry.export_name

            import_uri = self.resolve_module_uri(uri, module_name)
            if import_uri is not None and import_uri not in seen:
                seen.add(import_uri)
                imports.append(import_uri)

        return imports

    def analyze_related(self, uri: str):
        """Analyze a document and its reachable ORD imports."""
        analyses = dict()
        pending = [uri]

        while pending:
            current_uri = pending.pop()
            if current_uri in analyses:
                continue

            if current_uri not in self.documents and current_uri.startswith("file:"):
                current_path = Path(unquote(urlparse(current_uri).path))
                self.open_path(str(current_path))

            if current_uri not in self.documents:
                continue

            analyses[current_uri] = self.analyze(current_uri)

            for import_uri in self.resolve_import_uris(current_uri):
                if import_uri not in analyses:
                    pending.append(import_uri)

        return analyses

    def local_definition(self, uri: str, position: AnalysisPosition):
        """Resolve a local binding or occurrence at a document position."""
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
                "binding_id": binding["id"],
                "scope_id": binding["scope_id"],
                "exported": binding["exported"],
            }

        return None

    def visible_bindings(self, uri: str, position: AnalysisPosition):
        """Return bindings visible from a document position."""
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
        if not self.ensure_document(uri):
            return []

        analysis = self.analyze(uri)
        candidates = []

        for import_entry in analysis.import_entries:
            candidates.append({
                "name": import_entry.local_name,
                "range": import_entry.selection_range,
            })

        for occurrence in analysis.occurrences:
            candidates.append({
                "name": occurrence["name"],
                "range": occurrence["range"],
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
        if not self.ensure_document(uri):
            return None

        for import_entry in self.analyze(uri).import_entries:
            start = import_entry.selection_range.start
            end = import_entry.selection_range.end

            if start.line != position.line or end.line != position.line:
                continue

            if start.character <= position.character < end.character:
                return import_entry

        return None

    def name_at_position(self, uri: str, position: AnalysisPosition):
        """Return the identifier token at or immediately before a position."""
        if not self.ensure_document(uri):
            return None

        lines = self.documents[uri]["text"].splitlines()
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
        if not self.ensure_document(uri):
            return None

        analysis = self.analyze(uri)

        if name in analysis.exports:
            return self.find_export(uri, name)

        for import_entry in analysis.import_entries:
            if import_entry.local_name != name:
                continue

            if import_entry.kind == "from":
                import_uri = None
                if import_entry.module and set(import_entry.module) == {"."}:
                    import_uri = self.resolve_module_uri(uri, import_entry.module + import_entry.export_name)
                else:
                    import_uri = self.resolve_module_uri(uri, import_entry.module)

                if import_uri is None:
                    python_module_name = self.resolve_python_import_name(uri, import_entry.module)
                    match = self.python_definition(
                        python_module_name,
                        export_name=import_entry.export_name,
                    )
                else:
                    match = self.find_export(import_uri, import_entry.export_name)
                if match is not None:
                    return match

            else:
                match = self.module_definition(uri, import_entry.module)
                if match is not None:
                    return match

        for import_entry in analysis.import_entries:
            if import_entry.kind != "from" or import_entry.export_name != "*":
                continue

            module_name = import_entry.module
            if module_name and set(module_name) == {"."}:
                continue

            python_module_name = self.resolve_python_import_name(uri, module_name)
            match = self.python_definition(python_module_name, export_name=name)
            if match is not None:
                return match

        return None

    def hover(self, uri: str, position: AnalysisPosition):
        """Return hover contents for the definition at a position."""
        definition = self.definition(uri, position)
        if definition is None:
            return None

        name_info = self.name_at_position(uri, position)
        hover_range = definition["selection_range"]
        if name_info is not None:
            hover_range = name_info["range"]

        contents = "{} {}".format(definition["kind"], definition["name"])
        if definition["uri"] != uri:
            contents += "\n{}".format(definition["uri"])

        return {
            "contents": contents,
            "range": hover_range,
        }

    def ord_cell_member_definition(self, cell_uri: str, cell_name: str, member_name: str):
        """Resolve a member declared by an ORD cell."""
        if not self.ensure_document(cell_uri):
            return None

        analysis = self.analyze(cell_uri)

        # Find the cell symbol to identify its scope.
        cell_symbol = None
        for symbol in analysis.symbols:
            if symbol.name == cell_name and symbol.kind == "class":
                cell_symbol = symbol
                break

        if cell_symbol is None:
            return None

        # Find the cell's body scope — the scope whose range matches the cell
        # and whose parent is the file-level scope.
        cell_scope = None
        for scope in analysis.scopes.values():
            if scope["depth"] != 1:
                continue
            if not range_contains(scope["range"], cell_symbol.selection_range.start):
                continue
            cell_scope = scope
            break

        if cell_scope is None:
            return None

        # Look for a binding in the cell's body scope that matches the member name.
        for binding_id in cell_scope["bindings"]:
            binding = analysis.binding_map.get(binding_id)
            if binding is None:
                continue
            if binding["name"] != member_name:
                continue

            return {
                "uri": cell_uri,
                "name": binding["name"],
                "kind": binding["kind"],
                "range": binding["range"],
                "selection_range": binding["selection_range"],
            }

        return None

    def ord_cell_members(self, cell_uri: str, cell_name: str):
        """Collect members exposed by an ORD cell."""
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
            members.setdefault(binding["name"], {
                "uri": cell_uri,
                "name": binding["name"],
                "kind": binding["kind"],
                "range": binding["range"],
                "selection_range": binding["selection_range"],
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
        # symbol view. Layout instances additionally expose named layout nodes.
        for symbol in analysis.symbols:
            if symbol.name not in ("symbol", "layout") or symbol.kind != "function":
                continue
            if not range_contains(cell_symbol.range, symbol.selection_range.start):
                continue

            for binding in analysis.bindings:
                if binding["kind"] != "variable":
                    continue
                if not range_contains(symbol.range, binding["selection_range"].start):
                    continue
                add_binding_member(binding)

        return members

    def member_definition(self, uri: str, position: AnalysisPosition):
        """Resolve a member or parameter access at a document position."""
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
                    return match

        return None

    def member_occurrence_at_position(self, uri: str, position: AnalysisPosition):
        """Return a member occurrence that contains a document position."""
        if not self.ensure_document(uri):
            return None

        for occurrence in self.analyze(uri).member_occurrences:
            if range_contains(occurrence["range"], position):
                return occurrence

        return None

    def folding_ranges(self, uri: str):
        """Return foldable symbol and import ranges for a document."""
        if not self.ensure_document(uri):
            return []

        analysis = self.analyze(uri)
        ranges = []

        # Fold each multi-line symbol (cell, viewgen, function, class, context, path, net).
        for symbol in analysis.symbols:
            start_line = symbol.range.start.line
            end_line = symbol.range.end.line
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

        return result

    def references(self, uri: str, position: AnalysisPosition):
        """Return references to the definition at a document position."""
        definition = self.definition(uri, position)
        if definition is None:
            return []

        references = []
        seen = set()
        target = self.definition_key(definition)

        for ref_uri in self.reference_search_uris(uri, definition):
            for candidate in self.reference_candidates(ref_uri):
                resolved = self.definition(ref_uri, candidate["range"].start)
                if resolved is None:
                    continue

                if self.definition_key(resolved) != target:
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
        if definition.get("binding_id") is not None and not definition.get("exported"):
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
        for reference in self.references(uri, position):
            if reference["uri"] != uri:
                continue

            highlight = {
                "range": reference["range"],
                "kind": "read",
            }
            if definition_range is not None and reference["range"] == definition_range:
                highlight["kind"] = "write"

            highlights.append(highlight)

        return highlights

    def definition(self, uri: str, position: AnalysisPosition):
        """Resolve the best definition for a document position."""
        if not self.ensure_document(uri):
            return None

        local_definition = self.local_definition(uri, position)
        if local_definition is not None:
            return local_definition

        member_definition = self.member_definition(uri, position)
        if member_definition is not None:
            return member_definition

        analysis = self.analyze(uri)
        for symbol in analysis.symbols:
            if range_contains(symbol.selection_range, position):
                return {
                    "uri": uri,
                    "name": symbol.name,
                    "kind": symbol.kind,
                    "range": symbol.range,
                    "selection_range": symbol.selection_range,
                }

        import_entry = self.import_entry_at_position(uri, position)
        if import_entry is not None:
            if import_entry.kind == "from":
                import_uri = None
                if import_entry.module and set(import_entry.module) == {"."}:
                    import_uri = self.resolve_module_uri(uri, import_entry.module + import_entry.export_name)
                else:
                    import_uri = self.resolve_module_uri(uri, import_entry.module)

                if import_uri is not None:
                    match = self.find_export(import_uri, import_entry.export_name)
                    if match is not None:
                        return match

            else:
                match = self.module_definition(uri, import_entry.module)
                if match is not None:
                    return match

        name_info = self.name_at_position(uri, position)
        if name_info is None:
            return None

        definition = self.resolve_name(uri, name_info["name"])
        if definition is not None:
            return definition

        return self.resolve_completion_type(uri, name_info["name"])
