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
    sr = SRouter(rs, layout=l, solver=s)
    sr.move(layers.Metal1, (0, 0))
    sr.wire((1000, 0))
    sr.wire((1000, 1000))
    sr.layer(layers.Metal3)
    sr.wire((0, 1000))

    s.solve()
    return l

def test_basic():
    expected = Layout(ref_layers=layers)
    expected % LayoutPath(layer=layers.Metal1, width=200, endtype=PathEndType.Custom,
        ext_bgn=150, ext_end=150,
        vertices=[Vec2I(0, 0), Vec2I(1000, 0), Vec2I(1000, 1000)])
    expected % LayoutPath(layer=layers.Metal3, width=200, endtype=PathEndType.Custom,
        ext_bgn=150, ext_end=150,
        vertices=[Vec2I(1000, 1000), Vec2I(0, 1000)])
    # layer() emits a complete via stack: cuts plus landing pads on every
    # metal, including the start (Metal1) and destination (Metal3) layers.
    # The pads at the ends of the stack are route_pad-sized, as the wires
    # running into them supply the endcap enclosure; the Metal2 pad in the
    # middle of the stack stands on its own and is route_via-sized.
    expected % LayoutRect(layer=layers.Metal1, rect=Rect4I(895, 895, 1105, 1105))
    expected % LayoutRect(layer=layers.Via1, rect=Rect4I(905, 905, 1095, 1095))
    expected % LayoutRect(layer=layers.Metal2, rect=Rect4I(760, 850, 1240, 1150))
    expected % LayoutRect(layer=layers.Via2, rect=Rect4I(905, 905, 1095, 1095))
    expected % LayoutRect(layer=layers.Metal3, rect=Rect4I(895, 895, 1105, 1105))
    assert compare(layout_basic(), expected) is None

@generate_func
def layout_push_pop():
    """T-shaped route: go right, push, go up, pop, go down."""
    l = Layout(ref_layers=layers)
    s = Solver(l)
    sr = SRouter(rs, layout=l, solver=s)
    sr.move(layers.Metal1, (0, 0))
    sr.wire((1000, 0))
    sr.push()
    sr.wire((1000, 1000))
    sr.pop()
    sr.wire((1000, -1000))

    s.solve()
    return l

@generate_func
def layout_push_pop_layerchange():
    """T-shaped route: go right, push, go up, pop, change layer, go down."""
    l = Layout(ref_layers=layers)
    s = Solver(l)
    sr = SRouter(rs, layout=l, solver=s)
    sr.move(layers.Metal1, (0, 0))
    sr.wire((1000, 0))
    sr.push()
    sr.wire((1000, 1000))
    sr.pop()
    sr.layer(layers.Metal2)
    sr.wire((1000, -1000))
    s.solve()
    return l

def test_push_pop():
    expected = Layout(ref_layers=layers)
    expected % LayoutPath(layer=layers.Metal1, width=200, endtype=PathEndType.Custom,
        ext_bgn=150, ext_end=150,
        vertices=[Vec2I(0, 0), Vec2I(1000, 0), Vec2I(1000, 1000)])
    expected % LayoutPath(layer=layers.Metal1, width=200, endtype=PathEndType.Custom,
        ext_bgn=150, ext_end=150,
        vertices=[Vec2I(1000, 0), Vec2I(1000, -1000)])
    assert compare(layout_push_pop(), expected) is None

def test_push_pop_layerchange():
    expected = Layout(ref_layers=layers)
    expected % LayoutPath(layer=layers.Metal1, width=200, endtype=PathEndType.Custom,
        ext_bgn=150, ext_end=150,
        vertices=[Vec2I(0, 0), Vec2I(1000, 0), Vec2I(1000, 1000)])
    expected % LayoutPath(layer=layers.Metal2, width=200, endtype=PathEndType.Custom,
        ext_bgn=150, ext_end=150,
        vertices=[Vec2I(1000, 0), Vec2I(1000, -1000)])
    expected % LayoutRect(layer=layers.Metal1, rect=Rect4I(895, -105, 1105, 105))
    expected % LayoutRect(layer=layers.Via1, rect=Rect4I(905, -95, 1095, 95))
    expected % LayoutRect(layer=layers.Metal2, rect=Rect4I(895, -105, 1105, 105))
    assert compare(layout_push_pop_layerchange(), expected) is None
