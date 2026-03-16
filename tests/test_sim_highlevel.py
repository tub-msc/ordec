# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
import math
from ordec.schematic.netlister import Netlister
from ordec import R
from .lib import sim as lib_test
from ordec.core import *

# Helper functions
# ----------------

@pytest.fixture(params=[True, False], ids=["batch", "piped"])
def sim_batch(request):
    return request.param


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
    offset = float(src.dc)
    amplitude = float(src.ac)
    frequency = float(src.freq)
    delay = float(src.delay)
    damping = float(src.damping)

    if t < delay:
        return offset
    td = t - delay
    return offset + amplitude * math.sin(2 * math.pi * frequency * td) * math.exp(-damping * td)

# Passive & ideal components
# --------------------------

def test_sim_dc_flat(sim_batch):
    tb = lib_test.ResdivFlatTb()
    h = tb.sim_dc_batch if sim_batch else tb.sim_dc_piped
    assert h.a.voltage[0] == pytest.approx(1.0 / 3.0, abs=1e-12)
    assert h.b.voltage[0] == pytest.approx(2.0 / 3.0, abs=1e-12)

def test_sim_dc_hier(sim_batch):
    tb = lib_test.ResdivHierTb()
    h = tb.sim_dc_batch if sim_batch else tb.sim_dc_piped
    assert h.r.voltage[0] == pytest.approx(0.3589743589743596, abs=1e-10)
    assert h.I0.I1.m.voltage[0] == pytest.approx(0.5897435897435901, abs=1e-10)
    # Top-level: voltage source current
    assert h.I2.p.current[0] == pytest.approx(-2.051282e-03, abs=1e-8)
    # Nested: ResdivHier1 -> ResdivHier2(r=100) -> Res I0.p
    assert h.I0.I0.I0.p.current[0] == pytest.approx(2.051282e-03, abs=1e-8)
    # Nested: ResdivHier1 -> ResdivHier2(r=200) -> Res I1.p
    assert h.I0.I1.I1.p.current[0] == pytest.approx(2.051282e-03, abs=1e-8)
    # Deeper nesting via path: ResdivHier1 -> sub2.I2 -> Res I2.p (no current: shorted)
    assert h.I0.sub2.I2.I2.p.current[0] == pytest.approx(0, abs=1e-10)


def test_sim_vpwltb_tran(sim_batch):
    tb = lib_test.VpwlTb()
    h = tb.sim_tran_batch if sim_batch else tb.sim_tran_piped
    for t, out_v in zip(h.time, h.out.voltage):
        assert out_v == pytest.approx(expected_pwl_value(t), abs=1e-6)


def test_sim_ipwltb_tran(sim_batch):
    tb = lib_test.IpwlTb()
    h = tb.sim_tran_batch if sim_batch else tb.sim_tran_piped
    for t, res_i in zip(h.time, h.res.p.current):
        assert res_i == pytest.approx(expected_pwl_value(t), abs=1e-8)


def test_sim_vpulsetb_tran(sim_batch):
    tb = lib_test.VpulseTb()
    src = tb.schematic.vsrc.symbol.cell
    h = tb.sim_tran_batch if sim_batch else tb.sim_tran_piped
    for t, out_v in zip(h.time, h.out.voltage):
        expected = expected_pulse_value(t, src)
        assert out_v == pytest.approx(expected, abs=1e-6)


def test_sim_ipulsetb_tran(sim_batch):
    tb = lib_test.IpulseTb()
    src = tb.schematic.isrc.symbol.cell
    h = tb.sim_tran_batch if sim_batch else tb.sim_tran_piped
    for t, res_i in zip(h.time, h.res.p.current):
        expected = expected_pulse_value(t, src)
        assert res_i == pytest.approx(expected, abs=1e-8)


