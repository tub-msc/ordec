from ordec.core import *
from ordec.lib import ihp130

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
            self.path = self.layout % LayoutPath(
                layer=self.cur_layer, width=200, endtype=PathEndType.Square)
            self._add_vertex()

        self.cur_pos = pos
        self._add_vertex()

    def _end_path(self):
        self.path = None
        self.path_order = 0

    def layer(self, layer: Layer):
        self._end_path()
        self.cur_layer = layer

@generate_func
def layout_x():
    layers = ihp130.SG13G2().layers
    l = Layout(ref_layers=layers)
    s = Solver(l)
    sr = SRouter(l, s, layers.Metal1, pos=(0, 0))
    sr.move((1000, 0))
    sr.move((1000, 1000))
    sr.layer(layers.Metal2)
    sr.move((0, 1000))

    s.solve()
    return l
