# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Competition check for the 'amp_competition' course (Amplifier Competition).

One lesson: design an amplifier inside the fixed Amp symbol, meet the spec
gates at every process corner, minimize the current. gen_challenge renders
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

# Spec gates. The score (current drawn from the testbench sources while
# amplifying, see measure_tran) only counts with all gates passing at all
# corners; rescore.py applies the same numbers, and all displayed texts
# derive from them, so retuning after playtesting is a one-place edit.
GAIN_MIN = 20.0      # V/V at GAIN_FREQ
GAIN_FREQ = 1e6      # Hz; into the 1 pF load, this prices gm (and current)
GAIN_MIN_DB = 20 * math.log10(GAIN_MIN)
VOUT_DC_MIN = 0.35   # V
VOUT_DC_MAX = 0.85   # V
# Large-signal gate: the testbench's input sine (VIN_AMP at GAIN_FREQ, see
# vin_src in challenge.ord) must come out GAIN_MIN times larger with at
# most THD_MAX distortion. The small-signal gain can be faked by a chain
# of starved stages that limit rather than amplify; a faithful copy of the
# input cannot.
VIN_AMP = 0.01       # V
THD_MAX = 0.05
# Transient length in periods of the input sine. The bias networks (GΩ,
# pF) settle during the first half; the second half is analysed.
TRAN_CYCLES = 20

# (label, ihp130.Corner, temperature in degrees C). The gates must hold at
# every corner; the first entry is the nominal one whose current is the
# score. Slow/hot pairs with high resistance and low capacitance (worst
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
    """Output DC voltage in V at the operating point."""
    h, sim = testbench(g, corner, temp)
    sim.op()
    return float(h.vout.voltage[0])


def measure_ac(g, corner, temp):
    """Gain in V/V at GAIN_FREQ. The testbench drives vin with ac_mag=1,
    so |v(vout)| is the gain; a single-point AC analysis measures it."""
    h, sim = testbench(g, corner, temp)
    sim.ac('lin', 1, GAIN_FREQ, GAIN_FREQ)
    return abs(h.vout.voltage[0])


