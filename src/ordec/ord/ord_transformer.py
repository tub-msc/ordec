# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import ast
import copy

# third-party imports
from lark import v_args

# ordec imports
from .python_transformer import PythonTransformer


class OrdTransformer(PythonTransformer):
    """
    The OrdTransformer handles ORD-specific syntax and converts it
    back to valid Python ORDeC code. It inherits from the PythonTransformer
    for full support of the Python syntax.
    """

    @staticmethod
    def ast_name(identifier, ctx=ast.Load()):
        return ast.Name(id=identifier, ctx=ctx)
    @staticmethod
    def ast_attribute(value, attr, ctx=ast.Load()):
        return ast.Attribute(value=value, attr=attr, ctx=ctx)

    def ast_core(self, attr):
        return self.ast_attribute(self.ast_name("__ordec_core__"), attr)

    def ast_ord_context(self, attr):
        return self.ast_attribute(self.ast_name("__ord_context__"), attr)

    def ast_src_loc_keywords(self, meta):
        """Keyword arguments carrying the statement's source line and column."""
        return [
            ast.keyword(arg="src_line", value=ast.Constant(value=meta.line)),
            ast.keyword(arg="src_column", value=ast.Constant(value=meta.column)),
        ]

    def celldef(self, nodes):
        """ Definition of a ORDeC cell class"""
        cell_name = nodes[0]
        suite = nodes[1]
        base = self.ast_core("Cell")

        return ast.ClassDef(
            name=cell_name,
            bases=[base],
            keywords=[],
            body=suite,
            decorator_list=[], #self.ast_name("public")
            type_params=[]
        )

    def RATIONAL(self, token):
        """ Rational numbers with SI suffix (100n, 20u)"""
        si_suffixes = ('a','f','p','n','u','m','k','M','G','T')
        if token.endswith(si_suffixes):
            token = ast.Constant(token.value)
            return ast.Call(func=self.ast_core("R"), args=[token], keywords=[])
        else:
            token_value = token.value.replace("_", "")
            if "." in token_value or "e" in token_value.lower():
                number = float(token_value)
            else:
                number = int(token_value, 10)
            return ast.Constant(value=number)

    def viewgen(self, nodes):
        """
        `viewgen name(params) [-> view_target_expr]:\\n suite`

        Translated context-free: a function with the user's parameters
        verbatim, decorated with __ordec_core__.viewgen. Binding follows
        Python scoping - a viewgen in a cell body is a method, elsewhere a
        function - so no placement analysis happens here; arity mismatches
        are caught at runtime (MetaCell at class creation, or the call
        preflight).
        """
        name = str(nodes[0])
        index = 1
        if index < len(nodes) and isinstance(nodes[index], ast.arguments):
            args = nodes[index]
            index += 1
        else:
            args = ast.arguments(
                posonlyargs=[],
                args=[],
                vararg=None,
                kwonlyargs=[],
                kw_defaults=[],
                kwarg=None,
                defaults=[]
            )
        rest = nodes[index:]
        if len(rest) == 2:
            returns, suite = rest
        else:
            returns = None
            suite = rest[0]

        return ast.FunctionDef(
            name=name,
            args=args,
            body=suite,
            decorator_list=[self.ast_core("viewgen")],
            returns=returns,
            type_params=[]
        )

    @v_args(meta=True)
    def viewgen_oldform(self, meta, nodes):
        """
        Old parenless spelling `viewgen name -> target:`. Rejected with a
        fix-it; the diagnostic is context-free (placement is unknown here),
        so both spellings are shown.
        """
        name = nodes[0]
        e = SyntaxError(
            f"line {meta.line}: viewgen {name} declares no parameter list. "
            f"Write `viewgen {name}(self) -> T:` inside a cell, or "
            f"`viewgen {name}() -> T:` at module level."
        )
        e.lineno = meta.line
        raise e

    def constrain_stmt(self, nodes):
        """ ! x >= 200 """
        return ast.Expr(
            ast.Call(
                func=self.ast_ord_context("constrain"),
                args=[nodes[0]],
                keywords=[]
            )
        )

    def extract_path(self, nodes):
        """Extract string list from nested attributes"""

        # Base: Name(id)
        if isinstance(nodes, ast.Name):
            return [ast.Constant(nodes.id)]

        # Attribute(value, attr)
        elif isinstance(nodes, ast.Attribute):
            return self.extract_path(nodes.value) + [ast.Constant(nodes.attr)]

        # Subscript(value, slice)
        elif isinstance(nodes, ast.Subscript):
            if isinstance(nodes.slice, str) and nodes.slice.isidentifier():
                return self.extract_path(nodes.value) + [self.ast_name(nodes.slice)]
            return self.extract_path(nodes.value) + [nodes.slice]
        else:
            raise Exception(f"Incompatible path type: {nodes!r}")

    @v_args(meta=True)
    def node_stmt(self, meta, nodes):
        """Node statement: 'Type name' with optional body.

        There are three types of node statements:
        - Node class statements: e.g., LayoutRect x
        - Node instance statements: e.g., Nmos x
        - Node keyword statements: e.g., input x, port x, net x, path x
        """
        context_type = nodes[0]
        context_name = nodes[1]
        context_body = nodes[2] if len(nodes) > 2 else None
        if isinstance(context_type, str):
            context_type_name = context_type
        elif isinstance(context_type, ast.Name):
            context_type_name = context_type.id
        else:
            context_type_name = None
        inout = ''

        context_name_tuple = self.extract_path(context_name)
        path_node = None
        if len(context_name_tuple) > 1:
            path_node = context_name.value
        lhs = copy.copy(context_name)
        self._set_ctx(lhs, ast.Store())
        # Case for symbol statements
        if context_type_name in ["inout", "input", "output"]:
            # Default align by pin direction: inputs face West, outputs
            # East, inouts South. A body `.align=` assignment overrides.
            match context_type_name:
                case "inout":
                    inout, align = "Inout", "South"
                case "input":
                    inout, align = "In", "West"
                case _:
                    inout, align = "Out", "East"

            args = []
            func = self.ast_ord_context("add")

            args.append(ast.Tuple(elts=context_name_tuple, ctx=ast.Load()))
            args.append(ast.Call(
                        func=self.ast_core("Pin"),
                        keywords=[
                            ast.keyword(
                                arg="pintype",
                                value=self.ast_attribute(
                                    self.ast_core("PinType"),
                                    inout
                                )
                            ),
                            ast.keyword(
                                arg="align",
                                value=self.ast_attribute(
                                    self.ast_core("D4"),
                                    align
                                )
                            )
                        ],
                        args=[]
                    )
            )
            rhs = ast.Call(func=func, args=args, keywords=[])
        # Case for port statements
        elif context_type_name == "port":
 
            args = [ast.Tuple(elts=context_name_tuple, ctx=ast.Load())]
            func = self.ast_ord_context("add_port")
            rhs = ast.Call(func=func, args=args, keywords=[])

        # Case for net/path statements
        elif context_type_name in ("net", "path"):
            node_type = "Net" if context_type_name == "net" else "PathNode"
            rhs = ast.Call(
                func=self.ast_ord_context("add"),
                args=[
                    ast.Tuple(elts=context_name_tuple, ctx=ast.Load()),
                    ast.Call(
                        func=self.ast_core(node_type),
                        args=[],
                        keywords=[]
                    )
                ],
                keywords=[]
            )

        # Case for any other element type (Cell class/instance, Node class/instance)
        else:
            args = [
                ast.Tuple(elts=context_name_tuple, ctx=ast.Load()),
                context_type
            ]
            func = self.ast_ord_context("add_element")
            rhs = ast.Call(
                func=func,
                args=args,
                keywords=self.ast_src_loc_keywords(meta),
            )

        # Path accesses must not be assigned
        if path_node:
            assignment = ast.Expr(rhs)
        else:
            assignment = ast.Assign([lhs], rhs)

        if context_body is None:
            return [assignment]

        # Combine to context-with stmt
        with_stmt = ast.With(
            items=[
                ast.withitem(
                    context_expr=ast.Call(
                        func=self.ast_attribute(context_name, "ctx"),
                        args=[],
                        keywords=[]
                    )
                )
            ],
            body=context_body if isinstance(context_body, list) else [context_body]
        )
        return [assignment, with_stmt]

    @v_args(meta=True)
    def anon_node_stmt(self, meta, nodes):
        """Anonymous node statement: 'anonymous Type name' with optional body.

        Like node_stmt but passes None as name_tuple, so no NPath is created.
        """
        context_type = nodes[0]
        context_name = nodes[1]
        context_body = nodes[2] if len(nodes) > 2 else None

        rhs = ast.Call(
            func=self.ast_ord_context("add_element"),
            args=[ast.Constant(value=None), context_type],
            keywords=self.ast_src_loc_keywords(meta),
        )

        target = copy.copy(context_name)
        self._set_ctx(target, ast.Store())
        assignment = ast.Assign([target], rhs)

        if context_body is None:
            return [assignment]

        with_stmt = ast.With(
            items=[
                ast.withitem(
                    context_expr=ast.Call(
                        func=self.ast_attribute(context_name, "ctx"),
                        args=[],
                        keywords=[]
                    )
                )
            ],
            body=context_body if isinstance(context_body, list) else [context_body]
        )
        return [assignment, with_stmt]

    @v_args(meta=True)
    def anon_node_stmt_nobody(self, meta, nodes):
        """Anonymous node statement without body, supports multiple names."""
        result = []
        for context_target in nodes[1:]:
            result.extend(self.anon_node_stmt(meta, [nodes[0], context_target]))
        return result

    @v_args(meta=True)
    def node_stmt_nobody(self, meta, nodes):
        """Node statement without body, supports multiple names (e.g., 'Nmos a, b, c')"""
        result = []
        for context_target in nodes[1:]:
            result.extend(self.node_stmt(meta, [nodes[0], context_target]))
        return result

    def dotted_atom(self, nodes):
        """ Dotted name (.x) or bare dot (.) - access current context root """
        root = ast.Call(self.ast_ord_context("root"), args=[], keywords=[])
        if nodes:
            return self.ast_attribute(root, nodes[0])
        # Mark the bare-dot node so `assign` can recognize `. = ...` (assigning
        # the view root) instead of producing an invalid assignment target.
        root._ord_bare_root = True
        return root

    def assign(self, nodes):
        """Assignment, with special handling for `. = ...` (set view root)."""
        targets = nodes[:-1]
        value = nodes[-1]
        if len(targets) == 1 and getattr(targets[0], "_ord_bare_root", False):
            return ast.Expr(ast.Call(
                func=self.ast_ord_context("set_root"),
                args=[value],
                keywords=[]
            ))
        return super().assign(nodes)

    def getparam(self, nodes):
        """ get/set param (.$l = 100n) """
        if len(nodes) == 2:
            # assignment
            target = nodes[0]
            attr = nodes[1]
            ctx = ast.Load()
        else:
            # only dotted access
            attr = nodes[0]
            ctx = ast.Store()
            target = ast.Call(self.ast_ord_context("root"), args=[], keywords=[])
        return self.ast_attribute(
            self.ast_attribute(
                target,
                "params"
            ), attr, ctx=ctx
        )

    @v_args(meta=True)
    def net_stmt(self, meta, nodes):
        """ Net statement with body (net x: ...) """
        return self.node_stmt(meta, ["net", *nodes])

    @v_args(meta=True)
    def path_stmt(self, meta, nodes):
        """ Path statement with body (path x: ...) """
        return self.node_stmt(meta, ["path", *nodes])

    @v_args(meta=True)
    def net_stmt_nobody(self, meta, nodes):
        """ Net statement without body, supports multiple names (net a, b) """
        result = []
        for context_target in nodes:
            result.extend(self.node_stmt(meta, ["net", context_target]))
        return result

    @v_args(meta=True)
    def path_stmt_nobody(self, meta, nodes):
        """ Path statement without body, supports multiple names (path a, b) """
        result = []
        for context_target in nodes:
            result.extend(self.node_stmt(meta, ["path", context_target]))
        return result

    def _flatten(self, items):
        """ Flatten the body of a node statement suite"""
        flat = []
        for item in items:
            if isinstance(item, list):
                flat.extend(item)
            else:
                flat.append(item)
        return flat

    context_body = lambda self, nodes: nodes[0]
    SI = lambda self, token: token.value
    suite = lambda self, nodes: self._flatten(nodes)
