# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Lesson checks for the 'cmos_circuits' course (CMOS Integrated Circuits).

Each gen_lesson* function takes the lesson namespace (globals) and returns the
lesson() view generator for that lesson: a @viewgen_noctx building a Report
whose PassFail elements decide whether the lesson is passed (the course UI
considers a lesson passed when all its PassFail elements pass). Exceptions
during checking are converted into failing PassFail elements, so the view never
crashes on a broken user design.

The checks are fine-grained, but every step corresponds to one complete
edit (an import, a fully wired device, a structure change) -- never a
half-finished source state. Simulation-based checks then verify the
finished circuit. Each lesson emits a fixed number of PassFail elements in
every state, so the red/green pattern stays stable while the user works.

Wherever a lesson defines the needed analysis as a sim_* view, the check
reads that view instead of running its own Simulator: the view cache then
shares one simulator run between the check and the user's open result
views. Only analyses the lessons do not define (lesson 3's operating
point, lesson 8's per-input testbench) simulate on their own.

A half-finished design is an expected state, not an error: every lesson
captures the result of its structure check and passes it to
sim_failure_text(), so that a simulation failing on an incomplete circuit
explains itself instead of showing a Python traceback. Tracebacks are
reserved for failures that persist once the structure is correct.

All lessons use the IHP SG13G2 130nm technology (sg13_lv devices) with a
nominal supply of 1.2 V.
"""

import math

from ordec.core import *
from ordec.sim import Simulator
from ordec.lib import Gnd, Vdc, Res
from ordec.lib import ihp130

from ..common import exception_text, blocked_passfails, sim_failure_text


def instances_of(schematic, cell_type):
    """SchemInstances of schematic whose cell is an instance of cell_type."""
    return [i for i in schematic.all(SchemInstance)
        if isinstance(i.symbol.cell, cell_type)]


def pin_nets(inst):
    """Maps pin names of a SchemInstance to the nets they connect to."""
    return {c.there.full_path_str(): c.here for c in inst.conns()}


def wrong_pins(inst, target):
    """
    Names of the pins of inst that do not match target ({pin: net}).

    Status texts name these pins but never the nets they should go to:
    the pin-by-pin wiring belongs into the hint, which the user opens
    deliberately.
    """
    conns = pin_nets(inst)
    return [pin for pin, net in target.items() if conns.get(pin) != net]


def best_match(insts, target):
    """The instance of insts that comes closest to the target wiring."""
    return min(insts, key=lambda i: len(wrong_pins(i, target)))


def misplaced(inst, x, y):
    """Where inst sits when that is not (x, y), else None."""
    ax, ay = float(inst.pos.x), float(inst.pos.y)
    if (ax, ay) == (float(x), float(y)):
        return None
    return f"at ({ax:g},{ay:g}) instead of ({x},{y})"


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


def bandwidth_3db(freq, mag):
    """
    -3 dB bandwidth of a lowpass response, referenced to the lowest swept
    frequency. Returns the end of the sweep if the response never drops.
    """
    ref = mag[0] / math.sqrt(2)
    return next((f for f, m in zip(freq, mag) if m < ref), freq[-1])


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


def guarded_passfail(report, label, checker, hint):
    """
    Runs checker() and reports its (passed, instructions) result under label,
    converting an exception into a failing PassFail with the traceback.
    """
    try:
        passed, instructions = checker()
    except Exception:
        passed, instructions = False, exception_text()
    report.passfail(label, passed, instructions=instructions, hint=hint)
    return passed


# Lesson 1: MOS transistor curves
# -------------------------------

def gen_lesson1(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            Welcome to the CMOS integrated circuits course! All lessons use the
            open IHP SG13G2 130nm technology at a 1.2 V supply, from the [ihp130
            cell library](docs:cell_lib/ihp130.html).

            We start with the transistor itself. The `MosCurves` testbench
            is ready except for the two devices: one source drives both
            gates, and each drain has a source of its own so that the two
            currents can be measured separately.

            1. **Import Nmos and Pmos from the ihp130 library** at the first
               EDIT HERE marker using `from ordec.lib.ihp130 import Nmos, Pmos`.
            2. **Place and wire the NMOS** `mn` at the second marker:
               `$w=1u`, `$l=130n`, at position `(10,12)`.
            3. **Place and wire the PMOS** `mp` the same way: `$w=1u`,
               `$l=130n`, at position `(25,12)`.

            Each check below tells you what it is missing, and its hint
            spells out the pin connections. Once both transistors are in,
            the `report_curves` view plots their output characteristics.
        """)

        import_hint = ("The library module is called `ordec.lib.ihp130`, "
            "and both cells are imported from there by name.")
        imported = (g.get('Nmos') is ihp130.Nmos
            and g.get('Pmos') is ihp130.Pmos)
        report.passfail("Nmos and Pmos imported", imported,
            hint=import_hint,
            instructions="Looking for ihp130's Nmos and Pmos in the "
            "lesson namespace.")

        def device_check(cls, target_names, pos, where_text):
            def checker():
                sch = g['MosCurves']().schematic
                insts = instances_of(sch, cls)
                if not insts:
                    return False, (f"Looking for an ihp130."
                        f"{cls.__name__} instance {where_text}.")
                target = {pin: getattr(sch, net)
                    for pin, net in target_names.items()}
                inst = best_match(insts, target)
                wrong = wrong_pins(inst, target)
                if wrong:
                    return False, (f"{cls.__name__} placed, but these "
                        "pins are not connected as the testbench needs "
                        f"them: {', '.join(wrong)}.")
                where = misplaced(inst, *pos)
                if where:
                    return False, (f"{cls.__name__} is wired correctly, "
                        f"but it sits {where}.")
                return True, f"{cls.__name__} placed and wired."
            return checker

        nmos_ok = guarded_passfail(report, "SG13G2 NMOS placed and wired",
            device_check(ihp130.Nmos,
                {'g': 'gate', 'd': 'drain_n', 's': 'vss', 'b': 'vss'},
                (10, 12), "with w=1u, l=130n at position (10,12)"),
            hint="`g` to `gate`, `d` to `drain_n`, `s` to `vss`, `b` to "
            "`vss`. "
            "An NMOS sits on ground, which is why both source and bulk "
            "go there.")

        pmos_ok = guarded_passfail(report, "SG13G2 PMOS placed and wired",
            device_check(ihp130.Pmos,
                {'g': 'gate', 'd': 'drain_p', 's': 'vdd', 'b': 'vdd'},
                (25, 12), "with w=1u, l=130n at position (25,12)"),
            hint="`g` to `gate`, `d` to `drain_p`, `s` to `vdd`, `b` to "
            "`vdd`. "
            "The PMOS hangs on the supply instead of on ground.")

        curve_hints = (
            "The NMOS must be off at VGS=0 and carry a few hundred "
            "microamps at 1.2 V. If it stays off, check w=1u and "
            "l=130n. If it conducts at 0 V, its source is not on `vss`.",
            "The PMOS hangs on the 1.2 V supply, so it conducts at a "
            "gate voltage of 0 V and turns off at 1.2 V. If it never "
            "conducts, its source and bulk are not on `vdd`.")
        curve_labels = ("NMOS curve looks right", "PMOS curve looks right")
        if not (nmos_ok and pmos_ok):
            blocked_passfails(report, curve_labels, curve_hints,
                "The sweep runs once both transistors are placed and "
                "wired.")
            return report
        try:
            h = g['MosCurves']().sim_vgs
            nmos_si = sim_instances_of(h, ihp130.Nmos)[0]
            pmos_si = sim_instances_of(h, ihp130.Pmos)[0]
            idn = [abs(float(v)) for v in nmos_si.params['ids'].value]
            idp = [abs(float(v)) for v in pmos_si.params['ids'].value]
            report.passfail(curve_labels[0],
                idn[0] < 1e-9 and 100e-6 < idn[-1] < 2e-3,
                hint=curve_hints[0],
                instructions=f"NMOS |ID| at VGS=0: {idn[0]:.3g} A "
                f"(expected < 1 nA), at VGS=1.2 V: {idn[-1]:.3g} A "
                "(expected 100 µA ... 2 mA).")
            report.passfail(curve_labels[1],
                idp[-1] < 1e-9 and 50e-6 < idp[0] < 1e-3,
                hint=curve_hints[1],
                instructions=f"PMOS |ID| at VSG=1.2 V: {idp[0]:.3g} A "
                f"(expected 50 µA ... 1 mA), at VSG=0: {idp[-1]:.3g} A "
                "(expected < 1 nA).")
        except Exception:
            blocked_passfails(report, curve_labels, curve_hints,
                exception_text())
        return report
    return lesson


