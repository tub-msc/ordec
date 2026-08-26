# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
The web fixture rebuilds web/dist automatically when it is missing or older
than the frontend sources, so no manual 'npm run build' is required.
"""

import json
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

from .test_course import courses_testdata


@dataclass
class WebResViewer:
    html: str
    top: int
    left: int
    bottom: int
    right: int
    width: int
    height: int

# TODO: check_schematic, check_symbol and check_sim_op seem a bit too primitive at the moment.

def check_schematic(res_viewer):
    assert res_viewer.html.find('<svg') >= 0

def check_symbol(res_viewer):
    assert res_viewer.html.find('<svg') >= 0

def check_sim_op(res_viewer):
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
    # TeX math rendered client-side by KaTeX:
    assert html.find('class="katex"') >= 0

def check_min_size(min_width, min_height):
    def func(res_viewer):
        assert res_viewer.width >= min_width
        assert res_viewer.height >= min_height
    return func

testcases_integrated = {
    "nand2": {
        'Nand2().schematic': [check_schematic, check_min_size(300, 100)],
        'Nand2Tb().schematic': [check_schematic, check_min_size(300, 50)],
        'Nand2Tb().sim_op': [check_sim_op, check_min_size(300, 50)],
    },
    "voltagedivider_py": {
        'VoltageDivider().schematic': [check_schematic, check_min_size(300, 200)],
        'VoltageDivider().sim_op': [check_sim_op, check_min_size(300, 200)],
    },
    "blank": {
        'null':[],
    },
    "voltagedivider":{
        'VoltageDivider().schematic': [check_schematic, check_min_size(300, 200)],
        'VoltageDivider().sim_op': [check_sim_op, check_min_size(300, 200)],
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
        'CurrentMirror().sim_op': [check_sim_op, check_min_size(300, 200)],
    },
    'diffpair': {
        'DiffPair().schematic': [check_schematic, check_min_size(300, 100)],
        'DiffPairTb().schematic': [check_schematic, check_min_size(300, 100)],
        'DiffPairTb().report_dc': [],
    },
    'vco_pseudodiff': {
       "Vco(width='1u',length='500n').layout": [],
       "Vco(width='1u',length='500n').drc": [],
       "Vco(width='1u',length='500n').lvs": [],
    },
    'adder_pnr': {
        'RippleAdder().layout': [],
        'AdderTb().report_tran': [],
    },
    'stdcells': {
        "extlib['sg13g2_inv_1'].layout": [],
        "extlib['sg13g2_inv_1'].schematic": [],
        'inv_drc()': [],
        'InvTb().report_vtc': [],
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
    expected.update({f'course={name}' for name in courses_testdata.keys()})
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
        window.ordecApp.client.resultViewers.forEach(function(rv) {
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

    qs_local = web.key.query_string_local(module, [])
    web.navigate(f'app.html#refreshall=true&viewsel_flat=true&{qs_local}')

    web.wait_for_ready()

    for view in request_views:
        found = web.driver.execute_script("""
            let rv = window.ordecApp.client.resultViewers[0];
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
            let rv = window.ordecApp.client.resultViewers[0];
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
            editorSrc: cc.editor ? cc.editor.editor.getValue() : null,
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

def reset_course_storage(web):
    """Clears course progress from earlier runs."""
    web.driver.get(web.url)
    web.driver.execute_script(
        "window.localStorage.removeItem('ordecCourse:getting_started');")

