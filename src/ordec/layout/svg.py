# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
SVG rendering of layouts (see ordec.render for PNG output).

The SVG is made from the web viewer data (webdata), so that it shows what
the viewer shows: the same hierarchy, LayoutStyle and label rules. The
hierarchy is kept, with one group per cell and layer and the instances as
<use>. Outlines, fill patterns and labels are sized in output pixels, as in
the viewer.

The blend modes of the LayoutStyle map to SVG blend modes, one blended group
per layer: additive to screen, ink to multiply, max to lighten (on a
transparent backdrop, then over the background), over to normal with the
group opacity. Layer colors are adjusted so that additive and ink match the
viewer at its default intensity. The mix blend mode has no SVG counterpart
and is not supported.
"""

import math
from xml.sax.saxutils import escape
from public import public
from ..core import *
from .webdata import webdata

FONT_SIZE = 14 # label font size in pixels
LINE_HEIGHT = 1.1 * FONT_SIZE

# Viewer gains at the default intensity (see drawGLShapes in
# web/src/view/layout.js).
GAIN_ADDITIVE = math.exp(-20/15)
GAIN_INK = 0.25

BLEND_CSS = {'additive': 'screen', 'ink': 'multiply', 'max': 'lighten', 'over': 'normal'}

def hexcolor(rgb) -> str:
    return '#' + ''.join(f'{round(min(max(v, 0), 1) * 255):02x}' for v in rgb)

def layer_color(color: RGBColor, blend: str) -> str:
    """
    Color of a layer in the SVG. Additive light and ink sum optical
    densities per pixel in the viewer (see layout-shapes.frag); per layer,
    this is the screen or multiply blending of the colors computed here.
    """
    c = [color.r / 255, color.g / 255, color.b / 255]
    if blend == 'additive':
        c = [1 - (1 - 0.95*v)**GAIN_ADDITIVE for v in c]
    elif blend == 'ink':
        c = [(1 - 0.95*(1 - v))**GAIN_INK for v in c]
    return hexcolor(c)

def is_light(color: RGBColor) -> bool:
    """Same test as isLightBackground in web/src/view/layout-style.js."""
    return 0.3*color.r + 0.6*color.g + 0.1*color.b > 0.5 * 255

def fill_path(entry) -> str:
    """Path data of the rects and polygons of a webdata cell layer entry."""
    # All subpaths run counterclockwise, so that with the nonzero fill rule
    # overlapping shapes add up to their union.
    parts = [f'M{lx} {ly}H{ux}V{uy}H{lx}Z' for lx, ly, ux, uy in entry['rects'].reshape(-1, 4).tolist()]
    offs = entry['polyOffsets'].tolist()
    coords = entry['polyCoords'].reshape(-1, 2).tolist()
    for p in range(len(offs) - 1):
        vs = coords[offs[p]:offs[p+1]]
        area2 = sum(x0*y1 - x1*y0 for (x0, y0), (x1, y1) in zip(vs, vs[1:] + vs[:1]))
        if area2 < 0:
            vs.reverse()
        parts.append('M' + 'L'.join(f'{x} {y}' for x, y in vs) + 'Z')
    return ''.join(parts)

def cross_path(entry) -> str:
    """Path data of the diagonals of the rects and four-vertex polygons."""
    parts = [f'M{lx} {ly}L{ux} {uy}M{ux} {ly}L{lx} {uy}' for lx, ly, ux, uy in entry['rects'].reshape(-1, 4).tolist()]
    offs = entry['polyOffsets'].tolist()
    coords = entry['polyCoords'].reshape(-1, 2).tolist()
    for p in range(len(offs) - 1):
        if offs[p+1] - offs[p] == 4:
            (x0, y0), (x1, y1), (x2, y2), (x3, y3) = coords[offs[p]:offs[p+1]]
            parts.append(f'M{x0} {y0}L{x2} {y2}M{x1} {y1}L{x3} {y3}')
    return ''.join(parts)

def svg_matrix(m) -> str:
    """SVG transform of a webdata transform (a, b, c, d, tx, ty)."""
    a, b, c, d, tx, ty = m
    return f'matrix({a} {c} {b} {d} {tx} {ty})'

def compose(m1, m2):
    """m1 applied after m2 (as composeTransforms in web/src/view/layout.js)."""
    return (
        m1[0]*m2[0] + m1[1]*m2[2], m1[0]*m2[1] + m1[1]*m2[3],
        m1[2]*m2[0] + m1[3]*m2[2], m1[2]*m2[1] + m1[3]*m2[3],
        m1[0]*m2[4] + m1[1]*m2[5] + m1[4], m1[2]*m2[4] + m1[3]*m2[5] + m1[5],
    )

@public
def layout_svg(layout: Layout.Frozen, *, region: Rect4I | None = None, size: int = 1600,
        labels: bool = True, subcell_pins: bool = False) -> bytes:
    """
    Renders a layout with its LayoutStyle to SVG.

    Args:
        layout: The layout.
        region: Area to render, in layout coordinates. Defaults to the
            extent of the layout plus a small margin.
        size: Size of the longer side of the image in pixels.
        labels: Whether labels are drawn.
        subcell_pins: Whether the shapes and labels on pin layers (pins) of
            instantiated cells are drawn, not only those of the layout
            itself.

    Returns:
        The SVG document.
    """
    _, data = webdata(layout)
    style = data['style']
    blend = 'additive' if style is None else style['blend']
    background = RGBColor(0, 0, 0) if style is None else style['background']
    if blend not in BLEND_CSS:
        raise ValueError(f"Blend mode {blend!r} is not supported in SVG rendering.")
    light = is_light(background)

    if region is None:
        if data['extent'] is None:
            raise ValueError("The layout is empty and no region is given.")
        lx, ly, ux, uy = data['extent']
        pad = max(ux - lx, uy - ly, 1) * 0.02
        lx, ly, ux, uy = lx - pad, ly - pad, ux + pad, uy + pad
    else:
        lx, ly, ux, uy = region.lx, region.ly, region.ux, region.uy
    scale = size / max(ux - lx, uy - ly, 1) # pixels per layout unit
    width = max(1, round((ux - lx) * scale))
    height = max(1, round((uy - ly) * scale))
    # Layout coordinates to pixels, y pointing down:
    root = svg_matrix((scale, 0, 0, -scale, -lx*scale, uy*scale))

    cells = data['cells']
    entries = [{e['layer']: e for e in cell['layers']} for cell in cells]
    # Layers drawn for the layout itself only (see subcell_pins).
    top_only = set() if subcell_pins else {l['nid'] for l in data['layers'] if l['pin']}
    defs = []

    # One group per cell and layer, holding the cell's own shapes of the
    # layer and <use> of the groups of its instances.
    groups = {}
    def group(path_fn, cell, nid):
        key = (path_fn, cell, nid)
        if key not in groups:
            entry = entries[cell].get(nid)
            d = path_fn(entry) if entry else ''
            content = [f'<path d="{d}"/>'] if d else []
            inst = cells[cell]['instances']
            transforms = inst['transform'].reshape(-1, 6).tolist()
            for child, m in zip(inst['cell'].tolist(), transforms):
                child_id = None if nid in top_only else group(path_fn, child, nid)
                if child_id:
                    content.append(f'<use href="#{child_id}" transform="{svg_matrix(m)}"/>')
            gid = None
            if content:
                gid = f'{path_fn.__name__[0]}{cell}-{nid}'
                defs.append(f'<g id="{gid}">{"".join(content)}</g>')
            groups[key] = gid
        return groups[key]

    # By index: pattern names are not necessarily valid as SVG ids.
    patterns = {p['name']: (i, p['rows']) for i, p in enumerate(style['patterns'])} if style else {}
    pattern_ids = set()
    def pattern(name, color):
        index, rows = patterns[name]
        pid = f'p{index}-{color[1:]}'
        if pid not in pattern_ids:
            d = ''.join(f'M{x} {y}h1v1h-1Z' for y, row in enumerate(rows)
                for x in range(16) if row >> (15 - x) & 1)
            defs.append(f'<pattern id="{pid}" width="16" height="16" patternUnits="userSpaceOnUse">'
                f'<path d="{d}" fill="{color}"/></pattern>')
            pattern_ids.add(pid)
        return pid

    # Drawing order as layerOrder in web/src/view/layout-style.js: the
    # LayoutStyle order, then the unstyled layers in plain white (black on
    # light backgrounds).
    layers = sorted(data['layers'], key=lambda l: (l['order'] is None, l['order'] or 0, l['nid']))
    body = []
    for layer in layers:
        nid = layer['nid']
        unstyled = layer['order'] is None
        fill = (RGBColor(0, 0, 0) if light else RGBColor(255, 255, 255)) if unstyled else layer['styleFill']
        stroke = None if unstyled else layer['styleStroke']
        gid = group(fill_path, 0, nid)
        if gid is None:
            continue
        content = []
        if fill is not None:
            color = layer_color(fill, blend)
            if layer['pattern'] is None:
                content.append(f'<use href="#{gid}" transform="{root}" fill="{color}"/>')
            else:
                # Patterns are fixed to the image, not to the shapes (as in
                # the viewer), so the shapes are a mask for a patterned area.
                defs.append(f'<mask id="m{nid}" maskUnits="userSpaceOnUse" x="0" y="0" '
                    f'width="{width}" height="{height}">'
                    f'<use href="#{gid}" transform="{root}" fill="#fff"/></mask>')
                content.append(f'<rect width="{width}" height="{height}" '
                    f'fill="url(#{pattern(layer["pattern"], color)})" mask="url(#m{nid})"/>')
        if stroke is not None:
            stroke_attrs = f'fill="none" stroke="{layer_color(stroke, blend)}" stroke-width="{1/scale}"'
            content.append(f'<use href="#{gid}" transform="{root}" {stroke_attrs}/>')
            cid = group(cross_path, 0, nid) if layer['styleCrossRect'] else None
            if cid:
                content.append(f'<use href="#{cid}" transform="{root}" {stroke_attrs}/>')
        opacity = f' opacity="{style["opacity"]}"' if blend == 'over' else ''
        body.append(f'<g style="mix-blend-mode:{BLEND_CSS[blend]}"{opacity}>{"".join(content)}</g>')
    if blend == 'max':
        # Lighten among the layers only, then over the background.
        body = ['<g style="isolation:isolate">'] + body + ['</g>']

    if labels:
        text_color = '#000' if light else '#fff'
        body.append(f'<g font-family="Inconsolata" font-size="{FONT_SIZE}" text-anchor="middle" '
            f'fill="{text_color}" stroke="{hexcolor([v / 255 for v in background])}" '
            'stroke-width="3" stroke-linejoin="round" paint-order="stroke">')
        def walk(cell, m):
            for entry in cells[cell]['layers']:
                if cell != 0 and entry['layer'] in top_only:
                    continue
                for label in entry['labels']:
                    x, y = label['pos']
                    px = (m[0]*x + m[1]*y + m[4] - lx) * scale
                    py = (uy - (m[2]*x + m[3]*y + m[5])) * scale
                    if not (0 <= px <= width and 0 <= py <= height):
                        continue
                    lines = label['text'].split('\n')
                    for j, line in enumerate(lines):
                        # Lines centered on the label position, 0.35em is
                        # about half the height of capitals above the
                        # baseline.
                        ty = py + (j - (len(lines) - 1) / 2) * LINE_HEIGHT + 0.35 * FONT_SIZE
                        body.append(f'<text x="{px:.1f}" y="{ty:.1f}">{escape(line)}</text>')
            inst = cells[cell]['instances']
            for child, t in zip(inst['cell'].tolist(), inst['transform'].reshape(-1, 6).tolist()):
                walk(child, compose(m, t))
        walk(0, (1, 0, 0, 1, 0, 0))
        body.append('</g>')

    return ''.join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<defs>', *defs, '</defs>',
        f'<rect width="{width}" height="{height}" fill="{hexcolor([v / 255 for v in background])}"/>',
        *body,
        '</svg>',
    ]).encode()