def test_sim_vsintb_tran(sim_batch):
    tb = lib_test.VsinTb()
    src = tb.schematic.vsrc.symbol.cell
    h = tb.sim_tran_batch if sim_batch else tb.sim_tran_piped
    for t, out_v in zip(h.time, h.out.voltage):
        expected = expected_sin_value(t, src)
        assert out_v == pytest.approx(expected, abs=1e-6)


def test_sim_isintb_tran(sim_batch):
    tb = lib_test.IsinTb()
    src = tb.schematic.isrc.symbol.cell
    h = tb.sim_tran_batch if sim_batch else tb.sim_tran_piped
    for t, res_i in zip(h.time, h.res.p.current):
        expected = expected_sin_value(t, src)
        assert res_i == pytest.approx(expected, abs=1e-8)


def test_sim_sinerc_ac(sim_batch):
    tb = lib_test.SineRC()
    r = float(tb.schematic.res.symbol.cell.r)
    c = float(tb.schematic.cap.symbol.cell.c)
    h = tb.sim_ac_batch if sim_batch else tb.sim_ac_piped
    expected = [1.0 / (1.0 + 1j * 2.0 * math.pi * f * r * c) for f in h.freq]
    assert_simcolumn(h.out.voltage, expected, tol=0.02)


def test_sim_pulsedrc_tran(sim_batch):
    tb = lib_test.PulsedRC()
    src = tb.schematic.vsrc.symbol.cell
    tau = float(tb.schematic.res.symbol.cell.r) * float(tb.schematic.cap.symbol.cell.c)

    h = tb.sim_tran_batch if sim_batch else tb.sim_tran_piped
    expected_inp = [expected_pulse_value(t, src) for t in h.time]
    for got, exp in zip(h.inp.voltage, expected_inp):
        assert got == pytest.approx(exp, abs=1e-6)

    # Simple discrete RC update (backward Euler) on sampled Vin.
    expected_out = [float(h.out.voltage[0])]
    for i in range(1, len(h.time)):
        dt = float(h.time[i] - h.time[i - 1])
        alpha = dt / tau
        vin = expected_pulse_value(float(h.time[i]), src)
        y_prev = expected_out[-1]
        expected_out.append((y_prev + alpha * vin) / (1.0 + alpha))

    for got, exp in zip(h.out.voltage, expected_out):
        assert got == pytest.approx(exp, abs=0.07)


# generic_mos tests
# -----------------

def test_generic_mos_netlister():
    nl = Netlister(Directory())
    nl.netlist_hier(lib_test.NmosSourceFollowerTb(vin=R(2)).schematic)
    netlist = nl.out()

    assert netlist.count('.model nmosgeneric NMOS level=1') == 1
    assert netlist.count('.model pmosgeneric PMOS level=1') == 1

def test_generic_mos_nmos_sourcefollower(sim_batch):
    tb = lib_test.NmosSourceFollowerTb(vin=R(2))
    h = tb.sim_dc_batch if sim_batch else tb.sim_dc_piped
    assert h.o.voltage[0] == pytest.approx(1.2837721914145377, abs=1e-6)
    tb = lib_test.NmosSourceFollowerTb(vin=R(3))
    h = tb.sim_dc_batch if sim_batch else tb.sim_dc_piped
    assert h.o.voltage[0] == pytest.approx(2.2837721567191442, abs=1e-6)

def test_op_save_params(sim_batch):
    tb = lib_test.NmosSourceFollowerTb(vin=R(2))
    h = tb.sim_dc_batch if sim_batch else tb.sim_dc_piped
    nmos = h.I0
    assert nmos.params['gm'].value[0] > 0
    assert nmos.params['gds'].value[0] == pytest.approx(0)

