# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from lark import Transformer
import ast

class MatchCaseTransformer(Transformer):

    def __init__(self):
        pass

    def case(self, nodes):
        pattern = nodes[0]
        if len(nodes) > 2:
            # pattern if xy
            test = nodes[1]
            suite = nodes[2]
        else:
            # pattern
            test = None
            suite = nodes[1]

        if not isinstance(suite, list):
            suite = [suite]

        return ast.match_case(
            pattern=pattern,
            guard=test,
            body=suite
        )

    def capture_pattern(self, nodes):
        return ast.MatchAs(name=nodes[0])

    def any_pattern(self, nodes):
        # "_" wildcard
        return ast.MatchAs(name=None)

    def value(self, nodes):
        # nodes = list of names, ["a", "b", "c"] -> a.b.c
        node = ast.Name(id=nodes[0], ctx=ast.Load())
        for attr in nodes[1:]:
            node = ast.Attribute(value=node, attr=attr, ctx=ast.Load())
        return node

    def attr_pattern(self, nodes):
        return self.value(nodes)

    def name_or_attr_pattern(self, nodes):
        return self.value(nodes)

    def as_pattern(self, nodes):
        pattern = nodes[0]
        if len(nodes) > 1 and nodes[1]:
            return ast.MatchAs(pattern=pattern, name=nodes[1])
        return pattern

    def or_pattern(self, nodes):
        if len(nodes) == 1:
            return nodes[0]
        return ast.MatchOr(patterns=nodes)

    def star_pattern(self, nodes):
        return ast.MatchStar(name=nodes[0])

    def sequence_pattern(self, nodes):
        # nodes = list of sequence_item_pattern
        return ast.MatchSequence(patterns=nodes)

    def mapping_item_pattern(self, nodes):
        # literal/attribute + as_pattern)
        return nodes[0], nodes[1]

    def mapping_pattern(self, nodes):
        # nodes = list of mapping_item_pattern
        keys = [k for k, v in nodes]
        patterns = [v for k, v in nodes]
        return ast.MatchMapping(keys=keys, patterns=patterns, rest=None)

    def mapping_star_pattern(self, nodes):
        # nodes[-1] = NAME for **rest
        # nodes[:-1] = mapping_item_pattern
        keys = [k for k, v in nodes[:-1]]
        patterns = [v for k, v in nodes[:-1]]
        rest_name = nodes[-1][1] if isinstance(nodes[-1], tuple) else nodes[-1]
        return ast.MatchMapping(keys=keys, patterns=patterns, rest=rest_name)

    def keyws_arg_pattern(self, nodes):
        # extract keys and patterns
        keys = [name for name, _ in nodes]
        patterns = [pattern for _, pattern in nodes]
        return keys, patterns

    def arguments_pattern(self, nodes):
        pos_args = []
        keywords = ([], [])
        if len(nodes) == 2:
            pos_args = nodes[0]
            keywords = nodes[1]
        elif len(nodes) == 1:
            if isinstance(nodes[0], tuple):
                keywords = nodes[0]
            else:
                pos_args = nodes[0]
        return pos_args, keywords

    def no_pos_arguments(self, nodes):
        # only keywords
        return [], nodes[0]

    def class_pattern(self, nodes):
        # dotted_name (value)
        class_name = nodes[0]
        pos_args, keywords = ([], [])
        # optional arguments
        if len(nodes) > 1 and nodes[1]:
            pos_args, keywords = nodes[1]
        keys, patterns = keywords
        return ast.MatchClass(cls=class_name,
                              patterns=pos_args,
                              kwd_attrs=keys,
                              kwd_patterns=patterns)

    def literal_pattern(self, nodes):
        const = nodes[0]
        # Constants
        if isinstance(const, ast.Constant) and const.value in (None, True, False):
            return ast.MatchSingleton(value=const.value)
        # Other values
        return ast.MatchValue(value=const)

    lambdef_nocond = lambda self, nodes: nodes
    encoding_decl = lambda self, nodes: nodes[0]
    const_none = lambda self, _: ast.Constant(value=None)
    const_true = lambda self, _: ast.Constant(value=True)
    const_false = lambda self, _: ast.Constant(value=False)
    pos_arg_pattern = lambda self, nodes: nodes
    keyw_arg_pattern = lambda self, nodes: nodes