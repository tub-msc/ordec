# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for course mode: the /api/course endpoint and the course content
(skeleton lessons must fail their checks, solutions must pass).

The tests in this file do not go through the webui: lesson sources and check
epilogues are compiled and executed directly, mirroring what the server's
build_cells does. The end-to-end test of the course webui (navigator, lesson
gating, pass detection in the browser) is test_web.py::test_course.
"""

import json
import re
import textwrap
from dataclasses import dataclass

import pytest

from ordec.server import StaticHandler
from ordec.language import compile_ord

@dataclass
class InsertSolution:
    """
    One edit the user is asked to make: skeleton is the '# EDIT HERE' marker
    as it appears in the shipped lesson source (test contract: it is
    literal-replaced), solution is the code that replaces it. Both are
    written dedented; apply() detects the indentation of the skeleton in the
    lesson source and reindents both accordingly.
    """
    skeleton: str
    solution: str

    def __post_init__(self):
        # Dedent here, re-indent later:
        self.skeleton = textwrap.dedent(self.skeleton.lstrip('\n'))
        self.solution = textwrap.dedent(self.solution.lstrip('\n'))

    def apply(self, src):
        first_line = self.skeleton.splitlines()[0]
        m = re.search('^([ \t]*)' + re.escape(first_line) + '$', src,
            re.MULTILINE)
        assert m, f'skeleton not found in lesson source: {first_line!r}'
        skeleton = textwrap.indent(self.skeleton, m.group(1))
        assert skeleton in src
        return src.replace(skeleton, textwrap.indent(self.solution, m.group(1)))


@dataclass
class LessonTestdata:
    """
    Declarative test expectations for one lesson.

    solution lists the InsertSolution edits that turn the shipped skeleton
    into the correct solution, which must make all checks pass.

    Lessons without a solution (welcome lesson, frontend-checked lessons,
    dummy lessons of under-construction courses) just state their expected
    PassFail count: 0 means the report alone can never mark the lesson
    solved.
    """
    passfails: int = 0
    solution: list = ()
    # Expected per-check results on the unmodified skeleton (default: all
    # checks fail).
    skeleton_passed: list = None
    has_svg: bool = False

    def __post_init__(self):
        if self.skeleton_passed is None:
            self.skeleton_passed = [False] * self.passfails

    def solution_src(self, lesson):
        src = lesson['src']
        for edit in self.solution:
            src = edit.apply(src)
        return src


@dataclass
class CourseTestdata:
    title: str
    lessons: list


courses_testdata = {
    'getting_started': CourseTestdata('Getting Started', [
        # Lesson 1 (welcome) and lesson 2 (open result viewers) are handled
        # by the frontend; their reports are instruction-only.
        LessonTestdata(),
        LessonTestdata(),
        # Lesson 3: instantiating a resistor. The instance name is the
        # user's choice; the checks match by value/position.
        LessonTestdata(passfails=4, solution=[
            InsertSolution("""
            # EDIT HERE
            """, """
            Res r1: .$r=1k; .m -- vss; .p -- vdd; .pos=(5,6)
            """),
        ]),
        # Lesson 4: resistor network.
        LessonTestdata(passfails=6, solution=[
            InsertSolution("""
            # EDIT HERE
            """, """
            net mid
            Res r1: .$r=1k; .p -- vdd; .m -- mid; .pos=(5,12)
            Res r2: .$r=2k; .p -- mid; .m -- vss; .pos=(5,6)
            Res r3: .$r=3k; .p -- mid; .m -- vss; .pos=(10,6)
            """),
        ]),
        # Lesson 5: wiring with for loops (enforced by the checks via
        # bytecode analysis of the schematic viewgen).
        LessonTestdata(passfails=2, solution=[
            InsertSolution("""
            # EDIT HERE
            """, """
            for r in r1, r2, r3:
                r.p -- mid
            for r in r2, r3:
                r.m -- vss
            r1.m -- vdd
            """),
        ]),
        # Lesson 6: LC bandstop filter. The target-schematic sketch must
        # render as an SVG element. On the skeleton, the all-wired check
        # passes trivially (only the fully wired source and ground exist).
        LessonTestdata(passfails=4,
            skeleton_passed=[False, False, True, False],
            has_svg=True, solution=[
            InsertSolution("""
            # EDIT HERE
            """, """
            net mid
            Res r1: .$r=1k; .p -- vin; .m -- vout; .pos=(8,16); .orientation=R90
            Ind l1: .$l=1m; .pos=(8,11); .m -- mid; .p -- vout
            Cap c1: .$c=100n; .pos=(8,6); .p -- mid; .m -- vss
            """),
        ]),
        # Lesson 7: subcells.
        LessonTestdata(passfails=5, solution=[
            InsertSolution("""
            pass  # EDIT HERE (symbol)
            """, """
            input vin: .align=West
            output vout: .align=East
            inout vss: .align=South
            """),
            InsertSolution("""
            # EDIT HERE (schematic)
            """, """
            port vin: .align=East; .pos=(2,18)
            port vout: .align=West
            port vss: .align=North

            r1.p -- vin
            r1.m -- vout
            l1.p -- vout
            c1.m -- vss
            """),
            InsertSolution("""
            # EDIT HERE (testbench)
            """, """
            Bandstop dut: .pos=(6,9); .vin -- vin; .vout -- vout; .vss -- vss
            """),
        ]),
        # Lesson 8: parameters.
        LessonTestdata(passfails=5, solution=[
            InsertSolution("""
            # EDIT HERE (parameter)
            """, """
            freq = Parameter(R, default=15.9k)
            """),
            InsertSolution("""
            .$l=10m # EDIT HERE (parameter calculation)
            """, """
            .$l=1 / ((2 * math.pi * float(self.freq))**2 * 10e-9)
            """),
            InsertSolution("""
            # EDIT HERE (testbench)
            Bandstop f0:
                .pos=(6,9)
                .vin -- vin
                .vout -- vout
                .vss -- vss
            """, """
            net vmid
            Bandstop flt1:
                .pos=(6,9)
                .$freq=5k
                .vin -- vin
                .vout -- vmid
                .vss -- vss
            Bandstop flt2:
                .pos=(12,9)
                .$freq=50k
                .vin -- vmid
                .vout -- vout
                .vss -- vss
            """),
        ]),
        # Lesson 9: transient analysis and reports.
        LessonTestdata(passfails=5, solution=[
            InsertSolution("""
            # EDIT HERE (analysis)
            """, """
            viewgen sim_tran -> Simulation:
                .simulate().tran('1u', '2m')
            """),
            InsertSolution("""
            # EDIT HERE (report)
            """, """
            viewgen report -> Report:
                sim = self.sim_tran
                .markdown("Step response of the two RC stages.")
                PlotGroup grp
                .plot2d(x=sim.time, series={'vin': sim.vin.voltage},
                    xlabel="Time (s)", ylabel="Voltage (V)", height=200,
                    plot_group=grp)
                .plot2d(x=sim.time,
                    series={'mid': sim.mid.voltage, 'vout': sim.vout.voltage},
                    xlabel="Time (s)", ylabel="Voltage (V)", height=200,
                    plot_group=grp)
            """),
        ]),
        # Lesson 10: postprocessing.
        LessonTestdata(passfails=2, solution=[
            InsertSolution("""
            # EDIT HERE (postprocessing)
            """, """
            t = [float(x) for x in sim.time]
            vin = list(sim.vin.voltage)
            vout = list(sim.vout.voltage)

            pulses = sum(1 for a, b in zip(vin, vin[1:]) if a < 0.5 <= b)
            .markdown(f"**{pulses} pulses** counted on vin.")

            def crossings(v, level):
                up = [t[i] for i in range(len(v) - 1) if v[i] < level <= v[i+1]]
                down = [t[i] for i in range(len(v) - 1) if v[i] > level >= v[i+1]]
                return up, down
            up10, down10 = crossings(vout, 0.1)
            up90, down90 = crossings(vout, 0.9)
            .markdown(f"vout rise time (10-90%): {(up90[0]-up10[0])*1e6:.0f} us, "
                f"fall time: {(down10[0]-down90[0])*1e6:.0f} us.")
            """),
        ]),
    ]),
    # The under-construction courses have a single instruction-only dummy
    # lesson; without PassFail elements, it can never be marked solved.
    'cmos_circuits': CourseTestdata('CMOS Integrated Circuits',
        [LessonTestdata()]),
    'layout_tutorial': CourseTestdata('Layout Tutorial',
        [LessonTestdata()]),
}


def lesson_params(with_solution=False):
    for course_name, course in courses_testdata.items():
        for i, testdata in enumerate(course.lessons):
            if with_solution and not testdata.solution:
                continue
            yield pytest.param(course_name, i, testdata,
                id=f'{course_name}-{i}')


def course_data(name='getting_started'):
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


@pytest.mark.parametrize('name,course', courses_testdata.items(),
    ids=courses_testdata.keys())
def test_course_endpoint(name, course):
    data = course_data(name)
    assert data['name'] == name
    assert data['title'] == course.title
    assert len(data['lessons']) == len(course.lessons)
    for lesson in data['lessons']:
        assert lesson['srctype'] in ('ord', 'python')
        assert lesson['src']
        assert lesson['title']
        assert 'root' in lesson['uistate']


def test_course_special_lesson_flags():
    # The hard flags for the two special lessons (welcome lesson: solved
    # right away + spotlight tour; viewer lesson: passed by opening result
    # viewers, detected in the frontend) must be passed through to exactly
    # the first two getting_started lessons.
    data = course_data()
    assert [l['getting_started_lesson_1'] for l in data['lessons']] == \
        [True, False, False, False, False, False, False, False, False, False]
    assert [l['getting_started_lesson_2'] for l in data['lessons']] == \
        [False, True, False, False, False, False, False, False, False, False]
    for name in ('cmos_circuits', 'layout_tutorial'):
        for lesson in course_data(name)['lessons']:
            assert not lesson['getting_started_lesson_1']
            assert not lesson['getting_started_lesson_2']


def test_course_unknown():
    with pytest.raises(Exception, match='not found'):
        StaticHandler().process_request_course('nonexistent')
    # Course lookup must not be a path traversal vector:
    with pytest.raises(Exception, match='not found'):
        StaticHandler().process_request_course('../examples')


@pytest.mark.parametrize('course_name,lesson_index,testdata', lesson_params())
def test_lesson_skeleton(course_name, lesson_index, testdata):
    """
    Every shipped lesson must execute as-is and its report must show the
    expected check state (usually: all checks failing, each with a hint).
    """
    lesson = course_data(course_name)['lessons'][lesson_index]
    report = run_lesson(lesson)['lesson']()
    elements = [e.element_webdata() for e in report.elements()]
    passfails = [e for e in elements if e['element_type'] == 'passfail']
    assert [p['passed'] for p in passfails] == testdata.skeleton_passed
    assert all(p['hint'] for p in passfails if not p['passed'])
    if testdata.has_svg:
        assert any(e['element_type'] == 'svg' for e in elements)


@pytest.mark.parametrize('course_name,lesson_index,testdata',
    lesson_params(with_solution=True))
def test_lesson_solution(course_name, lesson_index, testdata):
    """The solution must make all checks of its lesson pass."""
    lesson = course_data(course_name)['lessons'][lesson_index]
    src = testdata.solution_src(lesson)
    report = run_lesson(lesson, src)['lesson']()
    elements = [e.element_webdata() for e in report.elements()]
    passfails = [e for e in elements if e['element_type'] == 'passfail']
    assert len(passfails) == testdata.passfails
    assert all(p['passed'] for p in passfails)