# Lesson 2: Current mirror
# ------------------------

def gen_lesson2(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            A current mirror copies a current. The diode-connected `n0`
            turns the 10 µA reference into a gate voltage, and `n1`
            shares that gate voltage. Both transistors are identical today,
            so the copy is 1:1.

            **Edit `n1` at the EDIT HERE marker so that the output current
            becomes 100 µA (within 10 %). Leave `n0` unchanged.**

            The transistors have four parameters:

            | Parameter | Meaning |
            |---|---|
            | `w` | total width of the device |
            | `l` | channel length |
            | `m` | number of identical devices in parallel |
            | `ng` | number of gate fingers the width is split into |

            Start by making `n1` ten times wider (`.$w=10u`) and read the
            measured current in the last check: it overshoots. Try to work
            out why, and experiment with the parameters above to see which
            of them actually scale the current. The hints are there if you
            get stuck.
        """)
        unit_hint = (
            "`n1` has to be ten copies of `n0`'s unit transistor, either "
            "as ten devices in parallel or as one device split into ten "
            "fingers of `n0`'s width. Scaling the width alone is not a "
            "copy, and trimming it until the current happens to fit "
            "gives a ratio that drifts with temperature and process.")
        current_hint = (
            "A wide transistor carries more current per micron than a "
            "narrow one, so w=10u overshoots to 136 µA. Ten unit devices "
            "land at 102.5 µA. The remaining 2.5 % is channel-length "
            "modulation, because `n0` and `n1` sit at different drain "
            "voltages.")

        def unit_devices():
            sch = g['CurrentMirror']().schematic
            devs = instances_of(sch, ihp130.Nmos)
            ref = [i for i in devs
                if pin_nets(i).get('g') == pin_nets(i).get('d')]
            out = [i for i in devs
                if pin_nets(i).get('g') != pin_nets(i).get('d')]
            if not (ref and out):
                return False, ("The mirror needs the diode-connected "
                    "reference n0 and the output transistor n1.")
            rc, oc = ref[0].symbol.cell, out[0].symbol.cell
            unit_w = float(rc.w) / rc.ng
            finger_w = float(oc.w) / oc.ng
            copies = (oc.m * float(oc.w)) / (rc.m * float(rc.w))
            found = (math.isclose(copies, 10, rel_tol=1e-9)
                and math.isclose(finger_w, unit_w, rel_tol=1e-9)
                and math.isclose(float(oc.l), float(rc.l), rel_tol=1e-9))
            return found, (f"n1 has {copies:g} times the total width of "
                f"n0, drawn as {finger_w*1e6:g} um wide fingers.")

        sim_error = None
        iout = vdiode = None
        try:
            h = g['CurrentMirrorTb']().sim_op
            iout = abs(float(h.vout_src.p.current[0]))
            vdiode = float(h.iin.voltage[0])
        except Exception:
            sim_error = exception_text()

        label = "Mirror input intact"
        diode_hint = ("Keep `n0` diode-connected (gate tied to drain) with "
            "w=1u, l=1u, so that the 10 µA reference sets a proper gate "
            "voltage on the shared gate net.")
        if sim_error is not None:
            report.passfail(label, False, instructions=sim_error,
                hint=diode_hint)
        else:
            report.passfail(label, 0.2 < vdiode < 0.8, hint=diode_hint,
                instructions=f"Voltage at the mirror input (diode): "
                f"{vdiode:.3f} V (expected 0.2 V ... 0.8 V).")

        guarded_passfail(report, "Mirror built from ten unit transistors",
            unit_devices, hint=unit_hint)

        label = "Output current = 100 µA (±10 %)"
        if sim_error is not None:
            # The first check already carries the simulation failure, so
            # this one points at it instead of repeating the traceback.
            report.passfail(label, False, hint=current_hint,
                instructions="The output current is measured once the "
                "mirror simulates (see the first check).")
        else:
            report.passfail(label, 90e-6 <= iout <= 110e-6,
                hint=current_hint,
                instructions=f"Measured output current: {iout*1e6:.2f} µA "
                "(target: 100 µA, tolerance: 10 %).")
        return report
    return lesson


# Lesson 3: Common-source amplifier
# ---------------------------------

def gen_lesson3(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            One transistor and one resistor make an **amplifier**: the input
            modulates the drain current, and the load resistor turns it back
            into a voltage swing at `vout`. The gain is $|A| = g_m R_L$.

            1. **Place and wire the transistor** `m0` at the EDIT HERE
               marker: `$l=130n` at position `(6,3)`, starting from `$w=1u`.
            2. **Increase its width `$w` until the gain reaches 5.** A wider
               transistor gives more gain, but also draws more bias current,
               which pulls the operating point down.

            `CsAmpTb` adds an AC signal of magnitude 1, so the gain can be
            read directly in the `report_ac` view.
        """)
        op_hint = (
            "`vout` sits at 1.2 V while the transistor is too narrow to "
            "draw current, and collapses towards 0 V once it is too "
            "wide. Adjust w until `vout` settles between 0.25 V and "
            "0.95 V.")
        gain_hint = (
            "The gain is gm times the 10k load, and gm grows with the "
            "width. Around w=10u the gain passes 5 while the operating "
            "point still holds.")

        def nmos_ok():
            sch = g['CsAmp']().schematic
            insts = instances_of(sch, ihp130.Nmos)
            if not insts:
                return False, ("Looking for an ihp130.Nmos instance at "
                    "position (6,3) in the CsAmp schematic (l=130n, "
                    "start with w=1u).")
            target = {'g': sch.vin, 'd': sch.vout, 's': sch.vss,
                'b': sch.vss}
            inst = best_match(insts, target)
            wrong = wrong_pins(inst, target)
            if wrong:
                return False, ("Transistor placed, but these pins are "
                    "not connected as the amplifier needs them: "
                    + ", ".join(wrong) + ".")
            where = misplaced(inst, 6, 3)
            if where:
                return False, ("The transistor is wired correctly, but "
                    f"it sits {where}.")
            return True, "Transistor placed and wired."
        device_ok = guarded_passfail(report, "NMOS placed and wired",
            nmos_ok,
            hint="`g` to `vin`, `d` to `vout`, `s` to `vss`, `b` to "
            "`vss`: the input drives the gate and the drain carries the "
            "output.")

        op_label = "Operating point in the amplifying region"
        try:
            # The lesson defines no op view, so this check simulates on
            # its own.
            h = SimHierarchy.from_schematic(g['CsAmpTb']().schematic)
            Simulator(h).op()
            vout_op = float(h.vout.voltage[0])
            report.passfail(op_label,
                0.25 < vout_op < 0.95,
                hint=op_hint,
                instructions=f"V(vout) at the operating point: "
                f"{vout_op:.3f} V (expected 0.25 V ... 0.95 V). In this "
                "region the transistor is saturated and the gain is "
                "highest -- visible as the steep part of the transfer "
                "curve.")
        except Exception:
            report.passfail(op_label, False, hint=op_hint,
                instructions=sim_failure_text(device_ok, "the amplifier"))

        gain_label = "Voltage gain ≥ 5"
        try:
            hac = g['CsAmpTb']().sim_ac
            freq = [float(f) for f in hac.freq]
            mag = [abs(v) for v in hac.vout.voltage]
            gain = ac_magnitude_at(freq, mag, 1e6)
            report.passfail(gain_label, gain >= 5,
                hint=gain_hint,
                instructions=f"Measured gain at 1 MHz: {gain:.2f} "
                "(required: ≥ 5).")
        except Exception:
            report.passfail(gain_label, False, hint=gain_hint,
                instructions=sim_failure_text(device_ok, "the amplifier"))
        return report
    return lesson


