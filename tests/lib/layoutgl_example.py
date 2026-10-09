# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *
from ordec.lib.ihp130 import SG13G2

@viewgen_noctx
def layoutgl_example() -> Layout:
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)

    l % LayoutPoly(
        layer=layers.Metal1,
        vertices=[
            Vec2I(0, 0),
            Vec2I(0, 1000),
            Vec2I(1000, 1000),
            Vec2I(1000, 500),
            Vec2I(500, 500),
            Vec2I(500, 0),
        ],
    )
    # The Metal3.pin square (250, 250)-(750, 750) comes from a rotated
    # instance of a subcell holding a LayoutRect, which exercises the
    # hierarchical transfer and rect rendering of the viewer.
    sub = Layout(ref_layers=layers)
    sub % LayoutRect(layer=layers.Metal3.pin, rect=Rect4I(0, -500, 500, 0))
    l % LayoutInstance(pos=Vec2I(250, 250), orient=D4.R90, ref=sub.freeze())
    l % LayoutLabel(
        layer=layers.Metal3.pin,
        pos=Vec2I(500,500),
        text='This example tests layout-gl.js!'
    )

    l % LayoutLabel(
        layer=layers.Metal4.pin,
        pos=Vec2I(1000, 0),
        text='Another label here'
    )
    return l
