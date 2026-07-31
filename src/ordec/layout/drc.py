# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..core.schema import (
    DrcReport, DrcItem, DrcCategory, DrcCell, DrcBox, DrcEdge, DrcEdgePair,
    DrcPoly, DrcPath, DrcText,
)


def webdata(report: DrcReport):
    cells = []
    for cell in report.all(DrcCell):
        cells.append({
            'nid': cell.nid,
            'name': cell.name,
            'has_layout_ref': cell.ref_layout is not None,
            'is_top': cell.ref_layout is not None
                and cell.ref_layout == report.ref_layout,
        })

    items_dict = {}
    categories_with_items = set()
    for item in report.all(DrcItem):
        items_dict[item.nid] = {
            'nid': item.nid,
            'category_nid': item.category.nid,
            'cell_nid': item.cell.nid if item.cell is not None else None,
            'shapes': [],
        }
        categories_with_items.add(item.category.nid)

    categories = []
    for cat in report.all(DrcCategory):
        if cat.nid in categories_with_items:
            categories.append({
                'nid': cat.nid,
                'name': cat.name,
                'description': cat.description,
                'parent_nid': cat.parent.nid if cat.parent else None,
            })

    for box in report.all(DrcBox):
        items_dict[box.item.nid]['shapes'].append({
            'type': 'box',
            'rect': [box.rect.lx, box.rect.ly, box.rect.ux, box.rect.uy]
        })

    for edge in report.all(DrcEdge):
        items_dict[edge.item.nid]['shapes'].append({
            'type': 'edge',
            'p1': [edge.p1.x, edge.p1.y],
            'p2': [edge.p2.x, edge.p2.y]
        })

    for ep in report.all(DrcEdgePair):
        items_dict[ep.item.nid]['shapes'].append({
            'type': 'edge_pair',
            'e1': [[ep.edge1_p1.x, ep.edge1_p1.y], [ep.edge1_p2.x, ep.edge1_p2.y]],
            'e2': [[ep.edge2_p1.x, ep.edge2_p1.y], [ep.edge2_p2.x, ep.edge2_p2.y]],
        })

    for poly in report.all(DrcPoly):
        verts = [[v.x, v.y] for v in poly.vertices()]
        items_dict[poly.item.nid]['shapes'].append({
            'type': 'poly', 'vertices': verts
        })

    for path in report.all(DrcPath):
        verts = [[v.x, v.y] for v in path.vertices()]
        items_dict[path.item.nid]['shapes'].append({
            'type': 'path', 'vertices': verts, 'width': path.width
        })

    for text in report.all(DrcText):
        items_dict[text.item.nid]['shapes'].append({
            'type': 'text', 'pos': [text.pos.x, text.pos.y], 'text': text.text
        })

    return 'drc_report', {
        'top_cell': report.top_cell_name,
        'categories': categories,
        'cells': cells,
        'items': list(items_dict.values()),
        'unit': float(report.ref_layout.ref_layers.unit),
    }