# Lesson 4: Differential pair
# ---------------------------

def gen_lesson4(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            A **differential pair** amplifies the difference of two inputs.
            Both transistors share one tail current source, and the input
            difference decides how that current splits between the two
            branches. The load resistors and the tail current source are
            already in place.

            **Add the two pair transistors at the EDIT HERE marker:** `m1`
            at position `(4,7)` and `m2` at `(16,7)` with
            `.orientation=FlippedSouth` so that its gate faces the `inn`
            port, both `$w=5u` and `$l=130n`.

            `DiffPairTb` sweeps `inp` around the **0.7 V** common mode of
            `inn`. Watch the outputs cross in the `report_dc` view.
        """)
        pair_hint = (
            "`m1`: `g` to `inp`, `d` to `outp`. `m2`: `g` to `inn`, `d` "
            "to `outn`. Both share `s` on `tail` and `b` on `vss` -- the "
            "common tail is what makes it a pair.")

        def pair_ok():
            sch = g['DiffPair']().schematic
            pair = [i for i in instances_of(sch, ihp130.Nmos)
                if i.nid != sch.mtail.nid]
            if len(pair) < 2:
                return False, ("Looking for the two pair transistors "
                    "(w=5u, l=130n) besides mtail: m1 at position (4,7) "
                    "and m2 at (16,7) with orientation FlippedSouth "
                    f"(found {len(pair)} of 2).")
            sides = (
                ("inp", {'g': sch.inp, 'd': sch.outp, 's': sch.tail,
                    'b': sch.vss}, (4, 7), None),
                ("inn", {'g': sch.inn, 'd': sch.outn, 's': sch.tail,
                    'b': sch.vss}, (16, 7), FlippedSouth),
            )
            problems = []
            for side, target, pos, orientation in sides:
                inst = best_match(pair, target)
                if wrong_pins(inst, target):
                    problems.append(f"the {side} side is missing or "
                        "miswired")
                    continue
                where = misplaced(inst, *pos)
                if where:
                    problems.append(f"the {side} transistor sits {where}")
                if orientation is not None and inst.orientation != orientation:
                    problems.append(f"the {side} transistor is not "
                        "mirrored with .orientation=FlippedSouth")
            if problems:
                msg = "; ".join(problems)
                return False, msg[0].upper() + msg[1:] + "."
            return True, "Both pair transistors in place."
        structure_ok = guarded_passfail(report,
            "Pair transistors placed and wired", pair_ok, hint=pair_hint)

        sim_labels = ("Differential gain ≥ 4",
            "Outputs balanced at Vinp = 0.7 V",
            "Tail current fully steered")
        gain_hint = ("Gain needs both drains on the load resistors, `m1` "
            "on `outp` and `m2` on `outn`. A drain on the wrong net leaves "
            "one output stuck at the supply.")
        balance_hint = ("With identical transistors and identical loads on "
            "both sides, the tail current splits exactly in half when "
            "both inputs are equal -- the outputs must then be equal too.")
        steering_hint = ("Steering only works if both sources meet on the "
            "`tail` net. With a source on `vss` instead, that branch conducts "
            "on its own and the pair never hands its current over.")
        sim_hints = (gain_hint, balance_hint, steering_hint)
        try:
            h = g['DiffPairTb']().sim_dc
            vin = [float(v) for v in h.inp.voltage]
            vop = [float(v) for v in h.outp.voltage]
            von = [float(v) for v in h.outn.voltage]
            diff = [p - n for p, n in zip(vop, von)]
            mid = len(vin) // 2
            gain = max_slope(vin, diff)
            report.passfail(sim_labels[0], gain >= 4, hint=gain_hint,
                instructions=f"Maximum differential gain "
                f"d(outp-outn)/d(inp): {gain:.2f} (required: ≥ 4).")
            balance = abs(vop[mid] - von[mid])
            report.passfail(sim_labels[1], balance <= 0.02,
                hint=balance_hint,
                instructions=f"|V(outp) - V(outn)| at Vinp = 0.7 V: "
                f"{balance*1e3:.1f} mV (expected ≤ 20 mV).")
            steering = diff[0] >= 0.4 and diff[-1] <= -0.4
            report.passfail(sim_labels[2], steering, hint=steering_hint,
                instructions=f"V(outp)-V(outn) at the sweep ends: "
                f"{diff[0]:+.3f} V / {diff[-1]:+.3f} V (expected ≥ +0.4 V "
                "and ≤ -0.4 V): a few 100 mV of input difference steer "
                "the entire tail current into one branch.")
        except Exception:
            blocked_passfails(report, sim_labels, sim_hints,
                sim_failure_text(structure_ok, "the pair"))
        return report
    return lesson


# Lesson 5: Differential ring oscillator
# --------------------------------------

def gen_lesson5(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            Three differential pairs wired in a ring make an **oscillator**:
            each stage inverts, so the signal never settles and races around
            the loop.

            But only if the loop inverts an odd number of times. This ring
            latches instead -- `report_tran` shows two flat lines.

            **Find the wiring mistake at the EDIT HERE marker and fix it.**
            The first check reports the number of inversions it found, and
            its hint helps if you get stuck.
        """)
        ring_hint = (
            "Look at the `inp` and `inn` pins of the three `DiffPair` "
            "instances and follow the signal once around the loop: one "
            "stage does not take its two inputs the same way round as "
            "the others. Each stage inverts once, and a swapped input "
            "pair inverts once more -- with an even number of "
            "inversions the loop feeds back positively at DC and "
            "latches like a flip-flop.")

        def inversion_count():
            sch = g['RingOsc']().schematic
            stages = (sch.stage0, sch.stage1, sch.stage2)
            # Around the ring, each stage adds one inversion and each
            # polarity swap between stages adds another one.
            inversions = len(stages)
            for prev, cur in zip((stages[-1],) + stages[:-1], stages):
                pp, pc = pin_nets(prev), pin_nets(cur)
                if (pc.get('inp') == pp.get('outp')
                        and pc.get('inn') == pp.get('outn')):
                    pass
                elif (pc.get('inp') == pp.get('outn')
                        and pc.get('inn') == pp.get('outp')):
                    inversions += 1
                else:
                    return None
            return inversions

        def ring_inverts():
            inversions = inversion_count()
            if inversions is None:
                return False, ("The three stages do not form a closed "
                    "ring: every stage input must connect to an output "
                    "pair of the previous stage.")
            return inversions % 2 == 1, (f"Inversions around the loop: "
                f"{inversions}.")
        structure_ok = guarded_passfail(report, "Ring feedback polarity",
            ring_inverts, hint=ring_hint)

        sim_labels = ("Ring oscillates (amplitude ≥ 0.3 V)",
            "Frequency between 30 MHz and 400 MHz")
        latch_hint = (
            "Two flat lines mean the loop found a stable state and stayed "
            "there. That is what an even number of inversions does: it "
            "feeds every level back to itself.")
        freq_hint = (
            "The frequency is set by the RC delay of the 30k loads and "
            "the 100f capacitors, so a working ring lands around "
            "120 MHz. A reading of 0 MHz means it is not oscillating at "
            "all yet.")
        sim_hints = (latch_hint, freq_hint)
        try:
            h = g['RingOscTb']().sim_tran
            t = [float(x) for x in h.time]
            vop = [float(v) for v in h.outp.voltage]
            von = [float(v) for v in h.outn.voltage]
            vdiff = [p - n for p, n in zip(vop, von)]
            vpp, freq = measure_oscillation(t, vdiff)
            report.passfail(sim_labels[0], vpp >= 0.3, hint=latch_hint,
                instructions=f"Differential peak-to-peak amplitude in the "
                f"second half of the simulation: {vpp:.3f} V (required: "
                "≥ 0.3 V).")
            freq_ok = 30e6 <= freq <= 400e6
            report.passfail(sim_labels[1], freq_ok,
                hint=freq_hint,
                instructions=f"Measured oscillation frequency: "
                f"{freq/1e6:.1f} MHz.")
        except Exception:
            blocked_passfails(report, sim_labels, sim_hints,
                sim_failure_text(structure_ok, "the ring"))
        return report
    return lesson


