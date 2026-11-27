# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Rendering of layouts, schematics and symbols to SVG and PNG, without a
browser: for looking at views from scripts, documentation and tests.
"""

import atexit
import functools
from importlib.resources import files
import os
import tarfile
import tempfile
import xml.etree.ElementTree as ET
import resvg_py
from public import public
from .core import *
from .layout.svg import layout_svg
from . import vite

# Font of labels and schematic text, in the frontend's public/ directory.
FONT = 'fonts/Inconsolata/Inconsolata-VariableFont_wdth,wght.ttf'

@functools.cache
def font_file() -> str:
    """
    Path of FONT: from the packaged frontend (webdist.tar) or, in editable
    installations, from the checkout's web/public.
    """
    webdist_tar = files(__package__) / 'webdist.tar'
    if webdist_tar.is_file():
        # resvg_py takes font files by path only.
        with tarfile.open(webdist_tar) as tar:
            data = tar.extractfile(f'./{FONT}').read()
        fd, path = tempfile.mkstemp(suffix='.ttf')
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        atexit.register(os.remove, path)
        return path
    if vite.available():
        return str(vite.web_path / 'public' / FONT)
    raise FileNotFoundError("Neither webdist.tar nor the web/ directory of a checkout was found.")

@public
def render_svg(view, **kwargs) -> bytes:
    """
    Renders a view to SVG.

    Args:
        view: Layout, Schematic or Symbol.
        kwargs: Options of layout_svg (layouts) or of
            ordec.schematic.render.render (schematics and symbols).
    """
    if isinstance(view, Layout):
        return layout_svg(view, **kwargs)
    if isinstance(view, (Schematic, Symbol)):
        return view.render(**kwargs).svg()
    raise TypeError(f"Cannot render {type(view).__name__} to SVG.")

@public
def render_png(view, path=None, *, size: int = 1600, **kwargs) -> bytes | None:
    """
    Renders a view to PNG.

    Args:
        view: Layout, Schematic or Symbol.
        path: File to write the PNG to. If None, the PNG is returned.
        size: Size of the longer side of the image in pixels.
        kwargs: Further options of render_svg.

    Returns:
        The PNG data if path is None, else None.
    """
    opts = {}
    if isinstance(view, Layout):
        svg = render_svg(view, size=size, **kwargs)
    else:
        svg = render_svg(view, **kwargs)
        # Schematic SVGs have their own size: scaled to size, on white.
        opts['background'] = '#ffffff'
        root = ET.fromstring(svg)
        width, height = (float(root.get(k).removesuffix('px')) for k in ('width', 'height'))
        if width >= height:
            opts['width'] = size
        else:
            opts['height'] = size
    # Only the bundled font, so that the result does not depend on the
    # system. The default dpi of resvg_py (0) turns pt sizes (schematic text)
    # into zero.
    png = bytes(resvg_py.svg_to_bytes(svg_string=svg.decode(), font_files=[font_file()],
        skip_system_fonts=True, dpi=96, **opts))
    if path is None:
        return png
    with open(path, 'wb') as f:
        f.write(png)
