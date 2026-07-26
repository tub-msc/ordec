# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Lesson checks for the 'getting_started' course.

Each gen_lesson* function takes the lesson namespace (globals) and returns the
lesson() view generator for that lesson: a @generate_func building a Report
whose PassFail elements decide whether the lesson is passed (the course UI
considers a lesson passed when all its PassFail elements pass). Exceptions
during checking are converted into failing PassFail elements, so the view never
crashes on a broken user design.

Exceptions: lesson 1 is a welcome lesson without tasks (course.json flag
getting_started_lesson_1; the frontend marks it solved right away and runs
the spotlight tour), and lesson 2 is passed by opening result viewers, which
the frontend detects on its own (flag getting_started_lesson_2). Both reports
carry only instructions and no PassFail elements.
"""

import dis
import inspect
import traceback

from ordec.core import *
from ordec.lib import Res, Ind, Cap, Gnd, Vdc


def exception_text() -> str:
    """Format the current exception for display in a PassFail element."""
    return "The check raised an exception:\n" + traceback.format_exc()


# Lesson 1: Welcome to ORDeC
# --------------------------

def gen_lesson1(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "## Welcome to ORDeC!\n\n"
            "In this course, you learn step by step how to work with ORDeC's "
            "web UI and how to describe circuits in the ORD language."
        )
        return report
    return lesson


# Lesson 2: Opening result viewers
# --------------------------------

def gen_lesson2(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "## Lesson 2: Opening result viewers\n\n"
            "The editor contains the source code of a small design: a cell "
            "`HelloWorld` with two views, a `schematic` "
            "(a voltage source with a resistor) and a report called `hello`.\n\n"
            "**Open the two views `HelloWorld().schematic` and "
            "`HelloWorld().hello`, each in a result viewer of its own.**\n\n"
            "Most lessons are solved by editing the source code — but not "
            "this one:\n\n"
            "1. Click *New Result View* in the toolbar at the top.\n"
            "2. In the new panel, pick `HelloWorld().schematic` from the "
            "view list.\n"
            "3. Repeat both steps for `HelloWorld().hello`.\n\n"
            "The lesson is passed as soon as both viewers are open at the "
            "same time. In later lessons, the most important viewers are "
            "already open when the lesson starts — but you can always "
            "open more yourself."
        )
        return report
    return lesson


# Lesson 3: Instantiating a resistor
# ----------------------------------

def gen_lesson3(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "## Lesson 3: Instantiating a resistor\n\n"
            "The `ParallelR` cell contains a 5 V voltage source `vsrc`, but "
            "no load yet.\n\n"
            "**Instantiate a 1 kOhm resistor at position (5, 6), in "
            "parallel to the voltage source: pin `p` to `vdd`, pin `m` to "
            "`vss`.**\n\n"
            "For example:\n\n"
            "```\n"
            "Res R0: .$r=1k\n"
            "```\n\n"
            "This declares a resistor instance `R0` with a resistance of "
            "1 kOhm: an instance is declared by cell name and instance "
            "name, followed by attributes. Parameters start with `.$`, "
            "`.pin -- net` connects a pin to a net, and `.pos` places the "
            "instance in the schematic.\n\n"
            "Tip: click on an instance in the schematic viewer to jump to "
            "the line of source code that created it."
        )

        # The instance name is the user's choice, so the checks match Res
        # instances by their properties, not by name.
        def resistors():
            return [inst for inst in
                g['ParallelR']().schematic.all(SchemInstance)
                if isinstance(inst.symbol.cell, Res)]

        label = "Resistor instantiated"
        try:
            report.passfail(label, bool(resistors()),
                hint="Add a `Res` instance at the EDIT HERE marker, for "
                "example: `Res R0: .$r=1k`.",
                instructions="Looking for a Res instance in the schematic.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Add a `Res` instance at the EDIT HERE marker, for "
                "example: `Res R0: .$r=1k`.")

        label = "Resistance set to 1 kOhm"
        try:
            found = any(float(inst.symbol.cell.r) == 1000
                for inst in resistors())
            report.passfail(label, found,
                hint="The resistance parameter is set with `.$r=1k`.",
                instructions="Looking for a resistor with r=1k.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="The resistance parameter is set with `.$r=1k`.")

        label = "Resistor positioned at (5, 6)"
        try:
            found = any(
                (float(inst.pos.x), float(inst.pos.y)) == (5.0, 6.0)
                for inst in resistors())
            report.passfail(label, found,
                hint="Place the resistor with `.pos=(5,6)`.",
                instructions="Looking for a resistor at position (5, 6).")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Place the resistor with `.pos=(5,6)`.")

        label = "Resistor in parallel to the source"
        try:
            s = g['ParallelR']().schematic
            src_nets = {c.here for c in s.vsrc.conns()}
            found = any({c.here for c in inst.conns()} == src_nets
                for inst in resistors())
            report.passfail(label, found,
                hint="In parallel means the resistor connects to the same "
                "two nets as the source: `.m -- vss; .p -- vdd`.",
                instructions="The resistor must connect to the same nets "
                "as vsrc.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="In parallel means the resistor connects to the same "
                "two nets as the source: `.m -- vss; .p -- vdd`.")
        return report
    return lesson


# Lesson 4: Resistor network
# --------------------------

def gen_lesson4(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "## Lesson 4: Resistor network\n\n"
            "**Connect a network of three resistors to the 5 V source: a "
            "2 kOhm and a 3 kOhm resistor in parallel, and a 1 kOhm "
            "resistor in series with the parallel pair, with a net `mid` "
            "between them.**\n\n"
            "Positions: the 1 kOhm resistor at (5, 12) (pin `p` to "
            "`vdd`, pin `m` to `mid`), the 2 kOhm resistor at (5, 6) "
            "and the 3 kOhm resistor at (10, 6) (each pin `p` to "
            "`mid`, pin `m` to `vss`)."
        )

        # The instance names are the user's choice, so the checks match Res
        # instances by their properties, not by name.
        def resistors(r_val):
            return [inst for inst in
                g['RNetwork']().schematic.all(SchemInstance)
                if isinstance(inst.symbol.cell, Res)
                and float(inst.symbol.cell.r) == r_val]

        for r_val, ohms in ((1000, '1k'), (2000, '2k'), (3000, '3k')):
            label = f"{ohms} resistor instantiated"
            hint = (f"Add a resistor with `.$r={ohms}` at the EDIT HERE "
                "marker, like in lesson 3.")
            try:
                report.passfail(label, bool(resistors(r_val)), hint=hint,
                    instructions=f"Looking for a resistor with r={ohms}.")
            except Exception:
                report.passfail(label, False, instructions=exception_text(),
                    hint=hint)

        label = "Each resistor placed at its specified position"
        try:
            s = g['RNetwork']().schematic
            status = []
            all_ok = True
            for r_val, x, y in ((1000, 5, 12), (2000, 5, 6), (3000, 10, 6)):
                ok = any((float(inst.pos.x), float(inst.pos.y)) == (x, y)
                    for inst in resistors(r_val))
                status.append(f"{r_val/1000:g}k at ({x}, {y}): "
                    + ("found" if ok else "missing"))
                all_ok = all_ok and ok
            report.passfail(label, all_ok, instructions="; ".join(status),
                hint="Place the resistors with `.pos=(5,12)`, `.pos=(5,6)` "
                "and `.pos=(10,6)`.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Place the resistors with `.pos=(5,12)`, `.pos=(5,6)` "
                "and `.pos=(10,6)`.")

        label = "Additional net defined"
        try:
            s = g['RNetwork']().schematic
            report.passfail(label, len(list(s.all(Net))) >= 3,
                hint="Declare the middle net with `net mid` (the net name "
                "is not checked).",
                instructions="Looking for a third net besides vdd and vss.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Declare the middle net with `net mid` (the net name "
                "is not checked).")

        label = "All resistors wired up properly"
        try:
            s = g['RNetwork']().schematic
            def net_set(inst):
                return {c.here for c in inst.conns()}
            found = False
            for n1 in map(net_set, resistors(1000)):
                if s.vdd not in n1:
                    continue
                mids = n1 - {s.vdd}
                if len(mids) != 1 or s.vss in mids:
                    continue
                mid = mids.pop()
                if (any(net_set(inst) == {mid, s.vss}
                        for inst in resistors(2000))
                    and any(net_set(inst) == {mid, s.vss}
                        for inst in resistors(3000))):
                    found = True
                    break
            report.passfail(label, found,
                hint="The 1 kOhm resistor connects `vdd` to the middle "
                "net, and the 2 kOhm and 3 kOhm resistors each connect "
                "the middle net to `vss`.",
                instructions="The 1 kOhm resistor must sit between vdd "
                "and the middle net, the 2 kOhm and 3 kOhm resistors "
                "between the middle net and vss.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="The 1 kOhm resistor connects `vdd` to the middle "
                "net, and the 2 kOhm and 3 kOhm resistors each connect "
                "the middle net to `vss`.")
        return report
    return lesson


# Lesson 5: Wiring with for loops
# -------------------------------

def gen_lesson5(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "## Lesson 5: Wiring with for loops\n\n"
            "The three resistors from lesson 4 are back, already placed but "
            "not connected. `r1` is rotated by 180 degrees "
            "(`.orientation=R180`), so the `p` pins of *all three* resistors "
            "must connect to `mid` — a perfect job for a for loop.\n\n"
            "**Connect all resistor pins using for loops: `p` of all three "
            "resistors to `mid`, `m` of `r2` and `r3` to `vss`, and `m` of "
            "`r1` to `vdd`.**\n\n"
            "Connections can also be made after an instance was declared, "
            "and ORD supports plain Python control flow:\n\n"
            "```\n"
            "for r in r1, r2, r3:\n"
            "    r.p -- mid\n"
            "```"
        )

        label = "All pins properly connected"
        try:
            s = g['RNetworkLoops']().schematic
            def net_set(inst):
                return {c.here for c in inst.conns()}
            unconnected = [name for name in ('r1', 'r2', 'r3')
                if len(list(getattr(s, name).conns())) != 2]
            # The middle net does not have to be the provided mid; any net
            # besides vdd/vss is accepted in its place.
            found = False
            if not unconnected:
                mids = net_set(s.r1) - {s.vdd}
                if (s.vdd in net_set(s.r1) and len(mids) == 1
                        and s.vss not in mids):
                    mid = mids.pop()
                    found = (net_set(s.r2) == {mid, s.vss}
                        and net_set(s.r3) == {mid, s.vss})
            report.passfail(label, found,
                hint="Connect the p pins of all three resistors to mid, "
                "m of r2 and r3 to vss, and m of r1 to vdd.",
                instructions="Resistors with unconnected pins: "
                + (", ".join(unconnected) if unconnected else "none") + ".")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Connect the p pins of all three resistors to mid, "
                "m of r2 and r3 to vss, and m of r1 to vdd.")

        label = "For loop used in the schematic view"
        try:
            code = inspect.unwrap(
                g['RNetworkLoops'].__dict__['schematic'].func).__code__
            found = any(ins.opname == 'FOR_ITER'
                for ins in dis.get_instructions(code))
            report.passfail(label, found,
                hint="Wire the pins inside a for loop, for example: "
                "`for r in r1, r2, r3:` followed by an indented "
                "`r.p -- mid`.",
                instructions="Checking the compiled schematic view for a "
                "for loop.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Wire the pins inside a for loop, for example: "
                "`for r in r1, r2, r3:` followed by an indented "
                "`r.p -- mid`.")
        return report
    return lesson


# Lesson 6: LC bandstop filter
# ----------------------------

class BandstopSolution(Cell):
    """Reference LC bandstop, rendered as a sketch in the lesson text."""

    @generate
    def schematic(self):
        s = Schematic(cell=self)
        s.vin = Net()
        s.vout = Net()
        s.vss = Net()
        s.mid = Net()

        s.gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(0, 0))
        s.vsrc = SchemInstance(Vdc(ac_mag=1).symbol.portmap(m=s.vss, p=s.vin),
            pos=Vec2R(0, 6))
        s.r1 = SchemInstance(Res(r='1k').symbol.portmap(p=s.vin, m=s.vout),
            pos=Vec2R(8, 16), orientation=R90)
        s.h1 = SchemInstance(Ind(l='1m').symbol.portmap(m=s.mid, p=s.vout),
            pos=Vec2R(8, 11))
        s.c1 = SchemInstance(Cap(c='100n').symbol.portmap(p=s.mid, m=s.vss),
            pos=Vec2R(8, 6))

        s.auto_wire()
        s.check(add_conn_points=True, add_terminal_taps=True)
        return s


def gen_lesson6(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "## Lesson 6: LC bandstop filter\n\n"
            "The `Bandstop` cell provides an AC source `vsrc` driving the "
            "net `vin`.\n\n"
            "**Build a bandstop filter: a 1 kOhm resistor from `vin` to "
            "`vout`, rotated to horizontal with `.orientation=R90`, and an "
            "inductor (1 mH) in series with a capacitor (100 nF) from "
            "`vout` down to `vss`, with a net `mid` between them.**\n\n"
            "Instances can be rotated (`R90`, `R180`, `R270`) and mirrored "
            "(`MX`, `MY`, `MX90`, `MY90`). At the resonance frequency "
            "f = 1/(2*pi*sqrt(L*C)) = 15.9 kHz, the LC trap shorts `vout` "
            "to ground and produces a deep notch in the Bode plot. Target "
            "schematic:"
        )
        try:
            report.svg(BandstopSolution().schematic)
        except Exception:
            report.pre(exception_text())

        # The instance names are the user's choice, so the checks match
        # instances by their cell type, not by name.
        def instances(cls):
            return [inst for inst in
                g['Bandstop']().schematic.all(SchemInstance)
                if isinstance(inst.symbol.cell, cls)]

        label = "Res, Ind and Cap added"
        try:
            status = [cls.__name__ + ': '
                + ('found' if instances(cls) else 'missing')
                for cls in (Res, Ind, Cap)]
            found = all(instances(cls) for cls in (Res, Ind, Cap))
            report.passfail(label, found, instructions="; ".join(status),
                hint="Add the resistor, the inductor and the capacitor at "
                "the EDIT HERE marker, as shown in the target schematic.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Add the resistor, the inductor and the capacitor at "
                "the EDIT HERE marker, as shown in the target schematic.")

        label = "Resistor in horizontal orientation"
        try:
            found = any(inst.orientation in (R90, R270, MX90, MY90)
                for inst in instances(Res))
            report.passfail(label, found,
                hint="Rotate the resistor with `.orientation=R90` (R270, "
                "MX90 and MY90 work as well).",
                instructions="Accepted orientations: R90, R270, MX90, "
                "MY90.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Rotate the resistor with `.orientation=R90` (R270, "
                "MX90 and MY90 work as well).")

        label = "All instances wired up"
        try:
            s = g['Bandstop']().schematic
            unwired = [inst.full_path_str()
                for inst in s.all(SchemInstance)
                if len(list(inst.conns())) != len(list(inst.symbol.all(Pin)))]
            report.passfail(label, not unwired,
                hint="Every pin needs a `-- net` connection: the resistor "
                "between vin and vout, the inductor between vout and mid, "
                "the capacitor between mid and vss.",
                instructions="Instances with unconnected pins: "
                + (", ".join(unwired) if unwired else "none") + ".")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Every pin needs a `-- net` connection: the resistor "
                "between vin and vout, the inductor between vout and mid, "
                "the capacitor between mid and vss.")

        label = "Expected passband behavior"
        try:
            h = g['Bandstop']().sim_ac
            freq = [f.real for f in h.freq]
            mag = [abs(v) for v in h.vout.voltage]
            i_min = min(range(len(mag)), key=lambda i: mag[i])
            f_notch = freq[i_min]
            found = (abs(f_notch - 15.9e3) <= 0.10 * 15.9e3
                and mag[i_min] < 0.1
                and mag[0] > 0.9 and mag[-1] > 0.9)
            report.passfail(label, found,
                hint="The trap must resonate at f = 1/(2*pi*sqrt(L*C)) = "
                "15.9 kHz: a deep notch there, an untouched passband "
                "everywhere else. Check the l and c values and that the "
                "inductor and capacitor are in series (via mid), not in "
                "parallel.",
                instructions=f"|V(vout)| minimum: {mag[i_min]:.4g} at "
                f"{f_notch:.4g} Hz (target: < 0.1 at 15.9 kHz); at the "
                f"sweep ends: {mag[0]:.3f} / {mag[-1]:.3f} (target: > 0.9 "
                "both).")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="The trap must resonate at f = 1/(2*pi*sqrt(L*C)) = "
                "15.9 kHz: a deep notch there, an untouched passband "
                "everywhere else. Check the l and c values and that the "
                "inductor and capacitor are in series (via mid), not in "
                "parallel.")
        return report
    return lesson
