# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Important: You have to run 'npm run build' in web/ before running the tests.
"""

import pytest
import time
from urllib.parse import urlparse
from dataclasses import dataclass
from PIL import Image, ImageStat
import io

try:
    from selenium.webdriver.common.by import By
except ImportError:
    By = None


@dataclass
class WebResViewer:
    html: str
    top: int
    left: int
    bottom: int
    right: int
    width: int
    height: int

# TODO: check_schematic, check_symbol and check_sim_dc seem a bit too primitive at the moment.

def check_schematic(res_viewer):
    assert res_viewer.html.find('<svg') >= 0

def check_symbol(res_viewer):
    assert res_viewer.html.find('<svg') >= 0

def check_sim_dc(res_viewer):
    assert res_viewer.html.find('report-view') >= 0

def check_sim_tran(res_viewer):
    assert res_viewer.html.find('report-view') >= 0

def check_report_example(res_viewer):
    html = res_viewer.html
    assert html.find('class="report-view"') >= 0
    assert html.count('class="report-element"') == 4
    assert html.count('class="report-svg"') == 2
    assert html.count('class="report-plot2d"') == 4
    assert html.find('simplot') >= 0
    assert html.find('Report Example') >= 0
    assert html.find('bold') >= 0
    assert html.find('alpha') >= 0

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
        'null':[],
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
    "rc_curve": {
        'RC().schematic': [check_schematic, check_min_size(300, 100)],
        'RC().sim_tran': [check_sim_tran, check_min_size(300, 100)],
    },
    "amp": {
        'Amp().schematic': [check_schematic, check_min_size(300, 100)],
        'AmpTb().schematic': [check_schematic, check_min_size(300, 100)],
        'AmpTb().report_ac': [],
    },
    'currentmirror': {
        'CurrentMirror().schematic': [check_schematic, check_min_size(300, 100)],
        'CurrentMirror().sim_dc': [check_sim_dc, check_min_size(300, 200)],
    },
    'vco_pseudodiff': {
        'VcoRing().layout': [],
    },
}

testcases_local = {
    "ordec.examples.voltagedivider": testcases_integrated['voltagedivider'],
    "ordec.examples.voltagedivider_py": testcases_integrated['voltagedivider_py'],
    "tests.lib.report": {
        'report_example()': [check_report_example],
    },
    # Further tests in local mode case be added here (for specific features of the webui).
}


@pytest.mark.web
def test_index(web):
    web.driver.get(web.url + '')
    app_html_link_queries = set()
    for a in web.driver.find_elements(By.TAG_NAME, 'a'):
        href = urlparse(a.get_attribute('href'))
        if href.path == '/app.html':
            app_html_link_queries.add(href.fragment)

    # Check that we link to each expected example.
    assert app_html_link_queries == {f'example={testcase}' for testcase in testcases_integrated.keys()}

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


def request_integrated_example(web, testcase):
    web.resize_viewport()

    web.driver.get(web.url + f'app.html#example={testcase}&refreshall=true')
    web.driver.refresh()  # fragment-only change doesn't reload the page

    web.wait_for_ready()

    res_viewers = web.driver.execute_script("""
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
def test_integrated(web, testcase):
    """Web tests using integrated mode (&example=..)"""
    res_viewers = request_integrated_example(web, testcase)

    ref = testcases_integrated[testcase]
    assert set(res_viewers.keys()) == set(ref.keys())

    for view_name, checkers in ref.items():
        res_viewer = res_viewers[view_name]

        for checker in checkers:
            checker(res_viewer)

def request_local(web, module, request_views):
    res = {}
    web.resize_viewport()
    
    qs_local = web.key.query_string_local(module, '')
    web.driver.get(web.url + f'app.html#refreshall=true&viewsel_flat=true&{qs_local}')
    web.driver.refresh()  # fragment-only change doesn't reload the page

    web.wait_for_ready()

    for view in request_views:
        found = web.driver.execute_script("""
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

        web.wait_for_ready()

        v = web.driver.execute_script("""
            let rv = window.ordecClient.resultViewers[0];
            return rv.testInfo();
        """)

        res[view] = WebResViewer(**v)

    return res

@pytest.mark.web
@pytest.mark.parametrize('testcase', testcases_local.keys())
def test_local(web, testcase):
    """Web tests using local mode (&module=..)"""
    ref = testcases_local[testcase]

    res_viewers = request_local(web, testcase, ref.keys())

    for view_name, checkers in ref.items():
        res_viewer = res_viewers[view_name]

        for checker in checkers:
            checker(res_viewer)

def myhistogram(img, thresh=50):
    h = {}
    for x in range(img.width):
        for y in range(img.height):
            val = img.getpixel((x, y))
            
            try:
                h[val]+=1
            except KeyError:
                h[val]=1
    drop_vals = []
    for val, count in h.items():
        if count < thresh:
            drop_vals.append(val)
    for val in drop_vals:
        del h[val]
    return h

@pytest.mark.web
def test_layoutgl(web):
    """Fuzzy visual testing of web layout viewer (layout-gl.js)."""
    web.resize_viewport()
        
    qs_local = web.key.query_string_local("tests.lib.layoutgl_example", "layoutgl_example()")
    web.driver.get(web.url + f'app.html#refreshall=true&{qs_local}')
    web.driver.refresh()  # fragment-only change doesn't reload the page

    web.wait_for_ready()

    time.sleep(1)
    canvas=web.driver.find_element(By.CSS_SELECTOR, "canvas.layoutFit")
    png = canvas.screenshot_as_png

    #with open("screenshot.png", "wb") as f:
    #    f.write(png)
    
    img = Image.open(io.BytesIO(png))

    wh = (img.width-img.height)/2
    margin = 25

    img = img.crop([wh+margin, margin, img.width-wh-margin, img.height-margin])
    img = img.resize([512, 512], Image.Resampling.NEAREST)

    expect_blue  = img.crop((0, 0, 256, 128))
    assert myhistogram(expect_blue)[(16, 71, 139)] > 20000

    expect_text  = img.crop((128, 256-32, 256+128, 256+32))
    assert myhistogram(expect_text)[(255,255,255)] > 100
    
    expect_red   = img.crop((256, 256+32, 256+128, 256+32+64))
    assert myhistogram(expect_red)[(89, 0, 0)] > 5000
    
    expect_black = img.crop((256, 256+128, 256+64, 256+128+64))
    assert myhistogram(expect_black)[(0, 0, 0)] > 2000
