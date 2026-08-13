# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Lesson checks for the 'getting_started' course.

Each gen_lesson* function takes the lesson namespace (globals) and returns the
lesson() view generator for that lesson: a @viewgen_noctx building a Report
whose PassFail elements decide whether the lesson is passed (the course UI
considers a lesson passed when all its PassFail elements pass). Exceptions
during checking are converted into failing PassFail elements, so the view never
crashes on a broken user design.

Exceptions: lesson 1 is a welcome lesson without tasks (course.json flag
getting_started_lesson_1; the frontend marks it solved right away and runs
the spotlight tour), lesson 2 is passed by opening result viewers, which
the frontend detects on its own (flag getting_started_lesson_2), and the
final what's-next lesson is a task-free epilogue (generic course.json flag
epilogue: solved right away, no callout, no source editor in its layout).
Their reports carry only instructions and no PassFail elements.
"""

import dis
import inspect
import re
import traceback

from ordec.core import *
from ordec.lib import Res, Ind, Cap


def exception_text() -> str:
    """Format the current exception for display in a PassFail element."""
    return "The check raised an exception:\n" + traceback.format_exc()


# Lesson 1: Welcome to ORDeC
# --------------------------

def gen_lesson1(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            In this course, you learn step by step how to work with ORDeC's
            web UI and how to describe circuits in the ORD language.
        """)
        return report
    return lesson


# Lesson 2: Opening result viewers
# --------------------------------

