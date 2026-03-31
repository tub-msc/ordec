# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from contextvars import ContextVar, Token


_ctx_var = ContextVar("ctx", default=None)
_view_ctx_var = ContextVar("view_ctx", default=None)


class NodeContext:
    """
    Class which represents the context where a specific
    ORDB element is alive and accessible via relative
    accesses (dotted notation)
    """

    def __init__(self, root):
        self.root = root

    def __enter__(self):
        """Enter context, set context variable and save parent"""
        self._token = _ctx_var.set(self)
        old = self._token.old_value
        self.parent = old if old is not Token.MISSING else None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context and reset context variable"""
        _ctx_var.reset(self._token)


class ViewContext:
    """
    Base view context. Subclasses override to add capabilities (e.g. constraint
    solving).

    ViewContext is a separate context from the NodeContext but its __enter__
    and __exit__ methods also automatically enter and exit a corresponding
    NodeContext.
    """
    def __init__(self, root):
        self.root = root

    def __enter__(self):
        self._node_ctx = self.root.ctx()
        self._node_ctx.__enter__()
        self._token = _view_ctx_var.set(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _view_ctx_var.reset(self._token)
        self._node_ctx.__exit__(exc_type, exc_val, exc_tb)

    def constrain(self, constraint):
        raise TypeError(f"Constraints not supported in {type(self.root).__name__} views.")


class LayoutViewContext(ViewContext):
    def __enter__(self):
        super().__enter__()
        from .constraints import Solver
        self.solver = Solver(self.root)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.solver.solve()
        super().__exit__(exc_type, exc_val, exc_tb)

    def constrain(self, constraint):
        self.solver.constrain(constraint)
