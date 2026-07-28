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

            Res R0:
                .$r=2k
                .pos=(5, 6)
                .m -- vss
                .p -- mid

            Res R1:
                .$r=3k
                .pos=(11,6)
                .m -- vss
                .p -- mid

            Res R2:
                .$r=1k
                .pos=(8, 12)
                .m -- mid
                .p -- vdd
            """),
        ]),
        # Lesson 5: wiring with for loops (enforced by the checks via
        # bytecode analysis of the schematic viewgen).
        LessonTestdata(passfails=2, solution=[
            InsertSolution("""
            # EDIT HERE
            """, """
            for r in R0, R1, R2:
                r.p -- mid
            for r in R0, R1:
                r.m -- vss
            R2.m -- vdd
            """),
        ]),
        # Lesson 6: LC bandstop filter. On the skeleton, the all-wired check
        # passes trivially (only the fully wired source and ground exist).
        LessonTestdata(passfails=4,
            skeleton_passed=[False, False, True, False],
            solution=[
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
            port vin: .align=East
            port vout: .align=West; .pos=(12,18)
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
                .simulate().tran(1u, 3m)
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
            from itertools import pairwise
            n_pulses = sum(1 for a, b in pairwise(sim.vout.voltage) if a <= 0.5 < b)
            .markdown(f"Counted {n_pulses} pulses.")

            it = zip(sim.time, sim.vout.voltage)
            rise_start = next(t for t, v in it if v >= 0.1)
            rise_end = next(t for t, v in it if v >= 0.9)
            rise_time = R(f"{rise_end - rise_start:.3g}")
            .markdown(f"Rise time: {rise_time}")
            """),
        ]),
        # Epilogue: task-free what's-next report closing the course.
        LessonTestdata(),
    ]),
    # The under-construction course has a single instruction-only dummy
    # lesson; without PassFail elements, it can never be marked solved.
    'cmos_circuits': CourseTestdata('CMOS Integrated Circuits',
        [LessonTestdata()]),
    'layout_tutorial': CourseTestdata('Layout Tutorial', [
        # Lesson 1 is a task-free welcome lesson (generic 'welcome' flag).
        LessonTestdata(),
        # Lesson 2: rectangles with absolute coordinates.
        LessonTestdata(passfails=3, solution=[
            InsertSolution("""
            # EDIT HERE
            """, """
            LayoutRect m2: .layer=layers.Metal2; .rect=(0, 900, 3000, 1400)
            LayoutRect act: .layer=layers.Activ; .rect=(500, 2000, 1500, 2600)
            LayoutRect gp: .layer=layers.GatPoly; .rect=(2000, 2000, 2200, 2900)
            """),
        ]),
        # Lesson 3: equality constraints and anchors (bridge, centered pad).
        LessonTestdata(passfails=4, solution=[
            InsertSolution("""
            # EDIT HERE (bridge)
            """, """
            LayoutRect bridge:
                .layer = layers.Metal1
                ! .west == pad_w.east
                ! .east == pad_e.west
                ! .height == 400
            """),
            InsertSolution("""
            # EDIT HERE (center)
            """, """
            LayoutRect pad_c:
                .layer = layers.Metal1
                ! .size == (800, 800)
                ! .ly == pad_w2.ly
                ! .lx - pad_w2.ux == pad_e2.lx - .ux
            """),
        ]),
        # Lesson 4: inequalities, even spacing, weighted centering.
        LessonTestdata(passfails=4, solution=[
            InsertSolution("""
            # EDIT HERE (pads)
            """, """
            LayoutRect p1: .layer=layers.Metal2; ! .size==(800,400); ! .ly==base.uy+300
            LayoutRect p2: .layer=layers.Metal2; ! .size==(800,400); ! .ly==base.uy+300
            LayoutRect p3: .layer=layers.Metal2; ! .size==(800,400); ! .ly==base.uy+300

            ! p1.lx >= base.lx + 400
            ! p2.lx - p1.ux == p3.lx - p2.ux
            ! p3.ux <= base.ux - 400
            ! p2.cx == 0.5*base.lx + 0.5*base.ux
            """),
        ]),
        # Lesson 5: SRouter obstacle crossing.
        LessonTestdata(passfails=3, solution=[
            InsertSolution("""
            # EDIT HERE (route)
            """, """
            sr = SRouter(SG13G2().default_routing_spec)
            sr.move(layers.Metal1, pad_w.center)
            sr.wire_x(obstacle.lx - 500)
            sr.layer(layers.Metal2)
            sr.wire_x(obstacle.ux + 500)
            sr.layer(layers.Metal1)
            sr.wire_x(pad_e.cx)
            """),
        ]),
        # Lesson 6: inverter device column.
        LessonTestdata(passfails=4, solution=[
            InsertSolution("""
            # EDIT HERE (devices)
            """, """
            Nmos(w=1u, l=130n) mn:
                ! .pos == (0, 0)
            Pmos(w=1u, l=130n) mp:
                ! .pos.x == mn.pos.x
                ! .pos.y == mn.pos.y + 2500
            Ptap(l=0.7u, w=0.7u) ptap:
                ! .activ.cx == mn.activ.cx
                ! .activ.uy + 600 == mn.poly[0].ly
            Ntap(l=0.7u, w=0.7u) ntap:
                ! .activ.cx == mp.activ.cx
                ! .activ.ly - 600 == mp.poly[0].uy
            """),
        ]),
        # Lesson 7: inverter wiring (gate bar, output, rails, nwell).
        LessonTestdata(passfails=5, solution=[
            InsertSolution("""
            # EDIT HERE (gate)
            """, """
            LayoutRect polybar:
                .layer = layers.GatPoly
                ! .south == mn.poly[0].north
                ! .north == mp.poly[0].south
                ! .width == mn.poly[0].width
            """),
            InsertSolution("""
            # EDIT HERE (output)
            """, """
            sr = SRouter(SG13G2().default_routing_spec)
            sr.move(layers.Metal1, mn.sd[1].center)
            sr.wire_y(mp.sd[1].cy)
            """),
            InsertSolution("""
            # EDIT HERE (power)
            """, """
            LayoutRect m1_vss:
                .layer = layers.Metal1
                ! .height == 160
                ! .cy == ptap.m1.cy
                ! .lx == mn.activ.lx - 400
                ! .ux == mn.activ.ux + 400
            LayoutRect m1_vdd:
                .layer = layers.Metal1
                ! .height == 160
                ! .cy == ntap.m1.cy
                ! .lx == mp.activ.lx - 400
                ! .ux == mp.activ.ux + 400
            sr.move(layers.Metal1, mn.sd[0].center)
            sr.wire_y(m1_vss.cy)
            sr.move(layers.Metal1, mp.sd[0].center)
            sr.wire_y(m1_vdd.cy)
            LayoutRect nwell:
                .layer = layers.NWell
                ! .contains(mp.nwell.rect)
                ! .contains(ntap.nwell.rect)
            """),
        ]),
        # Lesson 8: input contact and DRC (skeleton runs KLayout on the
        # planted rail-width violation).
        LessonTestdata(passfails=5, solution=[
            InsertSolution("""
            # EDIT HERE (input)
            """, """
            LayoutRect polyext:
                .layer = layers.GatPoly
                ! .size == (500, 500)
                ! .east == polybar.west
            LayoutRect polycont:
                .layer = layers.Cont
                ! .size == (160, 160)
                ! .center == polyext.center
            LayoutRect m1_a:
                .layer = layers.Metal1
                ! .y_extent == polycont.y_extent
                ! .ux == polycont.ux + 200
                ! .width == 1500
            """),
            InsertSolution("""
            ! .height == 100  # EDIT HERE (rail height)
            """, """
            ! .height == 160
            """),
        ]),
        # Lesson 9: pins and LVS.
        LessonTestdata(passfails=3, solution=[
            InsertSolution("""
            # EDIT HERE (a pin)
            """, """
            .create_pin(self.symbol.a)
            """),
            InsertSolution("""
            # EDIT HERE (y pin)
            """, """
            sr.path.create_pin(self.symbol.y)
            """),
            InsertSolution("""
            # EDIT HERE (vdd pin)
            """, """
            .create_pin(self.symbol.vdd)
            """),
            InsertSolution("""
            # EDIT HERE (vss pin)
            """, """
            .create_pin(self.symbol.vss)
            """),
        ]),
        # Lesson 10: matched diff pair row and inn gate comb.
        LessonTestdata(passfails=4, solution=[
            InsertSolution("""
            # EDIT HERE (row)
            """, """
            unit m1a:
                ! .pos == (0, 0)
            unit m2a:
                ! .sd[0].center == m1a.sd[1].center
                ! .pos.y == m1a.pos.y
            unit m2b:
                ! .sd[0].center == m2a.sd[1].center
                ! .pos.y == m1a.pos.y
            unit m1b:
                ! .sd[0].center == m2b.sd[1].center
                ! .pos.y == m1a.pos.y
            """),
            InsertSolution("""
            # EDIT HERE (gates)
            """, """
            LayoutRect inn_bar:
                .layer = layers.GatPoly
                ! .lx == m2a.poly[0].lx
                ! .ux == m2b.poly[0].ux
                ! .ly == m2a.poly[0].uy + 250
                ! .height == 130
            LayoutRect inn_drop_a:
                .layer = layers.GatPoly
                ! .x_extent == m2a.poly[0].x_extent
                ! .uy == inn_bar.uy
                ! .ly == m2a.poly[0].uy - 100
            LayoutRect inn_drop_b:
                .layer = layers.GatPoly
                ! .x_extent == m2b.poly[0].x_extent
                ! .uy == inn_bar.uy
                ! .ly == m2b.poly[0].uy - 100
            LayoutRect inn_ext:
                .layer = layers.GatPoly
                ! .size == (500, 500)
                ! .south == inn_bar.north
            LayoutRect inn_cont:
                .layer = layers.Cont
                ! .size == (160, 160)
                ! .center == inn_ext.center
            LayoutRect m1_inn:
                .layer = layers.Metal1
                ! .center == inn_cont.center
                ! .size == (500, 200)
            """),
        ]),
        # Lesson 11: routing, pins, DRC and LVS signoff (solution runs
        # KLayout twice).
        LessonTestdata(passfails=5, solution=[
            InsertSolution("""
            # EDIT HERE (route)
            """, """
            sr = SRouter(SG13G2().default_routing_spec)
            sr.move(layers.Metal1, m1a.sd[1].center)
            sr.wire_y(m1a.pos.y - 600)
            sr.wire_x(m2b.sd[1].cx)
            sr.wire_y(m2b.sd[1].cy)
            sr.path.create_pin(self.symbol.tail)
            sr.move(layers.Metal1, m1a.sd[0].center)
            sr.wire_y(m1a.pos.y + 2400)
            sr.layer(layers.Metal2)
            sr.wire_x(m1b.sd[1].cx)
            sr.path.create_pin(self.symbol.outn)
            sr.layer(layers.Metal1)
            sr.wire_y(m1b.sd[1].cy)
            """),
            InsertSolution("""
            # EDIT HERE (pins)
            """, """
            LayoutRect m1_outp:
                .layer = layers.Metal1
                ! .rect == m2a.sd[1].rect
                .create_pin(self.symbol.outp)
            m1_inp.create_pin(self.symbol.inp)
            m1_inn.create_pin(self.symbol.inn)
            m1_vss.create_pin(self.symbol.vss)
            """),
        ]),
        # Epilogue: task-free what's-next report closing the course.
        LessonTestdata(),
    ]),
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
    # The generic flags (welcome: task-free opening lesson, solved right
    # away; epilogue: task-free closing lesson) must be passed through to
    # exactly the first/last lessons of getting_started and layout_tutorial.
    # The getting_started-specific flags (lesson 1: spotlight tour; lesson
    # 2: passed by opening result viewers, detected in the frontend) must
    # appear on exactly the first two getting_started lessons.
    for name in ('getting_started', 'layout_tutorial'):
        data = course_data(name)
        n = len(data['lessons'])
        assert [l['welcome'] for l in data['lessons']] == \
            [True] + [False] * (n - 1)
        assert [l['epilogue'] for l in data['lessons']] == \
            [False] * (n - 1) + [True]

    data = course_data()
    n = len(data['lessons'])
    assert [l['getting_started_lesson_1'] for l in data['lessons']] == \
        [True] + [False] * (n - 1)
    assert [l['getting_started_lesson_2'] for l in data['lessons']] == \
        [False, True] + [False] * (n - 2)

    for name in ('cmos_circuits', 'layout_tutorial'):
        for lesson in course_data(name)['lessons']:
            assert not lesson['getting_started_lesson_1']
            assert not lesson['getting_started_lesson_2']
    for lesson in course_data('cmos_circuits')['lessons']:
        assert not lesson['welcome']
        assert not lesson['epilogue']


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
