# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Placement groups arrange schematic elements (instances, ports, nested
groups) relative to each other without explicit coordinates. A group
records its children in declaration order and emits constraints for the
view's Solver during postprocessing. Because only relative constraints are
emitted, children of different sizes (e.g. symbols whose size depends on
their pin count) are handled without user intervention.

Row and Col place their children geometrically. Series and Parallel
additionally connect them electrically, so circuit structures can be
described by nesting alone, e.g. a NAND as a Series of vdd, a Parallel
pull-up pair, the pull-down transistors and vss.

In ORD, groups are used as node statements::

    Col(gap=2) stack:
        Pmos pu
        Nmos pd

Group blocks are naming-transparent: children declared inside the body are
added to the view root as usual and only additionally recorded in the
group.
"""

import math
from dataclasses import dataclass
from itertools import chain
from typing import Callable

from public import public

from .constraints import EqualsZero, Rect4LinearTerm, coerce_term
from .context import _view_ctx_var
from .geoprim import D4
from .ordb import QueryException

SIDE_NAMES = {
    D4.North: 'upward', D4.South: 'downward',
    D4.East: 'right', D4.West: 'left',
}


def describe(node):
    """
    Name of a node for error messages: its NPath path, or type and nid
    for anonymous nodes (nodes are not required to have a path).
    """
    if node.npath_nid is None:
        return f"{type(node).__name__}(nid={node.nid})"
    return node.full_path_str()


class GroupContext:
    """
    Entered by the body of a placement group node statement. Unlike
    NodeContext, the name resolution root is left unchanged; the group is
    only marked as the innermost active group so that elements declared in
    the body register as its children.
    """
    def __init__(self, group):
        self.group = group

    def __enter__(self):
        view_ctx = _view_ctx_var.get()
        if view_ctx is None:
            raise TypeError(
                "Placement groups can only be used within a viewgen.")
        view_ctx.group_stack.append(self.group)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _view_ctx_var.get().group_stack.pop()


def term_constant(term):
    """Value of a LinearTerm without variable part (a size), as float."""
    if any(abs(c) >= 1e-9 for c in term.coefficients):
        raise ValueError(
            "Size of a placement group child is not constant; cannot "
            "arrange the group.")
    return term.constant


@dataclass
class Endpoint:
    """
    Connectable boundary of a placement group child: an instance pin, a
    port's net or a nested group's boundary/rail.

    Attributes:
        net: Net the endpoint is already connected to, or None.
        attach: Callback that connects the endpoint to a given net. None
            for endpoints that are themselves nets (ports), which are
            always connected.
    """
    net: object = None
    attach: Callable = None

    def connect(self, net):
        """Connects to net; being on a different net already is an error."""
        if self.net is not None:
            if self.net.nid != net.nid:
                raise ValueError(
                    f"Connection conflict between nets "
                    f"{describe(self.net)} and {describe(net)}.")
            return
        self.attach(net)


def adopted_net(endpoints):
    """
    The net some of the endpoints are already connected to, or None.
    Endpoints on distinct existing nets are a connection conflict and
    raise an error.
    """
    nets = {ep.net.nid: ep.net for ep in endpoints if ep.net is not None}
    if len(nets) > 1:
        names = ', '.join(sorted(describe(net) for net in nets.values()))
        raise ValueError(
            f"Connection conflict: endpoints are already connected to "
            f"different nets ({names}).")
    return next(iter(nets.values()), None)


def connect_endpoints(endpoints, root):
    """
    Connects all endpoints to one shared net. A net that an endpoint
    already is on is adopted (see adopted_net); without any, an anonymous
    net is created on root.
    """
    from .schema import Net
    net = adopted_net(endpoints)
    if net is None:
        net = root % Net()
    for endpoint in endpoints:
        endpoint.connect(net)


@public
class PlacementGroup:
    """
    Base class of all placement groups, see module docstring. Use Row or
    Col (or Series/Parallel for electrical connection).

    Args:
        gap: Distance between adjacent children along the main axis. The
            default leaves room for auto_wire() routing; tighter gaps can
            exceed the router's capacity.
        align: Cross-axis alignment of the children: 'center' (snapped
            down to the unit grid), 'start' (bottom/left edge) or 'end'
            (top/right edge). None picks the group's default_align.
        anchor: Position of the group's southwest corner. The default
            'auto' anchors a top-level group at (0, 0) — several
            auto-anchored groups in one view line up side by side —
            unless a member appears in a user constraint or has a
            directly assigned position. Pass an (x, y) tuple to anchor
            explicitly, or None to never emit an anchor.
    """
    axis = None #: Main axis along which children are placed: 0 = x, 1 = y.
    aligns = ('center', 'start', 'end') #: Supported align values.
    default_align = 'center' #: align used when None is passed.

    def __init__(self, gap=2, align=None, anchor='auto'):
        if align is None:
            align = self.default_align
        if align not in self.aligns:
            raise ValueError(f"align must be one of {self.aligns}.")
        self.children = []
        self.gap = gap
        self.align = align
        self.anchor = anchor
        self.sealed = False #: Set by rect(); blocks further add().

    def ctx(self):
        return GroupContext(self)

    def add(self, child):
        """Appends a child (instance, port/net or nested group)."""
        if self.sealed:
            raise TypeError(
                "Placement group can no longer be extended: its outline "
                "was already used.")
        self.children.append(child)
        return child

    def subgraph_root(self):
        """SubgraphRoot cursor of the subgraph the children belong to."""
        for child in self.children:
            if isinstance(child, PlacementGroup):
                return child.subgraph_root()
            return child.root
        raise ValueError("Placement group has no children.")

    def child_rect(self, child):
        """
        (lx, ly, ux, uy) LinearTerms of a child's bounding box in view
        coordinates. Ports are zero-size points at their position.
        """
        from .schema import Net, SchemPort
        if isinstance(child, PlacementGroup):
            return child.rect()
        if isinstance(child, Net):
            try:
                child = child.port
            except QueryException:
                raise ValueError(
                    f"Cannot place net {describe(child)}: it has no "
                    "port.") from None
        if isinstance(child, SchemPort):
            x = coerce_term(child.pos.x)
            y = coerce_term(child.pos.y)
            return (x, y, x, y)
        outline = child.outline
        return (coerce_term(outline.lx), coerce_term(outline.ly),
            coerce_term(outline.ux), coerce_term(outline.uy))

    def arrangement(self):
        """
        The relative arrangement of the children. Since child sizes are
        constants, the arrangement is rigid; it is returned as (rects,
        offsets, (width, height)), where offsets[i] is child i's constant
        (x, y) offset from the group's southwest corner. Center alignment
        is snapped down to the unit grid so that on-grid children stay on
        grid regardless of size differences.
        """
        if not self.children:
            raise ValueError("Placement group has no children.")
        main, cross = self.axis, 1 - self.axis
        rects = [self.child_rect(child) for child in self.children]
        main_sizes = [term_constant(r[main+2] - r[main]) for r in rects]
        cross_offsets, cross_span = self.cross_arrangement(rects, cross)

        # Main axis: sizes and gaps accumulate in declaration order,
        # left to right (Row) or top to bottom (Col).
        main_offsets = []
        position = 0
        for size in main_sizes:
            main_offsets.append(position)
            position += size + self.gap
        main_span = position - self.gap
        if main == 1:
            # Declaration order is top to bottom, offsets address the
            # child's lower edge.
            main_offsets = [main_span - offset - size
                for offset, size in zip(main_offsets, main_sizes)]

        if main == 0:
            offsets = list(zip(main_offsets, cross_offsets))
            size = (main_span, cross_span)
        else:
            offsets = list(zip(cross_offsets, main_offsets))
            size = (cross_span, main_span)
        return rects, offsets, size

    def cross_arrangement(self, rects, cross):
        """(offsets, span) of the children on the cross axis."""
        sizes = [term_constant(r[cross+2] - r[cross]) for r in rects]
        span = max(sizes)
        if self.align == 'center':
            offsets = [math.floor((span - size) / 2) for size in sizes]
        elif self.align == 'start':
            offsets = [0] * len(rects)
        else: # 'end'
            offsets = [span - size for size in sizes]
        return offsets, span

    def rect(self):
        """
        The group's bounding box as (lx, ly, ux, uy) LinearTerms, anchored
        on the first child. Reading it seals the group against further
        children (terms derived from it would not follow).
        """
        rects, offsets, (width, height) = self.arrangement()
        self.sealed = True
        lx = rects[0][0] - offsets[0][0]
        ly = rects[0][1] - offsets[0][1]
        return (lx, ly, lx + width, ly + height)

    @property
    def outline(self):
        """Group bounding box as Rect4LinearTerm, usable in constraints."""
        return Rect4LinearTerm(*self.rect())

    def __getattr__(self, name):
        # Convenience access to outline properties (south, center, lx, ...).
        # Unknown names must not reach self.outline: reading the outline
        # seals the group, which would make a typo mutate state.
        if name.startswith('_') or not hasattr(Rect4LinearTerm, name):
            raise AttributeError(name)
        return getattr(self.outline, name)

    def variables(self):
        """Solver Variables of all (transitive) children's positions."""
        variables = set()
        for child in self.children:
            if isinstance(child, PlacementGroup):
                variables |= child.variables()
            else:
                for term in self.child_rect(child):
                    variables |= set(term.variables)
        return variables

    def pinned(self):
        """
        True if any (transitive) child's position is already fixed
        (assigned directly instead of left to the solver); the group
        then follows that child and anchor='auto' does not apply.
        """
        for child in self.children:
            if isinstance(child, PlacementGroup):
                if child.pinned():
                    return True
            elif not any(term.variables for term in self.child_rect(child)):
                return True
        return False

    def emit(self, solver, toplevel=True, auto_anchor=(0, 0)):
        """
        Emits the group's placement constraints into solver. Called by the
        view context during postprocessing; call manually when using
        groups outside a viewgen.

        auto_anchor is the position used for anchor='auto'; the view
        context spreads several top-level groups side by side through it.
        Returns True if this automatic anchor was applied.
        """
        if toplevel:
            constrained = set()
            for constraint in chain(solver.equalities, solver.inequalities):
                constrained |= set(constraint.term.variables)
        for child in self.children:
            if isinstance(child, PlacementGroup):
                child.emit(solver, toplevel=False)
        rects, offsets, size = self.arrangement()
        # The arrangement is rigid: tie each child to the first child by
        # its constant offset delta, per axis.
        for rect, offset in zip(rects[1:], offsets[1:]):
            for axis in (0, 1):
                term = ((rect[axis] - offset[axis])
                    - (rects[0][axis] - offsets[0][axis]))
                if (all(abs(c) < 1e-9 for c in term.coefficients)
                        and abs(term.constant) >= 1e-9):
                    # Catch guaranteed contradictions here; the solver
                    # would only report an unspecific infeasibility.
                    raise ValueError(
                        "Placement group arrangement contradicts already "
                        "fixed child positions (a child added twice, or "
                        "several children with assigned positions).")
                solver.constrain(EqualsZero(term))
        if not toplevel:
            return False
        anchor = self.anchor
        applied_auto = False
        if anchor == 'auto':
            # Do not anchor groups that the user placed through their own
            # constraints or through a directly assigned child position.
            if self.variables() & constrained or self.pinned():
                anchor = None
            else:
                anchor = auto_anchor
                applied_auto = True
        if anchor is not None:
            group = self.rect()
            solver.constrain(EqualsZero(group[0] - anchor[0]))
            solver.constrain(EqualsZero(group[1] - anchor[1]))
        return applied_auto


