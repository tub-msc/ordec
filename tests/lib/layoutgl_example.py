# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *
from ordec.lib.ihp130 import SG13G2

@generate_func
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
    l % LayoutPoly(
        layer=layers.Metal3.pin,
        vertices=[
            Vec2I(250, 250),
            Vec2I(250, 750),
            Vec2I(750, 750),
            Vec2I(750, 250),
        ],
    )
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
