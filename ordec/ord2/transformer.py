# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#standard imports
from lark import Transformer
import ast

class Ord2Transformer(Transformer):

    # -- Dictionaries --

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

    ADD_OP_MAP = {
        "+": ast.Add,
        "-": ast.Sub,
    }

    UNARY_OP_MAP = {
        '+': ast.UAdd,
        '-': ast.USub,
        '~': ast.Invert,
        'not': ast.Not,
    }

    MUL_OP_MAP = {
        '*': ast.Mult,
        '@': ast.MatMult,
        '/': ast.Div,
        '%': ast.Mod,
        '//': ast.FloorDiv,
    }

    SHIFT_OP_MAP = {
        '<<': ast.LShift,
        '>>': ast.RShift,
    }

    CMP_OP_MAP = {
        '<': ast.Lt,
        '>': ast.Gt,
        '==': ast.Eq,
        '>=': ast.GtE,
        '<=': ast.LtE,
        '<>': ast.NotEq,  # Python 2
        '!=': ast.NotEq,
        'in': ast.In,
        'not in': ast.NotIn,
        'is': ast.Is,
        'is not': ast.IsNot,
    }

    def __init__(self):
        pass

    # -- HELPERS --

    def _flatten_body(self, body):
        """Recursively flatten a nested list of AST statements."""
        if isinstance(body, list):
            flattened = []
            for stmt in body:
                if isinstance(stmt, list):
                    flattened.extend(self._flatten_body(stmt))
                else:
                    flattened.append(stmt)
            return flattened
        return [body]

    def _set_ctx(self, node, ctx):
        """Recursively set context (Store or Load) for assignment targets."""
        if node is None:
            return

        # Single name: x
        if isinstance(node, ast.Name):
            node.ctx = ctx

        # Tuple or list: (x, y) or [x, y]
        elif isinstance(node, (ast.Tuple, ast.List)):
            node.ctx = ctx
            for elt in node.elts:
                self._set_ctx(elt, ctx)

        # Attribute: obj.attr
        elif isinstance(node, ast.Attribute):
            node.ctx = ctx
            self._set_ctx(node.value, ast.Load())  # The object itself is read

        # Subscript: arr[0]
        elif isinstance(node, ast.Subscript):
            node.ctx = ctx
            self._set_ctx(node.value, ast.Load())  # The container is read
            self._set_ctx(node.slice, ast.Load())  # The index expression is read

        # Slices like arr[1:2]
        elif isinstance(node, ast.Slice):
            if node.lower:
                self._set_ctx(node.lower, ast.Load())
            if node.upper:
                self._set_ctx(node.upper, ast.Load())
            if node.step:
                self._set_ctx(node.step, ast.Load())

        # Starred target: *rest
        elif isinstance(node, ast.Starred):
            node.ctx = ctx
            self._set_ctx(node.value, ctx)

        else:
            pass

    # -- Definitions --

    def expr_stmt(self, nodes):
        return ast.Expr(value=nodes[0])

    def simple_stmt(self, nodes):
        statements = []
        for node in nodes:
            if node is not None:
                if isinstance(node, list):
                    statements.extend(node)
                else:
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
        return ast.AnnAssign(target=target, annotation=target_type, value=value, simple=0)

    def decorator(self, nodes):
        dotted_name = nodes[0]
        func_name = ast.Name(id=dotted_name, ctx=ast.Load())

        if len(nodes) > 1 and nodes[1]:
            args, keywords = nodes[1]
            return ast.Call(func=func_name, args=args, keywords=keywords)
        return func_name

    def decorated(self, nodes):
        decorators = nodes[0]
        definition = nodes[1]
        # classdef, funcdef, async funcdef
        definition.decorator_list = decorators
        return definition


    def funcdef(self, nodes):
        name = nodes[0]
        if isinstance(nodes[1], ast.arguments):
            parameters = nodes[1]
            rest = nodes[2:]
        else:
            parameters = ast.arguments(
                posonlyargs=[],
                args=[],
                vararg=None,
                kwonlyargs=[],
                kw_defaults=[],
                kwarg=None,
                defaults=[]
            )
            rest = nodes[1:]

        # Extract return type and suite
        if len(rest) == 2:
            return_type, suite = rest
        else:
            return_type = None
            suite = rest[0]

        if return_type is not None and isinstance(return_type, str):
            return_type = ast.Name(id=return_type, ctx=ast.Load())

        return ast.FunctionDef(
            name=name,
            args=parameters,
            body=suite,
            decorator_list=[],
            returns=return_type
        )

    def async_funcdef(self, nodes):
        funcdef = nodes[0] if isinstance(nodes, list) else nodes
        name = funcdef.name
        args = funcdef.args
        body = funcdef.body
        returns = funcdef.returns
        return ast.AsyncFunctionDef(
            name=name,
            args=args,
            body=body,
            decorator_list=[],
            returns=returns
        )

    def async_stmt(self, nodes):
        if isinstance(nodes[0], ast.FunctionDef):
            return self.async_funcdef(nodes[0])

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

    def key_value(self, nodes):
        key = nodes[0]
        value = nodes[1]
        return key, value

    def dict(self, nodes):
        dict_items = nodes if nodes else []
        keys = []
        values = []
        for item in dict_items:
            if isinstance(item, tuple):
                # normal key-value
                key_node, value_node = item
                keys.append(key_node)
                values.append(value_node)
            else:
                # **expr unpacking
                keys.append(None)
                values.append(item)

        return ast.Dict(keys=keys, values=values)

    def list(self, nodes):
        list_items = nodes if nodes else []
        return ast.List(elts=list_items, ctx=ast.Load())

    def kwparams(self, nodes):
        typedparam = nodes[0]
        return "kwparam", typedparam

    def poststarparams(self, nodes):
        if not nodes:
            return [], None

        kwparams = nodes[-1] if (
                isinstance(nodes[-1], tuple) and nodes[-1][0] == "kwparam"
        ) else None
        paramvalues = nodes[:-1] if kwparams else nodes
        return paramvalues, kwparams

    def starguard(self, nodes):
        return "starguard"

    def starparam(self, nodes):
        typedparam = nodes[0]
        return "starparam", typedparam

    def starparams(self, nodes):
        star = nodes[0]
        poststarparams = nodes[1] if len(nodes) > 1 else ([], None)
        return star, poststarparams

    def paramvalue(self, nodes):
        typedparam = nodes[0]
        default = nodes[1] if len(nodes) > 1 else None
        if default:
            return "arg_with_default", typedparam, default
        return typedparam

    def typedparam(self, nodes):
        # x:Int
        name = nodes[0]
        annotation = nodes[1] if len(nodes) > 1 else None
        return ast.arg(arg=name, annotation=annotation)

    def parameters(self, nodes):
        """
        Parameters transformer that handles:
          - normal params
          - starparams: nested or flat form:
               - ("starparam", ast.arg)
               - (("starparam", ast.arg), poststar)
          - starguard
          - kwparams: ("kwparam", ast.arg)
        """

        posonlyargs, args = [], []
        vararg = None
        kwonlyargs, kw_defaults = [], []
        kwarg = None
        defaults = []

        # Ensures always return ast.arg instances
        def ensure_arg(node):
            if isinstance(node, ast.arg):
                return node
            if isinstance(node, str):
                return ast.arg(arg=node, annotation=None)

        def unpack_param(param, target_list, default_list=None):
            # p is "ast.arg" or ("arg_with_default", ast.arg, default_expr)
            if isinstance(param, tuple) and param[0] == "arg_with_default":
                target_list.append(ensure_arg(param[1]))
                if default_list is not None:
                    default_list.append(param[2])
            else:
                target_list.append(ensure_arg(param))
                if default_list is not None:
                    default_list.append(None)

        if not nodes:
            return ast.arguments(
                posonlyargs=[], args=[], vararg=None,
                kwonlyargs=[], kw_defaults=[], kwarg=None,
                defaults=[]
            )

        normal_params = []
        starparams = None
        kwparams = None

        # recognize normal params, starparams, kwparams
        for node in nodes:
            if isinstance(node, tuple):
                # ("kwparam", typedparam)
                if node[0] == "kwparam":
                    kwparams = node
                # ("starparam", typedparam)  or  ("starguard", ...)  (flat)
                elif node[0] in ("starparam", "starguard"):
                    starparams = node
                # (("starparam", typedparam), poststarparams) (nested)
                elif isinstance(node[0], tuple) and node[0][0] in ("starparam", "starguard"):
                    starparams = node
                else:
                    normal_params.append(node)
            else:
                normal_params.append(node)

        # normal params
        for param in normal_params:
            unpack_param(param, args, defaults)

        # process starparams if present
        if starparams:
            # (param_type, typedparam_or_None, poststar=(paramvalues, kwparams))
            param_type = None
            typed = None
            post = ([], None)

            # flat shape: ("starparam", typedparam) or ("starguard", something)
            if starparams[0] in ("starparam", "starguard"):
                param_type = starparams[0]
                #  (star, poststar)
                if len(starparams) > 1:
                    # ("starparam", typedparam)
                    typed = starparams[1] if param_type == "starparam" else None
                    if (isinstance(starparams[1], tuple) and len(starparams) == 2 and
                            isinstance(starparams[1][0], list)):
                        post = starparams[1]
                else:
                    typed = None
            elif isinstance(starparams[0], tuple) and starparams[0][0] in ("starparam", "starguard"):
                inner = starparams[0]
                param_type = inner[0]
                typed = inner[1] if len(inner) > 1 else None
                if len(starparams) > 1:
                    post = starparams[1]

            if param_type == "starparam":
                vararg = ensure_arg(typed)
            else:
                vararg = None

            # post is expected to be (paramvalues, kwparams)
            if post:
                paramvalues, maybe_kwparam = post
                for paramvalue in paramvalues:
                    unpack_param(paramvalue, kwonlyargs, kw_defaults)
                if maybe_kwparam:
                    # maybe_kwparam is ("kwparam", typedparam)
                    kwarg = ensure_arg(maybe_kwparam[1])

        # if kwparams standalone set kwarg
        if kwparams:
            kwarg = ensure_arg(kwparams[1])

        if defaults:
            # drop leading Nones so defaults align with the last args
            while defaults and defaults[0] is None:
                defaults.pop(0)

        return ast.arguments(
            posonlyargs=posonlyargs,
            args=args,
            vararg=vararg,
            kwonlyargs=kwonlyargs,
            kw_defaults=kw_defaults,
            kwarg=kwarg,
            defaults=defaults
        )

    def argvalue(self, nodes):
        arg_node = nodes[0]
        default = nodes[1] if len(nodes) == 2 else None
        return "argvalue", arg_node, default

    def stararg(self, nodes):
        argument = nodes[0]
        return "stararg", argument

    def kwargs(self, nodes):
        test = nodes[0]
        argvalues = nodes[1:] if len(nodes) > 1 else []
        return "kwargs", test, argvalues

    def starargs(self, nodes):
        return nodes

    def funccall(self, nodes):
        # Converts argvalue/stararg/kwargs into arguments
        function_name = nodes[0]
        prelim_args = nodes[1] if len(nodes) > 1 else []
        keywords = []
        args = []
        print(nodes)
        for arg in prelim_args:
            if isinstance(arg, list):
                for inner_arg in arg:
                    if isinstance(inner_arg, tuple) and inner_arg[0] == "stararg":
                        # starred argument
                        args.append(ast.Starred(inner_arg[1], ctx=ast.Load()))
                    elif isinstance(inner_arg, tuple) and inner_arg[0] == "kwargs":
                        # valued kwarg
                        if len(inner_arg[2]) > 0:
                            keywords.append(ast.keyword(arg=inner_arg[1], value=inner_arg[2]))
                        # **kwargs
                        else:
                            keywords.append(ast.keyword(arg=None, value=inner_arg[1]))
            elif isinstance(arg, tuple) and arg[0] == "argvalue":
                # normal value
                keywords.append(ast.keyword(arg=arg[1].id, value=arg[2]))
            elif isinstance(arg, tuple) and len(arg) == 2 and isinstance(arg[0], ast.JoinedStr) and isinstance(
                    arg[1], list):
                # Generator + comprehension
                joined_str, comprehensions = arg
                gen_expr = ast.GeneratorExp(
                    elt=joined_str,
                    generators=comprehensions
                )
                args.append(gen_expr)
            else:
                args.append(arg)

        return ast.Call(
            func=function_name,
            args=args,
            keywords=keywords
        )

    def getitem(self, nodes):
        object = nodes[0]
        subscript = nodes[1]
        return ast.Subscript(
            value=object,
            slice=subscript,
            ctx=ast.Load()
        )

    def getattr(self, nodes):
        object = nodes[0]
        attribute = nodes[1]

        return ast.Attribute(
            value=object,
            attr=attribute,
            ctx=ast.Load()
        )

    def arith_expr(self, nodes):
        expr = nodes[0]
        for i in range(1, len(nodes), 2):
            op_token = nodes[i]
            if isinstance(op_token, ast.AST):
                op_token = op_token.value
            right = nodes[i + 1]
            bin_op = self.ADD_OP_MAP[op_token]()
            expr = ast.BinOp(left=expr, op=bin_op, right=right)
        return expr

    def or_expr(self, nodes):
        expr = nodes[0]
        for i in range(1, len(nodes)):
            right = nodes[i]
            expr = ast.BinOp(left=expr, op=ast.BitOr(), right=right)
        return expr

    def xor_expr(self, nodes):
        expr = nodes[0]
        for i in range(1, len(nodes)):
            right = nodes[i]
            expr = ast.BinOp(left=expr, op=ast.BitXor(), right=right)
        return expr

    def and_expr(self, nodes):
        expr = nodes[0]
        for i in range(1, len(nodes)):
            right = nodes[i]
            expr = ast.BinOp(left=expr, op=ast.And(), right=right)
        return expr

    def shift_expr(self, nodes):
        expr = nodes[0]
        for i in range(1, len(nodes), 2):
            op_token = nodes[i]
            if isinstance(op_token, ast.AST):
                op_token = op_token.value
            right = nodes[i + 1]
            bin_op = self.SHIFT_OP_MAP[op_token]()
            expr = ast.BinOp(left=expr, op=bin_op, right=right)
        return expr

    def term(self, nodes):
        expr = nodes[0]
        for i in range(1, len(nodes), 2):
            op_token = nodes[i]
            if isinstance(op_token, ast.AST):
                op_token = op_token.value
            right = nodes[i + 1]
            bin_op = self.MUL_OP_MAP[op_token]()
            expr = ast.BinOp(left=expr, op=bin_op, right=right)
        return expr

    def factor(self, nodes):
        if len(nodes) == 1:
            # just a power expression
            return nodes[0]
        # unary operator case
        op_token = nodes[0]
        if isinstance(op_token, ast.AST):
            op_token = op_token.value
        operand = nodes[1]
        unary_op = self.UNARY_OP_MAP[op_token]()
        return ast.UnaryOp(op=unary_op, operand=operand)

    def list_comprehension(self, nodes):
        elt, generators = nodes[0]
        return ast.ListComp(elt=elt, generators=generators)

    def tuple_comprehension(self, nodes):
        elt, generators = nodes[0]
        return ast.GeneratorExp(elt=elt, generators=generators)

    def dict_comprehension(self, nodes):
        key_value_pair, generators = nodes[0]
        key, value = key_value_pair
        return ast.DictComp(key=key, value=value, generators=generators)

    def set_comprehension(self, nodes):
        elt, generators = nodes[0]
        return ast.SetComp(elt=elt, generators=generators)

    def comprehension(self, nodes):
        # comprehension
        comp_result = nodes[0]
        comp_fors = nodes[1]
        comp_if = nodes[2] if len(nodes) > 2 else None

        # Add the optional if to the last inst in the chain
        if comp_if:
            comp_fors[-1].ifs.append(comp_if)
        return comp_result, comp_fors

    def comp_for(self, nodes):
        async_flag = False
        index = 0
        # check for async
        if isinstance(nodes[0], str) and nodes[0] == 'async':
            async_flag = True
            index += 1

        target = nodes[index]
        iterable = nodes[index + 1]
        self._set_ctx(target, ast.Store())

        return ast.comprehension(
            target=target,
            iter=iterable,
            ifs=[],
            is_async=int(async_flag)
        )

    def comparison(self, nodes):
        lhs = nodes[0]
        ops = list()
        comparators = list()
        for i in range(1, len(nodes), 2):
            ops.append(self.CMP_OP_MAP[" ".join(nodes[i].split())]())
            comparators.append(nodes[i+1])
        return ast.Compare(left=lhs, ops=ops, comparators=comparators)

    def or_test(self, nodes):
        if len(nodes) == 1:
            return nodes[0]
        return ast.BoolOp(op=ast.Or(), values=nodes)

    def and_test(self, nodes):
        if len(nodes) == 1:
            return nodes[0]
        return ast.BoolOp(op=ast.And(), values=nodes)

    def not_test(self, nodes):
        return ast.UnaryOp(op=ast.Not(), operand=nodes[0])

    def exprlist(self, nodes):
        if len(nodes) == 1:
            node = nodes[0]
            return node
        else:
            return ast.Tuple(elts=nodes, ctx=ast.Load())

    def power(self, nodes):
        base = nodes[0]
        if len(nodes) == 1:
            return base
        exponent = nodes[1]
        return ast.BinOp(left=base, op=ast.Pow(), right=exponent)

    def lambda_paramvalue(self, nodes):
        name_node = nodes[0]
        default_node = nodes[1] if len(nodes) > 1 else None
        arg_node = ast.arg(arg=name_node,
                           annotation=None)
        return arg_node, default_node

    def lambda_starparams(self, nodes):
        # parameters with leading stars
        vararg = None
        kwonlyargs = []
        kw_defaults = []
        kwarg = None

        index = 0
        if len(nodes) > 0 and isinstance(nodes[0], str):
            vararg = ast.arg(arg=nodes[0], annotation=None)
            index = 1

        while index < len(nodes):
            node = nodes[index]
            if isinstance(node, tuple) and isinstance(node[0], ast.arg):
                kwonlyargs.append(node[0])
                kw_defaults.append(node[1])
            elif isinstance(node, dict) and "kwarg" in node:
                kwarg = node["kwarg"]
            index += 1

        return ast.arguments(
            posonlyargs=[], args=[],
            vararg=vararg,
            kwonlyargs=kwonlyargs,
            kw_defaults=kw_defaults,
            kwarg=kwarg,
            defaults=[]
        )

    def lambda_kwparams(self, nodes):
        argument = nodes[0]
        # return kwparams dict
        return {"kwarg": ast.arg(arg=argument, annotation=None)}

    def lambda_params(self, nodes):
        args = []
        defaults = []
        vararg = None
        kwonlyargs = []
        kw_defaults = []
        kwarg = None

        # construct the parameters
        for node in nodes:
            if isinstance(node, tuple) and isinstance(node[0], ast.arg):
                # lambda_paramvalue with optional default
                args.append(node[0])
                defaults.append(node[1])
            elif isinstance(node, str):
                # name -> positional arg, no default
                args.append(ast.arg(arg=node, annotation=None))
            elif isinstance(node, ast.arguments):
                if node.vararg:
                    vararg = node.vararg
                if node.kwarg:
                    kwarg = node.kwarg
                kwonlyargs.extend(node.kwonlyargs)
                kw_defaults.extend(node.kw_defaults)
            elif isinstance(node, dict) and "kwarg" in node:
                kwarg = node["kwarg"]

        return ast.arguments(
            posonlyargs=[],
            args=args,
            vararg=vararg,
            kwonlyargs=kwonlyargs,
            kw_defaults=kw_defaults,
            kwarg=kwarg,
            defaults=defaults
        )

    def lambdef(self, nodes):
        # lambda x, y=2, *args, **kw: x + y
        if len(nodes) == 2:
            params, body = nodes
        else:
            # set empty arguments for the lambda
            params = ast.arguments(
                posonlyargs=[], args=[], vararg=None,
                kwonlyargs=[], kw_defaults=[],
                kwarg=None, defaults=[]
            )
            body = nodes[0]

        return ast.Lambda(args=params, body=body)

    def assert_stmt(self, nodes):
        test = nodes[1]
        message = nodes[2] if nodes[1] else None
        return ast.Assert(test=test, msg=message)

    def dotted_name(self, nodes):
        parts = [str(node) for node in nodes if str(node) != "."]
        return ".".join(parts)

    def dotted_as_name(self, nodes):
        name = nodes[0]
        asname = nodes[1] if len(nodes) > 1 else None
        return name, asname

    def import_simple(self, nodes):
        aliases = [ast.alias(name=name, asname=asname) for name, asname in nodes]
        return ast.Import(names=aliases)

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

    def yield_expr(self, nodes):
        value = nodes[0] if len(nodes) > 0 else None
        return ast.Expr(ast.Yield(value))

    def yield_from(self, nodes):
        value = nodes[0] if len(nodes) > 0 else None
        return ast.Expr(ast.YieldFrom(value))

    def classdef(self, nodes):
        name = nodes[0]

        if len(nodes) == 3:
            bases_node = nodes[1]
            suite = nodes[2]
        else:
            bases_node = []
            suite = nodes[1]

        bases = bases_node if isinstance(bases_node, list) else []

        return ast.ClassDef(
            name=name,
            bases=bases,
            keywords=[],
            body=suite,
            decorator_list=[]
        )

    def await_expr(self, nodes):
        if len(nodes) > 1:
            return ast.Await(nodes[1])
        else:
            return nodes[0]


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


    def assign_expr(self, nodes):
        target = ast.Name(id=nodes[0], ctx=ast.Store())
        value = nodes[1]
        return ast.NamedExpr(target=target, value=value)

    def test(self, nodes):
        if len(nodes) == 3:
            # x if y else z
            body = nodes[0]
            test_cond = nodes[1]
            orelse = nodes[2]
            return ast.IfExp(test=test_cond, body=body, orelse=orelse)
        else:
            return nodes[0]

    def sliceop(self, nodes):
        step = nodes[0] if nodes else None
        return ":", step

    def slice(self, nodes):
        # Normal index x[1]
        if len(nodes) == 1:
            return nodes[0]
        else:
            lower = None
            upper = None
            step = None
            position = 0
            # Lower position x[2::]
            if nodes[position] != ":":
                lower = nodes[0]
                position += 2
            else:
                position += 1
            # Step amount x[::2]
            if len(nodes) > position and isinstance(nodes[position], tuple):
                upper = None
                step = nodes[position][1]
            # Upper pos x[:1:] [with step x[:1:2]]
            elif len(nodes) > position:
                upper = nodes[position]
                position += 1
                if len(nodes) > position and isinstance(nodes[position], tuple):
                    step = nodes[position][1]

            return ast.Slice(lower=lower, upper=upper, step=step)

    def subscript_tuple(self, nodes):
        if len(nodes) == 1:
            return nodes[0]
        else:
            return ast.Tuple(elts=nodes, ctx=ast.Load())

    def f_string(self, nodes):
        values = []
        # remove start and end
        for node in nodes[1:-1]:
            # string or expression
            if isinstance(node, str):
                values.append(ast.Constant(value=node))
            elif isinstance(node, ast.AST):
                values.append(node)
        # return the joined string
        return ast.JoinedStr(values=values)

    def f_expression_single(self, nodes):
        return self.f_expression(nodes)

    def f_expression_double(self, nodes):
        return self.f_expression(nodes)

    def f_expression(self, nodes):
        expr_node = nodes[0]
        conversion = -1
        format_spec = None

        for node in nodes[1:]:
            # check for the conversion
            if isinstance(node, str):
                conv_map = {"r": ord('r'), "s": ord('s'), "a": ord('a')}
                conversion = conv_map[node.lower()]
            elif isinstance(node, ast.AST):
                format_spec = node

        return ast.FormattedValue(
            value=expr_node,
            conversion=conversion,
            format_spec=format_spec
        )

    def conversion(self, token):
        return token[0]

    def format_spec_single(self, nodes):
        return self.format_spec(nodes)

    def format_spec_double(self, nodes):
        return self.format_spec(nodes)

    def format_spec(self, nodes):
        # return if only test value
        if len(nodes) == 1 and isinstance(nodes[0], str):
            return ast.Constant(value=nodes[0])
        values = []
        for node in nodes:
            # string or expression
            if isinstance(node, str):
                values.append(ast.Constant(value=node))
            elif isinstance(node, ast.AST):
                values.append(node)
        return ast.JoinedStr(values=values)

    def tuple(selfs, nodes):
        return ast.Tuple(elts=nodes, ctx=ast.Load())

    def testlist_tuple(self, nodes):
        return ast.Tuple(elts=nodes, ctx=ast.Load())

    def string_concat(self, nodes):
        concatenated_value = ''.join(node.value for node in nodes)
        return ast.Constant(value=concatenated_value)

    def DEC_NUMBER(self, nodes):
        value = nodes.value.replace("_", "")
        return ast.Constant(value=int(value, 10))

    def HEX_NUMBER(self, nodes):
        value = nodes.value.replace("_", "")
        return ast.Constant(value=int(value, 16))

    def OCT_NUMBER(self, nodes):
        value = nodes.value.replace("_", "")
        return ast.Constant(value=int(value, 8))

    def BIN_NUMBER(self, nodes) -> ast.Constant:
        value = nodes.value.replace("_", "")
        return ast.Constant(value=int(value, 2))


    ######################## ONELINE ##########################

    # -- Non-terminals --
    number = lambda self, nodes: nodes[0]
    string = lambda self, nodes: nodes[0]
    var = lambda self, nodes: nodes[0]
    single_input = lambda self, nodes: nodes[0]
    file_input = lambda self, nodes: ast.Module(body=nodes, type_ignores=[])
    eval_input = lambda self, nodes: nodes[0]
    pass_stmt = lambda self, _ : ast.Pass()
    expr_stmt = lambda self, nodes: ast.Expr(value=nodes[0])
    star_expr = lambda self, nodes: ast.Starred(value=nodes[0], ctx=ast.Load())
    assign_stmt = lambda self, nodes: nodes[0]
    name = lambda self, nodes: nodes[0]
    var = lambda self, nodes: ast.Name(id=nodes[0], ctx=ast.Load())
    return_stmt = lambda self, nodes: ast.Return(value=nodes[0] if len(nodes) > 0 else None)
    del_stmt = lambda self, nodes: ast.Del(value=nodes[0])
    break_stmt = lambda self, _: ast.Break()
    continue_stmt = lambda self, _: ast.Continue()
    suite = lambda self, nodes: nodes
    comp_op = lambda self, nodes: nodes[0]
    elifs = lambda self, nodes: nodes
    comp_fors = lambda self, nodes: nodes
    lambdef_nocond = lambda self, nodes: nodes
    global_stmt = lambda self, nodes: ast.Global(nodes)
    nonlocal_stmt = lambda self, nodes: ast.Nonlocal(nodes)
    dotted_as_names = lambda self, nodes: nodes
    import_as_names = lambda self, nodes: nodes
    import_stmt = lambda self, nodes: nodes[0]
    yield_stmt = lambda self, nodes: nodes[0]
    arguments = lambda self, nodes: nodes
    except_clauses = lambda self, nodes: nodes
    decorators = lambda self, nodes: nodes
    with_items = lambda self, nodes: nodes
    encoding_decl = lambda self, nodes: nodes[0]
    const_none = lambda self, _: ast.Constant(value=None)
    const_true = lambda self, _: ast.Constant(value=True)
    const_false = lambda self, _: ast.Constant(value=False)
    ellipsis = lambda self, _: ast.Constant(value=Ellipsis)
    pos_arg_pattern = lambda self, nodes: nodes
    keyw_arg_pattern = lambda self, nodes: nodes
    f_string_content_single = lambda self, nodes: nodes[0]
    f_string_content_double = lambda self, nodes: nodes[0]

    # -- Terminals --
    IMAG_NUMBER = lambda self, token: ast.Constant(value=complex(token.value))
    FLOAT_NUMBER = lambda self, token: ast.Constant(value=float(token.value))
    DECIMAL = lambda self, token: ast.Constant(value=float(token.value))
    STRING = lambda self, token: ast.Constant(value=token.value[1:-1])
    LONG_STRING = lambda self, token: ast.Constant(value=token.value[3:-3])
    NAME = lambda self, token: token.value
    ASYNC = lambda self, token: token.value
    SLASH = lambda self, token: token.value
    AWAIT = lambda self, token: token.value
    MARK = lambda self, token: token.value
    FSTRING_TEXT_SINGLE = lambda self, token: token.value
    FSTRING_TEXT_DOUBLE = lambda self, token: token.value
    FSTRING_SINGLE_START = lambda self, token: token.value
    FSTRING_DOUBLE_START = lambda self, token: token.value
    FSTRING_SINGLE_END = lambda self, token: token.value
    FSTRING_DOUBLE_END = lambda self, token: token.value



