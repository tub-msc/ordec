# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""Generate the views of the cells in an ORD module and report their errors.

The language server runs ``python -m ordec.lsp.check PATH`` when a document
is saved and ``checkOnSave`` is enabled. Each error is printed as one JSON
line with the line number it belongs to, as soon as it is found.
"""

# standard imports
import importlib
import inspect
import json
import os
import sys
import threading
import traceback
from pathlib import Path

# ordec imports
from .. import importer  # registers the import of .ord modules
from ..core.cell import Cell, ViewGenerator
from ..core.schema import Layout, Schematic, Symbol
from .analysis.import_resolver import module_name_in, package_context

# Simulation and report views run external tools, which is too slow here.
CHECKED_VIEW_TYPES = (Symbol, Schematic, Layout)


def report(results, path: Path, exc: Exception, fallback_line: int, view_name=None):
    """Write an error to ``results``, at the deepest line of ``path`` that raised it."""
    line = fallback_line
    for frame in traceback.extract_tb(exc.__traceback__):
        if Path(frame.filename).resolve() == path and frame.lineno:
            line = frame.lineno
    message = "{}: {}".format(type(exc).__name__, exc)
    if view_name is not None:
        message = "{} failed: {}".format(view_name, message)
    print(json.dumps({"line": line, "message": message}), file=results, flush=True)


def exit_on_eof():
    """End the check once the server closes stdin, also when the server dies."""
    sys.stdin.read()
    os._exit(1)


def main():
    # Results go to a copy of stdout. The checked code and the processes
    # it starts write to stderr instead, so they cannot garble them.
    results = os.fdopen(os.dup(1), "w")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    threading.Thread(target=exit_on_eof, daemon=True).start()

    path = Path(sys.argv[1]).resolve()
    import_root, _ = package_context(path.parent)
    module_name = module_name_in(path, import_root)
    if module_name is None:
        return
    sys.path.insert(0, str(import_root))
    try:
        module = importlib.import_module(module_name)
    except SyntaxError as exc:
        # The static analysis reports the syntax errors of the file itself.
        if exc.filename is None or Path(exc.filename).resolve() != path:
            report(results, path, exc, 1)
        return
    except Exception as exc:
        report(results, path, exc, 1)
        return
    module_file = getattr(module, "__file__", None)
    if module_file is None or Path(module_file).resolve() != path:
        message = "`{}` is shadowed by {}; rename the file to check its views.".format(
            module_name,
            module_file or "a built-in module",
        )
        print(json.dumps({"line": 1, "message": message}), file=results, flush=True)
        return

    for cell_class in list(vars(module).values()):
        if not isinstance(cell_class, type) or not issubclass(cell_class, Cell):
            continue
        if cell_class.__module__ != module.__name__:
            continue
        class_line = getattr(cell_class, "__firstlineno__", 1)
        views = dict()
        for name in dir(cell_class):
            view = inspect.getattr_static(cell_class, name)
            if (
                isinstance(view, ViewGenerator)
                and view.func.__annotations__.get("return") in CHECKED_VIEW_TYPES
            ):
                # Inherited views can be defined in another file.
                code = view.func.__code__
                same_file = Path(code.co_filename).resolve() == path
                views[name] = code.co_firstlineno if same_file else class_line
        try:
            instances = cell_class.discoverable_instances()
        except Exception as exc:
            view_name = "{}.discoverable_instances()".format(cell_class.__name__)
            report(results, path, exc, class_line, view_name)
            continue
        for instance in instances:
            for name, line in views.items():
                try:
                    getattr(instance, name)
                except Exception as exc:
                    report(results, path, exc, line, "{!r}.{}".format(instance, name))


if __name__ == "__main__":
    main()
