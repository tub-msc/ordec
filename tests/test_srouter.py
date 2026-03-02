# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.layout import SRouter
from ordec.lib import ihp130
from ordec.core import *

@generate_func
def layout_basic():
    layers = ihp130.SG13G2().layers
    rs = ihp130.SG13G2().default_routing_spec
    l = Layout(ref_layers=layers)
    s = Solver(l)
    sr = SRouter(l, s, layers.Metal1, pos=(0, 0), routing_spec=rs)
    sr.move((1000, 0))
    sr.move((1000, 1000))
    sr.layer(layers.Metal3)
    sr.move((0, 1000))

    s.solve()
    return l

def test_basic():
    layers = ihp130.SG13G2().layers
    l = layout_basic()

    (p1,) = [p for p in l.all(LayoutPath) if p.layer == layers.Metal1]
    assert p1.width == 210
    assert p1.endtype == PathEndType.Custom
    assert p1.ext_bgn == p1.ext_end == 145
    assert p1.vertices() == [Vec2I(0, 0), Vec2I(1000, 0), Vec2I(1000, 1000)]

    (p3,) = [p for p in l.all(LayoutPath) if p.layer == layers.Metal3]
    assert p3.width == 210
    assert p3.endtype == PathEndType.Custom
    assert p3.ext_bgn == p3.ext_end == 145
    assert p3.vertices() == [Vec2I(1000, 1000), Vec2I(0, 1000)]

    (via1,) = [r for r in l.all(LayoutRect) if r.layer == layers.Via1]
    assert via1.rect == Rect4I(905, 905, 1095, 1095)

    (via2,) = [r for r in l.all(LayoutRect) if r.layer == layers.Via2]
    assert via2.rect == Rect4I(905, 905, 1095, 1095)

    (m2,) = [r for r in l.all(LayoutRect) if r.layer == layers.Metal2]
    assert m2.rect == Rect4I(760, 850, 1240, 1150)

@generate_func
def layout_push_pop():
    """T-shaped route: go right, push, go up, pop, go down."""
    layers = ihp130.SG13G2().layers
    rs = ihp130.SG13G2().default_routing_spec
    l = Layout(ref_layers=layers)
    s = Solver(l)
    sr = SRouter(l, s, layers.Metal1, pos=(0, 0), routing_spec=rs)
    sr.move((1000, 0))
    sr.push()
    sr.move((1000, 1000))
    sr.pop()
    sr.move((1000, -1000))

    s.solve()
    return l

@generate_func
def layout_push_pop_layerchange():
    """T-shaped route: go right, push, go up, pop, go down."""
    layers = ihp130.SG13G2().layers
    rs = ihp130.SG13G2().default_routing_spec
    l = Layout(ref_layers=layers)
    s = Solver(l)
    sr = SRouter(l, s, layers.Metal1, pos=(0, 0), routing_spec=rs)
    sr.move((1000, 0))
    sr.push()
    sr.move((1000, 1000))
    sr.pop()
    sr.layer(layers.Metal2)
    sr.move((1000, -1000))
    s.solve()
    return l

def test_push_pop():
    layers = ihp130.SG13G2().layers
    l = layout_push_pop()

    paths = sorted(l.all(LayoutPath), key=lambda p: p.vertices()[-1].y, reverse=True)
    assert len(paths) == 2

    # Horizontal + upper arm (push doesn't end path): (0,0) -> (1000,0) -> (1000,1000)
    assert paths[0].vertices() == [Vec2I(0, 0), Vec2I(1000, 0), Vec2I(1000, 1000)]
    # After pop: new path from pushed pos downward: (1000,0) -> (1000,-1000)
    assert paths[1].vertices() == [Vec2I(1000, 0), Vec2I(1000, -1000)]

def test_push_pop_layerchange():
    layers = ihp130.SG13G2().layers
    l = layout_push_pop_layerchange()

    # M1 path: (0,0) -> (1000,0) -> (1000,1000), ended by pop
    (p1,) = [p for p in l.all(LayoutPath) if p.layer == layers.Metal1]
    assert p1.vertices() == [Vec2I(0, 0), Vec2I(1000, 0), Vec2I(1000, 1000)]

    # Pop sets place_throughrect=False, so no M1 through-rect is placed.
    # Layer change M1→M2 traverses Via1, placing only the Via1 rect.
    (via1,) = [r for r in l.all(LayoutRect) if r.layer == layers.Via1]
    assert via1.rect.center == Vec2I(1000, 0)

    # No extra Metal1 rect from the layer change
    assert len([r for r in l.all(LayoutRect) if r.layer == layers.Metal1]) == 0

    # M2 path from popped position downward
    (p2,) = [p for p in l.all(LayoutPath) if p.layer == layers.Metal2]
    assert p2.vertices() == [Vec2I(1000, 0), Vec2I(1000, -1000)]
