# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Full-copy storage backend: plain dicts for nodes and index, list/set
buckets, with complete copies at every boundary -- freeze, thaw, fork AND
transaction begin. This is the deliberately naive baseline ("strawman")
for the benchmark suite: no structure sharing anywhere.

Copying at transaction begin gives the required isolation (the target
subgraph keeps its pre-transaction state until commit) and makes abort
free: the copies are simply discarded.

index[key] returns a list snapshot of the bucket, per the base contract.
"""

import bisect

from .backend import StorageBackend, StorageTxn, BucketKind

class SnapshotIndexDict(dict):
    """dict whose [] returns a snapshot (fresh list) of the stored bucket,
    detached from future mutation, so callers can iterate it while mutating
    the subgraph. A list (not tuple) so it compares equal to plain lists,
    like pyrsistent's pvector does. All other dict operations stay native;
    internal backend code accesses raw buckets via dict.__getitem__."""
    __slots__ = ()

    def __getitem__(self, key):
        return list(dict.__getitem__(self, key))

def copy_index(index, cls=SnapshotIndexDict):
    new = cls()
    for key, bucket in dict.items(index):
        dict.__setitem__(new, key, bucket.copy())
    return new

class FullCopyTxn(StorageTxn):
    __slots__ = ('nodes', 'index')

    def __init__(self, subgraph):
        self.nodes = dict(subgraph.nodes)
        self.index = copy_index(subgraph.index)

    def node_set(self, nid, node):
        self.nodes[nid] = node

    def node_remove(self, nid):
        del self.nodes[nid]

    def _bucket_for_write(self, key, create_kind=None):
        bucket = dict.get(self.index, key)
        if bucket is None and create_kind is not None:
            bucket = set() if create_kind == BucketKind.SET else []
            dict.__setitem__(self.index, key, bucket)
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
        if bucket is None:
            raise KeyError(key)
        bucket.remove(value) # KeyError (set) / ValueError (list) if absent
        if not bucket:
            dict.__delitem__(self.index, key)

    def commit(self):
        return self.nodes, self.index

    def abort(self):
        pass # the copies are simply discarded

class FullCopyBackend(StorageBackend):
    name = 'fullcopy'

    def empty_state(self):
        return {}, SnapshotIndexDict(), range(0, 2**32)

    def begin(self, subgraph):
        return FullCopyTxn(subgraph)

    def _copy_state(self, subgraph):
        return (dict(subgraph.nodes), copy_index(subgraph.index),
            subgraph.nid_alloc)

    freeze_state = _copy_state
    thaw_state = _copy_state
    fork_state = _copy_state
