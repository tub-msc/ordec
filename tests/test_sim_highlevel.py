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

def test_sim_tran_flat():
    h = lib_test.ResdivFlatTb().sim_tran(R('0.1u'), R('1u'))
    assert len(h.time) > 0
    assert h.a.trans_voltage[-1] == pytest.approx(0.3333333, abs=1e-6)
    assert h.b.trans_voltage[-1] == pytest.approx(0.6666667, abs=1e-6)


def test_sim_pulsedrc_tran():
    h = lib_test.PulsedRC().sim_tran

    # Reference data generated using h.inp.trans_voltage.dump() and h.out.trans_voltage.dump().
    assert_simcolumn(h.inp.trans_voltage, [0.000e+00, 2.500e-03, 2.710e-03, 3.131e-03, 3.972e-03, 5.655e-03, 9.021e-03, 1.575e-02, 2.921e-02, 5.614e-02, 1.100e-01, 2.177e-01, 4.331e-01, 8.639e-01, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 9.500e-01, 8.500e-01, 6.500e-01, 2.500e-01, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 5.000e-02, 1.500e-01, 3.500e-01, 7.500e-01, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 9.500e-01, 8.500e-01, 6.500e-01, 2.500e-01, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 5.000e-02, 1.500e-01, 3.500e-01, 7.500e-01, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 9.500e-01, 8.500e-01, 6.500e-01, 2.500e-01, 1.332e-15, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 5.000e-02, 1.500e-01, 3.500e-01, 7.500e-01, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 9.500e-01, 8.500e-01, 6.500e-01, 2.500e-01, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 5.000e-02, 1.500e-01, 3.500e-01, 7.500e-01, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 1.000e+00, 9.500e-01, 8.500e-01, 6.500e-01, 2.500e-01, 1.332e-15, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00, 0.000e+00])
    assert_simcolumn(h.out.trans_voltage, [0.000e+00, 6.234e-06, 6.803e-06, 8.029e-06, 1.101e-05, 1.908e-05, 4.368e-05, 1.265e-04, 4.254e-04, 1.548e-03, 5.822e-03, 2.197e-02, 8.097e-02, 2.821e-01, 3.649e-01, 3.952e-01, 4.528e-01, 5.523e-01, 7.015e-01, 8.209e-01, 8.607e-01, 8.650e-01, 8.683e-01, 8.468e-01, 7.145e-01, 5.835e-01, 5.557e-01, 5.028e-01, 4.114e-01, 2.743e-01, 1.646e-01, 1.280e-01, 1.243e-01, 1.220e-01, 1.452e-01, 2.802e-01, 4.123e-01, 4.403e-01, 4.936e-01, 5.857e-01, 7.238e-01, 8.343e-01, 8.711e-01, 8.749e-01, 8.773e-01, 8.541e-01, 7.194e-01, 5.873e-01, 5.594e-01, 5.061e-01, 4.141e-01, 2.760e-01, 1.656e-01, 1.288e-01, 1.251e-01, 1.227e-01, 1.458e-01, 2.806e-01, 4.127e-01, 4.406e-01, 4.939e-01, 5.859e-01, 7.239e-01, 8.344e-01, 8.712e-01, 8.749e-01, 8.773e-01, 8.542e-01, 7.194e-01, 5.873e-01, 5.594e-01, 5.061e-01, 4.141e-01, 2.761e-01, 1.656e-01, 1.288e-01, 1.251e-01, 1.227e-01, 1.458e-01, 2.806e-01, 4.127e-01, 4.406e-01, 4.939e-01, 5.859e-01, 7.239e-01, 8.344e-01, 8.712e-01, 8.749e-01, 8.773e-01, 8.542e-01, 7.194e-01, 5.873e-01, 5.594e-01, 5.061e-01, 4.141e-01, 2.761e-01, 1.656e-01, 1.288e-01, 1.251e-01, 1.227e-01, 1.458e-01, 2.806e-01, 4.127e-01, 4.406e-01, 4.939e-01, 5.859e-01, 7.239e-01, 8.344e-01, 8.712e-01, 8.749e-01, 8.773e-01, 8.542e-01, 7.194e-01, 5.873e-01, 5.594e-01, 5.061e-01, 4.141e-01, 2.761e-01, 1.656e-01, 1.288e-01])

    plot_enable = False
    if plot_enable:
        import numpy as np
        import matplotlib.pyplot as plt
        time_us = np.array(h.time) * 1e6  # convert to µs
        inp = np.array(h.inp.trans_voltage)
        out = np.array(h.out.trans_voltage)

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(time_us, inp, label='inp')
        ax.plot(time_us, out, label='out')
        ax.set_xlabel('Time (µs)')
        ax.set_ylabel('Voltage (V)')
        ax.legend()
        ax.grid(True)
        fig.tight_layout()
        
        fig.savefig("pulsedrc_tran.svg")
        plt.close(fig)

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
    h = lib_test.SineRC().sim_ac

    # Reference data generated using h.out.ac_voltage.dump().
    assert_simcolumn(h.out.ac_voltage, [(1.000e+00-6.283e-05j), (1.000e+00-7.910e-05j), (1.000e+00-9.958e-05j), (1.000e+00-1.254e-04j), (1.000e+00-1.578e-04j), (1.000e+00-1.987e-04j), (1.000e+00-2.501e-04j), (1.000e+00-3.149e-04j), (1.000e+00-3.964e-04j), (1.000e+00-4.991e-04j), (1.000e+00-6.283e-04j), (1.000e+00-7.910e-04j), (1.000e+00-9.958e-04j), (1.000e+00-1.254e-03j), (1.000e+00-1.578e-03j), (1.000e+00-1.987e-03j), (1.000e+00-2.501e-03j), (1.000e+00-3.149e-03j), (1.000e+00-3.964e-03j), (1.000e+00-4.991e-03j), (1.000e+00-6.283e-03j), (9.999e-01-7.910e-03j), (9.999e-01-9.957e-03j), (9.998e-01-1.253e-02j), (9.998e-01-1.578e-02j), (9.996e-01-1.986e-02j), (9.994e-01-2.500e-02j), (9.990e-01-3.146e-02j), (9.984e-01-3.958e-02j), (9.975e-01-4.979e-02j), (9.961e-01-6.258e-02j), (9.938e-01-7.861e-02j), (9.902e-01-9.860e-02j), (9.845e-01-1.234e-01j), (9.757e-01-1.540e-01j), (9.620e-01-1.911e-01j), (9.411e-01-2.354e-01j), (9.098e-01-2.865e-01j), (8.642e-01-3.426e-01j), (8.006e-01-3.996e-01j), (7.170e-01-4.505e-01j), (6.151e-01-4.866e-01j), (5.021e-01-5.000e-01j), (3.889e-01-4.875e-01j), (2.865e-01-4.521e-01j), (2.021e-01-4.016e-01j), (1.378e-01-3.447e-01j), (9.160e-02-2.885e-01j), (5.982e-02-2.372e-01j), (3.860e-02-1.926e-01j), (2.470e-02-1.552e-01j), (1.573e-02-1.244e-01j), (9.983e-03-9.942e-02j), (6.322e-03-7.926e-02j), (3.999e-03-6.311e-02j), (2.527e-03-5.020e-02j), (1.596e-03-3.991e-02j), (1.007e-03-3.172e-02j), (6.359e-04-2.521e-02j), (4.013e-04-2.003e-02j), (2.532e-04-1.591e-02j), (1.598e-04-1.264e-02j), (1.008e-04-1.004e-02j), (6.362e-05-7.976e-03j), (4.014e-05-6.336e-03j), (2.533e-05-5.033e-03j), (1.598e-05-3.998e-03j), (1.008e-05-3.176e-03j), (6.363e-06-2.522e-03j), (4.015e-06-2.004e-03j), (2.533e-06-1.592e-03j), (1.598e-06-1.264e-03j), (1.008e-06-1.004e-03j), (6.363e-07-7.977e-04j), (4.015e-07-6.336e-04j), (2.533e-07-5.033e-04j), (1.598e-07-3.998e-04j), (1.008e-07-3.176e-04j), (6.363e-08-2.522e-04j), (4.015e-08-2.004e-04j), (2.533e-08-1.592e-04j), (1.598e-08-1.264e-04j), (1.008e-08-1.004e-04j), (6.363e-09-7.977e-05j), (4.015e-09-6.336e-05j), (2.533e-09-5.033e-05j), (1.598e-09-3.998e-05j), (1.008e-09-3.176e-05j), (6.363e-10-2.522e-05j), (4.015e-10-2.004e-05j), (2.533e-10-1.592e-05j)])

    plot_enable = False
    if plot_enable:
        import numpy as np
        import matplotlib.pyplot as plt
        freq = np.array(h.freq)
        out = np.array(list(h.out.ac_voltage))
        mag_db = 20 * np.log10(np.abs(out))
        phase_deg = np.degrees(np.angle(out))

        fig, (ax_mag, ax_phase) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
        ax_mag.semilogx(freq, mag_db)
        ax_mag.set_ylabel('Magnitude (dB)')
        ax_mag.grid(True)
        ax_phase.semilogx(freq, phase_deg)
        ax_phase.set_xlabel('Frequency (Hz)')
        ax_phase.set_ylabel('Phase (°)')
        ax_phase.grid(True)
        fig.tight_layout()

        fig.savefig("sinerc_ac.svg")
        plt.close(fig)


def test_webdata():
    # Test DC webdata
    h_dc = lib_test.ResdivFlatTb().sim_dc
    sim_type, data = h_dc.webdata()
    assert sim_type == 'dcsim'
    assert 'dc_voltages' in data
    assert 'dc_currents' in data

    # Test transient webdata
    h_tran = lib_test.ResdivFlatTb().sim_tran(R('0.1u'), R('1u'))
    sim_type, data = h_tran.webdata()
    assert sim_type == 'transim'
    assert 'time' in data
    assert 'voltages' in data
    assert 'currents' in data
