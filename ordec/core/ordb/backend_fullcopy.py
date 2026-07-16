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

_ABSENT = object()

def _reject_mutation(self, *args, **kwargs):
    raise TypeError(f"{type(self).__name__} rejects in-place mutation;"
        " subgraph state changes only through a StorageTxn")

class GuardedDict(dict):
    """dict that rejects all public in-place mutation, so that subgraph
    state can only change through a StorageTxn -- matching the guarantee
    the pyrsistent backend gets from pmap. Backend-internal code mutates
    via unbound dict.* calls (dict.__setitem__(d, ...), dict.pop(d, ...)).

    Escape hatches deliberately left open, on par with the reachable
    private attributes of pure-Python pyrsistent: the unbound dict.* calls
    themselves, d.__init__(other), and the C-level copy/merge fast paths
    (dict(d), Subclass(d), d | other -- these also keep freeze/fork copies
    cheap and must stay native, so __iter__/keys are not overridden).
    copy.copy() and pickle of these dicts raise via __setitem__; nothing
    in-tree uses either (Subgraph defines its own __copy__)."""
    __slots__ = ()

    __setitem__ = _reject_mutation
    __delitem__ = _reject_mutation
    __ior__ = _reject_mutation # inherited dict.__ior__ mutates at C level
    update = _reject_mutation
    pop = _reject_mutation
    popitem = _reject_mutation
    clear = _reject_mutation
    setdefault = _reject_mutation

class SnapshotIndexDict(GuardedDict):
    """Index dict whose public read paths ([], get, items, values, copy)
    return snapshots (fresh lists) of the stored buckets, detached from
    future mutation, so callers can iterate a bucket while mutating the
    subgraph and can never corrupt buckets shared between snapshots. A
    list (not tuple) so it compares equal to plain lists, like
    pyrsistent's pvector does. Internal backend code accesses raw buckets
    via dict.__getitem__ / dict.get."""
    __slots__ = ()

    def __getitem__(self, key):
        return list(dict.__getitem__(self, key))

    def get(self, key, default=None):
        bucket = dict.get(self, key, _ABSENT)
        if bucket is _ABSENT:
            return default
        return list(bucket)

    def items(self):
        return [(key, list(bucket)) for key, bucket in dict.items(self)]

    def values(self):
        return [list(bucket) for bucket in dict.values(self)]

    def copy(self):
        return dict(self.items())

def copy_index(index, cls=SnapshotIndexDict):
    new = cls()
    for key, bucket in dict.items(index):
        dict.__setitem__(new, key, bucket.copy())
    return new

class FullCopyTxn(StorageTxn):
    __slots__ = ('nodes', 'index')

    def __init__(self, subgraph):
        self.nodes = GuardedDict(subgraph.nodes)
        self.index = copy_index(subgraph.index)

    def node_set(self, nid, node):
        dict.__setitem__(self.nodes, nid, node)

    def node_remove(self, nid):
        dict.__delitem__(self.nodes, nid)

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
        return GuardedDict(), SnapshotIndexDict(), range(0, 2**32)

    def begin(self, subgraph):
        return FullCopyTxn(subgraph)

    def _copy_state(self, subgraph):
        return (GuardedDict(subgraph.nodes), copy_index(subgraph.index),
            subgraph.nid_alloc)

    freeze_state = _copy_state
    thaw_state = _copy_state
    fork_state = _copy_state
