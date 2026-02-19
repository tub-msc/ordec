# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
import math
from ordec.schematic.netlister import Netlister
from ordec import Rational as R
from .lib import sim as lib_test
from ordec.core import *

def assert_simcolumn(col, expected, tol=0.01):
    """Assert that a SimColumn matches expected values within relative tolerance.

    Args:
        col: SimColumn to check.
        expected: List of expected float values.
        tol: Maximum allowed relative error (default 1%).
    """
    assert len(col) == len(expected), f"length mismatch: {len(col)} != {len(expected)}"
    for i, (got, exp) in enumerate(zip(col, expected)):
        if exp == 0:
            assert got == 0, f"[{i}] expected 0, got {got:.3e}"
        else:
            rel = abs((got - exp) / exp)
            assert rel <= tol, (
                f"[{i}] {got:.3e} differs from {exp:.3e} by {rel:.1%} (tol {tol:.1%})"
            )


def plot_trans(time_s, traces, outfile, time_scale=1e6, time_unit="us"):
    """Plot transient traces.

    Args:
        time_s: Iterable of time values in seconds.
        traces: Dict of trace name -> iterable values.
        outfile: Output image path.
        time_scale: Multiplier for time axis (default: to microseconds).
        time_unit: Label for time axis unit.
    """
    import numpy as np
    import matplotlib.pyplot as plt

    t = np.array(time_s) * time_scale
    fig, ax = plt.subplots(figsize=(8, 4))
    for name, values in traces.items():
        ax.plot(t, np.array(values), label=name)
    ax.set_xlabel(f"Time ({time_unit})")
    ax.set_ylabel("Value")
    ax.legend()
    ax.grid(True)
    fig.tight_layout()
    fig.savefig(outfile)
    plt.close(fig)


def plot_bode(freq_hz, response, outfile):
    """Plot Bode magnitude/phase from complex frequency response."""
    import numpy as np
    import matplotlib.pyplot as plt

    f = np.array(freq_hz)
    h = np.array(list(response))
    mag_db = 20 * np.log10(np.abs(h))
    phase_deg = np.degrees(np.angle(h))

    fig, (ax_mag, ax_phase) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
    ax_mag.semilogx(f, mag_db)
    ax_mag.set_ylabel("Magnitude (dB)")
    ax_mag.grid(True)
    ax_phase.semilogx(f, phase_deg)
    ax_phase.set_xlabel("Frequency (Hz)")
    ax_phase.set_ylabel("Phase (deg)")
    ax_phase.grid(True)
    fig.tight_layout()
    fig.savefig(outfile)
    plt.close(fig)


def test_sim_dc_flat():
    h = lib_test.ResdivFlatTb().sim_dc
    assert h.a.dc_voltage == 0.33333333333333337
    assert h.b.dc_voltage == 0.6666666666666667

def test_sim_dc_hier():
    h = lib_test.ResdivHierTb().sim_dc
    assert h.r.dc_voltage == pytest.approx(0.3589743589743596, abs=1e-10)
    assert h.I0.I1.m.dc_voltage == pytest.approx(0.5897435897435901, abs=1e-10)

def test_generic_mos_netlister():
    nl = Netlister(Directory())
    nl.netlist_hier(lib_test.NmosSourceFollowerTb(vin=R(2)).schematic)
    netlist = nl.out()

    assert netlist.count('.model nmosgeneric NMOS level=1') == 1
    assert netlist.count('.model pmosgeneric PMOS level=1') == 1

def test_generic_mos_nmos_sourcefollower():
    assert lib_test.NmosSourceFollowerTb(vin=R(2)).sim_dc.o.dc_voltage == 0.6837722116612965
    assert lib_test.NmosSourceFollowerTb(vin=R(3)).sim_dc.o.dc_voltage == 1.6837721784225057

def test_generic_mos_inv():
    assert lib_test.InvTb(vin=R(0)).sim_dc.o.dc_voltage == 4.9999999698343345
    assert lib_test.InvTb(vin=R('2.5')).sim_dc.o.dc_voltage == 2.500000017115547
    assert lib_test.InvTb(vin=R(5)).sim_dc.o.dc_voltage == 3.131249965532494e-08

def test_sky_mos_inv():
    assert lib_test.InvSkyTb(vin=R(0)).sim_dc.o.dc_voltage == pytest.approx(4.999999973187308, abs=1e-10)
    assert lib_test.InvSkyTb(vin=R('2.5')).sim_dc.o.dc_voltage == pytest.approx(1.9806063550640076, abs=1e-10)
    assert lib_test.InvSkyTb(vin=R(5)).sim_dc.o.dc_voltage == pytest.approx(0.00012158997833462999, abs=1e-10)

def test_ihp_mos_inv_vin0():
    h_0 = lib_test.InvIhpTb(vin=R(0)).sim_dc
    assert h_0.o.dc_voltage == pytest.approx(4.999573)

def test_ihp_mos_inv_vin5():
    h_5 = lib_test.InvIhpTb(vin=R(5)).sim_dc
    assert h_5.o.dc_voltage == pytest.approx(0.00024556, abs=1e-5)

