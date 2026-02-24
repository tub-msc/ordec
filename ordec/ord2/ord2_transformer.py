# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import ast
import copy

# ordec imports
from .python_transformer import PythonTransformer


class Ord2Transformer(PythonTransformer):
    """
    The Ord2Transformer handles Ord specific sytnax and converts it
    back to valid Python ORDeC code. It inherits from the PythonTransformer
    for full support of the Python syntax. 
    """

    @staticmethod
    def ast_name(identifier, ctx=ast.Load()):
        return ast.Name(id=identifier, ctx=ctx)
    @staticmethod
    def ast_attribute(value, attr, ctx=ast.Load()):
        return ast.Attribute(value=value, attr=attr, ctx=ctx)

    def celldef(self, nodes):
        """ Definition of a ORDeC cell class"""
        cell_name = nodes[0]
        suite = nodes[1]
        base = self.ast_name('Cell')

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
            return ast.Call(func=self.ast_name("R"), args=[token], keywords=[])
        else:
            token_value = token.value.replace("_", "")
            if "." in token_value or "e" in token_value.lower():
                number = float(token_value)
            else:
                number = int(token_value, 10)
            return ast.Constant(value=number)

    def viewgen(self, nodes):
        """ Funcdef for cell (viewgen schematic:\n suite)"""
        func_name = nodes[0]
        suite = nodes[1]

        keywords = list()
        keywords.append(ast.keyword(arg="cell", value=self.ast_name("self")))
        if func_name == "schematic":
            keywords.append(
                ast.keyword(
                    arg="symbol",
                    value=self.ast_attribute(self.ast_name("self"), attr="symbol")
                )
            )

        viewgen_call = ast.Call(
            func=self.ast_name(func_name.title()),
            args=[],
            keywords=keywords
        )
        # Build the ORD context call
        ord_context_call = ast.Call(
            func=self.ast_name('OrdContext'),
            args=[],
            keywords=[
                ast.keyword(
                    arg='root',
                    value=viewgen_call
                ),
                ast.keyword(
                    arg='parent',
                    value=self.ast_name('self')
                )
            ]
        )
        # Call the corresponding context postprocess function implicitly
        return_value = ast.Return(
                ast.Call(
                func=self.ast_attribute(self.ast_name('ctx'),
                                    func_name + "_postprocess",
                ),
                args=[],
                keywords=[]
            )
        )

        suite.append(return_value)
        with_context = ast.With(
            items=[
                ast.withitem(
                    context_expr=ord_context_call
                )
            ],
            body=suite
        )
        # Wrap with statement with context in a decorated function call
        # --> See Python implementation
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
            body=[with_context],
            decorator_list=[self.ast_name("generate")],
            returns=self.ast_name(func_name.title()),
            type_params=[]
        )
        return func_def

    def connect_stmt(self, nodes):
        """ connect stmt x -- b"""
        connect_lhs = nodes[0]
        connect_rhs = nodes[1]
        call = ast.Call(func=self.ast_attribute(connect_lhs, attr="__wire_op__"),
                        args=[connect_rhs],
                        keywords=[])
        return ast.Expr(value=call)

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

    def context_element(self, nodes):
        """ context_element (name name:\n    suite)"""
        context_type = nodes[0]
        context_name = nodes[1]
        context_body = nodes[2] if len(nodes) > 2 else None
        inout = ''

        context_name_tuple = self.extract_path(context_name)
        path_node = None
        if len(context_name_tuple) > 1:
            path_node = context_name.value
        lhs = copy.copy(context_name)
        self._set_ctx(lhs, ast.Store())
        # Case for symbol statements
        if context_type in ["inout", "input", "output"]:
            match context_type:
                case "inout":
                    inout = "Inout"
                case "input":
                    inout = "In"
                case _:
                    inout = "Out"

            args = []
            func = self.ast_attribute(self.ast_name("ctx"), "add")

            args.append(ast.Tuple(elts=context_name_tuple, ctx=ast.Load()))
            args.append(ast.Call(
                        func=self.ast_name("Pin"),
                        keywords=[
                            ast.keyword(
                                arg="pintype",
                                value=self.ast_attribute(
                                    self.ast_name("PinType"),
                                    inout
                                )
                            )
                        ],
                        args=[]
                    )
            )
            rhs = ast.Call(func=func, args=args, keywords=[])
        # Case for port statements
        elif context_type == "port":
 
            args = [ast.Tuple(elts=context_name_tuple, ctx=ast.Load())]
            func = self.ast_attribute(self.ast_name("ctx"),"add_port")
            rhs = ast.Call(func=func, args=args, keywords=[])

        # Case for instantiating sub-cells
        else:
            resolver_lambda = ast.Lambda(
                        args=ast.arguments(
                            posonlyargs=[],
                            args=[],
                            kwonlyargs=[],
                            kw_defaults=[],
                            kwarg=ast.arg(
                                arg="params"
                            ),
                            defaults=[]
                        ),
                        body=self.ast_attribute(
                            ast.Call(
                                func=self.ast_name(context_type),
                                args=[],
                                keywords=[
                                    ast.keyword(
                                        value=self.ast_name("params"),
                                    )
                                ]
                            ),
                            "symbol"
                        )
                    )

            args = []
            func=self.ast_attribute(self.ast_name("ctx"), "add")                
            args.append(ast.Tuple(elts=context_name_tuple, ctx=ast.Load()))
            args.append(ast.Call(
                        func=self.ast_name("SchemInstanceUnresolved"),
                        keywords=[
                            ast.keyword(
                                arg="resolver",
                                value=resolver_lambda
                            )
                        ],
                        args=[]
                )
            )
            rhs = ast.Call(func=func, args=args, keywords=[])
        # Path accesses must not be assigned
        if path_node:
            assignment = ast.Expr(rhs)
        else:
            assignment = ast.Assign([lhs], rhs)

        # Combine to context-with stmt
        with_stmt = ast.With(
            items=[
                ast.withitem(
                    context_expr=ast.Call(
                        func=self.ast_name("OrdContext"),
                        args=[],
                        keywords=[
                            ast.keyword(
                                arg="root",
                                value=context_name
                            )
                        ]
                    )
                )
            ],
            body=context_body if isinstance(context_body, list) else [context_body]
        )
        return [assignment, with_stmt]

    def depth_helper(self, value, depth=1):
        """ Access parent attributes depending on the dotted depth"""
        node = self.ast_attribute(self.ast_name("ctx"), "root")

        for _ in range(depth - 1):
            node = self.ast_attribute(node,"parent")

        if value:
            node = self.ast_attribute(node, value)
        return node

    def dotted_atom(self, nodes):
        """ Dotted name (..x) or ellipsis (...) """
        if len(nodes) == 1:
            depth = nodes[0]
            if depth == 3:
                return ast.Constant(value=Ellipsis)
            return self.depth_helper(None, depth)
        else:
           depth = nodes[0]
           value = nodes[1]
           return self.depth_helper(value, depth)

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
            target = self.ast_attribute(
                self.ast_name("ctx"),
                "root"
            )
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
                func=self.ast_attribute(
                    self.ast_name("ctx"),
                    "add"),
                args=[
                    ast.Tuple(elts=context_name_tuple, ctx=ast.Load()),
                    ast.Call(
                        func=self.ast_name(stmt),
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
        """ Flatten the body of the context element suite"""
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