def skip_tour(web, timeout=5):
    """Waits for the spotlight tour (it replays on every visit of the welcome
    lesson) and dismisses it."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if web.driver.execute_script("""
            const skip = document.querySelector('.spotlight-skip');
            if (skip) skip.click();
            return !!skip;
        """):
            return
        time.sleep(0.1)
    raise AssertionError('spotlight tour did not appear')

@pytest.mark.web
def test_course(web):
    """Course mode: navigator, lesson gating, pass detection, start over."""
    from .test_course import course_data

    lessons = course_data()['lessons']
    # Expected lock state when the first n lessons are unlocked:
    def locked_after(n):
        return [i >= n for i in range(len(lessons))]

    web.resize_viewport()
    reset_course_storage(web)

    web.navigate('app.html#course=getting_started')
    web.wait_for_ready()
    skip_tour(web)

    # Lesson 1 (welcome) counts as solved right away, unlocking lesson 2;
    # lessons 2-5 stay locked.
    wait_for_course_marker(web, 'solved')
    state = course_nav_state(web)
    assert state['currentLesson'] == 0
    assert state['lessonsLocked'] == locked_after(2)
    assert state['editorSrc'] == lessons[0]['src']

    # The close controls of the Course panel and the source editor are
    # hidden (see course.js suppressCloseControls).
    assert web.driver.execute_script("""
        const allHidden = (sel) => {
            const els = Array.from(document.querySelectorAll(sel));
            return els.length > 0
                && els.every(el => getComputedStyle(el).display === 'none');
        };
        return allHidden('.panel-locked-tab .lm_close_tab')
            && allHidden('.panel-locked-header .lm_close');
    """) is True

    # Switch to lesson 2 via the next arrow.
    web.driver.execute_script(
        "document.querySelector('.course-next').click();")
    web.wait_for_ready()
    state = course_nav_state(web)
    assert state['currentLesson'] == 1
    assert state['marker'] == 'unsolved'

    # Lesson 2 is passed by opening the two HelloWorld result viewers
    # (frontend-only detection, see course.js checkLesson1Views). Open two
    # viewers via the toolbar button and select the views like a user would.
    web.driver.execute_script("""
        document.querySelector('#newresview').click();
        document.querySelector('#newresview').click();
        // Register the new viewers with the client right away instead of
        // relying on GoldenLayout's stateChanged event timing:
        const all = window.courseController.deps.getResultViewers();
        window.ordecApp.client.registerResultViewers(all);
        const rvs = all.filter(rv => !rv.courseMode && !rv.viewSelected);
        rvs[0]._onViewSelected('HelloWorld().schematic');
        rvs[1]._onViewSelected('HelloWorld().hello');
    """)
    wait_for_course_marker(web, 'solved')

    # The new result views must never be created as tabs on top of the
    # Course panel or the source editor (see main.js #newresview handler).
    well_placed = web.driver.execute_script("""
        const items = window.courseController.layout.root.getAllContentItems();
        return !items.some(e => e.isComponent && e.componentName === 'result'
            && e.component && !e.component.courseMode
            && e.parent.contentItems.some(sib => sib.isComponent
                && (sib.componentName === 'editor'
                    || (sib.component && sib.component.courseMode))));
    """)
    assert well_placed is True

    state = course_nav_state(web)
    assert state['lessonsLocked'] == locked_after(3)

    # Switch to lesson 3 via the dropdown.
    web.driver.execute_script("""
        const sel = document.querySelector('.course-lessonsel');
        sel.value = '2';
        sel.dispatchEvent(new Event('change'));
    """)
    web.wait_for_ready()
    state = course_nav_state(web)
    assert state['currentLesson'] == 2

    # Solve lesson 3 by editing the source; auto-refresh rebuilds and
    # re-checks, the pass must unlock lesson 4.
    sol = courses_testdata['getting_started'].lessons[2].solution_src(lessons[2])
    web.driver.execute_script(
        "window.courseController.editor.editor.setValue(arguments[0]);", sol)
    wait_for_course_marker(web, 'solved')
    state = course_nav_state(web)
    assert state['lessonsLocked'] == locked_after(4)

    # A syntax error while editing must not wipe the lesson report: the
    # Course panel keeps the last good report and shows the error strip; the
    # traceback appears only behind the details toggle (see resultviewer.js
    # showBuildError).
    def course_error_state(web):
        return web.driver.execute_script("""
            const rv = window.courseController.courseViewer;
            const shown = (el) => getComputedStyle(el).display !== 'none';
            return {
                strip: shown(rv.resOverlayError),
                stripText: rv.buildErrorText.innerText,
                content: shown(rv.resContent),
                exception: shown(rv.resException),
                exceptionText: rv.resException.innerText,
            };
        """)

    web.driver.execute_script(
        "window.courseController.editor.editor.setValue(arguments[0]);",
        sol + "\ndef broken(:\n")
    wait_for_course_marker(web, 'check error')
    state = course_error_state(web)
    assert state['strip'] and 'SyntaxError' in state['stripText']
    assert state['content'] and not state['exception']

    # Expanding the details shows the full traceback in place of the report;
    # collapsing restores the report.
    web.driver.execute_script(
        "window.courseController.courseViewer.buildErrorToggle.click();")
    state = course_error_state(web)
    assert state['exception'] and not state['content']
    assert 'SyntaxError' in state['exceptionText']
    web.driver.execute_script(
        "window.courseController.courseViewer.buildErrorToggle.click();")
    state = course_error_state(web)
    assert state['content'] and not state['exception']

    # Fixing the source clears the strip and re-checks the lesson.
    web.driver.execute_script(
        "window.courseController.editor.editor.setValue(arguments[0]);", sol)
    wait_for_course_marker(web, 'solved')
    state = course_error_state(web)
    assert not state['strip'] and state['content'] and not state['exception']

    # Progress (incl. edited lesson 3 source) must survive a reload.
    web.navigate('app.html#course=getting_started')
    web.wait_for_ready()
    state = course_nav_state(web)
    assert state['currentLesson'] == 2
    assert state['lessonsLocked'] == locked_after(4)

    # Start over (with confirmation) resets everything. This reloads the page
    # from app JS, so wait for the reload before reading state.
    web.run_and_wait_for_reload("""
        window.confirm = () => true;
        document.querySelector('.course-startover').click();
    """)
    wait_for_course_marker(web, 'solved')  # lesson 1 auto-passes again
    state = course_nav_state(web)
    assert state['currentLesson'] == 0
    assert state['lessonsLocked'] == locked_after(2)
    assert state['editorSrc'] == lessons[0]['src']

    # The epilogue (task-free closing lesson) counts as solved right away,
    # shows no callout, and its shipped layout has no source editor. Reached
    # via debug mode, which unlocks all lessons.
    web.navigate('app.html#course=getting_started&debug=true')
    web.wait_for_ready()
    skip_tour(web)
    web.driver.execute_script("""
        const sel = document.querySelector('.course-lessonsel');
        sel.value = String(sel.options.length - 1);
        sel.dispatchEvent(new Event('change'));
    """)
    web.wait_for_ready()
    wait_for_course_marker(web, 'solved')
    state = course_nav_state(web)
    assert state['currentLesson'] == len(lessons) - 1
    assert state['editorSrc'] is None
    info = web.driver.execute_script("""
        return {
            editorDom: !!document.querySelector('.ace_editor'),
            callout: !!document.querySelector('.course-callout'),
        };
    """)
    assert info == {'editorDom': False, 'callout': False}


@pytest.mark.web
def test_course_intro_callout(web):
    """Lesson 1 shows the success callout once the tour is done; the intro
    callout appears on lesson 2 and stays dismissed for the visit once
    closed."""
    web.resize_viewport()
    reset_course_storage(web)

    web.navigate('app.html#course=getting_started')
    web.wait_for_ready()
    skip_tour(web)

    # Lesson 1 once the tour is dismissed: the success callout, no intro
    # callout.
    wait_for_course_marker(web, 'solved')
    info = web.driver.execute_script("""
        return {
            success: !!document.querySelector('.course-callout-success'),
            intro: !!document.querySelector('.course-callout-intro'),
        };
    """)
    assert info['success'] is True
    assert info['intro'] is False

    # Switch to lesson 2: the intro callout explains the course mechanics.
    web.driver.execute_script(
        "document.querySelector('.course-next').click();")
    web.wait_for_ready()
    assert web.driver.execute_script(
        "return !!document.querySelector('.course-callout-intro');") is True

    # Closing the callout hides it for the current visit only (in-memory, not
    # persisted to localStorage).
    removed = web.driver.execute_script("""
        document.querySelector('.course-callout-close').click();
        return !document.querySelector('.course-callout');
    """)
    assert removed is True

    # The dismissal is not persisted, so re-opening the course (which resumes
    # at lesson 2) shows it again.
    web.navigate('app.html#course=getting_started')
    web.wait_for_ready()
    present_again = web.driver.execute_script(
        "return !!document.querySelector('.course-callout-intro');")
    assert present_again is True


@pytest.mark.web
def test_course_competition_nav(web):
    """A competition course (amp_competition) hides the lesson navigator; the
    status marker and the source management buttons remain. Without the
    hub's scoreboard service the course is unlisted on the landing page,
    there is no team dialog, and the Scoreboard panel of the shipped layout
    says so (see landing-page.js/scoreboard.js)."""
    web.resize_viewport()
    web.driver.get(web.url)
    web.driver.execute_script(
        "window.localStorage.removeItem('ordecCourse:amp_competition');")
    assert web.driver.execute_script("""
        return document.querySelector('#competitionSection').hidden;
    """) is True

    web.navigate('app.html#course=amp_competition')
    web.wait_for_ready()
    wait_for_course_marker(web, 'unsolved')
    info = web.driver.execute_script("""
        return {
            prev: !!document.querySelector('.course-prev'),
            lessonsel: !!document.querySelector('.course-lessonsel'),
            next: !!document.querySelector('.course-next'),
            marker: !!document.querySelector('.course-marker'),
            export_: !!document.querySelector('.course-export'),
            startover: !!document.querySelector('.course-startover'),
            teamdialog: !!document.querySelector('#teamdialog'),
            scoreboard: document.querySelector('.scoreboard').innerText,
            score: !!document.querySelector(
                '.report-score.report-score-ineligible'),
        };
    """)
    assert info == {'prev': False, 'lessonsel': False, 'next': False,
        'marker': True, 'export_': True, 'startover': True,
        'teamdialog': False,
        'scoreboard': 'The scoreboard is not available on this server.',
        'score': True}


# Stands in for a hub deployment with the scoreboard service: patches fetch()
# in every new document so that api/token puts the frontend into hub mode
# (with the real auth token and the scoreboard URL) and the scoreboard's
# JSON API (support/hub/scoreboard.py) is served from an in-page fake that
# records claims and pushes in window.scoreboardFake.
SCOREBOARD_FAKE_JS = """
    const realFetch = window.fetch;
    const fake = {
        team: null,
        rows: [{team: 'Other team', score: 12.5, updated: '09:59:00'}],
        final: null,
        claims: [],
        pushes: [],
    };
    window.scoreboardFake = fake;
    const json = (obj, status = 200) => new Response(JSON.stringify(obj),
        {status: status, headers: {'Content-Type': 'application/json'}});
    const state = () => ({team: fake.team, rows: fake.rows,
        final: fake.final});
    window.fetch = async (url, opts) => {
        if (url === 'api/token') {
            return json({auth: %s, hub_logout_url: '/hub/logout',
                scoreboard: '/services/scoreboard/'});
        }
        if (url === '/services/scoreboard/api/state') {
            return json(state());
        }
        if (url === '/services/scoreboard/api/claim') {
            const body = JSON.parse(opts.body);
            fake.claims.push(body);
            if (body.team === 'taken') {
                return json({error: 'This team name is already taken.'}, 409);
            }
            if (fake.team !== null) {
                fake.rows.find(r => r.team === fake.team).team = body.team;
            } else {
                fake.rows.push({team: body.team, score: null,
                    updated: '10:00:00'});
            }
            fake.team = body.team;
            return json(state());
        }
        if (url === '/services/scoreboard/api/push') {
            const body = JSON.parse(opts.body);
            fake.pushes.push(body);
            fake.rows[1].score = body.score;
            return new Response(null, {status: 204});
        }
        return realFetch(url, opts);
    };
