# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from pathlib import Path
import re
from typing import List
from typing import NamedTuple
from typing import Optional
from urllib.parse import unquote
from urllib.parse import urlparse

from lark import Token
from lark import Tree
from lark.exceptions import UnexpectedCharacters
from lark.exceptions import UnexpectedInput
from lark.exceptions import UnexpectedToken

# ordec imports
from ..ord2.parser import format_error
from ..ord2.parser import parser


class AnalysisPosition(NamedTuple):
    line: int
    character: int

    def to_dict(self):
        return {
            "line": self.line,
            "character": self.character,
        }


class AnalysisRange(NamedTuple):
    start: AnalysisPosition
    end: AnalysisPosition

    def to_dict(self):
        return {
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
        }


class AnalysisDiagnostic(NamedTuple):
    range: AnalysisRange
    severity: str
    message: str
    code: Optional[str] = None

    def to_dict(self):
        return {
            "range": self.range.to_dict(),
            "severity": self.severity,
            "message": self.message,
            "code": self.code,
        }


class AnalysisSymbol(NamedTuple):
    name: str
    kind: str
    range: AnalysisRange
    selection_range: AnalysisRange

    def to_dict(self):
        return {
            "name": self.name,
            "kind": self.kind,
            "range": self.range.to_dict(),
            "selection_range": self.selection_range.to_dict(),
        }


class AnalysisImport(NamedTuple):
    kind: str
    module: str
    export_name: Optional[str]
    local_name: str
    range: AnalysisRange
    selection_range: AnalysisRange

    def to_dict(self):
        return {
            "kind": self.kind,
            "module": self.module,
            "export_name": self.export_name,
            "local_name": self.local_name,
            "range": self.range.to_dict(),
            "selection_range": self.selection_range.to_dict(),
        }


class DocumentAnalysis:
    def __init__(
        self,
        uri: str,
        version: Optional[int],
        diagnostics: List[AnalysisDiagnostic],
        symbols: List[AnalysisSymbol],
        imports: Optional[List[str]] = None,
        import_entries: Optional[List[AnalysisImport]] = None,
        exports: Optional[List[str]] = None,
        scopes=None,
        bindings=None,
        occurrences=None,
    ):
        self.uri = uri
        self.version = version
        self.diagnostics = diagnostics
        self.symbols = symbols
        self.imports = imports if imports is not None else []
        self.import_entries = import_entries if import_entries is not None else []
        self.exports = exports if exports is not None else []
        self.scopes = scopes if scopes is not None else dict()
        self.bindings = bindings if bindings is not None else []
        self.binding_map = dict((binding["id"], binding) for binding in self.bindings)
        self.occurrences = occurrences if occurrences is not None else []

    def to_dict(self):
        return {
            "uri": self.uri,
            "version": self.version,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "symbols": [symbol.to_dict() for symbol in self.symbols],
            "imports": list(self.imports),
            "exports": list(self.exports),
        }


def position_before(left: AnalysisPosition, right: AnalysisPosition):
    if left.line != right.line:
        return left.line < right.line
    return left.character < right.character


def position_before_or_equal(left: AnalysisPosition, right: AnalysisPosition):
    return not position_before(right, left)


def range_contains(value_range: AnalysisRange, position: AnalysisPosition):
    if not position_before_or_equal(value_range.start, position):
        return False
    return position_before(position, value_range.end)


