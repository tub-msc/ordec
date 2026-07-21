# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Arrangement groups arrange schematic elements (instances, ports, nested
groups) relative to each other without explicit coordinates. A group
records its children in declaration order and emits constraints for the
view's Solver during postprocessing, so children of different sizes are
placed without user intervention.

Row and Col place their children geometrically. Series and Parallel
additionally connect them electrically, so circuit structures can be
described by nesting alone. Groups are context managers::

    with Col(gap=2):
        Pmos pu
        Nmos pd

``with Col(gap=2) as stack:`` names the group, e.g. for use in
constraints. Group blocks are naming-transparent: children declared
inside the body are added to the view root as usual and only
additionally recorded in the group.
"""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from itertools import chain
from typing import Callable, NamedTuple

from public import public

from .constraints import (EqualsZero, LinearTerm, Rect4LinearTerm,
    Solver, Variable, coerce_term)
from .context import _view_ctx_var
from .geoprim import D4
from .ordb import Node, QueryException, SubgraphRoot

SIDE_NAMES = {
    D4.North: 'upward', D4.South: 'downward',
    D4.East: 'right', D4.West: 'left',
}

#: Tolerance below which a float LinearTerm coefficient or constant counts as zero
COEFF_EPS = 1e-9

def describe(node: 'Node | ArrangementGroup') -> str:
    """
    Returns the name of a node for error messages: its NPath path, or
    its type and placeholder label (??nid) for anonymous nodes. An
    arrangement group is named by its type.
    """
    if isinstance(node, ArrangementGroup):
        return f"{type(node).__name__} group"
    label = node.full_path_label()
    if node.npath_nid is None:
        return f"{type(node).__name__} {label}"
    return label


def term_constant(term: LinearTerm, child) -> float:
    """
    Returns the constant value of a LinearTerm derived from child's
    geometry that has no variable part. Raises ValueError naming the
    child if it has one, i.e. it depends on positions that are not
    fixed relative to each other.
    """
    if any(abs(c) >= COEFF_EPS for c in term.coefficients):
        raise ValueError(
            f"Size of arrangement group child {describe(child)} is not "
            "constant. Cannot arrange the group.")
    return term.constant


@dataclass
class Endpoint:
    """
    Connectable boundary of an arrangement group child: an instance pin, a
    port's net or a nested group's boundary/rail.
    """
    net: 'Net' = None #: Net the endpoint is already connected to, or None.
    attach: Callable = None #: Callable that connects the endpoint to a given net, or None for endpoints that are themselves nets (ports).

    def connect(self, net: 'Net'):
        """Connects the endpoint to net. Raises ValueError on a conflict."""
        if self.net is not None:
            if self.net.nid != net.nid:
                raise ValueError(
                    f"Connection conflict between nets "
                    f"{describe(self.net)} and {describe(net)}.")
            return
        self.attach(net)


def adopted_net(endpoints: list[Endpoint]) -> 'Net | None':
    """
    Returns the net some of the endpoints are already connected to, or
    None. Raises ValueError if they are connected to more than one
    distinct net (connection conflict).
    """
    nets = {ep.net.nid: ep.net for ep in endpoints if ep.net is not None}
    if len(nets) > 1:
        names = ', '.join(sorted(describe(net) for net in nets.values()))
        raise ValueError(
            f"Connection conflict: endpoints are already connected to "
            f"different nets ({names}).")
    return next(iter(nets.values()), None)


def connect_endpoints(endpoints: list[Endpoint], root: SubgraphRoot):
    """
    Connects all endpoints to one shared net: a net an endpoint is
    already on is adopted (see adopted_net), otherwise an anonymous net
    is created on root.
    """
    from .schema import Net
    net = adopted_net(endpoints)
    if net is None:
        net = root % Net()
    for endpoint in endpoints:
        endpoint.connect(net)


class ArrangedRects(NamedTuple):
    """
    Rigid relative layout of a group's children, see
    ArrangementGroup.arrangement().
    """
    rects: list #: Child bounding boxes as Rect4LinearTerms.
    offsets: list #: Constant (x, y) offset of each child from the group's southwest corner.
    width: float #: Extent of the group along the x axis.
    height: float #: Extent of the group along the y axis.


@public
class ArrangementGroup(ABC):
    """
    Base class of all arrangement groups, see module docstring. Use Row or
    Col (or Series/Parallel for electrical connection).

    Args:
        gap: Distance between adjacent children along the main axis. The
            default leaves room for auto_wire() routing.
        align: Cross-axis alignment of the children: 'center' (snapped
            down to the unit grid), 'start' (bottom/left edge) or 'end'
            (top/right edge). None picks the group's default_align.
        anchor: Position of the group's southwest corner: an (x, y)
            tuple, None to never emit an anchor, or 'auto' (default) to
            anchor a top-level group at (0, 0) unless a member appears
            in a user constraint or has a directly assigned position.
    """
    aligns = ('center', 'start', 'end') #: Supported align values.
    default_align = 'center' #: align used when None is passed.

    @property
    @abstractmethod
    def vertical(self) -> bool:
        """Whether children are placed along the y axis instead of the x axis."""

    def __init__(self, gap: int = 2, align: str | None = None, anchor='auto'):
        if align is None:
            align = self.default_align
        if align not in self.aligns:
            raise ValueError(f"align must be one of {self.aligns}, got {align!r}.")
        self.children = []
        self.gap = gap
        self.align = align
        self.anchor = anchor
        self.sealed = False #: Set by rect() to block further add().

    def __enter__(self):
        """
        Registers the group with the enclosing group (or the view
        context for top-level groups) and marks it as the innermost
        active group, so that elements declared in the body register as
        its children. Unlike NodeContext, the name resolution root is
        left unchanged.
        """
        view_ctx = _view_ctx_var.get()
        if view_ctx is None:
            raise TypeError(
                "Arrangement groups can only be used in a schematic viewgen.")
        view_ctx.enter_group(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _view_ctx_var.get().exit_group()

    def add(self, child):
        """
        Appends a child (an instance, a port/net or a nested group) and
        returns it. Raises TypeError if the group is sealed because its
        outline was already used (see rect()), and ValueError if the
        child was already added.
        """
        if self.sealed:
            raise TypeError(f"{describe(self)} can no longer be extended: its outline was already used.")
        for existing in self.children:
            if child is existing or (isinstance(child, Node)
                    and isinstance(existing, Node)
                    and child.nid == existing.nid):
                raise ValueError(
                    f"{describe(child)} is already a child of "
                    f"{describe(self)}.")
        self.children.append(child)
        return child

    def subgraph_root(self) -> SubgraphRoot:
        """
        Returns the SubgraphRoot cursor of the children's subgraph,
        skipping over empty nested groups.
        """
        for child in self.children:
            if not isinstance(child, ArrangementGroup):
                return child.root
            try:
                return child.subgraph_root()
            except ValueError:
                continue
        raise ValueError(f"{describe(self)} has no children.")

    def child_rect(self, child) -> Rect4LinearTerm:
        """
        Returns a child's bounding box in view coordinates. A net is
        placed through its port. Ports are zero-size points at their
        position.
        """
        from .schema import Net, SchemPort
        if isinstance(child, ArrangementGroup):
            return child.rect()
        if isinstance(child, Net):
            try:
                child = child.port
            except QueryException:
                raise ValueError(
                    f"Cannot place net {describe(child)}: it has no "
                    "port.") from None
        if isinstance(child, SchemPort):
            pos = child.pos
            return Rect4LinearTerm(pos.x, pos.y, pos.x, pos.y)
        outline = child.outline
        return Rect4LinearTerm(outline.lx, outline.ly, outline.ux, outline.uy)

    def arrangement(self) -> ArrangedRects:
        """
        Computes the relative arrangement of the children. Since child
        sizes are constants, the arrangement is rigid. Center alignment
        is snapped down to the unit grid so that on-grid children stay
        on grid regardless of size differences.
        """
        if not self.children:
            raise ValueError(f"{describe(self)} has no children.")
        if self.vertical:
            main, cross = 1, 0
        else:
            main, cross = 0, 1
        rects = [self.child_rect(child) for child in self.children]
        main_sizes = [term_constant(r[main+2] - r[main], child)
            for child, r in zip(self.children, rects)]
        cross_offsets, cross_span = self.cross_arrangement(rects, cross)

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
            width, height = main_span, cross_span
        else:
            offsets = list(zip(cross_offsets, main_offsets))
            width, height = cross_span, main_span
        return ArrangedRects(rects, offsets, width, height)

    def cross_arrangement(self, rects: list, cross: int) -> tuple[list, float]:
        """
        Arranges the children on the cross axis according to align,
        returning (offsets, span): their constant offsets from the
        group's edge and the group's cross-axis extent.
        """
        sizes = [term_constant(r[cross+2] - r[cross], child)
            for child, r in zip(self.children, rects)]
        span = max(sizes)
        if self.align == 'center':
            offsets = [math.floor((span - size) / 2) for size in sizes]
        elif self.align == 'start':
            offsets = [0] * len(rects)
        else: # 'end'
            offsets = [span - size for size in sizes]
        return offsets, span

    def rect(self) -> Rect4LinearTerm:
        """
        Returns the group's bounding box, anchored on the first child.
        Reading it seals the group against further children (terms
        derived from it would not follow).
        """
        rects, offsets, width, height = self.arrangement()
        self.sealed = True
        lx = rects[0][0] - offsets[0][0]
        ly = rects[0][1] - offsets[0][1]
        return Rect4LinearTerm(lx, ly, lx + width, ly + height)

    @property
    def outline(self) -> Rect4LinearTerm:
        """Group bounding box, usable in constraints."""
        return self.rect()

    def __getattr__(self, name):
        # Convenience access to outline properties (south, center, lx, ...).
        # Unknown names must not reach self.outline: reading the outline
        # seals the group, which would make a typo mutate state. Names
        # inherited from tuple (count, index) are no outline properties
        # and must not seal the group either.
        if (name.startswith('_') or hasattr(tuple, name)
                or not hasattr(Rect4LinearTerm, name)):
            raise AttributeError(name)
        return getattr(self.outline, name)

    def variables(self) -> set[Variable]:
        """Returns the solver Variables of all (transitive) children's positions."""
        variables = set()
        for child in self.children:
            if isinstance(child, ArrangementGroup):
                variables |= child.variables()
            else:
                for term in self.child_rect(child):
                    variables |= set(term.variables)
        return variables

    def pinned(self) -> bool:
        """
        Returns True if any (transitive) child's position is already
        fixed. The group then follows that child and anchor='auto' does
        not apply.
        """
        for child in self.children:
            if isinstance(child, ArrangementGroup):
                if child.pinned():
                    return True
            elif not any(term.variables for term in self.child_rect(child)):
                return True
        return False

    def resolve_connectivity(self):
        """
        Establishes the group's electrical connections, a no-op for the
        purely geometric groups. emit() resolves a group's connectivity
        before its children's: a nested group receives its boundary nets
        from the enclosing group here and ties its internals to them
        when its own turn comes (ORDB cannot merge nets afterwards).
        """
        pass

    def emit(self, solver: Solver, toplevel: bool = True,
            auto_anchor: tuple = (0, 0)) -> bool:
        """
        Resolves the group's connectivity and emits its placement
        constraints into solver. Called by the view context during
        postprocessing. Call manually when using groups outside a
        viewgen. Nested groups are emitted with toplevel=False and never
        anchored. auto_anchor is the position used for anchor='auto'.
        Returns True if the automatic anchor was applied.
        """
        if toplevel:
            constrained = set()
            for constraint in chain(solver.equalities, solver.inequalities):
                constrained |= set(constraint.term.variables)
        self.resolve_connectivity()
        for child in self.children:
            if isinstance(child, ArrangementGroup):
                child.emit(solver, toplevel=False)
        arrangement = self.arrangement()
        rects, offsets = arrangement.rects, arrangement.offsets
        # The arrangement is rigid: tie each child to the first child by
        # its constant offset delta, per axis.
        for i, (rect, offset) in enumerate(zip(rects[1:], offsets[1:]), 1):
            for axis in (0, 1):
                term = ((rect[axis] - offset[axis])
                    - (rects[0][axis] - offsets[0][axis]))
                if (all(abs(c) < COEFF_EPS for c in term.coefficients)
                        and abs(term.constant) >= COEFF_EPS):
                    # Catch guaranteed contradictions here. The solver
                    # would only report an unspecific infeasibility.
                    raise ValueError(
                        f"Arrangement of {describe(self)} contradicts the "
                        f"directly assigned positions of "
                        f"{describe(self.children[0])} and "
                        f"{describe(self.children[i])}.")
                solver.constrain(EqualsZero(term))
        if not toplevel:
            return False
        anchor = self.anchor
        applied_auto = False
        if anchor == 'auto':
            # Groups placed by the user (own constraints or a directly
            # assigned child position) are not anchored.
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
class Row(ArrangementGroup):
    """Places children side by side, left to right along the x axis."""
    vertical = False


