# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *

class SRouterException(Exception):
    pass

class SRouter:
    """Stack router"""
    def __init__(self, layout: Layout, solver: Solver, layer: Layer,
        pos: Vec2LinearTerm, routing_spec: RoutingSpec):
        self.layout = layout
        self.solver = solver
        self.routing_spec = routing_spec
        self.cur_layer = layer
        self.cur_pos = pos
        self.path = None
        self.path_order = 0
        self.stack = []
        self.place_throughrect = True

    def _rsl(self) -> RoutingSpecLayer:
        """Look up the RoutingSpecLayer for the current layer."""
        return self.routing_spec.one(RoutingSpecLayer.layer_index.query(self.cur_layer))

    def push(self):
        self.stack.append(self.cur_pos)

    def pop(self):
        self._end_path()
        self.place_throughrect = False
        self.cur_pos = self.stack.pop()

    def _add_vertex(self):
        v = self.path % PolyVec2I(order=self.path_order)
        self.solver.constrain(v.pos==self.cur_pos)
        self.path_order += 1

    def move(self, pos: Vec2LinearTerm):
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

    def _end_path(self):
        if self.path is None:
            if self.place_throughrect:
                rsl = self._rsl()
                if None in (rsl.route_via_width, rsl.route_via_height):
                    raise SRouterException("Cannot draw via-like rect on layer wher"
                        " route_via_width or route_via_height is None.")
                r = self.layout % LayoutRect(layer=self.cur_layer)
                self.solver.constrain(r.rect.center == self.cur_pos)
                self.solver.constrain(r.rect.size ==
                    (rsl.route_via_width, rsl.route_via_height))
        else:
            self.path = None
            self.path_order = 0
        self.place_throughrect = True

    def layer(self, layer: Layer):
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

        self.cur_layer = layer
