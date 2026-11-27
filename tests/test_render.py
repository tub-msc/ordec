# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import io
from PIL import Image
from ordec.core import *
from ordec.lib import generic_mos
from ordec.render import render_png
from .lib.layoutgl_example import layoutgl_example

def png_image(png) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert('RGB')

def test_render_layout():
    # 1 pixel = 10 layout units, y pointing down.
    region = Rect4I(0, 0, 1000, 1000)
    img = png_image(render_png(layoutgl_example(), size=100, region=region,
        labels=False, subcell_pins=True))
    assert img.size == (100, 100)
    pixel = lambda img, x, y: img.getpixel((x // 10, (1000 - y) // 10))
    assert pixel(img, 900, 100) == (0, 0, 0) # background
    # Metal1 only, Metal3.pin only (from the rotated subcell instance), both:
    metal1, metal3, both = pixel(img, 100, 900), pixel(img, 700, 300), pixel(img, 300, 300)
    assert len({metal1, metal3, both, (0, 0, 0)}) == 4

    # Without subcell_pins, the pin layers of the subcell are left out.
    default = png_image(render_png(layoutgl_example(), size=100, region=region))
    assert pixel(default, 700, 300) == (0, 0, 0)
    assert pixel(default, 100, 900) == metal1
    assert default != png_image(render_png(layoutgl_example(), size=100, region=region, labels=False))

def test_render_schematic():
    img = png_image(render_png(generic_mos.Inv().schematic, size=300))
    assert max(img.size) == 300
    # Instance names are red: text is rendered, with the schematic CSS.
    assert any(c == (255, 0, 0) for _, c in img.getcolors(1 << 24))
