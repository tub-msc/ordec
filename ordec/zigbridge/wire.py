# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Canonical CBOR wire format for ORDB subgraphs, byte-compatible with
zig/src/serialize.zig:

Content form (the sha256 content hash input)::

    [1, root_type: tstr, nid_end: uint, [[nid, entry], ...]]

Transfer form (what crosses the language boundary)::

    [0, root_type: tstr, [parents], nid_end: uint, [[nid, entry], ...]]

    entry = [ntype_name: tstr, [attr, ...]]   ; attrs in Zig field order

The Python side always produces and consumes *single-generation* transfer
blobs (empty parent list, no tombstones): Python ORDB has no delta-chain
history to express, and the Zig side compact()s results before returning.
The subgraph hierarchy is fully preserved: SubgraphRef attributes serialize
as the target's 32-byte content hash and each referenced subgraph travels as
its own blob (a "bundle" is a list of blobs in dependency order, top last).

cbor2's default encoder already produces the canonical encoding this format
requires: definite lengths, minimal integer heads, tag 30 for Fraction
(head form below +/-2^64, bignum tags 2/3 beyond).
"""

import hashlib

import cbor2

from ..core.ordb import MutableSubgraph, FrozenSubgraph
from .tables import (
    NODE_TABLE, ROOTS, WIRE_TABLES, Opt, _SubgraphRef,
    WireError, UnsupportedNode, UnsupportedAttr,
)

CONTENT_VERSION = 1
TRANSFER_VERSION = 0


class _EncodeCtx:
    """Provides hash_of() to the SubgraphRef codec; memoizes per subgraph."""

    def __init__(self, memo=None):
        self.memo = memo if memo is not None else {}

    def hash_of(self, fsg):
        try:
            return self.memo[fsg]
        except KeyError:
            h = hashlib.sha256(_encode_content_obj(fsg, self)).digest()
            self.memo[fsg] = h
            return h


class _DecodeCtx:
    def __init__(self, deps):
        self.deps = deps


def _as_frozen_subgraph(sg):
    """Accept a FrozenSubgraph or any (frozen) cursor into one."""
    if isinstance(sg, FrozenSubgraph):
        return sg
    subgraph = getattr(sg, 'subgraph', None)
    if isinstance(subgraph, FrozenSubgraph):
        return subgraph
    raise TypeError(f"expected a frozen subgraph (or cursor), got {sg!r}")


def _encode_items(fsg, ctx, check_skip):
    """The [[nid, entry], ...] list shared by both wire forms."""
    items = []
    for nid in sorted(fsg.nodes):
        node = fsg.nodes[nid]
        cls = node._cursor_type
        spec = NODE_TABLE.get(cls)
        if spec is None:
            raise UnsupportedNode(
                f"{cls.__name__} (nid {nid}) has no wire representation"
            )
        if check_skip:
            for name in spec.skip:
                if node[node._attrdesc_by_name[name].index] is not None:
                    raise UnsupportedAttr(
                        f"{cls.__name__}.{name} (nid {nid}) is set but has "
                        f"no wire representation; pass strip_cell=True to "
                        f"drop it"
                    )
        attrs = []
        for name, codec in spec.fields:
            # Read the raw NodeTuple slot, never the cursor attribute: read
            # hooks would synthesize ConstrainableAttr placeholder objects
            # for unset values, wrap LocalRef nids in cursors and
            # SubgraphRefs in root cursors. The raw slot holds exactly the
            # wire-relevant value (None, plain value, int nid, or
            # FrozenSubgraph).
            v = node[node._attrdesc_by_name[name].index]
            try:
                attrs.append(codec.encode(v, ctx))
            except WireError as e:
                raise type(e)(f"{cls.__name__}.{name} (nid {nid}): {e}")
        items.append([nid, [spec.wire_name, attrs]])
    return items


def _root_wire_name(fsg):
    root_cls = fsg.nodes[0]._cursor_type
    for name, (cls, _members) in ROOTS.items():
        if cls is root_cls:
            return name
    raise UnsupportedNode(f"unsupported subgraph root {root_cls.__name__}")


def _encode_content_obj(fsg, ctx):
    name = _root_wire_name(fsg)
    items = _encode_items(fsg, ctx, check_skip=False)
    return cbor2.dumps([CONTENT_VERSION, name, fsg.nid_alloc.start, items])


def content_hash(fsg, memo=None) -> bytes:
    """sha256 of the canonical content form; the subgraph's global identity,
    equal to the Zig side's FrozenHeader.hash for equal content.

    The ``cell`` attribute has no wire representation and never enters the
    hash, regardless of the strip_cell policy: the hash is a pure function
    over wire-representable content (two subgraphs differing only in
    ``cell`` MUST collide, or re-attaching cell to a round-tripped subgraph
    would change its identity). The don't-silently-drop-data policy is
    enforced where data is actually dropped, in encode_transfer()."""
    return _EncodeCtx(memo).hash_of(_as_frozen_subgraph(fsg))


def encode_transfer(fsg, memo=None, strip_cell=False) -> bytes:
    """Encode a single-generation transfer blob. Raises UnsupportedAttr if a
    ``cell`` attribute is set, unless strip_cell explicitly drops it."""
    fsg = _as_frozen_subgraph(fsg)
    ctx = _EncodeCtx(memo)
    name = _root_wire_name(fsg)
    items = _encode_items(fsg, ctx, check_skip=not strip_cell)
    return cbor2.dumps([TRANSFER_VERSION, name, [], fsg.nid_alloc.start, items])


def collect_bundle(sg, memo=None, strip_cell=False):
    """
    Encode a subgraph and its full SubgraphRef closure as a bundle.

    Returns (blobs, deps): transfer blobs in dependency order (the given
    subgraph's blob last) and a dict mapping content hash -> FrozenSubgraph
    for every subgraph in the closure. Content-equal subgraphs are
    deduplicated (FrozenSubgraph hashes/compares by content).
    """
    top = _as_frozen_subgraph(sg)
    ctx = _EncodeCtx(memo)
    blobs = []
    deps = {}
    visited = set()

    def visit(fsg):
        if fsg in visited:
            return
        visited.add(fsg)
        for nid in sorted(fsg.nodes):
            node = fsg.nodes[nid]
            spec = NODE_TABLE.get(node._cursor_type)
            if spec is None:
                raise UnsupportedNode(
                    f"{node._cursor_type.__name__} (nid {nid}) has no wire "
                    f"representation"
                )
            for name, codec in spec.fields:
                inner = codec.inner if isinstance(codec, Opt) else codec
                if isinstance(inner, _SubgraphRef):
                    v = node[node._attrdesc_by_name[name].index]
                    if v is not None:
                        visit(v)
        deps[ctx.hash_of(fsg)] = fsg
        blobs.append(encode_transfer(fsg, ctx.memo, strip_cell))

    visit(top)
    return blobs, deps


def decode_transfer(blob: bytes, deps) -> FrozenSubgraph:
    """
    Decode a single-generation transfer blob into a FrozenSubgraph.
    SubgraphRef hashes are resolved through ``deps`` (content hash ->
    FrozenSubgraph). The usual deferred ORDB checks (required attributes,
    unique indexes, reference validity) run during reconstruction.
    """
    try:
        obj = cbor2.loads(blob)
    except Exception as e:
        raise WireError(f"undecodable CBOR: {e}")
    if not (isinstance(obj, list) and len(obj) == 5):
        raise WireError("not a transfer blob")
    version, root_name, parents, nid_end, items = obj
    if version != TRANSFER_VERSION:
        raise WireError(f"unsupported transfer version {version!r}")
    if parents != []:
        raise WireError("only single-generation blobs are supported on the "
                        "Python side (the Zig side compact()s its results)")
    try:
        wire_table = WIRE_TABLES[root_name]
        root_cls, _members = ROOTS[root_name]
    except (KeyError, TypeError):
        raise WireError(f"unsupported root type {root_name!r}")
    if not (isinstance(nid_end, int) and isinstance(items, list)):
        raise WireError("malformed transfer blob")

    ctx = _DecodeCtx(deps)
    nodes = {}
    prev_nid = -1
    for item in items:
        if not (isinstance(item, list) and len(item) == 2):
            raise WireError("malformed entry")
        nid, entry = item
        if not (isinstance(nid, int) and nid > prev_nid):
            raise WireError("entries not in ascending nid order")
        prev_nid = nid
        if entry is None:
            raise WireError("tombstone in a single-generation blob")
        if not (isinstance(entry, list) and len(entry) == 2):
            raise WireError("malformed entry")
        wire_name, attrs = entry
        try:
            cls = wire_table[wire_name]
        except (KeyError, TypeError):
            raise WireError(f"unknown node type {wire_name!r} in {root_name}")
        spec = NODE_TABLE[cls]
        if not (isinstance(attrs, list) and len(attrs) == len(spec.fields)):
            raise WireError(f"{wire_name}: wrong attribute count")
        kwargs = {}
        for (name, codec), v in zip(spec.fields, attrs):
            try:
                kwargs[name] = codec.decode(v, ctx)
            except WireError as e:
                raise type(e)(f"{wire_name}.{name} (nid {nid}): {e}")
        nodes[nid] = cls.Tuple(**kwargs)

    if 0 not in nodes or not isinstance(nodes[0], root_cls.Tuple):
        raise WireError(f"blob has no {root_name} root at nid 0")
    if nid_end <= prev_nid:
        raise WireError("nid_end inside the used nid range")

    root_cursor = MutableSubgraph.load(nodes)
    sg = root_cursor.subgraph
    # nid_end is part of the content hash; restore it exactly (load() only
    # advances the allocator to max nid + 1):
    if nid_end > sg.nid_alloc.start:
        sg.mutate(sg.nodes, sg.index, range(nid_end, 2**32))
    return sg.freeze()


def decode_bundle(blobs, deps=None) -> FrozenSubgraph:
    """Decode a bundle (list of transfer blobs in dependency order) and
    return the final blob's subgraph. ``deps`` seeds the resolvable
    dependency set and is extended with each decoded subgraph.

    Hashes are never trusted from the wire: each decoded subgraph is
    registered under the content hash recomputed from its decoded content
    (the Zig side does the same). A tampered or miscut blob therefore hashes
    to something nothing references, and decoding fails with a missing
    dependency instead of silently attaching wrong data. Seeding ``deps``
    with already-held subgraphs also means decoded SubgraphRefs resolve to
    those exact objects, not to duplicate copies."""
    deps = dict(deps) if deps else {}
    if not blobs:
        raise WireError("empty bundle")
    fsg = None
    memo = {}
    for blob in blobs:
        fsg = decode_transfer(blob, deps)
        deps[content_hash(fsg, memo)] = fsg
    return fsg
