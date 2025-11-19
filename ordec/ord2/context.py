# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from contextvars import ContextVar, Token

# ordec imports
from ..core import *
from ..routing import schematic_routing
from .. import helpers

_ctx_var = ContextVar("ctx", default=None)
class _CtxWrapper:
    """Wrapper for the context variable"""
    def __getattr__(self, item):
        return getattr(_ctx_var.get(), item)

    def __call__(self):
        return _ctx_var.get()
ctx = _CtxWrapper()


class OrdContext:
    """
    Class which represents the context where a specific
    ORDB element is alive and accessible via relative
    accesses (dotted notation)
    """
    def __init__(self, root=None, parent=None):
        self.root = root
        self._explicit_parent = parent
        self.parent = None

    def __enter__(self):
        self._token = _ctx_var.set(self)
        if self._token.old_value is not Token.MISSING:
            self.parent = self._token.old_value
        else:
            self.parent = self._explicit_parent
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _ctx_var.reset(self._token)

    def add(self, name_tuple, ref):
        """ Add a value to the current context"""
        helpers.recursive_setitem(self.root, name_tuple, ref)
        return helpers.recursive_getitem(self.root, name_tuple)

    def add_path(self, name):
        """ Add a path to the current context"""
        self.root.mkpath(name)
        return list()

    def add_port_normal(self, name):
        """ Add a port to a non path context"""
        pin = helpers.recursive_getitem(ctx.root.symbol, name)
        net = self.add(name, Net(pin=pin))
        port = net % SchemPort()
        return port

    def add_port_pathnode(self, name, node_list):
        """ Add a port to a path context"""
        pin = helpers.recursive_getitem(ctx.root.symbol, name)
        net = self.add(name, Net(pin=pin))
        node_list.insert(name[-1], net % SchemPort())

    def add_pathnode(self, name, node_list, value):
        """ Add a value to a path context"""
        ref = self.add(name, value)
        node_list.insert(name[-1], ref)

    def get_symbol_port(self, net):
        """ Get the symbol port for a Net if connected"""
        for port in self.root.all(SchemPort):
            if port.ref == net:
                return port
        return None

    def symbol_postprocess(self):
        """ Postprocess call when returning from symbol"""
        helpers.symbol_place_pins(ctx.root, vpadding=2, hpadding=2)
        return ctx.root

    def schematic_postprocess(self):
        """ Postprocess call when returning from schematic"""
        helpers.resolve_instances(ctx.root)
        ctx.root.outline = schematic_routing(ctx.root)
        helpers.schem_check(ctx.root, add_conn_points=True, add_terminal_taps=True)
        return ctx.root
