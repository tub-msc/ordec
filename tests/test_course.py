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
            Res r1: .$r=1k; .n -- vss; .p -- vdd; .pos=(5,6)
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
                .n -- vss
                .p -- mid

            Res R1:
                .$r=3k
                .pos=(11,6)
                .n -- vss
                .p -- mid

            Res R2:
                .$r=1k
                .pos=(8, 12)
                .n -- mid
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
                r.n -- vss
            R2.n -- vdd
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
            Res r1: .$r=1k; .p -- vin; .n -- vout; .pos=(8,16); .orientation=R90
            Ind l1: .$l=1m; .pos=(8,11); .n -- mid; .p -- vout
            Cap c1: .$c=100n; .pos=(8,6); .p -- mid; .n -- vss
            """),
        ]),
        # Lesson 7: subcells.
        LessonTestdata(passfails=5, solution=[
            InsertSolution("""
            pass  # EDIT HERE (symbol)
            """, """
            input vin
            output vout
            inout vss
            """),
            InsertSolution("""
            # EDIT HERE (schematic)
            """, """
            port vin
            port vout: .pos=(12,18)
            port vss

            r1.p -- vin
            r1.n -- vout
            l1.p -- vout
            c1.n -- vss
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
            viewgen sim_tran(self) -> Simulation:
                .simulate().tran(1u, 3m)
            """),
            InsertSolution("""
            # EDIT HERE (report)
            """, """
            viewgen report(self) -> Report:
                sim = self.sim_tran
                .markdown("Step response of the two RC stages.")
                PlotGroup grp
                .plot2d(sim.time, sim.vin, group=grp)
                .plot2d(sim.time, sim.mid, sim.vout, group=grp)
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
        # Lesson 4: inequality clearances (binding bound) and shrink-wrap
        # enclosure via contains.
        LessonTestdata(passfails=4, solution=[
            InsertSolution("""
            # EDIT HERE (clearance)
            """, """
            LayoutRect pad:
                .layer = layers.Metal1
                ! .size == (1200, 1200)
                ! .ly == 1200
                ! .lx >= wall_a.ux + 400
                ! .lx >= wall_b.ux + 400
            """),
            InsertSolution("""
            # EDIT HERE (well)
            """, """
            LayoutRect well:
                .layer = layers.NWell
                ! .contains(dev_a.rect)
                ! .contains(dev_b.rect)
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
            Nmos m1a, m2a, m2b, m1b
            for m in m1a, m2a, m2b, m1b:
                m.$w = 1u
                m.$l = 130n

            ! m1a.pos == (0, 0)
            ! m2a.sd[0].center == m1a.sd[1].center
            ! m2a.pos.y == m1a.pos.y
            ! m2b.sd[0].center == m2a.sd[1].center
            ! m2b.pos.y == m1a.pos.y
            ! m1b.sd[0].center == m2b.sd[1].center
            ! m1b.pos.y == m1a.pos.y
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
    'cmos_circuits': CourseTestdata('CMOS Integrated Circuits', [
        # Lesson 1: MOS transistor curves. The import and each complete
        # device have their own check, then two sweep checks verify the
        # curves.
        LessonTestdata(passfails=5, solution=[
            InsertSolution("""
            # EDIT HERE (import)
            """, """
            from ordec.lib.ihp130 import Nmos, Pmos
            """),
            InsertSolution("""
            # EDIT HERE (transistors)
            """, """
            Nmos mn: .$w=1u; .$l=130n; .g -- gate; .d -- drain_n; .s -- vss; .b -- vss; .pos=(10,12)
            Pmos mp: .$w=1u; .$l=130n; .g -- gate; .d -- drain_p; .s -- vdd; .b -- vdd; .pos=(25,12)
            """),
        ]),
        # Lesson 2: current mirror. The skeleton's 1:1 mirror biases fine
        # but is neither built from unit devices nor at the 100 uA
        # target. The solution uses 10 parallel unit devices (m=10);
        # a single 10x-wide transistor is not a match (width effects).
        LessonTestdata(passfails=3, skeleton_passed=[True, False, False],
            solution=[
            InsertSolution("""
            # EDIT HERE
            Nmos n1: .pos=(8,3); .$w=1u; .$l=1u; .d -- iout; .g -- iin; .s -- vss; .b -- vss
            """, """
            Nmos n1: .pos=(8,3); .$w=1u; .$l=1u; .$m=10; .d -- iout; .g -- iin; .s -- vss; .b -- vss
            """),
        ]),
        # Lesson 3: common-source amplifier. A device check first, then
        # w=10u satisfies the operating point and the gain spec.
        LessonTestdata(passfails=3, solution=[
            InsertSolution("""
            # EDIT HERE
            """, """
            Nmos m0: .$w=10u; .$l=130n; .g -- vin; .d -- vout; .s -- vss; .b -- vss; .pos=(6,3)
            """),
        ]),
        # Lesson 4: differential pair. A pair-wiring check, then three
        # sweep checks. On the skeleton the balance check passes trivially
        # (both outputs sit at vdd).
        LessonTestdata(passfails=4,
            skeleton_passed=[False, False, True, False], solution=[
            InsertSolution("""
            # EDIT HERE
            """, """
            Nmos m1: .$w=5u; .$l=130n; .g -- inp; .d -- outp; .s -- tail; .b -- vss; .pos=(4,7)
            Nmos m2: .$w=5u; .$l=130n; .g -- inn; .d -- outn; .s -- tail; .b -- vss; .pos=(16,7); .orientation=FlippedSouth
            """),
        ]),
        # Lesson 5: ring oscillator bug hunt. The inversion-count check
        # flips as soon as the wiring is fixed, the transient confirms.
        LessonTestdata(passfails=3, solution=[
            InsertSolution("""
            # EDIT HERE
            DiffPair stage0: .inp -- outn; .inn -- outp; .outp -- p1; .outn -- n1; .bias -- bias; .vdd -- vdd; .vss -- vss; .pos=(4,8)
            """, """
            DiffPair stage0: .inp -- outp; .inn -- outn; .outp -- p1; .outn -- n1; .bias -- bias; .vdd -- vdd; .vss -- vss; .pos=(4,8)
            """),
        ]),
        # Lesson 6: CMOS inverter. On the empty skeleton, the 1 GOhm probe
        # pulls y to ground, so only the VOL check passes.
        LessonTestdata(passfails=4,
            skeleton_passed=[False, False, True, False], solution=[
            InsertSolution("""
            # EDIT HERE
            """, """
            Nmos pd: .$w=1u; .$l=130n; .g -- a; .d -- y; .s -- vss; .b -- vss; .pos=(3,2)
            Pmos pu: .$w=2u; .$l=130n; .g -- a; .d -- y; .s -- vdd; .b -- vdd; .pos=(3,8)
            """),
        ]),
        # Lesson 7: self-biased inverter. The student places the feedback
        # resistor, so the skeleton fails everything: without it the input
        # node floats and the sim checks report a blocked state. Any rf
        # from 100k upwards then satisfies the gain check.
        LessonTestdata(passfails=3, solution=[
            InsertSolution("""
            # EDIT HERE
            """, """
            Res rf: .$r=1M; .p -- a; .n -- y; .pos=(11,8)
            """),
        ]),
        # Lesson 8: NAND2. A structure check, then the truth table. The
        # skeleton's inverter driven by a implements the wrong function
        # only for a=1, b=0.
        LessonTestdata(passfails=5,
            skeleton_passed=[False, True, True, False, True], solution=[
            InsertSolution("""
            # EDIT HERE
            Nmos n1: .pos=(4,1); .s -- vss; .d -- y; .g -- a; .b -- vss
            Pmos p1: .pos=(4,13); .s -- vdd; .d -- y; .g -- a; .b -- vdd

            for t in p1, n1:
                t.$w = 1u
                t.$l = 130n
            """, """
            net n
            Nmos n2: .pos=(4,7); .s -- n; .d -- y; .g -- b; .b -- vss
            Nmos n1: .pos=(4,1); .s -- vss; .d -- n; .g -- a; .b -- vss
            Pmos p1: .pos=(4,13); .s -- vdd; .d -- y; .g -- a; .b -- vdd
            Pmos p2: .pos=(12,13); .s -- vdd; .d -- y; .g -- b; .b -- vdd

            for t in p1, p2, n1, n2:
                t.$w = 1u
                t.$l = 130n
            """),
        ]),
        # Lesson 9: standard cells. The student instantiates the shipped
        # XOR2 cell and wires it up; without it the truth-table checks
        # report that they wait for the instance.
        LessonTestdata(passfails=5, solution=[
            InsertSolution("""
            # EDIT HERE
            """, """
            Xor2 dut: .A -- a; .B -- b; .X -- y; .VDD -- vdd; .VSS -- vss; .pos=(18,12)
            """),
        ]),
        # Lesson 10: LFSR. The skeleton ties the feedback to zero, so the
        # register never leaves the all-zero state. Only an XNOR (an XOR
        # would keep feeding zeros back) with taps including the last
        # flip-flop gives the maximal-length 15-state sequence.
        LessonTestdata(passfails=3, solution=[
            InsertSolution("""
            # EDIT HERE
            Tielo tie: .L_LO -- fb; .VDD -- vdd; .VSS -- vss; .pos=(64,14)
            """, """
            Xnor2 fbgate: .A -- q3; .B -- q2; .Y -- fb; .VDD -- vdd; .VSS -- vss; .pos=(64,14)
            """),
        ]),
        # Lesson 11: 5-transistor OTA bonus. The mirror-structure check
        # comes first. The resistor-loaded starting point misses the gain
        # and swing specs (the 30k loads cannot swing rail to rail) but
        # meets the current budget and, with its low gain, trivially the
        # bandwidth spec.
        LessonTestdata(passfails=5,
            skeleton_passed=[False, False, False, True, True],
            solution=[
            InsertSolution("""
            # EDIT HERE
            Res rl_p: .$r=30k; .p -- vdd; .n -- outx; .pos=(4,14)
            Res rl_n: .$r=30k; .p -- vdd; .n -- out; .pos=(12,14)
            Nmos m1: .$w=5u; .$l=130n; .g -- inp; .d -- outx; .s -- tail; .b -- vss; .pos=(4,7)
            Nmos m2: .$w=5u; .$l=130n; .g -- inn; .d -- out; .s -- tail; .b -- vss; .pos=(16,7); .orientation=FlippedSouth
            """, """
            Pmos m3: .$w=5u; .$l=300n; .g -- outx; .d -- outx; .s -- vdd; .b -- vdd; .pos=(8,14); .orientation=FlippedSouth
            Pmos m4: .$w=5u; .$l=300n; .g -- outx; .d -- out; .s -- vdd; .b -- vdd; .pos=(12,14)
            Nmos m1: .$w=5u; .$l=300n; .g -- inp; .d -- outx; .s -- tail; .b -- vss; .pos=(4,7)
            Nmos m2: .$w=5u; .$l=300n; .g -- inn; .d -- out; .s -- tail; .b -- vss; .pos=(16,7); .orientation=FlippedSouth
            """),
        ]),
    ]),
    'amp_competition': CourseTestdata('Amplifier Competition', [
        # Competition lesson: meet the spec gates at every corner, minimize
        # the current. The empty skeleton passes the device whitelist
        # (nothing forbidden yet) and fails the three measured gates. The
        # reference solution is a ratio-centered CMOS inverter amplifier at
        # ~30 uA, self-biased through Rhigh and AC-coupled through Cmim so
        # its operating point survives the sf/fs and temperature corners
        # (see test_amp_input_biased_fails_corners). The headroom below it
        # (7-10 uA for a single stage, where the gain gate binds at the
        # slow/hot corner) is playtested but not asserted here.
        LessonTestdata(passfails=4,
            skeleton_passed=[True, False, False, False],
            solution=[
            InsertSolution("""
            # EDIT HERE: your amplifier. Only ihp130 Nmos, Pmos, Rsil,
            # Rppd, Rhigh and Cmim are allowed (see the course panel).
            """, """
            net g
            Cmim cc: .$w=30u; .$l=30u; .p -- vin; .n -- g; .pos=(3,7)
            Rhigh rf: .$w=0.5u; .$l=2000u; .p -- vout; .n -- g; .bn -- vss; .pos=(13,13)
            Nmos mn: .$w=1u; .$l=500n; .g -- g; .d -- vout; .s -- vss; .b -- vss; .pos=(8,4)
            Pmos mp: .$w=6.25u; .$l=500n; .$ng=2; .g -- g; .d -- vout; .s -- vdd; .b -- vdd; .pos=(8,10)
            """),
        ]),
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


def test_course_competition_flag():
    # The competition flag (hides the lesson navigator in the frontend)
    # must be passed through, and only amp_competition carries it.
    for name in courses_testdata:
        assert course_data(name)['competition'] is (name == 'amp_competition')


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
    if course_name == 'amp_competition':
        # The report carries the schematic, pushed to the scoreboard as
        # audit trail (see checks.py / course.js pushScore).
        svgs = [e for e in elements if e['element_type'] == 'svg']
        assert len(svgs) == 1 and 'mn' in svgs[0]['inner']


def test_amp_score_and_corner_table():
    """The score is the nominal corner's current (~30 uA for the
    reference), and the report tabulates every corner."""
    from ordec.courses.amp_competition.checks import CORNERS
    lesson = course_data('amp_competition')['lessons'][0]
    src = courses_testdata['amp_competition'].lessons[0].solution_src(lesson)
    elements = [e.element_webdata()
        for e in run_lesson(lesson, src)['lesson']().elements()]
    score = [e for e in elements if e['element_type'] == 'score']
    assert len(score) == 1 and score[0]['eligible']
    assert abs(score[0]['value'] - 30.0) < 1.0
    table = [e for e in elements if e['element_type'] == 'markdown'
        and 'Measurements across corners' in e['html']]
    assert len(table) == 1
    assert all(label in table[0]['html'] for label, _, _ in CORNERS)


def test_amp_input_biased_fails_corners():
    """An inverter biased directly from the 0.6 V input passes at tt but
    runs into a rail at the skewed corners: the gates fail and name the
    corner, and no eligible score is reported."""
    lesson = course_data('amp_competition')['lessons'][0]
    src = courses_testdata['amp_competition'].lessons[0].solution_src(lesson)
    src = src.replace(".g -- g;", ".g -- vin;")
    assert ".g -- vin;" in src
    elements = [e.element_webdata()
        for e in run_lesson(lesson, src)['lesson']().elements()]
    passfails = [e for e in elements if e['element_type'] == 'passfail']
    assert [p['passed'] for p in passfails] == [True, False, False, False]
    for p in passfails[1:]:
        assert 'at sf 27 °C (fail)' in p['instructions']
        assert 'at tt 27 °C (fail)' not in p['instructions']
    score = [e for e in elements if e['element_type'] == 'score']
    assert len(score) == 1 and not score[0]['eligible']


def test_amp_input_current_counts():
    """The score counts the current from the input source as well: a
    resistor from vin to vss adds its ~18 uA to the reference's ~30 uA,
    so the ideal 0.6 V input cannot serve as a free supply."""
    lesson = course_data('amp_competition')['lessons'][0]
    edit = courses_testdata['amp_competition'].lessons[0].solution[0]
    src = InsertSolution(edit.skeleton, edit.solution + "Rhigh rx: .$w=0.5u; "
        ".$l=10u; .p -- vin; .n -- vss; .bn -- vss; .pos=(3,13)\n"
        ).apply(lesson['src'])
    elements = [e.element_webdata()
        for e in run_lesson(lesson, src)['lesson']().elements()]
    passfails = [e for e in elements if e['element_type'] == 'passfail']
    assert all(p['passed'] for p in passfails)
    score = [e for e in elements if e['element_type'] == 'score']
    assert len(score) == 1 and score[0]['eligible']
    assert abs(score[0]['value'] - 48.4) < 1.0


# Three AC-coupled self-biased inverters in weak inversion (0.84 uA at tt):
# the small-signal gain of the chain passes at every corner, but the
# 10 mV input sine drives the internal nodes into limiting, so the output
# is a distorted ~150-350 mV wave. The large-signal gate exists for this.
AMP_CASCADE = """
            net g1, rf1m, n1, g2, rf2m, n2, g3, rf3m
            Cmim c1: .$w=30u; .$l=30u; .p -- vin; .n -- g1; .pos=(6,4)
            Pmos rf1a: .$w=0.5u; .$l=0.13u; .g -- rf1m; .d -- rf1m; .s -- n1; .b -- n1; .pos=(12,4)
            Pmos rf1b: .$w=0.5u; .$l=0.13u; .g -- rf1m; .d -- rf1m; .s -- g1; .b -- g1; .pos=(18,4)
            Nmos mn1: .$w=0.15u; .$l=8u; .g -- g1; .d -- n1; .s -- vss; .b -- vss; .pos=(24,4)
            Pmos mp1: .$w=0.3u; .$l=8u; .g -- g1; .d -- n1; .s -- vdd; .b -- vdd; .pos=(30,4)
            Cmim c2: .$w=10u; .$l=10u; .p -- n1; .n -- g2; .pos=(36,4)
            Pmos rf2a: .$w=0.5u; .$l=0.13u; .g -- rf2m; .d -- rf2m; .s -- n2; .b -- n2; .pos=(42,4)
            Pmos rf2b: .$w=0.5u; .$l=0.13u; .g -- rf2m; .d -- rf2m; .s -- g2; .b -- g2; .pos=(48,4)
            Nmos mn2: .$w=0.15u; .$l=8u; .g -- g2; .d -- n2; .s -- vss; .b -- vss; .pos=(54,4)
            Pmos mp2: .$w=0.3u; .$l=8u; .g -- g2; .d -- n2; .s -- vdd; .b -- vdd; .pos=(6,10)
            Cmim c3: .$w=10u; .$l=10u; .p -- n2; .n -- g3; .pos=(12,10)
            Pmos rf3a: .$w=0.5u; .$l=0.13u; .g -- rf3m; .d -- rf3m; .s -- vout; .b -- vout; .pos=(18,10)
            Pmos rf3b: .$w=0.5u; .$l=0.13u; .g -- rf3m; .d -- rf3m; .s -- g3; .b -- g3; .pos=(24,10)
            Nmos mn3: .$w=0.15u; .$l=8u; .g -- g3; .d -- vout; .s -- vss; .b -- vss; .pos=(30,10)
            Pmos mp3: .$w=0.3u; .$l=8u; .g -- g3; .d -- vout; .s -- vdd; .b -- vdd; .pos=(36,10)
"""


def test_amp_cascade_fails_large_signal():
    """A starved multi-stage cascade passes the device, gain and DC gates
    at every corner but fails the large-signal gate (distortion), so its
    sub-uA current is not an eligible score."""
    lesson = course_data('amp_competition')['lessons'][0]
    edit = courses_testdata['amp_competition'].lessons[0].solution[0]
    src = InsertSolution(edit.skeleton, AMP_CASCADE).apply(lesson['src'])
    elements = [e.element_webdata()
        for e in run_lesson(lesson, src)['lesson']().elements()]
    passfails = [e for e in elements if e['element_type'] == 'passfail']
    assert [p['passed'] for p in passfails] == [True, True, True, False]
    assert 'distortion at tt 27 °C (fail)' in passfails[3]['instructions']
    score = [e for e in elements if e['element_type'] == 'score']
    assert len(score) == 1 and not score[0]['eligible']
    assert score[0]['value'] < 2.0


def cmos_variant_states(lesson_index, replace_from, replace_to):
    """Passfail states of a cmos_circuits solution with one edit applied."""
    lesson = course_data('cmos_circuits')['lessons'][lesson_index]
    src = courses_testdata['cmos_circuits'].lessons[lesson_index] \
        .solution_src(lesson)
    assert replace_from in src
    report = run_lesson(lesson, src.replace(replace_from, replace_to))
    elements = [e.element_webdata() for e in report['lesson']().elements()]
    return [e['passed'] for e in elements
        if e['element_type'] == 'passfail']


def test_cmos_mirror_wide_transistor():
    """
    A single 10x-wide transistor must fail both the unit-device check and
    the mirror's 10 % tolerance (width effects change the current
    density), which is the teaching point of cmos_circuits lesson 2.
    """
    assert cmos_variant_states(1,
        ".$w=1u; .$l=1u; .$m=10;", ".$w=10u; .$l=1u;") \
        == [True, False, False]


def test_cmos_mirror_trimmed_width():
    """
    Trimming the width until the current happens to land in the tolerance
    window (w=8u gives 104 uA) must not solve lesson 2: a mirror has to be
    built from unit transistors, so the structural check stays red.
    """
    assert cmos_variant_states(1,
        ".$w=1u; .$l=1u; .$m=10;", ".$w=8u; .$l=1u;") \
        == [True, False, True]


def test_cmos_mirror_fingers():
    """
    The second correct technique, one device split into ten unit-width
    fingers, must pass lesson 2 just like the m=10 solution.
    """
    assert cmos_variant_states(1,
        ".$w=1u; .$l=1u; .$m=10;", ".$w=10u; .$l=1u; .$ng=10;") \
        == [True, True, True]


# Devices the user has started but not finished wiring, per cmos_circuits
# lesson index. Each replaces the lesson's '# EDIT HERE' marker.
cmos_half_wired = [
    (2, """
    Nmos m0: .$w=1u; .$l=130n; .g -- vin; .d -- vout; .pos=(6,3)
    """),
    (3, """
    Nmos m1: .$w=5u; .$l=130n; .g -- inp; .d -- outp; .pos=(4,7)
    """),
    (5, """
    Nmos pd: .$w=1u; .$l=130n; .g -- a; .d -- y; .pos=(3,2)
    """),
]


@pytest.mark.parametrize('lesson_index,device', cmos_half_wired,
    ids=[f'lesson{i+1}' for i, _ in cmos_half_wired])
def test_cmos_half_wired_no_traceback(lesson_index, device):
    """
    A device with pins still missing is an expected state while the user
    types, so the checks must explain it instead of confronting the user
    with a Python traceback.
    """
    lesson = course_data('cmos_circuits')['lessons'][lesson_index]
    src = InsertSolution("""
    # EDIT HERE
    """, device).apply(lesson['src'])
    report = run_lesson(lesson, src)['lesson']()
    elements = [e.element_webdata() for e in report.elements()]
    failed = [e for e in elements
        if e['element_type'] == 'passfail' and not e['passed']]
    assert failed
    for check in failed:
        assert 'Traceback' not in check['instructions'], check['label']
        assert check['hint']


def test_cmos_inverter_symmetric_sizing():
    """
    Equal NMOS/PMOS widths must pass all structural checks and levels but
    miss the 0.6 V threshold window (cmos_circuits lesson 6 teaches the
    PMOS needs twice the width).
    """
    assert cmos_variant_states(5,
        "Pmos pu: .$w=2u", "Pmos pu: .$w=1u") \
        == [True, True, True, False]