@public
class Col(ArrangementGroup):
    """Places children in a stack, top to bottom along the y axis."""
    vertical = True


class ConnectingGroup(ArrangementGroup):
    """
    Common base of the electrically connecting groups Series and
    Parallel: pin detection by facing side and shared net handling.

    Pin detection relies on the symbol convention that the pins carrying
    the current path face along its direction. It must be unambiguous:
    with several pins on a facing side, the top=/bottom= (vertical) or
    left=/right= (horizontal) pin names select the pin, uniformly for
    all instance children. horizontal chooses the orientation of the
    current path. The placement axis follows from it and
    flow_along_axis. gap, align and anchor are inherited from
    ArrangementGroup.
    """
    #: Whether the children are placed along the current path (Series)
    #: or across it (Parallel).
    flow_along_axis = None

    def __init__(self, gap: int = 2, align: str | None = None, anchor='auto',
            horizontal: bool = False, top: str | None = None,
            bottom: str | None = None, left: str | None = None,
            right: str | None = None):
        super().__init__(gap=gap, align=align, anchor=anchor)
        if horizontal and (top is not None or bottom is not None):
            raise ValueError(
                "top/bottom pin overrides only apply to vertical groups. Use left/right.")
        if not horizontal and (left is not None or right is not None):
            raise ValueError(
                "left/right pin overrides only apply to horizontal groups. Use top/bottom.")
        self.horizontal = horizontal
        self.pin_overrides = {D4.North: top, D4.South: bottom,
            D4.West: left, D4.East: right}
        # Sides through which the current path enters and leaves the
        # children, ordered (facing the next child, facing the previous
        # child). These are the rails of a Parallel.
        if horizontal:
            self.flow_sides = (D4.East, D4.West)
        else:
            self.flow_sides = (D4.South, D4.North)
        #: Nets forced onto a side by an enclosing group (Parallel rails).
        self.rail_nets = {}

    @property
    def vertical(self) -> bool:
        # Series places along the current path, Parallel across it.
        flow_vertical = not self.horizontal
        return flow_vertical if self.flow_along_axis else not flow_vertical

    @abstractmethod
    def resolve_connectivity(self):
        """
        Connects the children electrically. Mandatory for connecting
        groups (see ArrangementGroup.resolve_connectivity for the
        ordering contract).
        """

    def child_symbol(self, inst) -> 'Symbol':
        """
        Returns the Symbol of an instance child. For unresolved
        instances, it is generated from the recorded parameters.
        """
        from .schema import SchemInstance, SchemInstanceUnresolvedParameter
        if isinstance(inst, SchemInstance):
            return inst.symbol
        params = {
            p.name: p.value
            for p in inst.root.all(SchemInstanceUnresolvedParameter.ref_idx.query(inst))
        }
        return inst.resolver(**params)

    def facing_pin(self, inst, side: D4) -> str:
        """
        Returns the name of the single pin of an instance child that
        faces side, honoring the group's pin name overrides. Raises
        ValueError if no unambiguous, plainly named pin is found.
        """
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
                f"found {len(candidates)}. Pass pin name overrides to "
                "select pins explicitly.")
        pin = candidates[0]
        # Auto-connection needs a plain pin name: it is matched against
        # name-based unresolved connections and passed to getattr().
        path = pin.full_path_list() if pin.npath_nid is not None else None
        if path is None or len(path) != 1:
            raise ValueError(
                f"{type(self).__name__} cannot auto-connect pin "
                f"{describe(pin)} of {describe(inst)}. Pass pin name "
                "overrides to select pins explicitly.")
        return path[0]

    def pin_net(self, inst, pin_name: str) -> 'Net | None':
        """Returns the net a pin of an instance child is connected to, or None."""
        from .schema import (SchemInstance, SchemInstanceConn,
            SchemInstanceUnresolvedConn)
        if isinstance(inst, SchemInstance):
            pin = getattr(inst.symbol, pin_name)
            query = SchemInstanceConn.ref_pin_idx.query((inst, pin))
            conn = next(iter(inst.root.all(query)), None)
            return conn.here if conn is not None else None
        for conn in inst.root.all(SchemInstanceUnresolvedConn.ref_idx.query(inst)):
            if conn.there == (pin_name,):
                return conn.here
        return None

    def endpoint(self, child, side: D4) -> Endpoint:
        """Returns the Endpoint of a direct child on the given side."""
        from .schema import Net, SchemPort
        if isinstance(child, ConnectingGroup):
            return child.side_endpoint(side)
        if isinstance(child, ArrangementGroup):
            raise ValueError(
                f"{type(self).__name__} cannot connect a nested Col/Row "
                "group. Nest Series/Parallel or wire explicitly.")
        if isinstance(child, SchemPort):
            return Endpoint(net=child.ref)
        if isinstance(child, Net):
            return Endpoint(net=child)
        name = self.facing_pin(child, side)
        return Endpoint(net=self.pin_net(child, name),
            attach=lambda net: getattr(child, name).__wire_op__(net))

    @abstractmethod
    def side_endpoint(self, side: D4) -> Endpoint:
        """Returns the boundary Endpoint offered to an enclosing connecting group."""

    def boundary_junction_offset(self, side: D4, cross: int) -> float | None:
        """
        Returns the cross-axis offset of the group's boundary connection
        point within its bounding box, or None if there is no single
        point (a Parallel rail). Used by Series align='pins'.
        """
        return None


