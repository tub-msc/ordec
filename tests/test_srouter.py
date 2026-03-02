# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.layout import SRouter, compare
from ordec.lib import ihp130
from ordec.core import *

layers = ihp130.SG13G2().layers
rs = ihp130.SG13G2().default_routing_spec

@generate_func
def layout_basic():
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
    expected = Layout(ref_layers=layers)
    expected % LayoutPath(layer=layers.Metal1, width=210, endtype=PathEndType.Custom,
        ext_bgn=145, ext_end=145,
        vertices=[Vec2I(0, 0), Vec2I(1000, 0), Vec2I(1000, 1000)])
    expected % LayoutPath(layer=layers.Metal3, width=210, endtype=PathEndType.Custom,
        ext_bgn=145, ext_end=145,
        vertices=[Vec2I(1000, 1000), Vec2I(0, 1000)])
    expected % LayoutRect(layer=layers.Via1, rect=Rect4I(905, 905, 1095, 1095))
    expected % LayoutRect(layer=layers.Via2, rect=Rect4I(905, 905, 1095, 1095))
    expected % LayoutRect(layer=layers.Metal2, rect=Rect4I(760, 850, 1240, 1150))
    assert compare(layout_basic(), expected) is None

@generate_func
def layout_push_pop():
    """T-shaped route: go right, push, go up, pop, go down."""
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
    """T-shaped route: go right, push, go up, pop, change layer, go down."""
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
    expected = Layout(ref_layers=layers)
    expected % LayoutPath(layer=layers.Metal1, width=210, endtype=PathEndType.Custom,
        ext_bgn=145, ext_end=145,
        vertices=[Vec2I(0, 0), Vec2I(1000, 0), Vec2I(1000, 1000)])
    expected % LayoutPath(layer=layers.Metal1, width=210, endtype=PathEndType.Custom,
        ext_bgn=145, ext_end=145,
        vertices=[Vec2I(1000, 0), Vec2I(1000, -1000)])
    assert compare(layout_push_pop(), expected) is None

def test_push_pop_layerchange():
    expected = Layout(ref_layers=layers)
    expected % LayoutPath(layer=layers.Metal1, width=210, endtype=PathEndType.Custom,
        ext_bgn=145, ext_end=145,
        vertices=[Vec2I(0, 0), Vec2I(1000, 0), Vec2I(1000, 1000)])
    expected % LayoutPath(layer=layers.Metal2, width=210, endtype=PathEndType.Custom,
        ext_bgn=145, ext_end=145,
        vertices=[Vec2I(1000, 0), Vec2I(1000, -1000)])
    expected % LayoutRect(layer=layers.Via1, rect=Rect4I(905, -95, 1095, 95))
    assert compare(layout_push_pop_layerchange(), expected) is None
