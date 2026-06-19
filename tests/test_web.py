# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
The web fixture rebuilds web/dist automatically when it is missing or older
than the frontend sources, so no manual 'npm run build' is required.
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

    # Check that we link to each expected example and course.
    expected = {f'example={testcase}' for testcase in testcases_integrated.keys()}
    expected.add('course=intro')
    assert app_html_link_queries == expected

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

    web.navigate(f'app.html#example={testcase}&refreshall=true')

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
    web.navigate(f'app.html#refreshall=true&viewsel_flat=true&{qs_local}')

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

def course_nav_state(web):
    """Returns the state of the course navigator for assertions."""
    return web.driver.execute_script("""
        const cc = window.courseController;
        const nav = document.querySelector('.course-nav');
        return {
            currentLesson: cc.currentLesson,
            marker: nav.querySelector('.course-marker').innerText,
            lessonsLocked: Array.from(
                nav.querySelectorAll('.course-lessonsel option'),
                o => o.disabled),
            nextDisabled: nav.querySelector('.course-next').disabled,
            editorSrc: cc.editor.editor.getValue(),
        };
    """)

def course_panel_lock_state(web):
    """Draggability and close-control visibility of the locked panels (the
    Course panel and the source editor)."""
    return web.driver.execute_script("""
        const items = window.courseController.layout.root.getAllContentItems();
        const find = (pred) => {
            let r = null;
            items.forEach(e => { if (e.isComponent && pred(e)) r = e; });
            return r;
        };
        const course = find(e => e.componentName === 'result'
            && e.component && e.component.courseMode);
        const editor = find(e => e.componentName === 'editor');
        // Closable (so GoldenLayout keeps it draggable) + reorderEnabled.
        const draggable = (e) => Boolean(e && e.reorderEnabled && e.isClosable);
        const allHidden = (sel) => {
            const els = Array.from(document.querySelectorAll(sel));
            return els.length > 0
                && els.every(el => getComputedStyle(el).display === 'none');
        };
        return {
            courseDraggable: draggable(course),
            editorDraggable: draggable(editor),
            tabClosesHidden: allHidden('.panel-locked-tab .lm_close_tab'),
            headerClosesHidden: allHidden('.panel-locked-header .lm_close'),
        };
    """)

def wait_for_course_marker(web, text, timeout=30):
    deadline = time.time() + timeout
    marker = None
    while time.time() < deadline:
        marker = web.driver.execute_script(
            "return document.querySelector('.course-marker').innerText;")
        if marker == text:
            return
        time.sleep(0.2)
    raise AssertionError(f"course marker did not become {text!r} "
        f"(last state: {marker!r})")

@pytest.mark.web
def test_course(web):
    """Course mode: navigator, lesson gating, pass detection, start over."""
    from .test_course import course_data, solution_src

    lessons = course_data()['lessons']

    web.resize_viewport()

    # Make sure we start without progress from earlier runs:
    web.driver.get(web.url)
    web.driver.execute_script(
        "window.localStorage.removeItem('ordecCourse:intro');")

    web.navigate('app.html#course=intro')
    web.wait_for_ready()

    # Lesson 1 skeleton: not passed, lessons 2+3 locked.
    state = course_nav_state(web)
    assert state['currentLesson'] == 0
    assert state['marker'] == 'unsolved'
    assert state['lessonsLocked'] == [False, True, True]
    assert state['nextDisabled'] is True
    assert state['editorSrc'] == lessons[0]['src']

    # The Course panel and the source editor must be movable but not closable.
    # GoldenLayout couples the two, so they stay closable (draggable) and their
    # close controls are hidden instead (see course.js suppressCloseControls).
    lock = course_panel_lock_state(web)
    assert lock['courseDraggable'] is True       # Course panel draggable
    assert lock['editorDraggable'] is True       # editor draggable
    assert lock['tabClosesHidden'] is True        # but tab closes hidden
    assert lock['headerClosesHidden'] is True     # and header closes hidden

    # Enter the lesson 1 solution into the editor; auto-refresh rebuilds and
    # re-checks, the pass must unlock lesson 2.
    sol = solution_src(lessons[0], ".$c=1n", ".$c=16n")
    web.driver.execute_script(
        "window.courseController.editor.editor.setValue(arguments[0]);", sol)
    wait_for_course_marker(web, 'solved')

    state = course_nav_state(web)
    assert state['lessonsLocked'] == [False, False, True]
    assert state['nextDisabled'] is False

    # Passing replaces the intro callout with the green success callout, whose
    # arrow points at the next button (lesson 1 is not the last lesson).
    success = web.driver.execute_script("""
        return {
            success: !!document.querySelector('.course-callout-success'),
            intro: !!document.querySelector('.course-callout-intro'),
            hasArrow: !!document.querySelector(
                '.course-callout-success .course-callout-arrow'),
        };
    """)
    assert success['success'] is True
    assert success['intro'] is False
    assert success['hasArrow'] is True

    # Switch to lesson 2 via the dropdown.
    web.driver.execute_script("""
        const sel = document.querySelector('.course-lessonsel');
        sel.value = '1';
        sel.dispatchEvent(new Event('change'));
    """)
    web.wait_for_ready()
    state = course_nav_state(web)
    assert state['currentLesson'] == 1
    assert state['marker'] == 'unsolved'
    assert state['editorSrc'] == lessons[1]['src']

    # Progress (incl. edited lesson 1 source) must survive a reload.
    web.navigate('app.html#course=intro')
    web.wait_for_ready()
    state = course_nav_state(web)
    assert state['currentLesson'] == 1
    assert state['lessonsLocked'] == [False, False, True]

    # Start over (with confirmation) resets everything. This reloads the page
    # from app JS, so wait for the reload before reading state.
    web.run_and_wait_for_reload("""
        window.confirm = () => true;
        document.querySelector('.course-startover').click();
    """)
    state = course_nav_state(web)
    assert state['currentLesson'] == 0
    assert state['lessonsLocked'] == [False, True, True]
    assert state['editorSrc'] == lessons[0]['src']