def gen_lesson2(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            **Your first task is to open the two views
            `HelloWorld().schematic` and `HelloWorld().hello` in two
            separate result viewers:**

            1. Click *New Result View* in the toolbar at the top.
            2. In the new panel, pick the cell `HelloWorld()` in the
               first dropdown, then the view `.schematic` in the second
               dropdown that appears.
            3. Repeat both steps for `HelloWorld().hello`.
            4. Explore how you can rearrange the result viewers using
               drag and drop!

            There is no need to edit the source code here. The lesson is
            passed as soon as both viewers are open at the same time. In
            later lessons, the most important viewers are already open when
            the lesson starts, but you can always open more yourself.
        """)
        return report
    return lesson


# Lesson 3: Instantiating a resistor
# ----------------------------------

def gen_lesson3(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            The source code below defines the cell `Example` containing an
            instance of the ground symbol and a DC voltage source.

            **Your task is to add a 1 kΩ resistor at position (5, 6), and
            connect it in parallel to the voltage source: pin `p` to `vdd`,
            pin `n` to `vss`.**

            To instantiate a resistor `R0` and set its resistance parameter, type:

            ```
            Res R0
            R0.$r = 1k
            ```

            The dollar sign indicates that `r` is a parameter of the `Res` cell.

            To connect symbol pins with nets, use the `--` operator, for example:

            ```
            R0.n -- vss
            ```

            To avoid having to repeat the instance name, you can use the
            following syntax:

            ```
            Res R0:
                .$r = 1k
                .n -- vss
            ```

            By adding the `:` at the end of the line, we open a block within
            which we can access `R0` by a simple dot (`.`) without having to
            repeat the name `R0` over and over again.

            The following more compact syntax is also available:

            ```
            Res R0: .$r=1k; .n--vss
            ```

            Lastly, set the desired **position** of the instance:

            ```
            .pos = (5, 6)
            ```

            *Tip: click on an instance in the schematic viewer to jump to
            the line of source code that created it.*
        """)

        # The instance name is the user's choice, so the checks match Res
        # instances by their properties, not by name.
        def resistors():
            return [inst for inst in
                g['Example']().schematic.all(SchemInstance)
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

        label = "Resistance set to 1 kΩ"
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
            s = g['Example']().schematic
            src_nets = {c.here for c in s.vsrc.conns()}
            found = any({c.here for c in inst.conns()} == src_nets
                for inst in resistors())
            report.passfail(label, found,
                hint="In parallel means the resistor connects to the same "
                "two nets as the source: `.n -- vss; .p -- vdd`.",
                instructions="The resistor must connect to the same nets "
                "as vsrc.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="In parallel means the resistor connects to the same "
                "two nets as the source: `.n -- vss; .p -- vdd`.")
        return report
    return lesson


# Lesson 4: Resistor network
# --------------------------

def gen_lesson4(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            **Connect a network of three resistors to the 5 V source: a
            2 kΩ and a 3 kΩ resistor in parallel, and a 1 kΩ
            resistor in series with the parallel pair, with a net `mid`
            between them:**

            - the 1 kΩ resistor at (8, 12) (pin `p` to `vdd`, pin `n` to `mid`),
            - the 2 kΩ resistor at (5, 6) (pin `p` to
            `mid`, pin `n` to `vss`) and
            - the 3 kΩ resistor at (11, 6) (pin `p` to
            `mid`, pin `n` to `vss`).
        """)

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
            status = []
            all_ok = True
            for r_val, x, y in ((1000, 8, 12), (2000, 5, 6), (3000, 11, 6)):
                ok = any((float(inst.pos.x), float(inst.pos.y)) == (x, y)
                    for inst in resistors(r_val))
                status.append(f"{r_val/1000:g}k at ({x}, {y}): "
                    + ("found" if ok else "missing"))
                all_ok = all_ok and ok
            report.passfail(label, all_ok, instructions="; ".join(status),
                hint="Place the resistors with `.pos=(8,12)`, `.pos=(5,6)` "
                "and `.pos=(11,6)`.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Place the resistors with `.pos=(8,12)`, `.pos=(5,6)` "
                "and `.pos=(11,6)`.")

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
                hint="The 1 kΩ resistor connects `vdd` to the middle "
                "net, and the 2 kΩ and 3 kΩ resistors each connect "
                "the middle net to `vss`.",
                instructions="The 1 kΩ resistor must sit between vdd "
                "and the middle net, the 2 kΩ and 3 kΩ resistors "
                "between the middle net and vss.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="The 1 kΩ resistor connects `vdd` to the middle "
                "net, and the 2 kΩ and 3 kΩ resistors each connect "
                "the middle net to `vss`.")
        return report
    return lesson


# Lesson 5: Wiring with for loops
# -------------------------------

def gen_lesson5(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            The three resistors from the previous lesson are back: placed but
            not connected. This time, `R2` is rotated by 180 degrees
            (`.orientation=R180`), so the `p` pins of *all three* resistors
            must connect to `mid` — a perfect job for a for loop.

            **Connect all pins of the resistors to the appropriate nets.
            Use a for loop where convenient: the `p` pins of all three
            resistors should be connected to `mid`.**

            ```
            for r in R0, R1, R2:
                r.p -- mid
            ```

            *This lesson shows you that ORD code can include arbitrary Python
            control flow constructs.*
        """)

        label = "For loop used in the schematic view"
        try:
            code = inspect.unwrap(
                g['RNetworkLoops'].__dict__['schematic'].func).__code__
            found = any(ins.opname == 'FOR_ITER'
                for ins in dis.get_instructions(code))
            report.passfail(label, found,
                hint="Wire the pins inside a for loop, for example: "
                "`for r in R0, R1, R2:` followed by an indented "
                "`r.p -- mid`.",
                instructions="Checking the compiled schematic view for a "
                "for loop.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Wire the pins inside a for loop, for example: "
                "`for r in R0, R1, R2:` followed by an indented "
                "`r.p -- mid`.")

        label = "All pins properly connected"
        try:
            s = g['RNetworkLoops']().schematic
            def net_set(inst):
                return {c.here for c in inst.conns()}
            unconnected = [name for name in ('R0', 'R1', 'R2')
                if len(list(getattr(s, name).conns())) != 2]
            # The middle net does not have to be the provided mid; any net
            # besides vdd/vss is accepted in its place.
            found = False
            if not unconnected:
                mids = net_set(s.R2) - {s.vdd}
                if (s.vdd in net_set(s.R2) and len(mids) == 1
                        and s.vss not in mids):
                    mid = mids.pop()
                    found = (net_set(s.R0) == {mid, s.vss}
                        and net_set(s.R1) == {mid, s.vss})
            report.passfail(label, found,
                hint="Connect the p pins of all three resistors to mid, "
                "m of R0 and R1 to vss, and m of R2 to vdd.",
                instructions="Resistors with unconnected pins: "
                + (", ".join(unconnected) if unconnected else "none") + ".")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Connect the p pins of all three resistors to mid, "
                "m of R0 and R1 to vss, and m of R2 to vdd.")
        return report
    return lesson


