# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Delta-chain storage backend: pure-Python port of the persistence model of
the Zig ORDB reimplementation (origin/zig, zig/src/subgraph.zig).

Each generation (Gen) stores only its own delta: a dict of added/modified
nodes plus tombstones for nodes removed from ancestor generations, and
per-key index deltas (added values + removed values). Reads walk the chain
newest to oldest, with newer generations shadowing older ones.

Lifecycle: thaw/fork are O(1) (fresh empty child generation); freeze seals
the mutable's current generation and hands it to the FrozenSubgraph, giving
the mutable a fresh empty child (Python freeze is non-consuming, a
deliberate divergence from Zig). compact() flattens a chain into a single
generation with identical content; auto_compact_depth makes freeze do this
automatically past a chain-depth threshold ('delta-compactN' variants).

Divergences from the Zig original: single-parent chains only (no thawMulti
/ nid offsets) and garbage collection instead of refcounting.

Transactions accumulate their changes in a private overlay generation on
top of the mutable's unsealed generation; commit() merges the overlay into
the top generation (O(transaction size)) and abort() discards it, so the
subgraph's own state stays at the pre-transaction snapshot while the
transaction is open (isolation contract). index[key] materializes the
merged bucket as a fresh list, which satisfies the snapshot contract for
free; the per-query cost is O(bucket x chain depth).
"""

import bisect
import heapq
from collections.abc import Mapping

from .backend import StorageBackend, StorageTxn, BucketKind

TOMBSTONE = object() #: marks a node removed from an ancestor generation
_ABSENT = object()

class Gen:
    __slots__ = ('parent', 'nodes', 'index', 'base_nid_end', 'size',
        'depth', 'sealed')

    def __init__(self, parent, base_nid_end):
        self.parent = parent #: Gen or None
        self.nodes = {} #: nid -> NodeTuple or TOMBSTONE
        self.index = {} #: key -> (BucketKind, added, removed-set)
        #: nids >= base_nid_end were born in this generation (removal is a
        #: hard delete); smaller nids are inherited (removal tombstones).
        self.base_nid_end = base_nid_end
        self.size = parent.size if parent is not None else 0
        self.depth = parent.depth + 1 if parent is not None else 0
        self.sealed = False

class ChainNodesView(Mapping):
    __slots__ = ('gen',)

    def __init__(self, gen):
        self.gen = gen

    def __getitem__(self, nid):
        g = self.gen
        while g is not None:
            v = g.nodes.get(nid, _ABSENT)
            if v is TOMBSTONE:
                raise KeyError(nid)
            if v is not _ABSENT:
                return v
            g = g.parent
        raise KeyError(nid)

    def __contains__(self, nid):
        g = self.gen
        while g is not None:
            v = g.nodes.get(nid, _ABSENT)
            if v is not _ABSENT:
                return v is not TOMBSTONE
            g = g.parent
        return False

    def __iter__(self):
        shadowed = set()
        g = self.gen
        while g is not None:
            for nid, v in g.nodes.items():
                if nid not in shadowed:
                    shadowed.add(nid)
                    if v is not TOMBSTONE:
                        yield nid
            g = g.parent

    def __len__(self):
        return self.gen.size

class ChainIndexView(Mapping):
    __slots__ = ('gen',)

    def __init__(self, gen):
        self.gen = gen

    def _merged(self, key):
        """(kind, merged) with removals applied; merged is a list (of nids,
        or of (sortval, nid) pairs for SORTED) or a set for SET buckets.
        Returns None if the merged bucket is empty or the key is unknown."""
        kind = None
        parts = [] # newest to oldest
        removed = set()
        g = self.gen
        while g is not None:
            delta = g.index.get(key)
            if delta is not None:
                kind, added, rem = delta[0], delta[1], delta[2]
                if added:
                    if kind == BucketKind.SORTED:
                        part = [p for p in added if p[1] not in removed]
                    else:
                        part = [v for v in added if v not in removed]
                    if part:
                        parts.append(part)
                if rem:
                    removed = removed | rem
            g = g.parent
        if not parts:
            return None
        if kind == BucketKind.SET:
            merged = set()
            for part in parts:
                merged.update(part)
        elif kind == BucketKind.SORTED:
            # heapq.merge is stable and prefers earlier iterables, so among
            # equal sort values newer generations come first -- matching the
            # bisect_left insertion order of the flat backends.
            merged = list(heapq.merge(*parts, key=lambda p: p[0]))
        else: # NID: each part ascending, merged ascending
            merged = list(heapq.merge(*parts))
        return kind, merged

    def __getitem__(self, key):
        entry = self._merged(key)
        if entry is None:
            raise KeyError(key)
        kind, merged = entry
        if kind == BucketKind.SORTED:
            return [nid for _, nid in merged]
        if kind == BucketKind.SET:
            return list(merged)
        return merged

    def __contains__(self, key):
        removed = set()
        g = self.gen
        while g is not None:
            delta = g.index.get(key)
            if delta is not None:
                kind, added, rem = delta[0], delta[1], delta[2]
                if kind == BucketKind.SORTED:
                    if any(p[1] not in removed for p in added):
                        return True
                elif any(v not in removed for v in added):
                    return True
                if rem:
                    removed = removed | rem
            g = g.parent
        return False

    def __iter__(self):
        seen = set()
        g = self.gen
        while g is not None:
            for key in g.index:
                if key not in seen:
                    seen.add(key)
                    if key in self:
                        yield key
            g = g.parent

    def __len__(self):
        return sum(1 for _ in self)

class DeltaTxn(StorageTxn):
    """Accumulates changes in a private overlay Gen whose parent is the
    mutable's unsealed top Gen; commit() merges the overlay into the top
    generation, abort() discards it."""
    __slots__ = ('nodes', 'index', '_subgraph', '_overlay')

    def __init__(self, subgraph):
        top = subgraph.nodes.gen
        if top.sealed:
            raise TypeError("Cannot mutate a sealed generation.")
        self._subgraph = subgraph
        overlay = Gen(parent=top, base_nid_end=subgraph.nid_alloc.start)
        self._overlay = overlay
        self.nodes = ChainNodesView(overlay)
        self.index = ChainIndexView(overlay)

    def node_set(self, nid, node):
        overlay = self._overlay
        if nid not in self.nodes:
            overlay.size += 1
        overlay.nodes[nid] = node

    def node_remove(self, nid):
        overlay = self._overlay
        own = overlay.nodes
        if nid >= overlay.base_nid_end:
            del own[nid] # born in this transaction: hard delete
        else:
            own[nid] = TOMBSTONE
        overlay.size -= 1

    def _delta_for_write(self, key, kind):
        index = self._overlay.index
        delta = index.get(key)
        if delta is None:
            added = set() if kind == BucketKind.SET else []
            delta = (kind, added, set())
            index[key] = delta
        return delta

    def bucket_add(self, key, value, kind):
        delta = self._delta_for_write(key, kind)
        if kind == BucketKind.SET:
            delta[1].add(value)
        else:
            bisect.insort(delta[1], value)

    def bucket_add_sorted(self, key, value, sortval, sortval_of):
        delta = self._delta_for_write(key, BucketKind.SORTED)
        added = delta[1] # list of (sortval, nid) pairs
        insert_at = bisect.bisect_left(added, sortval, key=lambda p: p[0])
        added.insert(insert_at, (sortval, value))

    def bucket_remove(self, key, value, kind):
        delta = self._delta_for_write(key, kind)
        added = delta[1]
        if kind == BucketKind.SET:
            if value in added:
                added.discard(value)
                return
        elif kind == BucketKind.SORTED:
            for i, (_, nid) in enumerate(added):
                if nid == value:
                    del added[i]
                    return
        else:
            i = bisect.bisect_left(added, value)
            if i < len(added) and added[i] == value:
                del added[i]
                return
        # Not added in this transaction: tombstone the older entry, which
        # must exist (contract: raise if the value is absent).
        if value in delta[2] or not self._in_ancestors(key, value, kind):
            if kind == BucketKind.SET:
                raise KeyError(value)
            raise ValueError(f"{value!r} not in bucket at {key!r}")
        delta[2].add(value)

    def _in_ancestors(self, key, value, kind):
        """Whether the chain below the overlay still holds value at key:
        added in some generation and not removed in a newer one. A
        generation's additions are checked before its removals: a value
        removed from an ancestor and re-added in the same generation
        appears in both and is present."""
        g = self._overlay.parent
        while g is not None:
            delta = g.index.get(key)
            if delta is not None:
                added = delta[1]
                if kind == BucketKind.SET:
                    if value in added:
                        return True
                elif kind == BucketKind.SORTED:
                    if any(nid == value for _, nid in added):
                        return True
                else:
                    i = bisect.bisect_left(added, value)
                    if i < len(added) and added[i] == value:
                        return True
                if value in delta[2]:
                    return False
            g = g.parent
        return False

    def commit(self):
        # Not the generation captured at begin: freeze()/copy() during the
        # transaction seal that one (handing it to the snapshot) and rebind
        # the subgraph to a fresh child, which is where the transaction must
        # land. The subgraph's top generation is unsealed by construction.
        top = self._subgraph.nodes.gen
        overlay = self._overlay

        for nid, v in overlay.nodes.items():
            if v is TOMBSTONE:
                if nid >= top.base_nid_end:
                    del top.nodes[nid] # born in the top gen: hard delete
                else:
                    top.nodes[nid] = TOMBSTONE
            else:
                top.nodes[nid] = v

        for key, delta in overlay.index.items():
            kind, o_added, o_removed = delta[0], delta[1], delta[2]
            t_delta = top.index.get(key)
            if t_delta is None:
                top.index[key] = delta
                continue
            _, t_added, t_removed = t_delta
            # Apply overlay removals against the top delta first:
            for value in o_removed:
                if kind == BucketKind.SET:
                    if value in t_added:
                        t_added.discard(value)
                        continue
                elif kind == BucketKind.SORTED:
                    for i, (_, nid) in enumerate(t_added):
                        if nid == value:
                            del t_added[i]
                            break
                    else:
                        t_removed.add(value)
                    continue
                else:
                    i = bisect.bisect_left(t_added, value)
                    if i < len(t_added) and t_added[i] == value:
                        del t_added[i]
                        continue
                t_removed.add(value)
            # Then merge overlay additions (overlay first: among equal sort
            # values, newer entries precede, matching bisect_left order):
            if kind == BucketKind.SET:
                t_added.update(o_added)
            elif kind == BucketKind.SORTED:
                merged = list(heapq.merge(o_added, t_added,
                    key=lambda p: p[0]))
                top.index[key] = (kind, merged, t_removed)
            else:
                merged = list(heapq.merge(o_added, t_added))
                top.index[key] = (kind, merged, t_removed)

        top.size = overlay.size
        return ChainNodesView(top), ChainIndexView(top)

    def abort(self):
        pass # the overlay is simply discarded

def _compact_gen(gen):
    """Flatten a sealed chain into a single sealed generation with
    identical merged content (mirrors Zig Frozen.compact)."""
    view = ChainNodesView(gen)
    new = Gen(parent=None, base_nid_end=0)
    new.nodes = {nid: view[nid] for nid in view}
    new.size = len(new.nodes)

    index_view = ChainIndexView(gen)
    keys = set()
    g = gen
    while g is not None:
        keys.update(g.index)
        g = g.parent
    for key in keys:
        entry = index_view._merged(key)
        if entry is None:
            continue
        kind, merged = entry
        new.index[key] = (kind, merged, set())
    new.sealed = True
    return new

class DeltaBackend(StorageBackend):
    def __init__(self, auto_compact_depth=None):
        self.auto_compact_depth = auto_compact_depth
        self.name = 'delta' if auto_compact_depth is None \
            else f'delta-compact{auto_compact_depth}'

    def empty_state(self):
        gen = Gen(parent=None, base_nid_end=0)
        return ChainNodesView(gen), ChainIndexView(gen), range(0, 2**32)

    def begin(self, subgraph):
        return DeltaTxn(subgraph)

    def _views(self, gen, nid_alloc):
        return ChainNodesView(gen), ChainIndexView(gen), nid_alloc

    def freeze_state(self, subgraph):
        gen = subgraph.nodes.gen
        alloc = subgraph.nid_alloc
        if not gen.nodes and not gen.index and gen.parent is not None:
            # Nothing changed since the last snapshot: reuse the parent
            # generation and keep the mutable's empty delta.
            return self._views(gen.parent, alloc)
        gen.sealed = True
        if self.auto_compact_depth is not None \
                and gen.depth >= self.auto_compact_depth:
            gen = _compact_gen(gen)
        child = Gen(parent=gen, base_nid_end=alloc.start)
        subgraph.mutate(*self._views(child, alloc))
        return self._views(gen, alloc)

    def thaw_state(self, subgraph):
        gen = subgraph.nodes.gen # sealed, owned by the FrozenSubgraph
        child = Gen(parent=gen, base_nid_end=subgraph.nid_alloc.start)
        return self._views(child, subgraph.nid_alloc)

    def fork_state(self, subgraph):
        gen = subgraph.nodes.gen
        alloc = subgraph.nid_alloc
        gen.sealed = True
        source_child = Gen(parent=gen, base_nid_end=alloc.start)
        subgraph.mutate(*self._views(source_child, alloc))
        copy_child = Gen(parent=gen, base_nid_end=alloc.start)
        return self._views(copy_child, alloc)

    def compact_state(self, subgraph):
        gen = subgraph.nodes.gen
        if gen.parent is None:
            return subgraph.nodes, subgraph.index, subgraph.nid_alloc
        return self._views(_compact_gen(gen), subgraph.nid_alloc)
