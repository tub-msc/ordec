# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.core import *
from ordec.core import ordb
from ordec.core.ordb.base import FarRef, LiveRef, wire_registry
from ordec.core.schema.base import SourceLocInfo
from ordec.core.wire import WireError, ExportTable, wire_decode

@pytest.fixture(autouse=True, params=ordb.available_backends())
def ordb_backend(request):
    """Wire bytes and hashes must be identical across storage backends."""
    with ordb.use_backend(request.param):
        yield request.param

@pytest.fixture
def ept():
    """Fresh endpoint (export table) per test; there is no global one."""
    return ExportTable()

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

def test_determinism(ept):
    a, b = build_head(), build_head()
    assert a.subgraph.wire_encode(ept) == b.subgraph.wire_encode(ept)
    assert a.subgraph.wire_hash(ept) == b.subgraph.wire_hash(ept)

def test_cross_backend_hash(ept):
    h = build_head().subgraph.wire_hash(ept)
    with ordb.use_backend(ordb.available_backends()[0]):
        assert build_head().subgraph.wire_hash(ept) == h

def test_hash_sensitivity(ept):
    # SourceLocInfo data (src_loc) participates in the hash:
    assert build_head(loc_line=2).subgraph.wire_hash(ept) != \
        build_head().subgraph.wire_hash(ept)

def test_nid_alloc_sensitivity(ept):
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
    assert scarred.subgraph.wire_hash(ept) != plain.subgraph.wire_hash(ept)

def test_roundtrip(ept):
    orig = build_head()
    back = wire_decode(orig.subgraph.wire_encode(ept), ept,
        orig.subgraph.wire_deps(ept))
    assert back.subgraph == orig.subgraph
    assert back.subgraph.wire_hash(ept) == orig.subgraph.wire_hash(ept)
    # NPath navigation and value types survive:
    assert back.first.pos == Vec2R(1, 2)
    assert back.first.tup == ('a', 1, R(1, 3), Vec2R(5, 6))
    assert back.second.ref == back.first
    # The live object comes back as the identical object:
    assert back.obj is live_obj

def test_merkle(ept):
    sub = build_sub()
    h1 = build_head(sub=sub).subgraph.wire_hash(ept)
    assert build_head(sub=sub).subgraph.wire_hash(ept) == h1
    # Changed dependency content propagates into the parent hash:
    assert build_head(sub=build_sub(label='other')) \
        .subgraph.wire_hash(ept) != h1

def test_hash_endpoint_scoped(ept):
    # The same subgraph hashes differently under different endpoints
    # (export refs participate in the hashed bytes), and the single-entry
    # memo recomputes rather than leaking a stale table's hash.
    head = build_head()
    h1 = head.subgraph.wire_hash(ept)
    assert head.subgraph.wire_hash(ExportTable()) != h1
    assert head.subgraph.wire_hash(ept) == h1

def test_roundtrip_real_schematic(ept):
    from ordec.examples.voltagedivider_py import VoltageDivider
    cell = VoltageDivider()
    sch = cell.schematic
    deps = sch.subgraph.wire_deps(ept)
    back = wire_decode(sch.subgraph.wire_encode(ept), ept, deps)
    assert back.subgraph == sch.subgraph
    assert back.subgraph.wire_hash(ept) == sch.subgraph.wire_hash(ept)
    assert back.cell is cell
    assert back.I1.pos == sch.I1.pos

def test_farref(ept):
    foreign = FarRef(b'\xaa' * 16, 42, name='foreign')
    orig = WHead(obj=foreign).freeze()
    back = wire_decode(orig.subgraph.wire_encode(ept), ept)
    assert back.obj == foreign
    assert isinstance(back.obj, FarRef)
    # eq/hash ignore the name metadata:
    assert back.obj == FarRef(b'\xaa' * 16, 42, name='renamed')
    assert hash(foreign) == hash(FarRef(b'\xaa' * 16, 42))
    assert foreign != FarRef(b'\xbb' * 16, 42)

def test_own_endpoint_unknown_objid(ept):
    bogus = FarRef(ept.endpoint_id, 2**62, name='bogus')
    data = WHead(obj=bogus).freeze().subgraph.wire_encode(ept)
    with pytest.raises(WireError, match="obj_id"):
        wire_decode(data, ept)

def test_missing_dep(ept):
    orig = build_head()
    with pytest.raises(WireError, match="dependency"):
        wire_decode(orig.subgraph.wire_encode(ept), ept, deps={})

def test_missing_wire_id(ept):
    h = WHead(obj=live_obj)
    h % WNoWire(label='x')
    with pytest.raises(WireError, match="WNoWire"):
        h.freeze().subgraph.wire_encode(ept)

def test_wire_id_uniqueness():
    class WFresh(Node):
        wire_id = WIRE_DOMAIN | 999
    assert wire_registry[WIRE_DOMAIN | 999] is WFresh
    with pytest.raises(TypeError, match="already used"):
        class WCollision(Node):
            wire_id = WIRE_DOMAIN | 999

def test_unsupported_value(ept):
    orig = WHead(obj=live_obj, blob=frozenset({1})).freeze()
    with pytest.raises(TypeError, match="WHead.blob"):
        orig.subgraph.wire_encode(ept)