def measure_tran(g, corner, temp):
    """(current in A, output amplitude in V at GAIN_FREQ, distortion as a
    ratio) for the testbench's input sine, from the second half of a
    transient of TRAN_CYCLES periods. The current is the average of
    everything the testbench sources deliver while amplifying, supply and
    input source: the input is an ideal 0.6 V source, so powering the
    amplifier from it would otherwise be free, and measuring under signal
    charges class-AB bursts and switching for what they draw. The
    distortion is the RMS of everything in vout that is not the
    fundamental (harmonics, drift of the bias point) relative to the RMS
    of the fundamental."""
    h, sim = testbench(g, corner, temp)
    period = 1 / GAIN_FREQ
    sim.tran(period / 50, TRAN_CYCLES * period, tmax=period / 100)
    t = [float(x) for x in h.time]
    v = [float(x) for x in h.vout.voltage]
    i_src = [abs(float(a)) + abs(float(b)) for a, b
        in zip(h.vdd_src.p.current, h.vin_src.p.current)]
    start = next(i for i, x in enumerate(t)
        if x >= TRAN_CYCLES // 2 * period)

    def mean(y):
        # Trapezoidal average; ngspice's time points are not uniform.
        acc = 0.0
        for i in range(start + 1, len(t)):
            acc += (y[i] + y[i - 1]) / 2 * (t[i] - t[i - 1])
        return acc / (t[-1] - t[start])

    dc = mean(v)
    ac = [x - dc for x in v]
    w = 2 * math.pi * GAIN_FREQ
    amp = 2 * math.hypot(
        mean([x * math.cos(w * tt) for x, tt in zip(ac, t)]),
        mean([x * math.sin(w * tt) for x, tt in zip(ac, t)]))
    rms = math.sqrt(mean([x * x for x in ac]))
    rest = math.sqrt(max(rms ** 2 - amp ** 2 / 2, 0))
    return mean(i_src), amp, rest / max(amp / math.sqrt(2), 1e-12)


def measure_corners(g):
    """[(label, current in A, output DC in V, gain, output amplitude in V,
    distortion)] over CORNERS."""
    rows = []
    for label, corner, temp in CORNERS:
        isup, vout_amp, thd = measure_tran(g, corner, temp)
        rows.append((label, isup, measure_op(g, corner, temp),
            measure_ac(g, corner, temp), vout_amp, thd))
    return rows


def gen_challenge(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        corner_list = ", ".join(label for label, _, _ in CORNERS)
        report.markdown(f"""
            # Amplifier Competition

            Build the amplifier inside the `Amp` cell (EDIT HERE marker).
            The `AmpTb` testbench is fixed: 1.2 V supply, input at a DC
            level of 0.6 V with a {VIN_AMP * 1e3:g} mV, {GAIN_FREQ / 1e6:g} MHz
            sine on it, 1 pF load on the output. Meet all specs, then
            **minimize the current — lowest current wins**:

            | Spec | Requirement |
            |---|---|
            | Gain at {GAIN_FREQ / 1e6:g} MHz | ≥ {GAIN_MIN:g} ({GAIN_MIN_DB:.0f} dB) |
            | Output DC level | {VOUT_DC_MIN:g} V … {VOUT_DC_MAX:g} V |
            | Output for the {VIN_AMP * 1e3:g} mV input sine | ≥ {GAIN_MIN * VIN_AMP * 1e3:g} mV amplitude, ≤ {THD_MAX:.0%} distortion |

            All must hold at every process corner and temperature:
            {corner_list}. The score is the current at the first (nominal)
            corner, averaged while the amplifier drives the {VIN_AMP * 1e3:g} mV
            sine: everything the testbench sources deliver, the supply
            *and* the input source (the ideal 0.6 V input is not a free
            supply). The table below the checks shows all corners;
            `report_dc`, `report_ac` and `report_tran` show the nominal
            one.

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
        tran_hint = (f"The {VIN_AMP * 1e3:g} mV input sine must come out "
            f"as a sine, only {GAIN_MIN:g} times larger (see report_tran"
            "). A chain of "
            "starved stages reaches the small-signal gain but limits "
            "instead of amplifying: clipped internal nodes, a square-ish "
            "output, and a bias point that drifts with the signal.")

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
        tran_label = (f"Output for the {VIN_AMP * 1e3:g} mV input sine "
            f"≥ {GAIN_MIN * VIN_AMP * 1e3:g} mV, distortion ≤ {THD_MAX:.0%}")
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
            report.passfail(tran_label, False, instructions=reason,
                hint=tran_hint)
            rows = None

        if rows is not None:
            gain_ok = [gain >= GAIN_MIN for _, _, _, gain, _, _ in rows]
            report.passfail(gain_label, all(gain_ok), hint=gain_hint,
                instructions=f"Gain at {GAIN_FREQ / 1e6:g} MHz: " + ", ".join(
                    f"{gain:.2f} ({20 * math.log10(max(gain, 1e-9)):.1f} dB)"
                    f" at {label}" + ("" if ok else " (fail)")
                    for (label, _, _, gain, _, _), ok in zip(rows, gain_ok))
                + f". Required: ≥ {GAIN_MIN:g} ({GAIN_MIN_DB:.0f} dB) at "
                "every corner.")
            dc_ok = [VOUT_DC_MIN <= vout_dc <= VOUT_DC_MAX
                for _, _, vout_dc, _, _, _ in rows]
            report.passfail(dc_label, all(dc_ok), hint=dc_hint,
                instructions="Output DC level: " + ", ".join(
                    f"{vout_dc:.3f} V at {label}" + ("" if ok else " (fail)")
                    for (label, _, vout_dc, _, _, _), ok in zip(rows, dc_ok))
                + f". Required: {VOUT_DC_MIN:g} V … {VOUT_DC_MAX:g} V at "
                "every corner. The input sits at 0.6 V; your amplifier "
                "must place its own operating point.")
            tran_ok = [vout_amp >= GAIN_MIN * VIN_AMP and thd <= THD_MAX
                for _, _, _, _, vout_amp, thd in rows]
            report.passfail(tran_label, all(tran_ok), hint=tran_hint,
                instructions=f"Output for the {VIN_AMP * 1e3:g} mV input "
                "sine: " + ", ".join(
                    f"{vout_amp * 1e3:.0f} mV amplitude with {thd:.1%} "
                    f"distortion at {label}" + ("" if ok else " (fail)")
                    for (label, _, _, _, vout_amp, thd), ok
                    in zip(rows, tran_ok))
                + f". Required: ≥ {GAIN_MIN * VIN_AMP * 1e3:g} mV with "
                f"distortion ≤ {THD_MAX:.0%} at every corner.")
            report.markdown("Measurements across corners:\n\n"
                f"| Corner | Current | Output DC | Gain at "
                f"{GAIN_FREQ / 1e6:g} MHz | Output amplitude | Distortion |"
                "\n|---|---|---|---|---|---|\n"
                + "\n".join(f"| {label} | {isup * 1e6:.2f} µA | "
                    f"{vout_dc:.3f} V | {gain:.2f} | {vout_amp * 1e3:.0f} mV "
                    f"| {thd:.1%} |"
                    for label, isup, vout_dc, gain, vout_amp, thd in rows))
            eligible = all(e.passed for e in report.elements()
                if isinstance(e, PassFail))
            # In competition course mode, the frontend pushes eligible
            # scores to the workshop scoreboard (see web/src/scoreboard.js).
            report.score(f"Score (current at {rows[0][0]})",
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
