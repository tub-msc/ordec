# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from typing import Optional

from lark import Token, Tree
from lark.exceptions import UnexpectedCharacters, UnexpectedInput, UnexpectedToken
from lark.indenter import DedentError

# ordec imports
from .model import (
    AnalysisDiagnostic,
    AnalysisImport,
    AnalysisPosition,
    AnalysisRange,
    AnalysisSymbol,
    DocumentAnalysis,
    context_type_names_for_kind,
    normalize_line_breaks,
    normalize_type_names,
    trailing_identifier,
)
from ...ord.parser import format_error
from ...ord.parser import parser


def tree_range(node):
    """Return the source range for a Lark token or tree node."""
    if isinstance(node, Token):
        return AnalysisRange(
            start=AnalysisPosition(node.line, node.column),
            end=AnalysisPosition(node.end_line, node.end_column),
        )

    return AnalysisRange(
        start=AnalysisPosition(node.meta.line, node.meta.column),
        end=AnalysisPosition(node.meta.end_line, node.meta.end_column),
    )


def content_end_line(node):
    """Return the last line holding a content-bearing token of a node.

    Parse tree meta end positions include trailing newline and dedent
    bookkeeping that reaches the next statement, so folding and other
    line-precise consumers need the last token that carries actual text.
    """
    if isinstance(node, Token):
        return node.end_line

    best = None
    for token in node.scan_values(lambda value: isinstance(value, Token)):
        if not str(token).strip():
            continue

        end_line = getattr(token, "end_line", None)
        if end_line is None:
            continue
        if best is None or end_line > best:
            best = end_line
    return best


def tree_text(node):
    """Reconstruct compact text for a parse-tree node."""
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


