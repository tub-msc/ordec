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
from .model import AnalysisPosition
from .model import AnalysisRange


class PythonModuleIndex:
    """Shallow Python source index used by ORD analysis.

    The index parses workspace Python modules without executing them and
    extracts the exported classes, functions, variables, and class members
    needed by LSP definition, diagnostics, and completion features. Resolving
    installed modules uses ``importlib`` and may execute parent package
    initialization code; failures are treated as unresolved modules.
    """

    def __init__(self, workspace_root: Optional[str] = None):
        """Initialize the Python source index."""
        self.workspace_root = workspace_root
        self.python_modules = dict()

    def clear(self):
        """Clear cached Python module analysis and importlib state."""
        importlib.invalidate_caches()
        self.python_modules.clear()

    def find_spec(self, module_name: str):
        """Return an importlib spec without letting package failures escape."""
        try:
            return importlib.util.find_spec(module_name)
        except KeyboardInterrupt:
            raise
        except BaseException:
            return None

    def resolve_module_path(self, module_name: str):
        """Resolve a Python module name to a source file path."""
        if self.workspace_root:
            workspace_root = Path(self.workspace_root).resolve()
            workspace_path = workspace_root.joinpath(*module_name.split("."))
            for candidate in (
                workspace_path.with_suffix(".py"),
                workspace_path / "__init__.py",
            ):
                if candidate.exists():
                    return candidate.resolve()

        spec = self.find_spec(module_name)

        if spec is None or spec.origin in (None, "built-in", "frozen"):
            return None

        path = Path(spec.origin)
        if not path.exists():
            return None

        return path.resolve()

    def resolve_import_name(self, uri: str, module_name: str):
        """Resolve a possibly relative Python import name for a document."""
        if not module_name:
            return module_name

        if not module_name.startswith("."):
            parsed_uri = urlparse(uri)
            if parsed_uri.scheme == "file" and self.workspace_root:
                doc_path = Path(unquote(parsed_uri.path)).resolve()
                workspace_root = Path(self.workspace_root).resolve()
                import_path = doc_path.parent.joinpath(*module_name.split("."))
                for candidate in (
                    import_path.with_suffix(".py"),
                    import_path / "__init__.py",
                ):
                    if not candidate.exists():
                        continue

                    try:
                        relative_path = candidate.resolve().relative_to(workspace_root)
                    except ValueError:
                        continue

                    if relative_path.name == "__init__.py":
                        module_parts = relative_path.parent.parts
                    else:
                        module_parts = relative_path.with_suffix("").parts

                    if module_parts:
                        return ".".join(module_parts)

            return module_name

        parsed_uri = urlparse(uri)
        if parsed_uri.scheme != "file" or not self.workspace_root:
            return None

        doc_path = Path(unquote(parsed_uri.path)).resolve()
        workspace_root = Path(self.workspace_root).resolve()
        try:
            relative_path = doc_path.relative_to(workspace_root)
        except ValueError:
            return None

        package_name = ".".join(relative_path.parent.parts)
        if not package_name:
            return None

        try:
            return importlib.util.resolve_name(module_name, package_name)
        except (ImportError, ValueError):
            return None

    def module_exists(self, module_name: str):
        """Return whether a Python module can be imported or found locally."""
        if not module_name:
            return False

        if self.resolve_module_path(module_name) is not None:
            return True

        return self.find_spec(module_name) is not None

    def module_names_for_path(self, path: Path):
        """Return cached or workspace module names that may map to a path."""
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

    def invalidate_module_path(self, path: Path):
        """Invalidate cached Python analysis for modules backed by a path."""
        importlib.invalidate_caches()
        for module_name in self.module_names_for_path(path):
            self.python_modules.pop(module_name, None)

    def module_info(self, module_name: str):
        """Analyze a Python module enough for ORD import and member lookup."""
        if module_name in self.python_modules:
            return self.python_modules[module_name]

        module_path = self.resolve_module_path(module_name)
        if module_path is None:
            self.python_modules[module_name] = None
            return None

        try:
            source_data = module_path.read_text(encoding="utf-8")
            syntax_tree = ast.parse(source_data, filename=str(module_path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            self.python_modules[module_name] = None
            return None

        source_lines = source_data.splitlines()
        exports = dict()
        reexports = []
        star_modules = []
        imports = dict()
        import_members = dict()
        classes = dict()

        def ast_position(lineno, col_offset):
            line = source_lines[lineno - 1] if lineno - 1 < len(source_lines) else ""
            consumed = 0
            character = 0
            for char in line:
                width = len(char.encode("utf-8"))
                if consumed + width > col_offset:
                    break
                consumed += width
                character += 1
            return AnalysisPosition(lineno, character + 1)

        def node_range(node):
            end_lineno = getattr(node, "end_lineno", node.lineno)
            end_col_offset = getattr(node, "end_col_offset", node.col_offset)
            return AnalysisRange(
                start=ast_position(node.lineno, node.col_offset),
                end=ast_position(end_lineno, end_col_offset),
            )

        def name_range(node, name):
            line = source_lines[node.lineno - 1] if node.lineno - 1 < len(source_lines) else ""
            start_hint = ast_position(node.lineno, node.col_offset).character - 1
            start = line.find(name, start_hint)
            if start < 0:
                start = start_hint
            return AnalysisRange(
                start=AnalysisPosition(node.lineno, start + 1),
                end=AnalysisPosition(node.lineno, start + 1 + len(name)),
            )

        def add_export(name, kind, node):
            if name.startswith("_") or name in exports:
                return

            exports[name] = {
                "uri": module_path.as_uri(),
                "name": name,
                "kind": kind,
                "range": node_range(node),
                "selection_range": name_range(node, name),
            }
            if kind == "class":
                exports[name]["python_module"] = module_name
                exports[name]["python_class"] = name

        def add_public_call_exports(node):
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                return

            if node_name(node.value.func) != "public":
                return

            for keyword in node.value.keywords:
                if keyword.arg is None:
                    continue

                value_name = node_name(keyword.value)
                value_export = exports.get(value_name)
                if value_export is not None and value_export.get("kind") == "class":
                    exports[keyword.arg] = value_export
                    continue

                add_export(keyword.arg, "variable", keyword)

        def node_name(node):
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                value_name = node_name(node.value)
                if value_name is None:
                    return None
                return "{}.{}".format(value_name, node.attr)
            return None

        def add_class_member(class_info, name, kind, node):
            if name.startswith("_"):
                return

            class_info["members"].setdefault(name, {
                "uri": module_path.as_uri(),
                "name": name,
                "kind": kind,
                "range": node_range(node),
                "selection_range": node_range(node),
            })

        def resolve_imported_module(node):
            import_name = "." * node.level
            if node.module:
                import_name += node.module

            package_name = module_name
            if node.level:
                if module_path.name == "__init__.py":
                    package_name = module_name
                else:
                    package_name = module_name.rsplit(".", 1)[0]

            try:
                return importlib.util.resolve_name(import_name, package_name)
            except (ImportError, ValueError):
                return None

        for node in syntax_tree.body:
            add_public_call_exports(node)

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
                            add_class_member(class_info, target.id, member_kind, target)
                        continue

                    if (
                        isinstance(class_node, ast.AnnAssign)
                        and isinstance(class_node.target, ast.Name)
                    ):
                        target = class_node.target
                        add_class_member(class_info, target.id, "variable", target)
                        continue

                    if not isinstance(class_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue

                    if not class_node.name.startswith("_"):
                        class_info["members"].setdefault(class_node.name, {
                            "uri": module_path.as_uri(),
                            "name": class_node.name,
                            "kind": "function",
                            "range": node_range(class_node),
                            "selection_range": name_range(class_node, class_node.name),
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
                                    start=ast_position(
                                        target.end_lineno,
                                        target.end_col_offset - len(target.attr),
                                    ),
                                    end=ast_position(target.end_lineno, target.end_col_offset),
                                ),
                            })

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
                            if target.value.id != "self":
                                continue

                            add_class_member(class_info, target.attr, "variable", target)

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

    def definition(self, module_name: str, export_name: Optional[str] = None, seen=None):
        """Resolve a Python module or exported member definition."""
        if not module_name:
            return None

        if seen is None:
            seen = set()

        if module_name in seen:
            return None
        seen.add(module_name)

        module_info = self.module_info(module_name)
        if module_info is None:
            return None

        if export_name is None:
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

            match = self.definition(
                reexport["module"],
                export_name=reexport["export_name"],
                seen=seen,
            )
            if match is not None:
                return match

        submodule_name = "{}.{}".format(module_name, export_name)
        match = self.definition(submodule_name, seen=seen)
        if match is not None:
            return match

        for star_module in module_info["star_modules"]:
            match = self.definition(
                star_module,
                export_name=export_name,
                seen=seen,
            )
            if match is not None:
                return match

        return None

    def base_class_refs(self, module_name: str, module_info, base_name: str):
        """Resolve a base class name from a parsed Python module."""
        if base_name in module_info["classes"]:
            return [(module_name, base_name)]

        if base_name in module_info["import_members"]:
            imported = module_info["import_members"][base_name]
            return [(imported["module"], imported["export_name"])]

        refs = []
        for star_module in module_info["star_modules"]:
            match = self.definition(star_module, export_name=base_name)
            if match is None:
                continue
            if "python_module" in match and "python_class" in match:
                refs.append((match["python_module"], match["python_class"]))

        if refs:
            return refs

        if "." not in base_name:
            return []

        local_name, member_name = base_name.split(".", 1)

        imported_module = module_info["imports"].get(local_name)
        if imported_module is not None:
            refs.append((imported_module, member_name))

        imported_member = module_info["import_members"].get(local_name)
        if imported_member is not None:
            module_candidate = "{}.{}".format(
                imported_member["module"],
                imported_member["export_name"],
            )
            if self.module_exists(module_candidate):
                refs.append((module_candidate, member_name))

        return refs

    def class_member_definition(
        self,
        module_name: str,
        class_name: str,
        member_name: str,
        seen=None,
    ):
        """Resolve a Python class member, including inherited members."""
        if seen is None:
            seen = set()

        key = (module_name, class_name, member_name)
        if key in seen:
            return None
        seen.add(key)

        module_info = self.module_info(module_name)
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
                match = self.class_member_definition(
                    module_name,
                    base_name,
                    member_name,
                    seen=seen,
                )
                if match is not None:
                    return match
                continue

            for base_module_name, base_class_name in self.base_class_refs(
                module_name,
                module_info,
                base_name,
            ):
                match = self.class_member_definition(
                    base_module_name,
                    base_class_name,
                    member_name,
                    seen=seen,
                )
                if match is not None:
                    return match

        return None

    def class_members(self, module_name: str, class_name: str, seen=None):
        """Collect Python class members, including inherited members."""
        if seen is None:
            seen = set()

        key = (module_name, class_name)
        if key in seen:
            return dict()
        seen.add(key)

        module_info = self.module_info(module_name)
        if module_info is None:
            return dict()

        class_info = module_info["classes"].get(class_name)
        if class_info is None:
            return dict()

        members = dict()
        for base_name in class_info["bases"]:
            if base_name in module_info["classes"]:
                members.update(self.class_members(
                    module_name,
                    base_name,
                    seen=seen,
                ))
                continue

            for base_module_name, base_class_name in self.base_class_refs(
                module_name,
                module_info,
                base_name,
            ):
                members.update(self.class_members(
                    base_module_name,
                    base_class_name,
                    seen=seen,
                ))

        members.update(class_info["members"])
        return members