@public
class Row(PlacementGroup):
    """Places children side by side, left to right along the x axis."""
    axis = 0


@public
class Col(PlacementGroup):
    """Places children in a stack, top to bottom along the y axis."""
    axis = 1


class ConnectingGroup(PlacementGroup):
    """
    Common base of the electrically connecting groups Series and Parallel:
    pin detection by facing side and shared net handling.

    Pin detection relies on the symbol convention that the pins carrying
    the current path face along its direction (pin align, after applying
    the instance's orientation). Detection must be unambiguous: with
    several pins on a facing side, the top=/bottom= (vertical) or
    left=/right= (horizontal) pin names select the pin, uniformly for all
    instance children. Heterogeneous cases that a uniform override cannot
    express should use Col/Row with explicit wiring instead.

    gap, align and anchor are inherited from PlacementGroup.

    Args:
        horizontal: Orientation of the current path: the children carry
            it vertically (False) or horizontally (True). The placement
            axis follows from it, see flow_along_axis.
        top: Pin name selecting the upward-facing pin on all instance
            children whose upward side has several pins (vertical groups).
        bottom: Like top, for downward-facing pins.
        left: Pin name selecting the left-facing pin (horizontal groups).
        right: Like left, for right-facing pins.
    """
    #: Whether the children are placed along the current path (Series)
    #: or across it (Parallel); together with the horizontal argument
    #: this determines the placement axis.
    flow_along_axis = None

    def __init__(self, gap=2, align=None, anchor='auto',
            horizontal=False, top=None, bottom=None, left=None, right=None):
        super().__init__(gap=gap, align=align, anchor=anchor)
        if horizontal and (top is not None or bottom is not None):
            raise ValueError(
                "top/bottom pin overrides only apply to vertical groups; "
                "use left/right.")
        if not horizontal and (left is not None or right is not None):
            raise ValueError(
                "left/right pin overrides only apply to horizontal groups; "
                "use top/bottom.")
        self.horizontal = horizontal
        self.pin_overrides = {D4.North: top, D4.South: bottom,
            D4.West: left, D4.East: right}
        # The two sides through which the current path enters and leaves
        # the children, ordered (facing the next child, facing the
        # previous child) in declaration order; the rails of a Parallel.
        if horizontal:
            self.flow_sides = (D4.East, D4.West)
        else:
            self.flow_sides = (D4.South, D4.North)
        flow_axis = 0 if horizontal else 1
        self.axis = flow_axis if self.flow_along_axis else 1 - flow_axis
        #: Nets forced onto a side by an enclosing group (Parallel rails).
        self.rail_nets = {}

    def child_symbol(self, inst):
        """Symbol of an instance child, resolving recorded parameters."""
        from .schema import SchemInstance, SchemInstanceUnresolvedParameter
        if isinstance(inst, SchemInstance):
            return inst.symbol
        params = {
            p.name: p.value
            for p in inst.root.all(SchemInstanceUnresolvedParameter.ref_idx.query(inst))
        }
        return inst.resolver(**params)

    def facing_pin(self, inst, side):
        """Name of the single pin of an instance child facing side."""
        from .schema import Pin
        override = self.pin_overrides[side]
        if override is not None:
            return override
        candidates = [pin for pin in self.child_symbol(inst).all(Pin)
            if (inst.orientation * pin.align).unflip() == side]
        if len(candidates) != 1:
            raise ValueError(
                f"{type(self).__name__} requires exactly one "
                f"{SIDE_NAMES[side]}-facing pin on {describe(inst)}, "
                f"found {len(candidates)}; pass pin name overrides to "
                "select pins explicitly.")
        pin = candidates[0]
        # Auto-connection needs a plain pin name: it is matched against
        # name-based unresolved connections and passed to getattr().
        # Hierarchical and anonymous pins do not qualify.
        path = pin.full_path_list() if pin.npath_nid is not None else None
        if path is None or len(path) != 1:
            raise ValueError(
                f"{type(self).__name__} cannot auto-connect pin "
                f"{describe(pin)} of {describe(inst)}; pass pin name "
                "overrides to select pins explicitly.")
        return path[0]

    def pin_net(self, inst, pin_name):
        """Net a pin of an instance child is connected to, or None."""
        from .schema import (SchemInstance, SchemInstanceConn,
            SchemInstanceUnresolvedConn)
        if isinstance(inst, SchemInstance):
            pin_nid = getattr(inst.symbol, pin_name).nid
            for conn in inst.root.all(SchemInstanceConn.ref_idx.query(inst)):
                if conn.there.nid == pin_nid:
                    return conn.here
        else:
            for conn in inst.root.all(SchemInstanceUnresolvedConn.ref_idx.query(inst)):
                if conn.there == (pin_name,):
                    return conn.here
        return None

    def endpoint(self, child, side):
        """Endpoint of a direct child on the given side."""
        from .schema import Net, SchemPort
        if isinstance(child, ConnectingGroup):
            return child.side_endpoint(side)
        if isinstance(child, PlacementGroup):
            raise ValueError(
                f"{type(self).__name__} cannot connect a nested Col/Row "
                "group; nest Series/Parallel or wire explicitly.")
        if isinstance(child, SchemPort):
            return Endpoint(net=child.ref)
        if isinstance(child, Net):
            return Endpoint(net=child)
        name = self.facing_pin(child, side)
        return Endpoint(net=self.pin_net(child, name),
            attach=lambda net: getattr(child, name).__wire_op__(net))

    def side_endpoint(self, side):
        """Boundary Endpoint offered to an enclosing connecting group."""
        raise NotImplementedError

    def boundary_junction_offset(self, side, cross):
        """
        Cross-axis offset of the group's boundary connection point within
        its bounding box, or None if there is no single point (a Parallel
        rail). Used by Series align='pins'.
        """
        return None


