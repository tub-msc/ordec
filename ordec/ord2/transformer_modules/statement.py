# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports
from lark import Transformer
import ast

#ordec imports
from .misc import Misc

class StatementTransformer(Transformer, Misc):

    AUG_OP_MAP = {
        "+=": ast.Add,
        "-=": ast.Sub,
        "*=": ast.Mult,
        "@=": ast.MatMult,
        "/=": ast.Div,
        "%=": ast.Mod,
        "&=": ast.BitAnd,
        "|=": ast.BitOr,
        "^=": ast.BitXor,
        "<<=": ast.LShift,
        ">>=": ast.RShift,
        "**=": ast.Pow,
        "//=": ast.FloorDiv,
    }

    def expr_stmt(self, nodes):
        return ast.Expr(value=nodes[0])

    def async_stmt(self, nodes):
        if isinstance(nodes[0], ast.FunctionDef):
            return self.async_funcdef(nodes[0])
        elif isinstance(nodes[0], ast.With):
            with_stmt = nodes[0]
            return ast.AsyncWith(items=with_stmt.items,
                                 body=with_stmt.body)
        else:
            for_stmt = nodes[0]
            return ast.AsyncFor(target=for_stmt.target,
                                iter=for_stmt.iter,
                                body=for_stmt.body,
                                orelse=for_stmt.orelse)

    def simple_stmt(self, nodes):
        statements = []
        for node in nodes:
            if node is not None:
                statements.append(node)
        return statements

    def assign(self, nodes):
        targets = nodes[:-1]
        value = nodes[-1]
        for t in targets:
            self._set_ctx(t, ast.Store())
        return ast.Assign(targets=targets, value=value)

    def augassign_op(self, nodes):
        op = nodes[0].value
        return self.AUG_OP_MAP[op]()

    def augassign(self, nodes):
        target = nodes[0]
        op = nodes[1]
        value = nodes[2]
        self._set_ctx(target, ast.Store())
        return ast.AugAssign(target=target, op=op, value=value)

    def annassign(self, nodes):
        target = nodes[0]
        target_type = nodes[1]
        value = nodes[2] if len(nodes) > 2 else None
        self._set_ctx(target, ast.Store())
        simple = 1 if isinstance(target, ast.Name) else 0
        return ast.AnnAssign(target=target, annotation=target_type, value=value, simple=simple)

    def raise_stmt(self, nodes):
        if not nodes:
            # raise
            exc = None
            cause = None
        elif len(nodes) == 1:
            # raise expr
            exc = nodes[0]
            cause = None
        else:
            # raise expr from cause
            exc, cause = nodes

        return ast.Raise(exc=exc, cause=cause)

    def assert_stmt(self, nodes):
        test = nodes[0]
        message = nodes[1] if len(nodes) > 1 else None
        return ast.Assert(test=test, msg=message)

    def dotted_name(self, nodes):
        parts = [str(node) for node in nodes if str(node) != "."]
        return ".".join(parts)

    def dotted_as_name(self, nodes):
        name = nodes[0]
        asname = nodes[1] if len(nodes) > 1 else None
        return name, asname

    def import_as_name(self, nodes):
        name = str(nodes[0])
        asname = str(nodes[1]) if len(nodes) > 1 else None
        return name, asname

    def import_name(self, nodes):
        # import xy as ab
        aliases = [ast.alias(name=name, asname=asname) for name, asname in nodes[0]]
        return ast.Import(names=aliases)

    def dots(self, nodes):
        return len(nodes)

    def import_from(self, nodes):
        # from .. core import helpers
        level = 0
        if isinstance(nodes[0], int):
            level = nodes.pop(0)

        module = None
        names_node = None

        if len(nodes) == 2:
            module, names_node = nodes
        elif len(nodes) == 1:
            # could be module or names
            if isinstance(nodes[0], str):
                module = nodes[0]
                names_node = []
            else:
                names_node = nodes[0]

        # build aliases
        aliases = []
        if isinstance(names_node, list):
            aliases = [ast.alias(name=name, asname=asname) for name, asname in names_node]

        if not aliases and module is not None:
            aliases = [ast.alias(name='*', asname=None)]
        return ast.ImportFrom(module=module, names=aliases, level=level)

    def del_stmt(self, nodes):
        # Set for each of the inner nodes
        del_stmts = nodes[0] if isinstance(nodes[0], list) else [nodes[0]]
        for del_stmt in del_stmts:
            self._set_ctx(del_stmt, ast.Del())
        return ast.Delete(targets=del_stmts)

    pass_stmt = lambda self, _ : ast.Pass()
    assign_stmt = lambda self, nodes: nodes[0]
    return_stmt = lambda self, nodes: ast.Return(value=nodes[0] if len(nodes) > 0 else None)
    break_stmt = lambda self, _: ast.Break()
    continue_stmt = lambda self, _: ast.Continue()
    global_stmt = lambda self, nodes: ast.Global(nodes)
    nonlocal_stmt = lambda self, nodes: ast.Nonlocal(nodes)
    dotted_as_names = lambda self, nodes: nodes
    import_as_names = lambda self, nodes: nodes
    import_stmt = lambda self, nodes: nodes[0]
    yield_stmt = lambda self, nodes: nodes[0]