# Lesson 6: CMOS inverter
# -----------------------

def gen_lesson6(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            The **CMOS inverter** is the simplest logic gate: a PMOS pulls
            the output high, an NMOS pulls it low.

            1. **Build the inverter** at the EDIT HERE marker: the NMOS `pd`
               at position `(3,2)` and the PMOS `pu` at `(3,8)`, both
               `$l=130n` and starting from `$w=1u`.
            2. **Size it so that the switching threshold lands at 0.6 V (±3
               %)**, half the supply, for symmetric noise margins. Equal
               widths miss it, because the PMOS carries only about half the
               NMOS current.

            The `sim_dc` view shows the transfer curve. The threshold is
            where it crosses vout = vin.
        """)
        build_hint = (
            "Both transistors take `g` to `a` and `d` to `y`. The NMOS "
            "pulls down with `s` and `b` to `vss`, the PMOS pulls up "
            "with `s` and `b` to `vdd`.")
        size_hint = (
            "Holes are less mobile than electrons: at equal width, the "
            "SG13G2 PMOS conducts roughly half the current of the NMOS, "
            "which pulls the switching threshold below 0.6 V. Make the "
            "PMOS about twice as wide as the NMOS (e.g. wn=1u, wp=2u).")

        def inverter_ok():
            sch = g['Inv']().schematic
            nmos = instances_of(sch, ihp130.Nmos)
            pmos = instances_of(sch, ihp130.Pmos)
            if not (nmos and pmos):
                status = [cls.__name__ + ': '
                    + ('found' if insts else 'missing')
                    for cls, insts in ((ihp130.Nmos, nmos),
                        (ihp130.Pmos, pmos))]
                return False, ("Transistors in the Inv schematic: "
                    + ", ".join(status) + ". Place the NMOS at position "
                    "(3,2) and the PMOS at (3,8), l=130n, start with "
                    "w=1u.")
            n_target = {'g': sch.a, 'd': sch.y, 's': sch.vss,
                'b': sch.vss}
            p_target = {'g': sch.a, 'd': sch.y, 's': sch.vdd,
                'b': sch.vdd}
            n_inst, p_inst = (best_match(nmos, n_target),
                best_match(pmos, p_target))
            n_wrong = wrong_pins(n_inst, n_target)
            p_wrong = wrong_pins(p_inst, p_target)
            status = ("NMOS pull-down: " + ("ok" if not n_wrong
                    else "pins " + ", ".join(n_wrong) + " miswired")
                + ", PMOS pull-up: " + ("ok" if not p_wrong
                    else "pins " + ", ".join(p_wrong) + " miswired")
                + ".")
            if n_wrong or p_wrong:
                return False, status
            where = [f"the NMOS sits {w}" for w in
                    [misplaced(n_inst, 3, 2)] if w]
            where += [f"the PMOS sits {w}" for w in
                    [misplaced(p_inst, 3, 8)] if w]
            if where:
                return False, ("Both transistors are wired correctly, "
                    "but " + " and ".join(where) + ".")
            return True, "Both transistors placed and wired."
        structure_ok = guarded_passfail(report,
            "Inverter transistors placed and wired", inverter_ok,
            hint=build_hint)

        sim_labels = ("Output high level (VOH ≥ 1.15 V)",
            "Output low level (VOL ≤ 0.05 V)",
            "Switching threshold at 0.6 V (±3 %)")
        voh_hint = ("Only the PMOS can pull `y` up to the supply. If `y` "
            "stays low, its source and bulk are not on `vdd`.")
        vol_hint = ("Only the NMOS pulls `y` down to ground. If `y` never "
            "reaches 0 V, its source and bulk are not on `vss`.")
        sim_hints = (voh_hint, vol_hint, size_hint)
        try:
            h = g['InvTb']().sim_dc
            vin = [float(v) for v in h.a.voltage]
            vout = [float(v) for v in h.y.voltage]
            report.passfail(sim_labels[0], vout[0] >= 1.15, hint=voh_hint,
                instructions=f"V(y) at vin = 0: {vout[0]:.3f} V. The PMOS "
                "must pull the output all the way to VDD.")
            report.passfail(sim_labels[1], vout[-1] <= 0.05, hint=vol_hint,
                instructions=f"V(y) at vin = 1.2 V: {vout[-1]:.3f} V. The "
                "NMOS must pull the output all the way to ground.")
            vth = vtc_threshold(vin, vout)
            if vth is None:
                report.passfail(sim_labels[2], False,
                    hint="The curve has to fall from the supply to "
                    "ground for a threshold to exist. As long as only "
                    "one of the two transistors drives y, it never "
                    "crosses vout = vin.",
                    instructions="The VTC never crosses vout = vin -- the "
                    "inverter is probably still incomplete.")
            else:
                report.passfail(sim_labels[2],
                    0.59 <= vth <= 0.635,
                    hint=size_hint,
                    instructions=f"Measured switching threshold: "
                    f"{vth:.3f} V (target: 0.59 V ... 0.635 V).")
        except Exception:
            blocked_passfails(report, sim_labels, sim_hints,
                sim_failure_text(structure_ok, "the inverter"))
        return report
    return lesson


# Lesson 7: Self-biased inverter
# ------------------------------

def gen_lesson7(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            At its switching threshold, an inverter is an **analog
            amplifier**: both transistors are saturated and their $g_m$ adds
            up. A feedback resistor from output to input forces v(a) = v(y)
            and keeps the inverter biased exactly there, while a capacitor
            couples the AC signal in.

            **Add the feedback resistor `rf` at the EDIT HERE marker, at
            position `(11,8)` between the inverter input and output, and
            size it so that the gain reaches 10.**

            Too small a resistance biases the inverter fine but ties the
            output straight back to the input, so nothing gets amplified.

            The `report_ac` view shows the self-bias point and the gain over
            frequency.
        """)
        place_hint = ("`p` to `a` and `n` to `y`, so that the resistor "
            "bridges the inverter from its output back to its input. A "
            "resistor is symmetric, so the two pins may also go the "
            "other way round.")
        op_hint = ("The feedback resistor connects the inverter input "
            "and output. Without it, the input node floats.")
        gain_hint = (
            "A small `rf` ties the output straight back to the input, so "
            "the amplifier ends up following its own output and the gain "
            "drops towards 1. Make `rf` large compared to the impedance at "
            "the input node, then the signal only sees the gates.")

        def rf_placed():
            sch = g['InvAmp']().schematic
            resistors = instances_of(sch, Res)
            if not resistors:
                return False, ("Looking for a Res instance between the "
                    "inverter input and output, at position (11,8).")
            # A resistor is symmetric, so either pin may face the input.
            for inst in resistors:
                if {c.here for c in inst.conns()} == {sch.a, sch.y}:
                    where = misplaced(inst, 11, 8)
                    if where:
                        return False, ("The resistor is wired correctly, "
                            f"but it sits {where}.")
                    return True, "Feedback resistor placed and wired."
            return False, ("A resistor is placed, but it does not bridge "
                "the inverter input and output.")
        structure_ok = guarded_passfail(report,
            "Feedback resistor placed and wired", rf_placed,
            hint=place_hint)

        sim_labels = ("Self-biased at the switching threshold",
            "Mid-band gain ≥ 10")
        if not structure_ok:
            blocked_passfails(report, sim_labels, (op_hint, gain_hint),
                "The amplifier is simulated once the feedback resistor "
                "bridges input and output.")
            return report

        op_label = sim_labels[0]
        try:
            h = g['InvAmpTb']().sim_op
            va = float(h.ain.voltage[0])
            vy = float(h.yout.voltage[0])
            report.passfail(op_label,
                abs(va - vy) <= 0.02 and 0.4 <= vy <= 0.8,
                hint=op_hint,
                instructions=f"Operating point: v(a) = {va:.3f} V, "
                f"v(y) = {vy:.3f} V (expected: equal within 20 mV, "
                "between 0.4 V and 0.8 V).")
        except Exception:
            report.passfail(op_label, False, hint=op_hint,
                instructions=sim_failure_text(structure_ok,
                    "the feedback path"))

        gain_label = sim_labels[1]
        try:
            hac = g['InvAmpTb']().sim_ac
            freq = [float(f) for f in hac.freq]
            mag = [abs(v) for v in hac.yout.voltage]
            gain = ac_magnitude_at(freq, mag, 5e6)
            report.passfail(gain_label, gain >= 10,
                hint=gain_hint,
                instructions=f"Measured gain at 5 MHz: {gain:.2f} "
                "(required: ≥ 10). The gain rolls off below the "
                "highpass corner set by the coupling capacitor and "
                "above the lowpass corner set by the load.")
        except Exception:
            report.passfail(gain_label, False,
                hint=gain_hint,
                instructions=sim_failure_text(structure_ok,
                    "the feedback path"))
        return report
    return lesson


