# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""Call hierarchy built on definition and reference analysis.

ORD cells act as the callables: incoming calls are the places that
instantiate or otherwise reference a cell, grouped by the enclosing cell
or function, and outgoing calls are the cells and functions referenced
inside a definition's body.
"""

# ordec imports
from .model import AnalysisDefinition, AnalysisPosition, AnalysisRange, range_contains


def hierarchy_item_from_definition(definition):
    """Convert a resolved definition to a call hierarchy item, or None."""
    if definition is None or definition.kind not in ("class", "function"):
        return None

    return AnalysisDefinition(
        uri=definition.uri,
        name=definition.name,
        kind=definition.kind,
        range=definition.range,
        selection_range=definition.selection_range,
    )


def call_hierarchy_item(session, uri: str, position: AnalysisPosition):
    """Return the call hierarchy item for a document position, or None."""
    uri = session.canonical_uri(uri)
    return hierarchy_item_from_definition(session.definition(uri, position))


def module_hierarchy_item(session, uri: str):
    """Return a file-level hierarchy item for module-scope references."""
    analysis = session.analyze(uri)
    if 0 in analysis.scopes:
        full_range = analysis.scopes[0]["range"]
    else:
        full_range = AnalysisRange(
            start=AnalysisPosition(1, 1),
            end=AnalysisPosition(1, 1),
        )

    path = session.file_uri_path(uri)
    name = path.stem if path is not None else uri
    return AnalysisDefinition(
        uri=uri,
        name=name,
        kind="module",
        range=full_range,
        selection_range=AnalysisRange(
            start=full_range.start,
            end=full_range.start,
        ),
    )


def enclosing_hierarchy_item(session, uri: str, position: AnalysisPosition):
    """Return the innermost cell or function item containing a position."""
    analysis = session.analyze(uri)

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
        return module_hierarchy_item(session, uri)

    return AnalysisDefinition(
        uri=uri,
        name=best.name,
        kind=best.kind,
        range=best.range,
        selection_range=best.selection_range,
    )


def hierarchy_group_key(item):
    """Return a stable sort and grouping key for a hierarchy item."""
    return (
        item.uri,
        item.selection_range.start.line,
        item.selection_range.start.character,
        item.name,
    )


def incoming_calls(session, uri: str, position: AnalysisPosition):
    """Return grouped callers of the definition at a position."""
    uri = session.canonical_uri(uri)
    definition = session.definition(uri, position)
    if hierarchy_item_from_definition(definition) is None:
        return []

    calls = dict()
    for reference in session.references(uri, position):
        ref_uri = reference["uri"]
        ref_range = reference["range"]
        if ref_uri == definition.uri and ref_range == definition.selection_range:
            continue

        item = enclosing_hierarchy_item(session, ref_uri, ref_range.start)
        key = hierarchy_group_key(item)
        entry = calls.setdefault(key, {
            "item": item,
            "from_ranges": [],
        })
        entry["from_ranges"].append(ref_range)

    return [calls[key] for key in sorted(calls)]


def outgoing_calls(session, uri: str, position: AnalysisPosition):
    """Return grouped callees referenced inside the definition at a position."""
    uri = session.canonical_uri(uri)
    definition = session.definition(uri, position)
    if hierarchy_item_from_definition(definition) is None:
        return []

    target_uri = definition.uri
    if not session.is_ord_uri(target_uri):
        return []

    container_range = definition.range
    analysis = session.analyze(target_uri)
    return_type_ranges = {
        viewgen["selection_range"]
        for viewgen in analysis.viewgen_returns
    }

    calls = dict()
    for candidate in session.reference_candidates(target_uri):
        candidate_range = candidate["range"]
        if not range_contains(container_range, candidate_range.start):
            continue

        # Viewgen return types are declarations, not calls.
        if candidate_range in return_type_ranges:
            continue

        callee = hierarchy_item_from_definition(
            session.definition(target_uri, candidate_range.start),
        )
        if callee is None:
            continue

        # Definition-site occurrences (the container's own name and any
        # nested cell or function headers) are declarations, not calls.
        if callee.uri == target_uri and callee.selection_range == candidate_range:
            continue

        key = hierarchy_group_key(callee)
        entry = calls.setdefault(key, {
            "item": callee,
            "from_ranges": [],
        })
        entry["from_ranges"].append(candidate_range)

    return [calls[key] for key in sorted(calls)]
