# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import ast
import re
from pathlib import Path
from typing import Optional

from lark.exceptions import LarkError

# ordec imports
from ...ord.parser import ord_to_py
from .import_resolver import ImportResolver, from_import_module_name
from .model import AnalysisDefinition
from .model import AnalysisPosition
from .model import AnalysisRange
from .model import split_source_lines


def expression_text(node, limit: int = 32):
    """Return compact source text for an expression node, or None."""
    try:
        text = ast.unparse(node)
    except ValueError:
        return None

    if len(text) > limit:
        return text[:limit - 1] + "…"
    return text


def function_signature_params(function_node, skip_receiver: bool = False):
    """Return display strings for a function's parameters in source order."""
    args = function_node.args
    positional = list(args.posonlyargs) + list(args.args)
    defaults = dict()
    for arg, default in zip(positional[len(positional) - len(args.defaults):], args.defaults):
        defaults[arg.arg] = default

    if skip_receiver and positional and positional[0].arg in ("self", "cls"):
        positional = positional[1:]

    def param_label(arg, default):
        if default is None:
            return arg.arg
        default_text = expression_text(default)
        if default_text is None:
            return arg.arg
        return "{}={}".format(arg.arg, default_text)

    params = []
    for arg in positional:
        params.append(param_label(arg, defaults.get(arg.arg)))

    if args.vararg is not None:
        params.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        params.append("*")

    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        params.append(param_label(arg, default))

    if args.kwarg is not None:
        params.append("**" + args.kwarg.arg)

    return params


