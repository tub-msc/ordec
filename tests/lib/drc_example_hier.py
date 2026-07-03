# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *
from ordec.lib.ihp130 import SG13G2, run_drc


class Sub(Cell):
    """Subcell with one intentional Metal1 spacing violation.

    KLayout deep-mode DRC reports this violation once, attached to this
    cell, no matter how often the cell is instantiated.
    """
    @generate
    def layout(self) -> Layout:
        layers = SG13G2().layers
        # cell=self makes write_gds/Directory name this cell 'sub', which is
        # how parse_rdb resolves the RDB cell name back to this Layout.
        l = Layout(ref_layers=layers, cell=self)
        # Two Metal1 rects with 100nm gap (min spacing is 180nm).
        l % LayoutRect(layer=layers.Metal1, rect=Rect4I(0, 0, 1000, 1000))
        l % LayoutRect(layer=layers.Metal1, rect=Rect4I(1100, 0, 2100, 1000))
        return l


class Top(Cell):
    """Top cell instantiating Sub multiple times.

    DRC on this layout must yield exactly two violations: Sub's internal
    spacing violation (once, in Sub-local coordinates) and the
    cross-hierarchy spacing violation between the top-level rect and sub1,
    attached to the top cell.
    """
    @generate
    def layout(self) -> Layout:
        layers = SG13G2().layers
        l = Layout(ref_layers=layers, cell=self)
        l.sub1 = LayoutInstance(ref=Sub().layout, pos=(0, 0))
        l.sub2 = LayoutInstance(ref=Sub().layout, pos=(0, 5000))
        l.sub3 = LayoutInstance(ref=Sub().layout, pos=(0, 10000))
        # Top-level Metal1 rect 100nm left of sub1's first rect: a
        # cross-hierarchy violation that KLayout attaches to the top cell.
        l % LayoutRect(layer=layers.Metal1, rect=Rect4I(-1100, 0, -100, 1000))
        return l

    @generate
    def drc_report(self) -> DrcReport:
        """Run IHP130 DRC (minimal rule set) on the hierarchical layout."""
        return run_drc(self.layout, variant='minimal')