class AnalysisSession:
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = workspace_root
        self.documents = dict()

    def open_document(self, uri: str, text: str, version: Optional[int] = None):
        self.documents[uri] = {
            "text": text,
            "version": version,
            "analysis": None,
        }

    def update_document(self, uri: str, text: str, version: Optional[int] = None):
        self.documents[uri] = {
            "text": text,
            "version": version,
            "analysis": None,
        }

    def close_document(self, uri: str):
        self.documents.pop(uri, None)

    def ensure_document(self, uri: str):
        if uri not in self.documents and uri.startswith("file:"):
            path = Path(unquote(urlparse(uri).path))
            self.open_path(str(path))
        return uri in self.documents

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

        import_path = import_path.with_suffix(".ord")
        if import_path.exists():
            return import_path.resolve().as_uri()

        return None

    def analyze(self, uri: str):
        doc = self.documents[uri]
        if doc["analysis"] is None:
            doc["analysis"] = analyze_ord2(doc["text"], uri=uri, version=doc["version"])
        return doc["analysis"]

    def open_path(self, path: str, version: Optional[int] = None):
        path = Path(path).resolve()
        with open(path) as source_file:
            text = source_file.read()
        uri = path.as_uri()
        self.open_document(uri, text, version=version)
        return uri

    def update_path(self, path: str, version: Optional[int] = None):
        path = Path(path).resolve()
        with open(path) as source_file:
            text = source_file.read()
        uri = path.as_uri()
        self.update_document(uri, text, version=version)
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
                        self.open_path(str(path))
                    uris.append(uri)
                return uris

        uris = []
        for uri in sorted(self.documents):
            if uri.startswith("file:"):
                uris.append(uri)
        return uris

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

        return candidates

    def definition_key(self, definition):
        if definition.get("binding_id") is not None and not definition.get("exported"):
            return (definition["uri"], definition["binding_id"])

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
            return None

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
                    continue

                match = self.find_export(import_uri, import_entry.export_name)
                if match is not None:
                    return match

            else:
                match = self.module_definition(uri, import_entry.module)
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

    def completions(self, uri: str, position: AnalysisPosition):
        if not self.ensure_document(uri):
            return []

        analysis = self.analyze(uri)
        items = dict()

        for binding in self.visible_bindings(uri, position):
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", binding["name"]) is None:
                continue

            items.setdefault(binding["name"], {
                "label": binding["name"],
                "kind": binding["kind"],
                "detail": binding["kind"],
            })

        for symbol in analysis.symbols:
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", symbol.name) is None:
                continue

            items.setdefault(symbol.name, {
                "label": symbol.name,
                "kind": symbol.kind,
                "detail": symbol.kind,
            })

        for import_entry in analysis.import_entries:
            if import_entry.kind == "from":
                import_uri = None
                if import_entry.module and set(import_entry.module) == {"."}:
                    import_uri = self.resolve_module_uri(uri, import_entry.module + import_entry.export_name)
                else:
                    import_uri = self.resolve_module_uri(uri, import_entry.module)

                import_kind = "module"
                if import_uri is not None:
                    match = self.find_export(import_uri, import_entry.export_name)
                    if match is not None:
                        import_kind = match["kind"]

                detail = "from {} import {}".format(import_entry.module, import_entry.export_name)
                if import_entry.local_name != import_entry.export_name:
                    detail = "{} as {}".format(detail, import_entry.local_name)

                items.setdefault(import_entry.local_name, {
                    "label": import_entry.local_name,
                    "kind": import_kind,
                    "detail": detail,
                })

            else:
                detail = "import {}".format(import_entry.module)
                if import_entry.local_name != import_entry.module.split(".", 1)[0]:
                    detail = "{} as {}".format(detail, import_entry.local_name)

                items.setdefault(import_entry.local_name, {
                    "label": import_entry.local_name,
                    "kind": "module",
                    "detail": detail,
                })

        for keyword in (
            "cell",
            "class",
            "def",
            "viewgen",
            "path",
            "net",
            "port",
            "input",
            "output",
            "inout",
            "return",
        ):
            items.setdefault(keyword, {
                "label": keyword,
                "kind": "keyword",
                "detail": "keyword",
            })

        result = []
        for label in sorted(items):
            result.append(items[label])
        return result

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

    def prepare_rename(self, uri: str, position: AnalysisPosition):
        name_info = self.name_at_position(uri, position)
        if name_info is None:
            return None

        if self.definition(uri, position) is None:
            return None

        return {
            "range": name_info["range"],
            "placeholder": name_info["name"],
        }

    def rename(self, uri: str, position: AnalysisPosition, new_name: str):
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", new_name) is None:
            raise ValueError("Invalid identifier: {}".format(new_name))

        name_info = self.name_at_position(uri, position)
        if name_info is None:
            return None

        definition = self.definition(uri, position)
        if definition is None:
            return None

        references = self.references(uri, position)
        if definition["kind"] == "module" or name_info["name"] != definition["name"]:
            changes = []
            for reference in references:
                if reference["uri"] != uri or reference["name"] != name_info["name"]:
                    continue

                changes.append({
                    "range": reference["range"],
                    "new_text": new_name,
                })

            if not changes:
                return None

            return {
                uri: changes,
            }

        changes = dict()
        for reference in references:
            changes.setdefault(reference["uri"], []).append({
                "range": reference["range"],
                "new_text": new_name,
            })

        if not changes:
            return None

        return changes

    def references(self, uri: str, position: AnalysisPosition):
        definition = self.definition(uri, position)
        if definition is None:
            return []

        references = []
        target = self.definition_key(definition)

        for ref_uri in self.analyze_related(uri):
            for candidate in self.reference_candidates(ref_uri):
                resolved = self.definition(ref_uri, candidate["range"].start)
                if resolved is None:
                    continue

                if self.definition_key(resolved) != target:
                    continue

                references.append({
                    "uri": ref_uri,
                    "name": candidate["name"],
                    "range": candidate["range"],
                })

        return references

    def definition(self, uri: str, position: AnalysisPosition):
        if not self.ensure_document(uri):
            return None

        local_definition = self.local_definition(uri, position)
        if local_definition is not None:
            return local_definition

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


