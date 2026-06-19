# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for course mode: the /api/course endpoint and the intro course
content (skeleton lessons must fail their checks, solutions must pass).
"""

import json
import pytest

from ordec.server import StaticHandler
from ordec.language import compile_ord


def course_data(name='intro'):
    resp = StaticHandler().process_request_course(name)
    return json.loads(resp.body.decode('utf8'))


def run_lesson(lesson, src=None):
    """Compiles and executes lesson source, returns the module namespace.

    Mirrors the server: after the lesson source, the check epilogue
    (lesson['check_src']) is executed separately in the same namespace so that
    the lesson() view is available, just like build_cells does.
    """
    if src is None:
        src = lesson['src']
    ns = {}
    if lesson['srctype'] == 'ord':
        code = compile_ord(src, ns, lesson['file'])
    else:
        code = compile(src, lesson['file'], 'exec')
    exec(code, ns)
    exec(compile(lesson['check_src'], '<lesson-check>', 'exec'), ns)
    return ns


def report_passfails(report):
    elements = [e.element_webdata() for e in report.elements()]
    return [e for e in elements if e['element_type'] == 'passfail']


def solution_src(lesson, skeleton_part, solution_part):
    assert skeleton_part in lesson['src']
    return lesson['src'].replace(skeleton_part, solution_part)


def test_course_endpoint():
    data = course_data()
    assert data['name'] == 'intro'
    assert data['title']
    assert len(data['lessons']) == 3
    for lesson in data['lessons']:
        assert lesson['srctype'] in ('ord', 'python')
        assert lesson['src']
        assert lesson['title']
        assert 'root' in lesson['uistate']


def test_course_unknown():
    with pytest.raises(Exception, match='not found'):
        StaticHandler().process_request_course('nonexistent')
    # Course lookup must not be a path traversal vector:
    with pytest.raises(Exception, match='not found'):
        StaticHandler().process_request_course('../examples')


@pytest.mark.parametrize('lesson_index', [0, 1, 2])
def test_lesson_executes(lesson_index):
    """All lesson sources must compile and execute (without view evaluation)."""
    data = course_data()
    ns = run_lesson(data['lessons'][lesson_index])
    assert 'lesson' in ns


def test_lesson1_skeleton_fails():
    data = course_data()
    report = run_lesson(data['lessons'][0])['lesson']()
    passfails = report_passfails(report)
    assert len(passfails) == 1
    assert not passfails[0]['passed']
    assert passfails[0]['hint']


def test_lesson1_solution_passes():
    data = course_data()
    skeleton_part = ".$c=1n"
    solution_part = ".$c=16n"
    src = solution_src(data['lessons'][0], skeleton_part, solution_part)
    report = run_lesson(data['lessons'][0], src)['lesson']()
    passfails = report_passfails(report)
    assert len(passfails) == 1
    assert passfails[0]['passed']


def test_lesson2_skeleton_fails():
    data = course_data()
    report = run_lesson(data['lessons'][1])['lesson']()
    passfails = report_passfails(report)
    assert len(passfails) == 4
    # The inverter skeleton implements the wrong function only for a=1, b=0:
    assert [p['passed'] for p in passfails] == [True, True, False, True]


def test_lesson2_solution_passes():
    data = course_data()
    skeleton_part = """\
        # TODO: Turn this inverter into a NAND2 gate.
        Nmos n1: .pos=(4,1); .s -- vss; .d -- y; .g -- a; .b -- vss
        Pmos p1: .pos=(4,14); .s -- vdd; .d -- y; .g -- a; .b -- vdd

        # Set width and length parameters for all transistors:
        for t in p1, n1:
"""
    solution_part = """\
        net x
        Nmos n1: .pos=(4,1); .s -- vss; .d -- x; .g -- a; .b -- vss
        Nmos n2: .pos=(4,7); .s -- x; .d -- y; .g -- b; .b -- vss
        Pmos p1: .pos=(4,14); .s -- vdd; .d -- y; .g -- a; .b -- vdd
        Pmos p2: .pos=(12,14); .s -- vdd; .d -- y; .g -- b; .b -- vdd

        for t in p1, p2, n1, n2:
"""
    src = solution_src(data['lessons'][1], skeleton_part, solution_part)
    report = run_lesson(data['lessons'][1], src)['lesson']()
    passfails = report_passfails(report)
    assert len(passfails) == 4
    assert all(p['passed'] for p in passfails)


def test_lesson3_skeleton_fails():
    data = course_data()
    report = run_lesson(data['lessons'][2])['lesson']()
    passfails = report_passfails(report)
    assert len(passfails) == 2
    assert passfails[0]['label'] == 'LVS clean'
    assert not passfails[0]['passed']
    # The skeleton itself must be DRC clean, so that only the missing
    # routing keeps the user from passing:
    assert passfails[1]['label'] == 'DRC clean'
    assert passfails[1]['passed']


def test_lesson3_solution_passes():
    data = course_data()
    skeleton_part = """\
        # TODO: Add the three missing Metal1 routes here. Example for the
        # vdd route (from the vdd stub to the PMOS source):
        #
        # sr = SRouter(SG13G2().default_routing_spec)
        # sr.move(layers.Metal1, (-630, 2760))
        # sr.wire((150, 2760))
"""
    solution_part = """\
        sr = SRouter(SG13G2().default_routing_spec)
        sr.move(layers.Metal1, (-630, 2760))
        sr.wire((150, 2760))
        sr.move(layers.Metal1, (-630, 260))
        sr.wire((150, 260))
        sr.move(layers.Metal1, (660, 1280))
        sr.wire((660, 2780))
"""
    src = solution_src(data['lessons'][2], skeleton_part, solution_part)
    report = run_lesson(data['lessons'][2], src)['lesson']()
    passfails = report_passfails(report)
    assert len(passfails) == 2
    assert all(p['passed'] for p in passfails)
