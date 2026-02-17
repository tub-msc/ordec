# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.schematic.netlister import Netlister
from ordec import Rational as R
from .lib import sim as lib_test
from ordec.core import *
from ordec.sim.sim_hierarchy import SimHierarchy, HighlevelSim

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
    assert abs(h.r.dc_voltage - 0.3589743589743596) < 1e-10
    assert abs(h.I0.I1.m.dc_voltage - 0.5897435897435901) < 1e-10

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
    assert abs(lib_test.InvSkyTb(vin=R(0)).sim_dc.o.dc_voltage - 4.999999973187308) < 1e-10
    assert abs(lib_test.InvSkyTb(vin=R('2.5')).sim_dc.o.dc_voltage - 1.9806063550640076) < 1e-10
    assert abs(lib_test.InvSkyTb(vin=R(5)).sim_dc.o.dc_voltage - 0.00012158997833462999) < 1e-10

def test_ihp_mos_inv_vin0():
    h_0 = lib_test.InvIhpTb(vin=R(0)).sim_dc
    assert h_0.o.dc_voltage == pytest.approx(4.999573)

def test_ihp_mos_inv_vin5():
    h_5 = lib_test.InvIhpTb(vin=R(5)).sim_dc
    assert h_5.o.dc_voltage == pytest.approx(0.00024556, abs=1e-5)

def test_sim_tran_flat():
    h = lib_test.ResdivFlatTb().sim_tran(R('0.1u'), R('1u'))
    assert len(h.time) > 0
    assert abs(h.a.trans_voltage[-1] - 0.3333333) < 1e-6
    assert abs(h.b.trans_voltage[-1] - 0.6666667) < 1e-6


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

def test_sim_ac_rc_filter():
    import math
    import numpy as np

    tb = lib_test.RcFilterTb(r='1k', c='1n')
    h = tb.sim_ac('dec', '10', '1', '1G')

    # Check that we have results
    assert len(h.freq) > 0
    assert hasattr(h, 'out')
    assert len(h.out.ac_voltage) > 0

    # Calculate cutoff frequency
    f_c = 1 / (2 * math.pi * tb.r * tb.c)

    # Find the frequency in the simulation results closest to the cutoff frequency
    freq_array = np.array(h.freq)
    idx = (np.abs(freq_array - f_c)).argmin()

    # Check the voltage magnitude at the cutoff frequency
    vout_complex = h.out.ac_voltage[idx]
    vout_mag = abs(vout_complex)

    # At the -3dB point, the magnitude should be 1/sqrt(2)
    assert np.isclose(vout_mag, 1/math.sqrt(2), atol=1e-2)
