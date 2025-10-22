# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import ast

class Misc():

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