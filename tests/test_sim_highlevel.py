# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.schematic.netlister import Netlister
from ordec import Rational as R
from .lib import sim as lib_test
from ordec.core import *
from ordec.sim.sim_hierarchy import SimHierarchy, HighlevelSim

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
    vout_mag = np.sqrt(vout_complex[0]**2 + vout_complex[1]**2)

    # At the -3dB point, the magnitude should be 1/sqrt(2)
    assert np.isclose(vout_mag, 1/math.sqrt(2), atol=1e-2)
