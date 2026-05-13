# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import re

# ordec imports
from .model import AnalysisPosition
from .model import range_contains


class TypeFlowMixin:
    def context_type_names_for_kind(self, kind_name: str):
        if kind_name in ("input", "output", "inout"):
            return ["Pin"]
        if kind_name in ("port", "net"):
            return ["Net"]
        if kind_name == "path":
            return ["PathNode"]

        match = re.match(r"^[A-Za-z_][A-Za-z0-9_]*", kind_name)
        if match is None:
            return []
        return [match.group(0)]

    def context_type_names_at_position(self, uri: str, position: AnalysisPosition):
        analysis = self.analyze(uri)

        best_symbol = None
        for symbol in analysis.symbols:
            if symbol.kind != "context":
                continue
            if not range_contains(symbol.range, position):
                continue
            if best_symbol is None or range_contains(best_symbol.range, symbol.range.start):
                best_symbol = symbol

        if best_symbol is None:
            return []

        kind_name = best_symbol.name.split(" ", 1)[0]
        return self.context_type_names_for_kind(kind_name)

    def resolve_completion_type(self, uri: str, type_name: str):
        type_definition = self.resolve_name(uri, type_name)
        if type_definition is not None:
            return type_definition

        if type_name in (
            "Symbol",
            "Schematic",
            "Layout",
            "SimHierarchy",
            "Pin",
            "Net",
            "PathNode",
            "LayoutRect",
            "LayoutPath",
            "LayoutPoly",
            "LayoutLabel",
            "LayoutPin",
            "SchemInstance",
        ):
            return self.python_definition("ordec.core", export_name=type_name)

        return None

    def type_members(self, type_definition):
        if "python_module" in type_definition and "python_class" in type_definition:
            return self.python_class_members(
                type_definition["python_module"],
                type_definition["python_class"],
            )

        if type_definition.get("kind") == "class" and "uri" in type_definition:
            return self.ord_cell_members(
                type_definition["uri"],
                type_definition["name"],
            )

        return dict()

