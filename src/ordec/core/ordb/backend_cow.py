# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Copy-on-write storage backend: plain dicts and list/set buckets like the
fullcopy backend, but freeze/thaw/fork are O(1): they mark the mapping
objects as shared and hand out the same objects.

Transactions never mutate the subgraph's mappings while open (isolation
contract): all changes accumulate in a txn-private overlay (node dict with
deletion markers; per-key bucket copies made on first touch). commit()
collapses the overlay into the base mappings -- copying the top-level dict
first if it is shared with a snapshot. Bucket objects carried over from a
shared dict stay shared and are tracked in the index's foreign_keys set;
they are never mutated in place, only replaced by owned copies.

Cost profile: O(touched nodes + touched buckets) per transaction, O(1)
lifecycle transitions, O(n) top-level copy on the first commit after a
snapshot. abort() discards the overlay -- free.
"""

from collections.abc import Mapping

import bisect

from .backend import StorageBackend, StorageTxn, BucketKind
from .backend_fullcopy import GuardedDict, SnapshotIndexDict

_ABSENT = object()
_DELETED = object()

class CowNodes(GuardedDict):
    __slots__ = ('shared',)

class CowIndex(SnapshotIndexDict):
    __slots__ = ('shared', 'foreign_keys')

def _new_cow_index():
    index = CowIndex()
    index.shared = False
    index.foreign_keys = set()
    return index

class OverlayNodes(Mapping):
    """Read view merging the txn overlay over the base nodes dict."""
    __slots__ = ('_overlay', '_base', '_txn')

    def __init__(self, overlay, base, txn):
        self._overlay = overlay
        self._base = base
        self._txn = txn

    def __getitem__(self, nid):
        v = self._overlay.get(nid, _ABSENT)
        if v is _DELETED:
            raise KeyError(nid)
        if v is not _ABSENT:
            return v
        return self._base[nid]

    def __contains__(self, nid):
        v = self._overlay.get(nid, _ABSENT)
        if v is not _ABSENT:
            return v is not _DELETED
        return nid in self._base

    def __iter__(self):
        overlay = self._overlay
        for nid, v in overlay.items():
            if v is not _DELETED:
                yield nid
        for nid in self._base:
            if nid not in overlay:
                yield nid

    def __len__(self):
        return self._txn._size

class OverlayIndex(Mapping):
    """Read view merging the txn's bucket overlay over the base index."""
    __slots__ = ('_overlay', '_base')

    def __init__(self, overlay, base):
        self._overlay = overlay
        self._base = base

    def __getitem__(self, key):
        bucket = self._overlay.get(key)
        if bucket is _DELETED:
            raise KeyError(key)
        if bucket is not None:
            return list(bucket)
        return self._base[key] # snapshots via CowIndex.__getitem__

    def __contains__(self, key):
        bucket = self._overlay.get(key)
        if bucket is not None:
            return bucket is not _DELETED
        return key in self._base

    def __iter__(self):
        overlay = self._overlay
        for key, bucket in overlay.items():
            if bucket is not _DELETED:
                yield key
        for key in self._base:
            if key not in overlay:
                yield key

    def __len__(self):
        return sum(1 for _ in self)

class CowTxn(StorageTxn):
    __slots__ = ('nodes', 'index', '_base_nodes', '_base_index', '_onodes',
        '_obuckets', '_size')

    def __init__(self, subgraph):
        self._base_nodes = subgraph.nodes
        self._base_index = subgraph.index
        self._onodes = {} # nid -> NodeTuple or _DELETED
        self._obuckets = {} # key -> owned bucket copy or _DELETED
        self._size = len(self._base_nodes)
        self.nodes = OverlayNodes(self._onodes, self._base_nodes, self)
        self.index = OverlayIndex(self._obuckets, self._base_index)

    def node_set(self, nid, node):
        prev = self._onodes.get(nid, _ABSENT)
        if prev is _DELETED or \
                (prev is _ABSENT and nid not in self._base_nodes):
            self._size += 1
        self._onodes[nid] = node

    def node_remove(self, nid):
        if nid not in self.nodes:
            raise KeyError(nid)
        self._onodes[nid] = _DELETED
        self._size -= 1

    def _bucket_for_write(self, key, create_kind=None):
        bucket = self._obuckets.get(key)
        if bucket is None or bucket is _DELETED:
            base_bucket = dict.get(self._base_index, key) \
                if bucket is not _DELETED else None
            if base_bucket is not None:
                bucket = base_bucket.copy()
            elif create_kind is not None:
                bucket = set() if create_kind == BucketKind.SET else []
            else:
                raise KeyError(key)
            self._obuckets[key] = bucket
        return bucket

    def bucket_add(self, key, value, kind):
        bucket = self._bucket_for_write(key, create_kind=kind)
        if kind == BucketKind.SET:
            bucket.add(value)
        else:
            bisect.insort(bucket, value)

    def bucket_add_sorted(self, key, value, sortval, sortval_of):
        bucket = self._bucket_for_write(key, create_kind=BucketKind.SORTED)
        insert_at = bisect.bisect_left(bucket, sortval, key=sortval_of)
        bucket.insert(insert_at, value)

    def bucket_remove(self, key, value, kind):
        bucket = self._bucket_for_write(key)
        bucket.remove(value) # KeyError (set) / ValueError (list) if absent
        if not bucket:
            self._obuckets[key] = _DELETED

    def commit(self):
        base_nodes = self._base_nodes
        if base_nodes.shared:
            nodes = CowNodes(base_nodes)
            nodes.shared = False
        else:
            nodes = base_nodes
        # nodes is a GuardedDict: mutate via unbound dict.* calls, batching
        # the updates through one C-level dict.update.
        upds = {}
        for nid, v in self._onodes.items():
            if v is _DELETED:
                dict.pop(nodes, nid, None) # may be overlay-born, already absent
            else:
                upds[nid] = v
        dict.update(nodes, upds)

        base_index = self._base_index
        if base_index.shared:
            index = _new_cow_index()
            dict.update(index, base_index) # bucket objects stay shared
            index.foreign_keys = set(dict.keys(index))
        else:
            index = base_index
        foreign = index.foreign_keys
        for key, bucket in self._obuckets.items():
            if bucket is _DELETED:
                dict.pop(index, key, None)
            else:
                dict.__setitem__(index, key, bucket) # owned copy
            foreign.discard(key)
        return nodes, index

    def abort(self):
        pass # the overlay is simply discarded

class CowBackend(StorageBackend):
    name = 'cow'

    def empty_state(self):
        nodes = CowNodes()
        nodes.shared = False
        return nodes, _new_cow_index(), range(0, 2**32)

    def begin(self, subgraph):
        return CowTxn(subgraph)

    def _share_state(self, subgraph):
        nodes = subgraph.nodes
        index = subgraph.index
        nodes.shared = True
        index.shared = True
        return nodes, index, subgraph.nid_alloc

    freeze_state = _share_state
    thaw_state = _share_state
    fork_state = _share_state
