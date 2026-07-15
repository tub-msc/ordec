# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Cross-backend correctness gates:

1. check_equivalence(): every workload at smoke scale must produce an
   identical canonical checksum under every backend.
2. differential_fuzz(): a seeded random operation sequence (insert /
   update / remove / freeze / thaw / copy / aborted txn) applied
   independently under a candidate and a reference backend, with the full
   state compared after every operation. This is the main defense against
   subtle state bugs (e.g. delta-chain shadowing).
"""

from ordec.core import ordb
from ordec.core.ordb import OrdbException

from .prng import Lcg
from .checksum import checksum_result, checksum_subgraph
from .schema import ChainRoot, CNode
from .workloads import WORKLOADS

REFERENCE_BACKEND = 'pyrsistent-patricia'

def check_equivalence(backends=None, scale='smoke', seed=1, verbose=False):
    """All backends must produce identical workload results."""
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
                f"Backend mismatch in workload {wl.name!r}: {checksums}")
        if verbose:
            print(f"{wl.name:<24} {next(iter(checksums.values()))} OK")

class _AbortFuzz(Exception):
    pass

class _FuzzDriver:
    """One backend's state during the differential fuzz."""

    def __init__(self, backend_name, seed):
        self.backend = ordb.get_backend(backend_name)
        self.rng = Lcg(seed)
        with ordb.use_backend(backend_name):
            self.cur = ChainRoot().subgraph
        self.snaps = []

    def _pick_nid(self):
        nids = sorted(self.cur.nodes)
        if len(nids) < 2:
            return None
        return nids[1 + self.rng.randint(len(nids) - 1)] # never the root

    def step(self, opcode):
        rng = self.rng
        if opcode < 50: # insert
            self.cur.add(CNode(tag=rng.randint(16), val=rng.randint(1 << 20)))
        elif opcode < 75: # update
            nid = self._pick_nid()
            if nid is not None:
                self.cur.update(
                    self.cur.nodes[nid].set(val=rng.randint(1 << 20)), nid)
        elif opcode < 85: # remove
            nid = self._pick_nid()
            if nid is not None:
                self.cur.remove_nid(nid)
        elif opcode < 90: # freeze (non-consuming)
            self.snaps.append(self.cur.freeze())
        elif opcode < 94: # thaw a random snapshot
            if self.snaps:
                self.cur = self.snaps[rng.randint(len(self.snaps))].thaw()
        elif opcode < 97: # fork the mutable
            self.cur = self.cur.copy()
        elif opcode < 99: # txn isolation: subgraph pristine until commit
            before = checksum_subgraph(self.cur)
            with self.cur.updater() as u:
                for _ in range(3):
                    u.add_single(CNode(tag=rng.randint(16),
                        val=rng.randint(1 << 20)), u.nid_generate())
                # The open transaction must not be visible on the subgraph:
                if checksum_subgraph(self.cur) != before:
                    raise AssertionError(
                        f"{self.backend.name}: open txn leaked into subgraph")
            if checksum_subgraph(self.cur) == before:
                raise AssertionError(
                    f"{self.backend.name}: committed txn not applied")
        else: # aborted transaction (must leave state untouched)
            before = checksum_subgraph(self.cur)
            try:
                with self.cur.updater() as u:
                    for _ in range(3):
                        u.add_single(CNode(tag=rng.randint(16),
                            val=rng.randint(1 << 20)), u.nid_generate())
                    raise _AbortFuzz()
            except _AbortFuzz:
                pass
            after = checksum_subgraph(self.cur)
            if before != after:
                raise AssertionError(
                    f"{self.backend.name}: aborted txn changed state")

    def state(self):
        """Comparable state fingerprint: current graph + index queries +
        all snapshots."""
        idx = tuple(
            tuple(self.cur.all(CNode.tag_idx.query(tag), wrap_cursor=False))
            for tag in range(16))
        return (checksum_subgraph(self.cur), len(self.cur.nodes),
            self.cur.nid_alloc.start, idx,
            tuple(checksum_subgraph(s) for s in self.snaps))

def differential_fuzz(candidate, reference=REFERENCE_BACKEND, ops=300,
        seed=1):
    """Apply the same op sequence under both backends, comparing after
    every op."""
    a = _FuzzDriver(reference, seed)
    b = _FuzzDriver(candidate, seed)
    script_rng = Lcg(seed ^ 0x5eed)
    for i in range(ops):
        opcode = script_rng.randint(100)
        a.step(opcode)
        b.step(opcode)
        sa, sb = a.state(), b.state()
        if sa != sb:
            raise AssertionError(
                f"Differential fuzz diverged at op {i} (opcode {opcode}):"
                f" {reference} vs {candidate}:\n{sa}\n{sb}")

def differential_fuzz_all(ops=300, seed=1):
    for backend in ordb.available_backends():
        if backend != REFERENCE_BACKEND:
            differential_fuzz(backend, ops=ops, seed=seed)

if __name__ == '__main__':
    check_equivalence(verbose=True)
    differential_fuzz_all()
    print("differential fuzz: OK")