def test_generic_mos_inv_dc_sweep(sim_batch):
    tb = lib_test.InvTb()
    i_ref = [0.000e+00, 2.000e-02, 4.000e-02, 6.000e-02, 8.000e-02, 1.000e-01, 1.200e-01, 1.400e-01, 1.600e-01, 1.800e-01, 2.000e-01, 2.200e-01, 2.400e-01, 2.600e-01, 2.800e-01, 3.000e-01, 3.200e-01, 3.400e-01, 3.600e-01, 3.800e-01, 4.000e-01, 4.200e-01, 4.400e-01, 4.600e-01, 4.800e-01, 5.000e-01, 5.200e-01, 5.400e-01, 5.600e-01, 5.800e-01, 6.000e-01, 6.200e-01, 6.400e-01, 6.600e-01, 6.800e-01, 7.000e-01, 7.200e-01, 7.400e-01, 7.600e-01, 7.800e-01, 8.000e-01, 8.200e-01, 8.400e-01, 8.600e-01, 8.800e-01, 9.000e-01, 9.200e-01, 9.400e-01, 9.600e-01, 9.800e-01, 1.000e+00, 1.020e+00, 1.040e+00, 1.060e+00, 1.080e+00, 1.100e+00, 1.120e+00, 1.140e+00, 1.160e+00, 1.180e+00, 1.200e+00, 1.220e+00, 1.240e+00, 1.260e+00, 1.280e+00, 1.300e+00, 1.320e+00, 1.340e+00, 1.360e+00, 1.380e+00, 1.400e+00, 1.420e+00, 1.440e+00, 1.460e+00, 1.480e+00, 1.500e+00, 1.520e+00, 1.540e+00, 1.560e+00, 1.580e+00, 1.600e+00, 1.620e+00, 1.640e+00, 1.660e+00, 1.680e+00, 1.700e+00, 1.720e+00, 1.740e+00, 1.760e+00, 1.780e+00, 1.800e+00, 1.820e+00, 1.840e+00, 1.860e+00, 1.880e+00, 1.900e+00, 1.920e+00, 1.940e+00, 1.960e+00, 1.980e+00, 2.000e+00, 2.020e+00, 2.040e+00, 2.060e+00, 2.080e+00, 2.100e+00, 2.120e+00, 2.140e+00, 2.160e+00, 2.180e+00, 2.200e+00, 2.220e+00, 2.240e+00, 2.260e+00, 2.280e+00, 2.300e+00, 2.320e+00, 2.340e+00, 2.360e+00, 2.380e+00, 2.400e+00, 2.420e+00, 2.440e+00, 2.460e+00, 2.480e+00, 2.500e+00, 2.520e+00, 2.540e+00, 2.560e+00, 2.580e+00, 2.600e+00, 2.620e+00, 2.640e+00, 2.660e+00, 2.680e+00, 2.700e+00, 2.720e+00, 2.740e+00, 2.760e+00, 2.780e+00, 2.800e+00, 2.820e+00, 2.840e+00, 2.860e+00, 2.880e+00, 2.900e+00, 2.920e+00, 2.940e+00, 2.960e+00, 2.980e+00, 3.000e+00, 3.020e+00, 3.040e+00, 3.060e+00, 3.080e+00, 3.100e+00, 3.120e+00, 3.140e+00, 3.160e+00, 3.180e+00, 3.200e+00, 3.220e+00, 3.240e+00, 3.260e+00, 3.280e+00, 3.300e+00, 3.320e+00, 3.340e+00, 3.360e+00, 3.380e+00, 3.400e+00, 3.420e+00, 3.440e+00, 3.460e+00, 3.480e+00, 3.500e+00, 3.520e+00, 3.540e+00, 3.560e+00, 3.580e+00, 3.600e+00, 3.620e+00, 3.640e+00, 3.660e+00, 3.680e+00, 3.700e+00, 3.720e+00, 3.740e+00, 3.760e+00, 3.780e+00, 3.800e+00, 3.820e+00, 3.840e+00, 3.860e+00, 3.880e+00, 3.900e+00, 3.920e+00, 3.940e+00, 3.960e+00, 3.980e+00, 4.000e+00, 4.020e+00, 4.040e+00, 4.060e+00, 4.080e+00, 4.100e+00, 4.120e+00, 4.140e+00, 4.160e+00, 4.180e+00, 4.200e+00, 4.220e+00, 4.240e+00, 4.260e+00, 4.280e+00, 4.300e+00, 4.320e+00, 4.340e+00, 4.360e+00, 4.380e+00, 4.400e+00, 4.420e+00, 4.440e+00, 4.460e+00, 4.480e+00, 4.500e+00, 4.520e+00, 4.540e+00, 4.560e+00, 4.580e+00, 4.600e+00, 4.620e+00, 4.640e+00, 4.660e+00, 4.680e+00, 4.700e+00, 4.720e+00, 4.740e+00, 4.760e+00, 4.780e+00, 4.800e+00, 4.820e+00, 4.840e+00, 4.860e+00, 4.880e+00, 4.900e+00, 4.920e+00, 4.940e+00, 4.960e+00, 4.980e+00, 5.000e+00]
    o_ref = [5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 5.000e+00, 4.999e+00, 4.999e+00, 4.998e+00, 4.998e+00, 4.997e+00, 4.996e+00, 4.995e+00, 4.994e+00, 4.993e+00, 4.991e+00, 4.990e+00, 4.988e+00, 4.987e+00, 4.985e+00, 4.983e+00, 4.981e+00, 4.979e+00, 4.977e+00, 4.974e+00, 4.972e+00, 4.969e+00, 4.966e+00, 4.963e+00, 4.960e+00, 4.957e+00, 4.953e+00, 4.950e+00, 4.946e+00, 4.942e+00, 4.938e+00, 4.934e+00, 4.929e+00, 4.925e+00, 4.920e+00, 4.915e+00, 4.910e+00, 4.905e+00, 4.899e+00, 4.893e+00, 4.887e+00, 4.881e+00, 4.875e+00, 4.868e+00, 4.862e+00, 4.855e+00, 4.847e+00, 4.840e+00, 4.832e+00, 4.824e+00, 4.816e+00, 4.807e+00, 4.798e+00, 4.789e+00, 4.780e+00, 4.770e+00, 4.760e+00, 4.750e+00, 4.739e+00, 4.728e+00, 4.716e+00, 4.704e+00, 4.692e+00, 4.680e+00, 4.667e+00, 4.653e+00, 4.639e+00, 4.625e+00, 4.610e+00, 4.595e+00, 4.579e+00, 4.562e+00, 4.545e+00, 4.527e+00, 4.509e+00, 4.490e+00, 4.470e+00, 4.449e+00, 4.428e+00, 4.406e+00, 4.382e+00, 4.358e+00, 4.333e+00, 4.307e+00, 4.279e+00, 4.250e+00, 4.220e+00, 4.187e+00, 4.154e+00, 4.118e+00, 4.080e+00, 4.039e+00, 3.996e+00, 3.950e+00, 3.899e+00, 3.844e+00, 3.784e+00, 3.717e+00, 3.640e+00, 3.550e+00, 3.440e+00, 3.292e+00, 2.904e+00, 1.710e+00, 1.560e+00, 1.449e+00, 1.360e+00, 1.283e+00, 1.216e+00, 1.156e+00, 1.101e+00, 1.050e+00, 1.004e+00, 9.606e-01, 9.201e-01, 8.822e-01, 8.464e-01, 8.125e-01, 7.805e-01, 7.500e-01, 7.210e-01, 6.934e-01, 6.670e-01, 6.417e-01, 6.175e-01, 5.943e-01, 5.720e-01, 5.506e-01, 5.300e-01, 5.102e-01, 4.911e-01, 4.727e-01, 4.550e-01, 4.379e-01, 4.214e-01, 4.054e-01, 3.900e-01, 3.751e-01, 3.607e-01, 3.468e-01, 3.333e-01, 3.203e-01, 3.077e-01, 2.955e-01, 2.837e-01, 2.723e-01, 2.612e-01, 2.505e-01, 2.401e-01, 2.300e-01, 2.203e-01, 2.109e-01, 2.017e-01, 1.929e-01, 1.843e-01, 1.760e-01, 1.680e-01, 1.603e-01, 1.528e-01, 1.455e-01, 1.385e-01, 1.317e-01, 1.251e-01, 1.188e-01, 1.126e-01, 1.067e-01, 1.010e-01, 9.546e-02, 9.014e-02, 8.500e-02, 8.006e-02, 7.530e-02, 7.071e-02, 6.631e-02, 6.207e-02, 5.800e-02, 5.410e-02, 5.035e-02, 4.677e-02, 4.333e-02, 4.006e-02, 3.692e-02, 3.394e-02, 3.110e-02, 2.840e-02, 2.583e-02, 2.341e-02, 2.111e-02, 1.895e-02, 1.691e-02, 1.500e-02, 1.322e-02, 1.156e-02, 1.001e-02, 8.588e-03, 7.279e-03, 6.085e-03, 5.003e-03, 4.032e-03, 3.170e-03, 2.415e-03, 1.765e-03, 1.220e-03, 7.768e-04, 4.348e-04, 1.923e-04, 4.788e-05, 2.871e-08, 2.941e-08, 2.954e-08, 2.940e-08, 2.926e-08, 2.913e-08, 2.899e-08, 2.886e-08, 2.873e-08, 2.860e-08, 2.847e-08, 2.834e-08, 2.821e-08, 2.808e-08, 2.796e-08, 2.783e-08, 2.771e-08, 2.759e-08, 2.747e-08, 2.735e-08, 2.723e-08]
    h = tb.sim_dc_batch if sim_batch else tb.sim_dc_piped
    assert h.sim_type == SimType.DCSWEEP
    assert len(h.i.voltage) == len(i_ref)
    assert len(h.o.voltage) == len(o_ref)
    for got, ref in zip(h.i.voltage, i_ref):
        assert got == pytest.approx(ref, abs=5e-4)
    for got, ref in zip(h.o.voltage, o_ref):
        assert got == pytest.approx(ref, abs=5e-4)


