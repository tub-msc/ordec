# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Vite dev server behind ordec, as in editable installations (ordec.vite).
"""

import http.client
import json
import queue
import re
import threading
import pytest
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed

from ordec import server, vite

@pytest.mark.web
def test_vite_behind_server():
    if not vite.available():
        pytest.skip("not run from a checkout with web/")
    dev_server = vite.Vite('/pre/')
    dev_server.start()
    try:
        static_handler = server.StaticHandler(base_path='/pre/',
            vite=dev_server)
        startup_queue = queue.Queue(maxsize=1)
        server_queue = queue.Queue(maxsize=1)
        threading.Thread(target=server.server_thread,
            args=('127.0.0.1', 0, static_handler, server.ServerKey(),
                startup_queue, server_queue), daemon=True).start()
        assert startup_queue.get() is None
        port = server_queue.get().socket.getsockname()[1]

        def get(path, headers={}):
            conn = http.client.HTTPConnection('127.0.0.1', port)
            conn.request('GET', path, headers=headers)
            resp = conn.getresponse()
            return resp.status, resp.read()

        # Served by Vite under the base path, with its HMR client.
        status, body = get('/pre/app.html')
        assert status == 200
        assert b'/pre/@vite/client' in body
        # api/ stays with ordec, also where ordec has no handler.
        assert get('/pre/api/token')[0] == 404
        # Other sites reach the entry pages only (not e.g. __open-in-editor).
        cross_site = {'Sec-Fetch-Site': 'cross-site'}
        assert get('/pre/app.html', cross_site)[0] == 200
        assert get('/pre/__open-in-editor?file=x', cross_site)[0] == 403

        # The HMR websocket is relayed to Vite.
        token = re.search(rb'const wsToken = "([^"]+)"', get('/pre/@vite/client')[1])[1]
        with connect(f'ws://127.0.0.1:{port}/pre/?token={token.decode()}',
                subprotocols=['vite-hmr']) as ws:
            assert json.loads(ws.recv(timeout=10)) == {'type': 'connected'}
        # Cross-site pages lack the token: Vite rejects them (Origin is
        # relayed). The relay accepts the browser side first, so the
        # rejection shows as a close.
        with connect(f'ws://127.0.0.1:{port}/pre/', subprotocols=['vite-hmr'],
                origin='http://evil.example') as ws:
            with pytest.raises(ConnectionClosed):
                ws.recv(timeout=10)
    finally:
        dev_server.stop()
