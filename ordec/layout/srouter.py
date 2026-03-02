# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *

class SRouterException(Exception):
    pass

class SRouter:
    """Stack router"""
    def __init__(self, layout: Layout, solver: Solver, layer: Layer, pos: Vec2LinearTerm):
        self.layout = layout
        self.solver = solver
        self.cur_layer = layer
        self.cur_pos = pos
        self.path = None
        self.path_order = 0

    def _add_vertex(self):
        v = self.path % PolyVec2I(order=self.path_order)
        self.solver.constrain(v.pos==self.cur_pos)
        self.path_order += 1

    def move(self, pos: Vec2LinearTerm):
        if self.path is None:
            l = self.cur_layer
            if None in (l.route_wire_width, l.route_wire_ext):
                raise SRouterException("Cannot draw wire on layer where"
                    " route_wire_width or route_wire_ext is None.")
            self.path = self.layout % LayoutPath(
                layer=l,
                width=l.route_wire_width,
                endtype=PathEndType.Custom,
                ext_bgn=l.route_wire_ext,
                ext_end=l.route_wire_ext,
                )
            self._add_vertex()

        self.cur_pos = pos
        self._add_vertex()

    def _end_path(self):
        l = self.cur_layer
        if self.path is None:
            if None in (l.route_via_width, l.route_via_height):
                raise SRouterException("Cannot draw via-like rect on layer wher"
                    " route_via_width or route_via_height is None.")
            r = self.layout % LayoutRect(layer=l)
            self.solver.constrain(r.rect.center == self.cur_pos)
            self.solver.constrain(r.rect.size ==
                (l.route_via_width, l.route_via_height))
        else:
            self.path = None
            self.path_order = 0

    def layer(self, layer: Layer):
        while self.cur_layer != layer:
            self._end_path()
            if self.cur_layer.route_id < layer.route_id:
                route_id_next = self.cur_layer.route_id + 1
            else:
                route_id_next = self.cur_layer.route_id - 1
            self.cur_layer = layer.root.one(Layer.route_id_index.query(route_id_next))

        self.cur_layer = layer
