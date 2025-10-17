# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from lark import Transformer
import ast

# ordec imports
from .misc import Misc

class ExpressionTransformer(Transformer, Misc):

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

    def funccall(self, nodes):
        # Converts argvalue/stararg/kwargs into arguments
        function_name = nodes[0]
        prelim_args = nodes[1] if len(nodes) > 1 else []
        keywords = []
        args = []
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
            elif isinstance(arg, tuple) and arg[0] == "kwargs":
                # valued kwarg
                if len(arg[2]) > 0:
                    keywords.append(ast.keyword(arg=arg[1], value=arg[2]))
                # **kwargs
                else:
                    keywords.append(ast.keyword(arg=None, value=arg[1]))
            elif isinstance(arg, tuple) and len(arg) == 2  and isinstance(arg[1], list):
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

    def getitem(self, nodes):
        object = nodes[0]
        subscript = nodes[1]
        return ast.Subscript(
            value=object,
            slice=subscript,
            ctx=ast.Load()
        )

    def getattr(self, nodes):
        obj = nodes[0]
        attr_token = nodes[1]

        return ast.Attribute(
            value=obj,
            attr=str(attr_token),
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

    def set(self, nodes):
        return ast.Set(nodes)

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

    def yield_expr(self, nodes):
        value = nodes[0] if len(nodes) > 0 else None
        return ast.Expr(ast.Yield(value))

    def yield_from(self, nodes):
        value = nodes[0] if len(nodes) > 0 else None
        return ast.Expr(ast.YieldFrom(value))

    def await_expr(self, nodes):
        if len(nodes) > 1:
            return ast.Await(nodes[1])
        else:
            return nodes[0]

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
            if isinstance(nodes[0], str) and nodes[0] == ":":
                return ast.Slice(lower=None, upper=None, step=None)
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

    def tuple(selfs, nodes):
        return ast.Tuple(elts=nodes, ctx=ast.Load())

    def testlist_tuple(self, nodes):
        return ast.Tuple(elts=nodes, ctx=ast.Load())

    def string_concat(self, nodes):
        values = []
        for node in nodes:
            if isinstance(node, ast.JoinedStr):
                values.extend(node.values)
            else:
                values.append(ast.Constant(node))
        return ast.JoinedStr(values=values)

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

    number = lambda self, nodes: nodes[0]
    string = lambda self, nodes: nodes[0]
    var = lambda self, nodes: nodes[0]
    star_expr = lambda self, nodes: ast.Starred(value=nodes[0], ctx=ast.Load())
    name = lambda self, nodes: nodes[0]
    var = lambda self, nodes: ast.Name(id=nodes[0], ctx=ast.Load())
    comp_op = lambda self, nodes: nodes[0]
    ellipsis = lambda self, _: ast.Constant(value=Ellipsis)
    f_string_content_single = lambda self, nodes: nodes[0]
    f_string_content_double = lambda self, nodes: nodes[0]