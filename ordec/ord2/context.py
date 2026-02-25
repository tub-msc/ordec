# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from contextvars import ContextVar, Token

# ordec imports
from ..core import *
from ..schematic.routing import schematic_routing, adjust_outline_initial
from ..schematic import helpers

_ctx_var = ContextVar("ctx", default=None)
class _CtxWrapper:
    """Wrapper for the context variable"""
    def __getattr__(self, item):
        return getattr(_ctx_var.get(), item)

    def __call__(self):
        return _ctx_var.get()

class OrdContext:
    """
    Class which represents the context where a specific
    ORDB element is alive and accessible via relative
    accesses (dotted notation)
    """
    ctx = _CtxWrapper()

    def __init__(self, root=None, parent=None):
        self.root = root
        self._explicit_parent = parent
        self.parent = None
        self._run_routing = True
        self._run_schem_check = True

    def __enter__(self):
        """Enter context, set context variable and save parent"""
        self._token = _ctx_var.set(self)
        if self._token.old_value is not Token.MISSING:
            self.parent = self._token.old_value
        else:
            # Case for the top-level context
            self.parent = self._explicit_parent
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context and reset context variable"""
        _ctx_var.reset(self._token)

    def add(self, name_tuple, ref):
        """ Add a value to the current context"""
        helpers.recursive_setitem(self.root, name_tuple, ref)
        return helpers.recursive_getitem(self.root, name_tuple)

    def add_port(self, name_tuple):
        """ Add a port to the current context"""
        pin = helpers.recursive_getitem(self.root.symbol, name_tuple)
        subgraph_root = self.root
        while not isinstance(subgraph_root, SubgraphRoot):
            subgraph_root = subgraph_root.parent
        port = self.add(name_tuple, SchemPort(ref=subgraph_root % Net(pin=pin)))
        return port

    def symbol_postprocess(self):
        """ Postprocess call when returning from symbol"""
        helpers.symbol_place_pins(self.root, vpadding=2, hpadding=2)
        return self.root

    def schematic_postprocess(self):
        """ Postprocess call when returning from schematic"""
        helpers.resolve_instances(self.root)
        if self._run_routing:
            self.root.outline = schematic_routing(self.root)
        else:
            self.root.outline = adjust_outline_initial(self.root)
        if self._run_schem_check:
            helpers.schem_check(self.root, add_conn_points=True, add_terminal_taps=True)
        return self.root

def routing(enabled=True):
    """Enable or disable automatic routing for the current ORD context."""
    current_context = OrdContext.ctx()
    if current_context is None:
        raise RuntimeError("routing() can only be used inside an OrdContext")
    current_context._run_routing = bool(enabled)

def schem_check(enabled=True):
    """Enable or disable schematic checks for the current ORD context."""
    current_context = OrdContext.ctx()
    if current_context is None:
        raise RuntimeError("schem_check() can only be used inside an OrdContext")
    current_context._run_schem_check = bool(enabled)

