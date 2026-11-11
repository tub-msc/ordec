# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Vite dev server behind ordec, as in editable installations (ordec.vite).
"""

import http.client
import queue
import threading
import pytest

from ordec import server, vite

@pytest.mark.web
def test_vite_behind_server():
    if not vite.available():
        pytest.skip("not run from a checkout with web/")
    dev_server = vite.Vite('127.0.0.1', '/pre/')
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

        def get(path):
            conn = http.client.HTTPConnection('127.0.0.1', port)
            conn.request('GET', path)
            resp = conn.getresponse()
            return resp.status, resp.read()

        # Served by Vite under the base path, with its HMR client.
        status, body = get('/pre/app.html')
        assert status == 200
        assert b'/pre/@vite/client' in body
        # api/ stays with ordec, also where ordec has no handler.
        assert get('/pre/api/token')[0] == 404
    finally:
        dev_server.stop()
