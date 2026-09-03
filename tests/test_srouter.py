# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.layout import SRouter, SRouterException, compare
from ordec.lib import ihp130
from ordec.core import *

layers = ihp130.SG13G2().layers
rs = ihp130.SG13G2().default_routing_spec

@viewgen_noctx
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

@viewgen_noctx
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

@viewgen_noctx
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

@viewgen_noctx
def layout_pass_through_riser():
    """move, layer(Metal2), layer(Metal3), then a wire."""
    l = Layout(ref_layers=layers)
    s = Solver(l)
    sr = SRouter(rs, layout=l, solver=s)
    sr.move(layers.Metal1, (0, 0))
    sr.layer(layers.Metal2)
    sr.layer(layers.Metal3)
    sr.wire((1000, 0))
    s.solve()
    return l

def test_pass_through_riser_gets_a_full_pad_on_the_stack_top():
    # The Metal1 start pad and the Metal3 destination pad are wire-sized.
    # The Metal2 start pad of the second layer() call sits on top of the
    # first stack and gets the full route_via pad.
    expected = Layout(ref_layers=layers)
    expected % LayoutRect(layer=layers.Metal1, rect=Rect4I(-105, -105, 105, 105))
    expected % LayoutRect(layer=layers.Via1, rect=Rect4I(-95, -95, 95, 95))
    expected % LayoutRect(layer=layers.Metal2, rect=Rect4I(-105, -105, 105, 105))
    expected % LayoutRect(layer=layers.Metal2, rect=Rect4I(-240, -150, 240, 150))
    expected % LayoutRect(layer=layers.Via2, rect=Rect4I(-95, -95, 95, 95))
    expected % LayoutRect(layer=layers.Metal3, rect=Rect4I(-105, -105, 105, 105))
    expected % LayoutPath(layer=layers.Metal3, width=200, endtype=PathEndType.Custom,
        ext_bgn=150, ext_end=150,
        vertices=[Vec2I(0, 0), Vec2I(1000, 0)])
    assert compare(layout_pass_through_riser(), expected) is None

def test_path_after_layer_change_raises_with_the_idiom():
    import pytest
    l = Layout(ref_layers=layers)
    s = Solver(l)
    sr = SRouter(rs, layout=l, solver=s)
    sr.move(layers.Metal1, (0, 0))
    sr.wire((1000, 0))
    assert sr.path is not None
    sr.layer(layers.Metal2)
    # layer() ends the path.
    with pytest.raises(SRouterException, match="right after the last wire"):
        sr.path

@viewgen_noctx
def layout_top_metal():
    l = Layout(ref_layers=layers)
    s = Solver(l)
    sr = SRouter(rs, layout=l, solver=s)
    sr.move(layers.TopMetal1, (0, 0))
    sr.wire((5000, 0))
    sr.layer(layers.TopMetal2)
    sr.wire((5000, 5000))
    s.solve()
    return l

def test_top_via2_pad_enclosure():
    # TV2.c/d demand 500 nm TopMetal1 enclosure of the 900 nm TopVia2 cut on
    # both sides, which the wire endcap cannot supply sideways, so even the
    # stack-end pad must be route_pad = 1900 nm.
    l = layout_top_metal()
    cut = next(r.rect for r in l.all(LayoutRect) if r.layer == layers.TopVia2)
    pad = next(r.rect for r in l.all(LayoutRect) if r.layer == layers.TopMetal1)
    assert (cut.ux - cut.lx, cut.uy - cut.ly) == (900, 900)
    assert min(cut.lx - pad.lx, cut.ly - pad.ly,
        pad.ux - cut.ux, pad.uy - cut.uy) >= 500
