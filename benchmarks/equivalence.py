# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Correctness gates for the storage engines:

1. check_equivalence(): every workload at the tiny scale must produce an
   identical canonical checksum under every storage engine. With one
   engine, compare the printed checksums across commits instead (see
   "Testing changes to the core" in docs/dev/ordb_core.rst).
2. differential_fuzz(): a seeded random operation sequence (insert, update,
   type change, remove, freeze, thaw, copy, aborted and nested
   transactions) applied to every engine in lockstep. After every
   operation, every engine must hold exactly the nodes of a pure-Python
   reference model (a dict of nid to NodeTuple per subgraph, updated
   alongside each operation), the engines must agree, every index query
   must equal a brute-force scan of the nodes, and every snapshot must
   still have the checksum and the nodes it had when it was taken.
"""

from ordec.core import ordb
from ordec.core.ordb import OrdbException

from .prng import Lcg
from .checksum import checksum_result, checksum_subgraph
import numpy as np

from .schema import ChainRoot, CNode, ANode, RNode
from .workloads import WORKLOADS

def check_equivalence(backends=None, scale='tiny', seed=1, verbose=False):
    """All engines must produce identical workload results."""
    if backends is None:
        backends = ordb.available_backends()
    for wl in WORKLOADS.values():
        params = wl.params[scale]
        checksums = {}
        for backend in backends:
            with ordb.use_backend(backend):
                run = wl.fn(dict(params), seed)
            checksums[backend] = checksum_result(run.final)
        if len(set(checksums.values())) != 1:
            raise AssertionError(
                f"Engine mismatch in workload {wl.name!r}: {checksums}")
        if verbose:
            print(f"{wl.name:<24} {next(iter(checksums.values()))} OK")

class _Abort(Exception):
    pass

_TAGS = 8
_KEYS = 24

class _FuzzDriver:
    """One engine's state during the differential fuzz."""

    def __init__(self, backend_name, seed):
        self.name = backend_name
        self.rng = Lcg(seed)
        with ordb.use_backend(backend_name):
            self.cur = ChainRoot().subgraph
        # Reference model of self.cur: nid -> NodeTuple. A transaction works
        # on a copy and replaces the model on commit, so model dicts are
        # never changed in place and snapshots can share them.
        self.model = {nid: self.cur.row(nid) for nid in self.cur.nids()}
        self.snaps = [] # (frozen subgraph, checksum when taken, model)

    def _pick(self, ntuple=None):
        nids = self.cur.nids(ntuple) if ntuple else self.cur.nids()[1:]
        if not nids:
            return None
        return nids[self.rng.randint(len(nids))]

    def _random_change(self, u, m):
        """One random change inside the open updater u, recorded in the
        model m of the transaction."""
        rng = self.rng
        sg = self.cur
        op = rng.randint(6)
        if op == 0:
            node = CNode(tag=rng.randint(_TAGS), val=rng.randint(1000))
            m[u.add_single(node, u.nid_generate())] = node
        elif op == 1:
            vals = [rng.randint(1000) for _ in range(1 + rng.randint(4))]
            other = rng.randint(8)
            nids = u.insert_array(ANode, val=np.array(vals), other=other)
            for nid, val in zip(nids, vals):
                m[nid] = ANode(val=val, other=other)
        elif op == 2:
            target = self._pick(CNode.Tuple)
            if target is not None:
                node = RNode(target=target, key=rng.randint(_KEYS))
                m[u.add_single(node, u.nid_generate())] = node
        elif op == 3: # update, including None values and key changes
            nid = self._pick()
            if nid is not None:
                node = sg.row(nid)
                if isinstance(node, CNode.Tuple):
                    node = node.set(tag=rng.randint(_TAGS))
                elif isinstance(node, RNode.Tuple):
                    node = node.set(key=None if rng.randint(4) == 0 else rng.randint(_KEYS))
                else:
                    node = node.set(val=None if rng.randint(4) == 0 else rng.randint(1000))
                u.update(node, nid)
                m[nid] = node
        elif op == 4: # type change under the same nid
            nid = self._pick(ANode.Tuple)
            if nid is not None:
                node = CNode(tag=rng.randint(_TAGS), val=1)
                u.update(node, nid)
                m[nid] = node
        else:
            nid = self._pick()
            if nid is not None:
                u.remove_nid(nid)
                del m[nid]

    def step(self, opcode):
        rng = self.rng
        if opcode < 55: # committed transaction with 1-3 changes
            n = 1 + rng.randint(3)
            m = dict(self.model)
            try:
                with self.cur.updater() as u:
                    for _ in range(n):
                        self._random_change(u, m)
            except OrdbException as e:
                return type(e).__name__ # rejected: same outcome everywhere
            self.model = m
        elif opcode < 65: # aborted transaction: state untouched
            before = checksum_subgraph(self.cur)
            m = dict(self.model)
            try:
                with self.cur.updater() as u:
                    for _ in range(1 + rng.randint(4)):
                        self._random_change(u, m)
                    raise _Abort()
            except (_Abort, OrdbException):
                pass
            if checksum_subgraph(self.cur) != before:
                raise AssertionError(f"{self.name}: aborted txn changed state")
        elif opcode < 72: # nested: inner aborts, outer commits
            m = dict(self.model)
            try:
                with self.cur.updater() as outer:
                    self._random_change(outer, m)
                    inner_before = checksum_subgraph(self.cur)
                    m_inner = dict(m)
                    try:
                        with self.cur.updater() as inner:
                            self._random_change(inner, m_inner)
                            self._random_change(inner, m_inner)
                            raise _Abort()
                    except (_Abort, OrdbException):
                        pass
                    if checksum_subgraph(self.cur) != inner_before:
                        raise AssertionError(f"{self.name}: inner abort leaked")
            except OrdbException as e:
                return type(e).__name__
            self.model = m
        elif opcode < 82: # freeze (non-consuming)
            snap = self.cur.freeze()
            self.snaps.append((snap, checksum_subgraph(snap), self.model))
        elif opcode < 88: # thaw a random snapshot
            if self.snaps:
                snap, _, self.model = self.snaps[rng.randint(len(self.snaps))]
                self.cur = snap.thaw()
        elif opcode < 93: # fork the mutable
            self.cur = self.cur.copy()
        elif opcode < 96: # compacted copy of a snapshot
            if self.snaps:
                snap = self.snaps[rng.randint(len(self.snaps))][0]
                if snap.compact() != snap:
                    raise AssertionError(f"{self.name}: compact() changed content")
        else: # big transaction: exercises index runs and table compaction
            m = dict(self.model)
            with self.cur.updater() as u:
                for _ in range(70):
                    node = CNode(tag=rng.randint(_TAGS), val=2)
                    m[u.add_single(node, u.nid_generate())] = node
            self.model = m
            m = dict(self.model)
            with self.cur.updater() as u:
                for nid in self.cur.nids(CNode.Tuple)[::2]:
                    if not self.cur.query(RNode.target_idx, nid):
                        u.remove_nid(nid)
                        del m[nid]
            self.model = m
        return None

    def validate(self):
        """Nodes against the model, index queries against brute force,
        snapshots unchanged."""
        sg = self.cur
        rows = _rows(sg)
        if _typed(rows) != _typed(self.model):
            raise AssertionError(f"{self.name}: nodes differ from the model")
        for ntuple in (CNode.Tuple, ANode.Tuple, RNode.Tuple):
            expect = [nid for nid, node in rows.items() if type(node) is ntuple]
            if sg.nids(ntuple) != expect:
                raise AssertionError(f"{self.name}: all({ntuple.__name__}) wrong")
        for tag in range(_TAGS):
            expect = [nid for nid, node in rows.items()
                if isinstance(node, CNode.Tuple) and node.tag == tag]
            if sg.query(CNode.tag_idx, tag) != expect:
                raise AssertionError(f"{self.name}: tag index wrong for {tag}")
        for key in range(_KEYS):
            expect = [nid for nid, node in rows.items()
                if isinstance(node, RNode.Tuple) and node.key == key]
            if sg.query(RNode.key_idx, key) != expect:
                raise AssertionError(f"{self.name}: key index wrong for {key}")
        for target in sg.nids(CNode.Tuple):
            expect = sorted((node.key, nid) for nid, node in rows.items()
                if isinstance(node, RNode.Tuple) and node.target == target
                and node.key is not None)
            got = [nid for nid in sg.query(RNode.target_idx, target)
                if rows[nid].key is not None]
            if got != [nid for _, nid in expect]:
                raise AssertionError(f"{self.name}: target index wrong for {target}")
        for snap, checksum, model in self.snaps:
            if checksum_subgraph(snap) != checksum or _typed(_rows(snap)) != _typed(model):
                raise AssertionError(f"{self.name}: snapshot changed")

    def state(self):
        return (checksum_subgraph(self.cur), self.cur.count(),
            self.cur.nid_alloc.start, tuple(c for _, c, _ in self.snaps))

def _rows(sg):
    return {nid: sg.row(nid) for nid in sg.nids()}

def _typed(rows):
    """NodeTuples compare as plain tuples: pair them with their type."""
    return {nid: (type(node), node) for nid, node in rows.items()}

def differential_fuzz(backends=None, ops=300, seed=1):
    """Apply the same op sequence under all engines, comparing after every
    op."""
    if backends is None:
        backends = ordb.available_backends()
    drivers = [_FuzzDriver(b, seed) for b in backends]
    script_rng = Lcg(seed ^ 0x5eed)
    for i in range(ops):
        opcode = script_rng.randint(100)
        outcomes = [d.step(opcode) for d in drivers]
        for d in drivers:
            d.validate()
        states = [d.state() for d in drivers]
        if len(set(outcomes)) != 1 or len(set(states)) != 1:
            raise AssertionError(
                f"Differential fuzz diverged at op {i} (opcode {opcode}):"
                f" {list(zip(backends, outcomes, states))}")

def differential_fuzz_all(ops=300, seeds=(1, 2, 3)):
    for seed in seeds:
        differential_fuzz(ops=ops, seed=seed)

if __name__ == '__main__':
    check_equivalence(verbose=True)
    differential_fuzz_all()
    print("differential fuzz: OK")
