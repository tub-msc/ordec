# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

_EMPTY = None # The shared empty set, bound below once the class exists.

class PatriciaSet:
    """
    Persistent (immutable, structure-sharing) set of non-negative integers,
    implemented as a big-endian Patricia trie (Okasaki & Gill, "Fast
    Mergeable Integer Maps"; same structure as Haskell's Data.IntSet).

    Iteration yields elements in ascending order by construction, with no
    sort step. add() and remove() are O(min(W, log n)) where W is the bit
    width of the largest element; both return a new set sharing structure
    with the original. The tree shape is canonical (history-independent):
    two PatriciaSets holding the same elements are structurally identical.
    PatriciaSet() always returns the same shared empty instance.

    Internal tree representation: None is the empty tree, a plain int is a
    leaf, and a branch is a tuple (prefix, mask, left, right). mask is the
    single branching bit; all elements in the branch agree with prefix on
    the bits above mask, left holds those with the mask bit cleared, right
    those with it set.
    """
    __slots__ = ('_tree', '_size')

    def __new__(cls, iterable=()):
        # The empty set is a shared singleton, like pyrsistent's pmap()/pset().
        # Instances are immutable, so callers never need distinct empty ones.
        # An empty iterable leaves __init__ a no-op, so it is safe to let it
        # run on the singleton. Iterators are always truthy and take the
        # regular path, even when they turn out to be empty.
        if cls is PatriciaSet and not iterable and _EMPTY is not None:
            return _EMPTY
        return super().__new__(cls)

    def __init__(self, iterable=()):
        self._tree = None
        self._size = 0
        for k in iterable:
            s = self.add(k)
            self._tree, self._size = s._tree, s._size

    @classmethod
    def _make(cls, tree, size):
        # object.__new__, not cls.__new__: the latter hands back the shared
        # empty singleton, whose slots must never be overwritten here.
        ret = object.__new__(cls)
        ret._tree = tree
        ret._size = size
        return ret

    @staticmethod
    def _join(k, kt, p, pt):
        # Combine subtrees kt (all elements agreeing with k) and pt (all
        # agreeing with p) that disagree above their own branching bits.
        m = 1 << ((k ^ p).bit_length() - 1)
        prefix = k & ~((m << 1) - 1)
        if k & m:
            return (prefix, m, pt, kt)
        else:
            return (prefix, m, kt, pt)

    @classmethod
    def _ins(cls, t, k):
        if t is None:
            return k
        if isinstance(t, int):
            if t == k:
                return t
            return cls._join(k, k, t, t)
        p, m, l, r = t
        if k & ~((m << 1) - 1) != p:
            return cls._join(k, k, p, t)
        if k & m:
            return (p, m, l, cls._ins(r, k))
        else:
            return (p, m, cls._ins(l, k), r)

    @classmethod
    def _del(cls, t, k):
        # Returns the new tree; raises KeyError if k is not in t.
        if t is None:
            raise KeyError(k)
        if isinstance(t, int):
            if t == k:
                return None
            raise KeyError(k)
        p, m, l, r = t
        if k & ~((m << 1) - 1) != p:
            raise KeyError(k)
        if k & m:
            r = cls._del(r, k)
            if r is None:
                return l
        else:
            l = cls._del(l, k)
            if l is None:
                return r
        return (p, m, l, r)

    def add(self, k: int) -> 'PatriciaSet':
        if not isinstance(k, int) or k < 0:
            raise ValueError("PatriciaSet elements must be non-negative ints.")
        if k in self:
            return self
        return self._make(self._ins(self._tree, k), self._size + 1)

    def remove(self, k: int) -> 'PatriciaSet':
        return self._make(self._del(self._tree, k), self._size - 1)

    def __contains__(self, k):
        t = self._tree
        while True:
            if t is None:
                return False
            if isinstance(t, int):
                return t == k
            p, m, l, r = t
            if k & ~((m << 1) - 1) != p:
                return False
            t = r if k & m else l

    def __iter__(self):
        if self._tree is None:
            return
        stack = [self._tree]
        while stack:
            t = stack.pop()
            if isinstance(t, int):
                yield t
            else:
                stack.append(t[3])
                stack.append(t[2])

    def __len__(self):
        return self._size

    def __eq__(self, other):
        # Canonical tree shape: equal element sets <=> equal trees.
        if not isinstance(other, PatriciaSet):
            return NotImplemented
        return self._tree == other._tree

    def __hash__(self):
        return hash((PatriciaSet, self._tree))

    def __repr__(self):
        return f"PatriciaSet({list(self)!r})"

_EMPTY = PatriciaSet()
