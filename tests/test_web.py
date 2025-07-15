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
except ImportError:
    skip_webtests = True
else:
    skip_webtests = False

    webdriver_options = webdriver.ChromeOptions()
    webdriver_options.add_argument("--headless=new")
    webdriver_options.add_argument("--window-size=1280,720")

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
    driver = webdriver.Chrome(options=webdriver_options)
    driver.get(webserver.url + '')
    app_html_link_queries = set()
    for a in driver.find_elements(By.TAG_NAME, 'a'):
        href =urlparse(a.get_attribute('href'))
        if href.path == '/app.html':
            app_html_link_queries.add(href.query)

    assert app_html_link_queries == {
        'example=nand2',
        'example=voltagedivider_py',
        'example=blank',
        'example=voltagedivider',
        'example=diffpair',
    }

    driver.quit()


# TODO: The screenshot in test_screenshot_voltagedivider is not always the same.
@pytest.mark.web
@pytest.mark.skipif(skip_webtests, reason="Prerequesites for web tests not installed.")
def test_screenshot_voltagedivider(webserver, tmp_path):
    driver = webdriver.Chrome(options=webdriver_options)
    driver.get(webserver.url + 'app.html?example=voltagedivider')
    
    # Hide ace-editor cursor (to always get the same screenshot):
    driver.execute_script(
        'document.styleSheets[0].insertRule(".ace_cursor { opacity: 0 !important; }", 0 )')

    # TODO: Delay to wait for result to show. We should do this somehow using JavaScript.

    time.sleep(2)
    
    result_png = driver.get_screenshot_as_png()
    (tmp_path / "voltagedivider.png").write_bytes(result_png) # Write output to tmp_path for user.

    result_image = Image.open(io.BytesIO(result_png))
    
    #x=driver.execute_script("return document.documentElement.outerHTML")
    #Path("test.html").write_text(x)

    driver.quit()

    ref_image = Image.open(refdir / 'voltagedivider.png')
    
    assert not ImageChops.difference(result_image, ref_image).getbbox()