@public
class Series(ConnectingGroup):
    """
    Places children in a stack like Col (side by side like Row with
    horizontal=True) and connects them in series, modeling a current
    path: the pin of each child facing the next child is connected to
    the next child's pin facing back. Port children connect through
    their net. A junction's net is adopted from whichever facing pin is
    already connected, so it can be named by wiring one pin explicitly
    (e.g. ``.d -- y``). Otherwise an anonymous net is created.

    The default alignment 'pins' aligns each pair's facing pins on one
    line, giving straight junction wires. Pass align='center' to center
    the children's bounding boxes instead.
    """
    flow_along_axis = True
    aligns = ('center', 'start', 'end', 'pins')
    default_align = 'pins'

    def resolve_connectivity(self):
        to_next, to_prev = self.flow_sides
        for prev, cur in zip(self.children, self.children[1:]):
            connect_endpoints([
                self.endpoint(prev, to_next),
                self.endpoint(cur, to_prev),
            ], self.subgraph_root())

    def side_endpoint(self, side: D4) -> Endpoint:
        if not self.children:
            raise ValueError(f"{describe(self)} has no children.")
        return self.endpoint(self.children[self.boundary_index(side)], side)

    def boundary_index(self, side: D4) -> int:
        """Returns the index of the child forming the group's boundary on side."""
        to_next, to_prev = self.flow_sides
        if side == to_prev:
            return 0
        if side == to_next:
            return -1
        raise ValueError(
            f"Series has no {SIDE_NAMES[side]}-facing boundary "
            "(orientation mismatch with the enclosing group).")

    def cross_arrangement(self, rects: list, cross: int) -> tuple[list, float]:
        if self.align != 'pins':
            return super().cross_arrangement(rects, cross)
        sizes = [term_constant(r[cross+2] - r[cross], child)
            for child, r in zip(self.children, rects)]
        # Chain the offsets so that each pair's facing pins line up.
        # Flooring snaps to the unit grid where center fallbacks (nested
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

    def junction_offset(self, child, side: D4, rect: tuple, cross: int) -> float:
        """
        Returns the cross-axis offset of a child's connection point on
        side, relative to its bounding box, or the center where there is no
        single connection point (nested Parallel rails).
        """
        from .schema import Net, SchemPort
        if isinstance(child, ConnectingGroup):
            offset = child.boundary_junction_offset(side, cross)
            if offset is None:
                offset = term_constant(rect[cross+2] - rect[cross], child) / 2
            return offset
        if isinstance(child, (Net, SchemPort)):
            return 0
        pin = getattr(child, self.facing_pin(child, side)).pos
        coord = pin.x if cross == 0 else pin.y
        return term_constant(coerce_term(coord) - rect[cross], child)

    def boundary_junction_offset(self, side: D4, cross: int) -> float:
        index = self.boundary_index(side)
        arrangement = self.arrangement()
        return (arrangement.offsets[index][cross]
            + self.junction_offset(self.children[index], side,
                arrangement.rects[index], cross))


