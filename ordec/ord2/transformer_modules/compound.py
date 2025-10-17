# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from lark import Transformer
import ast

# ordec imports
from .misc import Misc

class CompoundTransformer(Transformer, Misc):

    def __init__(self):
        pass

    def if_stmt(self, nodes):
        condition = nodes[0]
        body = nodes[1]
        elifs = nodes[2] if len(nodes) > 2 else []
        else_body = nodes[3] if len(nodes) > 3 else []
        or_else = else_body
        # process elifs in reverse order to nest properly
        for elif_test, elif_body in reversed(elifs):
            or_else = [ast.If(test=elif_test, body=elif_body, orelse=or_else)]
        return ast.If(test=condition, body=body, orelse=or_else)

    def elif_(self, nodes):
        condition = nodes[0]
        suite = nodes[1]
        return condition, suite

    def while_stmt(self, nodes):
        condition = nodes[0]
        body = nodes[1]
        else_body = nodes[2] if len(nodes) > 2 else []
        return ast.While(test=condition,
                         body=body,
                         orelse=else_body)

    def for_stmt(self, nodes):
        target = nodes[0]
        self._set_ctx(target, ast.Store())
        iterator = nodes[1]
        body = nodes[2]
        or_else = nodes[3] if len(nodes) > 3 else []
        return ast.For(target=target,
                       iter=iterator,
                       body=body,
                       orelse=or_else)

    def try_stmt(self, nodes):
        # try: suite except_clauses [else: suite] [finally]
        body = nodes[0]
        handlers = nodes[1]
        orelse = nodes[2] if len(nodes) > 2 and not isinstance(nodes[2], tuple) else []
        if len(orelse) > 0:
            finalbody = nodes[3][1] if len(nodes) > 3 else []
        else:
            finalbody = nodes[2][1] if len(nodes) > 2 else []
        return ast.Try(body=body, handlers=handlers, orelse=orelse, finalbody=finalbody)

    def try_finally(self, nodes):
        # try: suite finally
        body = nodes[0]
        finalbody = nodes[1][1] if (isinstance(nodes[1], tuple)
                                    and nodes[1][0] == "finally") else nodes[1]
        return ast.Try(body=body, handlers=[], orelse=[], finalbody=finalbody)

    def finally__(self, nodes):
        suite = nodes[0]
        return "finally", suite

    def except_clause(self, nodes):
        # except [test ["as" name]]: suite
        if len(nodes) == 1:
            # except: suite
            exc_type = None
            name = None
            suite = nodes[0]
        elif len(nodes) == 2:
            # except test: suite
            exc_type = nodes[0]
            name = None
            suite = nodes[1]
        elif len(nodes) == 3:
            # except test as name: suite
            exc_type = nodes[0]
            name = nodes[1]
            suite = nodes[2]
        else:
            raise ValueError(f"Unexpected except_clause nodes: {nodes}")
        return ast.ExceptHandler(type=exc_type, name=name, body=suite)

    def with_stmt(self, nodes):
        with_items = nodes[0]
        suite = nodes [1]
        return ast.With(with_items, suite)

    def with_item(self, nodes):
        test = nodes[0]
        name = nodes[1] if len(nodes) > 1 else None
        if isinstance(name, str):
            name = ast.Name(id=name, ctx=ast.Store())
        else:
            self._set_ctx(name, ast.Store())
        return ast.withitem(
            context_expr=test,
            optional_vars=name
        )

    def match_stmt(self, nodes):
        test = nodes[0]
        cases = nodes[1:]
        return ast.Match(test, cases)

    elifs = lambda self, nodes: nodes
    comp_fors = lambda self, nodes: nodes
    except_clauses = lambda self, nodes: nodes
    with_items = lambda self, nodes: nodes