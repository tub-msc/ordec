# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Thread stress test of the ORDB core (see "Testing changes to the core" in
docs/dev/ordb_core.rst). Not part of the pytest suite: it is timing-based.

One writer thread, two reader threads and one intruder thread work on the
same mutable subgraph, with thread switches forced every microsecond and
index keys whose __hash__ and __eq__ run Python code (switch points inside
core operations). Expected: no crash, every rejected write says "another
thread", readers keep running (KeyError for nodes of a query result that
were removed meanwhile is expected). Run it under AddressSanitizer:

    python -m benchmarks.thread_stress --seconds 3
"""

import argparse
import sys
import threading
import time

from ordec.core.ordb import (SubgraphRoot, Node, Attr, Index, OrdbException,
    use_backend, available_backends)

class StressRoot(SubgraphRoot):
    pass

class Key:
    """Index key whose hashing and comparison run Python code."""
    __slots__ = ('v',)

    def __init__(self, v):
        self.v = v

    def __hash__(self):
        x = 0
        for i in range(20):
            x += i
        return hash(self.v)

    def __eq__(self, other):
        return isinstance(other, Key) and other.v == self.v

class StressNode(Node):
    in_subgraphs = [StressRoot]
    key = Attr(object)
    num = Attr(int)
    key_idx = Index(key)
    num_idx = Index(num)

def run(engine, seconds):
    with use_backend(engine):
        root = StressRoot()
    sg = root.subgraph
    stop = time.time() + seconds
    rejected = {'writer': 0, 'intruder': 0}

    def rejected_write(who, e):
        if 'another thread' not in str(e):
            raise e
        rejected[who] += 1

    def writer():
        i = 0
        while time.time() < stop:
            try:
                with sg.updater() as u:
                    for _ in range(20):
                        i += 1
                        u.add_single(StressNode(key=Key(i % 50), num=i), u.nid_generate())
                    nids = sg.nids(StressNode.Tuple)
                    for nid in nids[:10]:
                        u.update(sg.row(nid).set(key=Key(i % 7)), nid)
                    for nid in nids[-5:]:
                        u.remove_nid(nid)
            except OrdbException as e:
                rejected_write('writer', e)

    def reader():
        while time.time() < stop:
            try:
                for node in sg.all(StressNode):
                    node.key, node.num
                sg.query(StressNode.key_idx, Key(3))
                sg.query(StressNode.num_idx, 5)
                sg._content_hash()
                for nid in sg.nids()[:50]:
                    sg.row(nid)
            except KeyError:
                pass # a node of a query result was removed meanwhile

    def intruder():
        while time.time() < stop:
            try:
                root % StressNode(key=Key(1), num=1)
            except OrdbException as e:
                rejected_write('intruder', e)

    threads = [threading.Thread(target=f) for f in (writer, reader, reader, intruder)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"{engine}: {sg.count()} nodes, rejected writes: writer"
        f" {rejected['writer']}, intruder {rejected['intruder']}")

def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--seconds', type=float, default=3)
    args = parser.parse_args()
    sys.setswitchinterval(1e-6)
    for engine in available_backends():
        run(engine, args.seconds)

if __name__ == '__main__':
    main()
