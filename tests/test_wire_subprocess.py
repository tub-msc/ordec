# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Demo: wire exchange with a cold subprocess over pipes.

The main process assembles a current-mirror schematic (instances, nets,
conns — everything except wiring), transfers it to a freshly spawned
Python subprocess via the want/have exchange over stdin/stdout pipes, and
receives back the auto_wire()d schematic. This exercises the full wire
stack end to end without any RPC machinery: Merkle deps (symbols travel
as separate blocks), the receiver store (symbols are not retransmitted on
the return trip), LiveRef export (the schematic's cell decodes to an
opaque FarRef in the subprocess, relays verbatim, and resolves back to
the identical live object at home).

This file doubles as the worker: run as a script, it acts as the
subprocess side (receive, auto_wire, send back).
"""

import struct
import subprocess
import sys

import cbor2

from ordec.core import *
from ordec.core.wire import ExportTable, WireSender, WireReceiver


# Message framing: 4-byte little-endian length prefix, CBOR [kind, payload].
# Wire blocks/wants are plain bytes values, so CBOR carries them natively.

def read_exact(f, n):
    buf = b''
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            raise EOFError("peer closed the pipe")
        buf += chunk
    return buf


def send_msg(f, kind, payload):
    data = cbor2.dumps([kind, payload])
    f.write(struct.pack("<I", len(data)))
    f.write(data)
    f.flush()


def recv_msg(f, expect):
    n, = struct.unpack("<I", read_exact(f, 4))
    kind, payload = cbor2.loads(read_exact(f, n))
    if kind != expect:
        raise ValueError(f"expected {expect!r} message, got {kind!r}")
    return payload


def send_subgraph(fin, fout, root, ept):
    """Drive a WireSender against the peer's receiver (lock-step)."""
    sender = WireSender(root, ept)
    send_msg(fout, "blocks", [list(sender.root_block())])
    while True:
        want = [bytes(h) for h in recv_msg(fin, "want")]
        if not want:
            return
        send_msg(fout, "blocks", [list(b) for b in sender.serve(want)])


def recv_subgraph(fin, fout, ept, store):
    """Drive a WireReceiver against the peer's sender (lock-step)."""
    receiver = WireReceiver(ept, store)
    while True:
        blocks = [(bytes(h), bytes(d)) for h, d in recv_msg(fin, "blocks")]
        want = receiver.receive(blocks)
        send_msg(fout, "want", want)
        if not want:
            return receiver.result


class MirrorDemo(Cell):
    pass


def build_unwired_mirror():
    """The currentmirror.ord schematic, stopped right before auto_wire."""
    from ordec.lib.generic_mos import Nmos
    from ordec.lib import Res, Vdc, Idc, Gnd

    cell = MirrorDemo()
    s = Schematic(cell=cell)
    s.vss = Net()
    s.vdd = Net()
    s.l = Net()
    s.r = Net()
    s.n0 = SchemInstance(
        Nmos(w=R('500n')).symbol.portmap(d=s.l, g=s.l, s=s.vss, b=s.vss),
        pos=Vec2R(10, 6), orientation=D4.FlippedSouth)
    s.n1 = SchemInstance(
        Nmos(w=R('1500n')).symbol.portmap(d=s.r, g=s.l, s=s.vss, b=s.vss),
        pos=Vec2R(14, 6))
    s.gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(0, 0))
    s.isrc = SchemInstance(Idc(dc=R('10u')).symbol.portmap(p=s.vdd, n=s.l),
        pos=Vec2R(6, 12))
    s.vsrc = SchemInstance(Vdc(dc=R(5)).symbol.portmap(p=s.vdd, n=s.vss),
        pos=Vec2R(0, 9))
    s.r0 = SchemInstance(Res(r=R('10k')).symbol.portmap(p=s.vdd, n=s.r),
        pos=Vec2R(14, 12))
    return s.freeze(), cell


def wire_schematic(frozen_root):
    """The tail of SchematicViewBuilder.postprocess: auto_wire + check."""
    root = frozen_root.thaw()
    root.auto_wire()
    root.check(add_conn_points=True, add_terminal_taps=True)
    return root.freeze()


def worker():
    fin, fout = sys.stdin.buffer, sys.stdout.buffer
    ept = ExportTable()
    sch = recv_subgraph(fin, fout, ept, store={})
    send_subgraph(fin, fout, wire_schematic(sch), ept)


def test_autowire_in_subprocess():
    orig, cell = build_unwired_mirror()
    ept = ExportTable()
    proc = subprocess.Popen([sys.executable, __file__],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        send_subgraph(proc.stdout, proc.stdin, orig, ept)
        # Receiver store pre-seeded with everything this endpoint already
        # holds, so the return trip transfers only the wired schematic.
        store = dict(orig.subgraph.wire_deps(ept))
        store[orig.subgraph.wire_hash(ept)] = orig.subgraph
        back = recv_subgraph(proc.stdout, proc.stdin, ept, store)
    finally:
        proc.stdin.close()
        proc.stdout.close()
        assert proc.wait(timeout=30) == 0

    # The subprocess produced the same wiring the local router computes:
    assert back.subgraph == wire_schematic(orig).subgraph
    assert len(list(back.all(SchemWire))) > 0
    # LiveRef round trip: opaque FarRef in the subprocess, relayed
    # verbatim, resolved back to the identical live object at home.
    assert back.cell is cell
    # Symbols came from the local store, not from retransmission:
    assert back.n0.symbol.subgraph is orig.n0.symbol.subgraph


# Dual purpose: under pytest this file is the main-process side (test +
# builders); executed as a script (which is how the test spawns it), it is
# the worker side. Keeping both in one file lets them share the framing,
# the pumps, and wire_schematic(), and the spawn can never point at a
# stale worker path.
if __name__ == "__main__":
    worker()