# SKY130 tests
# ------------

def test_sky130_inv_dc_sweep(sim_batch):
    tb = lib_test.InvSkyTb()
    h = tb.sim_dc_batch if sim_batch else tb.sim_dc_piped
    assert h.sim_type == SimType.DCSWEEP
    # vin=0 -> output ~5V
    assert h.o.voltage[0] == pytest.approx(4.999999973187308, abs=1e-10)
    # vin=2.5 -> midpoint
    assert h.o.voltage[125] == pytest.approx(1.9806063550640076, abs=1e-6)
    # vin=5 -> output ~0V
    assert h.o.voltage[-1] == pytest.approx(0.00012158997833462999, abs=1e-10)

def test_sky130_nmos_out_of_range(sim_batch):
    from ordec.sim.ngspice import NgspiceError
    from ordec.lib import sky130
    from ordec.sim import Simulator

    s = Schematic()
    s.vss = Net()
    nmos = sky130.Nmos(l=R("100n"), w=R("250n")).symbol
    s.i_nmos = SchemInstance(nmos.portmap(g=s.vss, d=s.vss, s=s.vss, b=s.vss), pos=Vec2R(10, 5))
    s = s.freeze()

    h = SimHierarchy.from_schematic(s)
    with pytest.raises(NgspiceError, match="circuit not parsed"):
        Simulator(h, batch=sim_batch).op()

# IHP130 tests
# ------------

def test_ihp130_inv_dc_sweep(sim_batch):
    tb = lib_test.InvIhpTb()
    h = tb.sim_dc_batch if sim_batch else tb.sim_dc_piped
    assert h.sim_type == SimType.DCSWEEP
    # vin=0 -> output ~5V
    assert h.o.voltage[0] == pytest.approx(4.999573, abs=1e-4)
    # vin=5 -> output ~0V
    assert h.o.voltage[-1] == pytest.approx(0.00024556, abs=1e-5)
