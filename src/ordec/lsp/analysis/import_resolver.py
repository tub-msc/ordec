# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""Import name resolution for ORD analysis.

ORD imports resolve to ``.ord`` files relative to the importing document
and the workspace root. Python imports resolve to dotted module names and
source files, which ``PythonModuleIndex`` then parses. Both live here so
that the rules for which file an import names can be compared side by side.
"""

# standard imports
import importlib.util
from pathlib import Path
from typing import Optional

# ordec imports
from .model import file_uri_to_path, find_module_source

# Suffix precedence for Python module resolution, which covers both plain
# Python modules and ORD modules importable through ordec's hook.
MODULE_SOURCE_SUFFIXES = (".py", ".ord")


def from_import_module_name(module_name: str, export_name: str):
    """Return the submodule candidate named by a from-import."""
    if not export_name or export_name == "*":
        return None

    separator = "" if module_name.endswith(".") else "."
    return module_name + separator + export_name


class ImportResolver:
    """Resolves ORD and Python import names for documents of one workspace.

    Resolving installed Python modules uses ``importlib`` and may execute
    parent package initialization code. Failures are treated as unresolved
    modules.
    """
    def __init__(self, workspace_root: Optional[str] = None):
        """Initialize the resolver for the optional workspace root."""
        self.workspace_root = workspace_root

    def ord_module_uri(self, uri: str, module_name: str):
        """Resolve an ORD import name relative to a document URI."""
        doc_path = file_uri_to_path(uri)
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

    def ord_from_import_uris(self, uri: str, module_name: str, export_name: str):
        """Return ORD module and submodule candidates for a from-import."""
        module_names = [module_name]
        submodule_name = from_import_module_name(module_name, export_name)
        if submodule_name is not None:
            module_names.append(submodule_name)

        uris = []
        for candidate_name in module_names:
            import_uri = self.ord_module_uri(uri, candidate_name)
            if import_uri is None or import_uri in uris:
                continue
            uris.append(import_uri)
        return uris

    def ord_import_uris(self, uri: str, import_entries):
        """Resolve a document's import entries to imported ORD document URIs."""
        imports = []
        seen = set()

        for import_entry in import_entries:
            if import_entry.kind == "from":
                import_uris = self.ord_from_import_uris(
                    uri,
                    import_entry.module,
                    import_entry.export_name,
                )
            else:
                import_uris = [self.ord_module_uri(uri, import_entry.module)]

            for import_uri in import_uris:
                if import_uri is None or import_uri in seen:
                    continue
                seen.add(import_uri)
                imports.append(import_uri)

        return imports

    def find_spec(self, module_name: str):
        """Return an importlib spec without letting package failures escape."""
        try:
            return importlib.util.find_spec(module_name)
        except KeyboardInterrupt:
            raise
        except BaseException:
            return None

    def workspace_module_name(self, path: Path):
        """Return the dotted module name of a resolved workspace path, or None."""
        if not self.workspace_root:
            return None

        try:
            relative_path = path.relative_to(Path(self.workspace_root).resolve())
        except ValueError:
            return None

        if relative_path.stem == "__init__":
            module_parts = relative_path.parent.parts
        else:
            module_parts = relative_path.with_suffix("").parts

        if not module_parts:
            return None
        return ".".join(module_parts)

    def python_module_path(self, module_name: str):
        """Resolve a Python module name to a source file path."""
        if self.workspace_root:
            workspace_root = Path(self.workspace_root).resolve()
            workspace_path = workspace_root.joinpath(*module_name.split("."))
            candidate = find_module_source(workspace_path, MODULE_SOURCE_SUFFIXES)
            if candidate is not None:
                return candidate.resolve()

        spec = self.find_spec(module_name)

        if spec is None or spec.origin in (None, "built-in", "frozen"):
            # Installed .ord modules are invisible to importlib unless ordec's
            # import hook is active. Resolve them via the parent package.
            if "." in module_name:
                parent_name, leaf_name = module_name.rsplit(".", 1)
                parent_path = self.python_module_path(parent_name)
                if parent_path is not None and parent_path.stem == "__init__":
                    candidate = parent_path.parent / (leaf_name + ".ord")
                    if candidate.exists():
                        return candidate.resolve()
            return None

        path = Path(spec.origin)
        if not path.exists():
            return None

        return path.resolve()

    def python_module_name(self, uri: str, module_name: str):
        """Resolve a possibly relative Python import name for a document."""
        if not module_name:
            return module_name

        if not module_name.startswith("."):
            doc_path = file_uri_to_path(uri)
            if doc_path is not None and self.workspace_root:
                import_path = doc_path.parent.joinpath(*module_name.split("."))
                candidate = find_module_source(import_path, MODULE_SOURCE_SUFFIXES)
                if candidate is not None:
                    local_name = self.workspace_module_name(candidate.resolve())
                    if local_name is not None:
                        return local_name

            return module_name

        doc_path = file_uri_to_path(uri)
        if doc_path is None or not self.workspace_root:
            return None

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

    def python_module_exists(self, module_name: str):
        """Return whether a Python module can be imported or found locally."""
        if not module_name:
            return False

        if self.python_module_path(module_name) is not None:
            return True

        return self.find_spec(module_name) is not None
