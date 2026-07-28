# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *

class SRouterException(Exception):
    pass

class SRouter:
    """Stack router"""
    def __init__(self, routing_spec: RoutingSpec,
        layout: Layout = None, solver: Solver = None):
        """Create a stack router.

        If layout or solver are not provided, they are obtained from the
        current LayoutViewContext.
        """
        if layout is None or solver is None:
            from ordec.ord.context import view_context
            vc = view_context()
            if layout is None:
                layout = vc.root
            if solver is None:
                solver = vc.solver
        self.layout = layout
        self.solver = solver
        self.routing_spec = routing_spec
        self.cur_layer = None
        self.cur_pos = None
        self.path = None
        self.path_order = 0
        self.stack = []

    def _rsl(self) -> RoutingSpecLayer:
        """Look up the RoutingSpecLayer for the current layer."""
        return self.routing_spec.one(RoutingSpecLayer.layer_index.query(self.cur_layer))

    def push(self):
        self.stack.append((self.cur_pos, self.cur_layer))

    def pop(self):
        self.path = None
        self.path_order = 0
        self.cur_pos, self.cur_layer = self.stack.pop()

    def _check_initialized(self):
        if self.cur_layer is None:
            raise SRouterException("Must call move() before wire/layer operations.")

    def _add_vertex(self):
        v = self.path % PolyVec2I(order=self.path_order)
        self.solver.constrain(v.pos==self.cur_pos)
        self.path_order += 1

    def move(self, layer: Layer, pos: Vec2LinearTerm):
        """Set position and layer without drawing (like SVG 'M')."""
        self.path = None
        self.path_order = 0
        self.cur_pos = pos
        self.cur_layer = layer

    def wire(self, pos: Vec2LinearTerm):
        """Draw a wire to pos (like SVG 'L')."""
        self._check_initialized()
        if self.path is None:
            rsl = self._rsl()
            if None in (rsl.route_wire_width, rsl.route_wire_ext):
                raise SRouterException("Cannot draw wire on layer where"
                    " route_wire_width or route_wire_ext is None.")
            self.path = self.layout % LayoutPath(
                layer=self.cur_layer,
                width=rsl.route_wire_width,
                endtype=PathEndType.Custom,
                ext_bgn=rsl.route_wire_ext,
                ext_end=rsl.route_wire_ext,
                )
            self._add_vertex()

        self.cur_pos = pos
        self._add_vertex()

    def wire_x(self, x):
        """Draw a horizontal wire (like SVG 'H')."""
        self.wire((x, self.cur_pos[1]))

    def wire_y(self, y):
        """Draw a vertical wire (like SVG 'V')."""
        self.wire((self.cur_pos[0], y))

    def _end_path(self):
        """End the current path (if any) and emit the via-stack element of
        the current layer at the current position: the cut on via layers, a
        route_via-sized landing pad on metal layers. Pads on the metals are
        required because a wire alone (route_wire_width) does not satisfy
        the via enclosure rules (e.g. V1.c/V1.c1 for SG13G2)."""
        rsl = self._rsl()
        if None in (rsl.route_via_width, rsl.route_via_height):
            raise SRouterException("Cannot draw via-like rect on layer where"
                " route_via_width or route_via_height is None.")
        r = self.layout % LayoutRect(layer=self.cur_layer)
        self.solver.constrain(r.center == self.cur_pos)
        self.solver.constrain(r.size ==
            (rsl.route_via_width, rsl.route_via_height))
        self.path = None
        self.path_order = 0

    def layer(self, layer: Layer):
        """Change to another routing layer, emitting a complete via stack at
        the current position: cuts plus landing pads on every metal layer
        traversed, including the start and destination layers."""
        self._check_initialized()
        if self.cur_layer == layer:
            return
        while self.cur_layer != layer:
            self._end_path()
            rsl = self._rsl()
            if rsl.route_id < self.routing_spec.one(
                RoutingSpecLayer.layer_index.query(layer)).route_id:
                route_id_next = rsl.route_id + 1
            else:
                route_id_next = rsl.route_id - 1
            next_rsl = self.routing_spec.one(
                RoutingSpecLayer.route_id_index.query(route_id_next))
            self.cur_layer = next_rsl.layer

        # Landing pad on the destination layer:
        self._end_path()
