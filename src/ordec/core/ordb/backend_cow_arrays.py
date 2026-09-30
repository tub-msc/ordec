# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
cow-arrays storage backend: the cow backend plus native storage of array
rows (see ordec.core.ordb.arrays).

Rows inserted with SubgraphUpdater.insert_array() are stored in chunks, one
per insert_array call: an ascending nid array, the int64 columns and a live
mask. All other nodes are stored in the cow dict part, including arrayable
rows inserted with add_single() and chunk rows whose update makes them
non-representable (they move to the dict part). Every nid is in exactly one
of the two parts; nodes[nid] and index[key] merge them.

Chunk rows have no index entries of their own: the NType index bucket of an
arrayable type is the union of its live chunk nids and its dict-part bucket.
Hence only arrayable types whose other indices keep no buckets
(ExternalRefIndex, integrity checks only) are stored in chunks, e.g.
LayoutRect; insert_array() of other types falls back to add_single().

Transactions collect chunk edits in an overlay (updated row values, removed
nids) and new chunks separately, and apply them at commit: in place for
chunks owned by the mutable subgraph, on a copy for chunks shared with a
snapshot (Chunk.shared, set at freeze/thaw/fork like the cow dicts'
shared flag). Arrays returned by arrays() for frozen subgraphs are views of
shared chunks, which are never modified again.
"""

import bisect
import hashlib
from collections.abc import Mapping
from types import SimpleNamespace

import numpy as np

from .backend import StorageBackend, StorageTxn, BucketKind
from .backend_cow import CowTxn, CowNodes, _new_cow_index
from .base import ExternalRefIndex
from .arrays import make_tuple, row_values, columns

class Chunk:
    __slots__ = ('nids', 'cols', 'live', 'shared', 'first')

    def __init__(self, nids, cols, live=None, shared=False):
        self.nids = nids # ascending int64
        self.cols = cols # attr name -> int64 array
        self.live = live # bool array, None: all rows live
        self.shared = shared
        self.first = int(nids[0])

    def row(self, nid) -> int|None:
        """Row index of nid (live or not) or None."""
        nids = self.nids
        if nid < self.first or nid > nids[-1]:
            return None
        i = int(np.searchsorted(nids, nid))
        return i if nids[i] == nid else None

    def is_live(self, i) -> bool:
        return self.live is None or bool(self.live[i])

    def live_nids(self):
        return self.nids if self.live is None else self.nids[self.live]

    def live_cols(self) -> dict:
        if self.live is None:
            return self.cols
        return {k: v[self.live] for k, v in self.cols.items()}

    def count(self) -> int:
        return len(self.nids) if self.live is None else int(self.live.sum())

    def copy(self) -> 'Chunk':
        return Chunk(self.nids, {k: v.copy() for k, v in self.cols.items()},
            None if self.live is None else self.live.copy())

def _materialize(ntuple, chunk, i, values=None):
    fields = ntuple._array_layout
    if values is None:
        values = [chunk.cols[f.name][i].tolist() for f in fields]
    return make_tuple(ntuple._cursor_type, fields, values)

def _locate(tables, nid):
    """(ntuple, chunk, row) of a live chunk row with nid, or None."""
    for ntuple, chunks in tables.items():
        k = bisect.bisect_right(chunks, nid, key=lambda c: c.first) - 1
        if k < 0:
            continue
        chunk = chunks[k]
        i = chunk.row(nid)
        if i is not None and chunk.is_live(i):
            return ntuple, chunk, i
    return None

def _sorted_merge(parts) -> list:
    nids = np.concatenate(parts) if parts else np.empty(0, np.int64)
    nids.sort()
    return nids.tolist()

class ArrayNodes(Mapping):
    """Committed node state: cow dict part plus chunk tables."""
    __slots__ = ('d', 'tables')

    def __init__(self, d, tables):
        self.d = d # CowNodes
        self.tables = tables # NodeTuple subclass -> tuple[Chunk], by first nid

    def __getitem__(self, nid):
        try:
            return dict.__getitem__(self.d, nid)
        except KeyError:
            loc = _locate(self.tables, nid)
            if loc is None:
                raise
            return _materialize(*loc)

    def __contains__(self, nid):
        return dict.__contains__(self.d, nid) or _locate(self.tables, nid) is not None

    def __iter__(self):
        yield from dict.__iter__(self.d)
        for chunks in self.tables.values():
            for chunk in chunks:
                yield from chunk.live_nids().tolist()

    def __len__(self):
        return len(self.d) + sum(c.count() for chunks in self.tables.values() for c in chunks)

class ArrayIndex(Mapping):
    """Committed index state: cow index plus the NType buckets of chunk rows."""
    __slots__ = ('d', 'tables')

    def __init__(self, d, tables):
        self.d = d # CowIndex
        self.tables = tables # shared with ArrayNodes

    def _chunk_nids(self, key):
        chunks = self.tables.get(key) if isinstance(key, type) else None
        if not chunks:
            return None
        return [c.live_nids() for c in chunks]

    def __getitem__(self, key):
        parts = self._chunk_nids(key)
        if parts is None:
            return self.d[key]
        bucket = dict.get(self.d, key)
        if bucket is not None:
            parts.append(np.array(bucket, dtype=np.int64))
        return _sorted_merge(parts)

    def __contains__(self, key):
        return self._chunk_nids(key) is not None or key in self.d

    def __iter__(self):
        yield from dict.__iter__(self.d)
        for key in self.tables:
            if not dict.__contains__(self.d, key):
                yield key

    def __len__(self):
        return sum(1 for _ in self)

class TxnNodes(Mapping):
    """Node state of an open transaction."""
    __slots__ = ('txn',)

    def __init__(self, txn):
        self.txn = txn

    def __getitem__(self, nid):
        txn = self.txn
        try:
            return txn.cow.nodes[nid]
        except KeyError:
            loc = txn.locate(nid)
            if loc is None:
                raise
            return _materialize(*loc, values=txn.upd.get(nid))

    def __contains__(self, nid):
        return nid in self.txn.cow.nodes or self.txn.locate(nid) is not None

    def __iter__(self):
        txn = self.txn
        yield from txn.cow.nodes
        for ntuple in txn.chunk_types():
            yield from _sorted_merge(txn.chunk_nids(ntuple))

    def __len__(self):
        txn = self.txn
        return len(txn.cow.nodes) + sum(len(p) for ntuple in txn.chunk_types()
            for p in txn.chunk_nids(ntuple))

class TxnIndex(Mapping):
    """Index state of an open transaction."""
    __slots__ = ('txn',)

    def __init__(self, txn):
        self.txn = txn

    def __getitem__(self, key):
        txn = self.txn
        parts = txn.chunk_nids(key) if isinstance(key, type) else None
        if not parts:
            return txn.cow.index[key]
        if key in txn.cow.index:
            parts.append(np.array(txn.cow.index[key], dtype=np.int64))
        return _sorted_merge(parts)

    def __contains__(self, key):
        txn = self.txn
        return (isinstance(key, type) and bool(txn.chunk_nids(key))) or key in txn.cow.index

    def __iter__(self):
        txn = self.txn
        yield from txn.cow.index
        for key in txn.chunk_types():
            if key not in txn.cow.index and txn.chunk_nids(key):
                yield key

    def __len__(self):
        return sum(1 for _ in self)

class CowArraysTxn(StorageTxn):
    __slots__ = ('nodes', 'index', 'cow', 'tables', 'new', 'upd', 'dead')

    def __init__(self, subgraph):
        base_nodes = subgraph.nodes
        self.cow = CowTxn(SimpleNamespace(nodes=base_nodes.d, index=subgraph.index.d))
        self.tables = base_nodes.tables
        self.new = {} # NodeTuple subclass -> list[Chunk] inserted in this txn
        self.upd = {} # nid -> row values (list per field) of updated chunk rows
        self.dead = set() # nids of chunk rows removed in this txn
        self.nodes = TxnNodes(self)
        self.index = TxnIndex(self)

    def locate(self, nid):
        """(ntuple, chunk, row) of a chunk row alive in this txn, or None."""
        if nid in self.dead:
            return None
        loc = _locate(self.tables, nid)
        if loc is None and self.new:
            loc = _locate(self.new, nid)
        return loc

    def chunk_types(self) -> set:
        return self.tables.keys() | self.new.keys()

    def chunk_nids(self, ntuple) -> list:
        """nid arrays of the chunk rows of ntuple alive in this txn."""
        ret = []
        dead = np.fromiter(self.dead, dtype=np.int64) if self.dead else None
        for tables in (self.tables, self.new):
            for c in tables.get(ntuple, ()):
                nids = c.live_nids()
                if dead is not None:
                    nids = nids[~np.isin(nids, dead)]
                if len(nids):
                    ret.append(nids)
        return ret

    def _chunk_resident(self, key, nid) -> bool:
        if not isinstance(key, type) or getattr(key, '_array_layout', None) is None:
            return False
        loc = self.locate(nid)
        return loc is not None and loc[0] is key

    def node_set(self, nid, node):
        loc = self.locate(nid)
        if loc is not None:
            ntuple = loc[0]
            if type(node) is ntuple:
                values = row_values(ntuple._array_layout, node)
                if values is not None:
                    self.upd[nid] = [v if isinstance(v, int) else list(v) for v in values]
                    return
            # Not representable in its chunk anymore: move to the dict part.
            self.dead.add(nid)
            self.upd.pop(nid, None)
        self.cow.node_set(nid, node)

    def node_remove(self, nid):
        if self.locate(nid) is not None:
            self.dead.add(nid)
            self.upd.pop(nid, None)
        else:
            self.cow.node_remove(nid)

    def bucket_add(self, key, value, kind):
        # The NType bucket of chunk rows is implied by the chunk.
        if kind == BucketKind.NID and self._chunk_resident(key, value):
            return
        self.cow.bucket_add(key, value, kind)

    def bucket_remove(self, key, value, kind):
        if kind == BucketKind.NID and self._chunk_resident(key, value):
            return
        self.cow.bucket_remove(key, value, kind)

    def bucket_add_sorted(self, key, value, sortval, sortval_of):
        self.cow.bucket_add_sorted(key, value, sortval, sortval_of)

    def insert_array(self, ntype, nids, cols) -> bool:
        ntuple = ntype.Tuple
        if not all(isinstance(idx, ExternalRefIndex) for idx in ntuple.indices):
            return False
        lo, hi = int(nids[0]), int(nids[-1])
        if any(lo <= nid <= hi for nid in self.cow.nodes) \
                or any(c.first <= hi and lo <= c.nids[-1]
                    for tables in (self.tables, self.new)
                    for chunks in tables.values() for c in chunks):
            # Overlapping nid ranges are rare (insert_array allocates fresh
            # nids; only wire_decode passes explicit ones); check precisely.
            for nid in nids.tolist():
                if nid in self.nodes:
                    raise KeyError(f"Duplicate nid {nid}.")
        # Always copy: the columns may alias caller arrays or be read-only
        # broadcast views, and chunks owned by the subgraph are edited in place.
        cols = {k: np.array(v, dtype=np.int64) for k, v in cols.items()}
        chunks = self.new.setdefault(ntuple, [])
        chunks.append(Chunk(np.array(nids, dtype=np.int64), cols))
        chunks.sort(key=lambda c: c.first)
        return True

    def commit(self):
        nodes_d, index_d = self.cow.commit()
        tables = dict(self.tables)
        # Apply row updates and removals to their chunks:
        touched = {} # id(chunk) -> (ntuple, original chunk, target chunk)
        def target(nid):
            ntuple, chunk, i = _locate(tables, nid) or _locate(self.new, nid)
            entry = touched.get(id(chunk))
            if entry is None:
                entry = (ntuple, chunk, chunk.copy() if chunk.shared else chunk)
                touched[id(chunk)] = entry
            return entry[0], entry[2], i
        for nid, values in self.upd.items():
            ntuple, c, i = target(nid)
            for f, v in zip(ntuple._array_layout, values):
                c.cols[f.name][i] = v
        for nid in self.dead:
            ntuple, c, i = target(nid)
            if c.live is None:
                c.live = np.ones(len(c.nids), dtype=bool)
            c.live[i] = False
        # Rebuild the chunk tuples of touched types (copies replace
        # originals, empty chunks are dropped) and add new chunks:
        replaced = {id(orig): tgt for ntuple, orig, tgt in touched.values()}
        for ntuple in {e[0] for e in touched.values()} | self.new.keys():
            chunks = [replaced.get(id(c), c) for c in tables.get(ntuple, ())]
            chunks += [replaced.get(id(c), c) for c in self.new.get(ntuple, ())]
            chunks = sorted((c for c in chunks if c.count() > 0), key=lambda c: c.first)
            if chunks:
                tables[ntuple] = tuple(chunks)
            else:
                tables.pop(ntuple, None)
        return ArrayNodes(nodes_d, tables), ArrayIndex(index_d, tables)

    def abort(self):
        pass # overlays and new chunks are simply discarded

class CowArraysBackend(StorageBackend):
    name = 'cow-arrays'

    def empty_state(self):
        d = CowNodes()
        d.shared = False
        tables = {}
        return ArrayNodes(d, tables), ArrayIndex(_new_cow_index(), tables), range(0, 2**32)

    def begin(self, subgraph):
        return CowArraysTxn(subgraph)

    def _share_state(self, subgraph):
        nodes = subgraph.nodes
        index = subgraph.index
        nodes.d.shared = True
        index.d.shared = True
        for chunks in nodes.tables.values():
            for c in chunks:
                c.shared = True
        return nodes, index, subgraph.nid_alloc

    freeze_state = _share_state
    thaw_state = _share_state
    fork_state = _share_state

    def row_nids(self, subgraph):
        return dict.keys(subgraph.nodes.d)

    def arrays(self, subgraph, ntype, partial=False):
        nodes = subgraph.nodes
        ntuple = ntype.Tuple
        fields = ntuple._array_layout
        if fields is None:
            raise TypeError(f"{ntype.__name__} is not arrayable.")
        chunks = nodes.tables.get(ntuple, ())
        # Rows in the dict part (inserted row by row):
        d_nids = []
        d_rows = []
        for nid in dict.get(subgraph.index.d, ntuple, ()):
            values = row_values(fields, dict.__getitem__(nodes.d, nid))
            if values is None:
                if partial:
                    continue
                raise ValueError(f"{ntype.__name__} nid={nid} has None values"
                    " and cannot be represented as array.")
            d_nids.append(nid)
            d_rows.append(values)
        if len(chunks) == 1 and not d_nids and chunks[0].live is None \
                and not subgraph.mutable:
            # Views of a shared chunk: never modified again.
            c = chunks[0]
            ret = {'nid': c.nids} | c.cols
            ret = {k: v.view() for k, v in ret.items()}
            for a in ret.values():
                a.flags.writeable = False
            return ret
        parts = [{'nid': c.live_nids()} | c.live_cols() for c in chunks]
        if d_nids:
            parts.append(columns(fields, d_nids, d_rows))
        if not parts:
            return columns(fields, [], [])
        nid = np.concatenate([p['nid'] for p in parts])
        order = np.argsort(nid, kind='stable')
        ret = {'nid': nid[order]}
        for f in fields:
            ret[f.name] = np.concatenate([p[f.name] for p in parts])[order]
        for a in ret.values():
            a.flags.writeable = False
        return ret

    # Value semantics: equal content gives equal hash/equality regardless of
    # whether array-representable rows are stored in chunks or in the dict
    # part. Array-representable rows of arrayable types are compared as
    # arrays, all other nodes as items.

    def _decompose(self, subgraph):
        d = subgraph.nodes.d
        plain = {nid: node for nid, node in dict.items(d)
            if node._array_layout is None or row_values(node._array_layout, node) is None}
        ntuples = set(subgraph.nodes.tables) | {node.__class__ for node in dict.values(d)
            if node._array_layout is not None}
        arrays = {}
        for ntuple in sorted(ntuples, key=lambda t: t.__qualname__):
            cols = self.arrays(subgraph, ntuple._cursor_type, partial=True)
            if len(cols['nid']):
                arrays[ntuple] = cols
        return plain, arrays

    def content_hash(self, subgraph):
        plain, arrays = self._decompose(subgraph)
        digests = []
        for ntuple, cols in arrays.items():
            h = hashlib.blake2b(digest_size=16)
            for name in ['nid'] + [f.name for f in ntuple._array_layout]:
                h.update(np.ascontiguousarray(cols[name]).tobytes())
            digests.append((ntuple, h.digest()))
        return hash((frozenset(plain.items()), tuple(digests), subgraph.nid_alloc))

    def content_equal(self, a, b):
        if b.backend is not self:
            return super().content_equal(a, b)
        if a.nid_alloc != b.nid_alloc:
            return False
        plain_a, arrays_a = self._decompose(a)
        plain_b, arrays_b = self._decompose(b)
        if plain_a != plain_b or arrays_a.keys() != arrays_b.keys():
            return False
        return all(np.array_equal(arrays_a[t][k], arrays_b[t][k])
            for t in arrays_a for k in arrays_a[t])
