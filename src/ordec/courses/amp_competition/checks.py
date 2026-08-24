# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Competition check for the 'amp_competition' course (Amplifier Competition).

One lesson: design an amplifier inside the fixed Amp symbol, meet the spec
gates, minimize supply current. gen_challenge renders rules, gates and the
score as the lesson() view. The measurement functions and gate constants are
also used by support/hub/rescore.py for the verified final ranking, so they
must stay importable without side effects.

Like the cmos_circuits checks, a half-finished design is an expected state:
simulation-based gates report a friendly status while the structure is
incomplete, and tracebacks are reserved for unexpected failures.
"""

import math
import traceback

from ordec.core import *
from ordec.lib import ihp130

# Spec gates. The score (supply current) only counts with all gates passing;
# rescore.py applies the same numbers, and all displayed texts derive from
# them, so retuning after playtesting is a one-place edit.
GAIN_MIN = 20.0      # V/V at 1 kHz
GAIN_MIN_DB = 20 * math.log10(GAIN_MIN)
GBW_MIN = 10e6       # Hz unity-gain frequency, into the 1 pF load
VOUT_DC_MIN = 0.35   # V
VOUT_DC_MAX = 0.85   # V

# Physical IHP devices only. ihp130.Res covers Rsil/Rppd/Rhigh; ideal
# elements (ordec.lib Res/Cap/...) are excluded on purpose: an ideal
# resistor load would buy arbitrary gain at no current cost.
ALLOWED_DEVICES = (ihp130.Nmos, ihp130.Pmos, ihp130.Res)


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


def measure_op(g):
    """(supply current in A, output DC voltage in V) at the operating point."""
    h = g['AmpTb']().sim_op
    return abs(float(h.vdd_src.p.current[0])), float(h.vout.voltage[0])


def measure_ac(g):
    """(gain in V/V at 1 kHz, unity-gain frequency in Hz).

    The testbench drives vin with ac_mag=1, so |v(vout)| is the gain. The
    unity crossing is interpolated on a log frequency axis; a response that
    never reaches 1 has GBW 0, one still above 1 at the end of the sweep is
    credited with the sweep end.
    """
    h = g['AmpTb']().sim_ac
    freq = [float(f) for f in h.freq]
    mag = [abs(v) for v in h.vout.voltage]
    for i in range(1, len(mag)):
        if mag[i - 1] >= 1 > mag[i]:
            ratio = (mag[i - 1] - 1) / (mag[i - 1] - mag[i])
            gbw = freq[i - 1] * (freq[i] / freq[i - 1]) ** ratio
            break
    else:
        gbw = freq[-1] if mag[-1] >= 1 else 0.0
    return mag[0], gbw


def gen_challenge(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown(f"""
            # Amplifier Competition

            Build the amplifier inside the `Amp` cell (EDIT HERE marker).
            The `AmpTb` testbench is fixed: 1.2 V supply, input driven at
            a DC level of 0.6 V, 1 pF load on the output. Meet all specs,
            then **minimize the supply current — lowest current wins**:

            | Spec | Requirement |
            |---|---|
            | Gain at 1 kHz | ≥ {GAIN_MIN:g} ({GAIN_MIN_DB:.0f} dB) |
            | Unity-gain frequency | ≥ {GBW_MIN / 1e6:g} MHz |
            | Output DC level | {VOUT_DC_MIN:g} V … {VOUT_DC_MAX:g} V |

            Only physical IHP SG13G2 devices are allowed inside `Amp`:
            `Nmos`, `Pmos` and the resistors `Rsil`, `Rppd`, `Rhigh`
            (low/medium/high sheet resistance), all from `ordec.lib.ihp130`.
            No ideal elements. Unlike the ideal `Res`, the physical
            resistors have a substrate pin `bn`, normally tied to `vss`:

                Rppd r1: .$w=1u; .$l=10u; .p -- vdd; .n -- vout; .bn -- vss; .pos=(6,9)

            Watch your design in the `report_dc` and `report_ac` views.
            Your score appears on the scoreboard automatically whenever
            all checks pass.
        """)

        # Hints level the field without giving away sizings.
        devices_hint = ("Everything inside Amp (including your own "
            "subcells) must be an ihp130 Nmos, Pmos, Rsil, Rppd or Rhigh. "
            "Ideal elements are rejected: an ideal resistor would make "
            "gain free.")
        gain_hint = (f"A resistor-loaded common-source stage cannot reach "
            f"{GAIN_MIN:g} here: its gain is capped by the DC drop across "
            "the load. The CMOS course's inverter lessons show loads that "
            "do better.")
        gbw_hint = ("The 1 pF load sets the price of speed: the "
            "unity-gain frequency follows from how much transconductance "
            "drives the output node, and transconductance costs current.")
        dc_hint = ("The input sits fixed at 0.6 V, so the output level is "
            "set by your device ratios (or by resistive feedback). The "
            "transfer curve in report_dc shows where you are.")

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

        def sim_failed_text():
            if structure_ok:
                return exception_text()
            return ("The simulation failed -- usually the amplifier is "
                "still incomplete (see the device check above).")

        gain_label = f"Gain at 1 kHz ≥ {GAIN_MIN:g}"
        gbw_label = f"Unity-gain frequency ≥ {GBW_MIN / 1e6:g} MHz"
        try:
            gain, gbw = measure_ac(g)
            report.passfail(gain_label, gain >= GAIN_MIN,
                hint=gain_hint,
                instructions=f"Gain at 1 kHz: {gain:.2f} "
                f"({20 * math.log10(max(gain, 1e-9)):.1f} dB), "
                f"required: ≥ {GAIN_MIN:g} ({GAIN_MIN_DB:.0f} dB).")
            report.passfail(gbw_label, gbw >= GBW_MIN,
                hint=gbw_hint,
                instructions=f"Unity-gain frequency: {gbw / 1e6:.2f} MHz, "
                f"required: ≥ {GBW_MIN / 1e6:g} MHz.")
        except Exception:
            reason = sim_failed_text()
            report.passfail(gain_label, False, instructions=reason,
                hint=gain_hint)
            report.passfail(gbw_label, False, instructions=reason,
                hint=gbw_hint)

        dc_label = (f"Output DC level {VOUT_DC_MIN:g} V … "
            f"{VOUT_DC_MAX:g} V")
        isup = None
        try:
            isup, vout_dc = measure_op(g)
            report.passfail(dc_label,
                VOUT_DC_MIN <= vout_dc <= VOUT_DC_MAX, hint=dc_hint,
                instructions=f"Output DC level: {vout_dc:.3f} V, required: "
                f"{VOUT_DC_MIN:g} V … {VOUT_DC_MAX:g} V. The input sits at "
                "0.6 V; your amplifier must place its own operating point.")
        except Exception:
            report.passfail(dc_label, False,
                instructions=sim_failed_text(), hint=dc_hint)

        if isup is not None:
            eligible = all(e.passed for e in report.elements()
                if isinstance(e, PassFail))
            # In competition course mode, the frontend pushes eligible
            # scores to the workshop scoreboard (see web/src/scoreboard.js).
            report.score("Score (supply current)", isup * 1e6, unit="µA",
                eligible=eligible)
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
