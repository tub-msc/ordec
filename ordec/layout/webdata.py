# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *

def layout_webdata(layout: Layout.Frozen):
    weblayers_list = []
    weblayers_dict = {}

    def get_weblayer(layer):
        try:
            weblayer = weblayers_dict[layer]
        except KeyError:
            weblayer = {
                'nid': layer.nid,
                'path': layer.full_path_str(),
                'styleFill': layer.style_fill,
                'styleStroke': layer.style_stroke,
                'styleCrossRect': layer.style_crossrect,
                'styleCSS': layer.inline_css(),
                'polys': [],
                'labels': [],
            }
            weblayers_list.append(weblayer)
            weblayers_dict[layer] = weblayer
        return weblayer

    extent = None
    def extent_add_vertex(vertex: Vec2I):
        nonlocal extent
        if extent == None:
            extent = Rect4I(vertex.x, vertex.y, vertex.x, vertex.y)
        else:
            extent = extent.extend(vertex)

    for poly in layout.all(LayoutPoly):
        # Flat list of coordinates x0, y0, x1, y1 and so on. This is what
        # the JS earcut library wants.
        vertices_flat = [v.pos[xy] for v in poly.vertices for xy in (0,1)]
        for v in poly.vertices:
            extent_add_vertex(v.pos)

        weblayer = get_weblayer(poly.layer)

        weblayer['polys'].append({
            'nid': poly.nid,
            'vertices': vertices_flat,
        })

    for label in layout.all(Label):
        extent_add_vertex(label.pos)

        weblayer = get_weblayer(label.layer)
        weblayer['labels'].append({
            'nid': label.nid,
            'pos': label.pos,
            'text': label.text,
        })

    if extent == None:
        extent = Rect4I(0, 0, 0, 0)

    weblayers_list.sort(key=lambda l: l['nid'])

    return 'layout_gl', {
        'layers': weblayers_list,
        'extent': [extent.lx, extent.ly, extent.ux, extent.uy],
        'unit': float(layout.ref_layers.unit),
    }
