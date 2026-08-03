# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Session-scoped wire serialization for ORDB subgraphs.

Subgraphs are encoded to canonical CBOR and identified by the SHA-256 hash of
their encoding (wire_hash). Nested SubgraphRefs are encoded as the wire_hash
of the referenced subgraph (Merkle-style), so a subgraph's hash covers its
transitive dependencies. LiveRef attributes (live objects such as Cells) are
encoded as (endpoint_id, obj_id, name) export references minted by the
process-global export_table; refs minted by a foreign endpoint decode to
opaque FarRef placeholders. Because export references participate in the
hashed bytes, wire hashes are session-scoped identity: they do not converge
across processes, by design. Wire data must never be stored in durable
artifacts (.ord files, uistate).

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

class ExportTable:
    """
    Process-global table of live objects that have crossed the wire inside
    LiveRef attributes. Export references are minted lazily at serialization
    time and memoized per object identity, so hashing is deterministic within
    the process. Exported objects are pinned (strong refs) for the process
    lifetime so that returning references always resolve.
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

#: The process-wide ExportTable singleton.
export_table = ExportTable()
public(export_table=export_table)

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

def encode_row_value(val, attr):
    if val is None:
        return None
    if isinstance(attr, LocalRef):
        return cbor2.CBORTag(TAG_LOCALREF, val)
    if isinstance(attr, ExternalRef):
        return cbor2.CBORTag(TAG_EXTERNALREF, val)
    if isinstance(attr, SubgraphRef):
        return cbor2.CBORTag(TAG_SUBGRAPHREF, wire_hash(val))
    if isinstance(attr, LiveRef):
        # Must precede plain-value dispatch: the stored value is an arbitrary
        # live object (or an already-opaque FarRef relayed onward).
        if isinstance(val, FarRef):
            return cbor2.CBORTag(TAG_LIVEREF,
                [val.endpoint_id, val.obj_id, val.name])
        return cbor2.CBORTag(TAG_LIVEREF, list(export_table.export(val)))
    return encode_plain(val)

@public
def subgraph_to_wire(x) -> bytes:
    """
    Encode a subgraph to canonical CBOR wire bytes. Nested SubgraphRefs are
    represented by their wire_hash; use wire_deps() to collect the referenced
    subgraphs for transmission.
    """
    sg = as_frozen(x)
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
                row.append(encode_row_value(node[ad.index], ad.attr))
            except TypeError as e:
                raise TypeError(f"{cls.__name__}.{ad.name}: {e}") from None
        rows_by_wid.setdefault(wid, []).append(row)
    return cbor2.dumps([rows_by_wid, sg.nid_alloc.start], canonical=True)

@public
def wire_hash(x) -> bytes:
    """
    SHA-256 wire hash (32 bytes) of a subgraph, memoized on FrozenSubgraph.
    Mutable input is hashed via a temporary freeze without memoization.
    """
    sg = as_frozen(x)
    h = sg._cached_wire_hash
    if h is None:
        h = hashlib.sha256(HASH_DOMAIN + subgraph_to_wire(sg)).digest()
        sg._cached_wire_hash = h
    return h

@public
def wire_deps(x) -> dict[bytes, FrozenSubgraph]:
    """
    Collect the transitive SubgraphRef dependencies of a subgraph, keyed by
    their wire_hash. Suitable as the deps argument of subgraph_from_wire.
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
                h = wire_hash(child)
                if h not in deps:
                    deps[h] = child
                    collect(child)
    collect(as_frozen(x))
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

def resolve_row_value(val, deps):
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
        if endpoint_id == export_table.endpoint_id:
            return export_table.resolve(obj_id)
        return FarRef(endpoint_id, obj_id, name)
    return fix_plain(val)

@public
def subgraph_from_wire(data: bytes, deps=None) -> Node:
    """
    Decode wire bytes into a new FrozenSubgraph, returned as its root cursor.

    Args:
        data: Bytes produced by subgraph_to_wire.
        deps: Mapping of wire_hash to already-materialized subgraph for every
            SubgraphRef occurring in data (see wire_deps). All dependencies
            must be present; laziness exists only on the wire.
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
                kwargs[ad.name] = resolve_row_value(val, deps)
            u.add_single(cls.Tuple(**kwargs), nid=nid)
    # The updater clamps nid_alloc.start to max_nid+1; restore the encoded
    # start (they differ when top nids were deleted before serialization).
    if sg.nid_alloc.start != nid_start:
        sg.mutate(sg.nodes, sg.index, range(nid_start, sg.nid_alloc.stop))
    return sg.freeze().root_cursor
