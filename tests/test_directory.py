# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the LvsDirectory alias mechanism that maps names reported by
KLayout's netlist comparer (SPICE element prefix stripped, case-folded)
back to ORDB nodes. Only the name-collision cases are covered here; the
plain resolution path is exercised end-to-end by test_ihp130_inv.py.
"""

import pytest

from ordec.core import *
from ordec.core.schema import LvsItemType
from ordec.lib import Res
from ordec.layout.klayout import LvsDirectory


def build_schematic():
    """
    Schematic exercising the naming edge cases: the array element r1[0]
    has basename "r1_0", which collides with the net r1_0 (device/net
    shadowing), and q[0]/q_0 force a uniquification suffix.
    """
    s = Schematic()
    sym = Res(r=100).symbol
    s.a = Net()
    s.b = Net()
    s.r1_0 = Net()
    s.r1 = PathNode()
    s.r1[0] = SchemInstance(sym.portmap(p=s.a, m=s.b), pos=Vec2R(0, 0))
    s.q = PathNode()
    s.q[0] = SchemInstance(sym.portmap(p=s.a, m=s.r1_0), pos=Vec2R(5, 0))
    s.q_0 = SchemInstance(sym.portmap(p=s.b, m=s.r1_0), pos=Vec2R(10, 0))
    return s.freeze()


def test_resolve_colliding_names():
    """A Device item must resolve to the device and a Net item to the net,
    even when the device's stripped SPICE name equals the net's name; the
    old prefix-guessing heuristic resolved both to the net. Aliases are
    derived from the final unique name, so uniquification suffixes are
    part of the alias."""
    s = build_schematic()
    d = LvsDirectory()
    for net in (s.a, s.b, s.r1_0):
        d.name_node(net)
    d.name_node(s.r1[0], prefix="R")
    d.name_node(s.q[0], prefix="M")
    assert d.name_node(s.q_0, prefix="M") == "Mq_00"

    # KLayout reports both element "Rr1_0" and net "r1_0" as "R1_0".
    assert d.resolve_schem_node(s, LvsItemType.Device, "R1_0") == s.r1[0]
    assert d.resolve_schem_node(s, LvsItemType.Net, "R1_0") == s.r1_0
    assert d.resolve_schem_node(s, LvsItemType.Device, "Q_00") == s.q_0
    assert d.resolve_schem_node(s, LvsItemType.Device, "NONEXISTENT") is None


def test_alias_collision_raises():
    """Distinct prefixes can yield unique names with the same stripped
    alias ("Mq_0"/"Rq_0" -> "q_0"), which is ambiguous to KLayout's
    comparer; registration must fail loudly at netlist-writing time."""
    s = build_schematic()
    d = LvsDirectory()
    d.name_node(s.q[0], prefix="M")
    with pytest.raises(ValueError, match="ambiguous"):
        d.name_node(s.q_0, prefix="R")
