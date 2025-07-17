# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from dataclasses import dataclass
import importlib.resources
import io

from ordec import ws_server

try:
    from selenium import webdriver
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.by import By
    from PIL import Image, ImageChops
    from SSIM_PIL import compare_ssim
except ImportError:
    skip_webtests = True
else:
    skip_webtests = False

    webdriver_options = webdriver.ChromeOptions()
    webdriver_options.add_argument("--headless=new")
    webdriver_options.add_argument("--force-device-scale-factor=1")
    # The following sets the window size, not the viewport size (see resize_viewport below):
    # webdriver_options.add_argument("--window-size=1280,720")


examples = [
    "nand2",
    "voltagedivider_py",
    "blank",
    "voltagedivider",
    "diffpair",
]

refdir = importlib.resources.files("tests.web_ref")

@dataclass
class WebserverInfo:
    url: str

@pytest.fixture(scope="session", autouse=True)
def webserver():
    static_handler = ws_server.StaticHandlerDir(Path('web/dist')) # TODO: Make this cleaner.
    t = threading.Thread(target=ws_server.server_thread,
        args=('localhost', 8100, static_handler), daemon=True)
    t.start()
    time.sleep(1) # Delay for server startup
    yield WebserverInfo("http://localhost:8100/")
    # Server will stop when pytest exits.

@pytest.mark.web
@pytest.mark.skipif(skip_webtests, reason="Prerequesites for web tests not installed.")
def test_index(webserver):
    with webdriver.Chrome(options=webdriver_options) as driver:
        driver.get(webserver.url + '')
        app_html_link_queries = set()
        for a in driver.find_elements(By.TAG_NAME, 'a'):
            href =urlparse(a.get_attribute('href'))
            if href.path == '/app.html':
                app_html_link_queries.add(href.query)

    # Check that we link to each expected example.
    assert app_html_link_queries == {f'example={example}' for example in examples}

def resize_viewport(driver, w, h):
    w_overhead = driver.execute_script("return window.outerWidth - window.innerWidth;")
    h_overhead = driver.execute_script("return window.outerHeight - window.innerHeight;")
    driver.set_window_size(w+w_overhead, h+h_overhead)

@pytest.mark.web
@pytest.mark.skipif(skip_webtests, reason="Prerequesites for web tests not installed.")
@pytest.mark.parametrize('example', examples)
def test_screenshot_example(webserver, tmp_path, example):
    with webdriver.Chrome(options=webdriver_options) as driver:
        resize_viewport(driver, 800, 600)
        driver.get(webserver.url + f'app.html?example={example}')
        
        # Hide ace-editor cursor (to always get the same screenshot):
        driver.execute_script(
            'document.styleSheets[0].insertRule(".ace_cursor { opacity: 0 !important; }", 0 )')

        # TODO: Delay to wait for result to show. We should do this somehow using JavaScript.
        time.sleep(2)
        
        result_png = driver.get_screenshot_as_png()
        (tmp_path / f"{example}.png").write_bytes(result_png) # Write output to tmp_path for user.
        #driver.save_screenshot('screenshot.png')

    result_image = Image.open(io.BytesIO(result_png))

    ref_image = Image.open(refdir / f'{example}.png')
    # I am not sure whether SSIM is really appropriate for this, but it seems fine so far.
    ssim = compare_ssim(result_image, ref_image, GPU=False)
    print(f"ssim={ssim}")
    assert ssim > 0.99
