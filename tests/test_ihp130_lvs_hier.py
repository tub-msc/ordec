# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Hierarchical LVS tests in IHP130: the same resistor network with four
different hierarchy cuts (see tests/lib/lvs_example_hier.ord):

1. C_Hier: hierarchical layout vs. hierarchical schematic. KLayout compares the
   cells pairwise, so the LvsReport has one LvsCircuitPair per cell.
2. C_FlatLayout: flat layout vs. hierarchical schematic.
3. C_FlatSchematic: hierarchical layout vs. flat schematic.
4. C_Moved: hierarchical layout whose hierarchy boundaries differ from the
   schematic (one resistor moved from A_Default into B_Moved on the layout side).

In cases 2-4, KLayout's netlist alignment flattens all circuits that have no
counterpart on the other side, so the comparison reduces to a single
top-level circuit pair and LVS is expected to be clean (the netlists are
electrically equivalent). Flattened schematic objects appear under dotted
hierarchical names (e.g. device "B1.A1.R1"); these names cannot currently be
resolved to ORDB nodes, so their LvsItem.schem reference is None.
"""

import pytest
import ordec.importer
from collections import Counter

from ordec.core.schema import LvsCircuitPair, LvsItem, LvsItemType, LvsStatus
from .lib import lvs_example_hier as fx


def pairs_of(report):
    return {(p.layout_cell, p.schem_cell): p for p in report.all(LvsCircuitPair)}


def items_of(report, pair, item_type=None):
    items = [i for i in report.all(LvsItem) if i.circuit == pair]
    if item_type is not None:
        items = [i for i in items if i.item_type == item_type]
    return items


def summary_of(report, pair):
    """Counter of (item_type, status) over all items of pair."""
    return Counter((i.item_type, i.status) for i in items_of(report, pair))


def devices_of(report, pair):
    """Sorted (schem_name, layout l param) tuples of pair's device items."""
    return sorted((i.schem_name, dict(i.layout_params)['l'])
                  for i in items_of(report, pair, LvsItemType.Device))


def warnings_of(report, pair):
    return sorted((i.item_type, i.schem_name, i.message)
                  for i in items_of(report, pair)
                  if i.status == LvsStatus.MatchWarning)


@pytest.mark.parametrize("cellname", ["C_Hier", "C_FlatLayout", "C_FlatSchematic", "C_Moved"])
def test_drc_clean(cellname):
    cell = getattr(fx, cellname)()
    assert cell.drc_report.summary() == {}


def test_lvs_hier_vs_hier():
    """Case 1: full hierarchical comparison, cell by cell."""
    c = fx.C_Hier()
    report = c.lvs_report

    assert report.status == LvsStatus.Match
    assert report.clean()
    assert report.top_cell == 'c_hier'
    assert report.ref_layout == c.layout
    assert report.ref_schematic == c.schematic

    pairs = pairs_of(report)
    assert set(pairs) == {('a_default', 'A_DEFAULT'), ('b_hier', 'B_HIER'), ('c_hier', 'C_HIER')}
    for pair in pairs.values():
        assert pair.status == LvsStatus.Match

    # Subcircuit pairs resolve to the sub-cells' layouts/schematics.
    a, b = fx.A_Default(), fx.B_Hier()
    assert pairs['a_default', 'A_DEFAULT'].ref_layout == a.layout
    assert pairs['a_default', 'A_DEFAULT'].ref_schematic == a.schematic
    assert pairs['b_hier', 'B_HIER'].ref_layout == b.layout
    assert pairs['b_hier', 'B_HIER'].ref_schematic == b.schematic
    assert pairs['c_hier', 'C_HIER'].ref_layout == c.layout
    assert pairs['c_hier', 'C_HIER'].ref_schematic == c.schematic

    # Pair (a, A): the three star resistors.
    pair = pairs['a_default', 'A_DEFAULT']
    assert summary_of(report, pair) == {
        (LvsItemType.Net, LvsStatus.Match): 5,      # x, y, z, c, sub
        (LvsItemType.Pin, LvsStatus.Match): 4,      # x, y, z, sub
        (LvsItemType.Device, LvsStatus.Match): 3,   # r1, r2, r3
    }
    assert devices_of(report, pair) == [('r1', 0.5), ('r2', 1.5), ('r3', 1.0)]
    # Device items cross-reference SchemInstances of A's schematic, nets/pins
    # cross-reference its Nets.
    schem_refs = {i.schem_name: i.schem for i in items_of(report, pair, LvsItemType.Device)}
    assert schem_refs == {'r1': a.schematic.r1, 'r2': a.schematic.r2, 'r3': a.schematic.r3}
    net_refs = {i.schem_name: i.schem for i in items_of(report, pair, LvsItemType.Net)}
    assert net_refs == {'x': a.schematic.x, 'y': a.schematic.y, 'z': a.schematic.z,
        'c': a.schematic.c, 'sub': a.schematic.sub}
    # Extracted device positions are reported (in nm).
    for item in items_of(report, pair, LvsItemType.Device):
        assert item.layout_pos is not None

    # Pair (b, B): two A subcircuits chained through two Rppd.
    pair = pairs['b_hier', 'B_HIER']
    assert summary_of(report, pair) == {
        (LvsItemType.Net, LvsStatus.Match): 7,        # x, z, i1, i2, y1, y2, sub
        (LvsItemType.Pin, LvsStatus.Match): 3,        # x, z, sub
        (LvsItemType.Device, LvsStatus.Match): 2,     # rp1, rp2
        (LvsItemType.Subcircuit, LvsStatus.Match): 2, # a1, a2
    }
    assert devices_of(report, pair) == [('rp1', 0.5), ('rp2', 1.0)]
    sub_refs = {i.schem_name: i.schem for i in items_of(report, pair, LvsItemType.Subcircuit)}
    assert sub_refs == {'a1': b.schematic.a1, 'a2': b.schematic.a2}

    # Pair (c, C): two B subcircuits in parallel with one Rsil.
    pair = pairs['c_hier', 'C_HIER']
    assert summary_of(report, pair) == {
        (LvsItemType.Net, LvsStatus.Match): 3,        # x, z, sub
        (LvsItemType.Pin, LvsStatus.Match): 3,
        (LvsItemType.Device, LvsStatus.Match): 1,     # rs
        (LvsItemType.Subcircuit, LvsStatus.Match): 2, # b1, b2
    }
    assert devices_of(report, pair) == [('rs', 2.0)]
    sub_refs = {i.schem_name: i.schem for i in items_of(report, pair, LvsItemType.Subcircuit)}
    assert sub_refs == {'b1': c.schematic.b1, 'b2': c.schematic.b2}


