# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Important: You have to run 'npm run build' in web/ before running the tests.
"""

import pytest
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from dataclasses import dataclass
import importlib.resources
import secrets

from ordec import server

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

@dataclass
class WebResViewer:
    html: str
    width: int
    height: int

# TODO: check_schematic, check_symbol and check_sim_dc seem a bit too primitive at the moment.

def check_schematic(res_viewer):
    assert res_viewer.html.find('<svg') >= 0

def check_symbol(res_viewer):
    assert res_viewer.html.find('<svg') >= 0

def check_sim_dc(res_viewer):
    assert res_viewer.html.find('<table') >= 0

def check_min_size(min_width, min_height):
    def func(res_viewer):
        assert res_viewer.width >= min_width
        assert res_viewer.height >= min_height
    return func

testcases_integrated = {
    "nand2": {
        'Nand2().schematic': [check_schematic, check_min_size(300, 100)],
        'Nand2Tb().schematic': [check_schematic, check_min_size(300, 50)],
        'Nand2Tb().sim_dc': [check_sim_dc, check_min_size(300, 50)],
    },
    "voltagedivider_py": {
        'VoltageDivider().schematic': [check_schematic, check_min_size(300, 200)],
        'VoltageDivider().sim_dc': [check_sim_dc, check_min_size(300, 200)],
    },
    "blank": {
        'undefined':[],
    },
    "voltagedivider":{
        'VoltageDivider().schematic': [check_schematic, check_min_size(300, 200)],
        'VoltageDivider().sim_dc': [check_sim_dc, check_min_size(300, 200)],
    },
    "diffpair": {
        'DiffPair().schematic': [check_schematic, check_min_size(300, 100)],
        'DiffPairTb().schematic': [check_schematic, check_min_size(300, 100)],
        'DiffPairTb().sim_dc': [check_sim_dc, check_min_size(300, 100)],
    },
}

testcases_local = {
    "ordec.lib.examples.voltagedivider": testcases_integrated['voltagedivider'],
    "ordec.lib.examples.voltagedivider_py": testcases_integrated['voltagedivider_py'],
    # Further tests in local mode case be added here (for specific features of the webui).
}


@dataclass
class WebserverInfo:
    url: str
    auth_token: str

@pytest.fixture(scope="session", autouse=True)
def webserver():
    auth_token = secrets.token_urlsafe()
    # Using a port other than 8100 makes it possible to run the tests
    # while having another independent ordec-server running.
    port = 8102
    web_dist_path = (Path(__file__).parent.parent/'web'/'dist').resolve()
    tar = server.anonymous_tar(web_dist_path)
    static_handler = server.StaticHandler(tar)

    t = threading.Thread(target=server.server_thread,
        args=('127.0.0.1', port, static_handler, auth_token), daemon=True)
    t.start()
    time.sleep(1) # Delay for server startup
    yield WebserverInfo(f"http://127.0.0.1:{port}/", auth_token)
    # Server will stop when pytest exits.

@pytest.mark.web
@pytest.mark.skipif(skip_webtests, reason="Prerequesites for web tests not installed.")
def test_index(webserver):
    with webdriver.Chrome(options=webdriver_options) as driver:
        driver.get(webserver.url + '')
        app_html_link_queries = set()
        for a in driver.find_elements(By.TAG_NAME, 'a'):
            href = urlparse(a.get_attribute('href'))
            if href.path == '/app.html':
                app_html_link_queries.add(href.query)

    # Check that we link to each expected example.
    assert app_html_link_queries == {f'example={testcase}' for testcase in testcases_integrated.keys()}

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
#    things have to go right. The server has to process the source data,
#    and the view requests. If the 'ready' state is not reached, request_example
#    fails.
# 2. The innerHTML of some result viewers is _superficially_ checked to make
#    sure it is showing roughly what is expected.

def request_integrated_example(webserver, testcase):
    with webdriver.Chrome(options=webdriver_options) as driver:
        resize_viewport(driver, 800, 600)

        driver.get(webserver.url)
        driver.add_cookie({"name": "ordecAuth", "value": webserver.auth_token})

        driver.get(webserver.url + f'app.html?example={testcase}&refreshall=true')

        WebDriverWait(driver, 10).until(
            EC.text_to_be_present_in_element((By.ID, 'status'), "ready"))

        res_viewers = driver.execute_script("""
            let res = {};
            window.ordecClient.resultViewers.forEach(function(rv) {
                res[rv.viewSelected] = rv.testInfo();
            });
            return res;
        """)

        #driver.save_screenshot('test.png')
    return {k:WebResViewer(**v) for k, v in res_viewers.items()}

@pytest.mark.web
@pytest.mark.parametrize('testcase', testcases_integrated.keys())
@pytest.mark.skipif(skip_webtests, reason="Prerequesites for web tests not installed.")
def test_integrated(webserver, testcase):
    """Web tests using integrated mode (&example=..)"""
    res_viewers = request_integrated_example(webserver, testcase)

    ref = testcases_integrated[testcase]
    assert set(res_viewers.keys()) == set(ref.keys())

    for view_name, checkers in ref.items():
        res_viewer = res_viewers[view_name]

        for checker in checkers:
            checker(res_viewer)

def request_local(webserver, module, request_views):
    res = {}
    with webdriver.Chrome(options=webdriver_options) as driver:
        resize_viewport(driver, 800, 600)

        driver.get(webserver.url)
        driver.add_cookie({"name": "ordecAuth", "value": webserver.auth_token})

        driver.get(webserver.url + f'app.html?module={module}&refreshall=true')

        WebDriverWait(driver, 10).until(
            EC.text_to_be_present_in_element((By.ID, 'status'), "ready"))

        for view in request_views:
            found = driver.execute_script("""
                let rv = window.ordecClient.resultViewers[0];
                let found = false;
                Array.prototype.forEach.call(rv.viewSelector.options, (o) => {
                    if(o.value == arguments[0]) {
                        o.selected=true;
                        found = true;
                    }
                });
                rv.viewSelectorOnChange();
                return found;
            """, view)

            assert found

            WebDriverWait(driver, 10).until(
                EC.text_to_be_present_in_element((By.ID, 'status'), "ready"))

            v = driver.execute_script("""
                let rv = window.ordecClient.resultViewers[0];
                return rv.testInfo();
            """)

            res[view] = WebResViewer(**v)

    return res

@pytest.mark.web
@pytest.mark.parametrize('testcase', testcases_local.keys())
@pytest.mark.skipif(skip_webtests, reason="Prerequesites for web tests not installed.")
def test_local(webserver, testcase):
    """Web tests using local mode (&module=..)"""
    ref = testcases_local[testcase]

    res_viewers = request_local(webserver, testcase, ref.keys())

    for view_name, checkers in ref.items():
        res_viewer = res_viewers[view_name]

        for checker in checkers:
            checker(res_viewer)