def test_sim_pulsedrc_tran():
    tb = lib_test.PulsedRC()
    h = tb.sim_tran
    src = tb.schematic.vsrc.symbol.cell

    expected_inp = [expected_pulse_value(t, src) for t in h.time]
    for got, exp in zip(h.inp.trans_voltage, expected_inp):
        assert got == pytest.approx(exp, abs=1e-6)

    # Simple discrete RC update (backward Euler) on sampled Vin.
    tau = float(tb.schematic.res.symbol.cell.r) * float(tb.schematic.cap.symbol.cell.c)

    expected_out = [float(h.out.trans_voltage[0])]
    for i in range(1, len(h.time)):
        dt = float(h.time[i] - h.time[i - 1])
        alpha = dt / tau
        vin = expected_pulse_value(float(h.time[i]), src)
        y_prev = expected_out[-1]
        expected_out.append((y_prev + alpha * vin) / (1.0 + alpha))

    for got, exp in zip(h.out.trans_voltage, expected_out):
        assert got == pytest.approx(exp, abs=0.07)

    plot_enable = False
    if plot_enable:
        plot_trans(h.time, {
                "inp": h.inp.trans_voltage,
                "out": h.out.trans_voltage,
                "out_expected": expected_out,
            }, "pulsedrc_tran.svg")

def expected_pwl_value(t):
    points = [(float(tp), float(vp)) for tp, vp in lib_test.SourceTb.demo_pwl_points]
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for i in range(len(points) - 1):
        t0, v0 = points[i]
        t1, v1 = points[i + 1]
        if t0 <= t <= t1:
            if t1 == t0:
                return v1
            alpha = (t - t0) / (t1 - t0)
            return v0 + alpha * (v1 - v0)
    return points[-1][1]


def expected_pulse_value(t, src):
    initial_value = float(src.initial_value)
    pulsed_value = float(src.pulsed_value)
    delay_time = float(src.delay_time)
    rise_time = float(src.rise_time)
    fall_time = float(src.fall_time)
    pulse_width = float(src.pulse_width)
    period = float(src.period)

    if t < delay_time:
        return initial_value

    tau = (t - delay_time) % period

    if rise_time > 0 and tau < rise_time:
        alpha = tau / rise_time
        return initial_value + alpha * (pulsed_value - initial_value)

    if tau < rise_time + pulse_width:
        return pulsed_value

    if fall_time > 0 and tau < rise_time + pulse_width + fall_time:
        alpha = (tau - rise_time - pulse_width) / fall_time
        return pulsed_value + alpha * (initial_value - pulsed_value)

    return initial_value


def expected_sin_value(t, src):
    offset = float(src.offset)
    amplitude = float(src.amplitude)
    frequency = float(src.frequency)
    delay = float(src.delay)
    damping_factor = float(src.damping_factor)

    if t < delay:
        return offset
    td = t - delay
    return offset + amplitude * math.sin(2 * math.pi * frequency * td) * math.exp(-damping_factor * td)


def test_sim_vpwltb_tran():
    tb = lib_test.VpwlTb()
    h = tb.sim_tran

    for t, out_v in zip(h.time, h.out.trans_voltage):
        assert out_v == pytest.approx(expected_pwl_value(t), abs=1e-6)


def test_sim_ipwltb_tran():
    tb = lib_test.IpwlTb()
    h = tb.sim_tran

    for t, res_i in zip(h.time, h.res.trans_current):
        assert res_i == pytest.approx(expected_pwl_value(t), abs=1e-8)


def test_sim_vpulsetb_tran():
    tb = lib_test.VpulseTb()
    h = tb.sim_tran
    src = tb.schematic.vsrc.symbol.cell

    for t, out_v in zip(h.time, h.out.trans_voltage):
        expected = expected_pulse_value(t, src)
        assert out_v == pytest.approx(expected, abs=1e-6)


def test_sim_ipulsetb_tran():
    tb = lib_test.IpulseTb()
    h = tb.sim_tran
    src = tb.schematic.isrc.symbol.cell

    for t, res_i in zip(h.time, h.res.trans_current):
        expected = expected_pulse_value(t, src)
        assert res_i == pytest.approx(expected, abs=1e-8)


def test_sim_vsintb_tran():
    tb = lib_test.VsinTb()
    h = tb.sim_tran
    src = tb.schematic.vsrc.symbol.cell

    for t, out_v in zip(h.time, h.out.trans_voltage):
        expected = expected_sin_value(t, src)
        assert out_v == pytest.approx(expected, abs=1e-6)


def test_sim_isintb_tran():
    tb = lib_test.IsinTb()
    h = tb.sim_tran
    src = tb.schematic.isrc.symbol.cell

    for t, res_i in zip(h.time, h.res.trans_current):
        expected = expected_sin_value(t, src)
        assert res_i == pytest.approx(expected, abs=1e-8)


def test_sim_sinerc_ac():
    tb = lib_test.SineRC()
    h = tb.sim_ac
    r = float(tb.schematic.res.symbol.cell.r)
    c = float(tb.schematic.cap.symbol.cell.c)
    expected = [1.0 / (1.0 + 1j * 2.0 * math.pi * f * r * c) for f in h.freq]
    assert_simcolumn(h.out.ac_voltage, expected, tol=0.02)

    plot_enable = False
    if plot_enable:
        plot_bode(h.freq, h.out.ac_voltage, "sinerc_ac.svg")


def test_webdata():
    # Test DC webdata
    h_dc = lib_test.ResdivFlatTb().sim_dc
    sim_type, data = h_dc.webdata()
    assert sim_type == 'dcsim'
    assert 'dc_voltages' in data
    assert 'dc_currents' in data

    # Test transient webdata
    sim_type, data = lib_test.PulsedRC().sim_tran.webdata()
    assert sim_type == 'transim'
    assert 'time' in data
    assert 'voltages' in data
    assert 'currents' in data
