# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Storage backend interface for ORDB subgraphs.

A subgraph's state is the triple (nodes, index, nid_alloc):

- nodes: Mapping[int, NodeTuple] -- the one true node store,
- index: Mapping[Hashable, bucket] -- combined index; keys are IndexKey
  namedtuples, NodeTuple subclasses (NType index) or raw ints (LocalRef
  target nids),
- nid_alloc: range -- nids available for allocation.

What the two mapping objects *are* is backend-private. ordb.py and all
other consumers use only the read-only Mapping protocol on them, plus the
following contract:

- ``index[key]`` returns an *immutable snapshot* of the bucket at access
  time. Callers may iterate it while mutating the subgraph (e.g. removing
  exactly the nodes it lists, as ordec.layout.helpers.expand_rects does).
  The same holds for every other public read path that exposes buckets
  (``get``, ``items``, ``values``, ``copy``): snapshots or immutable
  bucket objects, never mutable state shared with the subgraph.
- Buckets of BucketKind.NID iterate in ascending order, SORTED buckets in
  sort-value order (ties in insertion order), SET buckets unordered.
- ``key in index`` must reflect whether the key has a non-empty bucket.
- The mapping objects must reject in-place mutation through their public
  API (raise TypeError, or return a new object without mutating, as
  pyrsistent does). Subgraphs hand out these objects via ``.nodes`` /
  ``.index``, frozen subgraphs cache their content hash, and backends may
  share the objects across freeze/thaw/fork -- a caller that could mutate
  them in place would silently corrupt every subgraph in the sharing
  group.

All mutation goes through a StorageTxn obtained from
:meth:`StorageBackend.begin`; lifecycle transitions (freeze/thaw/fork) and
value equality/hashing of frozen subgraphs are backend hooks as well.
"""

import enum
from abc import ABC, abstractmethod
from contextlib import contextmanager
import os

class BucketKind(enum.IntEnum):
    """Semantic kind of an index bucket, passed with every bucket operation
    so that backends can pick a suitable representation per kind."""
    NID = 0     #: set of non-negative ints (nids), iterated ascending
    SORTED = 1  #: nids ordered by an externally supplied sort value
    SET = 2     #: unordered set of arbitrary hashable values

class StorageBackend(ABC):
    """
    One instance per backend variant, shared by all subgraphs using it.
    Backends are stateless with respect to individual subgraphs; per-subgraph
    state lives in the (nodes, index, nid_alloc) triple and, for mutable
    subgraphs, is rebound via Subgraph.mutate().
    """
    name = None

    @abstractmethod
    def empty_state(self):
        """Return (nodes, index, nid_alloc) for a fresh MutableSubgraph."""

    @abstractmethod
    def begin(self, subgraph) -> 'StorageTxn':
        """Start a transaction capturing the subgraph's current state."""

    @abstractmethod
    def freeze_state(self, subgraph):
        """
        Return (nodes, index, nid_alloc) for a FrozenSubgraph capturing the
        current state of the given MutableSubgraph. May rebind the source's
        state (via subgraph.mutate) if freezing requires it (delta chains).
        """

    @abstractmethod
    def thaw_state(self, subgraph):
        """Return (nodes, index, nid_alloc) for a new MutableSubgraph
        derived from the given FrozenSubgraph."""

    @abstractmethod
    def fork_state(self, subgraph):
        """Return (nodes, index, nid_alloc) for a MutableSubgraph copy of
        the given MutableSubgraph. May rebind the source's state."""

    def compact_state(self, subgraph):
        """Flatten internal delta structure; identity for flat backends."""
        return subgraph.nodes, subgraph.index, subgraph.nid_alloc

    # Value semantics of FrozenSubgraph (nodes + nid_alloc; index is excluded
    # as it is equal by construction). The generic implementations work
    # across backends; backends may override with faster equivalents that
    # MUST hash/compare identically to the generic ones within one backend.

    def content_hash(self, subgraph):
        return hash((frozenset(subgraph.nodes.items()), subgraph.nid_alloc))

    def content_equal(self, a, b):
        if a.nid_alloc != b.nid_alloc:
            return False
        a_nodes = a.nodes
        b_nodes = b.nodes
        if len(a_nodes) != len(b_nodes):
            return False
        for nid, node in a_nodes.items():
            if b_nodes.get(nid, None) != node:
                return False
        return True

class StorageTxn(ABC):
    """
    Uncommitted mutation handle for one SubgraphUpdater transaction.

    The ``nodes`` and ``index`` attributes must reflect all operations
    immediately: they back mid-transaction queries and the deferred
    constraint checks that run before commit. ``commit()`` returns the new
    (nodes, index) pair for Subgraph.mutate(); ``abort()`` must leave the
    target subgraph completely untouched.

    ISOLATION: the target subgraph's own state (subgraph.nodes /
    subgraph.index) must remain at the pre-transaction snapshot for as long
    as the transaction is open -- only txn.nodes/txn.index expose
    uncommitted changes. Real ORDeC code depends on this: e.g.
    ordec.schematic.helpers.resolve_instances queries the subgraph while
    its updater is open and must see pre-transaction state.
    """
    __slots__ = ()

    @abstractmethod
    def node_set(self, nid, node):
        """Insert or overwrite the NodeTuple stored at nid."""

    @abstractmethod
    def node_remove(self, nid):
        """Remove the node at nid. Raises KeyError if absent."""

    @abstractmethod
    def bucket_add(self, key, value, kind):
        """Add value to the bucket at key, creating the bucket if needed."""

    @abstractmethod
    def bucket_remove(self, key, value, kind):
        """Remove value from the bucket at key; drop the bucket when it
        becomes empty. Raises KeyError/ValueError if absent."""

    @abstractmethod
    def bucket_add_sorted(self, key, value, sortval, sortval_of):
        """
        Add value (a nid) to the SORTED bucket at key, positioned by
        sortval. sortval_of(other_nid) resolves the sort value of nids
        already in the bucket (via this txn's node state).
        """

    @abstractmethod
    def commit(self):
        """Finalize and return (nodes, index) for Subgraph.mutate()."""

    @abstractmethod
    def abort(self):
        """Discard the transaction, leaving the target untouched."""


# -- backend registry ------------------------------------------------------
#
# New subgraphs use the process-wide default backend, selected by (in order
# of precedence): an explicit MutableSubgraph(backend=...) / use_backend(),
# the ORDEC_ORDB_BACKEND environment variable, or BUILTIN_DEFAULT. The
# backends themselves are registered in this package's __init__, which is
# what keeps them free to import this module.

BUILTIN_DEFAULT = 'pyrsistent-patricia'

_registry = {}
_default = None

def register_backend(backend: StorageBackend):
    _registry[backend.name] = backend

def get_backend(name: str) -> StorageBackend:
    try:
        return _registry[name]
    except KeyError:
        raise ValueError(
            f"Unknown ORDB storage backend {name!r}."
            f" Available: {', '.join(sorted(_registry))}"
        ) from None

def available_backends() -> list[str]:
    return sorted(_registry)

def default_backend() -> StorageBackend:
    """Backend used for newly created subgraphs (resolved lazily so that
    ORDEC_ORDB_BACKEND can name backends registered after import)."""
    global _default
    if _default is None:
        _default = get_backend(os.environ.get('ORDEC_ORDB_BACKEND', BUILTIN_DEFAULT))
    return _default

@contextmanager
def use_backend(name: str):
    """Temporarily change the default backend for new subgraphs. Existing
    subgraphs keep the backend they were created with."""
    global _default
    prev = _default
    _default = get_backend(name)
    try:
        yield _default
    finally:
        _default = prev
