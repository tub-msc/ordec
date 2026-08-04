# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Session-scoped wire serialization for ORDB subgraphs.

The user-facing API is on FrozenSubgraph (ordb/base.py): wire_encode(),
wire_hash() and wire_deps(); this module provides their backends plus the
decoder, wire_decode().

Subgraphs are encoded to canonical CBOR and identified by the SHA-256 hash of
their encoding (wire_hash). Nested SubgraphRefs are encoded as the wire_hash
of the referenced subgraph (Merkle-style), so a subgraph's hash covers its
transitive dependencies. LiveRef attributes (live objects such as Cells) are
encoded as (endpoint_id, obj_id, name) export references minted by a
caller-supplied ExportTable; refs minted by a foreign endpoint decode to
opaque FarRef placeholders. There is deliberately no ambient/global table:
every encode, hash and decode operation takes the table as an explicit
parameter, and the table's owner decides its scope and lifetime (e.g. one
table per server). Because export references participate in the hashed
bytes, wire hashes are endpoint-scoped identity: they do not converge
across endpoints, by design. Wire data must never be stored in durable
artifacts (.ord files, uistate).

The want/have exchange (WireSender/WireReceiver) transfers a subgraph DAG
between two endpoints while retransmitting only subgraphs the receiver does
not already hold in its store; laziness exists on the wire only, in-memory
SubgraphRefs always hold fully materialized subgraphs.

Wire format (format version is the digit in HASH_DOMAIN):

    wire_bytes(sg) = canonical CBOR of [ {wire_id: [[nid, v0, ..., vN], ...]},
                                         nid_alloc.start ]
                     with rows ascending by nid and row values in
                     NodeTuple._layout order
    wire_hash(sg)  = SHA256(HASH_DOMAIN + wire_bytes(sg))