# Lesson 6: LC bandstop filter
# ----------------------------

def gen_lesson6(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown(r"""
            In this lesson you will build a bandstop RLC filter. You will
            practice instantiating symbols. Moreover, AC simulation is
            introduced.

            **Build a bandstop filter: Add a 1 kΩ resistor from `vin` to
            `vout` and rotate it by 90 degrees using `.orientation=R90`.
            Between `vout` and `vss`, add an inductor (1 mH) in series with a
            capacitor (100 nF).**

            Once your schematic is complete, the Bode plot should show up in the
            result viewer of `Bandstop().bode`. At the resonance frequency
            $f = \frac{1}{2\pi\sqrt{LC}} = 15.9\,\mathrm{kHz}$, the
            LC trap shorts `vout` to ground and produces a deep notch in
            the Bode plot.

            *Instances can be rotated (`R90`, `R180`, `R270`) and mirrored
            (`MX`, `MY`, `MX90`, `MY90`).*

            *Through the parameter `ac_mag` (AC magnitude), `vsrc` is configured
            as stimulus of the AC simulation: the analysis applies a test signal
            of this amplitude (1 V) at `vin` and sweeps its frequency,
            computing the circuit's response at each point. A source without
            `ac_mag` injects no AC signal.*

            *Hint: the status bar of the schematic viewer shows X and Y
            coordinates of your mouse pointer when hovering.*
        """)

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
                hint="Add a `Res` (1 kΩ), an `Ind` (1 mH) and a `Cap` (100 nF) "
                "instance at the EDIT HERE marker, like in the "
                "previous lessons, e.g. `Ind L0: .$l=1m`.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Add a `Res` (1 kΩ), an `Ind` (1 mH) and a `Cap` (100 nF) "
                "instance at the EDIT HERE marker, like in the "
                "previous lessons, e.g. `Ind L0: .$l=1m`.")

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

        label = "All instance pins connected"
        try:
            s = g['Bandstop']().schematic
            unwired = [inst.full_path_str()
                for inst in s.all(SchemInstance)
                if len(list(inst.conns())) != len(list(inst.symbol.all(Pin)))]
            report.passfail(label, not unwired,
                hint="Every pin needs a `-- net` connection: wire the resistor "
                "between vin and vout, then declare a net for the "
                "middle node (e.g. `net mid`) and wire the inductor "
                "between vout and mid and the capacitor between mid "
                "and vss.",
                instructions="Instances with unconnected pins: "
                + (", ".join(unwired) if unwired else "none") + ".")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Every pin needs a `-- net` connection: wire the resistor "
                "between vin and vout, then declare a net for the "
                "middle node (e.g. `net mid`) and wire the inductor "
                "between vout and mid and the capacitor between mid "
                "and vss.")

        label = "Expected passband behavior"
        hint = ("The trap must resonate at f = 1/(2*pi*sqrt(L*C)) = "
            "15.9 kHz: a deep notch there, an untouched passband "
            "everywhere else. Check the l and c values and that the "
            "inductor and capacitor are in series (via the middle net), "
            "not in parallel.")
        # Until the circuit is fully wired, the simulation fails or carries
        # no vout data; that is an expected state, not worth a traceback.
        dut = g['Bandstop']()
        if (dut.schematic.has_errors() or dut.sim_ac.freq is None
                or dut.sim_ac.vout.voltage is None):
            report.passfail(label, False, hint=hint,
                instructions="No AC simulation data for vout yet: the "
                "simulation only runs once the circuit is fully wired.")
        else:
            freq = [f.real for f in dut.sim_ac.freq]
            mag = [abs(v) for v in dut.sim_ac.vout.voltage]
            i_min = min(range(len(mag)), key=lambda i: mag[i])
            f_notch = freq[i_min]
            found = (abs(f_notch - 15.9e3) <= 0.10 * 15.9e3
                and mag[i_min] < 0.1
                and mag[0] > 0.9 and mag[-1] > 0.9)
            report.passfail(label, found, hint=hint,
                instructions=f"|V(vout)| minimum: {mag[i_min]:.4g} at "
                f"{f_notch:.4g} Hz (target: < 0.1 at 15.9 kHz); at the "
                f"sweep ends: {mag[0]:.3f} / {mag[-1]:.3f} (target: > 0.9 "
                "both).")
        return report
    return lesson


