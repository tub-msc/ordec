# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Vite dev server for editable installations (``pip install -e``, the Nix
development shell), which lack the packaged frontend (webdist.tar). ``ordec``
then runs Vite from the checkout's web/ directory as child process
(web/dev-server.js) and forwards static file requests (see StaticHandler in
ordec.server) and the websocket connections of Vite's hot module replacement
(HMR) client to it. The browser thus talks to ordec only, and frontend changes
show up instantly.

Vite listens on a Unix domain socket in a private directory rather than on a
TCP port: no other user can take its place, and no port needs to be picked.
"""

import http.client
import os
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.sync.client import unix_connect

web_path = Path(__file__).resolve().parents[2] / 'web'

def available():
    """True if ordec runs from a checkout that contains web/."""
    return (web_path / 'package.json').is_file()

class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path, timeout):
        super().__init__('localhost', timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)

class Vite:
    # Websocket subprotocols of Vite's HMR client: 'vite-ping' probes the
    # server before the client reconnects.
    subprotocols = ('vite-hmr', 'vite-ping')

    def __init__(self, base_path: str):
        """
        Args:
            base_path: URL path prefix of ordec, which Vite serves under, too.
        """
        self.base_path = base_path
        self.proc = None
        self.stopping = False
        # Private directory (mode 0700) for the socket.
        self.socket_dir = tempfile.TemporaryDirectory(prefix='ordec-vite-')
        self.socket_path = os.path.join(self.socket_dir.name, 'vite.sock')

    def start(self):
        """Start Vite and return once it accepts connections."""
        self.proc = subprocess.Popen(
            ['node', web_path / 'dev-server.js', self.socket_path, self.base_path],
            cwd=web_path,
            # stdin: Vite exits when ordec closes it (see dev-server.js).
            # stdout: printed with prefix by print_output.
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, errors='replace',
            # Own session, so that Ctrl+C reaches ordec only, which then
            # stops Vite in order (stop).
            start_new_session=True)
        threading.Thread(target=self.print_output, daemon=True).start()

        deadline = time.monotonic() + 30
        while self.proc.poll() is None and time.monotonic() < deadline:
            try:
                with socket.socket(socket.AF_UNIX) as s:
                    s.connect(self.socket_path)
                return
            except OSError:
                time.sleep(0.1)
        self.stop()
        print("ERROR: Vite dev server did not start.")
        raise SystemExit(1)

    def print_output(self):
        # One write per line, so that lines do not mix with output of ordec.
        for line in self.proc.stdout:
            print(f"vite: {line.rstrip()}\n", end='', flush=True)
        code = self.proc.wait()
        if not self.stopping:
            print(f"vite: dev server exited with code {code}", flush=True)

    def stop(self):
        self.stopping = True
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.socket_dir.cleanup()

    def http_connection(self):
        return UnixHTTPConnection(self.socket_path, timeout=60)

    def select_subprotocol(self, connection, subprotocols):
        """For websockets' serve(): accepts Vite's subprotocols only, while
        the websocket of the ordec frontend comes without subprotocol."""
        for subprotocol in subprotocols:
            if subprotocol in self.subprotocols:
                return subprotocol
        return None

    def relay(self, websocket):
        """Relay a websocket connection of Vite's HMR client to Vite."""
        request = websocket.request
        # The Host header is passed on unchanged, so that Vite's check
        # against DNS rebinding (server.allowedHosts) still applies. Same
        # for Origin: Vite checks the HMR token (against cross-site
        # websocket hijacking) only for connections that carry an Origin.
        try:
            upstream = unix_connect(self.socket_path,
                uri=f"ws://{request.headers['Host']}{request.path}",
                origin=request.headers.get('Origin'),
                subprotocols=[websocket.subprotocol])
        except (OSError, InvalidHandshake):
            return # Closes the connection to the browser.

        def to_vite():
            try:
                for message in websocket:
                    upstream.send(message)
            except ConnectionClosed:
                pass
            upstream.close()

        thread = threading.Thread(target=to_vite, daemon=True)
        thread.start()
        try:
            for message in upstream:
                websocket.send(message)
        except ConnectionClosed:
            pass
        websocket.close()
        thread.join()
