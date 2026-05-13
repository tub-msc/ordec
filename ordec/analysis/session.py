# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import ast
import importlib
import importlib.util
from pathlib import Path
from typing import Optional
from urllib.parse import unquote
from urllib.parse import urlparse

# ordec imports
from .completions import CompletionsMixin
from .diagnostics import DiagnosticsMixin
from .model import AnalysisPosition
from .model import AnalysisRange
from .model import position_before_or_equal
from .model import range_contains
from .parser_pass import analyze_ord
from .rename import RenameMixin
from .typeflow import TypeFlowMixin


class AnalysisSession(
    TypeFlowMixin,
    CompletionsMixin,
    DiagnosticsMixin,
    RenameMixin,
):
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = workspace_root
        self.documents = dict()
        self.python_modules = dict()
        self.workspace_index = None

    def last_good_analysis(self, doc):
        if doc is None:
            return None

        analysis = doc.get("analysis")
        if analysis is not None and not analysis.has_errors():
            return analysis

        return doc.get("last_good_analysis")

    def invalidate_workspace_index(self):
        self.workspace_index = None

    def clear_python_modules(self):
        importlib.invalidate_caches()
        self.python_modules.clear()

    def normalize_type_names(self, type_names):
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
        self.documents.pop(uri, None)
        self.invalidate_workspace_index()

    def ensure_document(self, uri: str):
        if uri not in self.documents and uri.startswith("file:"):
            path = Path(unquote(urlparse(uri).path))
            try:
                self.open_path(str(path))
            except OSError:
                return False
        return uri in self.documents

    def is_ord_uri(self, uri: str):
        parsed_uri = urlparse(uri)
        if parsed_uri.scheme != "file":
            return False

        return Path(unquote(parsed_uri.path)).suffix == ".ord"

    def invalidate_path(self, path: str):
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
        parsed_uri = urlparse(uri)
        if parsed_uri.scheme != "file":
            return None

        return self.invalidate_path(unquote(parsed_uri.path))

    def resolve_module_uri(self, uri: str, module_name: str):
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
        if self.workspace_root:
            workspace_root = Path(self.workspace_root).resolve()
            workspace_path = workspace_root.joinpath(*module_name.split("."))
            for candidate in (
                workspace_path.with_suffix(".py"),
                workspace_path / "__init__.py",
            ):
                if candidate.exists():
                    return candidate.resolve()

        try:
            spec = importlib.util.find_spec(module_name)
        except (ImportError, ModuleNotFoundError, ValueError):
            return None

        if spec is None or spec.origin in (None, "built-in", "frozen"):
            return None

        path = Path(spec.origin)
        if not path.exists():
            return None

        return path.resolve()

    def python_module_names_for_path(self, path: Path):
        names = []

        for module_name, module_info in self.python_modules.items():
            if module_info is None:
                continue
            if module_info.get("path") == path:
                names.append(module_name)

        if self.workspace_root:
            try:
                relative_path = path.relative_to(Path(self.workspace_root).resolve())
            except ValueError:
                relative_path = None

            if relative_path is not None:
                if relative_path.name == "__init__.py":
                    module_parts = relative_path.parent.parts
                else:
                    module_parts = relative_path.with_suffix("").parts

                if module_parts:
                    names.append(".".join(module_parts))

        return sorted(set(names))

    def invalidate_python_module_path(self, path: Path):
        importlib.invalidate_caches()
        for module_name in self.python_module_names_for_path(path):
            self.python_modules.pop(module_name, None)

    def python_module_info(self, module_name: str):
        if module_name in self.python_modules:
            return self.python_modules[module_name]

        module_path = self.resolve_python_module_path(module_name)
        if module_path is None:
            self.python_modules[module_name] = None
            return None

        try:
            source_data = module_path.read_text()
            syntax_tree = ast.parse(source_data, filename=str(module_path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            self.python_modules[module_name] = None
            return None

        exports = dict()
        reexports = []
        star_modules = []
        imports = dict()
        import_members = dict()
        classes = dict()

        def node_range(node):
            end_lineno = getattr(node, "end_lineno", node.lineno)
            end_col_offset = getattr(node, "end_col_offset", node.col_offset)
            return AnalysisRange(
                start=AnalysisPosition(node.lineno, node.col_offset + 1),
                end=AnalysisPosition(end_lineno, end_col_offset + 1),
            )

        def add_export(name, kind, node):
            if name.startswith("_") or name in exports:
                return

            exports[name] = {
                "uri": module_path.as_uri(),
                "name": name,
                "kind": kind,
                "range": node_range(node),
                "selection_range": AnalysisRange(
                    start=AnalysisPosition(node.lineno, node.col_offset + 1),
                    end=AnalysisPosition(node.lineno, node.col_offset + 1 + len(name)),
                ),
            }
            if kind == "class":
                exports[name]["python_module"] = module_name
                exports[name]["python_class"] = name

        def node_name(node):
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                value_name = node_name(node.value)
                if value_name is None:
                    return None
                return "{}.{}".format(value_name, node.attr)
            return None

        def resolve_imported_module(node):
            import_name = "." * node.level
            if node.module:
                import_name += node.module

            try:
                return importlib.util.resolve_name(import_name, module_name)
            except (ImportError, ValueError):
                return None

        for node in syntax_tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local_name = alias.asname or alias.name.split(".", 1)[0]
                    imports[local_name] = alias.name
                continue

            if isinstance(node, ast.ImportFrom):
                resolved_module = resolve_imported_module(node)
                if resolved_module is None:
                    continue

                for alias in node.names:
                    if alias.name == "*":
                        star_modules.append(resolved_module)
                        continue

                    import_members[alias.asname or alias.name] = {
                        "module": resolved_module,
                        "export_name": alias.name,
                    }
                # Keep parsing the same node for top-level reexports below.

            if isinstance(node, ast.ClassDef):
                class_info = {
                    "bases": [],
                    "members": dict(),
                }
                for base_node in node.bases:
                    base_name = node_name(base_node)
                    if base_name is not None:
                        class_info["bases"].append(base_name)

                for class_node in node.body:
                    if isinstance(class_node, ast.Assign):
                        member_kind = "variable"
                        if isinstance(class_node.value, ast.Call):
                            func_name = node_name(class_node.value.func)
                            if func_name == "Parameter":
                                member_kind = "parameter"

                        for target in class_node.targets:
                            if not isinstance(target, ast.Name):
                                continue
                            if target.id.startswith("_"):
                                continue

                            class_info["members"].setdefault(target.id, {
                                "uri": module_path.as_uri(),
                                "name": target.id,
                                "kind": member_kind,
                                "range": node_range(target),
                                "selection_range": node_range(target),
                            })
                        continue

                    if isinstance(class_node, ast.AnnAssign) and isinstance(class_node.target, ast.Name):
                        target = class_node.target
                        if not target.id.startswith("_"):
                            class_info["members"].setdefault(target.id, {
                                "uri": module_path.as_uri(),
                                "name": target.id,
                                "kind": "variable",
                                "range": node_range(target),
                                "selection_range": node_range(target),
                            })
                        continue

                    if not isinstance(class_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue

                    if not class_node.name.startswith("_"):
                        class_info["members"].setdefault(class_node.name, {
                            "uri": module_path.as_uri(),
                            "name": class_node.name,
                            "kind": "function",
                            "range": node_range(class_node),
                            "selection_range": AnalysisRange(
                                start=AnalysisPosition(class_node.lineno, class_node.col_offset + 1),
                                end=AnalysisPosition(class_node.lineno, class_node.col_offset + 1 + len(class_node.name)),
                            ),
                        })

                    container_names = set()
                    for stmt in ast.walk(class_node):
                        if not isinstance(stmt, ast.Assign):
                            continue
                        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                            continue
                        if not isinstance(stmt.value, ast.Call):
                            continue

                        func_name = node_name(stmt.value.func)
                        if func_name not in ("Symbol", "Schematic"):
                            continue

                        container_names.add(stmt.targets[0].id)

                    for stmt in ast.walk(class_node):
                        targets = []
                        if isinstance(stmt, ast.Assign):
                            targets = stmt.targets
                        elif isinstance(stmt, ast.AnnAssign):
                            targets = [stmt.target]

                        for target in targets:
                            if not isinstance(target, ast.Attribute):
                                continue
                            if not isinstance(target.value, ast.Name):
                                continue
                            if target.value.id not in container_names:
                                continue
                            if target.attr.startswith("_"):
                                continue

                            member_kind = "variable"
                            value = getattr(stmt, "value", None)
                            if isinstance(value, ast.Call) and node_name(value.func) == "Pin":
                                member_kind = "variable"

                            class_info["members"].setdefault(target.attr, {
                                "uri": module_path.as_uri(),
                                "name": target.attr,
                                "kind": member_kind,
                                "range": node_range(target),
                                "selection_range": AnalysisRange(
                                    start=AnalysisPosition(target.end_lineno, target.end_col_offset - len(target.attr) + 1),
                                    end=AnalysisPosition(target.end_lineno, target.end_col_offset + 1),
                                ),
                            })

                classes[node.name] = class_info
                add_export(node.name, "class", node)
                continue

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                add_export(node.name, "function", node)
                continue

            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        add_export(target.id, "variable", target)
                continue

            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                add_export(node.target.id, "variable", node.target)
                continue

            if not isinstance(node, ast.ImportFrom):
                continue

            resolved_module = resolve_imported_module(node)
            if resolved_module is None:
                continue

            for alias in node.names:
                if alias.name == "*":
                    continue

                reexports.append({
                    "local_name": alias.asname or alias.name,
                    "module": resolved_module,
                    "export_name": alias.name,
                })

        module_info = {
            "uri": module_path.as_uri(),
            "path": module_path,
            "exports": exports,
            "reexports": reexports,
            "star_modules": star_modules,
            "imports": imports,
            "import_members": import_members,
            "classes": classes,
        }
        self.python_modules[module_name] = module_info
        return module_info

    def python_definition(self, module_name: str, export_name: Optional[str] = None, seen=None):
        if seen is None:
            seen = set()

        if module_name in seen:
            return None
        seen.add(module_name)

        module_info = self.python_module_info(module_name)
        if module_info is None:
            return None

        if export_name is None:
            module_path = module_info["path"]
            return {
                "uri": module_info["uri"],
                "name": module_name.split(".")[-1],
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

        match = module_info["exports"].get(export_name)
        if match is not None:
            return match

        for reexport in module_info["reexports"]:
            if reexport["local_name"] != export_name:
                continue

            match = self.python_definition(
                reexport["module"],
                export_name=reexport["export_name"],
                seen=seen,
            )
            if match is not None:
                return match

        for star_module in module_info["star_modules"]:
            match = self.python_definition(
                star_module,
                export_name=export_name,
                seen=seen,
            )
            if match is not None:
                return match

        return None

    def python_class_member_definition(self, module_name: str, class_name: str, member_name: str, seen=None):
        if seen is None:
            seen = set()

        key = (module_name, class_name, member_name)
        if key in seen:
            return None
        seen.add(key)

        module_info = self.python_module_info(module_name)
        if module_info is None:
            return None

        class_info = module_info["classes"].get(class_name)
        if class_info is None:
            return None

        match = class_info["members"].get(member_name)
        if match is not None:
            return match

        for base_name in class_info["bases"]:
            if base_name in module_info["classes"]:
                match = self.python_class_member_definition(
                    module_name,
                    base_name,
                    member_name,
                    seen=seen,
                )
                if match is not None:
                    return match
                continue

            if base_name in module_info["import_members"]:
                imported = module_info["import_members"][base_name]
                match = self.python_class_member_definition(
                    imported["module"],
                    imported["export_name"],
                    member_name,
                    seen=seen,
                )
                if match is not None:
                    return match

        return None

    def python_class_members(self, module_name: str, class_name: str, seen=None):
        if seen is None:
            seen = set()

        key = (module_name, class_name)
        if key in seen:
            return dict()
        seen.add(key)

        module_info = self.python_module_info(module_name)
        if module_info is None:
            return dict()

        class_info = module_info["classes"].get(class_name)
        if class_info is None:
            return dict()

        members = dict()
        for base_name in class_info["bases"]:
            if base_name in module_info["classes"]:
                members.update(self.python_class_members(
                    module_name,
                    base_name,
                    seen=seen,
                ))
                continue

            if base_name in module_info["import_members"]:
                imported = module_info["import_members"][base_name]
                members.update(self.python_class_members(
                    imported["module"],
                    imported["export_name"],
                    seen=seen,
                ))

        members.update(class_info["members"])
        return members

    def analyze(self, uri: str):
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
        if not self.ensure_document(uri):
            return []

        analysis = self.analyze(uri)
        if analysis.has_errors():
            return analysis.diagnostics

        return analysis.diagnostics + self.semantic_diagnostics(uri)

    def open_path(self, path: str, version: Optional[int] = None):
        path = Path(path).resolve()
        uri = path.as_uri()
        if uri in self.documents and self.documents[uri].get("is_open"):
            return uri

        with open(path) as source_file:
            text = source_file.read()
        self.open_document(uri, text, version=version, is_open=False)
        return uri

    def update_path(self, path: str, version: Optional[int] = None):
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
        uri = self.update_path(path, version=version)
        return self.analyze(uri)

    def workspace_uris(self):
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
        module_uri = self.resolve_module_uri(uri, module_name)
        if module_uri is None:
            return self.python_definition(module_name)

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
                    match = self.python_definition(
                        import_entry.module,
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

            match = self.python_definition(module_name, export_name=name)
            if match is not None:
                return match

        return None

    def hover(self, uri: str, position: AnalysisPosition):
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

        # Include directly declared cell members. This covers compact tests and
        # unusual cells that declare pins directly in the cell body.
        for scope in analysis.scopes.values():
            if scope["depth"] != 1:
                continue
            if not range_contains(scope["range"], cell_symbol.selection_range.start):
                continue

            for binding_id in scope["bindings"]:
                binding = analysis.binding_map.get(binding_id)
                if binding is None or binding["kind"] != "variable":
                    continue
                members.setdefault(binding["name"], {
                    "uri": cell_uri,
                    "name": binding["name"],
                    "kind": binding["kind"],
                    "range": binding["range"],
                    "selection_range": binding["selection_range"],
                })

        # Normal ORD cells expose instance members through their symbol view.
        for symbol in analysis.symbols:
            if symbol.name != "symbol" or symbol.kind != "function":
                continue
            if not range_contains(cell_symbol.range, symbol.selection_range.start):
                continue

            for binding in analysis.bindings:
                if binding["kind"] != "variable":
                    continue
                if not range_contains(symbol.range, binding["selection_range"].start):
                    continue
                members.setdefault(binding["name"], {
                    "uri": cell_uri,
                    "name": binding["name"],
                    "kind": binding["kind"],
                    "range": binding["range"],
                    "selection_range": binding["selection_range"],
                })

        return members

    def member_definition(self, uri: str, position: AnalysisPosition):
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

                type_definition = self.resolve_name(uri, type_name)
                if type_definition is None:
                    continue

                # Try Python class member resolution first.
                if "python_module" in type_definition and "python_class" in type_definition:
                    match = self.python_class_member_definition(
                        type_definition["python_module"],
                        type_definition["python_class"],
                        occurrence["name"],
                    )
                    if match is not None:
                        return match

                # Try ORD cell member resolution for cross-file cells.
                if type_definition.get("kind") == "class" and "uri" in type_definition:
                    match = self.ord_cell_member_definition(
                        type_definition["uri"],
                        type_definition["name"],
                        occurrence["name"],
                    )
                    if match is not None:
                        return match

        return None

    def member_occurrence_at_position(self, uri: str, position: AnalysisPosition):
        if not self.ensure_document(uri):
            return None

        for occurrence in self.analyze(uri).member_occurrences:
            if range_contains(occurrence["range"], position):
                return occurrence

        return None












    def folding_ranges(self, uri: str):
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

        return self.resolve_name(uri, name_info["name"])
