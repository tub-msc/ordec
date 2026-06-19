# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Lesson checks for the 'intro' course.

Each gen_lesson* function takes the lesson namespace (globals) and returns the
lesson() view generator for that lesson: a @generate_func building a Report
whose PassFail elements decide whether the lesson is passed (the course UI
considers a lesson passed when all its PassFail elements pass). Exceptions
during checking are converted into failing PassFail elements, so the view never
crashes on a broken user design.
"""

import math
import traceback

from ordec.core import *
from ordec.sim import Simulator
from ordec.lib import Gnd, Vdc


def exception_text() -> str:
    """Format the current exception for display in a PassFail element."""
    return "The check raised an exception:\n" + traceback.format_exc()


# Lesson 1: RC lowpass
# --------------------

def corner_frequency(freq, mag):
    """
    Returns the first -3 dB crossing relative to the lowest-frequency
    magnitude, log-interpolated between simulation points, or None if the
    magnitude never falls below the threshold.
    """
    thresh = mag[0] / math.sqrt(2)
    for i in range(1, len(mag)):
        if mag[i] < thresh:
            f0, f1 = freq[i - 1], freq[i]
            m0, m1 = mag[i - 1], mag[i]
            alpha = (m0 - thresh) / (m0 - m1)
            return f0 * (f1 / f0) ** alpha
    return None


def gen_lesson1(g):
    """Build the lesson() view for lesson 1, closing over the lesson globals g."""
    @generate_func
    def lesson() -> Report:
        cell = g['Lowpass']()
        report = Report()
        report.markdown(
            "## Lesson 1: RC lowpass\n\n"
            "The `Lowpass` cell is an RC lowpass filter driven by an AC "
            "source. Adjust the resistor value `r` and the capacitor value `c` "
            "so that the corner frequency (-3 dB point) at the net `out` "
            "becomes **10 kHz** (&plusmn;5%).\n\n"
            "Look at the `sim_ac` view to see the frequency response of your "
            "filter."
        )
        label = "Corner frequency at 10 kHz"
        try:
            h = cell.sim_ac
            freq = [f.real for f in h.freq]
            mag = [abs(v) for v in h.out.voltage]
            report.plot2d(
                {"V(out)": mag},
                x=freq,
                xlabel="Frequency (Hz)",
                ylabel="Output voltage (V)",
                xscale=ScaleType.Log,
                yscale=ScaleType.Log,
                height=220,
            )
            fc = corner_frequency(freq, mag)
            if fc is None:
                report.passfail(label, False,
                    hint="The corner frequency of an RC lowpass is "
                    "f_c = 1/(2*pi*R*C). For example, with R = 1k, you need "
                    "C = 1/(2*pi*1e3*10e3) = 15.9n (16n is close enough).",
                    instructions="No -3 dB crossing found between 10 Hz and "
                    "100 MHz.")
            else:
                rel_err = abs(fc - 10e3) / 10e3
                report.passfail(label, rel_err <= 0.05,
                    hint="The corner frequency of an RC lowpass is "
                    "f_c = 1/(2*pi*R*C). For example, with R = 1k, you need "
                    "C = 1/(2*pi*1e3*10e3) = 15.9n (16n is close enough).",
                    instructions=f"Measured corner frequency: {fc:.4g} Hz "
                    f"(target: 10 kHz, tolerance: 5%).")
        except Exception:
            report.passfail(label, False, instructions=exception_text(),
                hint="The corner frequency of an RC lowpass is "
                "f_c = 1/(2*pi*R*C). For example, with R = 1k, you need "
                "C = 1/(2*pi*1e3*10e3) = 15.9n (16n is close enough).")
        return report
    return lesson


# Lesson 2: NAND2 gate
# --------------------

def gen_lesson2(g):
    """Build the lesson() view for lesson 2, closing over the lesson globals g."""
    dut = g['Nand2']

    class Nand2Tb(Cell):
        """Operating-point testbench applying static input levels to a NAND2."""
        vdd = Parameter(R)
        a = Parameter(R)
        b = Parameter(R)

        @generate
        def schematic(self):
            s = Schematic(cell=self)
            s.vdd = Net()
            s.vss = Net()
            s.a = Net()
            s.b = Net()
            s.y = Net()

            s.dut = SchemInstance(dut().symbol.portmap(
                vdd=s.vdd, vss=s.vss, a=s.a, b=s.b, y=s.y), pos=Vec2R(17, 6))
            s.gnd = SchemInstance(
                Gnd().symbol.portmap(p=s.vss), pos=Vec2R(0, 0))
            s.src_vdd = SchemInstance(
                Vdc(dc=self.vdd).symbol.portmap(m=s.vss, p=s.vdd),
                pos=Vec2R(0, 6))
            s.src_a = SchemInstance(
                Vdc(dc=self.a).symbol.portmap(m=s.vss, p=s.a), pos=Vec2R(5, 6))
            s.src_b = SchemInstance(
                Vdc(dc=self.b).symbol.portmap(m=s.vss, p=s.b), pos=Vec2R(10, 6))

            s.auto_wire()
            s.check(add_conn_points=True, add_terminal_taps=True)
            return s

    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "## Lesson 2: NAND2 gate\n\n"
            "The `Nand2` cell already has the right symbol (inputs `a` and "
            "`b`, output `y`), but its schematic is still just an inverter "
            "driven by `a`. Extend the schematic so that the cell implements "
            "the NAND2 function `y = !(a & b)`.\n\n"
            "Each check below applies one combination of static input levels "
            "and verifies the output with an operating point simulation "
            "(VDD = 5 V)."
        )
        for a, b in ((0, 0), (0, 1), (1, 0), (1, 1)):
            expect_high = not (a and b)
            label = f"a={a}, b={b} => y={int(expect_high)}"
            try:
                tb = Nand2Tb(vdd=5.0, a=a * 5.0, b=b * 5.0)
                h = SimHierarchy.from_schematic(tb.schematic)
                Simulator(h).op()
                y = float(h.y.voltage[0])
                if expect_high:
                    passed = y > 0.9 * 5.0
                else:
                    passed = y < 0.1 * 5.0
                report.passfail(label, passed,
                    hint="A NAND2 gate consists of two NMOS transistors in "
                    "series between vss and y (gates driven by a and b) and "
                    "two PMOS transistors in parallel between vdd and y (gates "
                    "driven by a and b). You need an additional internal net "
                    "between the two series NMOS transistors.",
                    instructions=f"Simulated y = {y:.3f} V, expected "
                    f"{'> ' + format(0.9 * 5.0, 'g') if expect_high else '< ' + format(0.1 * 5.0, 'g')} V.")
            except Exception:
                report.passfail(label, False, instructions=exception_text(),
                    hint="A NAND2 gate consists of two NMOS transistors in "
                    "series between vss and y (gates driven by a and b) and "
                    "two PMOS transistors in parallel between vdd and y (gates "
                    "driven by a and b). You need an additional internal net "
                    "between the two series NMOS transistors.")
        return report
    return lesson


# Lesson 3: Inverter layout routing
# ---------------------------------

def gen_lesson3(g):
    """Build the lesson() view for lesson 3, closing over the lesson globals g.

    auto_refresh=False: the LVS/DRC checks are expensive and run only when the
    user clicks the Check button.
    """
    @generate_func(auto_refresh=False)
    def lesson() -> Report:
        from ordec.lib import ihp130
        cell = g['Inv']()
        report = Report()
        report.markdown(
            "## Lesson 3: Inverter layout routing\n\n"
            "The `Inv` cell has a complete schematic, but its layout is "
            "missing the Metal1 routing for `vdd`, `vss` and `y`. Add the "
            "missing routes (e.g. with `SRouter`) so that the layout matches "
            "the schematic (LVS) without design rule violations (DRC).\n\n"
            "This check runs KLayout LVS and DRC, which can take a while."
        )
        try:
            lvs_clean = ihp130.run_lvs(cell.layout, cell.symbol)
            report.passfail("LVS clean", lvs_clean,
                hint="Three Metal1 connections are missing: from the vdd stub "
                "to the PMOS source (the left source/drain region of the "
                "PMOS), from the vss stub to the NMOS source, and from the "
                "NMOS drain up to the PMOS drain (output y). Use the "
                "commented-out SRouter code as a starting point and take "
                "coordinates from the layout view.",
                instructions="Layout-versus-schematic comparison "
                + ("succeeded." if lvs_clean else "failed: the extracted "
                "layout netlist does not match the schematic."))
        except Exception:
            report.passfail("LVS clean", False, instructions=exception_text(),
                hint="Three Metal1 connections are missing: from the vdd stub "
                "to the PMOS source (the left source/drain region of the "
                "PMOS), from the vss stub to the NMOS source, and from the "
                "NMOS drain up to the PMOS drain (output y). Use the "
                "commented-out SRouter code as a starting point and take "
                "coordinates from the layout view.")
        try:
            summary = ihp130.run_drc(cell.layout).summary()
            if summary:
                details = "DRC violations: " + ", ".join(
                    f"{rule} ({count}x)"
                    for rule, count in sorted(summary.items()))
            else:
                details = "No DRC violations."
            report.passfail("DRC clean", not summary, instructions=details,
                hint="Make sure your routes overlap the existing metal "
                "properly and do not leave sub-minimum-size metal shapes or "
                "spacing violations. The DRC report lists the violated rules.")
        except Exception:
            report.passfail("DRC clean", False, instructions=exception_text(),
                hint="Make sure your routes overlap the existing metal "
                "properly and do not leave sub-minimum-size metal shapes or "
                "spacing violations. The DRC report lists the violated rules.")
        return report
    return lesson