# Lesson 7: Subcells
# ------------------

def gen_lesson7(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            So far, each design was a single cell. Real designs are built
            from hierarchies of cells: a cell gets a *symbol* with pins, and
            other cells instantiate it like any component.

            **Turn the filter into a reusable cell: add the pins `vin`, `vout`
            and `vss` to the `symbol` of `Bandstop`. Add the corresponding ports
            to the `Bandstop` schematic (`vout` must be placed at (12, 18)).
            Wire up R, L and C to the ports. In `BandstopTb`, instantiate
            `Bandstop` and connect it to the `vin`, `vout` and `vss` nets.**

            Symbol pins are declared by direction:

            ```
            input vin
            output vout
            inout vss
            ```

            In the schematic, a `port` binds a net to the symbol pin of
            the same name. Ports without a `.pos` are placed
            automatically at the edge of the schematic:

            ```
            port vin
            port vout: .pos=(12,18)
            ```

            Wire the R, L and C pins to the port nets, e.g.
            `r1.p -- vin`. In the testbench, the subcell is then
            instantiated with its pins connected by name:

            ```
            Bandstop dut: .pos=(6,9); .vin -- vin; .vout -- vout; .vss -- vss
            ```
        """)

        label = "Pins vin, vout and vss added to the symbol"
        try:
            sym = g['Bandstop']().symbol
            names = {p.full_path_str() for p in sym.all(Pin)}
            report.passfail(label, {'vin', 'vout', 'vss'} <= names,
                hint="Declare the pins in the symbol viewgen: `input vin`, "
                "`output vout`, `inout vss`.",
                instructions="Symbol pins found: "
                + (", ".join(sorted(names)) if names else "none") + ".")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Declare the pins in the symbol viewgen: `input vin`, "
                "`output vout`, `inout vss`.")

        label = "Filter schematic wired up, including the ports"
        try:
            s = g['Bandstop']().schematic
            port_nets = {p.ref.full_path_str() for p in s.all(SchemPort)}
            found = ({'vin', 'vout', 'vss'} <= port_nets
                and not s.has_errors())
            report.passfail(label, found,
                hint="Declare a port for each of vin, vout and vss, then "
                "connect the component pins: `r1.p -- vin`, `r1.n -- "
                "vout`, `l1.p -- vout`, `c1.n -- vss`.",
                instructions="Ports found: "
                + (", ".join(sorted(port_nets)) if port_nets else "none")
                + ("; schematic has error markers." if s.has_errors()
                    else "."))
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Declare a port for each of vin, vout and vss, then "
                "connect the component pins: `r1.p -- vin`, `r1.n -- "
                "vout`, `l1.p -- vout`, `c1.n -- vss`.")

        label = "vout port placed at (12, 18)"
        try:
            s = g['Bandstop']().schematic
            found = any(p.ref.full_path_str() == 'vout'
                and (float(p.pos.x), float(p.pos.y)) == (12.0, 18.0)
                for p in s.all(SchemPort))
            report.passfail(label, found,
                hint="Give the vout port an explicit position: `port vout: "
                ".pos=(12,18)`. The other ports may stay auto-placed.",
                instructions="Looking for the vout port at position "
                "(12, 18).")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Give the vout port an explicit position: `port vout: "
                ".pos=(12,18)`. The other ports may stay auto-placed.")

        label = "Bandstop instantiated in the testbench"
        try:
            tb = g['BandstopTb']().schematic
            found = any(isinstance(inst.symbol.cell, g['Bandstop'])
                for inst in tb.all(SchemInstance))
            report.passfail(label, found,
                hint="Instantiate the filter at the EDIT HERE marker of "
                "the testbench: `Bandstop dut: .pos=(6,9); .vin -- vin; "
                ".vout -- vout; .vss -- vss`.",
                instructions="Looking for a Bandstop instance in the "
                "BandstopTb schematic.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Instantiate the filter at the EDIT HERE marker of "
                "the testbench: `Bandstop dut: .pos=(6,9); .vin -- vin; "
                ".vout -- vout; .vss -- vss`.")

        label = "Expected passband behavior"
        hint = ("The filter is the same as in lesson 6: a deep notch "
            "at 15.9 kHz, an untouched passband everywhere else. "
            "Check the wiring inside Bandstop and in the testbench.")
        # Until both cells are fully wired, the simulation fails or carries
        # no vout data; that is an expected state, not worth a traceback.
        tb = g['BandstopTb']()
        if (g['Bandstop']().schematic.has_errors()
                or tb.schematic.has_errors() or tb.sim_ac.freq is None
                or tb.sim_ac.vout.voltage is None):
            report.passfail(label, False, hint=hint,
                instructions="No AC simulation data for vout yet: the "
                "simulation only runs once the circuit is fully wired.")
        else:
            freq = [f.real for f in tb.sim_ac.freq]
            mag = [abs(v) for v in tb.sim_ac.vout.voltage]
            i_min = min(range(len(mag)), key=lambda i: mag[i])
            f_notch = freq[i_min]
            found = (abs(f_notch - 15.9e3) <= 0.10 * 15.9e3
                and mag[i_min] < 0.1
                and mag[0] > 0.9 and mag[-1] > 0.9)
            report.passfail(label, found, hint=hint,
                instructions=f"|V(vout)| minimum: {mag[i_min]:.4g} at "
                f"{f_notch:.4g} Hz (target: < 0.1 at 15.9 kHz); at the "
                f"sweep ends: {mag[0]:.3f} / {mag[-1]:.3f} (target: > 0.9 "
                "both).")
        return report
    return lesson


# Lesson 8: Parameters
# --------------------

def gen_lesson8(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown(r"""
            So far, the filter always rejects the same frequency. *Parameters*
            make a cell configurable per instance.

            **Parametrize the `Bandstop` cell and chain two of them in series.
            The first filter should have a notch frequency of 5 kHz, the second
            of 50 kHz, resulting in a double-notch in the Bode plot.**

            1. Declare the parameter directly below `cell Bandstop:` as follows:

            ```
            freq = Parameter(R, default=15.9k)
            ```

            2. From $f = \frac{1}{2\pi\sqrt{LC}}$ follows
            $L = \frac{1}{(2\pi f)^2 C}$. With C = 10 nF, assign the
            derived inductance directly at the EDIT HERE marker of
            `l1`:

            ```
            .$l=1 / ((2 * math.pi * float(self.freq))**2 * 10e-9)
            ```

            3. In the testbench, replace `f0` by two chained filters:
            declare a net `mid`, instantiate one `Bandstop` with
            `.$freq=5k` from `vin` to `mid` at (6, 9), and a second one
            with `.$freq=50k` from `mid` to `vout` at (12, 9), both
            with pin `vss` to `vss`.

            The Bode plot updates as you type: watch the second notch
            appear.
        """)

        def has_freq_param():
            return isinstance(getattr(g['Bandstop'], 'freq', None),
                Parameter)

        label = "freq parameter added to Bandstop"
        try:
            report.passfail(label, has_freq_param(),
                hint="Declare the parameter at the EDIT HERE marker: "
                "`freq = Parameter(R, default=15.9k)`.",
                instructions="Looking for a Parameter named freq on the "
                "Bandstop cell.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Declare the parameter at the EDIT HERE marker: "
                "`freq = Parameter(R, default=15.9k)`.")

        label = "Inductance derived from freq"
        try:
            if not has_freq_param():
                report.passfail(label, False,
                    hint="Assign the inductance directly from the parameter: "
                    "`.$l=1 / ((2 * math.pi * float(self.freq))**2 "
                    "* 10e-9)`.",
                    instructions="Requires the freq parameter (previous "
                    "check).")
            else:
                l5 = float(g['Bandstop'](freq=5000)
                    .schematic.l1.symbol.cell.l)
                l50 = float(g['Bandstop'](freq=50000)
                    .schematic.l1.symbol.cell.l)
                found = (abs(l5 - 0.101321) <= 0.05 * 0.101321
                    and abs(l50 - 1.01321e-3) <= 0.05 * 1.01321e-3)
                report.passfail(label, found,
                    hint="Assign the inductance directly from the parameter: "
                    "`.$l=1 / ((2 * math.pi * float(self.freq))**2 "
                    "* 10e-9)`.",
                    instructions=f"l1 at freq=5k: {l5*1e3:.3f} mH (target "
                    f"101.3 mH); at freq=50k: {l50*1e3:.4f} mH (target "
                    "1.013 mH).")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Assign the inductance directly from the parameter: "
                "`.$l=1 / ((2 * math.pi * float(self.freq))**2 "
                "* 10e-9)`.")

        # The instance names are the user's choice, so the checks match
        # Bandstop instances by their properties, not by name.
        def filters():
            return [inst for inst in
                g['BandstopTb']().schematic.all(SchemInstance)
                if isinstance(inst.symbol.cell, g['Bandstop'])]

        label = "Two filters with notches at 5 kHz and 50 kHz"
        try:
            if not has_freq_param():
                report.passfail(label, False,
                    hint="Instantiate two Bandstop filters with "
                    "`.$freq=5k` and `.$freq=50k`.",
                    instructions="Requires the freq parameter (first "
                    "check).")
            else:
                freqs = sorted(float(inst.symbol.cell.freq)
                    for inst in filters())
                report.passfail(label, freqs == [5000.0, 50000.0],
                    hint="Instantiate two Bandstop filters with "
                    "`.$freq=5k` and `.$freq=50k`.",
                    instructions="Notch frequencies found: "
                    + (", ".join(f"{f:g} Hz" for f in freqs)
                        if freqs else "none") + ".")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Instantiate two Bandstop filters with `.$freq=5k` "
                "and `.$freq=50k`.")

        label = "Filters chained through an intermediate net"
        try:
            tb = g['BandstopTb']().schematic
            def pin_nets(inst):
                return {c.there.full_path_str(): c.here
                    for c in inst.conns()}
            found = False
            insts = filters()
            for a in insts:
                for b in insts:
                    if a == b:
                        continue
                    pa, pb = pin_nets(a), pin_nets(b)
                    mid = pa.get('vout')
                    if (pa.get('vin') == tb.vin
                            and mid is not None
                            and mid == pb.get('vin')
                            and mid not in (tb.vin, tb.vout, tb.vss)
                            and pb.get('vout') == tb.vout
                            and pa.get('vss') == tb.vss
                            and pb.get('vss') == tb.vss):
                        found = True
            report.passfail(label, found,
                hint="Chain the filters: the first connects vin to a new "
                "net mid, the second connects mid to vout; vss goes to "
                "vss on both.",
                instructions="The two filters must connect in series "
                "between vin and vout via an intermediate net.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Chain the filters: the first connects vin to a new "
                "net mid, the second connects mid to vout; vss goes to "
                "vss on both.")

        label = "Double-notch AC response"
        hint = ("With both filters chained, the response has notches at "
            "5 kHz and 50 kHz and recovers in between. Check the freq "
            "parameters and the chaining.")
        tb = g['BandstopTb']()
        if (g['Bandstop']().schematic.has_errors()
                or tb.schematic.has_errors() or tb.sim_ac.freq is None
                or tb.sim_ac.vout.voltage is None):
            report.passfail(label, False, hint=hint,
                instructions="No AC simulation data for vout yet: the "
                "simulation only runs once the circuit is fully wired.")
        else:
            freq = [f.real for f in tb.sim_ac.freq]
            mag = [abs(v) for v in tb.sim_ac.vout.voltage]
            def min_in(lo, hi):
                return min(m for f, m in zip(freq, mag) if lo <= f <= hi)
            n1 = min_in(4.5e3, 5.5e3)
            n2 = min_in(45e3, 55e3)
            mid = max(m for f, m in zip(freq, mag) if 10e3 <= f <= 25e3)
            found = (n1 < 0.1 and n2 < 0.1 and mid > 0.4
                and mag[0] > 0.9 and mag[-1] > 0.9)
            report.passfail(label, found, hint=hint,
                instructions=f"|V(vout)| around 5 kHz: {n1:.3g} and "
                f"around 50 kHz: {n2:.3g} (target: < 0.1 both); between "
                f"the notches: {mid:.3f} (target: > 0.4); at the sweep "
                f"ends: {mag[0]:.3f} / {mag[-1]:.3f} (target: > 0.9 "
                "both).")
        return report
    return lesson


# Lesson 9: Transient analysis and reports
# ----------------------------------------

def gen_lesson9(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            In this lesson we will learn how to add a transient analysis
            to a cell and present the results in a custom report.

            **Add a transient analysis view generator, build a report that
            plots the pulse input and the two stage outputs, and finally link
            the plots so that they share cursor and zoom state.**

            1. Add the analysis at the EDIT HERE (analysis) marker:

            ```
            viewgen sim_tran(self) -> Simulation:
                .simulate().tran(1u, 3m)
            ```

            2. Add a report at the EDIT HERE (report) marker: a text, a
            plot of the pulse input, and a second plot with both stage
            outputs:

            ```
            viewgen report(self) -> Report:
                sim = self.sim_tran
                .markdown("Step response of the two RC stages.")
                .plot2d(sim.time, sim.vin)
                .plot2d(sim.time, sim.mid, sim.vout)
            ```

            Open the new `RcChain().report` view in the empty result
            viewer on the right, like in lesson 2.

            3. Try zooming into one of the plots: the other one does not
            follow. Link them: declare a group with `PlotGroup grp` after
            the markdown line and pass `group=grp` to both
            `.plot2d(...)` calls. Cursor and zoom of the two plots now
            move in sync.
        """)

        label = "Transient analysis added"
        try:
            found = (hasattr(g['RcChain'], 'sim_tran')
                and g['RcChain']().sim_tran.time is not None)
            report.passfail(label, found,
                hint="Add `viewgen sim_tran(self) -> Simulation:` with "
                "`.simulate().tran(1u, 3m)` at the EDIT HERE "
                "(analysis) marker.",
                instructions="Looking for a sim_tran view with transient "
                "data.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Add `viewgen sim_tran(self) -> Simulation:` with "
                "`.simulate().tran(1u, 3m)` at the EDIT HERE "
                "(analysis) marker.")

        def plots():
            if not hasattr(g['RcChain'], 'report'):
                return None
            return [e for e in g['RcChain']().report.elements()
                if isinstance(e, Plot2D)]

        label = "Report with a Markdown description"
        try:
            found = (hasattr(g['RcChain'], 'report')
                and any(isinstance(e, Markdown)
                    for e in g['RcChain']().report.elements()))
            report.passfail(label, found,
                hint="Add `viewgen report(self) -> Report:` at the EDIT HERE "
                "(report) marker and describe the circuit with "
                "`.markdown(...)`.",
                instructions="Looking for a report view containing a "
                "markdown element.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Add `viewgen report(self) -> Report:` at the EDIT HERE "
                "(report) marker and describe the circuit with "
                "`.markdown(...)`.")

        label = "First plot: the pulse input"
        try:
            ps = plots()
            found = (ps is not None and len(ps) >= 1
                and [se.name for se in ps[0].series()] == ['vin'])
            report.passfail(label, found,
                hint="The first `.plot2d(...)` plots sim.time against "
                "the single series sim.vin.",
                instructions="The report's first plot must show exactly "
                "one series named vin.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="The first `.plot2d(...)` plots sim.time against "
                "the single series sim.vin.")

        label = "Second plot: both stage outputs"
        try:
            ps = plots()
            found = (ps is not None and len(ps) >= 2
                and sorted(se.name for se in ps[1].series())
                    == ['mid', 'vout'])
            report.passfail(label, found,
                hint="The second `.plot2d(...)` plots the two series "
                "sim.mid and sim.vout.",
                instructions="The report's second plot must show exactly "
                "the two series mid and vout.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="The second `.plot2d(...)` plots the two series "
                "sim.mid and sim.vout.")

        label = "Plots linked in a group"
        try:
            ps = plots()
            found = (ps is not None and len(ps) >= 2
                and ps[0].group is not None
                and ps[0].group == ps[1].group)
            report.passfail(label, found,
                hint="Declare a group with `PlotGroup grp` and pass "
                "`group=grp` to both `.plot2d(...)` calls.",
                instructions="Both plots must reference the same "
                "PlotGroup.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="Declare a group with `PlotGroup grp` and pass "
                "`group=grp` to both `.plot2d(...)` calls.")
        return report
    return lesson


