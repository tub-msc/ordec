# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import numpy as np
from public import public
from ..core import *
from .helpers import path_to_poly_vertices, check_ref_layers, _interior_point

INT32_MIN = -2**31
INT32_MAX = 2**31 - 1

def int32(values) -> np.ndarray:
    a = np.asarray(values, dtype=np.int64)
    if a.size and (a.min() < INT32_MIN or a.max() > INT32_MAX):
        raise ValueError("Layout coordinates exceed the int32 range of the web viewer.")
    return a.astype(np.int32)

def td4_matrix(t: TD4I) -> tuple[int]:
    """(a, b, c, d, tx, ty) with x' = a*x + b*y + tx, y' = c*x + d*y + ty."""
    o = t * Vec2I(0, 0)
    ex = t * Vec2I(1, 0) - o
    ey = t * Vec2I(0, 1) - o
    return (ex.x, ey.x, ex.y, ey.y, o.x, o.y)

def transform_extent(m, extent):
    """Bounding box of an extent (lx, ly, ux, uy) under matrix m."""
    a, b, c, d, tx, ty = m
    lx, ly, ux, uy = extent
    xs = [a*x + b*y + tx for x in (lx, ux) for y in (ly, uy)]
    ys = [c*x + d*y + ty for x in (lx, ux) for y in (ly, uy)]
    return (min(xs), min(ys), max(xs), max(ys))

def union_extent(e1, e2):
    if e1 is None:
        return e2
    if e2 is None:
        return e1
    return (min(e1[0], e2[0]), min(e1[1], e2[1]), max(e1[2], e2[2]), max(e1[3], e2[3]))

class WebdataBuilder:
    def __init__(self, top: Layout):
        self.ref_layers = top.ref_layers
        self.directory = Directory()
        self.cells = [] # cell dicts, index = cell id
        self.cell_ids = {} # id(subgraph) -> cell id
        self.extents = [] # per cell id, whole hierarchy below
        self.layers = {} # Layer nid -> weblayer dict
        self.add_cell(top)

    def weblayer(self, nid):
        if nid not in self.layers:
            layer = self.ref_layers.subgraph.cursor_at(nid)
            try:
                path = layer.full_path_str()
            except TypeError:
                # Pin layers are usually inserted anonymously; label them
                # after the layer they belong to.
                parent = layer.root.one(Layer.pin_idx.query(layer))
                path = parent.full_path_str() + ".pin"
            self.layers[nid] = {
                'nid': nid,
                'path': path,
                'styleFill': layer.style_fill,
                'styleStroke': layer.style_stroke,
                'styleCrossRect': layer.style_crossrect,
                'styleCSS': layer.inline_css(),
            }
        return nid

    def add_cell(self, layout: Layout) -> int:
        key = id(layout.subgraph)
        if key in self.cell_ids:
            return self.cell_ids[key]
        cell_id = len(self.cells)
        self.cell_ids[key] = cell_id
        cell = {}
        self.cells.append(cell)
        self.extents.append(None)

        polys = {} # layer nid -> list of vertex lists
        labels = {} # layer nid -> list of labels
        def add_poly(layer_nid, vertices):
            polys.setdefault(self.weblayer(layer_nid), []).append(vertices)
        def add_label(layer_nid, pos, text):
            labels.setdefault(self.weblayer(layer_nid), []).append({
                'pos': [pos.x, pos.y], 'text': text})

        for poly in layout.all(LayoutPoly):
            add_poly(poly.layer.nid, poly.vertices())
        for path in layout.all(LayoutPath):
            add_poly(path.layer.nid, path_to_poly_vertices(path))
        for pin in layout.all(LayoutPin):
            ref = pin.ref
            if isinstance(ref, LayoutPoly):
                vertices = ref.vertices()
            elif isinstance(ref, LayoutPath):
                vertices = path_to_poly_vertices(ref)
            elif isinstance(ref, LayoutRect):
                r = ref.rect
                vertices = [Vec2I(r.lx, r.ly), Vec2I(r.ux, r.ly), Vec2I(r.ux, r.uy), Vec2I(r.lx, r.uy)]
            else:
                raise TypeError(f"Unsupported LayoutPin ref type {type(ref).__name__}.")
            pinlayer = ref.layer.pinlayer().nid
            add_poly(pinlayer, vertices)
            add_label(pinlayer, _interior_point(vertices), self.directory.name_node(pin.pin))
        for label in layout.all(LayoutLabel):
            add_label(label.layer.nid, label.pos, label.text)

        rects = layout.arrays(LayoutRect)
        rect_layers = rects['layer']
        for nid in np.unique(rect_layers).tolist():
            self.weblayer(nid)

        extent = None
        cell['layers'] = []
        for nid in sorted(set(rect_layers.tolist()) | polys.keys() | labels.keys()):
            entry = {'layer': nid}
            r = rects['rect'][rect_layers == nid]
            entry['rects'] = int32(r.reshape(-1))
            if len(r):
                extent = union_extent(extent, (int(r[:, 0].min()), int(r[:, 1].min()),
                    int(r[:, 2].max()), int(r[:, 3].max())))
            pl = polys.get(nid, [])
            coords = [c for vertices in pl for v in vertices for c in (v.x, v.y)]
            entry['polyOffsets'] = int32(np.cumsum([0] + [len(v) for v in pl]))
            entry['polyCoords'] = int32(coords)
            if coords:
                xs, ys = coords[0::2], coords[1::2]
                extent = union_extent(extent, (min(xs), min(ys), max(xs), max(ys)))
            entry['labels'] = labels.get(nid, [])
            for label in entry['labels']:
                x, y = label['pos']
                extent = union_extent(extent, (x, y, x, y))
            cell['layers'].append(entry)

        inst_cells = []
        inst_matrices = []
        for inst in layout.all(LayoutInstance):
            check_ref_layers(layout, inst)
            child = self.add_cell(inst.ref)
            m = td4_matrix(inst.loc_transform())
            inst_cells.append(child)
            inst_matrices.append(m)
            if self.extents[child] is not None:
                extent = union_extent(extent, transform_extent(m, self.extents[child]))
        for inst in layout.all(LayoutInstanceArray):
            check_ref_layers(layout, inst)
            child = self.add_cell(inst.ref)
            a, b, c, d, tx, ty = td4_matrix(inst.loc_transform())
            for col in range(inst.cols):
                for row in range(inst.rows):
                    off = col*inst.vec_col + row*inst.vec_row
                    m = (a, b, c, d, tx + off.x, ty + off.y)
                    inst_cells.append(child)
                    inst_matrices.append(m)
                    if self.extents[child] is not None:
                        extent = union_extent(extent, transform_extent(m, self.extents[child]))
        cell['instances'] = {
            'cell': int32(inst_cells),
            'transform': int32(np.array(inst_matrices, dtype=np.int64).reshape(-1)),
        }
        self.extents[cell_id] = extent
        return cell_id

@public
def webdata(layout: Layout.Frozen):
    """
    Web viewer data (web/src/view/layout.js) of a layout, keeping its
    hierarchy: every distinct layout (the given one and all instantiated
    ones) is one cell, sent once, with per-layer int32 arrays; instances
    refer to cells by index. See docs/dev/webui.rst for the format.
    """
    b = WebdataBuilder(layout)
    extent = b.extents[0]
    return 'layout', {
        'layers': [b.layers[nid] for nid in sorted(b.layers)],
        'cells': b.cells,
        'extent': None if extent is None else tuple(extent),
        'unit': float(layout.ref_layers.unit),
    }