@pytest.mark.web
def test_course_intro_callout(web):
    """The intro callout appears above the lesson report on first open, points
    its arrow at the status marker, and stays dismissed once closed."""
    web.resize_viewport()
    web.driver.get(web.url)
    web.driver.execute_script(
        "window.localStorage.removeItem('ordecCourse:intro');")

    web.navigate('app.html#course=intro')
    web.wait_for_ready()

    info = web.driver.execute_script("""
        const callout = document.querySelector('.course-callout');
        const arrow = callout && callout.querySelector('.course-callout-arrow');
        return {
            present: !!callout,
            arrowAligned: !!(arrow && arrow.style.left),
            hasClose: !!(callout
                && callout.querySelector('.course-callout-close')),
        };
    """)
    assert info['present'] is True
    assert info['arrowAligned'] is True
    assert info['hasClose'] is True

    # Closing the callout hides it for the current visit only (in-memory, not
    # persisted to localStorage).
    removed = web.driver.execute_script("""
        document.querySelector('.course-callout-close').click();
        return !document.querySelector('.course-callout');
    """)
    assert removed is True

    # The dismissal is not persisted, so re-opening the course shows it again.
    web.navigate('app.html#course=intro')
    web.wait_for_ready()
    present_again = web.driver.execute_script(
        "return !!document.querySelector('.course-callout');")
    assert present_again is True


@pytest.mark.web
def test_course_lesson3_refresh_overlay(web):
    """Lessons whose checks don't auto-run (lesson 3: LVS/DRC) show the standard
    in-panel Refresh overlay (not a toolbar Check button). debug=true unlocks
    lesson 3 so we can reach it without running the earlier checks."""
    web.resize_viewport()
    web.driver.get(web.url)
    web.driver.execute_script(
        "window.localStorage.removeItem('ordecCourse:intro');")

    web.navigate('app.html#course=intro&debug=true')
    web.wait_for_ready()
    web.driver.execute_script("""
        const sel = document.querySelector('.course-lessonsel');
        sel.value = '2';
        sel.dispatchEvent(new Event('change'));
    """)
    web.wait_for_ready()

    info = web.driver.execute_script("""
        let comp = null;
        window.courseController.layout.root.getAllContentItems().forEach(e => {
            if (e.isComponent && e.componentName === 'result'
                && e.component && e.component.courseMode) comp = e;
        });
        const overlay = comp.component.resOverlayRefreshable;
        return {
            currentLesson: window.courseController.currentLesson,
            marker: document.querySelector('.course-marker').innerText,
            refreshOverlayShown: getComputedStyle(overlay).display !== 'none',
            noCheckButton: !document.querySelector('.course-check'),
        };
    """)
    assert info['currentLesson'] == 2
    assert info['marker'] == 'not checked'
    assert info['refreshOverlayShown'] is True   # standard Refresh overlay
    assert info['noCheckButton'] is True          # toolbar Check button gone


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
    web.navigate(f'app.html#refreshall=true&{qs_local}')

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
