# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import builtins

# ordec imports
from .model import (
    NODE_KINDS,
    PIN_KINDS,
    AnalysisDiagnostic,
    is_identifier,
    range_contains,
)


class DiagnosticsMixin:
    """Semantic diagnostics derived from parsed ORD analysis data."""
    def semantic_diagnostics(self, uri: str):
        """Return semantic diagnostics for a document.

        Covers unresolved imports, invalid ORD contexts, unsupported constraints,
        and unknown members.
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

        def name_resolves(name):
            if hasattr(builtins, name):
                return True
            return self.resolve_name(uri, name) is not None

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
            if export_name == "*":
                if not module_exists(module_name):
                    add_diagnostic(
                        import_entry.selection_range,
                        "error",
                        "Cannot resolve import module `{}`.".format(module_name),
                        "unresolved-import",
                    )
                continue

            if self.resolve_from_import(uri, module_name, export_name) is not None:
                continue

            module_uri = self.resolve_module_uri(uri, module_name)
            if module_uri is None and not module_exists(module_name):
                add_diagnostic(
                    import_entry.selection_range,
                    "error",
                    "Cannot resolve import module `{}`.".format(module_name),
                    "unresolved-import",
                )
                continue

            python_module_name = self.resolve_python_import_name(uri, module_name)
            if module_uri is None and self.python_module_info(python_module_name) is None:
                continue

            add_diagnostic(
                import_entry.selection_range,
                "error",
                "Cannot resolve `{}` from `{}`.".format(export_name, module_name),
                "unresolved-import-member",
            )

        for statement in analysis.node_statements:
            kind_name = statement["kind_name"]
            if kind_name in NODE_KINDS:
                continue
            if statement.get("kind_binding_id") is not None:
                continue
            if not is_identifier(kind_name):
                continue
            if self.resolve_completion_type(uri, kind_name) is None:
                add_diagnostic(
                    statement["kind_range"],
                    "error",
                    "Cannot resolve ORD node type `{}`.".format(kind_name),
                    "unresolved-node-type",
                )

        for viewgen in analysis.viewgen_returns:
            type_name = viewgen["return_type"]
            if viewgen.get("return_binding_id") is not None:
                continue
            if viewgen.get("return_base") not in (None, type_name):
                # Qualified return types such as core.Schematic resolve
                # through their module, which the bare-name lookup below
                # cannot see. Only the base name is validated here.
                if not name_resolves(viewgen["return_base"]):
                    add_diagnostic(
                        viewgen["selection_range"],
                        "error",
                        "Cannot resolve `{}` in viewgen return type.".format(
                            viewgen["return_base"]
                        ),
                        "unresolved-viewgen-return",
                    )
                continue
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

        for occurrence in analysis.occurrences:
            if occurrence.get("binding_id") is not None:
                continue
            if not occurrence.get("diagnose_unresolved"):
                continue
            if name_resolves(occurrence["name"]):
                continue

            add_diagnostic(
                occurrence["range"],
                "error",
                "Cannot resolve name `{}`.".format(occurrence["name"]),
                "unresolved-name",
            )

        for constraint in analysis.constraints:
            containing_viewgen = None
            for viewgen in analysis.viewgen_returns:
                if not range_contains(viewgen["viewgen_range"], constraint["range"].start):
                    continue
                containing_viewgen = viewgen
                break

            if containing_viewgen is None and any(
                range_contains(context_range, constraint["range"].start)
                for context_range in analysis.view_context_ranges
            ):
                # `with x.view_context(...):` blocks build views outside a
                # viewgen, so constraints are valid there.
                continue

            if (
                containing_viewgen is None
                or containing_viewgen["return_type"] not in ("Schematic", "Layout")
            ):
                add_diagnostic(
                    constraint["range"],
                    "error",
                    "Constraints are only supported inside schematic or layout view generators.",
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

            parameter_only = occurrence.get("mode") == "parameter"
            if not parameter_only and any(
                viewgen["return_type"] == "Layout"
                and range_contains(viewgen["viewgen_range"], occurrence["range"].start)
                for viewgen in analysis.viewgen_returns
            ):
                # Layout generators commonly delegate to helper functions that
                # attach runtime-defined shapes to cell instances. Keep member
                # navigation when statically known, but do not report unknown
                # members in this inherently dynamic context.
                continue

            resolved_any = False
            matched = False
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

            # Node statements are recorded per target, so multi-name
            # declarations such as `input a, b` contribute every name
            # even though their outline symbol is combined.
            symbol_pins = set()
            schematic_ports = []
            for statement in analysis.node_statements:
                target_name = statement["target_name"]
                if not is_identifier(target_name):
                    continue

                kind_name = statement["kind_name"]
                target_start = statement["target_range"].start
                if kind_name in PIN_KINDS and range_contains(symbol_view.range, target_start):
                    symbol_pins.add(target_name)
                elif kind_name == "port" and range_contains(schematic_view.range, target_start):
                    schematic_ports.append(statement)

            for port_statement in schematic_ports:
                port_name = port_statement["target_name"]
                if port_name not in symbol_pins:
                    add_diagnostic(
                        port_statement["target_range"],
                        "error",
                        "Schematic port `{}` is not declared in the symbol view.".format(port_name),
                        "unknown-symbol-port",
                        data={
                            "portName": port_name,
                        },
                    )

        return diagnostics
