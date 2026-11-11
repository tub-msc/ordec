# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Vite dev server for editable installations (``pip install -e``), which lack
the packaged frontend (webdist.tar). ``ordec`` then runs Vite from the
checkout's web/ directory as child process and forwards static file
requests to it (see StaticHandler in ordec.server). The browser thus uses
the usual URL of ``ordec``, and frontend changes show up instantly (hot
module replacement); only the HMR websocket connects to Vite directly.
"""

import os
import socket
import subprocess
import threading
import time
from pathlib import Path

web_path = Path(__file__).resolve().parents[2] / 'web'

def available():
    """True if ordec runs from a checkout that contains web/."""
    return (web_path / 'package.json').is_file()

class Vite:
    def __init__(self, hostname: str, base_path: str):
        """
        Args:
            hostname: hostname to listen on; the browser connects the HMR
                websocket to it directly, so it is the hostname of ordec.
            base_path: URL path prefix of ordec, which Vite serves under, too.
        """
        self.exe = web_path / 'node_modules' / '.bin' / 'vite'
        self.hostname = hostname
        self.base_path = base_path
        # A free port picked by the OS. Vite runs with --strictPort, as its
        # own fallback to another port would leave ordec without its port.
        with socket.socket() as s:
            s.bind((hostname, 0))
            self.port = s.getsockname()[1]
        self.proc = None
        self.stopping = False

    def start(self):
        """Start Vite and return once it accepts connections."""
        self.proc = subprocess.Popen([self.exe,
            '--host', self.hostname, '--port', str(self.port), '--strictPort',
            '--base', self.base_path,
            # Vite's banner shows its own URL, which is not the one to open,
            # and info messages log every hot update: only warnings and errors
            # (e.g. syntax errors in frontend code) are of interest here.
            '--logLevel', 'warn', '--clearScreen', 'false'],
            cwd=web_path, env=os.environ | {'ORDEC_HMR_PORT': str(self.port)},
            # stdin: Vite exits when ordec closes it (see vite.config.js).
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
                socket.create_connection((self.hostname, self.port), timeout=1).close()
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
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