@public
class Series(ConnectingGroup):
    """
    Places children in a stack like Col (side by side like Row with
    horizontal=True) and connects them in series, modeling a current
    path: the pin of each child facing the next child is connected to the
    next child's pin facing back. Port children connect through their
    net.

    A pair's net is adopted from whichever facing pin is already
    connected, so junctions can be named by wiring one pin explicitly
    (e.g. ``.d -- y``); otherwise an anonymous net is created. Series and
    Parallel nest: a nested group connects through its boundary (the
    outward-facing pins of a Series, the rails of a Parallel).

    The default alignment 'pins' aligns each pair's facing pins on one
    line, giving straight junction wires; pass align='center' to center
    the children's bounding boxes instead.
    """
    flow_along_axis = True
    aligns = ('center', 'start', 'end', 'pins')
    default_align = 'pins'

    def emit(self, solver, toplevel=True, auto_anchor=(0, 0)):
        # Connectivity resolves top-down, before the children emit: nested
        # groups receive their boundary nets here and tie their internals
        # to them later (ORDB cannot merge nets afterwards).
        to_next, to_prev = self.flow_sides
        for prev, cur in zip(self.children, self.children[1:]):
            connect_endpoints([
                self.endpoint(prev, to_next),
                self.endpoint(cur, to_prev),
            ], self.subgraph_root())
        return super().emit(solver, toplevel=toplevel, auto_anchor=auto_anchor)

    def side_endpoint(self, side):
        return self.endpoint(self.children[self.boundary_index(side)], side)

    def boundary_index(self, side):
        """Child index forming the group's boundary on side."""
        to_next, to_prev = self.flow_sides
        if side == to_prev:
            return 0
        if side == to_next:
            return -1
        raise ValueError(
            f"Series has no {SIDE_NAMES[side]}-facing boundary "
            "(orientation mismatch with the enclosing group).")

    def cross_arrangement(self, rects, cross):
        if self.align != 'pins':
            return super().cross_arrangement(rects, cross)
        sizes = [term_constant(r[cross+2] - r[cross]) for r in rects]
        # Chain the offsets such that each pair's facing pins line up;
        # snapped down to the unit grid where center fallbacks (nested
        # Parallel) introduce half units.
        to_next, to_prev = self.flow_sides
        offsets = [0]
        for i, (prev, cur) in enumerate(zip(self.children, self.children[1:])):
            step = (self.junction_offset(prev, to_next, rects[i], cross)
                - self.junction_offset(cur, to_prev, rects[i+1], cross))
            offsets.append(offsets[-1] + step)
        offsets = [math.floor(offset) for offset in offsets]
        base = min(offsets)
        offsets = [offset - base for offset in offsets]
        span = max(offset + size for offset, size in zip(offsets, sizes))
        return offsets, span

    def junction_offset(self, child, side, rect, cross):
        """
        Cross-axis offset of a child's connection point on side, relative
        to its bounding box. Falls back to the center where there is no
        single connection point (nested Parallel rails).
        """
        from .schema import Net, SchemPort
        if isinstance(child, ConnectingGroup):
            offset = child.boundary_junction_offset(side, cross)
            if offset is None:
                offset = term_constant(rect[cross+2] - rect[cross]) / 2
            return offset
        if isinstance(child, (Net, SchemPort)):
            return 0
        pin = getattr(child, self.facing_pin(child, side)).pos
        coord = pin.x if cross == 0 else pin.y
        return term_constant(coerce_term(coord) - rect[cross])

    def boundary_junction_offset(self, side, cross):
        index = self.boundary_index(side)
        rects, offsets, size = self.arrangement()
        return (offsets[index][cross]
            + self.junction_offset(self.children[index], side, rects[index], cross))


