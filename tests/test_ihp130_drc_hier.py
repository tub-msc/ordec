# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Hierarchical DRC in IHP130 (see tests/lib/drc_example_hier.py): KLayout
deep-mode DRC reports a violation inside a subcell once, attached to that
cell, with coordinates in the cell's local space — not once per instance
at the top cell. Cross-hierarchy violations attach to the top cell.
"""

from ordec.core.schema import DrcCell, DrcItem, DrcEdgePair
from .lib.drc_example_hier import Sub, Top


def test_drc_hier():
    top = Top()
    report = top.drc_report

    # Sub's internal violation appears once (not 3x for 3 instances), plus
    # the cross-hierarchy violation at top: 2 items in the M1 spacing
    # category.
    assert report.summary() == {'M1.b': 2}

    cells = {c.name: c for c in report.all(DrcCell)}
    assert set(cells) == {'top', 'sub'}
    assert cells['top'].ref_layout == report.ref_layout == top.layout
    assert cells['sub'].ref_layout == Sub().layout

    items_by_cell = {}
    for item in report.all(DrcItem):
        items_by_cell.setdefault(item.cell.name, []).append(item)
    assert len(items_by_cell['sub']) == 1
    assert len(items_by_cell['top']) == 1

    # Sub's violation shapes are in Sub-local coordinates (the gap between
    # x=1000 and x=1100), not at any instance position of the top layout.
    (ep,) = report.all(DrcEdgePair.item_idx.query(items_by_cell['sub'][0]))
    assert {ep.edge1_p1.x, ep.edge1_p2.x, ep.edge2_p1.x, ep.edge2_p2.x} \
        == {1000, 1100}

    # The top item is the cross-hierarchy violation (gap between the
    # top-level rect at x=-100 and sub1's rect at x=0).
    (ep,) = report.all(DrcEdgePair.item_idx.query(items_by_cell['top'][0]))
    assert {ep.edge1_p1.x, ep.edge1_p2.x, ep.edge2_p1.x, ep.edge2_p2.x} \
        == {-100, 0}
