2# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from typing import Optional

from lark import Token, Tree
from lark.exceptions import UnexpectedCharacters, UnexpectedInput, UnexpectedToken

# ordec imports
from .model import (
    AnalysisDiagnostic,
    AnalysisImport,
    AnalysisPosition,
    AnalysisRange,
    AnalysisSymbol,
    DocumentAnalysis,
    leading_identifier,
    trailing_identifier,
)
from ..ord.parser import format_error
from ..ord.parser import parser


def analyze_ord(source_data: str, uri: str = "", version: Optional[int] = None):
    """Parse ORD source and collect syntax-aware analysis data.

    Args:
        source_data: ORD source text to parse.
        uri: Optional document URI associated with the source.
        version: Optional LSP document version associated with the source.

    Returns:
        ``DocumentAnalysis`` containing diagnostics, symbols, scopes,
        bindings, occurrences, imports, and ORD-specific semantic records.
    """

    def tree_range(node):
        if isinstance(node, Token):
            return AnalysisRange(
                start=AnalysisPosition(node.line, node.column),
                end=AnalysisPosition(node.end_line, node.end_column),
            )

        return AnalysisRange(
            start=AnalysisPosition(node.meta.line, node.meta.column),
            end=AnalysisPosition(node.meta.end_line, node.meta.end_column),
        )

    def tree_text(node):
        if isinstance(node, Token):
            return node.value

        if node.data == "dotted_name":
            return ".".join(
                tree_text(child)
                for child in node.children
            )

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
    member_occurrences = []
    viewgen_returns = []
    node_contexts = []
    constraints = []

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

    def normalize_type_names(type_names):
        if not type_names:
            return []

        seen = set()
        result = []
        for type_name in type_names:
            if not type_name or type_name in seen:
                continue
            seen.add(type_name)
            result.append(type_name)
        return result

    def context_type_names_for_kind(kind_name):
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

    def type_names_from_annotation(node):
        if not isinstance(node, Tree):
            return []

        name_node = simple_name_node(node)
        if name_node is not None:
            return [tree_text(name_node)]

        if node.data == "getitem" and node.children:
            return type_names_from_annotation(node.children[0])

        if node.data == "getattr":
            name = tree_text(node)
            identifier = trailing_identifier(name)
            if identifier is not None:
                return [identifier]

        return []

    def resolve_binding(scope_id, name):
        while scope_id is not None:
            binding_id = scope_bindings[scope_id].get(name)
            if binding_id is not None:
                return binding_id
            scope_id = scopes[scope_id]["parent_id"]
        return None

    def add_binding(scope_id, name_node, kind, node_range=None, exported=False, type_names=None):
        name = tree_text(name_node)
        binding_id = scope_bindings[scope_id].get(name)
        type_names = normalize_type_names(type_names)

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
                "type_names": type_names,
            })
            scopes[scope_id]["bindings"].append(binding_id)
            scope_bindings[scope_id][name] = binding_id
        elif type_names:
            existing_type_names = normalize_type_names(bindings[binding_id - 1].get("type_names"))
            bindings[binding_id - 1]["type_names"] = normalize_type_names(existing_type_names + type_names)

        occurrences.append({
            "name": name,
            "range": tree_range(name_node),
            "scope_id": scope_id,
            "binding_id": binding_id,
        })

        return binding_id

    def add_synthetic_binding(scope_id, name, kind, value_range, type_names=None):
        binding_id = scope_bindings[scope_id].get(name)
        type_names = normalize_type_names(type_names)

        if binding_id is not None:
            if type_names:
                existing_type_names = normalize_type_names(bindings[binding_id - 1].get("type_names"))
                bindings[binding_id - 1]["type_names"] = normalize_type_names(existing_type_names + type_names)
            return binding_id

        binding_id = len(bindings) + 1
        bindings.append({
            "id": binding_id,
            "name": name,
            "kind": kind,
            "scope_id": scope_id,
            "range": value_range,
            "selection_range": value_range,
            "exported": False,
            "type_names": type_names,
        })
        scopes[scope_id]["bindings"].append(binding_id)
        scope_bindings[scope_id][name] = binding_id
        return binding_id

    def binding_type_names(binding_id):
        if binding_id is None:
            return []
        return normalize_type_names(bindings[binding_id - 1].get("type_names"))

    def bind_target(scope_id, target_node, type_names=None, context_type_names=None):
        """Bind Python assignment/loop targets, including destructuring."""
        if not isinstance(target_node, Tree):
            return False

        name_node = simple_name_node(target_node)
        if name_node is not None:
            add_binding(
                scope_id,
                name_node,
                "variable",
                node_range=tree_range(target_node),
                type_names=type_names,
            )
            return True

        if target_node.data in ("tuple", "list", "exprlist", "testlist_tuple"):
            bound_any = False
            for child in target_node.children:
                if not isinstance(child, Tree):
                    continue

                if bind_target(
                    scope_id,
                    child,
                    type_names=type_names,
                    context_type_names=context_type_names,
                ):
                    bound_any = True
                    continue

                visit(child, scope_id, context_type_names=context_type_names)
            return bound_any

        if target_node.data == "star_expr" and target_node.children:
            child = target_node.children[0]
            if isinstance(child, Tree):
                return bind_target(
                    scope_id,
                    child,
                    type_names=type_names,
                    context_type_names=context_type_names,
                )

        if target_node.data == "getitem" and target_node.children:
            base_node = target_node.children[0]
            if isinstance(base_node, Tree):
                return bind_target(
                    scope_id,
                    base_node,
                    type_names=type_names,
                    context_type_names=context_type_names,
                )

        return False

    def bind_node_target(scope_id, target_node, type_names=None, context_type_names=None):
        """Bind an ORD node target without treating path segments as members."""
        if not isinstance(target_node, Tree):
            return False

        name_node = simple_name_node(target_node)
        if name_node is not None:
            add_binding(
                scope_id,
                name_node,
                "variable",
                node_range=tree_range(target_node),
                type_names=type_names,
            )
            return True

        if target_node.data == "getitem" and target_node.children:
            base_node = target_node.children[0]
            if isinstance(base_node, Tree) and simple_name_node(base_node) is not None:
                bind_node_target(
                    scope_id,
                    base_node,
                    type_names=type_names,
                    context_type_names=context_type_names,
                )
            for index_node in target_node.children[1:]:
                if isinstance(index_node, Tree):
                    visit(index_node, scope_id, context_type_names=context_type_names)
            return True

        if target_node.data == "getattr" and target_node.children:
            base_node = target_node.children[0]
            if isinstance(base_node, Tree):
                bind_node_target(
                    scope_id,
                    base_node,
                    context_type_names=context_type_names,
                )
            return True

        return False

    def expression_type_names(node, scope_id, context_type_names=None):
        if not isinstance(node, Tree):
            return []

        name_node = simple_name_node(node)
        if name_node is not None:
            return binding_type_names(resolve_binding(scope_id, tree_text(name_node)))

        if node.data in ("tuple", "list", "testlist_tuple"):
            type_names = []
            for child in node.children:
                if not isinstance(child, Tree):
                    continue
                type_names.extend(expression_type_names(child, scope_id, context_type_names=context_type_names))
            return normalize_type_names(type_names)

        if node.data == "funccall" and node.children:
            name_node = simple_name_node(node.children[0])
            if name_node is not None:
                name = tree_text(name_node)
                if name[:1].isupper():
                    return [name]

        if node.data == "getitem" and node.children:
            return expression_type_names(
                node.children[0],
                scope_id,
                context_type_names=context_type_names,
            )

        if node.data == "dotted_atom":
            return normalize_type_names(context_type_names)

        return []

    def expression_root_type_names(node, scope_id, context_type_names=None):
        if not isinstance(node, Tree):
            return []

        if node.data in ("getattr", "getitem") and node.children:
            return expression_root_type_names(
                node.children[0],
                scope_id,
                context_type_names=context_type_names,
            )

        return expression_type_names(
            node,
            scope_id,
            context_type_names=context_type_names,
        )

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

            if child.data == "typedparam":
                name_node = None
                annotation_node = None
                for value_node in child.children:
                    if not isinstance(value_node, Tree):
                        continue
                    if name_node is None and value_node.data == "name":
                        name_node = value_node
                    elif annotation_node is None:
                        annotation_node = value_node

                type_names = type_names_from_annotation(annotation_node)
                if name_node is not None:
                    add_binding(scope_id, name_node, "parameter", type_names=type_names)
                if annotation_node is not None:
                    visit(annotation_node, scope_id)
                continue

            if child.data != "paramvalue":
                visit(child, scope_id)
                continue

            name_node = None
            annotation_node = None
            for value_node in child.children:
                if not isinstance(value_node, Tree):
                    continue

                if value_node.data == "typedparam":
                    for typed_child in value_node.children:
                        if not isinstance(typed_child, Tree):
                            continue
                        if name_node is None and typed_child.data == "name":
                            name_node = typed_child
                        elif annotation_node is None:
                            annotation_node = typed_child
                    type_names = type_names_from_annotation(annotation_node)
                    if name_node is not None:
                        add_binding(scope_id, name_node, "parameter", type_names=type_names)
                    if annotation_node is not None:
                        visit(annotation_node, scope_id)
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

    def bind_pattern(scope_id, pattern_node):
        if isinstance(pattern_node, Token):
            return

        if not isinstance(pattern_node, Tree):
            return

        if pattern_node.data in ("capture_pattern", "star_pattern"):
            if pattern_node.children:
                add_binding(scope_id, pattern_node.children[0], "variable")
            return

        if pattern_node.data == "as_pattern":
            for child in pattern_node.children:
                if isinstance(child, Token):
                    add_binding(scope_id, child, "variable")
                else:
                    bind_pattern(scope_id, child)
            return

        if pattern_node.data == "mapping_star_pattern":
            for child in pattern_node.children:
                if isinstance(child, Token):
                    add_binding(scope_id, child, "variable")
                else:
                    bind_pattern(scope_id, child)
            return

        if pattern_node.data == "keyw_arg_pattern":
            for child in pattern_node.children[1:]:
                bind_pattern(scope_id, child)
            return

        for child in pattern_node.children:
            bind_pattern(scope_id, child)

    def visit_comprehension(node, scope_id, context_type_names=None):
        comprehension_node = None
        for child in node.children:
            if isinstance(child, Tree) and child.data == "comprehension":
                comprehension_node = child
                break

        if comprehension_node is None or not comprehension_node.children:
            for child in node.children:
                if isinstance(child, Tree):
                    visit(child, scope_id, context_type_names=context_type_names)
            return

        comp_scope_id = add_scope(node, scope_id)
        result_node = comprehension_node.children[0]
        post_for_nodes = []

        for child in comprehension_node.children[1:]:
            if not isinstance(child, Tree):
                continue

            if child.data != "comp_fors":
                post_for_nodes.append(child)
                continue

            for comp_for in child.children:
                if not isinstance(comp_for, Tree) or comp_for.data != "comp_for":
                    continue

                tree_children = [
                    comp_child for comp_child in comp_for.children
                    if isinstance(comp_child, Tree)
                ]
                if len(tree_children) < 2:
                    for comp_child in tree_children:
                        visit(comp_child, comp_scope_id, context_type_names=context_type_names)
                    continue

                target_node = tree_children[0]
                iterable_node = tree_children[1]
                visit(iterable_node, comp_scope_id, context_type_names=context_type_names)
                if not bind_target(
                    comp_scope_id,
                    target_node,
                    context_type_names=context_type_names,
                ):
                    visit(target_node, comp_scope_id, context_type_names=context_type_names)

                for extra_node in tree_children[2:]:
                    visit(extra_node, comp_scope_id, context_type_names=context_type_names)

        for post_for_node in post_for_nodes:
            visit(post_for_node, comp_scope_id, context_type_names=context_type_names)

        visit(result_node, comp_scope_id, context_type_names=context_type_names)

    def visit(node, scope_id, top_level=False, context_type_names=None):
        if not isinstance(node, Tree):
            return

        if node.data in ("celldef", "viewgen", "funcdef", "classdef"):
            name_node = None
            name_nodes = []
            for child in node.children:
                if isinstance(child, Tree) and child.data == "name":
                    name_nodes.append(child)
            if name_nodes:
                name_node = name_nodes[0]
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
                if node.data == "viewgen" and len(name_nodes) > 1:
                    return_type_node = name_nodes[1]
                    viewgen_returns.append({
                        "name": name,
                        "return_type": tree_text(return_type_node),
                        "range": tree_range(node),
                        "selection_range": tree_range(return_type_node),
                        "viewgen_range": tree_range(node),
                    })
                child_scope_id = add_scope(node, scope_id, name_node=name_node)
                if node.data == "celldef":
                    add_synthetic_binding(
                        child_scope_id,
                        "self",
                        "variable",
                        tree_range(name_node),
                        type_names=[name],
                    )
                for child in node.children:
                    if not isinstance(child, Tree) or child is name_node:
                        continue

                    if node.data == "funcdef" and child.data == "parameters":
                        bind_parameters(child, child_scope_id)
                        continue

                    visit(child, child_scope_id, context_type_names=context_type_names)
                return

        if node.data in ("node_stmt", "anon_node_stmt") and len(node.children) >= 2:
            kind_node = node.children[0]
            target_node = node.children[1]
            if isinstance(kind_node, Tree) and isinstance(target_node, Tree):
                kind_name = tree_text(kind_node)
                context_type_names = context_type_names_for_kind(kind_name)
                kind_binding_id = None
                kind_name_node = simple_name_node(kind_node)
                if kind_name_node is not None:
                    kind_binding_id = resolve_binding(scope_id, tree_text(kind_name_node))
                node_contexts.append({
                    "kind_name": kind_name,
                    "kind_range": tree_range(kind_node),
                    "kind_binding_id": kind_binding_id,
                    "target_name": tree_text(target_node),
                    "target_range": tree_range(target_node),
                    "range": tree_range(node),
                })

                symbols.append(AnalysisSymbol(
                    name="{} {}".format(tree_text(kind_node), tree_text(target_node)),
                    kind="context",
                    range=tree_range(node),
                    selection_range=tree_range(target_node),
                ))
                name_node = simple_name_node(target_node)
                if name_node is not None:
                    add_binding(
                        scope_id,
                        name_node,
                        "variable",
                        node_range=tree_range(target_node),
                        type_names=context_type_names,
                    )
                else:
                    if not bind_node_target(
                        scope_id,
                        target_node,
                        type_names=context_type_names,
                        context_type_names=context_type_names,
                    ):
                        visit(target_node, scope_id, context_type_names=context_type_names)

            for child in node.children[2:]:
                if isinstance(child, Tree):
                    visit(child, scope_id, context_type_names=context_type_names)
            return

        if node.data in ("node_stmt_nobody", "anon_node_stmt_nobody") and len(node.children) >= 2:
            kind_node = node.children[0]
            if isinstance(kind_node, Tree):
                kind_name = tree_text(kind_node)
                context_type_names = context_type_names_for_kind(kind_name)
                kind_binding_id = None
                kind_name_node = simple_name_node(kind_node)
                if kind_name_node is not None:
                    kind_binding_id = resolve_binding(scope_id, tree_text(kind_name_node))

                for target_node in node.children[1:]:
                    if not isinstance(target_node, Tree):
                        continue

                    node_contexts.append({
                        "kind_name": kind_name,
                        "kind_range": tree_range(kind_node),
                        "kind_binding_id": kind_binding_id,
                        "target_name": tree_text(target_node),
                        "target_range": tree_range(target_node),
                        "range": tree_range(node),
                    })
                    symbols.append(AnalysisSymbol(
                        name="{} {}".format(kind_name, tree_text(target_node)),
                        kind="context",
                        range=tree_range(node),
                        selection_range=tree_range(target_node),
                    ))

                    name_node = simple_name_node(target_node)
                    if name_node is not None:
                        add_binding(
                            scope_id,
                            name_node,
                            "variable",
                            node_range=tree_range(target_node),
                            type_names=context_type_names,
                        )
                    else:
                        bind_node_target(
                            scope_id,
                            target_node,
                            type_names=context_type_names,
                            context_type_names=context_type_names,
                        )
            return

        if node.data in ("path_stmt", "net_stmt"):
            names = []
            selection_node = None
            type_names = ["Net"] if node.data == "net_stmt" else ["PathNode"]
            for child in node.children:
                if isinstance(child, Tree) and child.data == "var":
                    if selection_node is None:
                        selection_node = child
                    names.append(tree_text(child))
                    name_node = simple_name_node(child)
                    if name_node is not None:
                        add_binding(
                            scope_id,
                            name_node,
                            "variable",
                            node_range=tree_range(child),
                            type_names=type_names,
                        )
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
            selection_node = None
            for child in node.children:
                if not isinstance(child, Tree):
                    continue

                if child.data == "dots":
                    module = tree_text(child) + module
                    if selection_node is None:
                        selection_node = child
                elif child.data == "dotted_name":
                    module = module + tree_text(child)
                    selection_node = child
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
                import_entries.append(AnalysisImport(
                    kind="from",
                    module=module,
                    export_name="*",
                    local_name="*",
                    range=tree_range(node),
                    selection_range=tree_range(selection_node if selection_node is not None else node),
                ))
            return

        if node.data == "assign":
            tree_children = [child for child in node.children if isinstance(child, Tree)]
            if tree_children:
                targets = tree_children[:-1]
                value_node = tree_children[-1]
                value_type_names = expression_type_names(
                    value_node,
                    scope_id,
                    context_type_names=context_type_names,
                )

                for target_node in targets:
                    if bind_target(
                        scope_id,
                        target_node,
                        type_names=value_type_names,
                        context_type_names=context_type_names,
                    ):
                        continue

                    visit(target_node, scope_id, context_type_names=context_type_names)

                visit(value_node, scope_id, context_type_names=context_type_names)
                return

        if node.data == "annassign":
            tree_children = [child for child in node.children if isinstance(child, Tree)]
            if len(tree_children) >= 2:
                target_node = tree_children[0]
                annotation_node = tree_children[1]
                value_node = tree_children[2] if len(tree_children) > 2 else None
                type_names = type_names_from_annotation(annotation_node)
                if value_node is not None:
                    type_names.extend(expression_type_names(
                        value_node,
                        scope_id,
                        context_type_names=context_type_names,
                    ))
                type_names = normalize_type_names(type_names)

                if not bind_target(
                    scope_id,
                    target_node,
                    type_names=type_names,
                    context_type_names=context_type_names,
                ):
                    visit(target_node, scope_id, context_type_names=context_type_names)

                visit(annotation_node, scope_id, context_type_names=context_type_names)
                if value_node is not None:
                    visit(value_node, scope_id, context_type_names=context_type_names)
                return

        if node.data == "for_stmt":
            tree_children = [child for child in node.children if isinstance(child, Tree)]
            if tree_children:
                iterable_type_names = []
                if len(tree_children) > 1:
                    iterable_type_names = expression_type_names(
                        tree_children[1],
                        scope_id,
                        context_type_names=context_type_names,
                    )

                if bind_target(
                    scope_id,
                    tree_children[0],
                    type_names=iterable_type_names,
                    context_type_names=context_type_names,
                ):
                    for child in tree_children[1:]:
                        visit(child, scope_id, context_type_names=context_type_names)
                    return

        if node.data in (
            "list_comprehension",
            "tuple_comprehension",
            "dict_comprehension",
            "set_comprehension",
        ):
            visit_comprehension(node, scope_id, context_type_names=context_type_names)
            return

        if node.data == "assign_expr" and len(node.children) >= 2:
            name_node = node.children[0]
            value_node = node.children[1]
            type_names = expression_type_names(
                value_node,
                scope_id,
                context_type_names=context_type_names,
            )
            add_binding(scope_id, name_node, "variable", type_names=type_names)
            visit(value_node, scope_id, context_type_names=context_type_names)
            return

        if node.data == "case" and node.children:
            pattern_node = None
            remaining_children = []
            for child in node.children:
                if not isinstance(child, Tree):
                    continue
                if pattern_node is None:
                    pattern_node = child
                    continue
                remaining_children.append(child)

            if pattern_node is not None:
                bind_pattern(scope_id, pattern_node)
            for child in remaining_children:
                visit(child, scope_id, context_type_names=context_type_names)
            return

        if node.data == "with_stmt":
            for child in node.children:
                if not isinstance(child, Tree):
                    continue

                if child.data != "with_items":
                    visit(child, scope_id, context_type_names=context_type_names)
                    continue

                for item_node in child.children:
                    if not isinstance(item_node, Tree) or item_node.data != "with_item":
                        continue

                    item_children = [
                        item_child for item_child in item_node.children
                        if isinstance(item_child, Tree)
                    ]
                    if not item_children:
                        continue

                    visit(item_children[0], scope_id, context_type_names=context_type_names)
                    for target_node in item_children[1:]:
                        if bind_target(
                            scope_id,
                            target_node,
                            context_type_names=context_type_names,
                        ):
                            continue
                        visit(target_node, scope_id, context_type_names=context_type_names)
            return

        if node.data == "except_clause":
            tree_children = [child for child in node.children if isinstance(child, Tree)]
            if tree_children and tree_children[0].data != "suite":
                visit(tree_children[0], scope_id, context_type_names=context_type_names)
                tree_children = tree_children[1:]

            for child in tree_children:
                if child.data == "name":
                    add_binding(scope_id, child, "variable")
                    continue
                visit(child, scope_id, context_type_names=context_type_names)
            return

        if node.data == "constrain_stmt":
            constraints.append({
                "range": tree_range(node),
            })
            for child in node.children:
                if isinstance(child, Tree):
                    visit(child, scope_id, context_type_names=context_type_names)
            return

        if node.data == "getattr" and len(node.children) == 2:
            base_node = node.children[0]
            name_node = node.children[1]
            if isinstance(base_node, Tree) and base_node.data == "dotted_atom":
                visit(base_node, scope_id, context_type_names=context_type_names)
                return

            binding_id = None
            base_name_node = simple_name_node(base_node)
            if base_name_node is not None:
                binding_id = resolve_binding(scope_id, tree_text(base_name_node))
            type_names = expression_type_names(
                base_node,
                scope_id,
                context_type_names=context_type_names,
            )

            member_occurrences.append({
                "name": tree_text(name_node),
                "range": tree_range(name_node),
                "scope_id": scope_id,
                "binding_id": binding_id,
                "type_names": normalize_type_names(type_names),
                "mode": "member",
            })
            visit(base_node, scope_id, context_type_names=context_type_names)
            return

        if node.data == "getparam":
            name_node = node.children[-1]
            binding_id = None
            type_names = normalize_type_names(context_type_names)
            if len(node.children) == 2:
                base_node = node.children[0]
                base_name_node = simple_name_node(base_node)
                if base_name_node is not None:
                    binding_id = resolve_binding(scope_id, tree_text(base_name_node))
                type_names.extend(expression_root_type_names(
                    base_node,
                    scope_id,
                    context_type_names=context_type_names,
                ))
                visit(base_node, scope_id, context_type_names=context_type_names)

            member_occurrences.append({
                "name": tree_text(name_node),
                "range": tree_range(name_node),
                "scope_id": scope_id,
                "binding_id": binding_id,
                "type_names": normalize_type_names(type_names),
                "mode": "parameter",
            })
            return

        if node.data == "dotted_atom" and len(node.children) == 1:
            name_node = node.children[0]
            member_occurrences.append({
                "name": tree_text(name_node),
                "range": tree_range(name_node),
                "scope_id": scope_id,
                "binding_id": None,
                "type_names": normalize_type_names(context_type_names),
                "mode": "member",
            })
            return

        if node.data == "var":
            name_node = simple_name_node(node)
            if name_node is not None:
                add_reference(scope_id, name_node)
                return

        for child in node.children:
            if isinstance(child, Tree):
                visit(
                    child,
                    scope_id,
                    top_level=node.data == "file_input",
                    context_type_names=context_type_names,
                )

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
        member_occurrences=member_occurrences,
        viewgen_returns=viewgen_returns,
        node_contexts=node_contexts,
        constraints=constraints,
    )
