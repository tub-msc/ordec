# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from lark import Transformer
import ast

class PythonTransformer(Transformer):
    """
    Transformer that transforms any Python code back into a Python AST.
    This Class represents the base of the ORD language
    """

    # Variables
    # ---------

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

    # Helpers
    # -------

    def _flatten_body(self, body):
        # flatten ast statements
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
        # Set context for load / store values
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
            self._set_ctx(node.value, ast.Load())

        # Subscript: arr[0]
        elif isinstance(node, ast.Subscript):
            node.ctx = ctx
            self._set_ctx(node.value, ast.Load())
            self._set_ctx(node.slice, ast.Load())

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

    # Terminals
    # ---------

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

    IMAG_NUMBER = lambda self, token: ast.Constant(value=complex(token.value))
    FLOAT_NUMBER = lambda self, token: ast.Constant(value=float(token.value))
    DECIMAL = lambda self, token: ast.Constant(value=float(token.value))
    NAME = lambda self, token: token.value
    ASYNC = lambda self, token: token.value
    AWAIT = lambda self, token: token.value
    MARK = lambda self, token: token.value
    FSTRING_TEXT_SINGLE = lambda self, token: token.value
    FSTRING_TEXT_DOUBLE = lambda self, token: token.value
    FSTRING_SINGLE_START = lambda self, token: token.value
    FSTRING_DOUBLE_START = lambda self, token: token.value
    FSTRING_SINGLE_END = lambda self, token: token.value
    FSTRING_DOUBLE_END = lambda self, token: token.value
    SLASH = lambda self, token: token.value
    STRING_OTHER_PREFIX = lambda self, token: token.value
    MATCH = lambda self, token: token.value

    # Statements
    # ----------

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

    pass_stmt = lambda self, _: ast.Pass()
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

    # Compound Statements
    # -------------------

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
        if isinstance(target, list):
            target = ast.Tuple(target, ast.Store())
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
        return ast.ExceptHandler(type=exc_type, name=name, body=suite)

    def with_stmt(self, nodes):
        with_items = nodes[0]
        suite = nodes [1]
        return ast.With(items=with_items, body=suite)

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

    # Expressions
    # -----------

    def funccall(self, nodes):
        # Converts argvalue/stararg/kwargs into arguments
        function_name = nodes[0]
        prelim_args = nodes[1] if len(nodes) > 1 else []
        keywords = []
        args = []
        for arg in prelim_args:
            # star arguments
            if isinstance(arg, list):
                for inner_arg in arg:
                    if isinstance(inner_arg, tuple) and inner_arg[0] == "stararg":
                        args.append(ast.Starred(inner_arg[1], ctx=ast.Load()))
                    elif isinstance(inner_arg, tuple) and inner_arg[0] == "argvalue":
                        keywords.append(ast.keyword(arg=inner_arg[1].id, value=inner_arg[2]))
                    elif isinstance(inner_arg, tuple) and inner_arg[0] == "kwargs":
                        keywords.append(ast.keyword(arg=None, value=inner_arg[1]))
                        # valued kwarg
                        if len(inner_arg[2]) > 0:
                            for kw in inner_arg[2]:
                                keywords.append(ast.keyword(arg=kw[1].id, value=kw[2]))
            # valued argument
            elif isinstance(arg, tuple) and arg[0] == "argvalue":
                # normal value
                keywords.append(ast.keyword(arg=arg[1].id, value=arg[2]))
            # keyword arguments
            elif isinstance(arg, tuple) and arg[0] == "kwargs":
                keywords.append(ast.keyword(arg=None, value=arg[1]))
                # valued kwarg
                if len(arg[2]) > 0:
                    for kw in arg[2]:
                        keywords.append(ast.keyword(arg=kw[1].id, value=kw[2]))
            # comprehension or single argument
            elif isinstance(arg, tuple) and len(arg) == 2 and isinstance(arg[1], list):
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
        def concat_attributes(node, new_name):
            if isinstance(node, ast.Attribute):
                node.value = concat_attributes(node.value, new_name)
                return node
            elif isinstance(node, ast.Name):
                if isinstance(new_name, ast.Name):
                    return ast.Attribute(
                        value=ast.Name(id=new_name.id, ctx=ast.Load()),
                        attr=node.id,
                        ctx=ast.Load()
                    )
                else:
                    return new_name
            else:
                return ast.Attribute(
                    value=new_name,
                    attr=str(node),
                    ctx=ast.Load()
                )
        lhs = nodes[0]
        rhs = nodes[1]
        return concat_attributes(rhs, lhs)

    def arith_expr(self, nodes):
        expr = nodes[0]
        for i in range(1, len(nodes), 2):
            op_token = nodes[i]
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
            expr = ast.BinOp(left=expr, op=ast.BitAnd(), right=right)
        return expr

    def shift_expr(self, nodes):
        expr = nodes[0]
        for i in range(1, len(nodes), 2):
            op_token = nodes[i]
            right = nodes[i + 1]
            bin_op = self.SHIFT_OP_MAP[op_token]()
            expr = ast.BinOp(left=expr, op=bin_op, right=right)
        return expr

    def term(self, nodes):
        expr = nodes[0]
        for i in range(1, len(nodes), 2):
            op_token = nodes[i]
            right = nodes[i + 1]
            bin_op = self.MUL_OP_MAP[op_token]()
            expr = ast.BinOp(left=expr, op=bin_op, right=right)
        return expr

    def factor(self, nodes):
        # unary operator case
        op_token = nodes[0]
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

        if isinstance(target, list):
            target = ast.Tuple(target)
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
            comparators.append(nodes[i + 1])
        return ast.Compare(left=lhs, ops=ops, comparators=comparators)

    def or_test(self, nodes):
        return ast.BoolOp(op=ast.Or(), values=nodes)

    def and_test(self, nodes):
        return ast.BoolOp(op=ast.And(), values=nodes)

    def not_test(self, nodes):
        return ast.UnaryOp(op=ast.Not(), operand=nodes[0])

    def power(self, nodes):
        base = nodes[0]
        exponent = nodes[1]
        return ast.BinOp(left=base, op=ast.Pow(), right=exponent)

    def yield_expr(self, nodes):
        value = nodes[0] if len(nodes) > 0 else None
        return ast.Expr(ast.Yield(value))

    def yield_from(self, nodes):
        value = nodes[0] if len(nodes) > 0 else None
        return ast.Expr(ast.YieldFrom(value))

    def await_expr(self, nodes):
        return ast.Await(nodes[1])

    def assign_expr(self, nodes):
        target = ast.Name(id=nodes[0], ctx=ast.Store())
        value = nodes[1]
        return ast.NamedExpr(target=target, value=value)

    def test(self, nodes):
        # x if y else z
        body = nodes[0]
        test_cond = nodes[1]
        orelse = nodes[2]
        return ast.IfExp(test=test_cond, body=body, orelse=orelse)

    def sliceop(self, nodes):
        step = nodes[0] if nodes else None
        return ":", step

    def slice(self, nodes):
        # Normal index x[1]
        if len(nodes) == 1:
            if isinstance(nodes[0], str) and nodes[0] == ":":
                return ast.Slice(lower=None, upper=None, step=None)
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
        return ast.Tuple(elts=nodes, ctx=ast.Load())

    def tuple(selfs, nodes):
        return ast.Tuple(elts=nodes, ctx=ast.Load())

    def testlist_tuple(self, nodes):
        return ast.Tuple(elts=nodes, ctx=ast.Load())

    @staticmethod
    def merge_adjacent_strings(items):
        merged_buffer = []
        temp_buffer = []

        for item in items:
            # String concat
            if isinstance(item, str):
                temp_buffer.append(item)
            # f string
            elif isinstance(item, ast.Constant):
                temp_buffer.append(item.value)
            else:
                if temp_buffer:
                    merged_buffer.append(ast.Constant(value="".join(temp_buffer)))
                    temp_buffer.clear()
                merged_buffer.append(item)
        if temp_buffer:
            merged_buffer.append(ast.Constant(value="".join(temp_buffer)))
        return merged_buffer

    def string_concat(self, nodes):
        merged_string = self.merge_adjacent_strings(nodes)
        # Return if only one value
        if len(merged_string) == 1:
            return merged_string[0]
        return_string = []
        # Merge everything into one joined string
        for string in merged_string:
            if isinstance(string, ast.Constant):
                return_string.append(string)
            if isinstance(string, ast.JoinedStr):
                return_string.extend(string.values)
        return ast.JoinedStr(values=return_string)

    def f_string(self, nodes):
        values = self.merge_adjacent_strings(nodes[1:-1])
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
        values = []
        for node in nodes:
            # string or expression
            if isinstance(node, str):
                values.append(ast.Constant(value=node))
            elif isinstance(node, ast.AST):
                values.append(self.f_expression([node]))
        return ast.JoinedStr(values=values)

    def string(self, nodes):
        current_string = nodes[0]
        if isinstance(current_string, ast.JoinedStr):
            return current_string
        else:
            prefix, string = current_string
            if len(prefix) == 0:
                return ast.Constant(value=string)
            elif 'b' in prefix:
                return ast.Constant(value=string.encode('utf-8'))
            elif 'u' == prefix:
                return ast.Constant(value=string, kind=prefix)
            else:
                return ast.Constant(value=string)

    def STRING(self, token):
        current_string = token.value
        string_parts = current_string.split(current_string[-1])
        if string_parts[0] == '':
            joined = '\''.join(string_parts[1:-1])
            return '', joined
        else:
            joined = '\''.join(string_parts[1:-1])
            return string_parts[0], joined

    def LONG_STRING(self, token):
        current_string = token.value
        string_parts = current_string.split(current_string[-3:])
        if string_parts[0] == '':
            joined = '\''.join(string_parts[1:-1])
            return '', joined
        else:
            joined = '\''.join(string_parts[1:-1])
            return string_parts[0], joined

    def var(self, nodes):
        return ast.Name(id=nodes[0], ctx=ast.Load())

    number = lambda self, nodes: nodes[0]
    star_expr = lambda self, nodes: ast.Starred(value=nodes[0], ctx=ast.Load())
    name = lambda self, nodes: nodes[0]
    comp_op = lambda self, nodes: nodes[0]
    ellipsis = lambda self, _: ast.Constant(value=Ellipsis)
    f_string_content_single = lambda self, nodes: nodes[0]
    f_string_content_double = lambda self, nodes: nodes[0]
    f_string_escaped_content_double = lambda self, nodes: nodes[0]
    f_string_escaped_content_single = lambda self, nodes: nodes[0]
    literal_open_brace = lambda self, _: '{'
    literal_close_brace = lambda self, _: '}'
    exprlist = lambda self, nodes: nodes

    # Definitions
    # -----------

    def decorator(self, nodes):
        dotted_name = nodes[0]
        func_name = ast.Name(id=dotted_name, ctx=ast.Load())

        if len(nodes) > 1 and nodes[1]:
            args = []
            keywords = []
            for value in nodes[1]:
                if isinstance(value, ast.Constant):
                    args.append(value)
                elif isinstance(value, tuple) and value[0] == "argvalue":
                    keywords.append(ast.keyword(arg=value[1].id, value=value[2]))
            return ast.Call(func=func_name, args=args, keywords=keywords)
        return func_name

    def decorated(self, nodes):
        decorators = nodes[0]
        definition = nodes[1]
        # classdef, funcdef, async funcdef
        definition.decorator_list = decorators
        return definition

    def funcdef(self, nodes):
        name = str(nodes[0])
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

        return ast.FunctionDef(
            name=name,
            args=parameters,
            body=suite,
            decorator_list=[],
            type_params=[],
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
            type_params=[],
            returns=returns
        )

    def classdef(self, nodes):
        name = nodes[0]

        if len(nodes) == 3:
            bases_node = nodes[1]
            suite = nodes[2]
        else:
            bases_node = []
            suite = nodes[1]

        bases = []
        keywords = []
        for base in bases_node:
            if isinstance(base, tuple) and base[0] == "argvalue":
                keywords.append(ast.keyword(arg=base[1].id, value=base[2]))
            else:
                bases.append(base)

        return ast.ClassDef(
            name=name,
            bases=bases,
            keywords=keywords,
            body=suite,
            decorator_list=[],
            type_params=[]
        )

    decorators = lambda self, nodes: nodes
    arguments = lambda self, nodes: nodes

    # Parameters / Arguments
    # ----------------------

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

        # Split in args and pos_args
        slash_index = normal_params.index("/") if "/" in normal_params else -1
        if slash_index != -1:
            params_pos = normal_params[:slash_index]
            params_args = normal_params[slash_index + 1:]
        else:
            params_pos = []
            params_args = normal_params[:]
        for param in params_pos:
            unpack_param(param, posonlyargs, defaults)
        for param in params_args:
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

    def kwparams(self, nodes):
        typedparam = nodes[0]
        return "kwparam", typedparam

    def poststarparams(self, nodes):
        if len(nodes) == 0:
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
        return "arg_with_default", typedparam, default

    def typedparam(self, nodes):
        # x:Int
        name = nodes[0]
        annotation = nodes[1] if len(nodes) > 1 else None
        return ast.arg(arg=name, annotation=annotation)

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

    starargs_part = lambda self, nodes: nodes

    # Match Case
    # ----------

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

    # Top-Level
    # ---------

    single_input = lambda self, nodes: nodes[0]
    file_input = lambda self, nodes: ast.Module(body=self._flatten_body(nodes), type_ignores=[])
    eval_input = lambda self, nodes: nodes[0]
