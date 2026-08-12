# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# ordec imports
from .model import AnalysisPosition, AnalysisRange, range_contains


class CallHierarchyMixin:
    """Call hierarchy built on definition and reference analysis.

    ORD cells act as the callables: incoming calls are the places that
    instantiate or otherwise reference a cell, grouped by the enclosing cell
    or function, and outgoing calls are the cells and functions referenced
    inside a definition's body.
    """
    def hierarchy_item_from_definition(self, definition):
        """Convert a resolved definition to a call hierarchy item, or None."""
        if definition is None or definition.get("kind") not in ("class", "function"):
            return None

        return {
            "name": definition["name"],
            "kind": definition["kind"],
            "uri": definition["uri"],
            "range": definition["range"],
            "selection_range": definition["selection_range"],
        }

    def call_hierarchy_item(self, uri: str, position: AnalysisPosition):
        """Return the call hierarchy item for a document position, or None."""
        uri = self.canonical_uri(uri)
        return self.hierarchy_item_from_definition(self.definition(uri, position))

    def module_hierarchy_item(self, uri: str):
        """Return a file-level hierarchy item for module-scope references."""
        analysis = self.analyze(uri)
        if 0 in analysis.scopes:
            full_range = analysis.scopes[0]["range"]
        else:
            full_range = AnalysisRange(
                start=AnalysisPosition(1, 1),
                end=AnalysisPosition(1, 1),
            )

        path = self.file_uri_path(uri)
        name = path.stem if path is not None else uri
        return {
            "name": name,
            "kind": "module",
            "uri": uri,
            "range": full_range,
            "selection_range": AnalysisRange(
                start=full_range.start,
                end=full_range.start,
            ),
        }

    def enclosing_hierarchy_item(self, uri: str, position: AnalysisPosition):
        """Return the innermost cell or function item containing a position."""
        analysis = self.analyze(uri)

        best = None
        for kinds in (("class",), ("function",)):
            for symbol in analysis.symbols:
                if symbol.kind not in kinds:
                    continue
                if not range_contains(symbol.range, position):
                    continue
                if best is None or range_contains(best.range, symbol.range.start):
                    best = symbol
            if best is not None:
                break

        if best is None:
            return self.module_hierarchy_item(uri)

        return {
            "name": best.name,
            "kind": best.kind,
            "uri": uri,
            "range": best.range,
            "selection_range": best.selection_range,
        }

    def hierarchy_group_key(self, item):
        """Return a stable sort and grouping key for a hierarchy item."""
        return (
            item["uri"],
            item["selection_range"].start.line,
            item["selection_range"].start.character,
            item["name"],
        )

    def incoming_calls(self, uri: str, position: AnalysisPosition):
        """Return grouped callers of the definition at a position."""
        uri = self.canonical_uri(uri)
        definition = self.definition(uri, position)
        if self.hierarchy_item_from_definition(definition) is None:
            return []

        calls = dict()
        for reference in self.references(uri, position):
            ref_uri = reference["uri"]
            ref_range = reference["range"]
            if ref_uri == definition["uri"] and ref_range == definition["selection_range"]:
                continue

            item = self.enclosing_hierarchy_item(ref_uri, ref_range.start)
            key = self.hierarchy_group_key(item)
            entry = calls.setdefault(key, {
                "item": item,
                "from_ranges": [],
            })
            entry["from_ranges"].append(ref_range)

        return [calls[key] for key in sorted(calls)]

    def outgoing_calls(self, uri: str, position: AnalysisPosition):
        """Return grouped callees referenced inside the definition at a position."""
        uri = self.canonical_uri(uri)
        definition = self.definition(uri, position)
        if self.hierarchy_item_from_definition(definition) is None:
            return []

        target_uri = definition["uri"]
        if not self.is_ord_uri(target_uri):
            return []

        container_range = definition["range"]
        analysis = self.analyze(target_uri)
        return_type_ranges = {
            viewgen["selection_range"]
            for viewgen in analysis.viewgen_returns
        }

        calls = dict()
        for candidate in self.reference_candidates(target_uri):
            candidate_range = candidate["range"]
            if not range_contains(container_range, candidate_range.start):
                continue

            # Viewgen return types are declarations, not calls.
            if candidate_range in return_type_ranges:
                continue

            callee = self.hierarchy_item_from_definition(
                self.definition(target_uri, candidate_range.start),
            )
            if callee is None:
                continue

            # Definition-site occurrences (the container's own name and any
            # nested cell or function headers) are declarations, not calls.
            if callee["uri"] == target_uri and callee["selection_range"] == candidate_range:
                continue

            key = self.hierarchy_group_key(callee)
            entry = calls.setdefault(key, {
                "item": callee,
                "from_ranges": [],
            })
            entry["from_ranges"].append(candidate_range)

        return [calls[key] for key in sorted(calls)]