class PythonModuleIndex:
    """Shallow Python source index used by ORD analysis.

    The index parses workspace Python modules without executing them and
    extracts the exported classes, functions, variables, and class members
    needed by LSP definition, diagnostics, and completion features. Modules
    are keyed by the source path they were found under (see
    ``ImportResolver.module_path()``); the imports inside a module resolve
    through the given ``ImportResolver`` like those of ORD documents. A
    cached module stays valid while the revision of its file contents in
    the resolver's ``revisions`` is unchanged.
    """
    def __init__(self, resolver: ImportResolver):
        """Initialize the Python source index."""
        self.resolver = resolver
        self.revisions = resolver.revisions
        self.python_modules = dict()
        self.star_name_lists = dict()

    def imported_paths(self, module_path: Path):
        """Return the source files that the imports of a module name."""
        module_info = self.module_info(module_path)
        if module_info is None:
            return []

        module_names = module_info["star_modules"] + module_info["import_names"]
        for member in module_info["import_members"].values():
            # The imported name may also be a submodule.
            module_names.append(member["module"])
            module_names.append(from_import_module_name(member["module"], member["export_name"]))
        paths = [self.import_path(module_info, module_name) for module_name in module_names]
        return [path for path in paths if path is not None]

    def star_names(self, module_path: Optional[Path], seen=None):
        """Return the names that ``from module import *`` binds, in module order.

        These are the names of ``__all__`` where it can be evaluated
        statically, otherwise the public names of the module.
        """
        if seen is None:
            # Name resolution asks for these over and over.
            entry = self.star_name_lists.get(module_path)
            if entry is not None and self.revisions.current(entry[0]):
                return entry[1]
            with self.revisions.track() as reads:
                names = self.star_names(module_path, seen=set())
            self.star_name_lists[module_path] = (reads, names)
            return names
        module_info = self.module_info(module_path)
        if module_info is None or module_path in seen:
            return []
        seen.add(module_path)

        names = []
        if module_info["all"] is not None:
            for kind, value in module_info["all"]:
                if kind == "names":
                    names.extend(value)
                else:
                    names.extend(self.star_names(self.import_path(module_info, value), seen))
        else:
            public_names = list(module_info["exports"]) + list(module_info["imports"]) + [
                reexport["local_name"] for reexport in module_info["reexports"]
            ]
            names.extend(name for name in public_names if not name.startswith("_"))
            for star_module in module_info["star_modules"]:
                names.extend(self.star_names(self.import_path(module_info, star_module), seen))
        return list(dict.fromkeys(names))

    def import_path(self, module_info, module_name: str):
        """Return the source file an import inside an indexed module names."""
        return self.resolver.module_path(module_info["uri"], module_name, script=False)

    def module_info(self, module_path: Optional[Path]):
        """Analyze a Python module enough for ORD import and member lookup."""
        if module_path is None:
            return None

        entry = self.python_modules.get(module_path)
        if entry is not None and self.revisions.current(entry[0]):
            return entry[1]

        # A symlinked module changes with its link and with its target.
        keys = (("file", module_path), ("file", module_path.resolve()))
        reads = {key: self.revisions.read(key) for key in keys}
        try:
            source_data = module_path.read_text(encoding="utf-8")
            if module_path.suffix == ".ord":
                syntax_tree = ord_to_py(source_data)
            else:
                syntax_tree = ast.parse(source_data, filename=str(module_path))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError, LarkError):
            self.python_modules[module_path] = (reads, None)
            return None

        source_lines = split_source_lines(source_data)
        exports = dict()
        reexports = []
        star_modules = []
        imports = dict()
        import_names = []
        import_members = dict()
        classes = dict()
        ast_columns_are_bytes = module_path.suffix == ".py"

        def ast_position(lineno, col_offset):
            if not ast_columns_are_bytes:
                return AnalysisPosition(lineno, col_offset + 1)

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
            # col_offset points at the def or class keyword, inside which
            # a plain find() can match a short name such as f. A word
            # boundary search cannot.
            match = re.search(r"\b" + re.escape(name) + r"\b", line[start_hint:])
            if match is not None:
                start = start_hint + match.start()
            else:
                start = start_hint
            return AnalysisRange(
                start=AnalysisPosition(node.lineno, start + 1),
                end=AnalysisPosition(node.lineno, start + 1 + len(name)),
            )

        def add_export(name, kind, node):
            if name in exports:
                return

            docstring = None
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                docstring = ast.get_docstring(node) or None
            signature = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                signature = {
                    "params": function_signature_params(node),
                }
            # Cells from .ord modules resolve members through the ORD
            # analysis of their uri, not the Python class machinery.
            python_class = kind == "class" and module_path.suffix != ".ord"
            exports[name] = AnalysisDefinition(
                uri=module_path.as_uri(),
                name=name,
                kind=kind,
                range=node_range(node),
                selection_range=name_range(node, name),
                docstring=docstring,
                signature=signature,
                python_module=module_path if python_class else None,
                python_class=name if python_class else None,
            )

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
                if value_export is not None and value_export.kind == "class":
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

        def add_class_member(class_info, name, kind, node, default=None):
            if name.startswith("_"):
                return

            member = class_info["members"].setdefault(name, AnalysisDefinition(
                uri=module_path.as_uri(),
                name=name,
                kind=kind,
                range=node_range(node),
                selection_range=node_range(node),
            ))
            if default is not None and member.default is None:
                class_info["members"][name] = member._replace(default=default)

        def all_expression_parts(value):
            # The forms __all__ takes in practice: literal lists,
            # concatenations, and the __all__ of an imported module.
            if isinstance(value, (ast.List, ast.Tuple)):
                names = [
                    element.value for element in value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                ]
                return [("names", names)] if len(names) == len(value.elts) else None
            if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
                left = all_expression_parts(value.left)
                right = all_expression_parts(value.right)
                return None if left is None or right is None else left + right
            if isinstance(value, ast.Attribute) and value.attr == "__all__":
                local_name = node_name(value.value)
                if local_name in import_members:
                    member = import_members[local_name]
                    module = from_import_module_name(member["module"], member["export_name"])
                    return [("module", module)]
                if local_name in imports:
                    return [("module", imports[local_name])]
            return None

        def imported_module_name(node):
            # Kept relative: the resolver resolves it from this module's path.
            return "." * node.level + (node.module or "")

        # Parts of __all__ in statement order, None without __all__, or
        # unknown when an assignment cannot be evaluated statically.
        all_parts = None
        all_unknown = False
        for node in syntax_tree.body:
            add_public_call_exports(node)

            # @public and public(...) append to __all__ (see the public package).
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(node_name(decorator) == "public" for decorator in node.decorator_list):
                    all_parts = (all_parts or []) + [("names", [node.name])]
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                if node_name(node.value.func) == "public":
                    names = [keyword.arg for keyword in node.value.keywords if keyword.arg]
                    all_parts = (all_parts or []) + [("names", names)]
            elif isinstance(node, ast.Assign):
                target_ids = [target.id for target in node.targets if isinstance(target, ast.Name)]
                if "__all__" in target_ids:
                    all_parts = all_expression_parts(node.value)
                    all_unknown = all_parts is None
            elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
                if isinstance(node.target, ast.Name) and node.target.id == "__all__":
                    parts = all_expression_parts(node.value)
                    all_unknown = all_unknown or parts is None
                    all_parts = (all_parts or []) + (parts or [])
            elif isinstance(node, ast.ImportFrom):
                if any(alias.name == "__all__" for alias in node.names):
                    all_parts = [("module", imported_module_name(node))]
                    all_unknown = False

            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_names.append(alias.name)
                    if alias.asname:
                        imports[alias.asname] = alias.name
                    else:
                        # import a.b binds the package a, not the module a.b.
                        top_name = alias.name.split(".", 1)[0]
                        imports[top_name] = top_name
                continue

            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        star_modules.append(imported_module_name(node))
                        continue

                    import_members[alias.asname or alias.name] = {
                        "module": imported_module_name(node),
                        "export_name": alias.name,
                    }
                # Keep parsing the same node for top-level reexports below.

            if isinstance(node, ast.ClassDef):
                class_info = {
                    "bases": [],
                    "member_sources": [],
                    "members": dict(),
                }
                for base_node in node.bases:
                    base_name = node_name(base_node)
                    if base_name is not None:
                        class_info["bases"].append(base_name)

                for class_node in node.body:
                    if isinstance(class_node, ast.Assign):
                        member_kind = "variable"
                        member_default = None
                        if isinstance(class_node.value, ast.Call):
                            func_name = node_name(class_node.value.func)
                            if func_name == "Parameter":
                                member_kind = "parameter"
                                for keyword in class_node.value.keywords:
                                    if keyword.arg == "default":
                                        member_default = expression_text(keyword.value)
                                        break

                        for target in class_node.targets:
                            if not isinstance(target, ast.Name):
                                continue
                            add_class_member(
                                class_info,
                                target.id,
                                member_kind,
                                target,
                                default=member_default,
                            )
                            value_name = node_name(class_node.value)
                            if (
                                target.id in ("symbol", "schematic", "layout")
                                and value_name is not None
                                and value_name.endswith("." + target.id)
                            ):
                                class_info["member_sources"].append(
                                    value_name.rsplit(".", 1)[0]
                                )
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
                        method_member = class_info["members"].setdefault(
                            class_node.name,
                            AnalysisDefinition(
                                uri=module_path.as_uri(),
                                name=class_node.name,
                                kind="function",
                                range=node_range(class_node),
                                selection_range=name_range(class_node, class_node.name),
                            ),
                        )
                        if method_member.docstring is None:
                            method_member = method_member._replace(
                                docstring=ast.get_docstring(class_node) or None,
                            )
                        if method_member.signature is None:
                            params = function_signature_params(class_node, skip_receiver=True)
                            method_member = method_member._replace(signature={"params": params})
                        class_info["members"][class_node.name] = method_member

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

                            attribute_end = ast_position(
                                target.end_lineno,
                                target.end_col_offset,
                            )
                            class_info["members"].setdefault(target.attr, AnalysisDefinition(
                                uri=module_path.as_uri(),
                                name=target.attr,
                                kind=member_kind,
                                range=node_range(target),
                                selection_range=AnalysisRange(
                                    start=AnalysisPosition(
                                        attribute_end.line,
                                        attribute_end.character - len(target.attr),
                                    ),
                                    end=attribute_end,
                                ),
                            ))

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

            for alias in node.names:
                if alias.name == "*":
                    continue

                reexports.append({
                    "local_name": alias.asname or alias.name,
                    "module": imported_module_name(node),
                    "export_name": alias.name,
                })

        module_info = {
            "uri": module_path.as_uri(),
            "path": module_path,
            "exports": exports,
            "reexports": reexports,
            "star_modules": star_modules,
            "imports": imports,
            "import_names": import_names,
            "import_members": import_members,
            "classes": classes,
            "all": None if all_unknown else all_parts,
        }
        self.python_modules[module_path] = (reads, module_info)
        return module_info

    def definition(
        self,
        module_path: Optional[Path],
        export_name: Optional[str] = None,
        seen=None,
    ):
        """Resolve a Python module or exported member definition."""
        if seen is None:
            seen = set()

        # Keyed by module and export so a re-export chain may revisit a
        # module under a different export name.
        key = (module_path, export_name)
        if key in seen:
            return None
        seen.add(key)

        module_info = self.module_info(module_path)
        if module_info is None:
            return None

        if export_name is None:
            name = module_path.parent.name if module_path.stem == "__init__" else module_path.stem
            return AnalysisDefinition(
                uri=module_info["uri"],
                name=name,
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

        match = module_info["exports"].get(export_name)
        if match is not None:
            return match

        # Later imports replace earlier bindings with the same local name.
        for reexport in reversed(module_info["reexports"]):
            if reexport["local_name"] != export_name:
                continue

            match = self.definition(
                self.import_path(module_info, reexport["module"]),
                export_name=reexport["export_name"],
                seen=seen,
            )
            if match is not None:
                return match

        module_name = self.resolver.module_name(module_path)
        if module_name is not None:
            submodule_path = self.import_path(
                module_info,
                "{}.{}".format(module_name, export_name),
            )
            match = self.definition(submodule_path, seen=seen)
            if match is not None:
                return match

        for star_module in module_info["star_modules"]:
            star_path = self.import_path(module_info, star_module)
            if export_name not in self.star_names(star_path):
                continue
            match = self.definition(star_path, export_name=export_name, seen=seen)
            if match is not None:
                return match

        return None

    def base_class_refs(self, module_path: Path, module_info, base_name: str):
        """Resolve a base class name from a parsed Python module."""
        if base_name in module_info["classes"]:
            return [(module_path, base_name)]

        if base_name in module_info["import_members"]:
            imported = module_info["import_members"][base_name]
            imported_path = self.import_path(module_info, imported["module"])
            return [(imported_path, imported["export_name"])]

        refs = []
        for star_module in module_info["star_modules"]:
            star_path = self.import_path(module_info, star_module)
            if base_name not in self.star_names(star_path):
                continue
            match = self.definition(star_path, export_name=base_name)
            if match is None:
                continue
            if match.python_class is not None:
                refs.append((match.python_module, match.python_class))

        if refs:
            return refs

        if "." not in base_name:
            return []

        # pkg.sub.S names class S of the module that local name pkg and
        # the attribute path sub lead to.
        module_part, class_name = base_name.rsplit(".", 1)
        local_name, _, attribute_path = module_part.partition(".")
        attribute_suffix = "." + attribute_path if attribute_path else ""

        imported_module = module_info["imports"].get(local_name)
        if imported_module is not None:
            imported_path = self.import_path(module_info, imported_module + attribute_suffix)
            refs.append((imported_path, class_name))

        imported_member = module_info["import_members"].get(local_name)
        if imported_member is not None:
            submodule_name = from_import_module_name(
                imported_member["module"],
                imported_member["export_name"],
            )
            submodule_path = self.import_path(module_info, submodule_name + attribute_suffix)
            if submodule_path is not None:
                refs.append((submodule_path, class_name))

        return refs

    def class_members(self, module_path: Optional[Path], class_name: str, seen=None):
        """Collect Python class members, including inherited members."""
        if seen is None:
            seen = set()

        key = (module_path, class_name)
        if key in seen:
            return dict()
        seen.add(key)

        module_info = self.module_info(module_path)
        if module_info is None:
            return dict()

        class_info = module_info["classes"].get(class_name)
        if class_info is None:
            # The class may only be re-exported here (e.g. a package
            # __init__.py). Follow the export to its defining module.
            resolved = self.definition(module_path, export_name=class_name)
            if resolved is None or resolved.python_class is None:
                return dict()
            return self.class_members(
                resolved.python_module,
                resolved.python_class,
                seen=seen,
            )

        members = dict()
        for source_name in class_info["member_sources"]:
            for source_module_path, source_class_name in self.base_class_refs(
                module_path,
                module_info,
                source_name,
            ):
                members.update(self.class_members(
                    source_module_path,
                    source_class_name,
                    seen=seen,
                ))

        for base_name in class_info["bases"]:
            if base_name in module_info["classes"]:
                members.update(self.class_members(
                    module_path,
                    base_name,
                    seen=seen,
                ))
                continue

            for base_module_path, base_class_name in self.base_class_refs(
                module_path,
                module_info,
                base_name,
            ):
                members.update(self.class_members(
                    base_module_path,
                    base_class_name,
                    seen=seen,
                ))

        members.update(class_info["members"])
        return members