@public
class Parallel(ConnectingGroup):
    """
    Places children side by side like Row (stacked like Col with
    horizontal=True) and connects them in parallel: all upward-facing
    pins are tied to one rail net and all downward-facing pins to
    another (left-/right-facing with horizontal=True). To name a rail
    net, wire one child pin explicitly (e.g. ``.d -- y``). Port children
    are not supported. Wire ports to the rail nets explicitly.
    """
    flow_along_axis = False

    def resolve_connectivity(self):
        for side in self.flow_sides:
            connect_endpoints(self.rail_endpoints(side), self.subgraph_root())

    def rail_endpoints(self, side: D4) -> list[Endpoint]:
        """
        Returns the Endpoints of one rail: one per child, plus a net an
        enclosing group forced onto the rail.
        """
        from .schema import Net, SchemPort
        endpoints = []
        for child in self.children:
            if isinstance(child, (Net, SchemPort)):
                net = child.ref if isinstance(child, SchemPort) else child
                raise ValueError(
                    f"Parallel does not support the port child "
                    f"{describe(net)}. Wire the rail net to the port explicitly.")
            endpoints.append(self.endpoint(child, side))
        forced = self.rail_nets.get(side)
        if forced is not None:
            endpoints.append(Endpoint(net=forced))
        return endpoints

    def side_endpoint(self, side: D4) -> Endpoint:
        if side not in self.flow_sides:
            raise ValueError(
                f"Parallel has no {SIDE_NAMES[side]}-facing rail "
                "(orientation mismatch with the enclosing group).")
        # The rail's net so far: forced by an enclosing group or wired
        # explicitly on a child pin, or None while the rail is still open.
        return Endpoint(net=adopted_net(self.rail_endpoints(side)),
            attach=lambda net: self.rail_nets.update({side: net}))