# Lesson 8: NAND2 gate
# --------------------

def gen_lesson8(g):
    dut = g['Nand2']

    class CheckNand2Tb(Cell):
        """Operating-point testbench applying static input levels."""
        a = Parameter(R)
        b = Parameter(R)

        @viewgen_noctx
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
                Vdc(dc=R('1.2')).symbol.portmap(n=s.vss, p=s.vdd),
                pos=Vec2R(0, 6))
            s.va_src = SchemInstance(
                Vdc(dc=self.a).symbol.portmap(n=s.vss, p=s.a), pos=Vec2R(6, 6))
            s.vb_src = SchemInstance(
                Vdc(dc=self.b).symbol.portmap(n=s.vss, p=s.b), pos=Vec2R(12, 6))
            s.dut = SchemInstance(dut().symbol.portmap(
                vdd=s.vdd, vss=s.vss, a=s.a, b=s.b, y=s.y), pos=Vec2R(18, 6))
            s.auto_wire()
            s.check(add_conn_points=True, add_terminal_taps=True)
            return s

    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            **`Nand2`** already has the right symbol, but its schematic is
            still the inverter from lesson 6, driven by `a` alone.

            **Extend it at the EDIT HERE marker so that `y = !(a & b)`.**

            The output may only go low when both inputs are high, so the two
            NMOS transistors go in series, which needs a new net (`net n`)
            between them. The two PMOS transistors go in parallel between
            `vdd` and `y`. Add the new transistors to the `for` loop so that
            they get sized as well.

            Each check applies one input combination and simulates the
            operating point.
        """)
        nand_hint = (
            "Lower NMOS: `s` to `vss`, `d` to the new net. Upper NMOS "
            "at (4,7): `s` to that net, `d` to `y`, with one input per "
            "gate. The second PMOS goes next to the first at (12,13) "
            "with `s` to `vdd`, `d` to `y`, `g` to `b`. Transistors "
            "left out of the sizing loop keep the library default "
            "l=1u.")

        def structure():
            sch = dut().schematic
            nmos = instances_of(sch, ihp130.Nmos)
            pmos = instances_of(sch, ihp130.Pmos)
            supply_nets = (sch.y, sch.vss, sch.vdd, sch.a, sch.b)
            # Kept so that the position check can name the two NMOS by
            # their role in the stack rather than by instance name.
            series_pair = None
            for top in nmos:
                for bottom in nmos:
                    if top.nid == bottom.nid:
                        continue
                    pt, pb = pin_nets(top), pin_nets(bottom)
                    x = pt.get('s')
                    if (pt.get('d') == sch.y and x is not None
                            and x not in supply_nets
                            and pb.get('d') == x
                            and pb.get('s') == sch.vss
                            and {pt.get('g'), pb.get('g')}
                                == {sch.a, sch.b}):
                        series_pair = (top, bottom)
            series = series_pair is not None
            parallel = (len(pmos) >= 2
                and all(pin_nets(t).get('s') == sch.vdd
                    and pin_nets(t).get('d') == sch.y for t in pmos)
                and {pin_nets(t).get('g') for t in pmos}
                    == {sch.a, sch.b})
            if series and parallel:
                top, bottom = series_pair
                by_gate = {pin_nets(t).get('g'): t for t in pmos}
                where = [f"the {role} sits {w}" for role, w in (
                    ("lower NMOS", misplaced(bottom, 4, 1)),
                    ("upper NMOS", misplaced(top, 4, 7)),
                    ("PMOS on a", misplaced(by_gate[sch.a], 4, 13)),
                    ("PMOS on b", misplaced(by_gate[sch.b], 12, 13)),
                ) if w]
                if where:
                    return False, ("The gate is wired correctly, but "
                        + ", ".join(where) + ".")
                return True, "Series NMOS stack and parallel PMOS in place."
            status = (f"{len(nmos)} NMOS and {len(pmos)} PMOS found "
                "(2 of each needed). Series NMOS stack y-n-vss: "
                f"{'ok' if series else 'missing'}, parallel PMOS "
                f"pull-up: {'ok' if parallel else 'missing'}.")
            return False, status
        structure_ok = guarded_passfail(report,
            "NMOS in series, PMOS in parallel", structure, hint=nand_hint)

        pullup_hint = ("`y` must be pulled high here, which is the job of "
            "the PMOS pair: each PMOS on its own reaches from `vdd` to `y`, "
            "one with `a` on its gate and one with `b`.")
        pulldown_hint = ("`y` must be pulled low here, which only the NMOS "
            "stack can do: from `vss` through the lower device to the "
            "internal net, and from there through the upper one to `y`, "
            "with one input per gate.")
        for a, b in ((0, 0), (0, 1), (1, 0), (1, 1)):
            expect_high = not (a and b)
            row_hint = pullup_hint if expect_high else pulldown_hint
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
                report.passfail(label, passed, hint=row_hint,
                    instructions=f"Simulated y = {y:.3f} V, expected "
                    f"{'> 1.08' if expect_high else '< 0.12'} V.")
            except Exception:
                report.passfail(label, False, hint=row_hint,
                    instructions=sim_failure_text(structure_ok, "the gate"))
        return report
    return lesson


# Lesson 9: Standard cells
# ------------------------

def gen_lesson9(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            Digital chips are usually not drawn transistor by transistor.
            They are assembled from **standard cells**: pre-designed,
            pre-verified gates, all on a common height grid so that
            place-and-route tools can tile them into rows. This lesson uses
            one straight from the PDK.

            **Instantiate the XOR2 cell as `dut` at position `(18,12)` and
            connect it to the testbench.**

            The cell is already loaded from the library and bound to the
            name `Xor2`, so it is instantiated like any other cell. Its pins
            are named by the library, not by you, and they are upper case.
            Open the `Xor2` symbol to look them up -- and note that this
            cell calls its output `X`, while most other SG13G2 cells call it
            `Y`.

            ### Layout tour

            The second result panel shows the layout of the real
            `sg13g2_xor2_1` cell, loaded from the PDK via
            [ExtLibrary](docs:ref/extlibrary.html). Things to spot: the
            `vdd` and `vss` rails at top and bottom, shared with the
            neighboring rows, the N-well covering the upper half where the
            PMOS transistors sit, and the vertical polysilicon gate stripes.
            An XOR needs far more transistors than the gates of the previous
            lessons, which is why the cell is so much wider. Layout design
            is the topic of the layout course!
        """)
        dut_hint = (
            "Each pin goes to the testbench net of the same name, and "
            "`VDD` and `VSS` must be connected too -- in a real chip the "
            "rails do that automatically when the cells are tiled into a "
            "row.")

        def dut_wired():
            sch = g['Xor2Tb']().schematic
            insts = [i for i in sch.all(SchemInstance)
                if i.symbol.cell == g['Xor2']]
            if not insts:
                return False, ("Looking for an instance of the "
                    "sg13g2_xor2_1 cell at position (18,12).")
            target = {'A': sch.a, 'B': sch.b, 'X': sch.y,
                'VDD': sch.vdd, 'VSS': sch.vss}
            inst = best_match(insts, target)
            wrong = wrong_pins(inst, target)
            if wrong:
                return False, ("Cell instantiated, but these pins are "
                    "not connected as the testbench needs them: "
                    + ", ".join(wrong) + ".")
            where = misplaced(inst, 18, 12)
            if where:
                return False, ("The cell is wired correctly, but it "
                    f"sits {where}.")
            return True, "Cell instantiated and wired."

        wired = guarded_passfail(report, "XOR2 cell instantiated and wired",
            dut_wired, hint=dut_hint)

        row_hint = ("If the output never moves, check the name of the "
            "output pin: this cell calls it `X`, not `Y`. If the levels are "
            "there but wrong, the two inputs are swapped.")
        for a, b in ((0, 0), (0, 1), (1, 0), (1, 1)):
            expect_high = bool(a) != bool(b)
            label = f"a={a}, b={b} => y={int(expect_high)}"
            if not wired:
                report.passfail(label, False, hint=row_hint,
                    instructions="The truth table is checked once the "
                    "cell is instantiated and wired.")
                continue
            try:
                h = g['Xor2Tb'](a=a * R('1.2'), b=b * R('1.2')).sim_op
                y = float(h.y.voltage[0])
                passed = y > 0.9 * 1.2 if expect_high else y < 0.1 * 1.2
                report.passfail(label, passed, hint=row_hint,
                    instructions=f"Simulated y = {y:.3f} V, expected "
                    f"{'> 1.08' if expect_high else '< 0.12'} V.")
            except Exception:
                report.passfail(label, False, hint=row_hint,
                    instructions=exception_text())
        return report
    return lesson


