# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import sys

# ordec imports
from ..core import *
from ..core.context import _ctx_var, _view_ctx_var
from ..schematic.placement import PlacementGroup
from ..schematic.helpers import recursive_setitem, recursive_getitem


def root():
    """Return the root of the current context"""
    return _ctx_var.get().root


def register_in_group(ref):
    """Records ref as child of the innermost active placement group."""
    view_ctx = _view_ctx_var.get()
    if view_ctx is not None and view_ctx.group_stack:
        view_ctx.group_stack[-1].add(ref)


def add(name_tuple, ref):
    """ Add a value to the current context"""
    ctx = _ctx_var.get()
    if name_tuple is None:
        # Anonymous: add to subgraph without NPath
        nid_new = ctx.root.subgraph.add(ref)
        cursor = ctx.root.subgraph.cursor_at(nid_new, lookup_npath=False)
    else:
        recursive_setitem(ctx.root, name_tuple, ref)
        cursor = recursive_getitem(ctx.root, name_tuple)
    if isinstance(cursor, (SchemInstance, SchemInstanceUnresolved)):
        register_in_group(cursor)
    return cursor


def add_port(name_tuple):
    """
    Add a port to the current context. If a Net of the same name was
    forward-declared (net statement), the port attaches to that net,
    allowing connections before the port statement is reached.
    """
    ctx = _ctx_var.get()
    pin = recursive_getitem(ctx.root.symbol, name_tuple)
    subgraph_root = ctx.root
    while not isinstance(subgraph_root, SubgraphRoot):
        subgraph_root = subgraph_root.parent
    try:
        net = recursive_getitem(ctx.root, name_tuple)
    except QueryException:
        net = add(name_tuple, Net(pin=pin))
    else:
        if not isinstance(net, Net):
            name = '.'.join(str(part) for part in name_tuple)
            raise TypeError(
                f"Port name {name!r} is already used by {net!r}.")
        # Forward-declared net: attach the symbol pin to it. The unique
        # index on SchemPort.ref rejects a second port on the same net.
        if net.pin is not None and net.pin.nid != pin.nid:
            name = '.'.join(str(part) for part in name_tuple)
            raise TypeError(
                f"Cannot create port {name!r}: net {name!r} is already "
                "bound to a different pin.")
        net.pin = pin
    port = subgraph_root % SchemPort(ref=net)
    register_in_group(port)
    return net


def view_context():
    return _view_ctx_var.get()


def create_view_context(cell, root_cls):
    """
    Create the ViewContext for an ORD viewgen method.

    The context's ViewContext subclass is taken from the view's return type
    (root_cls.view_context). The initial root is created via create_root(),
    which may return None for views whose root is assigned within the viewgen
    body (see set_root()).
    """
    try:
        view_context_cls = root_cls.view_context
    except AttributeError as e:
        raise TypeError(
            f"{root_cls!r} cannot be used as an ORD viewgen return type."
        ) from e
    root = view_context_cls.create_root(cell, root_cls)
    return view_context_cls(root)


def set_root(value):
    """Assign the root of the current view context (the `. = ...` statement)."""
    _view_ctx_var.get().set_root(value)
    return value


def constrain(constraint):
    return _view_ctx_var.get().constrain(constraint)


def add_element(name_tuple, element, src_line=None, src_column=None):
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
        src_line: line of the defining ORD statement.
        src_column: column of the defining ORD statement.
    """
    ctx = _ctx_var.get()
    # Source location for click-to-source.
    src_loc = SourceLocInfo(
        sys._getframe(1).f_code.co_filename, src_line, src_column
    ) if src_line is not None else None
    # Placement groups are not inserted into the subgraph. They are
    # recorded on the view context or parent group and emitted later.
    if isinstance(element, type) and issubclass(element, PlacementGroup):
        element = element()
    if isinstance(element, PlacementGroup):
        view_ctx = _view_ctx_var.get()
        if view_ctx is None or not view_ctx.supports_placement_groups:
            raise TypeError(
                "Placement groups can only be used in a schematic viewgen.")
        if view_ctx.group_stack:
            view_ctx.group_stack[-1].add(element)
        else:
            view_ctx.placement_groups.append(element)
        return element
    # Layout context: create LayoutInstance from Cell instances
    if isinstance(ctx.root, Layout):
        if isinstance(element, Cell):
            ref = LayoutInstance(ref=element.layout)
            return add(name_tuple, ref)

    if isinstance(element, type) and issubclass(element, Cell):
        # Cell class: deferred resolution with parameters
        ref = SchemInstanceUnresolved(
            resolver=lambda **params: element(**params).symbol,
            src_loc=src_loc,
        )
        return add(name_tuple, ref)

    if isinstance(element, Cell):
        # Cell instance: symbol already determined, create SchemInstance directly
        ref = SchemInstance(symbol=element.symbol, src_loc=src_loc)
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