This module imports ordb and the schema modules; it must never be imported by
them (or by core/__init__), so its top-level schema imports stay cycle-free.
"""

from fractions import Fraction
import hashlib
import os
import threading

import cbor2
from public import public

from .ordb.base import (
    LocalRef, ExternalRef, SubgraphRef, LiveRef, FarRef, Node, Subgraph,
    FrozenSubgraph, MutableSubgraph, OrdbException, wire_registry,
)
from .rational import R
from .geoprim import Vec2R, Vec2I, Rect4R, Rect4I, TD4R, TD4I, D4
from .simarray import SimArray, SimArrayField
from .schema.base import PathEndType, SourceLocInfo, GdsLayer, RGBColor
from .schema.schematic import PinType, SchemErrorType
from .schema.report import ScaleType
from .schema.simhier import SimType
from .schema.lvs import LvsStatus, LvsItemType

HASH_DOMAIN = b'ordec-sg-0:'

# CBOR tag assignments. Tag 30 is the standard rational tag, used for R
# (Fraction invariant guarantees reduced form). The 3900xx block is
# ORDeC-private: 3900{01..2x} value types, 3900{30..3x} attr-kind wrappers.
TAG_VEC2R = 390001
TAG_VEC2I = 390002
TAG_RECT4R = 390003
TAG_RECT4I = 390004
TAG_TD4R = 390005
TAG_TD4I = 390006
TAG_SIMARRAY = 390020
TAG_SOURCELOC = 390021
TAG_GDSLAYER = 390022
TAG_RGBCOLOR = 390023
TAG_LOCALREF = 390030
TAG_EXTERNALREF = 390031
TAG_SUBGRAPHREF = 390032
TAG_LIVEREF = 390033

# Enums are encoded by member name, one tag per enum class.
ENUM_TAGS = {
    D4: 390007,
    PathEndType: 390010,
    PinType: 390011,
    SchemErrorType: 390012,
    ScaleType: 390013,
    SimType: 390014,
    LvsStatus: 390015,
    LvsItemType: 390016,
}
ENUM_BY_TAG = {tag: cls for cls, tag in ENUM_TAGS.items()}

@public
class WireError(OrdbException):
    """Raised on wire encoding/decoding protocol violations."""
    pass

@public
class ExportTable:
    """
    Table of live objects that have crossed the wire inside LiveRef
    attributes; one per endpoint, created and owned by the API user (no
    global instance exists). Export references are minted lazily at
    serialization time and memoized per object identity, so hashing is
    deterministic per table. Exported objects are pinned (strong refs) for
    the table's lifetime so that returning references always resolve.
    """
    def __init__(self):
        self.endpoint_id = os.urandom(16)
        self._lock = threading.Lock()
        self._entry_of_pyid = {} # id(obj) -> (obj, obj_id, name); pins obj
        self._obj_of_id = {}

    def export(self, obj) -> tuple[bytes, int, str]:
        """Returns (endpoint_id, obj_id, name) for obj, minting if needed."""
        with self._lock:
            entry = self._entry_of_pyid.get(id(obj))
            if entry is None:
                obj_id = len(self._obj_of_id) + 1
                entry = (obj, obj_id, repr(obj))
                self._entry_of_pyid[id(obj)] = entry
                self._obj_of_id[obj_id] = obj
            return (self.endpoint_id, entry[1], entry[2])

    def resolve(self, obj_id: int):
        """Returns the live object for an own-endpoint obj_id."""
        with self._lock:
            try:
                return self._obj_of_id[obj_id]
            except KeyError:
                raise WireError(
                    f"Unknown obj_id {obj_id} for own endpoint"
                    " (protocol violation)."
                ) from None

def as_frozen(x) -> FrozenSubgraph:
    if isinstance(x, Node):
        x = x.subgraph
    if isinstance(x, MutableSubgraph):
        x = x.freeze()
    if not isinstance(x, FrozenSubgraph):
        raise TypeError(f"Expected subgraph or cursor, got {type(x).__name__}.")
    return x

# Encoding
# --------

def encode_plain(val):
    t = type(val)
    if val is None or t in (bool, int, str, bytes, float):
        return val
    if t is R:
        return cbor2.CBORTag(30, [val.numerator, val.denominator])
    if t is Vec2R:
        return cbor2.CBORTag(TAG_VEC2R, [encode_plain(val.x), encode_plain(val.y)])
    if t is Vec2I:
        return cbor2.CBORTag(TAG_VEC2I, [val.x, val.y])
    if t is Rect4R:
        return cbor2.CBORTag(TAG_RECT4R,
            [encode_plain(v) for v in (val.lx, val.ly, val.ux, val.uy)])
    if t is Rect4I:
        return cbor2.CBORTag(TAG_RECT4I, [val.lx, val.ly, val.ux, val.uy])
    if t is TD4R:
        return cbor2.CBORTag(TAG_TD4R,
            [encode_plain(val.transl), encode_plain(val.d4)])
    if t is TD4I:
        return cbor2.CBORTag(TAG_TD4I,
            [encode_plain(val.transl), encode_plain(val.d4)])
    if t in ENUM_TAGS:
        return cbor2.CBORTag(ENUM_TAGS[t], val.name)
    if t is SimArray:
        # data may be a memoryview (SimArray permits it); force bytes so the
        # encoding is a CBOR byte string either way.
        return cbor2.CBORTag(TAG_SIMARRAY,
            [[[f.fid, f.dtype] for f in val.fields], bytes(val.data)])
    if t is SourceLocInfo:
        return cbor2.CBORTag(TAG_SOURCELOC, list(val))
    if t is GdsLayer:
        return cbor2.CBORTag(TAG_GDSLAYER, list(val))
    if t is RGBColor:
        return cbor2.CBORTag(TAG_RGBCOLOR, list(val))
    if t is tuple:
        return [encode_plain(v) for v in val]
    raise TypeError(f"Type {t.__name__} is not wire-serializable.")

def encode_row_value(val, attr, ept: ExportTable):
    if val is None:
        return None
    if isinstance(attr, LocalRef):
        return cbor2.CBORTag(TAG_LOCALREF, val)
    if isinstance(attr, ExternalRef):
        return cbor2.CBORTag(TAG_EXTERNALREF, val)
    if isinstance(attr, SubgraphRef):
        return cbor2.CBORTag(TAG_SUBGRAPHREF, val.wire_hash(ept))
    if isinstance(attr, LiveRef):
        # Must precede plain-value dispatch: the stored value is an arbitrary
        # live object (or an already-opaque FarRef relayed onward).
        if isinstance(val, FarRef):
            return cbor2.CBORTag(TAG_LIVEREF,
                [val.endpoint_id, val.obj_id, val.name])
        return cbor2.CBORTag(TAG_LIVEREF, list(ept.export(val)))
    return encode_plain(val)

def encode_subgraph(sg: FrozenSubgraph, ept: ExportTable) -> bytes:
    """
    Encode a frozen subgraph to canonical CBOR wire bytes. Nested
    SubgraphRefs are represented by their wire_hash; collect the referenced
    subgraphs for transmission via FrozenSubgraph.wire_deps(). Backend of
    FrozenSubgraph.wire_encode().
    """
    rows_by_wid = {}
    for nid in sorted(sg.nodes):
        node = sg.nodes[nid]
        cls = node._cursor_type
        wid = cls.__dict__.get('wire_id')
        if wid is None:
            raise WireError(f"{cls.__name__} declares no wire_id;"
                " cannot serialize.")
        row = [nid]
        for ad in node._layout:
            try:
                row.append(encode_row_value(node[ad.index], ad.attr, ept))
            except TypeError as e:
                raise TypeError(f"{cls.__name__}.{ad.name}: {e}") from None
        rows_by_wid.setdefault(wid, []).append(row)
    return cbor2.dumps([rows_by_wid, sg.nid_alloc.start], canonical=True)

def hash_wire_bytes(data: bytes) -> bytes:
    """
    Domain-prefixed SHA-256 (32 bytes) over wire bytes. The wire hash is
    purely a digest of the encoding, which is what allows
    FrozenSubgraph.wire_encode() to memoize the hash as a side effect.
    """
    return hashlib.sha256(HASH_DOMAIN + data).digest()

def compute_wire_hash(sg: FrozenSubgraph, ept: ExportTable) -> bytes:
    """
    Recompute the wire hash from scratch, bypassing the memo that
    FrozenSubgraph.wire_hash()/wire_encode() maintain. Normal callers use
    wire_hash(); this exists for memo-independent verification (tests).
    """
    return hash_wire_bytes(encode_subgraph(sg, ept))

def collect_wire_deps(sg: FrozenSubgraph,
        ept: ExportTable) -> dict[bytes, FrozenSubgraph]:
    """
    Collect the transitive SubgraphRef dependencies of a frozen subgraph,
    keyed by their wire_hash. Backend of FrozenSubgraph.wire_deps().
    """
    deps = {}
    def collect(sg):
        for nid in sorted(sg.nodes):
            node = sg.nodes[nid]
            for ad in node._layout:
                if not isinstance(ad.attr, SubgraphRef):
                    continue
                child = node[ad.index]
                if child is None:
                    continue
                h = child.wire_hash(ept)
                if h not in deps:
                    deps[h] = child
                    collect(child)
    collect(sg)
    return deps

# Decoding
# --------

class RefMarker:
    """Wraps ref-tag payloads between tag_hook and row reconstruction."""
    __slots__ = ('tag', 'value')
    def __init__(self, tag, value):
        self.tag = tag
        self.value = value

def tag_hook(tag, shareable):
    t = tag.tag
    v = tag.value
    if t in (TAG_LOCALREF, TAG_EXTERNALREF, TAG_SUBGRAPHREF, TAG_LIVEREF):
        return RefMarker(t, v)
    if t == TAG_VEC2R:
        return Vec2R(R(v[0]), R(v[1]))
    if t == TAG_VEC2I:
        return Vec2I(v[0], v[1])
    if t == TAG_RECT4R:
        return Rect4R(*[R(c) for c in v])
    if t == TAG_RECT4I:
        return Rect4I(*v)
    if t == TAG_TD4R:
        return TD4R(transl=v[0], d4=v[1])
    if t == TAG_TD4I:
        return TD4I(transl=v[0], d4=v[1])
    if t in ENUM_BY_TAG:
        return ENUM_BY_TAG[t][v]
    if t == TAG_SIMARRAY:
        return SimArray([SimArrayField(*f) for f in v[0]], v[1])
    if t == TAG_SOURCELOC:
        return SourceLocInfo(*v)
    if t == TAG_GDSLAYER:
        return GdsLayer(*v)
    if t == TAG_RGBCOLOR:
        return RGBColor(*v)
    raise WireError(f"Unknown wire tag {t}.")

def fix_plain(val):
    # cbor2 auto-decodes tag 30 to Fraction before the tag_hook runs, and
    # plain CBOR arrays (encoded tuples) decode as lists.
    if type(val) is Fraction:
        return R(val)
    if type(val) in (list, tuple):
        return tuple(fix_plain(v) for v in val)
    return val

def resolve_row_value(val, deps, ept):
    if isinstance(val, RefMarker):
        if val.tag in (TAG_LOCALREF, TAG_EXTERNALREF):
            return val.value # stored nid
        if val.tag == TAG_SUBGRAPHREF:
            try:
                return as_frozen(deps[bytes(val.value)])
            except KeyError:
                raise WireError(
                    f"Missing dependency subgraph {bytes(val.value).hex()}."
                ) from None
        endpoint_id, obj_id, name = val.value
        endpoint_id = bytes(endpoint_id)
        if endpoint_id == ept.endpoint_id:
            return ept.resolve(obj_id)
        return FarRef(endpoint_id, obj_id, name)
    return fix_plain(val)

@public
def wire_decode(data: bytes, ept: ExportTable, deps=None) -> Node:
    """
    Decode wire bytes into a new FrozenSubgraph, returned as its root cursor.

    Args:
        data: Bytes produced by FrozenSubgraph.wire_encode().
        ept: The decoding endpoint's ExportTable; refs minted by it resolve
            to the identical live objects, foreign refs decode to FarRefs.
        deps: Mapping of wire_hash to already-materialized subgraph for every
            SubgraphRef occurring in data (see FrozenSubgraph.wire_deps()).
            All dependencies must be present; laziness exists only on the
            wire.
    """
    if deps is None:
        deps = {}
    try:
        tree = cbor2.loads(data, tag_hook=tag_hook)
    except cbor2.CBORDecodeError as e:
        raise WireError(f"CBOR decode failed: {e}") from e
    if not (isinstance(tree, list) and len(tree) == 2
            and isinstance(tree[0], dict) and isinstance(tree[1], int)):
        raise WireError("Malformed wire data (expected [rows, nid_start]).")
    rows_by_wid, nid_start = tree

    items = []
    for wid, rows in rows_by_wid.items():
        cls = wire_registry.get(wid)
        if cls is None:
            raise WireError(f"Unknown wire_id {wid:#x}.")
        layout = cls.Tuple._layout
        for row in rows:
            if not isinstance(row, list) or len(row) != len(layout) + 1:
                raise WireError(f"Malformed row for {cls.__name__}.")
            items.append((row[0], cls, row[1:]))
    items.sort(key=lambda item: item[0])

    sg = MutableSubgraph()
    with sg.updater() as u:
        for nid, cls, values in items:
            kwargs = {}
            for ad, val in zip(cls.Tuple._layout, values):
                kwargs[ad.name] = resolve_row_value(val, deps, ept)
            u.add_single(cls.Tuple(**kwargs), nid=nid)
    # The updater clamps nid_alloc.start to max_nid+1; restore the encoded
    # start (they differ when top nids were deleted before serialization).
    if sg.nid_alloc.start != nid_start:
        sg.mutate(sg.nodes, sg.index, range(nid_start, sg.nid_alloc.stop))
    return sg.freeze().root_cursor

# Want/have exchange
# ------------------
#
# Transfers one root subgraph per exchange while retransmitting only the
# parts of its Merkle DAG that the receiver does not already hold. Message
# shapes are plain Python values (a block is a (hash, bytes) pair, a want is
# a list of hashes); framing them is the transport's job. The exchange is
# lock-step: the sender pushes the root block unconditionally, the receiver
# answers each delivery with the list of hashes to send next, and an empty
# answer means the exchange is complete (sound because the sender holds the
# full DAG and always serves a want list completely).

def collect_child_hashes(data: bytes) -> list[bytes]:
    """
    Direct SubgraphRef child hashes occurring in wire bytes, deduplicated,
    in encounter order. Pass-through CBOR scan; no values are reconstructed.
    """
    hashes = {}
    def hook(tag, shareable):
        if tag.tag == TAG_SUBGRAPHREF:
            hashes[bytes(tag.value)] = None
        return tag
    try:
        cbor2.loads(data, tag_hook=hook)
    except cbor2.CBORDecodeError as e:
        raise WireError(f"CBOR decode failed: {e}") from e
    return list(hashes)

@public
class WireSender:
    """
    Sender side of the want/have exchange for one root subgraph. The sender
    holds the fully materialized DAG in memory, so it can serve any hash it
    announced (the root and its transitive closure).
    """
    def __init__(self, sg, ept: ExportTable):
        self.ept = ept
        self.sg = as_frozen(sg)
        self._table = None # lazy wire_hash -> FrozenSubgraph, full closure

    def root_block(self) -> tuple[bytes, bytes]:
        """The unconditionally transmitted first block: (hash, wire bytes)."""
        # Encode first: wire_encode memoizes the wire hash as a side
        # effect, so the wire_hash call below is free.
        data = self.sg.wire_encode(self.ept)
        return (self.sg.wire_hash(self.ept), data)

    def serve(self, want) -> list[tuple[bytes, bytes]]:
        """Blocks for a want list of hashes; all must have been announced."""
        if self._table is None:
            self._table = {self.sg.wire_hash(self.ept): self.sg}
            self._table.update(self.sg.wire_deps(self.ept))
        blocks = []
        for h in want:
            h = bytes(h)
            try:
                sg = self._table[h]
            except KeyError:
                raise WireError(f"Subgraph {h.hex()} was never announced"
                    " (protocol violation).") from None
            blocks.append((h, sg.wire_encode(self.ept)))
        return blocks

@public
class WireReceiver:
    """
    Receiver side of the want/have exchange; one instance per transferred
    root. Feed the sender's root block into receive(), serve each returned
    want list, and repeat until receive() returns an empty list; the
    materialized root is then available as .result.

    The store is a plain dict of wire_hash -> FrozenSubgraph, created and
    owned by the caller (no weak references; the owner's explicit lifetime
    bounds how long received subgraphs stay available without
    retransmission). Materialized subgraphs are added to it.
    """
    def __init__(self, ept: ExportTable, store: dict=None):
        self.ept = ept
        self.store = store if store is not None else {}
        self._root_hash = None
        self._outstanding = set() # wanted hashes not yet received
        self._pending = {} # wire_hash -> (data, child hashes), undecoded
        self._resolved = {} # wire_hash -> FrozenSubgraph
        self._result = None

    def receive(self, blocks) -> list[bytes]:
        """
        Ingest (hash, data) blocks; the first block of the exchange is the
        root. Returns the hashes to request next; an empty list means the
        exchange is complete.
        """
        if self._result is not None:
            raise WireError("Exchange is already complete.")
        new_children = []
        for h, data in blocks:
            h = bytes(h)
            if self._root_hash is None:
                self._root_hash = h
            elif h in self._outstanding:
                self._outstanding.discard(h)
            else:
                raise WireError(f"Received block {h.hex()} that was never"
                    " wanted (protocol violation).")
            if hashlib.sha256(HASH_DOMAIN + data).digest() != h:
                raise WireError(
                    f"Block does not match its announced hash {h.hex()}.")
            if h in self.store:
                self._resolved[h] = self.store[h]
                continue
            children = collect_child_hashes(data)
            self._pending[h] = (data, children)
            new_children.extend(children)
        want = []
        for c in dict.fromkeys(new_children):
            if (c in self._resolved or c in self._pending
                    or c in self._outstanding):
                continue
            if c in self.store:
                self._resolved[c] = self.store[c]
                continue
            want.append(c)
        self._outstanding.update(want)
        if not want and not self._outstanding:
            self._result = self._materialize(self._root_hash).root_cursor
        return want

    def _materialize(self, h) -> FrozenSubgraph:
        # Bottom-up (post-order) over the pending blocks; acyclic by Merkle
        # construction. Recursion depth is the DAG depth, which is shallow
        # for design data.
        sg = self._resolved.get(h)
        if sg is None:
            data, children = self._pending.pop(h)
            deps = {c: self._materialize(c) for c in children}
            sg = wire_decode(data, self.ept, deps).subgraph
            # The bytes were verified against h on receipt and re-encoding
            # is deterministic (FarRefs relay verbatim, own-endpoint refs
            # re-export to their memoized ids), so pre-seed the hash memo
            # instead of re-encoding the whole subgraph.
            sg._cached_wire_hash = (self.ept, h)
            self._resolved[h] = sg
            self.store[h] = sg
        return sg

    @property
    def result(self) -> Node:
        """Root cursor of the transferred subgraph, once complete."""
        if self._result is None:
            raise WireError("Exchange is not complete.")
        return self._result
