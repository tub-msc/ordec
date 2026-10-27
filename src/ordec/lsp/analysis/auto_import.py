# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""Import quick fixes for unresolved names."""

# standard imports
import re
from typing import NamedTuple

# ordec imports
from .import_resolver import package_context
from .model import AnalysisPosition, AnalysisRange


class ImportChoice(NamedTuple):
    """One way to import a name: the module and the edit adding the import."""
    module: str
    range: AnalysisRange
    text: str


def module_choices(session, uri: str, name: str):
    """Return the names of the modules that export ``name`` and import into ``uri``."""
    doc_path = session.file_uri_path(uri)
    if doc_path is not None:
        doc_path = doc_path.resolve()

    paths = []
    # Public modules of ordec are the ones declaring __all__.
    package_init = session.installed_module_path("ordec")
    if package_init is not None:
        package_root = package_init.parent
        for path in session.workspace_source_paths(package_root, ".py"):
            module_parts = path.relative_to(package_root).with_suffix("").parts
            if any(part.startswith("_") and part != "__init__" for part in module_parts):
                continue
            module_info = session.python_module_info(path)
            if module_info is None or module_info["all"] is None:
                continue
            if name in session.python_star_names(path):
                paths.append(path)

    # Workspace modules export what they define at top level, which the
    # Python index confirms.
    definition_re = re.compile(
        r"^(?:(?:cell|class|def)\s+{0}\b|{0}\s*[:=])".format(re.escape(name)),
        re.MULTILINE,
    )
    for path in session.workspace_sources_matching(definition_re):
        module_info = session.python_module_info(path)
        if module_info is not None and name in module_info["exports"]:
            paths.append(path)

    choices = dict()
    for path in paths:
        if path.resolve() == doc_path:
            continue
        module_name = session.python_module_name(path)
        if doc_path is not None and path.parent.resolve() == doc_path.parent:
            # Siblings import by their bare name, or relatively in a package,
            # whose __init__ is the package itself.
            _, package_name = package_context(path.parent)
            if path.stem == "__init__":
                module_name = "."
            else:
                module_name = ("." if package_name else "") + path.stem
        if module_name is None:
            continue
        resolved = session.resolve_python_module_path(uri, module_name)
        if resolved is None or resolved.resolve() != path.resolve():
            continue

        # Re-exports of one definition keep the shortest module name.
        definition = session.python_definition(path, export_name=name)
        key = path if definition is None else (definition.uri, definition.selection_range)
        if key not in choices or len(module_name) < len(choices[key]):
            choices[key] = module_name

    imported = {entry.module for entry in session.analyze(uri).import_entries}
    return sorted(
        set(choices.values()),
        key=lambda module_name: (module_name not in imported, module_name.count("."), module_name),
    )


def import_choices(session, uri: str, name: str):
    """Return the imports that make the unresolved ``name`` resolve in ``uri``."""
    lines = session.document_lines(uri) or []
    import_entries = session.analyze(uri).import_entries

    # New imports go below the last top-level import, else below the
    # leading comments.
    insert_line = 1
    while insert_line <= len(lines) and lines[insert_line - 1].startswith("#"):
        insert_line += 1
    line_number = 1
    while line_number <= len(lines):
        if lines[line_number - 1].startswith(("from ", "import ")):
            if "(" in lines[line_number - 1]:
                while ")" not in lines[line_number - 1] and line_number < len(lines):
                    line_number += 1
            while lines[line_number - 1].endswith("\\") and line_number < len(lines):
                line_number += 1
            insert_line = line_number + 1
        line_number += 1

    result = []
    for module_name in module_choices(session, uri, name):
        # Extend a one-line `from module import a, b` of the same module.
        pattern = r"from\s+{}\s+import\s+[\w\s,]+".format(re.escape(module_name))
        extended_line = None
        for entry in import_entries:
            if entry.kind != "from" or entry.module != module_name:
                continue
            line = lines[entry.range.start.line - 1].rstrip()
            if re.fullmatch(pattern, line):
                extended_line = entry.range.start.line
        if extended_line is not None:
            end = AnalysisPosition(extended_line, len(lines[extended_line - 1].rstrip()) + 1)
            result.append(ImportChoice(module_name, AnalysisRange(end, end), ", " + name))
            continue

        start = AnalysisPosition(insert_line, 1)
        result.append(ImportChoice(
            module_name,
            AnalysisRange(start, start),
            "from {} import {}\n".format(module_name, name),
        ))
    return result
