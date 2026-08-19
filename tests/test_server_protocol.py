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

@viewgen_noctx
def quick():
    return "quick result"

@viewgen_noctx
def slow():
    for i in range(100):
        progress(f"step {i}", i/100)
        time.sleep(0.05)
    return "slow result"

@viewgen_noctx
def infinite_loop():
    while True:
        pass

@viewgen_noctx
def with_progress():
    for i in range(4):
        progress(f"phase {i}", i/4)
    return "progressed"

@viewgen_noctx
def sym():
    from ordec.lib import Res
    return Res(r=100).symbol

@viewgen_noctx
def failing():
    raise ValueError("boom")
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
    def __init__(self, url, key, src=TEST_SRC, srctype='python',
            expect_exception=False):
        self.sock = connect(url)
        self.send({'msg': 'source', 'srctype': srctype, 'src': src,
            'auth': key.token()})
        first = self.recv()
        if expect_exception:
            assert first['msg'] == 'exception'
            self.exception = first['exception']
            self.views = set()
        else:
            assert first['msg'] == 'viewlist'
            self.views = {v['name'] for v in first['views']}

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

def test_view_wire_hash(proto_server):
    """Subgraph views carry a stable wire hash on the terminal message."""
    url, key = proto_server
    c = Client(url, key)
    try:
        c.getview('sym()', req=50)
        _, terminal1 = c.recv_until_terminal(50)
        c.getview('sym()', req=51)
        _, terminal2 = c.recv_until_terminal(51)
        assert len(terminal1['wire_hash']) == 64
        int(terminal1['wire_hash'], 16)
        assert terminal1['wire_hash'] == terminal2['wire_hash']
    finally:
        c.close()

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

def test_build_exception_structured(proto_server):
    """Module-level errors arrive as structured tracebacks (see server.py
    format_user_exception): frames locating the editor line, plus a
    plain-text fallback."""
    url, key = proto_server
    c = Client(url, key, src="x = 1\ny = 1/0\n", expect_exception=True)
    try:
        exc = c.exception
        assert exc['etype'] == 'ZeroDivisionError'
        assert 'division' in exc['message']
        frame = exc['frames'][-1]
        assert frame['filename'] == '<webeditor>'
        assert frame['lineno'] == 2
        assert frame['line'] == 'y = 1/0'
        assert exc['text'].startswith('Traceback')
    finally:
        c.close()

def test_build_syntax_error_pos(proto_server):
    """Syntax errors (Python and ORD alike) carry a structured position
    so the frontend can annotate the editor."""
    url, key = proto_server
    c = Client(url, key, src="def broken(:\n", expect_exception=True)
    try:
        assert c.exception['etype'] == 'SyntaxError'
        assert c.exception['pos']['filename'] == '<webeditor>'
        assert c.exception['pos']['lineno'] == 1
    finally:
        c.close()
    c = Client(url, key, src="cell Foo:\n    x = = 1\n", srctype='ord',
        expect_exception=True)
    try:
        exc = c.exception
        assert exc['etype'] == 'SyntaxError'
        assert exc['pos'] == {'filename': '<webeditor>', 'lineno': 2,
            'col': 9, 'end_col': None, 'line': '    x = = 1'}
    finally:
        c.close()

def test_view_exception_structured(proto_server):
    """View-generation errors carry the structured traceback on the
    terminal message."""
    url, key = proto_server
    c = Client(url, key)
    try:
        c.getview('failing()', req=60)
        _, terminal = c.recv_until_terminal(60)
        exc = terminal['exception']
        assert exc['etype'] == 'ValueError'
        assert exc['message'] == 'boom'
        assert any(f['filename'] == '<webeditor>' and f['name'] == 'failing'
            for f in exc['frames'])
    finally:
        c.close()

def test_auth_error_structured(proto_server):
    """Operational errors (here: a bad auth token) use the same structured
    dict shape as tracebacks (see server.py message_exception), so the
    frontend never has to special-case plain strings."""
    url, key = proto_server
    sock = connect(url)
    try:
        sock.send(json.dumps({'msg': 'source', 'srctype': 'python',
            'src': 'x = 1\n', 'auth': 'wrong-token'}))
        msg = json.loads(sock.recv(timeout=30))
        assert msg['msg'] == 'exception'
        exc = msg['exception']
        assert isinstance(exc, dict)
        assert exc['frames'] == [] and 'pos' not in exc
        assert 'auth token' in exc['message']
    finally:
        sock.close()
