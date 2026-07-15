# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
WebSocket protocol tests for progress reporting and view-generation
cancellation (no browser; raw websockets.sync client against the server).
"""

import json
import queue
import socket
import threading
import pytest
from websockets.sync.client import connect

from ordec import server
from ordec.jobrunner import ThreadedJobRunner

TEST_SRC = '''
from ordec.core import *
import time

@generate_func
def quick():
    return "quick result"

@generate_func
def slow():
    for i in range(100):
        progress(f"step {i}", i/100)
        time.sleep(0.05)
    return "slow result"

@generate_func
def infinite_loop():
    while True:
        pass

@generate_func
def with_progress():
    for i in range(4):
        progress(f"phase {i}", i/4)
    return "progressed"
'''

@pytest.fixture(scope="module")
def proto_server():
    """Backend-only server on a free port with fast cancel timeouts."""
    jobrunner = ThreadedJobRunner(4)
    jobrunner.cooperative_timeout = 0.3
    jobrunner.async_exc_timeout = 2.0

    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]

    key = server.ServerKey()
    startup_queue = queue.Queue(maxsize=1)
    t = threading.Thread(target=server.server_thread,
        args=('127.0.0.1', port, server.StaticHandler(), key, startup_queue),
        kwargs={'jobrunner': jobrunner}, daemon=True)
    t.start()
    startup_error = startup_queue.get()
    if startup_error is not None:
        raise RuntimeError(f"Test server failed to start: {startup_error}")
    yield f"ws://127.0.0.1:{port}/api/websocket", key

class Client:
    """Minimal protocol client: authenticates, sends the test source,
    consumes the viewlist, then exposes send/recv of JSON messages."""
    def __init__(self, url, key, src=TEST_SRC):
        self.sock = connect(url)
        self.send({'msg': 'source', 'srctype': 'python', 'src': src,
            'auth': key.token()})
        viewlist = self.recv()
        assert viewlist['msg'] == 'viewlist'
        self.views = {v['name'] for v in viewlist['views']}

    def send(self, payload):
        self.sock.send(json.dumps(payload))

    def recv(self, timeout=30):
        return json.loads(self.sock.recv(timeout=timeout))

    def getview(self, view, req):
        self.send({'msg': 'getview', 'view': view, 'req': req})

    def cancelview(self, req):
        self.send({'msg': 'cancelview', 'req': req})

    def recv_until_terminal(self, req):
        """Collects viewprogress messages until the terminal 'view'
        message for req arrives; returns (progress_msgs, terminal)."""
        progress_msgs = []
        while True:
            msg = self.recv()
            if msg['msg'] == 'viewprogress' and msg['req'] == req:
                progress_msgs.append(msg)
            elif msg['msg'] == 'view' and msg['req'] == req:
                return progress_msgs, msg

    def close(self):
        self.sock.close()

def test_getview_and_progress(proto_server):
    url, key = proto_server
    c = Client(url, key)
    try:
        assert 'with_progress()' in c.views
        c.getview('with_progress()', req=1)
        progress_msgs, terminal = c.recv_until_terminal(1)
        assert terminal['view'] == 'with_progress()'
        assert 'type' in terminal and 'exception' not in terminal
        # Throttling may drop some updates, but status changes always pass.
        statuses = [m['status'] for m in progress_msgs]
        assert statuses == [f"phase {i}" for i in range(4)]
        assert progress_msgs[-1]['fraction'] == pytest.approx(0.75)
    finally:
        c.close()

def test_concurrent_requests(proto_server):
    url, key = proto_server
    c = Client(url, key)
    try:
        c.getview('slow()', req=10)
        c.getview('quick()', req=11)
        # quick must finish while slow is still running (parallel jobs).
        msgs, terminal_quick = c.recv_until_terminal(11)
        assert terminal_quick['type'] == 'report'
        c.cancelview(10)
        _, terminal_slow = c.recv_until_terminal(10)
        assert terminal_slow.get('cancelled') is True
    finally:
        c.close()

def test_cancel_slow_view(proto_server):
    url, key = proto_server
    c = Client(url, key)
    try:
        c.getview('slow()', req=20)
        # Wait for at least one progress message, then cancel.
        msg = c.recv()
        assert msg['msg'] == 'viewprogress' and msg['req'] == 20
        c.cancelview(20)
        _, terminal = c.recv_until_terminal(20)
        assert terminal.get('cancelled') is True
        assert 'type' not in terminal and 'exception' not in terminal
        # The connection must remain healthy afterwards.
        c.getview('quick()', req=21)
        _, terminal = c.recv_until_terminal(21)
        assert 'type' in terminal
    finally:
        c.close()

def test_cancel_infinite_loop(proto_server):
    url, key = proto_server
    c = Client(url, key)
    try:
        c.getview('infinite_loop()', req=30)
        c.cancelview(30)  # exercises the async-exc rung
        _, terminal = c.recv_until_terminal(30)
        assert terminal.get('cancelled') is True
    finally:
        c.close()
    # A NEW connection (fresh build_cells taking import_lock as writer)
    # proves the cancelled job released the import lock.
    c2 = Client(url, key)
    try:
        c2.getview('quick()', req=31)
        _, terminal = c2.recv_until_terminal(31)
        assert 'type' in terminal
    finally:
        c2.close()

def test_cancel_unknown_req_ignored(proto_server):
    url, key = proto_server
    c = Client(url, key)
    try:
        c.cancelview(999)  # must not kill the connection
        c.getview('quick()', req=40)
        _, terminal = c.recv_until_terminal(40)
        assert 'type' in terminal
    finally:
        c.close()
