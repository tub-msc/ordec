# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import ast
import copy

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
        if token.endswith(si_suffixes) or '/' in token:
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
        """ Funcdef for cell (viewgen name -> Type:\n suite)"""
        func_name = nodes[0]
        if len(nodes) == 4:
            viewgen_args = nodes[1]
            viewgen_type = nodes[2]
            suite = nodes[3]
        else:
            viewgen_args = []
            viewgen_type = nodes[1]
            suite = nodes[2]

        # Validate the return type
        viewgen_type_lower = viewgen_type.lower()
        if viewgen_type_lower not in ("symbol", "schematic", "layout"):
            raise SyntaxError(
                f"Unknown viewgen return type '{viewgen_type}'. "
                f"Expected Symbol, Schematic, or Layout."
            )

        # Extract keyword arguments
        kwarg_assignments = []
        for arg in viewgen_args:
            if isinstance(arg, tuple) and arg[0] == "argvalue":
                kwarg_assignments.append(
                    ast.Assign(
                        targets=[self.ast_name(arg[1].id, ctx=ast.Store())],
                        value=arg[2]
                    )
                )

        keywords = list()
        keywords.append(ast.keyword(arg="cell", value=self.ast_name("self")))
        if viewgen_type_lower in ("schematic", "layout"):
            keywords.append(
                ast.keyword(
                    arg="symbol",
                    value=self.ast_attribute(self.ast_name("self"), attr="symbol")
                )
            )

        ord_root = self.ast_name("__ord_root__")
        ord_root_store = self.ast_name("__ord_root__", ctx=ast.Store())

        viewgen_call = ast.Call(
            func=self.ast_core(viewgen_type.title()),
            args=[],
            keywords=keywords
        )

        # __ord_root__ = Type(cell=self, symbol=self.symbol)
        root_assign = ast.Assign(
            targets=[ord_root_store],
            value=viewgen_call
        )

        # __ord_root__.view_context(__ord_root__) — access class attr, instantiate
        view_context_call = ast.Call(
            func=self.ast_attribute(ord_root, "view_context"),
            args=[ord_root],
            keywords=[]
        )

        # return __ord_root__
        return_value = ast.Return(ord_root)

        with_context = ast.With(
            items=[
                ast.withitem(context_expr=view_context_call),
            ],
            body=suite
        )
        # Wrap with statement with context in a decorated function call
        # --> See Python implementation
        func_body = kwarg_assignments + [root_assign, with_context, return_value]
        func_def = ast.FunctionDef(
            name=func_name,
            args=ast.arguments(
                posonlyargs=[],
                args=[ast.arg(arg="self")],
                kwonlyargs=[],
                kw_defaults=[],
                kwarg=None,
                defaults=[]
            ),
            body=func_body,
            decorator_list=[self.ast_core("generate")],
            returns=self.ast_core(viewgen_type.title()),
            type_params=[]
        )
        return func_def

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

    def node_stmt(self, nodes):
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
            rhs = ast.Call(func=func, args=args, keywords=[])

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

    def anon_node_stmt(self, nodes):
        """Anonymous node statement: 'anonymous Type name' with optional body.

        Like node_stmt but passes None as name_tuple, so no NPath is created.
        """
        context_type = nodes[0]
        context_name = nodes[1]
        context_body = nodes[2] if len(nodes) > 2 else None

        rhs = ast.Call(
            func=self.ast_ord_context("add_element"),
            args=[ast.Constant(value=None), context_type],
            keywords=[]
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

    def anon_node_stmt_nobody(self, nodes):
        """Anonymous node statement without body, supports multiple names."""
        result = []
        for context_target in nodes[1:]:
            result.extend(self.anon_node_stmt([nodes[0], context_target]))
        return result

    def node_stmt_nobody(self, nodes):
        """Node statement without body, supports multiple names (e.g., 'Nmos a, b, c')"""
        result = []
        for context_target in nodes[1:]:
            result.extend(self.node_stmt([nodes[0], context_target]))
        return result

    def dotted_atom(self, nodes):
        """ Dotted name (.x) or bare dot (.) - access current context root """
        root = ast.Call(self.ast_ord_context("root"), args=[], keywords=[])
        if nodes:
            return self.ast_attribute(root, nodes[0])
        return root

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
