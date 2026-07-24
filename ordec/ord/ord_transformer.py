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

        # Finalize viewgens to method form. Like a def in a Python class
        # body, a viewgen anywhere lexically within the cell suite binds in
        # the cell namespace - including inside if/for/try/... - so it is a
        # method. Nested scopes (def/class) are their own binding context.
        for stmt in suite:
            self._finalize_viewgens(stmt)

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
        `viewgen name -> view_target_expr:\\n suite`

        Emitted in module-level (function) form: a no-argument function whose
        body is the suite verbatim, decorated with __ord_context__.
        viewgen_func. The ViewContext setup/teardown around the body lives in
        wrap_viewgen() (see ordec.ord.context), so no boilerplate is emitted
        here. celldef() rewrites viewgens lexically within a cell body into
        method form (_finalize_viewgens).
        """
        func_name = nodes[0]
        view_target_expr = nodes[1]
        suite = nodes[2]

        func_def = ast.FunctionDef(
            name=func_name,
            args=ast.arguments(
                posonlyargs=[],
                args=[],
                kwonlyargs=[],
                kw_defaults=[],
                kwarg=None,
                defaults=[]
            ),
            body=suite,
            decorator_list=[self.ast_ord_context("viewgen_func")],
            returns=view_target_expr,
            type_params=[]
        )
        # Tag for celldef()'s _finalize_viewgens().
        func_def._ord_viewgen = True
        return func_def

    def _viewgen_to_method(self, func_def):
        """
        Rewrites a function-form viewgen into cell-method form: adds the
        `self` parameter and swaps the decorator for the method-form one.
        The viewgen decorator is the last in the list (`decorated` prepends
        user decorators).
        """
        func_def.args.args.insert(0, ast.arg(arg="self"))
        func_def.decorator_list[-1] = self.ast_ord_context("viewgen")
        del func_def._ord_viewgen

    def _finalize_viewgens(self, node):
        """
        Rewrites node to method form if it is a viewgen, and recurses into
        compound statements to find lexically nested ones. Nested scopes
        (def/class) are not visited: viewgens there bind in that scope and
        stay in function form, as outside of cells.
        """
        if getattr(node, "_ord_viewgen", False):
            self._viewgen_to_method(node)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                ast.ClassDef)):
            return
        for child in ast.iter_child_nodes(node):
            self._finalize_viewgens(child)

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
        - Node keyword statements: e.g., input x, port x
        """
        context_type = nodes[0]
        context_name = nodes[1]
        context_body = nodes[2] if len(nodes) > 2 else None
        if isinstance(context_type, str):
            context_type_name = context_type
            context_type_expr = ast.Name(id=context_type, ctx=ast.Load())
        elif isinstance(context_type, ast.Name):
            context_type_name = context_type.id
            context_type_expr = context_type
        else:
            context_type_name = None
            context_type_expr = context_type
        inout = ''

        context_name_tuple = self.extract_path(context_name)
        path_node = None
        if len(context_name_tuple) > 1:
            path_node = context_name.value
        lhs = copy.copy(context_name)
        self._set_ctx(lhs, ast.Store())
        # Case for symbol statements
        if context_type_name in ["inout", "input", "output"]:
            match context_type_name:
                case "inout":
                    inout = "Inout"
                case "input":
                    inout = "In"
                case _:
                    inout = "Out"

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

        # Case for any other element type (Cell class/instance, Node class/instance)
        else:
            args = [
                ast.Tuple(elts=context_name_tuple, ctx=ast.Load()),
                context_type_expr
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

    def net_and_path_stmt_helper(self, nodes, stmt):
        """Helper for similar code from net and path statements"""
        stmt_list = list()
        for name in nodes:
            # Names can be attributes or subscript accesses
            context_name_tuple = self.extract_path(name)
            name_length = len(context_name_tuple)
            rhs = ast.Call(
                func=self.ast_ord_context("add"),
                args=[
                    ast.Tuple(elts=context_name_tuple, ctx=ast.Load()),
                    ast.Call(
                        func=self.ast_core(stmt),
                        keywords=[],
                        args=[]
                    )
                ],
                keywords=[]
            )
            # Path access must not be assigned
            if name_length > 1:
                stmt_list.append(ast.Expr(rhs))
            else:
                lhs = copy.copy(name)
                self._set_ctx(lhs, ast.Store())
                stmt_list.append(ast.Assign([lhs], rhs))
        return stmt_list

    def net_stmt(self, nodes):
        """ Add net (net x)"""
        return self.net_and_path_stmt_helper(nodes, "Net")

    def path_stmt(self, nodes):
        """ Add path (path x) """
        return self.net_and_path_stmt_helper(nodes, "PathNode")

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
