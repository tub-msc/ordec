# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import ast

# ordec imports
from .python_transformer import PythonTransformer


class Ord2Transformer(PythonTransformer):

    @staticmethod
    def ast_name(identifier, ctx=ast.Load()):
        return ast.Name(id=identifier, ctx=ctx)
    @staticmethod
    def ast_attribute(value, attr, ctx=ast.Load()):
        return ast.Attribute(value=value, attr=attr, ctx=ctx)

    def celldef(self, nodes):
        cell_name = nodes[0]
        suite = nodes[1]
        base = self.ast_name('Cell')

        return ast.ClassDef(
            name=cell_name,
            bases=[base],
            keywords=[],
            body=suite,
            decorator_list=[self.ast_name("public")],
            type_params=[]
        )

    def RATIONAL(self, token):
        si_suffixes = ('a','f','p','n','u','m','k','M','G','T')
        if token.endswith(si_suffixes) or '/' in token:
            token = ast.Constant(token.value)
            return ast.Call(func=self.ast_name("R"), args=[token], keywords=[])
        else:
            if '.' in token:
                number = float(token)
            else:
                number = token.value.replace("_", "")
                number = int(number, 10)
            return ast.Constant(value=number)

    def cell_func_def(self, nodes):
        func_name = nodes[0]
        suite = nodes[1]
        # Create suite assignment rhs

        keywords = list()
        keywords.append(ast.keyword(arg="cell", value=self.ast_name("self")))
        if func_name == "schematic":
            keywords.append(
                ast.keyword(
                    arg="symbol",
                    value=self.ast_attribute(self.ast_name("self"), attr="symbol")
                )
            )

        cell_func_call = ast.Call(
            func=self.ast_name(func_name.title()),
            args=[],
            keywords=keywords
        )

        ord_context_call = ast.Call(
            func=self.ast_name('OrdContext'),
            args=[],
            keywords=[
                ast.keyword(
                    arg='root',
                    value=cell_func_call
                ),
                ast.keyword(
                    arg='parent',
                    value=self.ast_name('self')
                )
            ]
        )

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
        # insert assignment before first inner content

        # Combine to function definition
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
        # Attr because of the dotted_atom
        connect_lhs = nodes[0].attr
        connect_rhs = nodes[1]
        lhs = nodes[0].value

        keywords=list()
        keywords.append(ast.keyword(arg="here", value=connect_rhs))
        keywords.append(ast.keyword(arg="there",
                                    value=self.tuple([ast.Constant(value)
                                                      for value in connect_lhs.split('.')])
                                    )
        )
        rhs = ast.Call(func=self.ast_name("SchemInstanceUnresolvedConn"),
                       args=[],
                       keywords=keywords
        )
        return ast.Expr(ast.BinOp(lhs, ast.Mod(), rhs))

    def context_element(self, nodes):
        context_type = nodes[0]
        context_name = nodes[1]
        context_body = nodes[2] if len(nodes) > 2 else None
        inout = ''

        lhs = self.ast_name(context_name, ctx=ast.Store())
        if context_type in ["inout", "input", "output"]:
            match context_type:
                case "inout":
                    inout = "Inout"
                case "input":
                    inout = "In"
                case _:
                    inout = "Out"
            rhs = ast.Call(
                func=self.ast_attribute(self.ast_name("ctx"), "add"),
                args=[
                    ast.Tuple(
                        elts=[ast.Constant(value=value) for value in context_name.split('.')],
                        ctx=ast.Load()
                    ),
                    ast.Call(
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
                ],
                keywords=[]
            )
        elif context_type == "port":
            rhs = ast.Call(
                func=self.ast_attribute(self.ast_name("ctx"),'add_port_normal'),
                args=[
                    ast.Tuple(
                        elts=[ast.Constant(value=value) for value in context_name.split('.')],
                        ctx=ast.Load()
                    ),
                ],
                keywords=[]
            )
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

            rhs = ast.Call(
                func=self.ast_attribute(self.ast_name("ctx"), "add"),
                args=[
                    ast.Tuple(
                        elts=[ast.Constant(value=value) for value in context_name.split('.')],
                        ctx=ast.Load()
                    ),
                    ast.Call(
                        func=self.ast_name("SchemInstanceUnresolved"),
                        keywords=[
                            ast.keyword(
                                arg="resolver",
                                value=resolver_lambda
                            )
                        ],
                        args=[]
                    )
                ],
                keywords=[]
            )
        assignment = ast.Assign([lhs], rhs)

        if context_type == "port":
            with_root_value = ast.Call(
                func=self.ast_attribute(self.ast_name("ctx"), attr='get_symbol_port'),
                args=[self.ast_name(context_name)],
                keywords=[]
            )
        else:
            with_root_value = self.ast_name(context_name)
        with_stmt = ast.With(
            items=[
                ast.withitem(
                    context_expr=ast.Call(
                        func=self.ast_name("OrdContext"),
                        args=[],
                        keywords=[
                            ast.keyword(
                                arg="root",
                                value=with_root_value
                            )
                        ]
                    )
                )
            ],
            body=context_body if isinstance(context_body, list) else [context_body]
        )
        return [assignment, with_stmt]

    def depth_helper(self, value, depth=1):
        node = self.ast_attribute(self.ast_name("ctx"), "root")

        for _ in range(depth - 1):
            node = self.ast_attribute(node,"parent")

        node = self.ast_attribute(node, value, ctx=ast.Store())
        return node

    def dotted_atom(self, nodes):
        if len(nodes) == 1:
            return nodes
        else:
           depth = nodes[0]
           value = nodes[1]
           return self.depth_helper(value, depth)

    def getparam(self, nodes):
        if len(nodes) == 2:
            target = nodes[0]
            attr = nodes[1]
            ctx = ast.Load()
        else:
            # without lhs
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

    def net_stmt(self, nodes):
        net_name = nodes[0]
        lhs = self.ast_name(net_name, ctx=ast.Store())
        rhs = ast.Call(
            func=self.ast_attribute(self.ast_name("ctx"), "add"),
            args=[
                ast.Tuple(
                    elts=[ast.Constant(value=value) for value in net_name.split('.')],
                    ctx=ast.Load()
                ),
                ast.Call(
                    func=self.ast_name("Net"),
                    keywords=[],
                    args=[]
                )
            ],
            keywords=[]
        )
        return ast.Assign([lhs], rhs)


    def _flatten(self, items):
        flat = []
        for item in items:
            if isinstance(item, list):   # child returned multiple stmts
                flat.extend(item)
            else:
                flat.append(item)
        return flat

    context_body = lambda self, nodes: nodes[0]
    SI = lambda self, token: token.value
    suite = lambda self, nodes: self._flatten(nodes)
