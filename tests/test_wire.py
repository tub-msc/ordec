# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.core import *
from ordec.core import ordb
from ordec.core.ordb.base import FarRef, LiveRef, wire_registry
from ordec.core.schema.base import SourceLocInfo
from ordec.core.wire import (
    WireError, export_table, subgraph_from_wire, subgraph_to_wire, wire_deps,
    wire_hash,
)

@pytest.fixture(autouse=True, params=ordb.available_backends())
def ordb_backend(request):
    """Wire bytes and hashes must be identical across storage backends."""
    with ordb.use_backend(request.param):
        yield request.param

# Custom test schema (wire_id domain 15<<16 is reserved for tests):
WIRE_DOMAIN = 15 << 16

class WSub(SubgraphRoot):
    wire_id = WIRE_DOMAIN | 1
    label = Attr(str)

class WHead(SubgraphRoot):
    wire_id = WIRE_DOMAIN | 2
    sub = SubgraphRef(WSub)
    obj = LiveRef(object)
    blob = Attr(object)

class WItem(Node):
    in_subgraphs = [WHead]
    wire_id = WIRE_DOMAIN | 3
    ref = LocalRef('WItem', refcheck_custom=lambda val: issubclass(val, WItem))
    label = Attr(str|int, typecheck_custom=lambda v: isinstance(v, (str, int)))
    pos = Attr(Vec2R)
    rect = Attr(Rect4R)
    d4 = Attr(D4)
    r = Attr(R)
    f = Attr(float)
    b = Attr(bool)
    raw = Attr(bytes)
    tup = Attr(tuple)
    loc = Attr(SourceLocInfo)

class WNoWire(Node):
    in_subgraphs = [WHead]
    label = Attr(str)

# One shared live object so repeated builds export the same reference:
live_obj = object()

def build_sub(label='sub'):
    return WSub(label=label).freeze()

def build_head(sub=None, loc_line=1):
    h = WHead(sub=sub or build_sub(), obj=live_obj)
    h.first = WItem(label='first', pos=Vec2R(1, 2),
        rect=Rect4R(0, 0, 3, 4), d4=D4.MY90, r=R('1k'), f=1.5, b=True,
        raw=b'\x00\xff', tup=('a', 1, R(1, 3), Vec2R(5, 6)),
        loc=SourceLocInfo('x.ord', loc_line, 0))
    h.second = WItem(label=7, ref=h.first)
    return h.freeze()

def test_determinism():
    a, b = build_head(), build_head()
    assert subgraph_to_wire(a) == subgraph_to_wire(b)
    assert wire_hash(a) == wire_hash(b)

def test_cross_backend_hash():
    h = wire_hash(build_head())
    with ordb.use_backend(ordb.available_backends()[0]):
        assert wire_hash(build_head()) == h

def test_hash_sensitivity():
    # SourceLocInfo data (src_loc) participates in the hash:
    assert wire_hash(build_head(loc_line=2)) != wire_hash(build_head())

def test_nid_alloc_sensitivity():
    # nid_alloc.start participates: adding and removing a node leaves the
    # same nodes but different allocation state than never adding it.
    def head_with_first():
        h = WHead(obj=live_obj)
        h.first = WItem(label='first')
        return h
    plain = head_with_first().freeze()
    scarred = head_with_first()
    temp = scarred % WItem(label='temp')
    temp.remove()
    scarred = scarred.freeze()
    assert dict(scarred.subgraph.nodes) == dict(plain.subgraph.nodes)
    assert wire_hash(scarred) != wire_hash(plain)

def test_roundtrip():
    orig = build_head()
    back = subgraph_from_wire(subgraph_to_wire(orig), wire_deps(orig))
    assert back.subgraph == orig.subgraph
    assert wire_hash(back) == wire_hash(orig)
    # NPath navigation and value types survive:
    assert back.first.pos == Vec2R(1, 2)
    assert back.first.tup == ('a', 1, R(1, 3), Vec2R(5, 6))
    assert back.second.ref == back.first
    # The live object comes back as the identical object:
    assert back.obj is live_obj

def test_merkle():
    sub = build_sub()
    h1 = wire_hash(build_head(sub=sub))
    assert wire_hash(build_head(sub=sub)) == h1
    # Changed dependency content propagates into the parent hash:
    assert wire_hash(build_head(sub=build_sub(label='other'))) != h1

def test_roundtrip_real_schematic():
    from ordec.examples.voltagedivider_py import VoltageDivider
    cell = VoltageDivider()
    sch = cell.schematic
    deps = wire_deps(sch)
    back = subgraph_from_wire(subgraph_to_wire(sch), deps)
    assert back.subgraph == sch.subgraph
    assert wire_hash(back) == wire_hash(sch)
    assert back.cell is cell
    assert back.I1.pos == sch.I1.pos

def test_farref():
    foreign = FarRef(b'\xaa' * 16, 42, name='foreign')
    orig = WHead(obj=foreign).freeze()
    back = subgraph_from_wire(subgraph_to_wire(orig))
    assert back.obj == foreign
    assert isinstance(back.obj, FarRef)
    # eq/hash ignore the name metadata:
    assert back.obj == FarRef(b'\xaa' * 16, 42, name='renamed')
    assert hash(foreign) == hash(FarRef(b'\xaa' * 16, 42))
    assert foreign != FarRef(b'\xbb' * 16, 42)

def test_own_endpoint_unknown_objid():
    bogus = FarRef(export_table.endpoint_id, 2**62, name='bogus')
    data = subgraph_to_wire(WHead(obj=bogus).freeze())
    with pytest.raises(WireError, match="obj_id"):
        subgraph_from_wire(data)

def test_missing_dep():
    orig = build_head()
    with pytest.raises(WireError, match="dependency"):
        subgraph_from_wire(subgraph_to_wire(orig), deps={})

def test_missing_wire_id():
    h = WHead(obj=live_obj)
    h % WNoWire(label='x')
    with pytest.raises(WireError, match="WNoWire"):
        subgraph_to_wire(h.freeze())

def test_wire_id_uniqueness():
    class WFresh(Node):
        wire_id = WIRE_DOMAIN | 999
    assert wire_registry[WIRE_DOMAIN | 999] is WFresh
    with pytest.raises(TypeError, match="already used"):
        class WCollision(Node):
            wire_id = WIRE_DOMAIN | 999

def test_unsupported_value():
    orig = WHead(obj=live_obj, blob=frozenset({1})).freeze()
    with pytest.raises(TypeError, match="WHead.blob"):
        subgraph_to_wire(orig)