"""


@pytest.mark.web
def test_course_competition_scoreboard(web):
    """With a scoreboard (faked in-page, see SCOREBOARD_FAKE_JS), the
    competition course is listed on the landing page and opens with the
    team dialog; a rejected name shows the error inline, an accepted one
    opens the course with the Scoreboard panel polling the standings. An
    all-checks-passing design pushes its score, and a revisit re-claims the
    stored team without asking again."""
    web.resize_viewport()
    web.driver.get(web.url)
    web.driver.execute_script("""
        window.localStorage.removeItem('ordecCourse:amp_competition');
        window.localStorage.removeItem('ordecTeam:amp_competition');
    """)
    script = web.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',
        {'source': SCOREBOARD_FAKE_JS % json.dumps(web.key.token())})
    try:
        web.navigate('')
        web.wait_until("""
            return !document.querySelector('#competitionSection').hidden;
        """)

        web.navigate('app.html#course=amp_competition')
        web.wait_until("return !!document.querySelector('#teamdialog');")
        # The course does not open before the team has joined:
        assert web.driver.execute_script(
            "return !!document.querySelector('.course-marker');") is False

        def join(name):
            web.driver.execute_script("""
                document.querySelector('.teamdialog-name').value = arguments[0];
                document.querySelector('.teamdialog-join').click();
            """, name)

        join('taken')
        web.wait_until("""
            return document.querySelector('.teamdialog-error').innerText
                === 'This team name is already taken.';
        """)
        join('Ohm sweet Ohm')
        web.wait_until("return !document.querySelector('#teamdialog');")
        web.wait_for_ready()
        wait_for_course_marker(web, 'unsolved')
        # The panel shares its stack with the course panel; bring it to
        # the front (innerText of a hidden tab is empty).
        web.driver.execute_script("""
            [...document.querySelectorAll('.lm_tab')]
                .find(t => t.innerText.startsWith('Scoreboard')).click();
        """)
        # The panel shows the standings with the own team highlighted.
        web.wait_until("""
            return document.querySelectorAll('.scoreboard tr').length === 3;
        """)
        info = web.driver.execute_script("""
            const rows = [...document.querySelectorAll('.scoreboard tr')];
            return {
                rows: rows.map(tr => tr.innerText.split('\t')),
                own: rows.map(tr => tr.classList.contains('scoreboard-own')),
                claims: window.scoreboardFake.claims.map(c => c.team),
                pushes: window.scoreboardFake.pushes.map(p => p.score),
                stored: JSON.parse(window.localStorage.getItem(
                    'ordecTeam:amp_competition')).name,
            };
        """)
        assert info['rows'] == [
            ['#', 'Team', 'Supply current', 'Updated'],
            ['1', 'Other team', '12.50 µA', '09:59:00'],
            ['2', 'Ohm sweet Ohm rename', 'no score', '10:00:00'],
        ]
        assert info['own'] == [False, False, True]
        assert info['claims'] == ['taken', 'Ohm sweet Ohm']
        # The skeleton's build fails the checks: pushed as "no score".
        assert info['pushes'] == [None]
        assert info['stored'] == 'Ohm sweet Ohm'

        # Renaming keeps the entry (the fake renames its row) and the
        # stored secret is replaced along with the name.
        secret = web.driver.execute_script("""
            return JSON.parse(window.localStorage.getItem(
                'ordecTeam:amp_competition')).secret;
        """)
        web.driver.execute_script(
            "document.querySelector('.scoreboard-rename').click();")
        web.wait_until("""
            const b = document.querySelector('.teamdialog-join');
            return b && b.innerText === 'Rename'
                && document.querySelector('.teamdialog-name').value
                    === 'Ohm sweet Ohm';
        """)
        web.driver.execute_script(
            "document.querySelector('.teamdialog-cancel').click();")
        web.wait_until("return !document.querySelector('#teamdialog');")
        web.driver.execute_script(
            "document.querySelector('.scoreboard-rename').click();")
        web.wait_until("return !!document.querySelector('.teamdialog-join');")
        join('Ohm my')
        web.wait_until("""
            return !document.querySelector('#teamdialog')
                && document.querySelector('.scoreboard-own td:nth-child(2)')
                    .innerText.startsWith('Ohm my');
        """)
        info = web.driver.execute_script("""
            const rows = [...document.querySelectorAll('.scoreboard tr')];
            const stored = JSON.parse(window.localStorage.getItem(
                'ordecTeam:amp_competition'));
            return {
                rows: rows.map(tr => tr.innerText.split('\t')),
                own: rows.map(tr => tr.classList.contains('scoreboard-own')),
                claims: window.scoreboardFake.claims.map(c => c.team),
                stored: stored, fakeRows: window.scoreboardFake.rows.length,
            };
        """)
        assert info['rows'][2][1] == 'Ohm my rename'
        assert info['own'] == [False, False, True]
        assert info['claims'] == ['taken', 'Ohm sweet Ohm', 'Ohm my']
        assert info['stored']['name'] == 'Ohm my'
        assert info['stored']['secret'] != secret
        assert info['fakeRows'] == 2

        # Solving the task pushes the score (with the source as audit trail)
        # and the polled standings pick it up. While the rebuild runs, the
        # own score is marked stale (spinner).
        lessons = web.driver.execute_script(
            "return window.courseController.course.lessons;")
        sol = courses_testdata['amp_competition'].lessons[0].solution_src(
            lessons[0])
        web.driver.execute_script(
            "window.courseController.editor.editor.setValue(arguments[0]);", sol)
        web.wait_until("""
            return document.querySelector('.scoreboard')
                .classList.contains('scoreboard-stale');
        """)
        wait_for_course_marker(web, 'solved')
        web.wait_until("""
            return !document.querySelector('.scoreboard')
                .classList.contains('scoreboard-stale');
        """)
        assert web.driver.execute_script("""
            return [...document.querySelectorAll('.lm_tab')]
                .some(t => t.innerText === 'Scoreboard');
        """)
        # The spinner only goes once the pushed score is on screen (the
        # panel refreshes right after the push instead of waiting for
        # the next poll).
        assert web.driver.execute_script("""
            return document.querySelector('.scoreboard-own').innerText;
        """).split('\t')[2].endswith(' µA')
        web.wait_until("""
            return document.querySelectorAll('.scoreboard tr')[2]
                .innerText.includes(' µA');
        """)
        push = web.driver.execute_script("""
            const pushes = window.scoreboardFake.pushes;
            return {count: pushes.length, score: pushes[1].score,
                source: pushes[1].source, svg: pushes[1].svg};
        """)
        assert push['count'] == 2
        assert 0 < push['score'] < 1000
        assert push['source'] == sol
        # The schematic travels along as a standalone SVG document.
        assert push['svg'].startswith('<svg xmlns="http://www.w3.org/2000/svg"')
        assert 'viewBox="' in push['svg'] and push['svg'].endswith('</svg>')
        assert 'mn' in push['svg'] and 'mp' in push['svg']

        # A build that fails a check pushes null: the board shows "no score"
        # again instead of the earlier passing one.
        web.driver.execute_script("""
            const editor = window.courseController.editor.editor;
            editor.setValue(editor.getValue().replace(arguments[0],
                arguments[0] + arguments[1]));
        """, '.b -- vdd; .pos=(8,10)',
            '\n        Cap cx: .$c=1p; .p -- vout; .n -- vss; .pos=(12,4)')
        wait_for_course_marker(web, 'unsolved')
        web.wait_until("""
            return !document.querySelector('.scoreboard')
                    .classList.contains('scoreboard-stale')
                && window.scoreboardFake.pushes.length === 3;
        """)
        info = web.driver.execute_script("""
            return {
                score: window.scoreboardFake.pushes[2].score,
                own: document.querySelector('.scoreboard-own').innerText,
            };
        """)
        assert info['score'] is None
        assert info['own'].split('\t')[2] == 'no score'
        web.driver.execute_script(
            "window.courseController.editor.editor.setValue(arguments[0]);", sol)
        wait_for_course_marker(web, 'solved')
        web.wait_until("return window.scoreboardFake.pushes.length === 4;")

        # Final scoring (admin-triggered on the service): the panel switches
        # to the verified ranking and pushes stop while the board is
        # frozen; back to live scores restores the standings.
        web.driver.execute_script("""
            window.scoreboardFake.final = {started: '11:00:00', result: [
                {team: 'Ohm my', verified: 30.01, fails: []},
                {team: 'Other team', verified: null,
                    fails: ['gain 3.00 < 20']},
            ]};
        """)
        web.wait_until("""
            return !!document.querySelector('.scoreboard-final');
        """)
        web.driver.execute_script("""
            const editor = window.courseController.editor.editor;
            editor.setValue(editor.getValue() + '\\n# frozen\\n');
        """)
        wait_for_course_marker(web, 'solved')
        info = web.driver.execute_script("""
            const rows = [...document.querySelectorAll('.scoreboard tr')];
            return {
                note: document.querySelector('.scoreboard-final').innerText,
                rows: rows.map(tr => tr.innerText.split('\t')),
                own: rows.map(tr => tr.classList.contains('scoreboard-own')),
                pushes: window.scoreboardFake.pushes.length,
            };
        """)
        assert info['note'].startswith('Final ranking')
        assert info['rows'] == [
            ['#', 'Team', 'Supply current', ''],
            ['1', 'Ohm my', '30.01 µA', ''],
            ['–', 'Other team', 'not ranked', 'gain 3.00 < 20'],
        ]
        assert info['own'] == [False, True, False]
        assert info['pushes'] == 4
        web.driver.execute_script("window.scoreboardFake.final = null;")
        web.wait_until("""
            return !document.querySelector('.scoreboard-final')
                && document.querySelectorAll('.scoreboard tr').length === 3;
        """)

        # A fresh guest session (the fake forgets the team) silently
        # re-claims the stored name with its secret instead of asking again.
        web.navigate('app.html#course=amp_competition')
        web.wait_for_ready()
        wait_for_course_marker(web, 'solved')
        info = web.driver.execute_script("""
            return {
                teamdialog: !!document.querySelector('#teamdialog'),
                claims: window.scoreboardFake.claims,
            };
        """)
        assert info['teamdialog'] is False
        assert info['claims'] == [{'team': 'Ohm my',
            'secret': json.loads(web.driver.execute_script(
                "return window.localStorage.getItem('ordecTeam:amp_competition');"
            ))['secret']}]
    finally:
        web.driver.execute_cdp_cmd('Page.removeScriptToEvaluateOnNewDocument',
            script)
        web.driver.execute_script(
            "window.localStorage.removeItem('ordecTeam:amp_competition');")


@pytest.mark.web
def test_course_welcome_no_tour(web):
    """The generic welcome flag without the getting_started tour: lesson 1
    of the layout tutorial auto-passes and shows the proceed callout right
    away (no spotlight to click through first)."""
    web.resize_viewport()
    web.driver.get(web.url)
    web.driver.execute_script(
        "window.localStorage.removeItem('ordecCourse:layout_tutorial');")

    web.navigate('app.html#course=layout_tutorial')
    web.wait_for_ready()
    wait_for_course_marker(web, 'solved')
    info = web.driver.execute_script("""
        return {
            success: !!document.querySelector('.course-callout-success'),
            spotlight: !!document.querySelector('.spotlight-skip'),
        };
    """)
    assert info['success'] is True
    assert info['spotlight'] is False


@pytest.mark.web
def test_course_spotlight(web):
    """The spotlight intro tour appears on every visit of the welcome
    lesson, can be stepped through in both directions, and Skip dismisses
    it for the current visit."""
    web.resize_viewport()
    reset_course_storage(web)

    web.navigate('app.html#course=getting_started')
    web.wait_for_ready()

    counter = web.driver.execute_script(
        "return document.querySelector('.spotlight-counter')?.innerText;")
    assert counter and counter.startswith('1/')
    total = int(counter.split('/')[1])

    # While the tour runs, the 'proceed to lesson 2' callout stays hidden.
    wait_for_course_marker(web, 'solved')
    assert web.driver.execute_script(
        "return !!document.querySelector('.course-callout');") is False

    # Back is disabled on the first step; after Next it leads back to it.
    nav = web.driver.execute_script("""
        const counter = () =>
            document.querySelector('.spotlight-counter').innerText;
        const back = document.querySelector('.spotlight-back');
        const res = {backDisabledAtStart: back.disabled};
        document.querySelector('.spotlight-next').click();
        res.counterAfterNext = counter();
        back.click();
        res.counterAfterBack = counter();
        return res;
    """)
    assert nav['backDisabledAtStart'] is True
    assert nav['counterAfterNext'] == f'2/{total}'
    assert nav['counterAfterBack'] == f'1/{total}'

    # Step through with Next; every step must be visited (a missing target
    # would silently skip its step), and the caption must not cover the
    # highlighted area (unless the target spans the full width, where
    # spotlight.js accepts the overlap). After the last step (whose button
    # reads "Done") the tour is gone.
    seen = []
    for _ in range(total):
        seen.append(web.driver.execute_script("""
            const counter =
                document.querySelector('.spotlight-counter').innerText;
            const cap = document.querySelector('.spotlight-caption')
                .getBoundingClientRect();
            const cut = document.querySelector('.spotlight-cutout')
                .getBoundingClientRect();
            const overlap = !(cap.right <= cut.left || cap.left >= cut.right
                || cap.bottom <= cut.top || cap.top >= cut.bottom);
            const fullWidth = cut.width > 0.9 * window.innerWidth;
            document.querySelector('.spotlight-next').click();
            return [counter, overlap && !fullWidth];
        """))
    assert [s[0] for s in seen] == [f'{i}/{total}' for i in range(1, total + 1)]
    assert [s[0] for s in seen if s[1]] == []
    assert web.driver.execute_script(
        "return !document.querySelector('.spotlight');") is True

    # Finishing the tour reveals the callout pointing at the next button.
    assert web.driver.execute_script(
        "return !!document.querySelector('.course-callout-success');") is True

    # Completion is not persisted: the tour replays on every visit of the
    # welcome lesson - after a reload (skip_tour waits for it and skips) ...
    web.navigate('app.html#course=getting_started')
    web.wait_for_ready()
    skip_tour(web)

    # ... and when navigating away and back. Skip only dismisses it for the
    # current visit.
    web.driver.execute_script(
        "document.querySelector('.course-next').click();")
    web.wait_for_ready()
    assert web.driver.execute_script(
        "return !!document.querySelector('.spotlight');") is False
    web.driver.execute_script(
        "document.querySelector('.course-prev').click();")
    web.wait_for_ready()
    skip_tour(web)


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

    qs_local = web.key.query_string_local("tests.lib.layoutgl_example", ["layoutgl_example()"])
    web.navigate(f'app.html#refreshall=true&{qs_local}')

    web.wait_for_ready()

    time.sleep(1)
    canvas=web.driver.find_element(By.CSS_SELECTOR, "canvas.layoutFit")
    png = canvas.screenshot_as_png

    #with open("screenshot.png", "wb") as f:
    #    f.write(png)
    
    img = Image.open(io.BytesIO(png))

    # The layers sidebar overlays the right edge of the canvas; the layout is
    # fitted and centered within the remaining (unobstructed) area, so crop
    # the fitted square relative to that area rather than the full canvas.
    sidebar_width = web.driver.execute_script(
        "return document.querySelector('.layout-sidebar').offsetWidth")
    avail = img.width - sidebar_width
    fit = min(avail, img.height)
    left = (avail - fit)/2
    top = (img.height - fit)/2
    margin = 25

    img = img.crop([left+margin, top+margin, left+fit-margin, top+fit-margin])
    img = img.resize([512, 512], Image.Resampling.NEAREST)

    expect_blue  = img.crop((0, 0, 256, 128))
    assert myhistogram(expect_blue)[(16, 71, 139)] > 20000

    expect_text  = img.crop((128, 256-32, 256+128, 256+32))
    assert myhistogram(expect_text)[(255,255,255)] > 100
    
    expect_red   = img.crop((256, 256+32, 256+128, 256+32+64))
    assert myhistogram(expect_red)[(89, 0, 0)] > 5000
    
    expect_black = img.crop((256, 256+128, 256+64, 256+128+64))
    assert myhistogram(expect_black)[(0, 0, 0)] > 2000


SLOW_VIEW_SRC = '''
from ordec.core import *
import time

@viewgen_noctx
def slow():
    for i in range(100):
        progress(f"step {i}", i/100)
        time.sleep(0.05)
    return "slow result"
'''

@pytest.mark.web
def test_progress_and_cancel(web):
    """Progress bar, cancel button and cancelled-state overlay of a slow
    view generator."""
    web.resize_viewport()
    web.navigate('app.html#example=blank')
    web.wait_for_ready()

    # Replace the source with a slow view and reconnect.
    web.driver.execute_script("""
        window.ordecApp.client.src = arguments[0];
        window.ordecApp.client.connect();
    """, SLOW_VIEW_SRC)
    web.wait_for_ready()

    def rv_js(script):
        return web.driver.execute_script(
            "let rv = window.ordecApp.client.resultViewers[0];" + script)

    rv_js("rv._onViewSelected('slow()');")

    # Progress message and bar appear.
    web.wait_until(
        "return window.ordecApp.client.resultViewers[0]"
        ".refreshStatus.textContent.startsWith('step');")
    web.wait_until(
        "return parseFloat(window.ordecApp.client.resultViewers[0]"
        ".refreshProgressFill.style.width) > 0;")

    # Cancel via the overlay's cancel button. (The transient "Cancelling…"
    # label is not asserted: the cancelled terminal may arrive faster than
    # the next poll.)
    rv_js("rv.refreshCancel.click();")
    web.wait_until(
        "return window.ordecApp.client.resultViewers[0].generationCancelled;")
    assert rv_js("return rv.refreshableText.textContent;") \
        == "View generation cancelled."
    web.wait_for_ready()  # no re-request of the cancelled view

    # The overlay's Refresh button retries and the view now loads fully
    # (result is a str, shown as preformatted Report).
    rv_js("rv.resOverlayRefreshable.querySelector('button').click();")
    web.wait_until(
        "return window.ordecApp.client.resultViewers[0].viewUpToDate;",
        timeout=30)
    assert "slow result" in rv_js("return rv.testInfo().html;")


@pytest.mark.web
def test_view_removed_deselects(web):
    """A viewer whose selected view disappears from a fresh viewlist (e.g.
    its cell was renamed in the sources) is fully deselected: the stale
    render must not linger behind the "Select a view" placeholder. A build
    exception, in contrast, must keep the selection."""
    named_view_src = '''
from ordec.core import *

@viewgen_noctx
def {name}():
    return "{name} result"
'''

    web.resize_viewport()
    web.navigate('app.html#example=blank')
    web.wait_for_ready()

    def rv_js(script):
        return web.driver.execute_script(
            "let rv = window.ordecApp.client.resultViewers[0];" + script)

    def set_src(src):
        web.driver.execute_script("""
            window.ordecApp.client.src = arguments[0];
            window.ordecApp.client.connect();
        """, src)

    set_src(named_view_src.format(name='before'))
    web.wait_for_ready()
    rv_js("rv._onViewSelected('before()');")
    web.wait_until(
        "return window.ordecApp.client.resultViewers[0].viewUpToDate;",
        timeout=30)
    assert "before result" in rv_js("return rv.testInfo().html;")

    # A module build exception keeps the (stale) view list and selection.
    set_src("this is a syntax error(")
    web.wait_until("return window.ordecApp.client.exception;")
    assert rv_js("return rv.viewSelected;") == 'before()'

    # "Rename" the view: the fresh viewlist no longer contains before().
    set_src(named_view_src.format(name='after'))
    web.wait_for_ready()
    web.wait_until(
        "return window.ordecApp.client.resultViewers[0].viewSelected === null;")
    assert "before result" not in rv_js("return rv.testInfo().html;")
    assert rv_js("return getComputedStyle(rv.resEmpty).display;") != 'none'
    assert rv_js("return rv.restoreSelectedView;") is None

@pytest.mark.web
def test_structured_traceback(web):
    """Build errors annotate the failing line in the editor's gutter, the
    structured traceback's frame links jump the editor to the frame's line,
    and a successful rebuild clears the annotation again."""
    web.resize_viewport()
    web.navigate('app.html#example=blank')
    web.wait_for_ready()

    def editor_js(script, *args):
        return web.driver.execute_script("""
            const ed = window.ordecApp.layout.root.getAllContentItems()
                .find(i => i.isComponent && i.componentName === 'editor')
                .component.editor;
        """ + script, *args)

    # Set the source through the editor (not client.src directly): the
    # frame links must jump within the document the editor actually shows.
    def set_src(src):
        editor_js("ed.setValue(arguments[0]); ed.clearSelection();", src)

    set_src("def boom():\n    raise ValueError('nope')\nboom()\n")
    web.wait_until("return window.ordecApp.client.exception;")
    assert editor_js("return ed.session.getAnnotations();") == [
        {'row': 1, 'column': 0, 'type': 'error', 'text': 'ValueError: nope'}]

    # Two frames (module level and boom()); clicking the first jumps the
    # editor cursor to its line 3 (row 2).
    web.wait_until(
        "return document.querySelectorAll('.exc-frame-link').length;")
    web.driver.execute_script(
        "document.querySelector('.exc-frame-link').click();")
    assert editor_js("return ed.getCursorPosition().row;") == 2

    set_src("x = 1\n")
    web.wait_until("return !window.ordecApp.client.exception;")
    web.wait_for_ready()
    assert editor_js("return ed.session.getAnnotations();") == []

@pytest.mark.web
def test_local_multiple_views(web):
    """Each --view opens a result viewer of its own, side by side."""
    web.resize_viewport()

    views = ["schematic()", "lvs_report()"]
    qs_local = web.key.query_string_local("tests.lib.lvs_example", views)
    web.navigate(f'app.html#refreshall=true&{qs_local}')

    web.wait_for_ready()

    viewers = web.driver.execute_script("""
        return window.ordecApp.client.resultViewers.map(rv => {
            const r = rv.container.element.getBoundingClientRect();
            return {view: rv.viewSelected, top: r.top, left: r.left};
        });
    """)
    assert [v['view'] for v in viewers] == views
    assert viewers[0]['top'] == viewers[1]['top']
    assert viewers[0]['left'] < viewers[1]['left']
