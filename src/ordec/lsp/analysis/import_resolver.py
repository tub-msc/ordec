# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""Import name resolution for ORD analysis.

At runtime, ordec's import hook (``ordec.importer``) makes ``.ord`` files
importable as ordinary Python modules, so ORD and Python imports follow one
set of rules. The resolver mirrors them for a document's imports: in each
directory, packages win over modules and ``.py`` files over ``.ord`` files.

Which directories are on ``sys.path`` depends on how a design is run, so
they are derived from the files: walking up from a document while each
directory holds an ``__init__.py`` or ``__init__.ord`` yields the
document's package and its import root, the directory above the topmost
package, as in pytest's default "prepend" import mode. Absolute names
search the import root, the document's directory (``ordec FILE`` puts it
first on ``sys.path``), the workspace root (a guess at the current
directory for ``ordec -m``) and then the installed packages. Relative names
resolve within the document's package. Documents in a directory without
``__init__`` may still belong to a namespace package, so their relative
imports resolve against their own directory.

A ``.ord`` file found this way is analyzed as an ORD document. Everything
else, including ``.ord`` modules of installed packages, is handed to
``PythonModuleIndex`` by module name.
"""

# standard imports
import importlib.util
from pathlib import Path
from typing import NamedTuple, Optional

# ordec imports
from .model import file_uri_to_path, find_module_source

# Suffix precedence within one directory, as registered by ordec.importer.
MODULE_SOURCE_SUFFIXES = (".py", ".ord")


class ImportTarget(NamedTuple):
    """What an import resolves to: an ORD document or a Python module name.

    At most one field is set; neither is set for relative imports that
    leave their package or find no module file.
    """
    ord_uri: Optional[str] = None
    python_name: Optional[str] = None


def from_import_module_name(module_name: str, export_name: str):
    """Return the submodule candidate named by a from-import."""
    if not export_name or export_name == "*":
        return None

    separator = "" if module_name.endswith(".") else "."
    return module_name + separator + export_name


def module_name_in(path: Path, search_dir: Path):
    """Return the dotted name of a module source file in search_dir, or None."""
    try:
        relative_path = path.relative_to(search_dir)
    except ValueError:
        return None

    if relative_path.stem == "__init__":
        module_parts = relative_path.parent.parts
    else:
        module_parts = relative_path.with_suffix("").parts

    if not module_parts:
        return None
    return ".".join(module_parts)


def package_context(directory: Path):
    """Return the import root and package name for modules in a directory.

    The package name is empty for a directory that is not a regular package,
    whose modules are then top-level modules of the directory itself.
    """
    package_parts = []
    while directory.name and any(
        (directory / ("__init__" + suffix)).is_file()
        for suffix in MODULE_SOURCE_SUFFIXES
    ):
        package_parts.insert(0, directory.name)
        directory = directory.parent
    return directory, ".".join(package_parts)


class ImportResolver:
    """Resolves ORD and Python import names for documents of one workspace.

    ``search_dirs`` models the ``sys.path`` entries before the installed
    packages: the workspace root, followed by the directories that document
    imports were found in (see ``import_target()``). Resolving installed
    Python modules uses ``importlib`` and may execute parent package
    initialization code. Failures are treated as unresolved modules.
    """
    def __init__(self, workspace_root: Optional[str] = None):
        """Initialize the resolver for the optional workspace root."""
        self.workspace_root = workspace_root
        self.search_dirs = [Path(workspace_root)] if workspace_root else []

    def import_candidates(self, doc_path: Path, module_name: str):
        """Return the (directory, module name, package only) triples to probe.

        Package only marks a dots-only relative import such as
        ``from . import x``, which names a package, never a module file.
        """
        import_root, package_name = package_context(doc_path.parent)

        if not module_name.startswith("."):
            directories = [import_root, doc_path.parent]
            if self.workspace_root:
                directories.append(Path(self.workspace_root))
            unique_directories = list(dict.fromkeys(directories))
            return [(directory, module_name, False) for directory in unique_directories]

        tail = module_name.lstrip(".")
        if package_name:
            try:
                absolute_name = importlib.util.resolve_name(module_name, package_name)
            except (ImportError, ValueError):
                # The import climbs above the topmost package.
                return []
            return [(import_root, absolute_name, not tail)]

        base_dir = doc_path.parent
        for _ in range(len(module_name) - len(tail) - 1):
            base_dir = base_dir.parent
        if tail:
            return [(base_dir, tail, False)]
        return [(base_dir.parent, base_dir.name, True)]

    def import_target(self, uri: str, module_name: str):
        """Resolve an import in the document at ``uri`` to an ImportTarget."""
        if not module_name:
            return ImportTarget()

        relative = module_name.startswith(".")
        doc_path = file_uri_to_path(uri)
        if doc_path is None:
            # Documents without a file have no directory to search.
            return ImportTarget() if relative else ImportTarget(python_name=module_name)

        for directory, name, package_only in self.import_candidates(doc_path, module_name):
            path = find_module_source(
                directory.joinpath(*name.split(".")),
                MODULE_SOURCE_SUFFIXES,
                package_only=package_only,
            )
            if path is None:
                continue

            if path.suffix == ".ord":
                return ImportTarget(ord_uri=path.as_uri())

            # The Python index finds modules by name, so the directory the
            # name is relative to becomes one of its search directories.
            if directory not in self.search_dirs:
                self.search_dirs.append(directory)
            return ImportTarget(python_name=name)

        return ImportTarget() if relative else ImportTarget(python_name=module_name)

    def ord_from_import_uris(self, uri: str, module_name: str, export_name: str):
        """Return ORD module and submodule candidates for a from-import."""
        module_names = [module_name]
        submodule_name = from_import_module_name(module_name, export_name)
        if submodule_name is not None:
            module_names.append(submodule_name)

        uris = []
        for candidate_name in module_names:
            import_uri = self.import_target(uri, candidate_name).ord_uri
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
                import_uris = [self.import_target(uri, import_entry.module).ord_uri]

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

    def python_module_path(self, module_name: str):
        """Resolve an absolute Python module name to a source file path."""
        for search_dir in self.search_dirs:
            candidate = find_module_source(
                search_dir.resolve().joinpath(*module_name.split(".")),
                MODULE_SOURCE_SUFFIXES,
            )
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

    def python_module_exists(self, module_name: str):
        """Return whether a Python module can be imported or found locally."""
        if not module_name:
            return False

        if self.python_module_path(module_name) is not None:
            return True

        return self.find_spec(module_name) is not None