def check_flattened_report(cell, top_name, expected_devices, warn_nets):
    """Common assertions for the flattened comparisons (cases 2-4).

    The two parallel (identical) B copies make some star-center nets
    topologically symmetric; KLayout matches them with an "ambiguous match"
    warning, which must not count as a mismatch.
    """
    report = cell.lvs_report

    assert report.status == LvsStatus.Match
    nresults = sum(1 for item in report.all(LvsItem)
        if item.status not in (LvsStatus.Match, LvsStatus.MatchWarning))
    assert nresults == 0
    assert report.top_cell == top_name

    pairs = pairs_of(report)
    assert set(pairs) == {(top_name, top_name.upper())}
    pair = pairs[top_name, top_name.upper()]
    assert pair.status == LvsStatus.Match
    assert pair.ref_layout == cell.layout
    assert pair.ref_schematic == cell.schematic

    assert summary_of(report, pair) == {
        (LvsItemType.Net, LvsStatus.Match): 13,
        (LvsItemType.Net, LvsStatus.MatchWarning): 2,
        (LvsItemType.Pin, LvsStatus.Match): 3,
        (LvsItemType.Device, LvsStatus.Match): 17,
    }
    assert devices_of(report, pair) == expected_devices
    assert sorted(i.schem_name for i in items_of(report, pair, LvsItemType.Pin)) \
        == ['sub', 'x', 'z']
    assert warnings_of(report, pair) == \
        [(LvsItemType.Net, n, 'ambiguous match') for n in warn_nets]
    return report, pair


# Device l parameters of the flattened design: per B copy, two A stars of
# (0.5u, 1.5u, 1u) plus rp1 (0.5u) and rp2 (1u); plus the parallel rs (2u).
FLAT_DEVICES_DOTTED = sorted(
    [(f'B{k}.A{j}.R{i}', l) for k in (1, 2) for j in (1, 2)
     for i, l in ((1, 0.5), (2, 1.5), (3, 1.0))]
    + [(f'B{k}.RP{i}', l) for k in (1, 2) for i, l in ((1, 0.5), (2, 1.0))]
    + [('rs', 2.0)]
)


def test_lvs_flat_layout_vs_hier_schematic():
    """Case 2: the schematic's a/b subcircuits are flattened by alignment."""
    cell = fx.C_FlatLayout()
    report, pair = check_flattened_report(cell, 'c_flatlayout',
        FLAT_DEVICES_DOTTED, ['B1.A1.C', 'B2.A1.C'])
    # Dotted names of flattened-away hierarchy cannot be cross-referenced;
    # the top-level device rs can.
    schem_refs = {i.schem_name: i.schem for i in items_of(report, pair, LvsItemType.Device)}
    assert schem_refs['rs'] == cell.schematic.rs
    assert all(ref is None for name, ref in schem_refs.items() if name != 'rs')


def test_lvs_hier_layout_vs_flat_schematic():
    """Case 3: the layout's a/b cells are flattened by alignment."""
    cell = fx.C_FlatSchematic()
    expected_devices = sorted(
        [(f'{inst}_{k}', l) for k in (0, 1) for inst, l in (
            ('a1r1', 0.5), ('a1r2', 1.5), ('a1r3', 1.0),
            ('a2r1', 0.5), ('a2r2', 1.5), ('a2r3', 1.0),
            ('rp1', 0.5), ('rp2', 1.0))]
        + [('rs', 2.0)]
    )
    report, pair = check_flattened_report(cell, 'c_flatschematic',
        expected_devices, ['c1_0', 'c1_1'])
    # The schematic is the top-level one here, so all devices cross-reference.
    s = cell.schematic
    schem_refs = {i.schem_name: i.schem for i in items_of(report, pair, LvsItemType.Device)}
    assert schem_refs['rs'] == s.rs
    for inst in ('a1r1', 'a1r2', 'a1r3', 'a2r1', 'a2r2', 'a2r3', 'rp1', 'rp2'):
        for k in (0, 1):
            assert schem_refs[f'{inst}_{k}'] == getattr(s, inst)[k]


def test_lvs_hier_vs_hier_moved():
    """Case 4: hierarchy boundaries differ between layout (a_moved/b_moved) and
    schematic (a_default/b_hier); alignment flattens both sides and the electrically
    equivalent netlists match."""
    cell = fx.C_Moved()
    check_flattened_report(cell, 'c_moved',
        FLAT_DEVICES_DOTTED, ['B1.A1.C', 'B2.A1.C'])
