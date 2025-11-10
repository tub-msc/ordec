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
    def __getattr__(self, item):
        return getattr(_ctx_var.get(), item)

    def __call__(self):
        return _ctx_var.get()
ctx = _CtxWrapper()


class OrdContext:
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
        helpers.recursive_setitem(self.root, name_tuple, ref)
        return helpers.recursive_getitem(self.root, name_tuple)

    def add_path(self, name):
        self.root.mkpath(name)
        return getattr(self.root, name)

    def add_symbol_port(self, name):
        pin = helpers.recursive_getitem(ctx.root.symbol, name)
        net = self.add(name, Net(pin=pin))
        net % SchemPort(ref=pin)
        return net

    def get_symbol_port(self, net):
        for port in self.root.all(SchemPort):
            if port.ref == net:
                return port
        return net

    def symbol_postprocess(self):
        helpers.symbol_place_pins(ctx.root, vpadding=2, hpadding=2)
        return ctx.root

    def schematic_postprocess(self):
        helpers.resolve_instances(ctx.root)
        ctx.root.outline = schematic_routing(ctx.root)
        helpers.schem_check(ctx.root, add_conn_points=True, add_terminal_taps=True)
        return ctx.root
