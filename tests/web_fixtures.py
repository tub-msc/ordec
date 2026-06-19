# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Pytest fixture for web UI testing with Selenium.

The web fixture rebuilds web/dist automatically (via build_web_dist) when it is
missing or older than the frontend sources, so a manual 'npm run build' is no
longer required before running web tests.
"""

import threading
import queue
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass

import pytest
from ordec import server

try:
    from selenium import webdriver
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.wait import WebDriverWait
    from selenium.webdriver.common.by import By
    _selenium_available = True
except ImportError:
    _selenium_available = False


WEB_DIR = (Path(__file__).parent.parent / 'web').resolve()


def _newest_mtime(paths):
    """Return the newest mtime among the given files/directories (0 if none exist)."""
    newest = 0.0
    for path in paths:
        if not path.exists():
            continue
        if path.is_dir():
            for sub in path.rglob('*'):
                newest = max(newest, sub.stat().st_mtime)
        else:
            newest = max(newest, path.stat().st_mtime)
    return newest


def build_web_dist():
    """
    Ensure web/dist is built and up-to-date before serving it in tests.

    Rebuilds via 'npm run build' only when web/dist is missing or older than
    the frontend sources, so a Python-only iteration loop pays no build cost.
    'npm ci' is intentionally not run here: dependencies are assumed installed
    (see CLAUDE.md). If a build is needed but npm is unavailable, this raises
    rather than skipping, so the missing toolchain is reported as a failure.
    """
    dist_dir = WEB_DIR / 'dist'
    src_mtime = _newest_mtime([
        WEB_DIR / 'src',
        WEB_DIR / 'package.json',
        WEB_DIR / 'vite.config.js',
    ])
    dist_mtime = _newest_mtime([dist_dir])
    if dist_dir.is_dir() and dist_mtime >= src_mtime:
        return  # web/dist is fresh, nothing to do.

    if shutil.which('npm') is None:
        raise RuntimeError(
            "web/dist is missing or stale and 'npm' was not found on PATH. "
            "Install Node.js/npm, or run 'npm run build' in web/ manually.")

    subprocess.check_call(['npm', '--prefix', str(WEB_DIR), 'run', 'build'])


@dataclass
class WebInfo:
    url: str
    key: server.ServerKey
    driver: object

    def resize_viewport(self, w=800, h=600):
        w_overhead = self.driver.execute_script("return window.outerWidth - window.innerWidth;")
        h_overhead = self.driver.execute_script("return window.outerHeight - window.innerHeight;")
        self.driver.set_window_size(w+w_overhead, h+h_overhead)

    def authenticate(self, hmac_bypass: bool=False):
        self.driver.get(self.url)
        self.driver.execute_script("""
            window.localStorage.setItem('ordecAuth', arguments[0]);
            window.localStorage.setItem('ordecHmacBypass', arguments[1]?"true":"");
        """, self.key.token(), hmac_bypass)

    def wait_for_ready(self):
        WebDriverWait(self.driver, 10).until(
            EC.text_to_be_present_in_element((By.ID, 'status'), "ready"))

    def run_and_wait_for_reload(self, script):
        """
        Run script (which triggers a same-URL reload, e.g. via
        window.location.reload()), then wait until the page has actually
        reloaded and reached the 'ready' state.

        Without the staleness wait, wait_for_ready() can race: the old page
        already shows 'ready', so it returns before the reload happened.
        """
        old_html = self.driver.find_element(By.TAG_NAME, 'html')
        self.driver.execute_script(script)
        WebDriverWait(self.driver, 10).until(EC.staleness_of(old_html))
        self.wait_for_ready()

    def navigate(self, path_with_fragment):
        """
        Navigate to a URL, forcing full reload even if only fragment changed.

        Fragment-only changes don't reload the page in browsers, so we first
        navigate to about:blank to ensure the next navigation is a full load.
        """
        self.driver.get("about:blank")
        self.driver.get(self.url + path_with_fragment)


@pytest.fixture(scope="session")
def web():
    """
    Pytest fixture that starts an ORDeC server and Selenium webdriver.
    Shared across all web tests in the session.

    Tests using this fixture will be automatically skipped if Selenium
    is not installed.
    """
    if not _selenium_available:
        pytest.skip("Selenium not installed")

    build_web_dist()

    webdriver_options = webdriver.ChromeOptions()
    webdriver_options.add_argument("--no-sandbox")
    webdriver_options.add_argument("--headless=new")
    webdriver_options.add_argument("--force-device-scale-factor=1")

    key = server.ServerKey()
    port = 8102
    web_dist_path = (Path(__file__).parent.parent/'web'/'dist').resolve()
    tar = server.anonymous_tar(web_dist_path)
    static_handler = server.StaticHandler(tar)
    startup_queue = queue.Queue(maxsize=1)

    t = threading.Thread(target=server.server_thread,
        args=('127.0.0.1', port, static_handler, key, startup_queue), daemon=True)
    t.start()
    startup_error = startup_queue.get()
    if startup_error is not None:
        raise RuntimeError(f"Test server failed to start: {startup_error}")

    with webdriver.Chrome(options=webdriver_options) as driver:
        web = WebInfo(
            f"http://127.0.0.1:{port}/",
            key=key,
            driver=driver,
        )
        web.authenticate(hmac_bypass=True)
        yield web