def analyze_ord2(source_data: str, uri: str = "", version: Optional[int] = None):
    """Parse ORD2 source and return diagnostics plus declaration symbols."""

    def tree_range(node: Tree):
        return AnalysisRange(
            start=AnalysisPosition(node.meta.line, node.meta.column),
            end=AnalysisPosition(node.meta.end_line, node.meta.end_column),
        )

    def tree_text(node):
        if isinstance(node, Token):
            return node.value

        if node.data == "getattr":
            return "{}.{}".format(tree_text(node.children[0]), tree_text(node.children[1]))

        if node.data == "getitem":
            return "{}[{}]".format(tree_text(node.children[0]), tree_text(node.children[1]))

        parts = []
        for child in node.children:
            parts.append(tree_text(child))
        return "".join(parts)

    try:
        syntax_tree = parser.parse(source_data + "\n")
    except UnexpectedToken as exc:
        diagnostic = AnalysisDiagnostic(
            range=AnalysisRange(
                start=AnalysisPosition(exc.line, exc.column),
                end=AnalysisPosition(exc.line, exc.column),
            ),
            severity="error",
            message=(
                "Syntax Error: Unexpected token `{}`\n\n"
                "Expected one of: {}\n"
                "At line {}, column {}:\n\n{}"
            ).format(
                exc.token,
                ", ".join(sorted(exc.expected)),
                exc.line,
                exc.column,
                format_error(source_data, exc.line, exc.column),
            ),
            code="unexpected-token",
        )
        return DocumentAnalysis(uri=uri, version=version, diagnostics=[diagnostic], symbols=[])
    except UnexpectedCharacters as exc:
        diagnostic = AnalysisDiagnostic(
            range=AnalysisRange(
                start=AnalysisPosition(exc.line, exc.column),
                end=AnalysisPosition(exc.line, exc.column),
            ),
            severity="error",
            message=(
                "Syntax Error: Unexpected character `{}`\n\n"
                "At line {}, column {}:\n\n{}"
            ).format(
                exc.char,
                exc.line,
                exc.column,
                format_error(source_data, exc.line, exc.column),
            ),
            code="unexpected-character",
        )
        return DocumentAnalysis(uri=uri, version=version, diagnostics=[diagnostic], symbols=[])
    except UnexpectedInput as exc:
        diagnostic = AnalysisDiagnostic(
            range=AnalysisRange(
                start=AnalysisPosition(exc.line, exc.column),
                end=AnalysisPosition(exc.line, exc.column),
            ),
            severity="error",
            message="Syntax Error\n\nAt line {}, column {}:\n\n{}".format(
                exc.line,
                exc.column,
                format_error(source_data, exc.line, exc.column),
            ),
            code="unexpected-input",
        )
        return DocumentAnalysis(uri=uri, version=version, diagnostics=[diagnostic], symbols=[])

    symbols = []
    imports = []
    import_entries = []
    exports = []
    scopes = {
        0: {
            "id": 0,
            "parent_id": None,
            "range": tree_range(syntax_tree),
            "selection_range": tree_range(syntax_tree),
            "depth": 0,
            "bindings": [],
        },
    }
    scope_bindings = {
        0: dict(),
    }
    bindings = []
    occurrences = []

    def simple_name_node(node):
        if not isinstance(node, Tree):
            return None

        if node.data == "name":
            return node

        if node.data != "var" or len(node.children) != 1:
            return None

        child = node.children[0]
        if not isinstance(child, Tree) or child.data != "name":
            return None

        return child

    def add_scope(node, parent_id, name_node=None):
        scope_id = len(scopes)
        scopes[scope_id] = {
            "id": scope_id,
            "parent_id": parent_id,
            "range": tree_range(node),
            "selection_range": tree_range(name_node if name_node is not None else node),
            "depth": scopes[parent_id]["depth"] + 1,
            "bindings": [],
        }
        scope_bindings[scope_id] = dict()
        return scope_id

    def resolve_binding(scope_id, name):
        while scope_id is not None:
            binding_id = scope_bindings[scope_id].get(name)
            if binding_id is not None:
                return binding_id
            scope_id = scopes[scope_id]["parent_id"]
        return None

    def add_binding(scope_id, name_node, kind, node_range=None, exported=False):
        name = tree_text(name_node)
        binding_id = scope_bindings[scope_id].get(name)

        if binding_id is None:
            binding_id = len(bindings) + 1
            bindings.append({
                "id": binding_id,
                "name": name,
                "kind": kind,
                "scope_id": scope_id,
                "range": node_range if node_range is not None else tree_range(name_node),
                "selection_range": tree_range(name_node),
                "exported": exported,
            })
            scopes[scope_id]["bindings"].append(binding_id)
            scope_bindings[scope_id][name] = binding_id

        occurrences.append({
            "name": name,
            "range": tree_range(name_node),
            "scope_id": scope_id,
            "binding_id": binding_id,
        })

        return binding_id

    def add_reference(scope_id, name_node):
        name = tree_text(name_node)
        binding_id = resolve_binding(scope_id, name)

        occurrences.append({
            "name": name,
            "range": tree_range(name_node),
            "scope_id": scope_id,
            "binding_id": binding_id,
        })

    def bind_parameters(parameters_node, scope_id):
        for child in parameters_node.children:
            if not isinstance(child, Tree):
                continue

            if child.data == "name":
                add_binding(scope_id, child, "parameter")
                continue

            if child.data != "paramvalue":
                visit(child, scope_id)
                continue

            name_node = None
            for value_node in child.children:
                if not isinstance(value_node, Tree):
                    continue

                if name_node is None and value_node.data == "name":
                    name_node = value_node
                    add_binding(scope_id, name_node, "parameter")
                    continue

                visit(value_node, scope_id)

    def bind_arguments(arguments_node, scope_id):
        for child in arguments_node.children:
            if not isinstance(child, Tree):
                continue

            if child.data != "argvalue":
                visit(child, scope_id)
                continue

            value_nodes = [
                value_node for value_node in child.children
                if isinstance(value_node, Tree)
            ]
            if value_nodes:
                name_node = simple_name_node(value_nodes[0])
                if name_node is not None:
                    add_binding(scope_id, name_node, "parameter")

            for value_node in value_nodes[1:]:
                visit(value_node, scope_id)

    def visit(node, scope_id, top_level=False):
        if not isinstance(node, Tree):
            return

        if node.data in ("celldef", "viewgen", "funcdef", "classdef"):
            name_node = None
            for child in node.children:
                if isinstance(child, Tree) and child.data == "name":
                    name_node = child
                    break
            if name_node is not None:
                kind = "function"
                if node.data in ("celldef", "classdef"):
                    kind = "class"
                name = tree_text(name_node)
                symbols.append(AnalysisSymbol(
                    name=name,
                    kind=kind,
                    range=tree_range(node),
                    selection_range=tree_range(name_node),
                ))
                add_binding(
                    scope_id,
                    name_node,
                    kind,
                    node_range=tree_range(node),
                    exported=top_level,
                )
                if top_level:
                    exports.append(name)
                child_scope_id = add_scope(node, scope_id, name_node=name_node)
                for child in node.children:
                    if not isinstance(child, Tree) or child is name_node:
                        continue

                    if node.data == "funcdef" and child.data == "parameters":
                        bind_parameters(child, child_scope_id)
                        continue

                    if node.data == "viewgen" and child.data == "arguments":
                        bind_arguments(child, child_scope_id)
                        continue

                    visit(child, child_scope_id)
                return

        if node.data == "context_element" and len(node.children) >= 2:
            kind_node = node.children[0]
            target_node = node.children[1]
            if isinstance(kind_node, Tree) and isinstance(target_node, Tree):
                symbols.append(AnalysisSymbol(
                    name="{} {}".format(tree_text(kind_node), tree_text(target_node)),
                    kind="context",
                    range=tree_range(node),
                    selection_range=tree_range(target_node),
                ))
            return

        if node.data in ("path_stmt", "net_stmt"):
            names = []
            selection_node = None
            for child in node.children:
                if isinstance(child, Tree) and child.data == "var":
                    if selection_node is None:
                        selection_node = child
                    names.append(tree_text(child))
            if names and selection_node is not None:
                symbols.append(AnalysisSymbol(
                    name=", ".join(names),
                    kind=node.data[:-5],
                    range=tree_range(node),
                    selection_range=tree_range(selection_node),
                ))
            return

        if node.data == "import_name":
            for child in node.children:
                if not isinstance(child, Tree) or child.data != "dotted_as_names":
                    continue

                for import_node in child.children:
                    if not isinstance(import_node, Tree) or import_node.data != "dotted_as_name":
                        continue

                    parts = []
                    value_nodes = []
                    for value_node in import_node.children:
                        if not isinstance(value_node, Tree):
                            continue
                        value_nodes.append(value_node)
                        parts.append(tree_text(value_node))

                    if len(parts) == 2:
                        imports.append("{} as {}".format(parts[0], parts[1]))
                    elif parts:
                        imports.append(parts[0])

                    if not value_nodes:
                        continue

                    module_name = tree_text(value_nodes[0])
                    local_name = module_name.split(".", 1)[0]
                    selection_node = value_nodes[0]
                    if len(value_nodes) == 2:
                        local_name = tree_text(value_nodes[1])
                        selection_node = value_nodes[1]

                    import_entries.append(AnalysisImport(
                        kind="import",
                        module=module_name,
                        export_name=None,
                        local_name=local_name,
                        range=tree_range(import_node),
                        selection_range=tree_range(selection_node),
                    ))
            return

        if node.data == "import_from":
            module = ""
            names = []
            for child in node.children:
                if not isinstance(child, Tree):
                    continue

                if child.data == "dots":
                    module = tree_text(child) + module
                elif child.data == "dotted_name":
                    module = module + tree_text(child)
                elif child.data == "import_as_names":
                    for import_node in child.children:
                        if not isinstance(import_node, Tree) or import_node.data != "import_as_name":
                            continue

                        parts = []
                        value_nodes = []
                        for value_node in import_node.children:
                            if not isinstance(value_node, Tree):
                                continue
                            value_nodes.append(value_node)
                            parts.append(tree_text(value_node))

                        if len(parts) == 2:
                            names.append("{} as {}".format(parts[0], parts[1]))
                        elif parts:
                            names.append(parts[0])

                        if not value_nodes:
                            continue

                        export_name = tree_text(value_nodes[0])
                        local_name = export_name
                        selection_node = value_nodes[0]
                        if len(value_nodes) == 2:
                            local_name = tree_text(value_nodes[1])
                            selection_node = value_nodes[1]

                        import_entries.append(AnalysisImport(
                            kind="from",
                            module=module,
                            export_name=export_name,
                            local_name=local_name,
                            range=tree_range(import_node),
                            selection_range=tree_range(selection_node),
                        ))

            if names:
                imports.append("from {} import {}".format(module, ", ".join(names)))
            elif module:
                imports.append("from {} import *".format(module))
            return

        if node.data == "assign":
            tree_children = [child for child in node.children if isinstance(child, Tree)]
            if tree_children:
                name_node = simple_name_node(tree_children[0])
                if name_node is not None:
                    add_binding(
                        scope_id,
                        name_node,
                        "variable",
                        node_range=tree_range(tree_children[0]),
                    )
                    for child in tree_children[1:]:
                        visit(child, scope_id)
                    return

        if node.data == "for_stmt":
            tree_children = [child for child in node.children if isinstance(child, Tree)]
            if tree_children:
                name_node = simple_name_node(tree_children[0])
                if name_node is not None:
                    add_binding(
                        scope_id,
                        name_node,
                        "variable",
                        node_range=tree_range(tree_children[0]),
                    )
                    for child in tree_children[1:]:
                        visit(child, scope_id)
                    return

        if node.data == "var":
            name_node = simple_name_node(node)
            if name_node is not None:
                add_reference(scope_id, name_node)
                return

        for child in node.children:
            if isinstance(child, Tree):
                visit(child, scope_id, top_level=node.data == "file_input")

    visit(syntax_tree, 0)

    return DocumentAnalysis(
        uri=uri,
        version=version,
        diagnostics=[],
        symbols=symbols,
        imports=imports,
        import_entries=import_entries,
        exports=exports,
        scopes=scopes,
        bindings=bindings,
        occurrences=occurrences,
    )
