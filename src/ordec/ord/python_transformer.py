# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from lark import Transformer, v_args
import ast
import unicodedata

class PythonTransformer(Transformer):
    """
    Transform parsed Python syntax into a Python AST.

    This generic Python transformer provides the Python-language foundation for
    ORD. It builds standard ``ast`` nodes, uses Python 3.13 syntax and AST
    behavior as its primary reference, and raises ``SyntaxError`` for parsed
    forms that are not valid Python syntax.
    """

    # -------------------------------------------------------------------------
    # Variables
    # -------------------------------------------------------------------------

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
        '!=': ast.NotEq,
        'in': ast.In,
        'not in': ast.NotIn,
        'is': ast.Is,
        'is not': ast.IsNot,
    }

    STRING_ESCAPE_MAP = {
        "\\": "\\",
        "'": "'",
        '"': '"',
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
    }

    BYTES_ESCAPE_MAP = {
        "\\": ord("\\"),
        "'": ord("'"),
        '"': ord('"'),
        "a": 7,
        "b": 8,
        "f": 12,
        "n": 10,
        "r": 13,
        "t": 9,
        "v": 11,
    }

    FSTRING_LITERAL_CLOSE_BRACE = object()

    def __init__(self, source_text=""):
        super().__init__()
        self.source_text = source_text

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _call_userfunc(self, tree, new_children=None):
        result = super()._call_userfunc(tree, new_children)
        if isinstance(result, ast.AST) and hasattr(tree, 'meta'):
            meta = tree.meta
            if meta.line is not None:
                result.lineno = meta.line
                result.col_offset = (meta.column or 1) - 1
            if meta.end_line is not None:
                result.end_lineno = meta.end_line
                result.end_col_offset = (meta.end_column or 1) - 1
        return result

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
            if isinstance(ctx, ast.Del):
                raise SyntaxError("cannot delete starred")
            node.ctx = ctx
            self._set_ctx(node.value, ctx)

        else:
            if isinstance(ctx, ast.Store):
                raise SyntaxError("invalid assignment target")
            if isinstance(ctx, ast.Del):
                raise SyntaxError("invalid deletion target")

    @staticmethod
    def _contains_unparenthesized_namedexpr(node):
        # The grammar accepts `test` in several places where Python only allows
        # a named expression when it is parenthesized or nested in a container.
        if node is None:
            return False
        if (isinstance(node, ast.NamedExpr) and
                not getattr(node, "_parenthesized_expr", False)):
            return True
        if (isinstance(node, ast.Tuple) and
                not getattr(node, "_parenthesized_expr", False)):
            return any(
                isinstance(elt, ast.NamedExpr) and
                not getattr(elt, "_parenthesized_expr", False)
                for elt in node.elts
            )
        return False

    @staticmethod
    def merge_adjacent_strings(items):
        merged_buffer = []
        temp_value = None
        temp_kind = None

        for item in items:
            if isinstance(item, str):
                item = ast.Constant(value=item)

            if isinstance(item, ast.Constant) and isinstance(item.value, (str, bytes)):
                if temp_value is None:
                    temp_value = item.value
                    temp_kind = item.kind
                # Merge items of the same type directly
                elif isinstance(item.value, type(temp_value)):
                    temp_value += item.value
                    if temp_kind is None:
                        temp_kind = item.kind
                # Append if the type differs
                else:
                    merged_buffer.append(ast.Constant(value=temp_value, kind=temp_kind))
                    temp_value = item.value
                    temp_kind = item.kind
                continue
            # Append if not string or bytes
            if temp_value is not None:
                merged_buffer.append(ast.Constant(value=temp_value, kind=temp_kind))
                temp_value = None
                temp_kind = None

            merged_buffer.append(item)

        if temp_value is not None:
            merged_buffer.append(ast.Constant(value=temp_value, kind=temp_kind))
        return merged_buffer

    def _debug_prefix_from_source(self, meta):
        # Parser additions:
        # - propagate_positions=True provides start_pos/end_pos on f_expression nodes.
        # - source_text contains the parsed source.
        segment = self.source_text[meta.start_pos:meta.end_pos]
        inner = segment[1:-1]
        eq_index = inner.rfind("=")

        after_eq = eq_index + 1
        while after_eq < len(inner) and inner[after_eq] in " \t":
            after_eq += 1
        return inner[:after_eq]

    def _normalize_joined_str(self, node, decode_literals):
        """
        Merge adjacent literal Constant(str) pieces into one piece
        and recursively normalize joined strings
        """
        normalized_values = []
        literal_buffer = []

        def flush_literal_buffer():
            if literal_buffer:
                literal = "".join(literal_buffer)
                if literal:
                    normalized_values.append(ast.Constant(value=literal))
                literal_buffer.clear()

        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                literal = value.value
                if decode_literals:
                    literal = self._decode_string_escapes(literal)
                literal_buffer.append(literal)
                continue

            flush_literal_buffer()
            if isinstance(value, ast.FormattedValue) and isinstance(value.format_spec, ast.JoinedStr):
                value.format_spec = self._normalize_joined_str(
                    value.format_spec,
                    decode_literals=decode_literals
                )
            normalized_values.append(value)

        flush_literal_buffer()
        return ast.JoinedStr(values=normalized_values)

    @staticmethod
    def _split_string_literal(token_value):
        """Extract string literal"""
        quote_start = 0
        while quote_start < len(token_value) and token_value[quote_start].isalpha():
            quote_start += 1

        prefix = token_value[:quote_start]
        if token_value[quote_start:quote_start + 3] in ('"""', "'''"):
            quote_len = 3
        else:
            quote_len = 1

        content = token_value[quote_start + quote_len:-quote_len]
        return prefix, content

    @staticmethod
    def _is_hex_digits(value):
        return all(ch in "0123456789abcdefABCDEF" for ch in value)

    def _decode_string_escapes(self, value):
        # Decode Python literal escape sequences so transformed AST constants match Python.
        decoded = []
        i = 0
        while i < len(value):
            char = value[i]
            if char != "\\":
                decoded.append(char)
                i += 1
                continue

            if i + 1 >= len(value):
                decoded.append("\\")
                i += 1
                continue

            esc = value[i + 1]
            if esc == "\n":
                i += 2
                continue
            if esc in self.STRING_ESCAPE_MAP:
                decoded.append(self.STRING_ESCAPE_MAP[esc])
                i += 2
                continue
            if esc in "01234567":
                j = i + 1
                while j < len(value) and j < i + 4 and value[j] in "01234567":
                    j += 1
                decoded.append(chr(int(value[i + 1:j], 8)))
                i = j
                continue
            if esc == "x":
                hex_digits = value[i + 2:i + 4]
                if len(hex_digits) != 2 or not self._is_hex_digits(hex_digits):
                    raise SyntaxError("invalid \\x escape sequence")
                decoded.append(chr(int(hex_digits, 16)))
                i += 4
                continue
            if esc == "u":
                hex_digits = value[i + 2:i + 6]
                if len(hex_digits) != 4 or not self._is_hex_digits(hex_digits):
                    raise SyntaxError("invalid \\u escape sequence")
                decoded.append(chr(int(hex_digits, 16)))
                i += 6
                continue
            if esc == "U":
                hex_digits = value[i + 2:i + 10]
                if len(hex_digits) != 8 or not self._is_hex_digits(hex_digits):
                    raise SyntaxError("invalid \\U escape sequence")
                decoded.append(chr(int(hex_digits, 16)))
                i += 10
                continue
            if esc == "N" and i + 2 < len(value) and value[i + 2] == "{":
                closing_brace = value.find("}", i + 3)
                if closing_brace == -1:
                    raise SyntaxError("malformed \\N escape sequence")
                unicode_name = value[i + 3:closing_brace]
                try:
                    decoded.append(unicodedata.lookup(unicode_name))
                except KeyError as exc:
                    raise SyntaxError("unknown Unicode character name") from exc
                i = closing_brace + 1
                continue

            decoded.append("\\")
            decoded.append(esc)
            i += 2
        return "".join(decoded)

    def _decode_bytes_escapes(self, value):
        decoded = bytearray()
        i = 0
        while i < len(value):
            char = value[i]
            if char != "\\":
                if ord(char) > 0x7F:
                    raise SyntaxError("bytes literals may only contain ASCII characters")
                decoded.append(ord(char))
                i += 1
                continue

            if i + 1 >= len(value):
                decoded.append(ord("\\"))
                i += 1
                continue

            esc = value[i + 1]
            if esc == "\n":
                i += 2
                continue
            if esc in self.BYTES_ESCAPE_MAP:
                decoded.append(self.BYTES_ESCAPE_MAP[esc])
                i += 2
                continue
            if esc in "01234567":
                j = i + 1
                while j < len(value) and j < i + 4 and value[j] in "01234567":
                    j += 1
                decoded.append(int(value[i + 1:j], 8) & 0xFF)
                i = j
                continue
            if esc == "x":
                hex_digits = value[i + 2:i + 4]
                if len(hex_digits) != 2 or not self._is_hex_digits(hex_digits):
                    raise SyntaxError("invalid \\x escape sequence")
                decoded.append(int(hex_digits, 16))
                i += 4
                continue

            decoded.append(ord("\\"))
            decoded.append(ord(esc))
            i += 2
        return bytes(decoded)

    # -------------------------------------------------------------------------
    # Terminals
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Statements
    # -------------------------------------------------------------------------

    def expr_stmt(self, nodes):
        if self._contains_unparenthesized_namedexpr(nodes[0]):
            raise SyntaxError(
                "assignment expression cannot be used in a bare expression statement"
            )
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
        return [node for node in nodes if node is not None]

    def assign(self, nodes):
        targets = nodes[:-1]
        value = nodes[-1]
        if self._contains_unparenthesized_namedexpr(value):
            raise SyntaxError("invalid assignment expression")
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
        if self._contains_unparenthesized_namedexpr(value):
            raise SyntaxError("invalid assignment expression")
        if not isinstance(target, (ast.Name, ast.Attribute, ast.Subscript)):
            raise SyntaxError("illegal expression for augmented assignment")
        self._set_ctx(target, ast.Store())
        return ast.AugAssign(target=target, op=op, value=value)

    def annassign(self, nodes):
        target = nodes[0]
        target_type = nodes[1]
        value = nodes[2] if len(nodes) > 2 else None
        if (self._contains_unparenthesized_namedexpr(target_type) or
                self._contains_unparenthesized_namedexpr(value)):
            raise SyntaxError("invalid assignment expression")
        if not isinstance(target, (ast.Name, ast.Attribute, ast.Subscript)):
            raise SyntaxError("illegal target for annotation")
        self._set_ctx(target, ast.Store())
        simple = 1 if (
            isinstance(target, ast.Name) and
            not getattr(target, "_parenthesized_expr", False)
        ) else 0
        return ast.AnnAssign(
            target=target,
            annotation=target_type,
            value=value,
            simple=simple
        )

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

        if (self._contains_unparenthesized_namedexpr(exc) or
                self._contains_unparenthesized_namedexpr(cause)):
            raise SyntaxError("invalid assignment expression")
        return ast.Raise(exc=exc, cause=cause)

    def assert_stmt(self, nodes):
        test = nodes[0]
        if self._contains_unparenthesized_namedexpr(test):
            raise SyntaxError("invalid assignment expression")
        message = nodes[1] if len(nodes) > 1 else None
        if self._contains_unparenthesized_namedexpr(message):
            raise SyntaxError("invalid assignment expression")
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
        for target in del_stmts:
            self._set_ctx(target, ast.Del())
        return ast.Delete(targets=del_stmts)

    pass_stmt = lambda self, _: ast.Pass()
    assign_stmt = lambda self, nodes: nodes[0]
    def return_stmt(self, nodes):
        value = nodes[0] if len(nodes) > 0 else None
        if self._contains_unparenthesized_namedexpr(value):
            raise SyntaxError("invalid assignment expression")
        return ast.Return(value=value)
    break_stmt = lambda self, _: ast.Break()
    continue_stmt = lambda self, _: ast.Continue()
    global_stmt = lambda self, nodes: ast.Global(nodes)
    nonlocal_stmt = lambda self, nodes: ast.Nonlocal(nodes)
    dotted_as_names = lambda self, nodes: nodes
    import_as_names = lambda self, nodes: nodes
    import_stmt = lambda self, nodes: nodes[0]
    yield_stmt = lambda self, nodes: ast.Expr(value=nodes[0])

    # -------------------------------------------------------------------------
    # Compound Statements
    # -------------------------------------------------------------------------

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
        if self._contains_unparenthesized_namedexpr(iterator):
            raise SyntaxError("invalid assignment expression")
        body = nodes[2]
        or_else = nodes[3] if len(nodes) > 3 else []
        return ast.For(target=target,
                       iter=iterator,
                       body=body,
                       orelse=or_else)

    def try_stmt(self, nodes):
        # try: suite except_clauses [else: suite] [finally]
        body = nodes[0]
        raw_handlers = nodes[1]
        is_star = any(
            isinstance(handler, tuple) and handler[0] == "except_star"
            for handler in raw_handlers
        )
        if is_star and any(
            not (isinstance(handler, tuple) and handler[0] == "except_star")
            for handler in raw_handlers
        ):
            raise SyntaxError("cannot mix except and except*")
        handlers = [
            handler[1]
            if isinstance(handler, tuple) and handler[0] == "except_star"
            else handler
            for handler in raw_handlers
        ]
        for handler in handlers[:-1]:
            if handler.type is None:
                raise SyntaxError("default 'except:' must be last")
        orelse = nodes[2] if len(nodes) > 2 and not isinstance(nodes[2], tuple) else []
        if len(orelse) > 0:
            finalbody = nodes[3][1] if len(nodes) > 3 else []
        else:
            finalbody = nodes[2][1] if len(nodes) > 2 else []
        if is_star:
            return ast.TryStar(
                body=body,
                handlers=handlers,
                orelse=orelse,
                finalbody=finalbody
            )
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

    def except_star_clause(self, nodes):
        if len(nodes) == 2:
            exc_type = nodes[0]
            name = None
            suite = nodes[1]
        else:
            exc_type = nodes[0]
            name = nodes[1]
            suite = nodes[2]
        return "except_star", ast.ExceptHandler(type=exc_type, name=name, body=suite)

    def with_stmt(self, nodes):
        with_items = nodes[0]
        if isinstance(with_items, ast.withitem):
            with_items = [with_items]
        suite = nodes[1]
        if (len(with_items) == 1 and
                with_items[0].optional_vars is None and
                isinstance(with_items[0].context_expr, ast.Tuple) and
                not getattr(with_items[0].context_expr, "_parenthesized_expr", False)):
            with_items = [
                ast.withitem(context_expr=elt, optional_vars=None)
                for elt in with_items[0].context_expr.elts
            ]
        return ast.With(items=with_items, body=suite)

    def with_parenthesized_expr_as(self, nodes):
        return ast.With(items=[self.with_item(nodes[:2])], body=nodes[2])

    def with_parenthesized_items_as(self, nodes):
        items = nodes[0]
        if any(item.optional_vars is not None for item in items):
            raise SyntaxError("invalid syntax")
        tuple_expr = ast.Tuple(
            elts=[item.context_expr for item in items],
            ctx=ast.Load()
        )
        return ast.With(items=[self.with_item([tuple_expr, nodes[1]])], body=nodes[2])

    def with_item(self, nodes):
        test = nodes[0]
        if self._contains_unparenthesized_namedexpr(test):
            raise SyntaxError("invalid assignment expression")
        name = nodes[1] if len(nodes) > 1 else None
        if isinstance(name, str):
            name = ast.Name(id=name, ctx=ast.Store())
        else:
            self._set_ctx(name, ast.Store())
        return ast.withitem(
            context_expr=test,
            optional_vars=name
        )

    def with_paren_single_item(self, nodes):
        return [ast.withitem(context_expr=nodes[0], optional_vars=None)]

    def with_paren_single_as_item(self, nodes):
        return [nodes[0]]

    def with_paren_mixed_items(self, nodes):
        if isinstance(nodes[0], ast.withitem):
            return nodes
        return [ast.withitem(context_expr=nodes[0], optional_vars=None), *nodes[1:]]

    def match_stmt(self, nodes):
        test = nodes[0]
        cases = nodes[1:]
        return ast.Match(test, cases)

    elifs = lambda self, nodes: nodes
    except_clauses = lambda self, nodes: nodes
    with_items = lambda self, nodes: nodes

    # -------------------------------------------------------------------------
    # Expressions
    # -------------------------------------------------------------------------

    def funccall(self, nodes):
        # Converts argvalue/stararg/kwargs into arguments
        function_name = nodes[0]
        prelim_args = nodes[1] if len(nodes) > 1 else []
        keywords = []
        args = []
        ordered_args = []

        for arg in prelim_args:
            if isinstance(arg, list):
                ordered_args.extend(arg)
            else:
                ordered_args.append(arg)

        seen_keyword = False
        seen_kwargs = False
        for arg in ordered_args:
            if isinstance(arg, tuple) and arg[0] == "stararg":
                if seen_kwargs:
                    raise SyntaxError(
                        "iterable argument unpacking follows keyword argument unpacking"
                    )
            elif isinstance(arg, tuple) and arg[0] == "argvalue":
                seen_keyword = True
            elif isinstance(arg, tuple) and arg[0] == "kwargs":
                seen_kwargs = True
            elif isinstance(arg, tuple) and len(arg) == 2 and isinstance(arg[1], list):
                if seen_keyword or seen_kwargs:
                    raise SyntaxError("positional argument follows keyword argument")
            else:
                if seen_keyword:
                    raise SyntaxError("positional argument follows keyword argument")
                if seen_kwargs:
                    raise SyntaxError(
                        "positional argument follows keyword argument unpacking"
                    )

            if isinstance(arg, tuple) and arg[0] == "stararg":
                args.append(ast.Starred(arg[1], ctx=ast.Load()))
            elif isinstance(arg, tuple) and arg[0] == "argvalue":
                keywords.append(ast.keyword(arg=arg[1], value=arg[2]))
            elif isinstance(arg, tuple) and arg[0] == "kwargs":
                keywords.append(ast.keyword(arg=None, value=arg[1]))
            elif isinstance(arg, tuple) and len(arg) == 2 and isinstance(arg[1], list):
                args.append(ast.GeneratorExp(elt=arg[0], generators=arg[1]))
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
        if (self._contains_unparenthesized_namedexpr(key) or
                self._contains_unparenthesized_namedexpr(value)):
            raise SyntaxError("invalid assignment expression")
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
        return ast.List(elts=nodes if nodes else [], ctx=ast.Load())

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
        return ast.Set(elts=nodes)

    def comprehension(self, nodes):
        # comprehension
        comp_result = nodes[0]
        comp_fors = nodes[1:]
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
        ifs = nodes[index + 2:]

        if isinstance(target, list):
            target = ast.Tuple(target)
        self._set_ctx(target, ast.Store())

        return ast.comprehension(
            target=target,
            iter=iterable,
            ifs=ifs,
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

    not_in = lambda self, _: "not in"
    is_not = lambda self, _: "is not"

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
        if self._contains_unparenthesized_namedexpr(value):
            raise SyntaxError("invalid assignment expression")
        return ast.Yield(value=value)

    def yield_from(self, nodes):
        value = nodes[0] if len(nodes) > 0 else None
        if self._contains_unparenthesized_namedexpr(value):
            raise SyntaxError("invalid assignment expression")
        return ast.YieldFrom(value=value)

    def await_expr(self, nodes):
        return ast.Await(nodes[1])

    def assign_expr(self, nodes):
        target = ast.Name(id=nodes[0], ctx=ast.Store())
        value = nodes[1]
        return ast.NamedExpr(target=target, value=value)

    def grouped_test(self, nodes):
        node = nodes[0]
        if isinstance(node, ast.AST):
            node._parenthesized_expr = True
        return node

    def test(self, nodes):
        # x if y else z
        body = nodes[0]
        test_cond = nodes[1]
        orelse = nodes[2]
        return ast.IfExp(test=test_cond, body=body, orelse=orelse)

    def f_test(self, nodes):
        return self.test(nodes)

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

    def tuple(self, nodes):
        return ast.Tuple(elts=nodes, ctx=ast.Load())

    def parenthesized_tuple(self, nodes):
        node = ast.Tuple(elts=nodes, ctx=ast.Load())
        node._parenthesized_expr = True
        return node

    def testlist_tuple(self, nodes):
        return ast.Tuple(elts=nodes, ctx=ast.Load())

    def string_concat(self, nodes):
        merged_string = self.merge_adjacent_strings(nodes)
        # Return if only one value
        if len(merged_string) == 1:
            return merged_string[0]

        if all(
            isinstance(item, ast.Constant) and
            isinstance(item.value, (str, bytes))
            for item in merged_string
        ):
            if isinstance(merged_string[0].value, str):
                return ast.Constant(value="".join(item.value for item in merged_string))
            return ast.Constant(value=b"".join(item.value for item in merged_string))

        return_string = []
        # Merge everything into one joined string
        for string in merged_string:
            if isinstance(string, ast.Constant):
                if isinstance(string.value, str):
                    return_string.append(string)
                else:
                    raise SyntaxError("Cannot concatenate bytes literals with f-strings")
            elif isinstance(string, ast.JoinedStr):
                return_string.extend(string.values)
        return self._normalize_joined_str(
            ast.JoinedStr(values=return_string),
            decode_literals=False
        )

    def f_string(self, nodes):
        is_raw = isinstance(nodes[0], str) and "r" in nodes[0].lower()
        values_raw = []
        pending_close_brace = False
        for item in nodes[1:-1]:
            # Close braces are accepted singly in the grammar so nested format
            # specs can split adjacent expression closers. Pair literal braces
            # here to preserve CPython's escaped "}}" rule.
            if item is self.FSTRING_LITERAL_CLOSE_BRACE:
                if pending_close_brace:
                    values_raw.append("}")
                    pending_close_brace = False
                else:
                    pending_close_brace = True
                continue

            if pending_close_brace:
                raise SyntaxError("f-string: single '}' is not allowed")

            if (
                    isinstance(item, tuple) and len(item) == 2 and
                    item[0] == "named_unicode_escape"):
                if is_raw:
                    if not item[1].isidentifier():
                        raise SyntaxError("invalid syntax")
                    values_raw.append("\\N")
                    values_raw.append(ast.FormattedValue(
                        value=ast.Name(id=item[1], ctx=ast.Load()),
                        conversion=-1,
                        format_spec=None
                    ))
                else:
                    try:
                        values_raw.append(unicodedata.lookup(item[1]))
                    except KeyError as exc:
                        raise SyntaxError("unknown Unicode character name") from exc
                continue

            if isinstance(item, tuple) and len(item) == 3 and item[0] == "debug_fexpr":
                values_raw.append(ast.Constant(value=item[1]))
                values_raw.append(item[2])
            else:
                values_raw.append(item)
        if pending_close_brace:
            raise SyntaxError("f-string: single '}' is not allowed")
        values = self.merge_adjacent_strings(values_raw)
        joined = ast.JoinedStr(values=values)
        return self._normalize_joined_str(joined, decode_literals=not is_raw)

    @v_args(meta=True)
    def f_expression_single(self, meta, nodes):
        # v_args gives function access to meta information (propagate_position)
        return self.f_expression(nodes, meta=meta)

    @v_args(meta=True)
    def f_expression_double(self, meta, nodes):
        return self.f_expression(nodes, meta=meta)

    def f_expression(self, nodes, meta=None):
        expr_node = nodes[0]
        conversion = -1
        format_spec = None
        debug_eq = None

        for node in nodes[1:]:
            # check for the conversion
            if isinstance(node, str):
                conversion = ord(node.lower())
            elif isinstance(node, tuple) and len(node) == 2 and node[0] == "debug_eq":
                debug_eq = node[1]
            elif isinstance(node, ast.AST):
                format_spec = node

        if debug_eq is not None and conversion == -1 and format_spec is None:
            conversion = ord("r")

        formatted_value = ast.FormattedValue(
            value=expr_node,
            conversion=conversion,
            format_spec=format_spec
        )
        if debug_eq is not None:
            return "debug_fexpr", self._debug_prefix_from_source(meta), formatted_value
        return formatted_value

    def debug_eq(self, nodes):
        return "debug_eq", "="

    def conversion(self, token):
        return token[0]

    def format_spec_eq(self, nodes):
        return self.format_spec(["=", *nodes])

    def format_spec(self, nodes):
        values = []
        for node in nodes:
            # string or expression
            if isinstance(node, str):
                values.append(ast.Constant(value=node))
            elif isinstance(node, ast.FormattedValue):
                values.append(node)
            elif isinstance(node, ast.AST):
                values.append(self.f_expression([node]))
        return ast.JoinedStr(values=values)

    def string(self, nodes):
        current_string = nodes[0]
        if isinstance(current_string, (ast.JoinedStr, ast.Constant)):
            return current_string

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
        prefix, content = self._split_string_literal(token.value)
        prefix_lower = prefix.lower()
        is_raw = "r" in prefix_lower
        is_bytes = "b" in prefix_lower

        if is_bytes:
            if is_raw:
                if any(ord(ch) > 0x7F for ch in content):
                    raise SyntaxError("bytes literals may only contain ASCII characters")
                return ast.Constant(value=content.encode("ascii"))
            return ast.Constant(value=self._decode_bytes_escapes(content))

        value = content if is_raw else self._decode_string_escapes(content)
        kind = "u" if prefix == "u" else None
        return ast.Constant(value=value, kind=kind)

    def LONG_STRING(self, token):
        return self.STRING(token)

    def F_LONG_STRING(self, token):
        return ast.parse(token.value, mode="eval").body

    def INVALID_STRING_PREFIX(self, token):
        raise SyntaxError("invalid string prefix")

    def var(self, nodes):
        return ast.Name(id=nodes[0], ctx=ast.Load())

    number = lambda self, nodes: nodes[0]
    star_expr = lambda self, nodes: ast.Starred(value=nodes[0], ctx=ast.Load())
    name = lambda self, nodes: str(nodes[0])
    comp_op = lambda self, nodes: nodes[0]
    ellipsis = lambda self, _: ast.Constant(value=Ellipsis)
    f_string_content_single = lambda self, nodes: nodes[0]
    f_string_content_double = lambda self, nodes: nodes[0]
    literal_open_brace = lambda self, _: '{'
    literal_close_brace = lambda self, _: self.FSTRING_LITERAL_CLOSE_BRACE
    named_unicode_escape = lambda self, nodes: ("named_unicode_escape", str(nodes[0])[3:-1])
    exprlist = lambda self, nodes: nodes

    # -------------------------------------------------------------------------
    # Definitions
    # -------------------------------------------------------------------------

    def decorator(self, nodes):
        return nodes[0]

    def decorated(self, nodes):
        decorators = nodes[0]
        definition = nodes[1]
        # classdef, funcdef, async funcdef, viewgen. Prepend, since a viewgen
        # already carries its own decorator.
        definition.decorator_list = decorators + definition.decorator_list
        return definition

    def funcdef(self, nodes):
        name = str(nodes[0])
        index = 1
        type_params = []
        if (
            index < len(nodes) and isinstance(nodes[index], tuple) and
            len(nodes[index]) == 2 and nodes[index][0] == "type_params"
        ):
            type_params = nodes[index][1]
            index += 1
        if index < len(nodes) and isinstance(nodes[index], ast.arguments):
            parameters = nodes[index]
            index += 1
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

        # Extract return type and suite
        rest = nodes[index:]
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
            type_params=type_params,
            returns=return_type
        )

    def async_funcdef(self, nodes):
        funcdef = nodes[0] if isinstance(nodes, list) else nodes
        return ast.AsyncFunctionDef(
            name=funcdef.name,
            args=funcdef.args,
            body=funcdef.body,
            decorator_list=[],
            type_params=funcdef.type_params,
            returns=funcdef.returns
        )

    def classdef(self, nodes):
        name = nodes[0]
        index = 1
        type_params = []
        if (
            index < len(nodes) and isinstance(nodes[index], tuple) and
            len(nodes[index]) == 2 and nodes[index][0] == "type_params"
        ):
            type_params = nodes[index][1]
            index += 1
        if index < len(nodes) - 1:
            bases_node = nodes[index]
            suite = nodes[index + 1]
        else:
            bases_node = []
            suite = nodes[index]

        bases = []
        keywords = []
        seen_keyword = False
        seen_kwargs = False
        for base in bases_node:
            if isinstance(base, tuple) and base[0] == "argvalue":
                seen_keyword = True
                keywords.append(ast.keyword(arg=base[1], value=base[2]))
            elif isinstance(base, tuple) and base[0] == "stararg":
                if seen_kwargs:
                    raise SyntaxError(
                        "iterable argument unpacking follows keyword argument unpacking"
                    )
                bases.append(ast.Starred(value=base[1], ctx=ast.Load()))
            elif isinstance(base, tuple) and base[0] == "kwargs":
                seen_kwargs = True
                keywords.append(ast.keyword(arg=None, value=base[1]))
            else:
                if seen_keyword:
                    raise SyntaxError("positional argument follows keyword argument")
                if seen_kwargs:
                    raise SyntaxError(
                        "positional argument follows keyword argument unpacking"
                    )
                bases.append(base)

        return ast.ClassDef(
            name=name,
            bases=bases,
            keywords=keywords,
            body=suite,
            decorator_list=[],
            type_params=type_params
        )

    def type_params(self, nodes):
        return "type_params", nodes

    def typevar(self, nodes):
        return ast.TypeVar(name=nodes[0], bound=None, default_value=None)

    def typevar_default(self, nodes):
        return ast.TypeVar(name=nodes[0], bound=None, default_value=nodes[1])

    def bounded_typevar(self, nodes):
        return ast.TypeVar(name=nodes[0], bound=nodes[1], default_value=None)

    def bounded_typevar_default(self, nodes):
        return ast.TypeVar(name=nodes[0], bound=nodes[1], default_value=nodes[2])

    def typevartuple(self, nodes):
        return ast.TypeVarTuple(name=nodes[0], default_value=None)

    def typevartuple_default(self, nodes):
        return ast.TypeVarTuple(name=nodes[0], default_value=nodes[1])

    def paramspec(self, nodes):
        return ast.ParamSpec(name=nodes[0], default_value=None)

    def paramspec_default(self, nodes):
        return ast.ParamSpec(name=nodes[0], default_value=nodes[1])

    def type_alias_stmt(self, nodes):
        name = ast.Name(id=nodes[0], ctx=ast.Store())
        if len(nodes) == 3:
            type_params = nodes[1][1]
            value = nodes[2]
        else:
            type_params = []
            value = nodes[1]
        if self._contains_unparenthesized_namedexpr(value):
            raise SyntaxError("invalid assignment expression")
        return ast.TypeAlias(name=name, type_params=type_params, value=value)

    decorators = lambda self, nodes: nodes
    arguments = lambda self, nodes: nodes

    # -------------------------------------------------------------------------
    # Parameters / Arguments
    # -------------------------------------------------------------------------

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
        if any(default is not None for default in defaults):
            seen_default = False
            for default in defaults:
                if default is None and seen_default:
                    raise SyntaxError("non-default argument follows default argument")
                seen_default = seen_default or default is not None

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
                if param_type == "starguard" and not paramvalues and maybe_kwparam is None:
                    raise SyntaxError("named arguments must follow bare *")
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
        if self._contains_unparenthesized_namedexpr(default):
            raise SyntaxError("invalid assignment expression")
        return "arg_with_default", typedparam, default

    def typedparam(self, nodes):
        # x:Int
        name = nodes[0]
        annotation = nodes[1] if len(nodes) > 1 else None
        return ast.arg(arg=name, annotation=annotation)

    def argvalue(self, nodes):
        if self._contains_unparenthesized_namedexpr(nodes[1]):
            raise SyntaxError("invalid assignment expression")
        return "argvalue", nodes[0], nodes[1]

    def stararg(self, nodes):
        argument = nodes[0]
        if self._contains_unparenthesized_namedexpr(argument):
            raise SyntaxError("invalid assignment expression")
        return "stararg", argument

    def kwargs(self, nodes):
        if self._contains_unparenthesized_namedexpr(nodes[0]):
            raise SyntaxError("invalid assignment expression")
        return "kwargs", nodes[0]

    def lambda_paramvalue(self, nodes):
        name_node = nodes[0]
        default_node = nodes[1] if len(nodes) > 1 else None
        if self._contains_unparenthesized_namedexpr(default_node):
            raise SyntaxError("invalid assignment expression")
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

        if vararg is None and not kwonlyargs and kwarg is None:
            raise SyntaxError("named arguments must follow bare *")

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
        posonlyargs = []
        args = []
        defaults = []
        vararg = None
        kwonlyargs = []
        kw_defaults = []
        kwarg = None
        normal_params = []

        def unpack_param(param, target_list):
            if isinstance(param, tuple) and isinstance(param[0], ast.arg):
                target_list.append(param[0])
                defaults.append(param[1])
            elif isinstance(param, ast.arg):
                target_list.append(param)
                defaults.append(None)
            elif isinstance(param, str):
                target_list.append(ast.arg(arg=param, annotation=None))
                defaults.append(None)

        # construct the parameters
        for node in nodes:
            if isinstance(node, tuple) and isinstance(node[0], ast.arg):
                # lambda_paramvalue with optional default
                normal_params.append(node)
            elif isinstance(node, str) and node == "/":
                normal_params.append(node)
            elif isinstance(node, str):
                # bare name -> positional arg, no default
                normal_params.append(node)
            elif isinstance(node, ast.arguments):
                if node.vararg:
                    vararg = node.vararg
                if node.kwarg:
                    kwarg = node.kwarg
                kwonlyargs.extend(node.kwonlyargs)
                kw_defaults.extend(node.kw_defaults)
            elif isinstance(node, dict) and "kwarg" in node:
                kwarg = node["kwarg"]

        slash_index = normal_params.index("/") if "/" in normal_params else -1
        if slash_index != -1:
            params_pos = normal_params[:slash_index]
            params_args = normal_params[slash_index + 1:]
        else:
            params_pos = []
            params_args = normal_params

        for param in params_pos:
            unpack_param(param, posonlyargs)
        for param in params_args:
            unpack_param(param, args)
        if any(default is not None for default in defaults):
            seen_default = False
            for default in defaults:
                if default is None and seen_default:
                    raise SyntaxError("non-default argument follows default argument")
                seen_default = seen_default or default is not None

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

        if self._contains_unparenthesized_namedexpr(body):
            raise SyntaxError("invalid assignment expression")
        return ast.Lambda(args=params, body=body)

    # -------------------------------------------------------------------------
    # Match Case
    # -------------------------------------------------------------------------

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

    def attr_pattern(self, nodes):
        return ast.MatchValue(self.value(nodes))

    def keyw_arg_pattern(self, nodes):
        key = nodes[0]
        pattern = nodes[1]
        return key, pattern

    def as_pattern(self, nodes):
        pattern = nodes[0]
        name = nodes[1]
        if name == "_":
            raise SyntaxError("cannot use '_' as a target")
        return ast.MatchAs(pattern=pattern, name=name)

    def or_pattern(self, nodes):
        return ast.MatchOr(patterns=nodes)

    def star_pattern(self, nodes):
        name = None if nodes[0] == "_" else nodes[0]
        return ast.MatchStar(name=name)

    def sequence_pattern(self, nodes):
        # nodes = list of sequence_item_pattern
        return ast.MatchSequence(patterns=nodes)

    def mapping_item_pattern(self, nodes):
        # literal/attribute + as_pattern)
        return nodes[0], nodes[1]

    @staticmethod
    def _mapping_key_to_expr(key):
        if isinstance(key, ast.MatchValue):
            return key.value
        if isinstance(key, ast.MatchSingleton):
            return ast.Constant(value=key.value)
        return key

    def mapping_pattern(self, nodes):
        # nodes = list of mapping_item_pattern
        keys = [self._mapping_key_to_expr(k) for k, v in nodes]
        patterns = [v for k, v in nodes]
        return ast.MatchMapping(keys=keys, patterns=patterns, rest=None)

    def mapping_star_pattern(self, nodes):
        # nodes[-1] = NAME for **rest
        # nodes[:-1] = mapping_item_pattern
        keys = [self._mapping_key_to_expr(k) for k, v in nodes[:-1]]
        patterns = [v for k, v in nodes[:-1]]
        rest_name = nodes[-1][1] if isinstance(nodes[-1], tuple) else nodes[-1]
        if rest_name == "_":
            raise SyntaxError("invalid mapping pattern rest name '_'")
        return ast.MatchMapping(keys=keys, patterns=patterns, rest=rest_name)

    def arguments_pattern(self, nodes):
        pos_args = []
        kw_names = []
        kw_values = []
        seen_keyword = False
        for argument in nodes:
            if isinstance(argument, tuple):
                seen_keyword = True
                kw_names.append(argument[0])
                kw_values.append(argument[1])
            else:
                if seen_keyword:
                    raise SyntaxError("positional patterns follow keyword patterns")
                pos_args.append(argument)
        return pos_args, (kw_names, kw_values)

    def class_pattern(self, nodes):
        # dotted_name (value)
        class_name = nodes[0]
        pos_args = []
        keys = []
        patterns = []
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
        if (isinstance(const, ast.Constant) and
                (type(const.value) is bool or const.value is None)):
            return ast.MatchSingleton(value=const.value)
        # Other values
        return ast.MatchValue(const)

    def negative_number(self, nodes):
        return ast.UnaryOp(op=ast.USub(), operand=nodes[0])

    def complex_number_pattern(self, nodes):
        left = nodes[0]
        op = self.ADD_OP_MAP[nodes[1]]()
        right = nodes[2]
        return ast.BinOp(left=left, op=op, right=right)

    lambdef_nocond = lambda self, nodes: nodes
    const_none = lambda self, _: ast.Constant(value=None)
    const_true = lambda self, _: ast.Constant(value=True)
    const_false = lambda self, _: ast.Constant(value=False)
    argument = lambda self, nodes: nodes[0]

    # -------------------------------------------------------------------------
    # Top-Level
    # -------------------------------------------------------------------------

    single_input = lambda self, nodes: nodes[0]
    file_input = lambda self, nodes: ast.Module(body=self._flatten_body(nodes), type_ignores=[])
    eval_input = lambda self, nodes: nodes[0]
