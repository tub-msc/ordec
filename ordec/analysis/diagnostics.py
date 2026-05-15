# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# ordec imports
from .model import AnalysisDiagnostic, is_identifier, range_contains


class DiagnosticsMixin:
    """Semantic diagnostics derived from parsed ORD analysis data."""

    def semantic_diagnostics(self, uri: str):
        """Return semantic diagnostics for a document.

        Args:
            uri: Document URI to analyze.

        Returns:
            List of ``AnalysisDiagnostic`` objects for unresolved imports,
            invalid ORD contexts, unsupported constraints, and unknown members.
        """
        analysis = self.analyze(uri)
        diagnostics = []
        seen = set()

        def add_diagnostic(value_range, severity, message, code, data=None):
            key = (
                code,
                value_range.start.line,
                value_range.start.character,
                value_range.end.line,
                value_range.end.character,
            )
            if key in seen:
                return
            seen.add(key)
            diagnostics.append(AnalysisDiagnostic(
                range=value_range,
                severity=severity,
                message=message,
                code=code,
                data=data,
            ))

        def module_exists(module_name):
            if module_name is None:
                return False
            python_module_name = self.resolve_python_import_name(uri, module_name)
            return (
                self.module_definition(uri, module_name) is not None
                or self.python_module_exists(python_module_name)
            )

        for import_entry in analysis.import_entries:
            if import_entry.kind == "import":
                if not module_exists(import_entry.module):
                    add_diagnostic(
                        import_entry.selection_range,
                        "error",
                        "Cannot resolve import `{}`.".format(import_entry.module),
                        "unresolved-import",
                    )
                continue

            export_name = import_entry.export_name
            module_name = import_entry.module

            if export_name not in (None, "*") and module_name and set(module_name) == {"."}:
                if self.resolve_module_uri(uri, module_name + export_name) is not None:
                    continue

            module_uri = self.resolve_module_uri(uri, module_name)
            if module_uri is None:
                if not module_exists(module_name):
                    add_diagnostic(
                        import_entry.selection_range,
                        "error",
                        "Cannot resolve import module `{}`.".format(module_name),
                        "unresolved-import",
                    )
                    continue

                if export_name not in (None, "*"):
                    python_module_name = self.resolve_python_import_name(uri, module_name)
                    match = self.python_definition(python_module_name, export_name=export_name)
                    module_info = self.python_module_info(python_module_name)
                    if module_info is not None and match is None:
                        add_diagnostic(
                            import_entry.selection_range,
                            "error",
                            "Cannot resolve `{}` from `{}`.".format(export_name, module_name),
                            "unresolved-import-member",
                        )
                continue

            if export_name in (None, "*"):
                continue

            if self.find_export(module_uri, export_name) is None:
                add_diagnostic(
                    import_entry.selection_range,
                    "error",
                    "Cannot resolve `{}` from `{}`.".format(export_name, module_name),
                    "unresolved-import-member",
                )

        built_in_contexts = {
            "input",
            "output",
            "inout",
            "port",
            "net",
            "path",
        }
        for context in analysis.node_contexts:
            kind_name = context["kind_name"]
            if kind_name in built_in_contexts:
                continue
            if context.get("kind_binding_id") is not None:
                continue
            if not is_identifier(kind_name):
                continue
            if self.resolve_completion_type(uri, kind_name) is None:
                add_diagnostic(
                    context["kind_range"],
                    "error",
                    "Cannot resolve ORD node type `{}`.".format(kind_name),
                    "unresolved-node-type",
                )

        for viewgen in analysis.viewgen_returns:
            type_name = viewgen["return_type"]
            type_definition = self.resolve_completion_type(uri, type_name)
            if type_definition is None:
                add_diagnostic(
                    viewgen["selection_range"],
                    "error",
                    "Cannot resolve viewgen return type `{}`.".format(type_name),
                    "unresolved-viewgen-return",
                )
                continue

            members = self.type_members(type_definition)
            if "view_context" not in members:
                add_diagnostic(
                    viewgen["selection_range"],
                    "error",
                    "`{}` cannot be used as an ORD viewgen return type.".format(type_name),
                    "invalid-viewgen-return",
                )

        for constraint in analysis.constraints:
            containing_viewgen = None
            for viewgen in analysis.viewgen_returns:
                if not range_contains(viewgen["viewgen_range"], constraint["range"].start):
                    continue
                containing_viewgen = viewgen
                break

            if containing_viewgen is None:
                add_diagnostic(
                    constraint["range"],
                    "error",
                    "Constraints are only supported inside layout view generators.",
                    "invalid-constraint-context",
                )
                continue

            if containing_viewgen["return_type"] not in ("Layout",):
                add_diagnostic(
                    constraint["range"],
                    "error",
                    "Constraints are only supported inside layout view generators.",
                    "invalid-constraint-context",
                )

        for occurrence in analysis.member_occurrences:
            type_names = list(occurrence.get("type_names", []))
            binding_id = occurrence.get("binding_id")
            if binding_id is not None:
                binding = analysis.binding_map.get(binding_id)
                if binding is not None:
                    type_names = list(binding.get("type_names", [])) + type_names
            type_names = self.normalize_type_names(type_names)
            if not type_names:
                continue

            resolved_any = False
            matched = False
            parameter_only = occurrence.get("mode") == "parameter"
            for type_name in type_names:
                type_definition = self.resolve_completion_type(uri, type_name)
                if type_definition is None:
                    continue

                if type_definition.get("kind") != "class" and "python_class" not in type_definition:
                    continue

                resolved_any = True

                if not parameter_only and self.allows_dynamic_members(type_name):
                    matched = True
                    break

                member = self.type_members(type_definition).get(occurrence["name"])
                if member is None:
                    continue
                if parameter_only and member["kind"] != "parameter":
                    continue
                matched = True
                break

            if not resolved_any or matched:
                continue

            diagnostic_type = "parameter" if parameter_only else "member"
            add_diagnostic(
                occurrence["range"],
                "error",
                "Unknown {} `{}` for `{}`.".format(
                    diagnostic_type,
                    occurrence["name"],
                    " | ".join(type_names),
                ),
                "unknown-{}".format(diagnostic_type),
            )

        for cell in [symbol for symbol in analysis.symbols if symbol.kind == "class"]:
            cell_viewgens = [
                symbol for symbol in analysis.symbols
                if symbol.kind == "function"
                and range_contains(cell.range, symbol.selection_range.start)
            ]
            symbol_view = next((symbol for symbol in cell_viewgens if symbol.name == "symbol"), None)
            schematic_view = next((symbol for symbol in cell_viewgens if symbol.name == "schematic"), None)
            if symbol_view is None or schematic_view is None:
                continue

            symbol_pins = set()
            schematic_ports = []
            for symbol in analysis.symbols:
                if symbol.kind != "context":
                    continue

                parts = symbol.name.split(" ", 1)
                if len(parts) != 2:
                    continue
                kind_name, target_name = parts
                if not is_identifier(target_name):
                    continue

                if kind_name in ("input", "output", "inout") and range_contains(symbol_view.range, symbol.selection_range.start):
                    symbol_pins.add(target_name)
                elif kind_name == "port" and range_contains(schematic_view.range, symbol.selection_range.start):
                    schematic_ports.append(symbol)

            for port_symbol in schematic_ports:
                port_name = port_symbol.name.split(" ", 1)[1]
                if port_name not in symbol_pins:
                    add_diagnostic(
                        port_symbol.selection_range,
                        "error",
                        "Schematic port `{}` is not declared in the symbol view.".format(port_name),
                        "unknown-symbol-port",
                        data={
                            "portName": port_name,
                        },
                    )

        return diagnostics
