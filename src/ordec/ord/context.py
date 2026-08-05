# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import sys

# ordec imports
from ..core import *
from ..core.context import (_viewgen_ctx_var, ViewGenContext, current_node_context,
    require_viewgen_context)
from ..schematic.helpers import recursive_setitem, recursive_getitem


def root():
    """Return the root of the current context"""
    return current_node_context().root


def register_in_group(ref):
    """Records ref as child of the innermost active arrangement group."""
    vgctx = _viewgen_ctx_var.get()
    if isinstance(vgctx, ViewGenContext) and vgctx.builder is not None:
        vgctx.builder.register_in_group(ref)


def add(name_tuple, ref):
    """ Add a value to the current context"""
    ctx = current_node_context()
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
    ctx = current_node_context()
    symbol = ctx.root.symbol
    if symbol is None:
        name = '.'.join(str(part) for part in name_tuple)
        raise TypeError(
            f"Cannot create port {name!r}: this schematic has no symbol to "
            "take pins from (the cell defines no symbol viewgen, or the "
            "viewgen is outside of a cell)."
        )
    pin = recursive_getitem(symbol, name_tuple)
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
    # Default align: flipped pin align, so e.g. a West-facing input pin
    # yields an East-facing port (same rule as the netlist importers).
    # A body `.align=` assignment overrides via the Net.align property.
    port = subgraph_root % SchemPort(ref=net, align=pin.align * R180)
    register_in_group(port)
    return net


def view_builder():
    """
    Return the running viewgen's ViewBuilder, materializing it from the
    return annotation if no node operation has established it yet (e.g. for
    bodies that construct an SRouter before the first node op).
    """
    return require_viewgen_context().require_builder()


def set_root(value):
    """Assign the root of the current view (the `. = ...` statement)."""
    require_viewgen_context().adopt(value)
    return value


def constrain(constraint):
    return require_viewgen_context().require_builder().constrain(constraint)


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
    ctx = current_node_context()
    # Source location for click-to-source.
    src_loc = SourceLocInfo(
        sys._getframe(1).f_code.co_filename, src_line, src_column
    ) if src_line is not None else None
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