class OrdAnalysisBuilder:
    """Build a DocumentAnalysis from a parsed ORD syntax tree."""
    def __init__(self, syntax_tree, uri: str, version: Optional[int]):
        """Initialize builder state for one parsed document."""
        self.syntax_tree = syntax_tree
        self.uri = uri
        self.version = version
        self.symbols = []
        self.imports = []
        self.import_entries = []
        self.exports = []
        self.scopes = {
            0: {
                "id": 0,
                "parent_id": None,
                "range": tree_range(syntax_tree),
                "selection_range": tree_range(syntax_tree),
                "depth": 0,
                "bindings": [],
            },
        }
        self.scope_bindings = {
            0: dict(),
        }
        self.bindings = []
        self.occurrences = []
        self.member_occurrences = []
        self.viewgen_returns = []
        self.node_statements = []
        self.constraints = []
        self.type_hints = []
        self.view_context_ranges = []

    def simple_name_node(self, node):
        """Return the simple name node represented by a parse-tree node."""
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

    def dotted_name_nodes(self, node):
        """Return the (base, attribute) name nodes of a dotted name chain.

        For a bare name both entries are the name itself. For a chain
        such as ``core.Schematic`` the base is the leftmost name and the
        attribute the rightmost one. Returns None for other expressions.
        """
        name_node = self.simple_name_node(node)
        if name_node is not None:
            return name_node, name_node

        if not isinstance(node, Tree) or node.data != "getattr" or len(node.children) != 2:
            return None

        attribute_node = node.children[1]
        if not isinstance(attribute_node, Tree) or attribute_node.data != "name":
            return None

        inner_nodes = self.dotted_name_nodes(node.children[0])
        if inner_nodes is None:
            return None

        return inner_nodes[0], attribute_node

    def opens_view_context(self, expression_node):
        """Return whether a with-item expression opens an ORDB view context.

        ``with root.view_context(root):`` and ``with node.ctx():`` execute
        their bodies inside a view building context, so constraints and
        node statements are valid there even outside a viewgen. Only a
        call whose callee is the ctx or view_context attribute counts, so
        an argument such as ``open(cfg.ctx)`` does not open a context.
        """
        if not isinstance(expression_node, Tree) or expression_node.data != "funccall":
            return False
        if not expression_node.children:
            return False

        callee_node = expression_node.children[0]
        if not isinstance(callee_node, Tree) or callee_node.data != "getattr":
            return False
        if len(callee_node.children) != 2:
            return False

        return tree_text(callee_node.children[1]) in ("view_context", "ctx")

    def kind_name_node(self, node):
        """Return the name node for a plain or parameterized node kind."""
        name_node = self.simple_name_node(node)
        if name_node is not None:
            return name_node

        if not isinstance(node, Tree) or node.data != "funccall" or not node.children:
            return None

        return self.simple_name_node(node.children[0])

    def visit_kind_expression(self, kind_node, scope_id):
        """Visit node-kind subtrees not covered by the kind occurrence.

        Call arguments in ``Res(r=width) r1:`` and dotted kinds such as
        ``lib.Inv i1:`` contain references that navigation and rename
        must see. The plain kind name itself is skipped because the node
        statement records its occurrence manually.
        """
        if self.simple_name_node(kind_node) is not None:
            return

        if isinstance(kind_node, Tree) and kind_node.data == "funccall" and kind_node.children:
            callee_node = kind_node.children[0]
            if self.simple_name_node(callee_node) is None:
                self.visit(callee_node, scope_id)
            for child in kind_node.children[1:]:
                if isinstance(child, Tree):
                    self.visit(child, scope_id)
            return

        self.visit(kind_node, scope_id)

    def add_scope(self, node, parent_id, name_node=None):
        """Create and register a child lexical scope."""
        scope_id = len(self.scopes)
        self.scopes[scope_id] = {
            "id": scope_id,
            "parent_id": parent_id,
            "range": tree_range(node),
            "selection_range": tree_range(name_node if name_node is not None else node),
            "depth": self.scopes[parent_id]["depth"] + 1,
            "bindings": [],
        }
        self.scope_bindings[scope_id] = dict()
        return scope_id

    def type_names_from_annotation(self, node):
        """Extract candidate type names from an annotation node."""
        if not isinstance(node, Tree):
            return []

        name_node = self.simple_name_node(node)
        if name_node is not None:
            return [tree_text(name_node)]

        if node.data == "getitem" and node.children:
            return self.type_names_from_annotation(node.children[0])

        if node.data == "getattr":
            name = tree_text(node)
            identifier = trailing_identifier(name)
            if identifier is not None:
                return [identifier]

        return []

    def visit_required_expression(self, node, scope_id, context_type_names=None):
        """Visit an expression whose unresolved names should be diagnosed."""
        occurrence_start = len(self.occurrences)
        self.visit(node, scope_id, context_type_names=context_type_names)
        for occurrence in self.occurrences[occurrence_start:]:
            occurrence["diagnose_unresolved"] = True

    def resolve_binding(self, scope_id, name):
        """Resolve a name from a scope through its parent scopes."""
        while scope_id is not None:
            binding_id = self.scope_bindings[scope_id].get(name)
            if binding_id is not None:
                return binding_id
            scope_id = self.scopes[scope_id]["parent_id"]
        return None

    def add_binding(
        self,
        scope_id,
        name_node,
        kind,
        node_range=None,
        exported=False,
        type_names=None,
        fresh=False,
    ):
        """Register a named binding and its defining occurrence."""
        name = tree_text(name_node)
        binding_id = None if fresh else self.scope_bindings[scope_id].get(name)
        type_names = normalize_type_names(type_names)

        if binding_id is None:
            binding_id = len(self.bindings) + 1
            self.bindings.append({
                "id": binding_id,
                "name": name,
                "kind": kind,
                "scope_id": scope_id,
                "range": node_range if node_range is not None else tree_range(name_node),
                "selection_range": tree_range(name_node),
                "exported": exported,
                "type_names": type_names,
            })
            self.scopes[scope_id]["bindings"].append(binding_id)
            self.scope_bindings[scope_id][name] = binding_id
        elif type_names:
            existing_type_names = normalize_type_names(self.bindings[binding_id - 1].get("type_names"))
            self.bindings[binding_id - 1]["type_names"] = normalize_type_names(existing_type_names + type_names)

        self.occurrences.append({
            "name": name,
            "range": tree_range(name_node),
            "scope_id": scope_id,
            "binding_id": binding_id,
        })

        return binding_id

    def add_synthetic_binding(self, scope_id, name, kind, value_range, type_names=None):
        """Register an implicit binding without adding an occurrence."""
        binding_id = self.scope_bindings[scope_id].get(name)
        type_names = normalize_type_names(type_names)

        if binding_id is not None:
            if type_names:
                existing_type_names = normalize_type_names(self.bindings[binding_id - 1].get("type_names"))
                self.bindings[binding_id - 1]["type_names"] = normalize_type_names(existing_type_names + type_names)
            return binding_id

        binding_id = len(self.bindings) + 1
        self.bindings.append({
            "id": binding_id,
            "name": name,
            "kind": kind,
            "scope_id": scope_id,
            "range": value_range,
            "selection_range": value_range,
            "exported": False,
            "type_names": type_names,
        })
        self.scopes[scope_id]["bindings"].append(binding_id)
        self.scope_bindings[scope_id][name] = binding_id
        return binding_id

    def binding_type_names(self, binding_id):
        """Return candidate type names attached to a binding."""
        if binding_id is None:
            return []
        return normalize_type_names(self.bindings[binding_id - 1].get("type_names"))

    def bind_target(
        self,
        scope_id,
        target_node,
        type_names=None,
        context_type_names=None,
        fresh=False,
    ):
        """Bind Python assignment/loop targets, including destructuring."""
        if not isinstance(target_node, Tree):
            return False

        name_node = self.simple_name_node(target_node)
        if name_node is not None:
            self.add_binding(
                scope_id,
                name_node,
                "variable",
                node_range=tree_range(target_node),
                type_names=type_names,
                fresh=fresh,
            )
            return True

        if target_node.data in ("tuple", "parenthesized_tuple", "list", "exprlist", "testlist_tuple"):
            bound_any = False
            for child in target_node.children:
                if not isinstance(child, Tree):
                    continue

                if self.bind_target(
                    scope_id,
                    child,
                    type_names=type_names,
                    context_type_names=context_type_names,
                    fresh=fresh,
                ):
                    bound_any = True
                    continue

                self.visit(child, scope_id, context_type_names=context_type_names)
            return bound_any

        if target_node.data == "star_expr" and target_node.children:
            child = target_node.children[0]
            if isinstance(child, Tree):
                return self.bind_target(
                    scope_id,
                    child,
                    type_names=type_names,
                    context_type_names=context_type_names,
                    fresh=fresh,
                )

        if target_node.data == "getitem" and target_node.children:
            base_node = target_node.children[0]
            if isinstance(base_node, Tree):
                self.visit(
                    base_node,
                    scope_id,
                    context_type_names=context_type_names,
                )
            for index_node in target_node.children[1:]:
                if isinstance(index_node, Tree):
                    self.visit_required_expression(
                        index_node,
                        scope_id,
                        context_type_names=context_type_names,
                    )
            return True

        if target_node.data == "getattr" and target_node.children:
            self.visit(target_node, scope_id, context_type_names=context_type_names)
            return True

        return False

    def bind_node_target(self, scope_id, target_node, type_names=None, context_type_names=None):
        """Bind an ORD node target without treating path segments as members."""
        if not isinstance(target_node, Tree):
            return False

        name_node = self.simple_name_node(target_node)
        if name_node is not None:
            self.add_binding(
                scope_id,
                name_node,
                "variable",
                node_range=tree_range(target_node),
                type_names=type_names,
            )
            return True

        if target_node.data == "getitem" and target_node.children:
            base_node = target_node.children[0]
            if isinstance(base_node, Tree):
                self.bind_node_target(
                    scope_id,
                    base_node,
                    type_names=type_names,
                    context_type_names=context_type_names,
                )
            for index_node in target_node.children[1:]:
                if isinstance(index_node, Tree):
                    self.visit_required_expression(
                        index_node,
                        scope_id,
                        context_type_names=context_type_names,
                    )
            return True

        if target_node.data == "getattr" and target_node.children:
            base_node = target_node.children[0]
            if isinstance(base_node, Tree):
                self.bind_node_target(
                    scope_id,
                    base_node,
                    context_type_names=context_type_names,
                )
            return True

        return False

    def expression_type_names(self, node, scope_id, context_type_names=None):
        """Infer lightweight candidate type names for an expression."""
        if not isinstance(node, Tree):
            return []

        name_node = self.simple_name_node(node)
        if name_node is not None:
            return self.binding_type_names(self.resolve_binding(scope_id, tree_text(name_node)))

        if node.data in ("tuple", "parenthesized_tuple", "list", "testlist_tuple"):
            type_names = []
            for child in node.children:
                if not isinstance(child, Tree):
                    continue
                type_names.extend(self.expression_type_names(child, scope_id, context_type_names=context_type_names))
            return normalize_type_names(type_names)

        if node.data == "funccall" and node.children:
            name_node = self.simple_name_node(node.children[0])
            if name_node is not None:
                name = tree_text(name_node)
                if name[:1].isupper():
                    return [name]

        if node.data == "getitem":
            # The element type is generally unrelated to the container type.
            # Chained expressions such as instances[i].pin retain their root
            # type through expression_root_type_names(), but assignments from
            # dynamic containers must remain unknown without annotations.
            return []

        if node.data == "dotted_atom":
            return normalize_type_names(context_type_names)

        return []

    def expression_root_type_names(self, node, scope_id, context_type_names=None):
        """Infer candidate type names for the root of a chained expression."""
        if not isinstance(node, Tree):
            return []

        if node.data in ("getattr", "getitem") and node.children:
            return self.expression_root_type_names(
                node.children[0],
                scope_id,
                context_type_names=context_type_names,
            )

        return self.expression_type_names(
            node,
            scope_id,
            context_type_names=context_type_names,
        )

    def add_type_hint(self, target_node, type_names):
        """Record an inferred-type hint for a simple assignment target."""
        type_names = normalize_type_names(type_names)
        if not type_names:
            return

        if self.simple_name_node(target_node) is None:
            return

        self.type_hints.append({
            "range": tree_range(target_node),
            "type_names": type_names,
        })

    def add_reference(self, scope_id, name_node):
        """Register a name reference occurrence."""
        name = tree_text(name_node)
        binding_id = self.resolve_binding(scope_id, name)

        self.occurrences.append({
            "name": name,
            "range": tree_range(name_node),
            "scope_id": scope_id,
            "binding_id": binding_id,
        })

    def bind_parameters(self, node, outer_scope_id, function_scope_id):
        """Bind parameters while visiting defaults and annotations outside."""
        if not isinstance(node, Tree):
            return

        if node.data == "name":
            self.add_binding(function_scope_id, node, "parameter")
            return

        if node.data == "typedparam":
            children = [child for child in node.children if isinstance(child, Tree)]
            if not children:
                return

            name_node = children[0]
            annotation_node = children[1] if len(children) > 1 else None
            self.add_binding(
                function_scope_id,
                name_node,
                "parameter",
                type_names=self.type_names_from_annotation(annotation_node),
            )
            if annotation_node is not None:
                self.visit(annotation_node, outer_scope_id)
            return

        if node.data == "paramvalue":
            children = [child for child in node.children if isinstance(child, Tree)]
            if not children:
                return

            self.bind_parameters(children[0], outer_scope_id, function_scope_id)
            for child in children[1:]:
                self.visit(child, outer_scope_id)
            return

        if node.data in (
            "parameters",
            "starparams",
            "starparam",
            "poststarparams",
            "kwparams",
        ):
            for child in node.children:
                self.bind_parameters(child, outer_scope_id, function_scope_id)
            return

        self.visit(node, outer_scope_id)

    def bind_pattern(self, scope_id, pattern_node):
        """Bind names introduced by a match-case pattern."""
        if isinstance(pattern_node, Token):
            return

        if not isinstance(pattern_node, Tree):
            return

        if pattern_node.data in ("capture_pattern", "star_pattern"):
            if pattern_node.children:
                self.add_binding(scope_id, pattern_node.children[0], "variable")
            return

        if pattern_node.data == "as_pattern":
            for child in pattern_node.children:
                if isinstance(child, Token):
                    self.add_binding(scope_id, child, "variable")
                else:
                    self.bind_pattern(scope_id, child)
            return

        if pattern_node.data == "mapping_star_pattern":
            for child in pattern_node.children:
                if isinstance(child, Token):
                    self.add_binding(scope_id, child, "variable")
                else:
                    self.bind_pattern(scope_id, child)
            return

        if pattern_node.data == "keyw_arg_pattern":
            for child in pattern_node.children[1:]:
                self.bind_pattern(scope_id, child)
            return

        for child in pattern_node.children:
            self.bind_pattern(scope_id, child)

    def bind_lambda_parameters(self, node, outer_scope_id, lambda_scope_id):
        """Bind lambda parameters while visiting defaults in the outer scope."""
        if not isinstance(node, Tree):
            return

        if node.data == "lambda_paramvalue":
            name_node = None
            for child in node.children:
                if not isinstance(child, Tree):
                    continue
                if name_node is None and child.data == "name":
                    name_node = child
                    self.add_binding(lambda_scope_id, child, "parameter")
                    continue
                self.visit(child, outer_scope_id)
            return

        if node.data not in (
            "lambda_params",
            "lambda_starparams",
            "lambda_kwparams",
        ):
            self.visit(node, outer_scope_id)
            return

        for child in node.children:
            if not isinstance(child, Tree):
                continue
            if child.data == "name":
                self.add_binding(lambda_scope_id, child, "parameter")
                continue
            self.bind_lambda_parameters(child, outer_scope_id, lambda_scope_id)

    def visit_with_item(self, node, scope_id, statement_node, context_type_names=None):
        """Visit one with-item and bind its optional target."""
        children = [child for child in node.children if isinstance(child, Tree)]
        if not children:
            return

        expression_node = children[0]
        if self.opens_view_context(expression_node):
            context_range = tree_range(statement_node)
            if context_range not in self.view_context_ranges:
                self.view_context_ranges.append(context_range)
        self.visit(expression_node, scope_id, context_type_names=context_type_names)
        for target_node in children[1:]:
            if self.bind_target(
                scope_id,
                target_node,
                context_type_names=context_type_names,
            ):
                continue
            self.visit(target_node, scope_id, context_type_names=context_type_names)

    def visit_with_items(self, node, scope_id, statement_node, context_type_names=None):
        """Visit a parenthesized or plain collection of with-items."""
        container_names = {
            "with_items",
            "with_paren_mixed_items",
            "with_paren_single_as_item",
            "with_paren_single_item",
        }
        for child in node.children:
            if not isinstance(child, Tree):
                continue
            if child.data == "with_item":
                self.visit_with_item(
                    child,
                    scope_id,
                    statement_node,
                    context_type_names=context_type_names,
                )
                continue
            if child.data in container_names:
                self.visit_with_items(
                    child,
                    scope_id,
                    statement_node,
                    context_type_names=context_type_names,
                )
                continue
            self.visit(child, scope_id, context_type_names=context_type_names)

    def visit_comprehension(self, node, scope_id, context_type_names=None):
        """Visit a comprehension using an isolated comprehension scope."""
        comprehension_node = None
        for child in node.children:
            if isinstance(child, Tree) and child.data == "comprehension":
                comprehension_node = child
                break

        if comprehension_node is None or not comprehension_node.children:
            for child in node.children:
                if isinstance(child, Tree):
                    self.visit(child, scope_id, context_type_names=context_type_names)
            return

        comp_scope_id = self.add_scope(node, scope_id)
        result_node = comprehension_node.children[0]
        post_for_nodes = []

        for child in comprehension_node.children[1:]:
            if not isinstance(child, Tree):
                continue

            # `comp_for` trees sit directly under `comprehension` in the
            # grammar, one per `for` clause.
            if child.data != "comp_for":
                post_for_nodes.append(child)
                continue

            tree_children = [
                comp_child for comp_child in child.children
                if isinstance(comp_child, Tree)
            ]
            if len(tree_children) < 2:
                for comp_child in tree_children:
                    self.visit(comp_child, comp_scope_id, context_type_names=context_type_names)
                continue

            target_node = tree_children[0]
            iterable_node = tree_children[1]
            self.visit(iterable_node, comp_scope_id, context_type_names=context_type_names)
            if not self.bind_target(
                comp_scope_id,
                target_node,
                context_type_names=context_type_names,
            ):
                self.visit(target_node, comp_scope_id, context_type_names=context_type_names)

            for extra_node in tree_children[2:]:
                self.visit(extra_node, comp_scope_id, context_type_names=context_type_names)

        for post_for_node in post_for_nodes:
            self.visit(post_for_node, comp_scope_id, context_type_names=context_type_names)

        self.visit(result_node, comp_scope_id, context_type_names=context_type_names)

    def visit(self, node, scope_id, top_level=False, context_type_names=None):
        """Visit a parse tree node and collect analysis records."""
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
                self.symbols.append(AnalysisSymbol(
                    name=name,
                    kind=kind,
                    range=tree_range(node),
                    selection_range=tree_range(name_node),
                    content_end_line=content_end_line(node),
                ))
                self.add_binding(
                    scope_id,
                    name_node,
                    kind,
                    node_range=tree_range(node),
                    exported=top_level,
                )
                if top_level:
                    self.exports.append(name)
                if node.data == "viewgen":
                    for child in node.children:
                        if not isinstance(child, Tree) or child.data in ("name", "suite"):
                            continue
                        # A dotted return type such as core.Schematic
                        # records the rightmost name as the type and
                        # resolves the leftmost name as its binding.
                        return_nodes = self.dotted_name_nodes(child)
                        if return_nodes is not None:
                            base_node, type_node = return_nodes
                            self.viewgen_returns.append({
                                "name": name,
                                "return_type": tree_text(type_node),
                                "return_base": tree_text(base_node),
                                "return_binding_id": self.resolve_binding(
                                    scope_id,
                                    tree_text(base_node),
                                ),
                                "range": tree_range(node),
                                "selection_range": tree_range(child),
                                "viewgen_range": tree_range(node),
                            })
                        break
                child_scope_id = self.add_scope(node, scope_id, name_node=name_node)
                if node.data == "celldef":
                    self.add_synthetic_binding(
                        child_scope_id,
                        "self",
                        "variable",
                        tree_range(name_node),
                        type_names=[name],
                    )
                for child in node.children:
                    if not isinstance(child, Tree) or child is name_node:
                        continue

                    if node.data == "funcdef":
                        if child.data == "parameters":
                            self.bind_parameters(child, scope_id, child_scope_id)
                            continue
                        if child.data != "suite":
                            self.visit(child, scope_id, context_type_names=context_type_names)
                            continue

                    self.visit(child, child_scope_id, context_type_names=context_type_names)
                return

        if node.data in ("node_stmt", "anon_node_stmt") and len(node.children) >= 2:
            kind_node = node.children[0]
            target_node = node.children[1]
            if isinstance(kind_node, Tree) and isinstance(target_node, Tree):
                kind_name_node = self.kind_name_node(kind_node)
                kind_name = tree_text(
                    kind_name_node if kind_name_node is not None else kind_node
                )
                context_type_names = context_type_names_for_kind(kind_name)
                kind_binding_id = None
                if kind_name_node is not None:
                    kind_binding_id = self.resolve_binding(scope_id, tree_text(kind_name_node))
                self.node_statements.append({
                    "kind_name": kind_name,
                    "kind_range": tree_range(
                        kind_name_node if kind_name_node is not None else kind_node
                    ),
                    "kind_binding_id": kind_binding_id,
                    "target_name": tree_text(target_node),
                    "target_range": tree_range(target_node),
                    "range": tree_range(node),
                })
                if kind_name_node is not None:
                    # Record the node kind as a reference occurrence so that
                    # references, rename, and call hierarchy see cell
                    # instantiation sites.
                    self.occurrences.append({
                        "name": kind_name,
                        "range": tree_range(kind_name_node),
                        "scope_id": scope_id,
                        "binding_id": kind_binding_id,
                    })

                self.symbols.append(AnalysisSymbol(
                    name="{} {}".format(kind_name, tree_text(target_node)),
                    kind="context",
                    range=tree_range(node),
                    selection_range=tree_range(target_node),
                    content_end_line=content_end_line(node),
                ))
                self.visit_kind_expression(kind_node, scope_id)
                name_node = self.simple_name_node(target_node)
                if name_node is not None:
                    self.add_binding(
                        scope_id,
                        name_node,
                        "variable",
                        node_range=tree_range(target_node),
                        type_names=context_type_names,
                    )
                else:
                    if not self.bind_node_target(
                        scope_id,
                        target_node,
                        type_names=context_type_names,
                        context_type_names=context_type_names,
                    ):
                        self.visit(target_node, scope_id, context_type_names=context_type_names)

            for child in node.children[2:]:
                if isinstance(child, Tree):
                    self.visit(child, scope_id, context_type_names=context_type_names)
            return

        if node.data in ("node_stmt_nobody", "anon_node_stmt_nobody") and len(node.children) >= 2:
            kind_node = node.children[0]
            if isinstance(kind_node, Tree):
                kind_name_node = self.kind_name_node(kind_node)
                kind_name = tree_text(
                    kind_name_node if kind_name_node is not None else kind_node
                )
                context_type_names = context_type_names_for_kind(kind_name)
                kind_binding_id = None
                if kind_name_node is not None:
                    kind_binding_id = self.resolve_binding(scope_id, tree_text(kind_name_node))
                    # Same as node_stmt: expose the node kind as a reference
                    # occurrence for references, rename, and call hierarchy.
                    self.occurrences.append({
                        "name": kind_name,
                        "range": tree_range(kind_name_node),
                        "scope_id": scope_id,
                        "binding_id": kind_binding_id,
                    })
                self.visit_kind_expression(kind_node, scope_id)

                for target_node in node.children[1:]:
                    if not isinstance(target_node, Tree):
                        continue

                    self.node_statements.append({
                        "kind_name": kind_name,
                        "kind_range": tree_range(
                            kind_name_node if kind_name_node is not None else kind_node
                        ),
                        "kind_binding_id": kind_binding_id,
                        "target_name": tree_text(target_node),
                        "target_range": tree_range(target_node),
                        "range": tree_range(node),
                    })
                    self.symbols.append(AnalysisSymbol(
                        name="{} {}".format(kind_name, tree_text(target_node)),
                        kind="context",
                        range=tree_range(node),
                        selection_range=tree_range(target_node),
                        content_end_line=content_end_line(node),
                    ))

                    name_node = self.simple_name_node(target_node)
                    if name_node is not None:
                        self.add_binding(
                            scope_id,
                            name_node,
                            "variable",
                            node_range=tree_range(target_node),
                            type_names=context_type_names,
                        )
                    else:
                        self.bind_node_target(
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
                if not isinstance(child, Tree):
                    continue

                if selection_node is None:
                    selection_node = child
                names.append(tree_text(child))
                # Each declared name is its own node statement record, so cell
                # member collection sees multi-name declarations too.
                self.node_statements.append({
                    "kind_name": node.data[:-5],
                    "kind_range": tree_range(node),
                    "kind_binding_id": None,
                    "target_name": tree_text(child),
                    "target_range": tree_range(child),
                    "range": tree_range(node),
                })

                name_node = self.simple_name_node(child)
                if name_node is not None:
                    self.add_binding(
                        scope_id,
                        name_node,
                        "variable",
                        node_range=tree_range(child),
                        type_names=type_names,
                    )
                else:
                    self.bind_node_target(
                        scope_id,
                        child,
                        type_names=type_names,
                        context_type_names=type_names,
                    )
            if names and selection_node is not None:
                self.symbols.append(AnalysisSymbol(
                    name=", ".join(names),
                    kind=node.data[:-5],
                    range=tree_range(node),
                    selection_range=tree_range(selection_node),
                    content_end_line=content_end_line(node),
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
                        self.imports.append("{} as {}".format(parts[0], parts[1]))
                    elif parts:
                        self.imports.append(parts[0])

                    if not value_nodes:
                        continue

                    module_name = tree_text(value_nodes[0])
                    local_name = module_name.split(".", 1)[0]
                    selection_node = value_nodes[0]
                    if len(value_nodes) == 2:
                        local_name = tree_text(value_nodes[1])
                        selection_node = value_nodes[1]

                    self.import_entries.append(AnalysisImport(
                        kind="import",
                        module=module_name,
                        export_name=None,
                        local_name=local_name,
                        range=tree_range(import_node),
                        selection_range=tree_range(selection_node),
                        is_alias=len(value_nodes) == 2,
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

                        self.import_entries.append(AnalysisImport(
                            kind="from",
                            module=module,
                            export_name=export_name,
                            local_name=local_name,
                            range=tree_range(import_node),
                            selection_range=tree_range(selection_node),
                            is_alias=len(value_nodes) == 2,
                            export_range=tree_range(value_nodes[0]),
                        ))

            if names:
                self.imports.append("from {} import {}".format(module, ", ".join(names)))
            elif module:
                self.imports.append("from {} import *".format(module))
                self.import_entries.append(AnalysisImport(
                    kind="from",
                    module=module,
                    export_name="*",
                    local_name="*",
                    range=tree_range(node),
                    selection_range=tree_range(selection_node if selection_node is not None else node),
                    is_alias=False,
                ))
            return

        if node.data == "assign":
            tree_children = [child for child in node.children if isinstance(child, Tree)]
            if tree_children:
                targets = tree_children[:-1]
                value_node = tree_children[-1]
                value_type_names = self.expression_type_names(
                    value_node,
                    scope_id,
                    context_type_names=context_type_names,
                )

                for target_node in targets:
                    if self.bind_target(
                        scope_id,
                        target_node,
                        type_names=value_type_names,
                        context_type_names=context_type_names,
                    ):
                        self.add_type_hint(target_node, value_type_names)
                        continue

                    self.visit(target_node, scope_id, context_type_names=context_type_names)

                self.visit(value_node, scope_id, context_type_names=context_type_names)
                return

        if node.data == "annassign":
            tree_children = [child for child in node.children if isinstance(child, Tree)]
            if len(tree_children) >= 2:
                target_node = tree_children[0]
                annotation_node = tree_children[1]
                value_node = tree_children[2] if len(tree_children) > 2 else None
                type_names = self.type_names_from_annotation(annotation_node)
                if value_node is not None:
                    type_names.extend(self.expression_type_names(
                        value_node,
                        scope_id,
                        context_type_names=context_type_names,
                    ))
                type_names = normalize_type_names(type_names)

                if not self.bind_target(
                    scope_id,
                    target_node,
                    type_names=type_names,
                    context_type_names=context_type_names,
                ):
                    self.visit(target_node, scope_id, context_type_names=context_type_names)

                self.visit(annotation_node, scope_id, context_type_names=context_type_names)
                if value_node is not None:
                    self.visit(value_node, scope_id, context_type_names=context_type_names)
                return

        if node.data == "for_stmt":
            tree_children = [child for child in node.children if isinstance(child, Tree)]
            if tree_children:
                iterable_type_names = []
                if len(tree_children) > 1:
                    iterable_type_names = self.expression_type_names(
                        tree_children[1],
                        scope_id,
                        context_type_names=context_type_names,
                    )

                if self.bind_target(
                    scope_id,
                    tree_children[0],
                    type_names=iterable_type_names,
                    context_type_names=context_type_names,
                    fresh=True,
                ):
                    for child in tree_children[1:]:
                        self.visit(child, scope_id, context_type_names=context_type_names)
                    return

        if node.data in (
            "list_comprehension",
            "tuple_comprehension",
            "dict_comprehension",
            "set_comprehension",
        ):
            self.visit_comprehension(node, scope_id, context_type_names=context_type_names)
            return

        if node.data in ("lambdef", "lambdef_nocond"):
            lambda_scope_id = self.add_scope(node, scope_id)
            for child in node.children:
                if not isinstance(child, Tree):
                    continue
                if child.data == "lambda_params":
                    self.bind_lambda_parameters(child, scope_id, lambda_scope_id)
                    continue
                self.visit(child, lambda_scope_id, context_type_names=context_type_names)
            return

        if node.data == "assign_expr" and len(node.children) >= 2:
            name_node = node.children[0]
            value_node = node.children[1]
            type_names = self.expression_type_names(
                value_node,
                scope_id,
                context_type_names=context_type_names,
            )
            self.add_binding(scope_id, name_node, "variable", type_names=type_names)
            self.add_type_hint(name_node, type_names)
            self.visit(value_node, scope_id, context_type_names=context_type_names)
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
                self.bind_pattern(scope_id, pattern_node)
            for child in remaining_children:
                self.visit(child, scope_id, context_type_names=context_type_names)
            return

        if node.data == "with_stmt":
            container_names = {
                "with_items",
                "with_paren_mixed_items",
                "with_paren_single_as_item",
                "with_paren_single_item",
            }
            for child in node.children:
                if not isinstance(child, Tree):
                    continue
                if child.data in container_names:
                    self.visit_with_items(
                        child,
                        scope_id,
                        node,
                        context_type_names=context_type_names,
                    )
                    continue
                self.visit(child, scope_id, context_type_names=context_type_names)
            return

        if node.data in (
            "with_parenthesized_expr_as",
            "with_parenthesized_items_as",
        ):
            children = [child for child in node.children if isinstance(child, Tree)]
            if len(children) < 2:
                for child in children:
                    self.visit(child, scope_id, context_type_names=context_type_names)
                return

            expression_node = children[0]
            if node.data == "with_parenthesized_expr_as":
                if self.opens_view_context(expression_node):
                    self.view_context_ranges.append(tree_range(node))
                self.visit(expression_node, scope_id, context_type_names=context_type_names)
            else:
                self.visit_with_items(
                    expression_node,
                    scope_id,
                    node,
                    context_type_names=context_type_names,
                )

            target_node = children[1]
            if not self.bind_target(
                scope_id,
                target_node,
                context_type_names=context_type_names,
            ):
                self.visit(target_node, scope_id, context_type_names=context_type_names)
            for child in children[2:]:
                self.visit(child, scope_id, context_type_names=context_type_names)
            return

        if node.data in ("except_clause", "except_star_clause"):
            tree_children = [child for child in node.children if isinstance(child, Tree)]
            if tree_children and tree_children[0].data != "suite":
                self.visit(tree_children[0], scope_id, context_type_names=context_type_names)
                tree_children = tree_children[1:]

            for child in tree_children:
                if child.data == "name":
                    self.add_binding(scope_id, child, "variable")
                    continue
                self.visit(child, scope_id, context_type_names=context_type_names)
            return

        if node.data == "constrain_stmt":
            self.constraints.append({
                "range": tree_range(node),
            })
            for child in node.children:
                if isinstance(child, Tree):
                    self.visit(child, scope_id, context_type_names=context_type_names)
            return

        if node.data == "getattr" and len(node.children) == 2:
            base_node = node.children[0]
            name_node = node.children[1]
            if isinstance(base_node, Tree) and base_node.data == "dotted_atom":
                self.visit(base_node, scope_id, context_type_names=context_type_names)
                return

            binding_id = None
            base_name_node = self.simple_name_node(base_node)
            if base_name_node is not None:
                binding_id = self.resolve_binding(scope_id, tree_text(base_name_node))
            type_names = self.expression_type_names(
                base_node,
                scope_id,
                context_type_names=context_type_names,
            )
            if not type_names and isinstance(base_node, Tree) and base_node.data == "getitem":
                # ORD node arrays are homogeneous, so `I[i].q` keeps the
                # root binding's type. Attribute chains change type and
                # stay unknown without deeper inference.
                type_names = self.expression_root_type_names(
                    base_node,
                    scope_id,
                    context_type_names=context_type_names,
                )

            self.member_occurrences.append({
                "name": tree_text(name_node),
                "range": tree_range(name_node),
                "scope_id": scope_id,
                "binding_id": binding_id,
                "type_names": normalize_type_names(type_names),
                "mode": "member",
            })
            self.visit(base_node, scope_id, context_type_names=context_type_names)
            return

        if node.data == "getparam":
            name_node = node.children[-1]
            binding_id = None
            type_names = normalize_type_names(context_type_names)
            if len(node.children) == 2:
                base_node = node.children[0]
                base_name_node = self.simple_name_node(base_node)
                if base_name_node is not None:
                    binding_id = self.resolve_binding(scope_id, tree_text(base_name_node))
                type_names.extend(self.expression_root_type_names(
                    base_node,
                    scope_id,
                    context_type_names=context_type_names,
                ))
                self.visit(base_node, scope_id, context_type_names=context_type_names)

            self.member_occurrences.append({
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
            self.member_occurrences.append({
                "name": tree_text(name_node),
                "range": tree_range(name_node),
                "scope_id": scope_id,
                "binding_id": None,
                "type_names": normalize_type_names(context_type_names),
                "mode": "member",
            })
            return

        if node.data == "var":
            name_node = self.simple_name_node(node)
            if name_node is not None:
                self.add_reference(scope_id, name_node)
                return

        for child in node.children:
            if isinstance(child, Tree):
                self.visit(
                    child,
                    scope_id,
                    # A decorated definition sits under a `decorated`
                    # wrapper, but stays a top-level export.
                    top_level=node.data == "file_input"
                    or (top_level and node.data == "decorated"),
                    context_type_names=context_type_names,
                )

    def build(self):
        """Walk the syntax tree and return the completed document analysis."""
        self.visit(self.syntax_tree, 0)

        return DocumentAnalysis(
            uri=self.uri,
            version=self.version,
            diagnostics=[],
            symbols=self.symbols,
            imports=self.imports,
            import_entries=self.import_entries,
            exports=self.exports,
            scopes=self.scopes,
            bindings=self.bindings,
            occurrences=self.occurrences,
            member_occurrences=self.member_occurrences,
            viewgen_returns=self.viewgen_returns,
            node_statements=self.node_statements,
            constraints=self.constraints,
            type_hints=self.type_hints,
            view_context_ranges=self.view_context_ranges,
        )


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

    try:
        syntax_tree = parser.parse(normalize_line_breaks(source_data) + "\n")
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
    except DedentError as exc:
        # lark's indenter reports inconsistent dedents outside the
        # UnexpectedInput hierarchy and without position attributes, so
        # the diagnostic anchors at the document start.
        diagnostic = AnalysisDiagnostic(
            range=AnalysisRange(
                start=AnalysisPosition(1, 1),
                end=AnalysisPosition(1, 1),
            ),
            severity="error",
            message="Syntax Error: {}".format(exc),
            code="inconsistent-dedent",
        )
        return DocumentAnalysis(uri=uri, version=version, diagnostics=[diagnostic], symbols=[])

    return OrdAnalysisBuilder(syntax_tree, uri, version).build()
