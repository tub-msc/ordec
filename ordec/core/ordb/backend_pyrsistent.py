# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Reference storage backend: pyrsistent persistent maps for nodes and index,
with either PatriciaSet or pvector NID buckets (the two variants that were
previously toggled by the module-level INDEX_PATRICIA switch in ordb.py).

freeze/thaw/fork are O(1) reference handovers; transaction abort is free
because operations never mutate shared structures.
"""

import bisect

from pyrsistent import pmap, pvector, pset

from .backend import StorageBackend, StorageTxn, BucketKind
from .patricia import PatriciaSet

_EMPTY_PMAP = pmap()
_EMPTY_PATRICIA = PatriciaSet()

class PyrsistentTxn(StorageTxn):
    __slots__ = ('nodes', 'index', '_patricia')

    def __init__(self, subgraph, patricia):
        self.nodes = subgraph.nodes
        self.index = subgraph.index
        self._patricia = patricia

    def node_set(self, nid, node):
        self.nodes = self.nodes.set(nid, node)

    def node_remove(self, nid):
        self.nodes = self.nodes.remove(nid)

    def bucket_add(self, key, value, kind):
        values = self.index.get(key)
        if kind == BucketKind.SET:
            values = (pset() if values is None else values).add(value)
        elif self._patricia:
            values = (_EMPTY_PATRICIA if values is None else values).add(value)
        else:
            if values is None:
                values = pvector()
            insert_at = bisect.bisect_left(values, value)
            if insert_at == len(values):
                values = values.append(value)
            else:
                # TODO: This is probably inefficient with pyrsistent, but maybe we can make this case rare.
                values = values[:insert_at].append(value) + values[insert_at:]
        self.index = self.index.set(key, values)

    def bucket_add_sorted(self, key, value, sortval, sortval_of):
        values = self.index.get(key)
        if values is None:
            values = pvector()
        insert_at = bisect.bisect_left(values, sortval, key=sortval_of)
        if insert_at == len(values):
            values = values.append(value)
        else:
            values = values[:insert_at].append(value) + values[insert_at:]
        self.index = self.index.set(key, values)

    def bucket_remove(self, key, value, kind):
        values = self.index[key].remove(value)
        if len(values) > 0:
            self.index = self.index.set(key, values)
        else:
            self.index = self.index.remove(key)

    def commit(self):
        return self.nodes, self.index

    def abort(self):
        pass # Persistent structures: nothing was shared, nothing to undo.

class PyrsistentBackend(StorageBackend):
    def __init__(self, patricia: bool):
        self._patricia = patricia
        self.name = 'pyrsistent-patricia' if patricia else 'pyrsistent-pvector'

    def empty_state(self):
        return _EMPTY_PMAP, _EMPTY_PMAP, range(0, 2**32)

    def begin(self, subgraph):
        return PyrsistentTxn(subgraph, self._patricia)

    # freeze/thaw/fork all hand over the same persistent references (O(1)).

    def freeze_state(self, subgraph):
        return subgraph.nodes, subgraph.index, subgraph.nid_alloc

    def thaw_state(self, subgraph):
        return subgraph.nodes, subgraph.index, subgraph.nid_alloc

    def fork_state(self, subgraph):
        return subgraph.nodes, subgraph.index, subgraph.nid_alloc

    def content_hash(self, subgraph):
        # PMap.__hash__ hashes frozenset(items), so this matches the generic
        # StorageBackend.content_hash but avoids rebuilding the frozenset in
        # Python.
        return hash((subgraph.nodes, subgraph.nid_alloc))

    def content_equal(self, a, b):
        return (a.nodes == b.nodes) and (a.nid_alloc == b.nid_alloc)
