# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.core import *
from ordec.core import ordb
from ordec.core.ordb.base import FarRef, LiveRef, wire_registry
from ordec.core.schema.base import SourceLocInfo
from ordec.core.wire import (
    WireError, ExportTable, wire_decode, WireSender, WireReceiver,
    compute_wire_hash,
)

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

class WPair(SubgraphRoot):
    wire_id = WIRE_DOMAIN | 4
    label = Attr(str)
    a = SubgraphRef(WSub)
    b = SubgraphRef(SubgraphRoot) # WSub or a nested WPair

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

# Want/have exchange
# ------------------

def exchange(root, ept_s, ept_r, store=None):
    """Lock-step pump; returns (result, per-round want lists)."""
    s = WireSender(root, ept_s)
    r = WireReceiver(ept_r, store)
    wants = [r.receive([s.root_block()])]
    while wants[-1]:
        wants.append(r.receive(s.serve(wants[-1])))
    return r.result, wants

def test_exchange_empty_store(ept):
    orig = build_head()
    store = {}
    back, wants = exchange(orig, ept, ept, store)
    assert back.subgraph == orig.subgraph
    assert back.obj is live_obj
    assert back.second.ref == back.first
    # Exactly one round: only the child is missing.
    sub_hash = orig.sub.subgraph.wire_hash(ept)
    assert wants == [[sub_hash], []]
    assert set(store) == {orig.subgraph.wire_hash(ept), sub_hash}
    # The pre-seeded hash memo matches an actual recomputation
    # (encode/decode asymmetry guard):
    assert back.subgraph.wire_hash(ept) == orig.subgraph.wire_hash(ept)
    assert compute_wire_hash(back.subgraph, ept) == \
        back.subgraph.wire_hash(ept)

def test_exchange_store_hit(ept):
    store = {}
    orig = build_head()
    back1, _ = exchange(orig, ept, ept, store)
    # Everything is in the store now; the root block alone completes the
    # exchange and yields the identical stored object.
    back2, wants = exchange(orig, ept, ept, store)
    assert wants == [[]]
    assert back2.subgraph is back1.subgraph

def test_exchange_partial_store(ept):
    sub1, sub2 = build_sub('one'), build_sub('two')
    pair = WPair(a=sub1, b=sub2).freeze()
    store = {}
    exchange(sub1, ept, ept, store)
    # Only the missing child is requested:
    back, wants = exchange(pair, ept, ept, store)
    assert wants[0] == [sub2.subgraph.wire_hash(ept)]
    assert back.a.subgraph is store[sub1.subgraph.wire_hash(ept)]

def test_exchange_depth_rounds(ept):
    mid = WPair(a=build_sub('m'), b=build_sub('leaf')).freeze()
    top = WPair(a=build_sub('t'), b=mid).freeze()
    # Round trips scale with the depth of the missing part of the DAG:
    back, wants = exchange(top, ept, ept)
    assert len(wants) == 3 # top's children; mid's children; done
    assert back.b.b.label == 'leaf'

def test_exchange_diamond(ept):
    sub = build_sub()
    inner = WPair(a=sub, b=build_sub('x')).freeze()
    outer = WPair(a=sub, b=inner).freeze()
    # The shared child is wanted once and materializes as one object:
    back, wants = exchange(outer, ept, ept)
    sub_hash = sub.subgraph.wire_hash(ept)
    assert [h for w in wants for h in w].count(sub_hash) == 1
    assert back.a.subgraph is back.b.a.subgraph

def test_exchange_two_endpoints(ept):
    ept2 = ExportTable()
    orig = build_head()
    back, _ = exchange(orig, ept, ept2)
    # The live object decodes to an opaque FarRef of the sender's endpoint:
    assert isinstance(back.obj, FarRef)
    assert back.obj.endpoint_id == ept.endpoint_id
    # FarRefs relay verbatim, so re-encoding under the receiver's table
    # reproduces the sender's bytes and hash:
    assert compute_wire_hash(back.subgraph, ept2) == \
        orig.subgraph.wire_hash(ept)

def test_exchange_real_schematic(ept):
    from ordec.examples.voltagedivider_py import VoltageDivider
    cell = VoltageDivider()
    sch = cell.schematic
    back, wants = exchange(sch, ept, ept)
    assert back.subgraph == sch.subgraph
    assert back.cell is cell
    assert len(wants) >= 2 # symbol children were actually transferred

def test_exchange_corrupt_block(ept):
    s = WireSender(build_head(), ept)
    r = WireReceiver(ept)
    h, data = s.root_block()
    with pytest.raises(WireError, match="announced hash"):
        r.receive([(h, data + b'\x00')])

def test_exchange_unrequested_block(ept):
    s = WireSender(build_head(), ept)
    r = WireReceiver(ept)
    r.receive([s.root_block()])
    stray = build_sub('stray').subgraph
    with pytest.raises(WireError, match="never wanted"):
        r.receive([(stray.wire_hash(ept), stray.wire_encode(ept))])

def test_exchange_serve_unknown(ept):
    s = WireSender(build_head(), ept)
    with pytest.raises(WireError, match="never announced"):
        s.serve([b'\x00' * 32])

def test_exchange_state_misuse(ept):
    s = WireSender(build_head(), ept)
    r = WireReceiver(ept)
    assert r.receive([s.root_block()]) # incomplete: child missing
    with pytest.raises(WireError, match="not complete"):
        r.result
    sub = build_sub()
    r2 = WireReceiver(ept)
    assert r2.receive([WireSender(sub, ept).root_block()]) == []
    with pytest.raises(WireError, match="already complete"):
        r2.receive([])
