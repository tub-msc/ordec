# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Pytest fixture for web UI testing with Selenium.

Important: You have to run 'npm run build' in web/ before running web tests.
"""

import threading
import queue
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
