# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""Import name resolution for ORD analysis.

At runtime, ordec's import hook (``ordec.importer``) makes ``.ord`` files
importable as ordinary Python modules, so ORD and Python imports follow one
set of rules. The resolver mirrors them for the imports of a source file,
an ORD document or a Python module: in each directory, packages win over
modules and ``.py`` files over ``.ord`` files.

Which directories are on ``sys.path`` depends on how a design is run, so
they are derived from the files: walking up from a source file while each
directory holds an ``__init__.py`` or ``__init__.ord`` yields the file's
package and its import root, the directory above the topmost package, as
in pytest's default "prepend" import mode. Absolute names search the import
root, the directory of an ORD document (``ordec FILE`` puts it first on
``sys.path``; the modules it imports are not run that way), the workspace
root (a guess at the current directory for ``ordec -m``) and then the
installed packages. Relative names resolve within the file's
package. Files in a directory without ``__init__`` may still belong to a
namespace package, so their relative imports resolve against their own
directory.

A ``.ord`` file found this way is analyzed as an ORD document. Python
modules, including ``.ord`` modules of installed packages, are handed to
``PythonModuleIndex`` by source path, since one module name can name
different files for different importers.
"""

# standard imports
import importlib.util
from pathlib import Path
from typing import NamedTuple, Optional

# ordec imports
from .model import file_uri_to_path, find_module_source
from .revisions import Revisions

# Suffix precedence within one directory, as registered by ordec.importer.
MODULE_SOURCE_SUFFIXES = (".py", ".ord")


class ImportTarget(NamedTuple):
    """What an import resolves to.

    ``path`` is the module source found for the importing file, an ORD
    document or a Python module. Absolute names without one keep
    ``python_name`` for the lookup among the installed packages. Neither is
    set for relative imports that leave their package or find no module file.
    """
    path: Optional[Path] = None
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
    """Resolves ORD and Python import names for source files of one workspace.

    Resolving installed Python modules uses ``importlib`` and may execute
    parent package initialization code. Failures are treated as unresolved
    modules.

    Results are memoized with the ``"files"`` revision of ``revisions``
    and reused while no files came or went.
    """
    def __init__(
        self,
        workspace_root: Optional[str] = None,
        revisions: Optional[Revisions] = None,
    ):
        """Initialize the resolver for the optional workspace root."""
        self.workspace_root = workspace_root
        self.revisions = revisions if revisions is not None else Revisions()
        self.memo_files = None
        self.targets = dict()
        self.module_paths = dict()
        self.installed_paths = dict()
        self.module_names = dict()

    def clear_outdated_memos(self):
        """Clear the memos once the ``"files"`` revision changed."""
        files = self.revisions.read("files")
        if files != self.memo_files:
            self.memo_files = files
            for memo in (self.targets, self.module_paths, self.installed_paths, self.module_names):
                memo.clear()

    def import_candidates(self, doc_path: Optional[Path], module_name: str, script: bool):
        """Return the (directory, module name, package only) triples to probe.

        Package only marks a dots-only relative import such as
        ``from . import x``, which names a package, never a module file.
        """
        if doc_path is None:
            # Documents without a file, such as untitled editor buffers,
            # have only the workspace root to search.
            if self.workspace_root and not module_name.startswith("."):
                return [(Path(self.workspace_root), module_name, False)]
            return []

        import_root, package_name = package_context(doc_path.parent)

        if not module_name.startswith("."):
            directories = [import_root]
            if script:
                directories.append(doc_path.parent)
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

    def import_target(self, uri: str, module_name: str, script: bool = True):
        """Resolve an import in the source file at ``uri`` to an ImportTarget.

        ``script`` marks an ORD document, which may be run as ``ordec FILE``
        with its directory on ``sys.path``. Modules imported by others are
        not, and Python has no implicit relative imports.
        """
        self.clear_outdated_memos()
        key = (uri, module_name, script)
        if key in self.targets:
            return self.targets[key]

        if not module_name or module_name.startswith("."):
            target = ImportTarget()
        else:
            target = ImportTarget(python_name=module_name)

        if module_name:
            candidates = self.import_candidates(file_uri_to_path(uri), module_name, script)
            for directory, name, package_only in candidates:
                path = find_module_source(
                    directory.joinpath(*name.split(".")),
                    MODULE_SOURCE_SUFFIXES,
                    package_only=package_only,
                )
                if path is not None:
                    target = ImportTarget(path=path)
                    break

        self.targets[key] = target
        return target

    def ord_module_uri(self, uri: str, module_name: str):
        """Return the URI of the ORD document an import names, or None."""
        path = self.import_target(uri, module_name).path
        if path is None or path.suffix != ".ord":
            return None
        return path.as_uri()

    def module_path(self, uri: str, module_name: str, script: bool = True):
        """Return the source file an import names, or None.

        This covers all modules the Python index reads, installed ones
        included. Symlinks are not resolved: as at runtime, the package of a
        module follows the path it was found under.
        """
        self.clear_outdated_memos()
        key = (uri, module_name, script)
        if key in self.module_paths:
            return self.module_paths[key]

        target = self.import_target(uri, module_name, script)
        if target.path is not None:
            path = target.path
        elif target.python_name is not None:
            path = self.installed_module_path(target.python_name)
        else:
            path = None
        self.module_paths[key] = path
        return path

    def module_name(self, path: Path):
        """Return the dotted name of a module source file below its import root."""
        self.clear_outdated_memos()
        if path not in self.module_names:
            import_root, _ = package_context(path.parent)
            self.module_names[path] = module_name_in(path, import_root)
        return self.module_names[path]

    def module_exists(self, uri: str, module_name: str):
        """Return whether an import names a module source or installed module."""
        target = self.import_target(uri, module_name)
        if target.path is not None:
            return True
        return self.installed_module_exists(target.python_name)

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

    def installed_module_path(self, module_name: str):
        """Resolve an absolute module name to a source file of the installed packages."""
        self.clear_outdated_memos()
        if module_name in self.installed_paths:
            return self.installed_paths[module_name]

        path = None
        spec = self.find_spec(module_name)
        origin = None if spec is None else spec.origin
        if origin == "frozen":
            # Frozen stdlib modules such as os keep their source file name
            # in the loader state.
            origin = getattr(spec.loader_state, "filename", None)
        if origin in (None, "built-in", "frozen"):
            # Installed .ord modules are invisible to importlib unless ordec's
            # import hook is active. Resolve them via the parent package.
            if "." in module_name:
                parent_name, leaf_name = module_name.rsplit(".", 1)
                parent_path = self.installed_module_path(parent_name)
                if parent_path is not None and parent_path.stem == "__init__":
                    candidate = parent_path.parent / (leaf_name + ".ord")
                    if candidate.exists():
                        path = candidate
        elif Path(origin).exists():
            path = Path(origin).absolute()

        self.installed_paths[module_name] = path
        return path

    def installed_module_exists(self, module_name: str):
        """Return whether an installed Python module can be imported."""
        if not module_name:
            return False

        if self.installed_module_path(module_name) is not None:
            return True

        return self.find_spec(module_name) is not None
