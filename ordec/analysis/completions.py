# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import re

# ordec imports
from .model import AnalysisPosition


class CompletionsMixin:
    def completion_context(self, uri: str, position: AnalysisPosition):
        lines = self.documents[uri]["text"].splitlines()
        if position.line < 1 or position.line > len(lines):
            return None

        line = lines[position.line - 1]
        cursor = max(0, min(position.character - 1, len(line)))

        prefix_start = cursor
        while (
            prefix_start > 0
            and (
                line[prefix_start - 1].isalnum()
                or line[prefix_start - 1] == "_"
            )
        ):
            prefix_start -= 1

        prefix = line[prefix_start:cursor]
        before_prefix = line[:prefix_start]

        if before_prefix.endswith(".$"):
            return {
                "mode": "parameter",
                "prefix": prefix,
                "base": self.completion_subject(before_prefix[:-2]),
            }

        if before_prefix.endswith("."):
            return {
                "mode": "member",
                "prefix": prefix,
                "base": self.completion_subject(before_prefix[:-1]),
            }

        return None

    def completion_subject(self, text: str):
        text = text.rstrip()
        if text == "":
            return None

        match = re.search(
            r"(?:\.?[A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]+\]|\.[A-Za-z_][A-Za-z0-9_]*)*$",
            text,
        )
        if match is None or match.end() != len(text):
            return None
        return match.group(0)

    def completion_type_names(self, uri: str, position: AnalysisPosition, context):
        base_name = context["base"]
        if base_name is None:
            return self.context_type_names_at_position(uri, position)

        if base_name.startswith("."):
            return self.context_type_names_at_position(uri, position)

        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", base_name)
        if match is not None:
            base_name = match.group(0)

        for binding in self.visible_bindings(uri, position):
            if binding["name"] == base_name:
                return self.normalize_type_names(binding.get("type_names"))

        return []

    def completion_sort_key(self, item, prefix=None):
        kind_rank = {
            "parameter": 0,
            "variable": 1,
            "function": 2,
            "class": 3,
            "module": 4,
            "keyword": 5,
        }.get(item["kind"], 9)
        label = item["label"]
        prefix_rank = 0
        if prefix:
            prefix_rank = 0 if label.startswith(prefix) else 1
        return (prefix_rank, kind_rank, label.lower(), label)

    def member_completion_items(self, uri: str, position: AnalysisPosition, context):
        items = dict()
        prefix = context.get("prefix") or ""

        for type_name in self.completion_type_names(uri, position, context):
            type_definition = self.resolve_completion_type(uri, type_name)
            if type_definition is None:
                continue

            for name, member in self.type_members(type_definition).items():
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name) is None:
                    continue
                if prefix and not name.startswith(prefix):
                    continue
                if context["mode"] == "parameter" and member["kind"] != "parameter":
                    continue
                items.setdefault(name, {
                    "label": name,
                    "kind": member["kind"],
                    "detail": "{} of {}".format(member["kind"], type_name),
                })

        return items

    def completions(self, uri: str, position: AnalysisPosition):
        if not self.ensure_document(uri):
            return []

        analysis = self.analyze(uri)
        items = dict()

        context = self.completion_context(uri, position)
        if context is not None:
            items.update(self.member_completion_items(uri, position, context))
            if items:
                return [
                    items[label]
                    for label in sorted(
                        items,
                        key=lambda item_label: self.completion_sort_key(items[item_label], context.get("prefix")),
                    )
                ]

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