# Lesson 10: LFSR from standard cells
# -----------------------------------

TCLK = 2e-9  #: clock period of the LFSR testbench in lesson 10


def lfsr_states(sim, bits=4, cycles=24):
    """
    Digitizes the register state of the lesson-10 LFSR once per clock
    cycle, sampled shortly before each rising clock edge where the
    flip-flop outputs have settled. Returns the list of states, each a
    tuple of bits.
    """
    t = [float(x) for x in sim.time]
    q = [[float(v) for v in getattr(sim, f'q{i}').voltage]
        for i in range(bits)]
    states = []
    for k in range(2, cycles):
        target = k * TCLK - 0.1 * TCLK
        idx = min(range(len(t)), key=lambda j: abs(t[j] - target))
        states.append(tuple(1 if q[i][idx] > 0.6 else 0 for i in range(bits)))
    return states


def gen_lesson10(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            Time to build something out of standard cells. Four flip flops
            are already chained into a shift register, clocked and reset by
            the two sources on the left. The input of the first flip flop is
            tied to a constant zero, so after the reset the register just
            sits there.

            Feed the outputs of the last flip flops back into the first one
            through a gate and the register turns into a **linear feedback
            shift register**: it walks through a long, scrambled sequence of
            states that looks random but repeats exactly. Real chips use
            them to generate test patterns and to scramble data.

            **Replace the tie cell at the EDIT HERE marker by a feedback
            gate at the same position `(64,14)`, so that the four bits run
            through all 15 states before repeating.**

            Two things to work out: which gate, `Xor2` or `Xnor2`, and which
            two flip flop outputs to tap. Remember that the reset leaves
            every flip flop at zero. Watch the bits in the `report_tran`
            view and the measured sequence length in the checks below.
        """)
        place_hint = (
            "`A` and `B` come from flip flop outputs, the output pin "
            "drives `fb` (the D input of the first flip flop), and "
            "`VDD` and `VSS` go to the supply nets.")
        gate_hint = (
            "After the reset all four bits are zero. An XOR of two zeros "
            "feeds another zero back, so the register would stay at 0000 "
            "forever. The XNOR feeds a one back and starts the "
            "sequence.")
        tap_hint = (
            "Only two tap pairs walk through all 15 states, and both of "
            "them use the last flip flop `q3` together with one other "
            "output. Try `q3` with `q2`, or `q3` with `q0`. Without "
            "the last flip flop in the loop, the bits behind the tap "
            "only delay the sequence instead of shaping it.")

        def feedback_gate():
            sch = g['Lfsr']().schematic
            gates = [i for i in sch.all(SchemInstance)
                if i.symbol.cell in (g['Xor2'], g['Xnor2'])]
            if not gates:
                return False, ("Looking for an Xor2 or Xnor2 instance "
                    "that drives fb, the D input of the first flip "
                    "flop.")
            outs = {'X', 'Y'}
            qnets = {getattr(sch, f'q{i}') for i in range(4)}
            for inst in gates:
                conns = pin_nets(inst)
                drives = any(conns.get(p) == sch.fb for p in outs)
                taps = [conns.get('A'), conns.get('B')]
                if drives and all(t in qnets for t in taps):
                    where = misplaced(inst, 64, 14)
                    if where:
                        return False, ("The feedback gate is wired "
                            f"correctly, but it sits {where}.")
                    return True, "Feedback gate in place."
            return False, ("A gate is placed, but its output must drive "
                "fb and both its inputs must come from flip flop "
                "outputs (q0 ... q3).")

        wired = guarded_passfail(report, "Feedback gate closes the loop",
            feedback_gate, hint=place_hint)

        run_labels = ("Register does not stand still",
            "Sequence runs through all 15 states")
        run_hints = (gate_hint, tap_hint)
        if not wired:
            blocked_passfails(report, run_labels, run_hints,
                "The sequence is measured once the feedback gate is in "
                "place.")
            return report
        try:
            states = lfsr_states(g['Lfsr']().sim_tran)
            distinct = len(set(states))
            first = states[0]
            period = next((i for i, s in enumerate(states[1:], 1)
                if s == first), None)
            shown = " ".join("".join(str(b) for b in s)
                for s in states[:8])
            report.passfail(run_labels[0], distinct > 1, hint=gate_hint,
                instructions=f"States seen after the reset: {shown} ... "
                f"({distinct} different ones).")
            report.passfail(run_labels[1],
                distinct == 15 and period == 15, hint=tap_hint,
                instructions=f"The register visits {distinct} different "
                "states and repeats after "
                + (f"{period} clock cycles" if period else
                    "more than the simulated time")
                + " (15 of each is what a maximal-length LFSR does).")
        except Exception:
            blocked_passfails(report, run_labels, run_hints,
                exception_text())
        return report
    return lesson


# Lesson 11: 5-transistor OTA (bonus)
# -----------------------------------

def gen_lesson11(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            The capstone is a **5-transistor OTA**: it combines the current
            mirror of lesson 2 with the differential pair of lesson 4, which
            is exactly the circuit you start from here. A PMOS mirror in
            place of the resistor loads folds the signal current of one
            branch onto the other, which doubles the gain, and it lets the
            output swing almost from rail to rail.

            **Replace the resistor loads by a PMOS current mirror at the
            EDIT HERE marker and size the amplifier to meet all four
            specs:**

            | Spec | Requirement |
            |---|---|
            | DC gain | ≥ 12 (21.6 dB) |
            | Bandwidth | ≥ 2.5 MHz |
            | Supply current | ≤ 50 µA |
            | Output swing | ≥ 0.8 V |

            The specs pull against each other, which is what makes this a
            design task. The hints of the failing checks point at the
            topology and at the sizing knobs.

            The gain is the steepest slope of the DC transfer curve in the
            `report_dc` view.
        """)
        ota_hint = (
            "Replace `rl_p` and `rl_n` by two PMOS, both w=5u. `m3` at "
            "(8,14) is diode-connected: `g` and `d` both to `outx`, "
            "mirrored with FlippedSouth so that it faces `m4`. `m4` at "
            "(12,14): `g` to `outx`, `d` to `out`. Both take `s` and "
            "`b` to `vdd`. `m3` carries the current of one branch and "
            "`m4` copies it onto the other.")

        def mirror_load():
            sch = g['Ota']().schematic
            resistors = len(instances_of(sch, Res))
            pmos = instances_of(sch, ihp130.Pmos)
            mirror = False
            problems = []
            for diode in pmos:
                for outdev in pmos:
                    if diode.nid == outdev.nid:
                        continue
                    pd, po = pin_nets(diode), pin_nets(outdev)
                    gate = pd.get('g')
                    if (gate is not None and pd.get('d') == gate
                            and pd.get('s') == sch.vdd
                            and po.get('g') == gate
                            and po.get('d') == sch.out
                            and po.get('s') == sch.vdd):
                        mirror = True
                        problems = [f"the diode transistor sits {t}"
                            for t in [misplaced(diode, 8, 14)] if t]
                        problems += [f"the output transistor sits {t}"
                            for t in [misplaced(outdev, 12, 14)] if t]
                        if diode.orientation != FlippedSouth:
                            problems.append("the diode transistor is not "
                                "mirrored with .orientation=FlippedSouth")
            if mirror and resistors == 0 and problems:
                return False, ("The mirror is wired correctly, but "
                    + ", ".join(problems) + ".")
            status = (f"Resistors left: {resistors} (0 needed), PMOS "
                f"mirror (diode + output device): "
                f"{'ok' if mirror else 'missing'}.")
            return resistors == 0 and mirror, status
        structure_ok = guarded_passfail(report,
            "Resistor loads replaced by a PMOS mirror", mirror_load,
            hint=ota_hint)

        dc_labels = ("DC gain ≥ 12", "Output swing ≥ 0.8 V")
        gain_hint = ("Gain comes from the intrinsic gain of the devices, "
            "which grows with channel length, and the PMOS mirror "
            "dominates it. At 130n the OTA only reaches about 8, but a "
            "very long channel costs bandwidth -- l=300n on `m1` to `m4` "
            "meets both specs.")
        swing_hint = ("The output can only approach the rails once both "
            "resistors are gone. A resistor left in a branch drops its "
            "share of the supply no matter what the transistors do.")
        dc_hints = (gain_hint, swing_hint)
        try:
            h = g['OtaTb']().sim_dc
            vin = [float(v) for v in h.inp.voltage]
            vout = [float(v) for v in h.out.voltage]
            gain = max_slope(vin, vout)
            report.passfail(dc_labels[0], gain >= 12, hint=gain_hint,
                instructions=f"Maximum slope of the transfer curve: "
                f"{gain:.2f} ({20*math.log10(max(gain, 1e-9)):.1f} dB), "
                "required: ≥ 12 (21.6 dB).")
            swing = max(vout) - min(vout)
            report.passfail(dc_labels[1], swing >= 0.8, hint=swing_hint,
                instructions=f"Output range over the sweep: {swing:.3f} V "
                "(required: ≥ 0.8 V).")
        except Exception:
            blocked_passfails(report, dc_labels, dc_hints,
                sim_failure_text(structure_ok, "the load replacement"))

        isup_label = "Supply current ≤ 50 µA"
        isup_hint = ("The supply current is essentially the tail current "
            "set by `mtail` and the bias voltage. If you widened `mtail` "
            "or shortened its channel, the current went up.")
        try:
            hop = g['OtaTb']().sim_op
            isup = abs(float(hop.vdd_src.p.current[0]))
            report.passfail(isup_label, isup <= 50e-6,
                hint=isup_hint,
                instructions=f"Current drawn from the 1.2 V supply at the "
                f"balance point: {isup*1e6:.1f} µA (allowed: ≤ 50 µA).")
        except Exception:
            report.passfail(isup_label, False, hint=isup_hint,
                instructions=sim_failure_text(structure_ok,
                    "the load replacement"))

        bw_label = "Bandwidth ≥ 2.5 MHz"
        bw_hint = ("Bandwidth pulls against gain: a longer channel raises "
            "the intrinsic gain but also adds capacitance, which moves "
            "the output pole down. Stretching the devices until the gain "
            "is comfortable therefore costs the bandwidth spec.")
        try:
            hac = g['OtaTb']().sim_ac
            freq = [float(f) for f in hac.freq]
            mag = [abs(v) for v in hac.out.voltage]
            bw = bandwidth_3db(freq, mag)
            report.passfail(bw_label, bw >= 2.5e6, hint=bw_hint,
                instructions=f"-3 dB bandwidth: {bw/1e6:.2f} MHz "
                "(required: ≥ 2.5 MHz).")
        except Exception:
            report.passfail(bw_label, False, hint=bw_hint,
                instructions=sim_failure_text(structure_ok,
                    "the load replacement"))
        return report
    return lesson
