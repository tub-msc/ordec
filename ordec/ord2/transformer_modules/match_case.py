# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from lark import Transformer
import ast

class MatchCaseTransformer(Transformer):

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

    def keyw_arg_pattern(self, nodes):
        key = nodes[0]
        pattern = nodes[1]
        return key, pattern

    def as_pattern(self, nodes):
        pattern = nodes[0]
        name = nodes[1]
        return ast.MatchAs(pattern=pattern, name=name)

    def or_pattern(self, nodes):
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
        keys = [k.value for k, v in nodes]
        patterns = [v for k, v in nodes]
        return ast.MatchMapping(keys=keys, patterns=patterns, rest=None)

    def mapping_star_pattern(self, nodes):
        # nodes[-1] = NAME for **rest
        # nodes[:-1] = mapping_item_pattern
        keys = [k.value for k, v in nodes[:-1]]
        patterns = [v for k, v in nodes[:-1]]
        rest_name = nodes[-1][1] if isinstance(nodes[-1], tuple) else nodes[-1]
        return ast.MatchMapping(keys=keys, patterns=patterns, rest=rest_name)

    def arguments_pattern(self, nodes):
        pos_args = []
        kw_names = []
        kw_values = []
        for argument in nodes:
            if isinstance(argument, tuple):
                kw_names.append(argument[0])
                kw_values.append(argument[1])
            else:
                pos_args.append(argument)
        return pos_args, (kw_names, kw_values)


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

    @staticmethod
    def convert_string(current_string):
        prefix, string = current_string
        if len(prefix) == 0:
            return ast.Constant(value=string)
        elif 'b' in prefix:
            return ast.Constant(value=string.encode('utf-8'))
        elif 'u' == prefix:
            return ast.Constant(value=string, kind=prefix)
        else:
            return ast.Constant(value=string)

    def literal_pattern(self, nodes):
        const = nodes[0]
        # Constants
        if (isinstance(const, ast.Constant) and
                (type(const.value) is bool or const.value is None)):
            return ast.MatchSingleton(value=const.value)
        # Strings
        elif isinstance(const, tuple):
            return ast.MatchValue(self.convert_string(const))
        # Other values
        return ast.MatchValue(const)

    lambdef_nocond = lambda self, nodes: nodes
    encoding_decl = lambda self, nodes: nodes[0]
    const_none = lambda self, _: ast.Constant(value=None)
    const_true = lambda self, _: ast.Constant(value=True)
    const_false = lambda self, _: ast.Constant(value=False)
    argument = lambda self, nodes: nodes[0]