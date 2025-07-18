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
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.wait import WebDriverWait
    from selenium.webdriver.common.by import By
except ImportError:
    skip_webtests = True
else:
    skip_webtests = False

    webdriver_options = webdriver.ChromeOptions()
    webdriver_options.add_argument("--no-sandbox") # Somehow needed for webdriver to work in ordec-base image (something with the ubuntu version?!)
    webdriver_options.add_argument("--headless=new")
    webdriver_options.add_argument("--force-device-scale-factor=1")
    # The following sets the window size, not the viewport size (see resize_viewport below):
    # webdriver_options.add_argument("--window-size=1280,720")

examples = {
    "nand2":{'Nand2().schematic', 'Nand2Tb().schematic', 'Nand2Tb().sim_dc'},
    "voltagedivider_py":{'VoltageDivider().schematic', 'VoltageDivider().sim_dc'},
    "blank":{'undefined'},
    "voltagedivider":{'VoltageDivider().schematic', 'VoltageDivider().sim_dc'},
    "diffpair":{'DiffPair().schematic', 'DiffPairTb().schematic', 'DiffPairTb().sim_dc'},
}

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
    assert app_html_link_queries == {f'example={example}' for example in examples.keys()}

def resize_viewport(driver, w, h):
    w_overhead = driver.execute_script("return window.outerWidth - window.innerWidth;")
    h_overhead = driver.execute_script("return window.outerHeight - window.innerHeight;")
    driver.set_window_size(w+w_overhead, h+h_overhead)


# Visual browser-based testing was painful (fonts, different browser versions,
# comparison algorithms, large PNGs in repo). For those reasons, it is no
# longer done here.
#
# The examples are now tested in two ways:
# 1. Does the webinterface reach the 'ready' state? For this to happen, a lot of
#    things have to go right. The ws_server has to process the source data,
#    and the view requests. If the 'ready' state is not reached, request_example
#    fails.
# 2. The innerHTML of some result viewers is _superficially_ checked to make
#    sure it is showing roughly what is expected.

def request_example(webserver, example):
    with webdriver.Chrome(options=webdriver_options) as driver:
        resize_viewport(driver, 800, 600)
        driver.get(webserver.url + f'app.html?example={example}')
        
        WebDriverWait(driver, 10).until(
            EC.text_to_be_present_in_element((By.ID, 'status'), "ready"))
        
        res_viewers = driver.execute_script("""
            var res = {};
            window.myLayout.root.getAllContentItems().forEach(function(e) {
                if (!e.isComponent) return;
                if (e.componentName != 'result') return;
                res[e.component.viewRequested] = e.component.resContent.innerHTML;
            });
            return res;
        """)
        #driver.save_screenshot('test.png')
    return res_viewers

@pytest.mark.web
@pytest.mark.parametrize('example', examples.keys())
@pytest.mark.skipif(skip_webtests, reason="Prerequesites for web tests not installed.")
def test_example(webserver, tmp_path, example):
    res_viewers = request_example(webserver, example)

    assert set(res_viewers.keys()) == examples[example]

    for view_name, html in res_viewers.items():
        if view_name.endswith(".schematic"):
            assert html.find('<svg') >= 0
        elif view_name.endswith(".symbol"):
            assert html.find('<svg') >= 0
        elif view_name.endswith(".sim_dc"):
            assert html.find('<table') >= 0
        elif view_name == 'undefined':
            pass # for blank example
        else:
            raise NotImplementedError(f"No test implemented for result viewer {view_name!r}.")

        
