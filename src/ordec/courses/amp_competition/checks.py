# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Competition check for the 'amp_competition' course (Amplifier Competition).

One lesson: design an amplifier inside the fixed Amp symbol, meet the spec
gates at every process corner, minimize supply current. gen_challenge renders
rules, gates and the score as the lesson() view. The measurement functions,
gate constants and corner list are also used by support/hub/rescore.py for
the verified final ranking, so they must stay importable without side
effects.

Like the cmos_circuits checks, a half-finished design is an expected state:
simulation-based gates report a friendly status while the structure is
incomplete, and tracebacks are reserved for unexpected failures.
"""

import math
import traceback

from ordec.core import *
from ordec.lib import ihp130

# Spec gates. The score (supply current) only counts with all gates passing
# at all corners; rescore.py applies the same numbers, and all displayed
# texts derive from them, so retuning after playtesting is a one-place edit.
GAIN_MIN = 20.0      # V/V at GAIN_FREQ
GAIN_FREQ = 1e6      # Hz; into the 1 pF load, this prices gm (and current)
GAIN_MIN_DB = 20 * math.log10(GAIN_MIN)
VOUT_DC_MIN = 0.35   # V
VOUT_DC_MAX = 0.85   # V

# (label, ihp130.Corner, temperature in degrees C). The gates must hold at
# every corner; the first entry is the nominal one whose supply current is
# the score. Slow/hot pairs with high resistance and low capacitance (worst
# for gain and for an AC-coupled input), fast/cold with the opposite (most
# current); sf/fs move the trip point of any stage biased from the input.
CORNERS = [
    ("tt 27 °C", ihp130.Corner.TT, 27),
    ("ss 125 °C (R high, C low)",
        ihp130.Corner(mos='ss', res='wcs', cap='bcs'), 125),
    ("ff −40 °C (R low, C high)",
        ihp130.Corner(mos='ff', res='bcs', cap='wcs'), -40),
    ("sf 27 °C", ihp130.Corner.SF, 27),
    ("fs 27 °C", ihp130.Corner.FS, 27),
]

# Physical IHP devices only. ihp130.Res covers Rsil/Rppd/Rhigh; ideal
# elements (ordec.lib Res/Cap/...) are excluded on purpose: an ideal
# resistor load would buy arbitrary gain at no current cost.
ALLOWED_DEVICES = (ihp130.Nmos, ihp130.Pmos, ihp130.Res, ihp130.Cmim)


def exception_text():
    """Format the current exception for display in a PassFail element."""
    return "The check raised an exception:\n" + traceback.format_exc()


def forbidden_devices(schematic, prefix="", depth=0):
    """
    Names of instances in schematic (recursively, so subcells are fine)
    whose leaf cells are not allowed ihp130 devices.
    """
    if depth > 20:
        return [prefix + "…: hierarchy deeper than 20 levels"]
    bad = []
    for inst in schematic.all(SchemInstance):
        cell = inst.symbol.cell
        name = prefix + inst.full_path_str()
        if isinstance(cell, ALLOWED_DEVICES):
            continue
        try:
            sub = cell.schematic
        except Exception:
            bad.append(f"{name} ({type(cell).__name__})")
            continue
        bad += forbidden_devices(sub, prefix=name + ".", depth=depth + 1)
    return bad


def testbench(g, corner, temp):
    """Fresh SimHierarchy of the AmpTb testbench and its Simulator at one
    corner. The testbench's own sim_* views stay nominal for the report
    views; the checks simulate every corner from here."""
    h = SimHierarchy.from_schematic(g['AmpTb']().schematic)
    return h, h.simulate(corner=corner, temp=temp)


def measure_op(g, corner, temp):
    """(supply current in A, output DC voltage in V) at the operating point."""
    h, sim = testbench(g, corner, temp)
    sim.op()
    return abs(float(h.vdd_src.p.current[0])), float(h.vout.voltage[0])


def measure_ac(g, corner, temp):
    """Gain in V/V at GAIN_FREQ. The testbench drives vin with ac_mag=1,
    so |v(vout)| is the gain; a single-point AC analysis measures it."""
    h, sim = testbench(g, corner, temp)
    sim.ac('lin', 1, GAIN_FREQ, GAIN_FREQ)
    return abs(h.vout.voltage[0])


def measure_corners(g):
    """[(label, supply current in A, output DC in V, gain)] over CORNERS."""
    rows = []
    for label, corner, temp in CORNERS:
        isup, vout_dc = measure_op(g, corner, temp)
        rows.append((label, isup, vout_dc, measure_ac(g, corner, temp)))
    return rows


def gen_challenge(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        corner_list = ", ".join(label for label, _, _ in CORNERS)
        report.markdown(f"""
            # Amplifier Competition

            Build the amplifier inside the `Amp` cell (EDIT HERE marker).
            The `AmpTb` testbench is fixed: 1.2 V supply, input driven at
            a DC level of 0.6 V, 1 pF load on the output. Meet all specs,
            then **minimize the supply current — lowest current wins**:

            | Spec | Requirement |
            |---|---|
            | Gain at {GAIN_FREQ / 1e6:g} MHz | ≥ {GAIN_MIN:g} ({GAIN_MIN_DB:.0f} dB) |
            | Output DC level | {VOUT_DC_MIN:g} V … {VOUT_DC_MAX:g} V |

            Both must hold at every process corner and temperature:
            {corner_list}. The score is the supply current at the first
            (nominal) corner. The table below the checks shows all
            corners; `report_dc` and `report_ac` show the nominal one.

            Only physical IHP SG13G2 devices are allowed inside `Amp`:
            `Nmos`, `Pmos`, the resistors `Rsil`, `Rppd`, `Rhigh`
            (low/medium/high sheet resistance) and the capacitor `Cmim`,
            all from `ordec.lib.ihp130`. No ideal elements. Unlike the
            ideal `Res`, the physical resistors have a substrate pin
            `bn`, normally tied to `vss`:

                Rppd r1: .$w=1u; .$l=10u; .p -- vdd; .n -- vout; .bn -- vss; .pos=(6,9)

            Your score appears on the scoreboard automatically whenever
            all checks pass.
        """)

        # Hints level the field without giving away sizings.
        devices_hint = ("Everything inside Amp (including your own "
            "subcells) must be an ihp130 Nmos, Pmos, Rsil, Rppd, Rhigh or "
            "Cmim. Ideal elements are rejected: an ideal resistor would "
            "make gain free.")
        gain_hint = (f"A resistor-loaded common-source stage cannot reach "
            f"{GAIN_MIN:g} here: its gain is capped by the DC drop across "
            "the load. The CMOS course's inverter lessons show loads that "
            f"do better. At {GAIN_FREQ / 1e6:g} MHz the 1 pF load also "
            "sets the price of gain: it takes transconductance, and "
            "transconductance costs current. If the gain is low at "
            f"{GAIN_FREQ / 1e6:g} MHz but fine above, the input coupling "
            "is the limit: a feedback resistor looks (1 + gain) times "
            "smaller to a coupling capacitor (Miller effect).")
        dc_hint = ("The input sits fixed at 0.6 V. A stage biased from it "
            "moves with the thresholds: fine at tt, at the rails at sf/fs "
            "and hot (see the corner table). A stage that sets its own "
            "operating point and only takes the signal from vin holds "
            "its level at every corner; its transfer curve in report_dc "
            "is then flat.")

        try:
            bad = forbidden_devices(g['Amp']().schematic)
            report.passfail("Only allowed devices in Amp", not bad,
                instructions=("Not allowed: " + ", ".join(bad) + "."
                    if bad else ""), hint=devices_hint)
            structure_ok = not bad
        except Exception:
            report.passfail("Only allowed devices in Amp", False,
                instructions=exception_text(), hint=devices_hint)
            structure_ok = False

        gain_label = f"Gain at {GAIN_FREQ / 1e6:g} MHz ≥ {GAIN_MIN:g}"
        dc_label = (f"Output DC level {VOUT_DC_MIN:g} V … "
            f"{VOUT_DC_MAX:g} V")
        try:
            rows = measure_corners(g)
        except Exception:
            if structure_ok:
                reason = exception_text()
            else:
                reason = ("The simulation failed -- usually the amplifier "
                    "is still incomplete (see the device check above).")
            report.passfail(gain_label, False, instructions=reason,
                hint=gain_hint)
            report.passfail(dc_label, False, instructions=reason,
                hint=dc_hint)
            rows = None

        if rows is not None:
            gain_ok = [gain >= GAIN_MIN for _, _, _, gain in rows]
            report.passfail(gain_label, all(gain_ok), hint=gain_hint,
                instructions=f"Gain at {GAIN_FREQ / 1e6:g} MHz: " + ", ".join(
                    f"{gain:.2f} ({20 * math.log10(max(gain, 1e-9)):.1f} dB)"
                    f" at {label}" + ("" if ok else " (fail)")
                    for (label, _, _, gain), ok in zip(rows, gain_ok))
                + f". Required: ≥ {GAIN_MIN:g} ({GAIN_MIN_DB:.0f} dB) at "
                "every corner.")
            dc_ok = [VOUT_DC_MIN <= vout_dc <= VOUT_DC_MAX
                for _, _, vout_dc, _ in rows]
            report.passfail(dc_label, all(dc_ok), hint=dc_hint,
                instructions="Output DC level: " + ", ".join(
                    f"{vout_dc:.3f} V at {label}" + ("" if ok else " (fail)")
                    for (label, _, vout_dc, _), ok in zip(rows, dc_ok))
                + f". Required: {VOUT_DC_MIN:g} V … {VOUT_DC_MAX:g} V at "
                "every corner. The input sits at 0.6 V; your amplifier "
                "must place its own operating point.")
            report.markdown("Measurements across corners:\n\n"
                f"| Corner | Supply current | Output DC | Gain at "
                f"{GAIN_FREQ / 1e6:g} MHz |\n|---|---|---|---|\n"
                + "\n".join(f"| {label} | {isup * 1e6:.2f} µA | "
                    f"{vout_dc:.3f} V | {gain:.2f} |"
                    for label, isup, vout_dc, gain in rows))
            eligible = all(e.passed for e in report.elements()
                if isinstance(e, PassFail))
            # In competition course mode, the frontend pushes eligible
            # scores to the workshop scoreboard (see web/src/scoreboard.js).
            report.score(f"Score (supply current at {rows[0][0]})",
                rows[0][1] * 1e6, unit="µA", eligible=eligible)
        # The schematic goes to the scoreboard with the score (see
        # course.js pushScore), so admins can look at a submission without
        # running it. Skipped when it cannot be drawn: that case is already
        # reported by the checks above.
        try:
            schematic = g['Amp']().schematic
            report.markdown("Your schematic, as pushed with the score:")
            report.svg(schematic)
        except Exception:
            pass
        return report
    return lesson