# Lesson 10: Postprocessing
# -------------------------

def gen_lesson10(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            One great thing about ORD being a Python superset is that you have
            the full data processing capabilities of Python at your hands. Use
            it to evaluate the waveforms from the previous lesson.

            **From the transient simulation results `self.sim_tran`, count the
            pulses arriving at `vout` and measure the 10%-90% rise time of
            the first pulse.**

            1. A pulse arrives at `vout` whenever the voltage crosses 0.5 V
            upwards. `itertools.pairwise` yields each sample together with
            its successor:

            ```
            from itertools import pairwise
            n_pulses = sum(1 for a, b in pairwise(sim.vout.voltage) if a <= 0.5 < b)
            .markdown(f"Counted {n_pulses} pulses.")
            ```

            2. For the rise time, walk the waveform to the first sample at
            10% of the pulse level, then continue to 90%. Both searches
            share the iterator `it`, so the second continues where the
            first stopped. `R(...)` formats the value with an SI suffix;
            rounding to three significant digits first keeps the output
            free of floating-point noise:

            ```
            it = zip(sim.time, sim.vout.voltage)
            rise_start = next(t for t, v in it if v >= 0.1)
            rise_end = next(t for t, v in it if v >= 0.9)
            rise_time = R(f"{rise_end - rise_start:.3g}")
            .markdown(f"Rise time: {rise_time}")
            ```
        """)

        def md_texts():
            if not hasattr(g['RcChain'], 'report'):
                return []
            return [e.markdown for e in g['RcChain']().report.elements()
                if isinstance(e, Markdown)]

        label = "Pulse count reported"
        hint = ("Count the upward crossings of vout through 0.5 V and "
            "report the count in a markdown text (3 pulses in this "
            "simulation).")
        try:
            found = any(re.search(r'\b3 pulses\b', txt)
                for txt in md_texts())
            report.passfail(label, found, hint=hint,
                instructions="Looking for a markdown text stating "
                "'3 pulses'.")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint=hint)

        label = "Rise time measured"
        hint = ("Measure the time between the first 10% and 90% crossings "
            "of vout and report it in a markdown text, e.g. "
            "'Rise time: 138u'.")
        try:
            rise = None
            for txt in md_texts():
                m = re.search(r'[Rr]ise.*?([0-9.]+)\s*[uµ]', txt)
                if m:
                    rise = float(m.group(1))
            found = rise is not None and 120 <= rise <= 160
            report.passfail(label, found, hint=hint,
                instructions="Measured rise time found: "
                + (f"{rise:g} us" if rise is not None else "none")
                + " (expected: roughly 138 us).")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint=hint)

        return report
    return lesson


# Epilogue: What's next?
# ----------------------

def gen_epilogue(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        # Course links open in a new tab (inline HTML with target=_blank):
        # a plain link would only change the URL fragment of the running
        # app without reloading it.
        report.markdown("""
            **Congratulations &mdash; you have completed the Getting Started
            course!**

            You have learned how to work with the ORDeC web UI and how to
            describe circuits in ORD: instantiating and wiring components,
            building subcells with symbols and parameters, running DC, AC and
            transient simulations, and evaluating the results in reports.

            Here is where you can go from here:

            - **Continue with the next courses:**
              <a href="app.html#course=cmos_circuits" target="_blank"
              rel="noopener">CMOS Integrated Circuits</a> and the
              <a href="app.html#course=layout_tutorial" target="_blank"
              rel="noopener">Layout Tutorial</a>.

            - **Explore the examples.** The <a href="." target="_blank"
              rel="noopener">start page</a> collects example designs that go
              beyond this course: MOSFET circuits on real PDKs,
              constraint-based layout and DRC/LVS.

            - **Start your own design** and consult the
              [documentation](docs:) along the way!

            - **Get involved.** ORDeC is open source! You can ask questions
              or report issues on
              <a href="https://github.com/tub-msc/ordec" target="_blank"
              rel="noopener">GitHub</a>.

            Your course progress and edits stay in this browser; use
            *Export* in the toolbar above to save them as a zip file.
        """)
        return report
    return lesson
