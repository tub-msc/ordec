# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# ordec imports
from ..core import *
from ..core.context import _ctx_var, _view_ctx_var
from ..schematic.helpers import recursive_setitem, recursive_getitem


def root():
    """Return the root of the current context"""
    return _ctx_var.get().root


def add(name_tuple, ref):
    """ Add a value to the current context"""
    ctx = _ctx_var.get()
    if name_tuple is None:
        # Anonymous: add to subgraph without NPath
        nid_new = ctx.root.subgraph.add(ref)
        return ctx.root.subgraph.cursor_at(nid_new, lookup_npath=False)
    recursive_setitem(ctx.root, name_tuple, ref)
    return recursive_getitem(ctx.root, name_tuple)


def add_port(name_tuple):
    """ Add a port to the current context"""
    ctx = _ctx_var.get()
    pin = recursive_getitem(ctx.root.symbol, name_tuple)
    subgraph_root = ctx.root
    while not isinstance(subgraph_root, SubgraphRoot):
        subgraph_root = subgraph_root.parent
    net = add(name_tuple, Net(pin=pin))
    subgraph_root % SchemPort(ref=net)
    return net


def view_context():
    return _view_ctx_var.get()


def constrain(constraint):
    return _view_ctx_var.get().constrain(constraint)


def add_element(name_tuple, element):
    """
    Add an element from a node statement, dispatching based on type.

    Handles the three types of node statements:
    - Node class statements (e.g., LayoutRect x)
    - Node instance statements (e.g., Nmos x)
    - Cell class/instance statements (e.g., Inv x)

    Args:
        name_tuple: path components for naming the element.
        element: Cell class, Cell instance, Node subclass,
            or NodeTuple instance.
    """
    ctx = _ctx_var.get()
    # Layout context: create LayoutInstance from Cell instances
    if isinstance(ctx.root, Layout):
        if isinstance(element, Cell):
            ref = LayoutInstance(ref=element.layout)
            return add(name_tuple, ref)

    if isinstance(element, type) and issubclass(element, Cell):
        # Cell class: deferred resolution with parameters
        ref = SchemInstanceUnresolved(
            resolver=lambda **params: element(**params).symbol
        )
        return add(name_tuple, ref)

    if isinstance(element, Cell):
        # Cell instance: symbol already determined, create SchemInstance directly
        ref = SchemInstance(symbol=element.symbol)
        return add(name_tuple, ref)

    if isinstance(element, type) and issubclass(element, Node):
        # Node subclass: instantiate with defaults
        return add(name_tuple, element())

    if isinstance(element, NodeTuple):
        # Node instance: add directly
        return add(name_tuple, element)

    raise TypeError(
        f"Cannot use {element!r} in node statement. "
        f"Expected Cell class/instance or Node class/instance."
    )
