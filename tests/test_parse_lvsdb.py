# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests parse_lvsdb against a fixed LVSDB specimen (tests/lvsdb/c_hier.lvsdb),
pinning down the parser's behavior independently of KLayout and of any PDK.
See the parse_lvsdb docstring for an annotated description of the format.

The specimen was generated from the hierarchical LVS example
(tests/lib/lvs_example_hier.ord) via:

    import ordec.importer
    from ordec.lib.ihp130 import run_lvs
    from tests.lib import lvs_example_hier as ex
    c = ex.C_Hier()
    run_lvs(c.layout, c.symbol, use_tempdir=False)  # writes lvs/out.lvsdb

As no Directory is passed to parse_lvsdb here, names are not resolved back
to ORDB nodes/subgraphs; the resolved path is covered by
tests/test_ihp130_lvs_hier.py (which requires KLayout and the IHP PDK).
"""

from collections import Counter
from pathlib import Path

from ordec.core.schema import LvsCircuitPair, LvsItem, LvsItemType, LvsStatus
from ordec.layout.klayout import parse_lvsdb

LVSDB_FILE = Path(__file__).parent / 'lvsdb' / 'c_hier.lvsdb'


def items_of(report, circuit):
    return list(report.all(LvsItem.circuit_idx.query(circuit)))


def test_parse_lvsdb_fixture():
    report = parse_lvsdb(LVSDB_FILE, None, None)

    assert report.top_cell == 'c_hier'
    assert report.clean()

    pairs = list(report.all(LvsCircuitPair))
    # LVSDB lists circuit pairs bottom-up (callees before callers).
    assert [(p.layout_cell, p.schem_cell) for p in pairs] == [
        ('a_default', 'A_DEFAULT'),
        ('b_hier', 'B_HIER'),
        ('c_hier', 'C_HIER'),
    ]
    for pair in pairs:
        assert pair.status == LvsStatus.Match
        assert pair.message is None
        # Without a Directory, no subgraph references are resolved.
        assert pair.ref_layout is None
        assert pair.ref_schematic is None

    pair_a, pair_b, pair_c = pairs

    def item_summary(pair):
        return Counter((i.item_type, i.status) for i in items_of(report, pair))

    assert item_summary(pair_a) == {
        (LvsItemType.Net, LvsStatus.Match): 5,
        (LvsItemType.Pin, LvsStatus.Match): 4,
        (LvsItemType.Device, LvsStatus.Match): 3,
    }
    assert item_summary(pair_b) == {
        (LvsItemType.Net, LvsStatus.Match): 7,
        (LvsItemType.Pin, LvsStatus.Match): 3,
        (LvsItemType.Device, LvsStatus.Match): 2,
        (LvsItemType.Subcircuit, LvsStatus.Match): 2,
    }
    assert item_summary(pair_c) == {
        (LvsItemType.Net, LvsStatus.Match): 3,
        (LvsItemType.Pin, LvsStatus.Match): 3,
        (LvsItemType.Device, LvsStatus.Match): 1,
        (LvsItemType.Subcircuit, LvsStatus.Match): 2,
    }


def test_parse_lvsdb_device_details():
    report = parse_lvsdb(LVSDB_FILE, None, None)
    pair_a = next(p for p in report.all(LvsCircuitPair)
                  if p.layout_cell == 'a_default')

    devices = {i.schem_name: i for i in items_of(report, pair_a)
               if i.item_type == LvsItemType.Device}
    assert set(devices) == {'R1', 'R2', 'R3'}

    # Device parameters ('E' entries) from both netlist sections; layout and
    # reference agree here since the design is LVS-clean.
    assert dict(devices['R1'].layout_params)['l'] == 0.5
    assert dict(devices['R2'].layout_params)['l'] == 1.5
    assert dict(devices['R3'].layout_params)['l'] == 1.0
    for dev in devices.values():
        assert dev.layout_params == dev.schem_params
        # Layout devices are unnamed in the LVSDB (GDS structure references
        # carry no instance names); they are identified by location only.
        assert dev.layout_name == ''
        assert dev.layout_pos is not None
        # Without a Directory, schematic nodes are not resolved.
        assert dev.schem is None

    assert tuple(devices['R1'].layout_pos) == (-5, 2995)
    assert tuple(devices['R2'].layout_pos) == (2325, 1805)
    assert tuple(devices['R3'].layout_pos) == (-5, 105)


def test_parse_lvsdb_names():
    report = parse_lvsdb(LVSDB_FILE, None, None)
    pairs = list(report.all(LvsCircuitPair))
    pair_a, pair_b, pair_c = pairs

    def names(pair, item_type):
        return {(i.layout_name, i.schem_name) for i in items_of(report, pair)
                if i.item_type == item_type}

    # Reference names are upper-cased SPICE names. Layout nets/pins are only
    # named where the layout has labels: the ports x/y/z everywhere, sub only
    # in the top cell (where the substrate is materialized with a tap + pin).
    assert names(pair_a, LvsItemType.Pin) == {
        ('x', 'X'), ('y', 'Y'), ('z', 'Z'), ('', 'SUB')}
    assert names(pair_c, LvsItemType.Pin) == {
        ('x', 'X'), ('z', 'Z'), ('sub', 'SUB')}

    # Subcircuit instances are named on the reference side only.
    assert names(pair_b, LvsItemType.Subcircuit) == {('', 'A1'), ('', 'A2')}
    assert names(pair_c, LvsItemType.Subcircuit) == {('', 'B1'), ('', 'B2')}