@public
class Parallel(ConnectingGroup):
    """
    Places children side by side like Row (stacked like Col with
    horizontal=True, for children whose current path runs horizontally)
    and connects them in parallel: all upward-facing pins are tied to one
    rail net and all downward-facing pins to another (left-/right-facing
    with horizontal=True).

    To name a rail net, wire one child pin explicitly (e.g. ``.d -- y``);
    nested inside a Series, the rails connect through the enclosing
    stack. Port children are not supported; wire ports to the rail nets
    explicitly.
    """
    flow_along_axis = False

    def emit(self, solver, toplevel=True, auto_anchor=(0, 0)):
        # Connectivity resolves top-down, see Series.emit.
        for side in self.flow_sides:
            connect_endpoints(self.rail_endpoints(side), self.subgraph_root())
        return super().emit(solver, toplevel=toplevel, auto_anchor=auto_anchor)

    def rail_endpoints(self, side):
        """
        Endpoints of one rail: one per child, plus a net an enclosing
        group forced onto the rail.
        """
        from .schema import Net, SchemPort
        endpoints = []
        for child in self.children:
            if isinstance(child, (Net, SchemPort)):
                raise ValueError(
                    "Parallel does not support port children; wire the "
                    "rail net to the port explicitly.")
            endpoints.append(self.endpoint(child, side))
        forced = self.rail_nets.get(side)
        if forced is not None:
            endpoints.append(Endpoint(net=forced))
        return endpoints

    def side_endpoint(self, side):
        if side not in self.flow_sides:
            raise ValueError(
                f"Parallel has no {SIDE_NAMES[side]}-facing rail "
                "(orientation mismatch with the enclosing group).")
        # The rail's net so far: forced by an enclosing group or wired
        # explicitly on a child pin; None while the rail is still open.
        return Endpoint(net=adopted_net(self.rail_endpoints(side)),
            attach=lambda net: self.rail_nets.update({side: net}))
