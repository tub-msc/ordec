# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import re

# ordec imports
from .model import AnalysisPosition
from .model import range_contains


SCHEMA_TYPE_NAMES = {
    "Symbol",
    "Schematic",
    "Layout",
    "SimHierarchy",
    "Simulation",
    "Pin",
    "Net",
    "PathNode",
    "LayoutRect",
    "LayoutPath",
    "LayoutPoly",
    "LayoutLabel",
    "LayoutPin",
    "SchemInstance",
}


class TypeFlowMixin:
    """Helpers for resolving lightweight ORD and Python type information."""

    def context_type_names_for_kind(self, kind_name: str):
        """Map an ORD context keyword to candidate type names.

        Args:
            kind_name: Context keyword or user-defined context type.

        Returns:
            Candidate type names usable for member completion and diagnostics.
        """
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
        """Return type names implied by the ORD context at a position.

        Args:
            uri: Document URI to inspect.
            position: One-based analysis position.

        Returns:
            Candidate type names for the innermost matching context.
        """
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
        """Resolve a type name to an ORD or Python definition.

        Args:
            uri: Document URI that provides local import context.
            type_name: Type name to resolve.

        Returns:
            Definition dictionary, or None when the type cannot be resolved.
        """
        type_definition = self.resolve_name(uri, type_name)
        if type_definition is not None:
            return type_definition

        if type_name == "Simulation":
            return self.python_definition("ordec.core", export_name="SimHierarchy")

        if type_name in SCHEMA_TYPE_NAMES:
            return self.python_definition("ordec.core", export_name=type_name)

        return None

    def schematic_instance_members(self):
        """Return members common to schematic cell instances."""
        return self.python_class_members("ordec.core.schema", "SchemInstance")

    def type_members(self, type_definition):
        """Collect members available on a resolved type definition.

        Args:
            type_definition: Definition dictionary from the analysis session.

        Returns:
            Mapping of member names to member metadata.
        """
        if "python_module" in type_definition and "python_class" in type_definition:
            members = self.python_class_members(
                type_definition["python_module"],
                type_definition["python_class"],
            )
            if type_definition["python_class"] not in SCHEMA_TYPE_NAMES:
                members = dict(members)
                members.update(self.schematic_instance_members())
            return members

        if type_definition.get("kind") == "class" and "uri" in type_definition:
            members = self.ord_cell_members(
                type_definition["uri"],
                type_definition["name"],
            )
            members = dict(members)
            members.update(self.schematic_instance_members())
            return members

        return dict()
