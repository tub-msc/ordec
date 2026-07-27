# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Lesson checks for the 'cmos_circuits' course (CMOS Integrated Circuits).

Each gen_lesson* function takes the lesson namespace (globals) and returns the
lesson() view generator for that lesson: a @generate_func building a Report
whose PassFail elements decide whether the lesson is passed (the course UI
considers a lesson passed when all its PassFail elements pass). Exceptions
during checking are converted into failing PassFail elements, so the view never
crashes on a broken user design.

All lessons use the IHP SG13G2 130nm technology (sg13_lv devices) with a
nominal supply of 1.2 V.
"""

import importlib
import math
import traceback

import ordec.importer  # noqa: F401 -- registers the .ord module loader

from ordec.core import *
from ordec.sim import Simulator
from ordec.lib import Gnd, Vdc
from ordec.lib import ihp130


def exception_text() -> str:
    """Format the current exception for display in a PassFail element."""
    return "The check raised an exception:\n" + traceback.format_exc()


def target_figure(report, cell_name):
    """
    Renders the target circuit's schematic (from the figures module of this
    course) into the report as the circuit the user is asked to build.
    """
    figures = importlib.import_module('ordec.courses.cmos_circuits.figures')
    report.markdown(f"**Target circuit** -- build this in `{cell_name}`:")
    report.svg(getattr(figures, cell_name)().schematic)


def sim_instances_of(h, cell_type):
    """Top-level SimInstances of h whose cell is an instance of cell_type."""
    return [si for si in h.all(SimInstance)
        if si.parent_inst is None and isinstance(si.eref.symbol.cell, cell_type)]


def vtc_threshold(vin, vout):
    """
    Returns the switching threshold (vout == vin crossing) of a voltage
    transfer curve, linearly interpolated, or None if there is no crossing.
    """
    for i in range(1, len(vin)):
        if (vout[i-1] - vin[i-1]) > 0 >= (vout[i] - vin[i]):
            d0 = vout[i-1] - vin[i-1]
            d1 = vout[i] - vin[i]
            return vin[i-1] + d0 / (d0 - d1) * (vin[i] - vin[i-1])
    return None


def max_slope(x, y):
    """Maximum of |dy/dx| over a sampled curve."""
    return max(abs((y[i+1] - y[i]) / (x[i+1] - x[i])) for i in range(len(x)-1))


def ac_magnitude_at(freq, mag, freq_target):
    """Magnitude at the frequency point closest to freq_target."""
    i = min(range(len(freq)), key=lambda j: abs(freq[j] - freq_target))
    return mag[i]


def measure_oscillation(t, vdiff, settle_fraction=0.5):
    """
    Measures an oscillation on the differential signal vdiff(t), ignoring the
    first settle_fraction of the simulated time span.

    Returns (vpp, freq): peak-to-peak amplitude and the frequency estimated
    from the rising zero crossings (0.0 if fewer than two crossings).
    """
    start = int(len(t) * settle_fraction)
    t2 = t[start:]
    d2 = vdiff[start:]
    vpp = max(d2) - min(d2)
    crossings = []
    for i in range(1, len(d2)):
        if d2[i-1] < 0 <= d2[i]:
            frac = -d2[i-1] / (d2[i] - d2[i-1])
            crossings.append(t2[i-1] + frac * (t2[i] - t2[i-1]))
    if len(crossings) >= 2:
        freq = (len(crossings) - 1) / (crossings[-1] - crossings[0])
    else:
        freq = 0.0
    return vpp, freq


# Lesson 1: MOS transistor curves
# -------------------------------

def gen_lesson1(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "Welcome to the CMOS course! Everything here runs in the open "
            "IHP SG13G2 130nm technology; its devices are available in the "
            "[ihp130 cell library](docs:cell_lib/ihp130.html).\n\n"
            "The `MosCurves` testbench is almost ready: supply and gate "
            "voltage sources are placed.\n\n"
            "**Complete the two EDIT HERE markers: import `Nmos` and `Pmos` "
            "from `ordec.lib.ihp130`, then place one of each (w=1u, "
            "l=130n) as shown in the target circuit -- the NMOS `mn` with "
            "its drain on `dn`, the PMOS `mp` with its drain on `dp`.**\n\n"
            "The checks below sweep the gate voltage from 0 V to 1.2 V and "
            "plot the drain currents. Watch how the NMOS turns on as the "
            "gate voltage rises while the PMOS (whose source sits at 1.2 V) "
            "turns off. Once `mn` and `mp` are placed, the lower right "
            "view (`report_curves`) also shows the classic output "
            "characteristics: ID over VDS for several gate voltages."
        )
        target_figure(report, 'MosCurves')
        place_hint = (
            "Import the transistors at the EDIT HERE (import) marker: "
            "`from ordec.lib.ihp130 import Nmos, Pmos`. Then place them at "
            "the EDIT HERE (transistors) marker: `Nmos mn: .$w=1u; "
            ".$l=130n; .g -- gate; .d -- dn; .s -- vss; .b -- vss; "
            ".pos=(22,12)` and the PMOS `mp` the same way with `.d -- dp; "
            ".s -- vdd; .b -- vdd; .pos=(30,12)`.")
        try:
            sch = g['MosCurves']().schematic
            nmos_placed = any(isinstance(i.symbol.cell, ihp130.Nmos)
                for i in sch.all(SchemInstance))
            pmos_placed = any(isinstance(i.symbol.cell, ihp130.Pmos)
                for i in sch.all(SchemInstance))
        except Exception:
            report.passfail("SG13G2 NMOS placed", False,
                instructions=exception_text(), hint=place_hint)
            report.passfail("SG13G2 PMOS placed", False, hint=place_hint)
            return report
        report.passfail("SG13G2 NMOS placed", nmos_placed, hint=place_hint,
            instructions="Place an ordec.lib.ihp130.Nmos in the schematic."
            if not nmos_placed else "Found an SG13G2 NMOS transistor.")
        report.passfail("SG13G2 PMOS placed", pmos_placed, hint=place_hint,
            instructions="Place an ordec.lib.ihp130.Pmos in the schematic."
            if not pmos_placed else "Found an SG13G2 PMOS transistor.")
        if not (nmos_placed and pmos_placed):
            return report

        curve_hint = (
            "Check the connections: NMOS with .g -- gate, .d -- dn, "
            ".s -- vss, .b -- vss; PMOS with .g -- gate, .d -- dp, "
            ".s -- vdd, .b -- vdd. Both with .$w=1u and .$l=130n.")
        try:
            h = SimHierarchy.from_schematic(sch)
            Simulator(h).dc_sweep(sch.vg_src, 0, 1.2, 61, save_params=True)
            vg = [float(v) for v in h.gate.voltage]
            nmos_si = sim_instances_of(h, ihp130.Nmos)[0]
            pmos_si = sim_instances_of(h, ihp130.Pmos)[0]
            idn = [abs(float(v)) for v in nmos_si.params['ids'].value]
            idp = [abs(float(v)) for v in pmos_si.params['ids'].value]
            report.plot2d(
                {"NMOS |ID|": idn, "PMOS |ID|": idp},
                x=vg,
                xlabel="Gate voltage (V)",
                ylabel="Drain current (A)",
                height=260,
            )
            report.passfail("NMOS curve looks right",
                idn[0] < 1e-9 and 100e-6 < idn[-1] < 2e-3,
                hint=curve_hint,
                instructions=f"NMOS |ID| at VGS=0: {idn[0]:.3g} A "
                f"(expected < 1 nA), at VGS=1.2 V: {idn[-1]:.3g} A "
                "(expected 100 uA ... 2 mA).")
            report.passfail("PMOS curve looks right",
                idp[-1] < 1e-9 and 50e-6 < idp[0] < 1e-3,
                hint=curve_hint,
                instructions=f"PMOS |ID| at VSG=1.2 V: {idp[0]:.3g} A "
                f"(expected 50 uA ... 1 mA), at VSG=0: {idp[-1]:.3g} A "
                "(expected < 1 nA).")
        except Exception:
            report.passfail("Transistor curves", False,
                instructions=exception_text(), hint=curve_hint)
        return report
    return lesson


# Lesson 2: Current mirror
# ------------------------

def gen_lesson2(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "`CurrentMirrorTb` feeds a 10 uA reference current into the "
            "`CurrentMirror` cell, whose diode-connected transistor `n0` "
            "turns it into a gate voltage that also drives `n1`. Right now "
            "`n1` is identical to `n0`, so the output current is a 1:1 copy."
            "\n\n"
            "**Change the mirror at the EDIT HERE marker so that it "
            "multiplies the current by 10 (output current 100 uA, within "
            "10 %).**\n\n"
            "Matching matters: real mirrors are built from *identical unit "
            "transistors*. Try making `n1` ten times wider (`.$w=10u`) "
            "first and look closely at the measured current -- then check "
            "the hint."
        )
        mirror_hint = (
            "A transistor that is drawn 10x wider is not exactly 10 "
            "identical transistors: narrow- and wide-width effects change "
            "the current density, so w=10u overshoots by more than 30 %. "
            "Instead, use 10 parallel copies of the unit device: set "
            ".$m=10 (device multiplier) or .$ng=10 (gate fingers) on n1. "
            "The remaining ~2.5 % error comes from the different drain "
            "voltages of n0 and n1 (channel-length modulation).")
        try:
            tb = g['CurrentMirrorTb']()
            h = SimHierarchy.from_schematic(tb.schematic)
            Simulator(h).op()
            iout = abs(float(h.vout_src.p.current[0]))
            vdiode = float(h.iin.voltage[0])
            report.passfail("Mirror input intact",
                0.2 < vdiode < 0.8,
                hint="Keep n0 diode-connected (gate tied to drain) with "
                "w=1u, l=1u, so that the 10 uA reference sets a proper "
                "gate voltage on the shared gate net.",
                instructions=f"Voltage at the mirror input (diode): "
                f"{vdiode:.3f} V (expected 0.2 V ... 0.8 V).")
            report.passfail("Output current = 100 uA (+-10 %)",
                90e-6 <= iout <= 110e-6,
                hint=mirror_hint,
                instructions=f"Measured output current: {iout*1e6:.2f} uA "
                "(target: 100 uA, tolerance: 10 %).")
        except Exception:
            report.passfail("Output current = 100 uA (+-10 %)", False,
                instructions=exception_text(), hint=mirror_hint)
        return report
    return lesson


# Lesson 3: Common-source amplifier
# ---------------------------------

def gen_lesson3(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "One transistor plus one resistor make an amplifier: the input "
            "voltage modulates the transistor's drain current, and the load "
            "resistor turns that current back into a (much larger) voltage "
            "swing at `vout`. The small-signal voltage gain is "
            "$|A| = g_m R_L$.\n\n"
            "`CsAmpTb` biases the input at 0.45 V and applies an AC signal "
            "of magnitude 1, so the AC magnitude at `vout` directly reads "
            "as the gain.\n\n"
            "**Place the NMOS transistor in `CsAmp` at the EDIT HERE "
            "marker and choose its width `w` so that both checks pass.**\n\n"
            "The plots below show the voltage transfer curve (with your "
            "operating point) and the frequency response."
        )
        target_figure(report, 'CsAmp')
        size_hint = (
            "Place the transistor at the EDIT HERE marker: Nmos m0: "
            ".$w=1u; .$l=130n; .g -- vin; .d -- vout; .s -- vss; "
            ".b -- vss; .pos=(6,3) -- then increase w. A wider transistor "
            "has more gm (more gain), but also draws more bias current, "
            "which pulls the operating point down. Around w=10u, both "
            "checks pass.")
        try:
            tb = g['CsAmpTb']()
            h = SimHierarchy.from_schematic(tb.schematic)
            Simulator(h).op()
            vout_op = float(h.vout.voltage[0])

            hdc = SimHierarchy.from_schematic(tb.schematic)
            Simulator(hdc).dc_sweep(tb.schematic.vin_src, 0, 1.2, 61)
            report.plot2d(
                {"V(vout)": [float(v) for v in hdc.vout.voltage],
                 "operating point": [vout_op] * 61},
                x=[float(v) for v in hdc.vin.voltage],
                xlabel="Input voltage (V)",
                ylabel="Output voltage (V)",
                height=220,
            )
            report.passfail("Operating point in the amplifying region",
                0.25 < vout_op < 0.95,
                hint=size_hint,
                instructions=f"V(vout) at the operating point: "
                f"{vout_op:.3f} V (expected 0.25 V ... 0.95 V). In this "
                "region the transistor is saturated and the gain is "
                "highest -- visible as the steep part of the transfer "
                "curve.")

            hac = SimHierarchy.from_schematic(tb.schematic)
            Simulator(hac).ac('dec', 10, 1e3, 1e9)
            freq = [float(f) for f in hac.freq]
            mag = [abs(v) for v in hac.vout.voltage]
            report.plot2d(
                {"|V(vout)| = gain": mag},
                x=freq,
                xlabel="Frequency (Hz)",
                ylabel="Voltage gain",
                xscale=ScaleType.Log,
                height=220,
            )
            gain = ac_magnitude_at(freq, mag, 1e6)
            report.passfail("Voltage gain >= 5", gain >= 5,
                hint=size_hint,
                instructions=f"Measured gain at 1 MHz: {gain:.2f} "
                "(required: >= 5).")
        except Exception:
            report.passfail("Voltage gain >= 5", False,
                instructions=exception_text(), hint=size_hint)
        return report
    return lesson


# Lesson 4: Differential pair
# ---------------------------

def gen_lesson4(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "The differential pair amplifies the *difference* of two "
            "inputs while rejecting what they have in common -- the "
            "workhorse of analog design. Two transistors share one tail "
            "current source; the input difference decides how the tail "
            "current splits between the two branches and thus which load "
            "resistor drops more voltage.\n\n"
            "The loads and the tail transistor are already placed in "
            "`DiffPair`.\n\n"
            "**Add the two pair transistors `m1` and `m2` at the EDIT "
            "HERE marker, as shown in the target circuit.**\n\n"
            "`DiffPairTb` holds `inn` at the 0.7 V common mode and sweeps "
            "`inp` around it; also check out its `sim_dc` and `report_dc` "
            "views."
        )
        target_figure(report, 'DiffPair')
        pair_hint = (
            "Nmos m1: .$w=5u; .$l=130n; .g -- inp; .d -- outp; .s -- tail; "
            ".b -- vss; .pos=(4,7) and the mirrored m2 with .g -- inn; "
            ".d -- outn; .orientation=FlippedSouth at .pos=(14,7). Both "
            "sources share the tail net -- that is the whole trick.")
        try:
            tb = g['DiffPairTb']()
            h = SimHierarchy.from_schematic(tb.schematic)
            Simulator(h).dc_sweep(tb.schematic.vinp_src, 0.4, 1.0, 121)
            vin = [float(v) for v in h.inp.voltage]
            vop = [float(v) for v in h.outp.voltage]
            von = [float(v) for v in h.outn.voltage]
            diff = [p - n for p, n in zip(vop, von)]
            report.plot2d(
                {"outp": vop, "outn": von},
                x=vin,
                xlabel="Vinp (V), Vinn = 0.7 V",
                ylabel="Output voltage (V)",
                height=260,
            )
            mid = len(vin) // 2
            gain = max_slope(vin, diff)
            report.passfail("Differential gain >= 4", gain >= 4,
                hint=pair_hint,
                instructions=f"Maximum differential gain "
                f"d(outp-outn)/d(inp): {gain:.2f} (required: >= 4).")
            balance = abs(vop[mid] - von[mid])
            report.passfail("Outputs balanced at Vinp = 0.7 V",
                balance <= 0.02,
                hint="With identical transistors and identical loads on "
                "both sides, the tail current splits exactly in half when "
                "both inputs are equal -- the outputs must then be equal "
                "too.",
                instructions=f"|V(outp) - V(outn)| at Vinp = 0.7 V: "
                f"{balance*1e3:.1f} mV (expected <= 20 mV).")
            steering = diff[0] >= 0.4 and diff[-1] <= -0.4
            report.passfail("Tail current fully steered", steering,
                hint=pair_hint,
                instructions=f"V(outp)-V(outn) at the sweep ends: "
                f"{diff[0]:+.3f} V / {diff[-1]:+.3f} V (expected >= +0.4 V "
                "and <= -0.4 V): a few 100 mV of input difference steer "
                "the entire tail current into one branch.")
        except Exception:
            report.passfail("Differential gain >= 4", False,
                instructions=exception_text(), hint=pair_hint)
        return report
    return lesson


# Lesson 5: Differential ring oscillator
# --------------------------------------

def gen_lesson5(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "Three differential pairs, connected in a ring, make an "
            "oscillator: each stage inverts and delays the signal, and if "
            "the loop as a whole inverts (negative feedback at DC), the "
            "signal can never settle and races around the ring forever.\n\n"
            "`RingOsc` already contains the three stages and their load "
            "capacitors, but the ring is wired incorrectly and *latches* "
            "instead of oscillating (a flat line below).\n\n"
            "**Fix the wiring of `stage0` (see the EDIT HERE marker), then "
            "look at the waveform and the measured frequency.**\n\n"
            "`RingOscTb` runs a 200 ns transient with `uic=True`, starting "
            "from the capacitors' initial conditions."
        )
        ring_hint = (
            "Count the inversions around the loop: each differential pair "
            "stage inverts (rising inp -> falling outp), so three stages "
            "give three inversions -- already an odd number, which is "
            "exactly what a ring oscillator needs. The extra polarity swap "
            "at stage0 (.inp -- n2; .inn -- p2) makes the number of "
            "inversions even: the loop then has *positive* DC feedback and "
            "latches like a flip-flop. Connect stage0 straight: "
            ".inp -- p2; .inn -- n2.")
        try:
            tb = g['RingOscTb']()
            h = SimHierarchy.from_schematic(tb.schematic)
            Simulator(h).tran(R('50p'), R('200n'), uic=True)
            t = [float(x) for x in h.time]
            vop = [float(v) for v in h.outp.voltage]
            von = [float(v) for v in h.outn.voltage]
            report.plot2d(
                {"outp": vop, "outn": von},
                x=t,
                xlabel="Time (s)",
                ylabel="Voltage (V)",
                height=260,
            )
            vdiff = [p - n for p, n in zip(vop, von)]
            vpp, freq = measure_oscillation(t, vdiff)
            report.passfail("Ring oscillates (amplitude >= 0.3 V)",
                vpp >= 0.3,
                hint=ring_hint,
                instructions=f"Differential peak-to-peak amplitude in the "
                f"second half of the simulation: {vpp:.3f} V (required: "
                ">= 0.3 V).")
            freq_ok = 30e6 <= freq <= 400e6
            report.passfail("Frequency between 30 MHz and 400 MHz", freq_ok,
                hint=ring_hint + " The frequency is set by the RC delay of "
                "the 30k loads and 100f capacitors; with the given sizing "
                "it lands around 120 MHz.",
                instructions=f"Measured oscillation frequency: "
                f"{freq/1e6:.1f} MHz.")
        except Exception:
            report.passfail("Ring oscillates (amplitude >= 0.3 V)", False,
                instructions=exception_text(), hint=ring_hint)
        return report
    return lesson


# Lesson 6: CMOS inverter
# -----------------------

def gen_lesson6(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "Time for digital: the CMOS inverter is the simplest logic "
            "gate -- a PMOS pulls the output high, an NMOS pulls it low, "
            "and (apart from switching moments) no static current flows.\n\n"
            "**Build the inverter in `Inv` at the EDIT HERE marker, then "
            "*size* it so the switching threshold lands at VDD/2 = 0.6 V "
            "(+-3 %) for symmetric noise margins.**\n\n"
            "The plot below shows the voltage transfer curve (VTC) "
            "together with the line `vout = vin`. Their crossing is the "
            "switching threshold."
        )
        target_figure(report, 'Inv')
        build_hint = (
            "Nmos pd: .$w=1u; .$l=130n; .g -- a; .d -- y; .s -- vss; "
            ".b -- vss; .pos=(3,2) and Pmos pu: .$w=1u; .$l=130n; "
            ".g -- a; .d -- y; .s -- vdd; .b -- vdd; .pos=(3,8).")
        size_hint = (
            "Holes are less mobile than electrons: at equal width, the "
            "SG13G2 PMOS conducts roughly half the current of the NMOS, "
            "which pulls the switching threshold below 0.6 V. Make the "
            "PMOS about twice as wide as the NMOS (e.g. wn=1u, wp=2u).")
        try:
            tb = g['InvTb']()
            h = SimHierarchy.from_schematic(tb.schematic)
            Simulator(h).dc_sweep(tb.schematic.vin_src, 0, 1.2, 121)
            vin = [float(v) for v in h.a.voltage]
            vout = [float(v) for v in h.y.voltage]
            report.plot2d(
                {"V(y)": vout, "vout = vin": vin},
                x=vin,
                xlabel="Input voltage (V)",
                ylabel="Output voltage (V)",
                height=260,
            )
            report.passfail("Output high level (VOH >= 1.15 V)",
                vout[0] >= 1.15,
                hint=build_hint,
                instructions=f"V(y) at vin = 0: {vout[0]:.3f} V. The PMOS "
                "must pull the output all the way to VDD.")
            report.passfail("Output low level (VOL <= 0.05 V)",
                vout[-1] <= 0.05,
                hint=build_hint,
                instructions=f"V(y) at vin = 1.2 V: {vout[-1]:.3f} V. The "
                "NMOS must pull the output all the way to ground.")
            vth = vtc_threshold(vin, vout)
            if vth is None:
                report.passfail("Switching threshold at 0.6 V (+-3 %)",
                    False, hint=build_hint,
                    instructions="The VTC never crosses vout = vin -- the "
                    "inverter is probably still incomplete.")
            else:
                report.passfail("Switching threshold at 0.6 V (+-3 %)",
                    0.59 <= vth <= 0.635,
                    hint=size_hint,
                    instructions=f"Measured switching threshold: "
                    f"{vth:.3f} V (target: 0.59 V ... 0.635 V).")
        except Exception:
            report.passfail("Output high level (VOH >= 1.15 V)", False,
                instructions=exception_text(), hint=build_hint)
        return report
    return lesson


# Lesson 7: NAND2 gate
# --------------------

def gen_lesson7(g):
    dut = g['Nand2']

    class CheckNand2Tb(Cell):
        """Operating-point testbench applying static input levels."""
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
            s.gnd = SchemInstance(
                Gnd().symbol.portmap(p=s.vss), pos=Vec2R(0, 0))
            s.vdd_src = SchemInstance(
                Vdc(dc=R('1.2')).symbol.portmap(m=s.vss, p=s.vdd),
                pos=Vec2R(0, 6))
            s.va_src = SchemInstance(
                Vdc(dc=self.a).symbol.portmap(m=s.vss, p=s.a), pos=Vec2R(6, 6))
            s.vb_src = SchemInstance(
                Vdc(dc=self.b).symbol.portmap(m=s.vss, p=s.b), pos=Vec2R(12, 6))
            s.dut = SchemInstance(dut().symbol.portmap(
                vdd=s.vdd, vss=s.vss, a=s.a, b=s.b, y=s.y), pos=Vec2R(18, 6))
            s.auto_wire()
            s.check(add_conn_points=True, add_terminal_taps=True)
            return s

    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "With more transistors, the inverter generalizes to any "
            "inverting logic function. The `Nand2` cell already has the "
            "right symbol (inputs `a` and `b`, output `y`), but its "
            "schematic is still just an inverter driven by `a`.\n\n"
            "**Extend it at the EDIT HERE marker so that the cell "
            "implements `y = !(a & b)`: NMOS transistors in *series* pull "
            "low only when all inputs are high; PMOS transistors in "
            "*parallel* pull high when any input is low.**\n\n"
            "Each check applies one combination of static input levels and "
            "verifies the output with an operating point simulation "
            "(VDD = 1.2 V). `Nand2Tb` does the same interactively."
        )
        target_figure(report, 'Nand2')
        nand_hint = (
            "You need an additional internal net between the two series "
            "NMOS transistors: net x, then n1 with .d -- x and n2 with "
            ".s -- x; .d -- y; .g -- b. The second PMOS p2 sits in "
            "parallel to p1 (.s -- vdd; .d -- y) with .g -- b. Remember "
            "to add the new transistors to the sizing loop.")
        for a, b in ((0, 0), (0, 1), (1, 0), (1, 1)):
            expect_high = not (a and b)
            label = f"a={a}, b={b} => y={int(expect_high)}"
            try:
                tb = CheckNand2Tb(a=a * R('1.2'), b=b * R('1.2'))
                h = SimHierarchy.from_schematic(tb.schematic)
                Simulator(h).op()
                y = float(h.y.voltage[0])
                if expect_high:
                    passed = y > 0.9 * 1.2
                else:
                    passed = y < 0.1 * 1.2
                report.passfail(label, passed, hint=nand_hint,
                    instructions=f"Simulated y = {y:.3f} V, expected "
                    f"{'> 1.08' if expect_high else '< 0.12'} V.")
            except Exception:
                report.passfail(label, False,
                    instructions=exception_text(), hint=nand_hint)
        return report
    return lesson


# Lesson 8: Self-biased inverter
# ------------------------------

def gen_lesson8(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "A digital inverter is secretly an analog amplifier: right at "
            "its switching threshold, the VTC from lesson 6 is at its "
            "steepest -- both transistors are saturated and their $g_m$ "
            "adds up. The trick is to *keep* it there: a feedback resistor "
            "from output to input forces v(a) = v(y) (no DC current flows "
            "into the gates), so the inverter biases itself exactly at the "
            "threshold. This circuit amplifies AC signals coupled in "
            "through a capacitor -- the classic crystal oscillator "
            "amplifier.\n\n"
            "In `InvAmp`, the feedback resistor `rf` is far too small and "
            "feeds the output signal back to the input, destroying the "
            "gain.\n\n"
            "**Increase `rf` at the EDIT HERE marker until the checks "
            "pass.**\n\n"
            "The plot shows the gain over frequency."
        )
        rf_hint = (
            "The feedback resistor must be large compared to the "
            "amplifier's impedance level, otherwise the output 'fights' "
            "the input signal through rf (the gain approaches 1, like a "
            "unity-gain buffer). Values of 100k and above work; 1M (.$r=1M) "
            "is a good choice. Note how the operating point check passes "
            "even with a small rf -- self-biasing works at any rf value, "
            "only the AC gain suffers.")
        try:
            tb = g['InvAmpTb']()
            h = SimHierarchy.from_schematic(tb.schematic)
            Simulator(h).op()
            va = float(h.ain.voltage[0])
            vy = float(h.yout.voltage[0])
            report.passfail("Self-biased at the switching threshold",
                abs(va - vy) <= 0.02 and 0.4 <= vy <= 0.8,
                hint="The feedback resistor connects the inverter input "
                "and output; without it, the input node floats.",
                instructions=f"Operating point: v(a) = {va:.3f} V, "
                f"v(y) = {vy:.3f} V (expected: equal within 20 mV, "
                "between 0.4 V and 0.8 V).")
            hac = SimHierarchy.from_schematic(tb.schematic)
            Simulator(hac).ac('dec', 10, 1e3, 1e10)
            freq = [float(f) for f in hac.freq]
            mag = [abs(v) for v in hac.yout.voltage]
            report.plot2d(
                {"|V(yout)| = gain": mag},
                x=freq,
                xlabel="Frequency (Hz)",
                ylabel="Voltage gain",
                xscale=ScaleType.Log,
                height=240,
            )
            gain = ac_magnitude_at(freq, mag, 5e6)
            report.passfail("Mid-band gain >= 10", gain >= 10,
                hint=rf_hint,
                instructions=f"Measured gain at 5 MHz: {gain:.2f} "
                "(required: >= 10). The gain rolls off below the "
                "highpass corner set by the coupling capacitor and "
                "above the lowpass corner set by the load.")
        except Exception:
            report.passfail("Mid-band gain >= 10", False,
                instructions=exception_text(), hint=rf_hint)
        return report
    return lesson


# Lesson 9: Standard cell: NOR2
# -----------------------------

def gen_lesson9(g):
    dut = g['Nor2']

    class CheckNor2Tb(Cell):
        """Operating-point testbench applying static input levels."""
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
            s.gnd = SchemInstance(
                Gnd().symbol.portmap(p=s.vss), pos=Vec2R(0, 0))
            s.vdd_src = SchemInstance(
                Vdc(dc=R('1.2')).symbol.portmap(m=s.vss, p=s.vdd),
                pos=Vec2R(0, 6))
            s.va_src = SchemInstance(
                Vdc(dc=self.a).symbol.portmap(m=s.vss, p=s.a), pos=Vec2R(6, 6))
            s.vb_src = SchemInstance(
                Vdc(dc=self.b).symbol.portmap(m=s.vss, p=s.b), pos=Vec2R(12, 6))
            s.dut = SchemInstance(dut().symbol.portmap(
                vdd=s.vdd, vss=s.vss, a=s.a, b=s.b, y=s.y), pos=Vec2R(18, 6))
            s.auto_wire()
            s.check(add_conn_points=True, add_terminal_taps=True)
            return s

    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "Digital chips are assembled from *standard cells*: a library "
            "of pre-designed, pre-verified gates on a common height grid "
            "that place-and-route tools can tile into rows. This lesson "
            "recreates the schematic of the SG13G2 library's NOR2 cell -- "
            "with the *original transistor sizes* -- and then looks at the "
            "real thing.\n\n"
            "**Build `Nor2` at the EDIT HERE marker (`y = !(a | b)`: "
            "parallel NMOS, stacked PMOS, NMOS w=740n, PMOS w=1.12u).**\n\n"
            "### Layout tour\n\n"
            "The lesson file loads the real standard cell library via "
            "[ExtLibrary](docs:ref/extlibrary.html) -- the second result "
            "tab shows the actual layout of `sg13g2_nor2_1`. Things to "
            "spot: the horizontal `vdd`/`vss` metal rails at top and "
            "bottom (shared between neighboring rows), the N-well under "
            "the two PMOS transistors, the two vertical polysilicon gate "
            "stripes crossing both device rows (each stripe is one input "
            "driving one NMOS *and* one PMOS), and the stacked PMOS pair "
            "sharing one diffusion region. Layout design is the topic of "
            "the layout course -- see also the "
            "[layout how-to](docs:howto_layout.html)."
        )
        target_figure(report, 'Nor2')
        nor_hint = (
            "Mirror image of the NAND2: net x between the stacked PMOS "
            "transistors (p1 with .s -- vdd; .d -- x; .g -- a, p2 with "
            ".s -- x; .d -- y; .g -- b), and both NMOS transistors in "
            "parallel from y to vss (gates a and b). Sizes: NMOS .$w=740n, "
            "PMOS .$w=1.12u, all .$l=130n.")
        for a, b in ((0, 0), (0, 1), (1, 0), (1, 1)):
            expect_high = not (a or b)
            label = f"a={a}, b={b} => y={int(expect_high)}"
            try:
                tb = CheckNor2Tb(a=a * R('1.2'), b=b * R('1.2'))
                h = SimHierarchy.from_schematic(tb.schematic)
                Simulator(h).op()
                y = float(h.y.voltage[0])
                if expect_high:
                    passed = y > 0.9 * 1.2
                else:
                    passed = y < 0.1 * 1.2
                report.passfail(label, passed, hint=nor_hint,
                    instructions=f"Simulated y = {y:.3f} V, expected "
                    f"{'> 1.08' if expect_high else '< 0.12'} V.")
            except Exception:
                report.passfail(label, False,
                    instructions=exception_text(), hint=nor_hint)
        return report
    return lesson


# Lesson 10: 5-transistor OTA
# ---------------------------

def gen_lesson10(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "The capstone: an operational transconductance amplifier that "
            "combines lesson 2 (current mirror) with lesson 4 "
            "(differential pair). Replacing the two load resistors by a "
            "PMOS current mirror does two things at once: the mirror "
            "*folds* m1's signal current onto the output, doubling the "
            "single-ended gain, and without resistors the output can swing "
            "almost rail to rail.\n\n"
            "**Rebuild the loads at the EDIT HERE marker and size the OTA "
            "to meet the specs** (the hints of the failing checks give "
            "topology and sizing tips):\n\n"
            "| Spec | Requirement |\n"
            "|---|---|\n"
            "| DC gain | >= 12 (21.6 dB) |\n"
            "| Supply current | <= 50 uA |\n"
            "| Output swing | >= 0.8 V |\n\n"
            "The gain is measured as the maximum slope of the DC transfer "
            "curve below (open loop, `inn` fixed at 0.7 V)."
        )
        ota_hint = (
            "Replace rl_p/rl_n by PMOS transistors m3 (diode-connected: "
            ".d -- outx; .g -- outx; .s -- vdd; .b -- vdd; .pos=(8,13); "
            ".orientation=FlippedSouth) and m4 (.g -- outx; .d -- out; "
            ".s -- vdd; .b -- vdd; .pos=(10,13)). For enough gain, use "
            "l=300n for m1..m4 (longer channel = higher intrinsic gain "
            "gm/gds) with w=5u; the short l=130n of the starting point "
            "wastes gain. Keep mtail at w=3u, l=1u -- widening it costs "
            "supply current.")
        try:
            tb = g['OtaTb']()
            h = SimHierarchy.from_schematic(tb.schematic)
            Simulator(h).dc_sweep(tb.schematic.vinp_src, 0.55, 0.85, 241)
            vin = [float(v) for v in h.inp.voltage]
            vout = [float(v) for v in h.out.voltage]
            report.plot2d(
                {"V(out)": vout},
                x=vin,
                xlabel="Vinp (V), Vinn = 0.7 V",
                ylabel="Output voltage (V)",
                height=260,
            )
            gain = max_slope(vin, vout)
            report.passfail("DC gain >= 12", gain >= 12,
                hint=ota_hint,
                instructions=f"Maximum slope of the transfer curve: "
                f"{gain:.1f} ({20*math.log10(max(gain, 1e-9)):.1f} dB), "
                "required: >= 12 (21.6 dB).")
            swing = max(vout) - min(vout)
            report.passfail("Output swing >= 0.8 V", swing >= 0.8,
                hint=ota_hint,
                instructions=f"Output range over the sweep: {swing:.3f} V "
                "(required: >= 0.8 V).")
            hop = SimHierarchy.from_schematic(tb.schematic)
            Simulator(hop).op()
            isup = abs(float(hop.vdd_src.p.current[0]))
            report.passfail("Supply current <= 50 uA", isup <= 50e-6,
                hint="The supply current is essentially the tail current "
                "set by mtail and the bias voltage. If you widened mtail "
                "or shortened its channel, the current went up.",
                instructions=f"Current drawn from the 1.2 V supply at the "
                f"balance point: {isup*1e6:.1f} uA (allowed: <= 50 uA).")
        except Exception:
            report.passfail("DC gain >= 12", False,
                instructions=exception_text(), hint=ota_hint)
        return report
    return lesson
