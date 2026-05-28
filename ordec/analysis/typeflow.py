# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# ordec imports
from .model import AnalysisPosition, leading_identifier, range_contains


CORE_TYPE_ALIASES = {
    "Simulation": "SimHierarchy",
}


class TypeFlowMixin:
    """Helpers for resolving lightweight ORD and Python type information."""
    def allows_dynamic_members(self, type_name: str):
        """Return whether the named type can expose runtime-defined members."""
        type_definition = self.resolve_core_type(type_name)
        if type_definition is None:
            return False
        return "view_context" in self.type_members(type_definition)

    def resolve_core_type(self, type_name: str):
        """Resolve an ORDeC core type exported by ``ordec.core``."""
        core_type_name = CORE_TYPE_ALIASES.get(type_name, type_name)
        type_definition = self.python_definition("ordec.core", export_name=core_type_name)
        if type_definition is None or type_definition.get("kind") != "class":
            return None
        return type_definition

    def context_type_names_for_kind(self, kind_name: str):
        """Map an ORD context keyword to candidate type names."""
        if kind_name in ("input", "output", "inout"):
            return ["Pin"]
        if kind_name in ("port", "net"):
            return ["Net"]
        if kind_name == "path":
            return ["PathNode"]

        identifier = leading_identifier(kind_name)
        if identifier is None:
            return []
        return [identifier]

    def context_type_names_at_position(self, uri: str, position: AnalysisPosition):
        """Return type names implied by the innermost ORD context at ``position``."""
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
        """Resolve ``type_name`` to an ORD or Python definition, or None."""
        type_definition = self.resolve_name(uri, type_name)
        if type_definition is not None:
            return type_definition

        core_definition = self.resolve_core_type(type_name)
        if core_definition is not None:
            return core_definition

        return None

    def schematic_instance_members(self):
        """Return members common to schematic cell instances."""
        return self.python_class_members("ordec.core.schema", "SchemInstance")

    def type_members(self, type_definition):
        """Return a name→metadata mapping for members of a resolved type."""
        if "python_module" in type_definition and "python_class" in type_definition:
            members = self.python_class_members(
                type_definition["python_module"],
                type_definition["python_class"],
            )
            if self.resolve_core_type(type_definition["python_class"]) is None:
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
