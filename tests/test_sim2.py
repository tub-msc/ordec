# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
import pytest
from ordec.sim2.ngspice import Ngspice, Netlister
from ordec.sim2.ngspice_common import NgspiceError, NgspiceFatalError
from ordec import Rational as R
from ordec.lib import test as lib_test
from ordec.core import *
from ordec.sim2.sim_hierarchy import SimHierarchy, HighlevelSim
from ordec.lib.test import RCAlterTestbench

sim2_backends = [
    pytest.param('subprocess', marks=[]),
    pytest.param('ffi', marks=[pytest.mark.libngspice]),
    pytest.param('mp', marks=[pytest.mark.libngspice]),
]

@pytest.mark.parametrize("backend", sim2_backends)
def test_ngspice_illegal_netlist_1(backend):
    with Ngspice.launch(debug=True, backend=backend) as sim:
        with pytest.raises(NgspiceFatalError, match=".*Error: Mismatch of .subckt ... .ends statements!.*"):
            sim.load_netlist(".title test\n.ends\n.end")

@pytest.mark.parametrize("backend", sim2_backends)
def test_ngspice_illegal_netlist_2(backend):
    with Ngspice.launch(debug=True, backend=backend) as sim:
        with pytest.raises(NgspiceError, match=".*unknown subckt: x0 1 2 3 invalid.*"):
            sim.load_netlist(".title test\nx0 1 2 3 invalid\n.end")

@pytest.mark.skip(reason="Ngspice seems to hang here.")
@pytest.mark.parametrize("backend", sim2_backends)
def test_ngspice_illegal_netlist_3(backend):
    broken_netlist = """.title test
    MN0 d 0 0 0 N1 w=hello
    .end
    """
    with Ngspice.launch(debug=True, backend=backend) as sim:
        sim.load_netlist(broken_netlist)

# TODO: Not all problems seem to currently be caught and raises in Python as exception at the moment (see sky130 with Rational params).

@pytest.mark.parametrize("backend", sim2_backends)
def test_ngspice_version(backend):
    with Ngspice.launch(debug=True, backend=backend) as sim:
        version_str = sim.command("version -f")
        version_number = int(re.search(r"\*\* ngspice-([0-9]+)(.[0-9]+)?\s+", version_str).group(1))
        assert version_number >= 39

@pytest.mark.parametrize("backend", sim2_backends)
def test_ngspice_op_no_auto_gnd(backend):
    netlist_voltage_divider = """.title voltage divider netlist
    V1 in 0 3
    R1 in a 1k
    R2 a gnd 1k
    R3 gnd 0 1k
    .end
    """

    def voltages(op):
        return {name:value for vtype, name, subname, value in op if vtype=='voltage'}

    # Default behavior: net 'gnd' is automatically ground.
    with Ngspice.launch(debug=True, backend=backend) as sim:
        # Reset no_auto_gnd to ensure clean state
        sim.command("unset no_auto_gnd")
        sim.load_netlist(netlist_voltage_divider, no_auto_gnd=False)
        op = voltages(sim.op())
    assert op['a'] == 1.5

    # Altered no_auto_gnd behavior
    with Ngspice.launch(debug=True, backend=backend) as sim:
        sim.load_netlist(netlist_voltage_divider, no_auto_gnd=True)
        op = voltages(sim.op())
    assert op['a'] == 2.0
    assert op['gnd'] == 1.0

@pytest.mark.parametrize("backend,golden_a,golden_b", [
    ('subprocess', 0.3333333, 0.6666667),
    pytest.param('ffi', 0.33333333333333337, 0.6666666666666667, marks=pytest.mark.libngspice),
    pytest.param('mp', 0.33333333333333337, 0.6666666666666667, marks=pytest.mark.libngspice),
])
def test_sim_dc_flat(backend, golden_a, golden_b):
    h = lib_test.ResdivFlatTb(backend=backend).sim_dc
    # Note: FFI backend has different golden values
    assert h.a.dc_voltage == golden_a
    assert h.b.dc_voltage == golden_b


@pytest.mark.parametrize("backend,golden_r,golden_m", [
    ('subprocess', 0.3589744, 0.5897436),
    pytest.param('ffi', 0.3589743589743596, 0.5897435897435901, marks=pytest.mark.libngspice),
    pytest.param('mp', 0.3589743589743596, 0.5897435897435901, marks=pytest.mark.libngspice),
])
def test_sim_dc_hier(backend, golden_r, golden_m):
    h = lib_test.ResdivHierTb(backend=backend).sim_dc
    # Note: FFI backend has different golden values
    assert h.r.dc_voltage == golden_r
    assert h.I0.I1.m.dc_voltage == golden_m

def test_generic_mos_netlister():
    nl = Netlister()
    nl.netlist_hier(lib_test.NmosSourceFollowerTb(vin=R(2)).schematic)
    netlist = nl.out()

    assert netlist.count('.model nmosgeneric NMOS level=1') == 1
    assert netlist.count('.model pmosgeneric PMOS level=1') == 1

@pytest.mark.parametrize("backend,golden_2,golden_3", [
    ('subprocess', 0.6837722, 1.683772),
    pytest.param('ffi', 0.6837722116612965, 1.6837721784225057, marks=pytest.mark.libngspice),
    pytest.param('mp', 0.6837722116612965, 1.6837721784225057, marks=pytest.mark.libngspice),
])
def test_generic_mos_nmos_sourcefollower(backend, golden_2, golden_3):
    assert lib_test.NmosSourceFollowerTb(vin=R(2), backend=backend).sim_dc.o.dc_voltage == golden_2
    assert lib_test.NmosSourceFollowerTb(vin=R(3), backend=backend).sim_dc.o.dc_voltage == golden_3

@pytest.mark.parametrize("backend,golden_0,golden_2_5,golden_5", [
    ('subprocess', 5.0, 2.5, 3.13125e-08),
    pytest.param('ffi', 4.9999999698343345, 2.500000017115547, 3.131249965532494e-08, marks=pytest.mark.libngspice),
    pytest.param('mp', 4.9999999698343345, 2.500000017115547, 3.131249965532494e-08, marks=pytest.mark.libngspice),
])
def test_generic_mos_inv(backend, golden_0, golden_2_5, golden_5):
    assert lib_test.InvTb(vin=R(0), backend=backend).sim_dc.o.dc_voltage == golden_0
    assert lib_test.InvTb(vin=R('2.5'), backend=backend).sim_dc.o.dc_voltage == golden_2_5
    assert lib_test.InvTb(vin=R(5), backend=backend).sim_dc.o.dc_voltage == golden_5

@pytest.mark.parametrize("backend,golden_0,golden_2_5,golden_5", [
    ('subprocess', 5.0, 1.980606, 0.00012159),
    pytest.param('ffi', 4.999999973187308, 1.9806063550640076, 0.00012158997833462999, marks=pytest.mark.libngspice),
    pytest.param('mp', 4.999999973187308, 1.9806063550640076, 0.00012158997833462999, marks=pytest.mark.libngspice),
])
def test_sky_mos_inv(backend, golden_0, golden_2_5, golden_5):
    assert lib_test.InvSkyTb(vin=R(0), backend=backend).sim_dc.o.dc_voltage == golden_0
    assert lib_test.InvSkyTb(vin=R('2.5'), backend=backend).sim_dc.o.dc_voltage == golden_2_5
    assert lib_test.InvSkyTb(vin=R(5), backend=backend).sim_dc.o.dc_voltage == golden_5

@pytest.mark.parametrize("backend,golden", [
    ('subprocess', 4.999573),
    pytest.param('ffi', 4.9995727, marks=pytest.mark.libngspice),
    pytest.param('mp', 4.9995727, marks=pytest.mark.libngspice),
])
def test_ihp_mos_inv_vin0(backend, golden):
    h_0 = lib_test.InvIhpTb(vin=R(0), backend=backend).sim_dc
    assert h_0.o.dc_voltage == pytest.approx(golden)

@pytest.mark.parametrize("backend,golden", [
    ('subprocess', 0.00024556),
    pytest.param('ffi', 0.00024556, marks=pytest.mark.libngspice),
    pytest.param('mp', 0.00024556, marks=pytest.mark.libngspice),
])
def test_ihp_mos_inv_vin5(backend, golden):
    h_5 = lib_test.InvIhpTb(vin=R(5), backend=backend).sim_dc
    assert h_5.o.dc_voltage == pytest.approx(golden, abs=1e-5)

@pytest.mark.parametrize("backend,golden_a,golden_b,atol", [
    ('subprocess', 0.3333333, 0.6666667, 1e-6),
    pytest.param('ffi', 0.33333333333333337, 0.6666666666666667, 1e-9, marks=pytest.mark.libngspice),
    pytest.param('mp', 0.33333333333333337, 0.6666666666666667, 1e-9, marks=pytest.mark.libngspice),
])
def test_sim_tran_flat(backend, golden_a, golden_b, atol):
    h = lib_test.ResdivFlatTb(backend=backend).sim_tran("0.1u", "1u")
    assert len(h.time) > 0
    assert abs(h.a.trans_voltage[-1] - golden_a) < atol
    assert abs(h.b.trans_voltage[-1] - golden_b) < atol

@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["ffi"])  # FFI backend required for precise timing control
def test_async_halt_and_alter(backend):
    """Test async simulation with halt and alter functionality using queue-based API"""
    import time
    import queue

    netlist = """.title Halt alter test
V1 in 0 DC 1
R1 in out 1k
C1 out 0 1uF IC=0
.end
"""

    with Ngspice.launch(debug=False, backend=backend) as sim:
        sim.load_netlist(netlist)

        # Start async simulation - returns queue instead of generator
        data_queue = sim.tran_async("5us", "10ms")
        assert isinstance(data_queue, queue.Queue), "tran_async should return Queue object"

        # Wait for startup
        timeout = time.time() + 3.0
        while not sim.is_running() and time.time() < timeout:
            time.sleep(0.01)

        if not sim.is_running():
            pytest.skip("Background simulation failed to start")

        # Let simulation run briefly to collect some data
        time.sleep(0.2)

        # Test safe halt with proper timing - this addresses the critical issue that
        # bg_halt is not instantaneous and can fail silently
        halt_success = sim.safe_halt_simulation(max_attempts=3, wait_time=0.2)
        assert halt_success, "Halt should succeed"
        assert not sim.is_running(), "Simulation should be stopped after halt"

        # Verify component state before alter
        show_before = sim.command("show r1")
        assert "1000" in show_before, "Should show original 1k resistance"

        # Test alter command - this only works when simulation is properly halted
        alter_result = sim.command("alter r1 resistance=2000")

        # Verify alter worked by checking component parameters
        show_after = sim.command("show r1")
        assert "2000" in show_after, "Should show altered 2k resistance"

        # Verify we can collect some queue data (demonstrates queue benefits)
        data_count = 0
        while not data_queue.empty() and data_count < 5:
            try:
                data_point = data_queue.get_nowait()
                assert 'data' in data_point, "Queue data should have expected structure"
                data_count += 1
            except queue.Empty:
                break

@pytest.mark.parametrize("backend", sim2_backends)
def test_webdata(backend):
    # Test DC webdata
    h_dc = lib_test.ResdivFlatTb(backend=backend).sim_dc
    sim_type, data = h_dc.webdata()
    assert sim_type == 'dcsim'
    assert 'dc_voltages' in data
    assert 'dc_currents' in data

    # Test transient webdata
    h_tran = lib_test.ResdivFlatTb(backend=backend).sim_tran("0.1u", "1u")
    sim_type, data = h_tran.webdata()
    assert sim_type == 'transim'
    assert 'time' in data
    assert 'voltages' in data
    assert 'currents' in data

@pytest.mark.parametrize("backend", sim2_backends)
def test_sim_ac_rc_filter(backend):
    import math
    import numpy as np

    r_val = 1e3
    c_val = 1e-9
    h = lib_test.RcFilterTb(r=R(r_val), c=R(c_val), backend=backend).sim_ac('dec', '10', '1', '1G')

    # Check that we have results
    assert len(h.freq) > 0
    assert hasattr(h, 'out')
    assert len(h.out.ac_voltage) > 0

    # Calculate cutoff frequency
    f_c = 1 / (2 * math.pi * r_val * c_val)

    # Find the frequency in the simulation results closest to the cutoff frequency
    freq_array = np.array(h.freq)
    idx = (np.abs(freq_array - f_c)).argmin()

    # Check the voltage magnitude at the cutoff frequency
    vout_complex = h.out.ac_voltage[idx]
    vout_mag = np.sqrt(vout_complex[0]**2 + vout_complex[1]**2)

    # At the -3dB point, the magnitude should be 1/sqrt(2)
    assert np.isclose(vout_mag, 1/math.sqrt(2), atol=1e-2)


@pytest.mark.parametrize("backend", sim2_backends)
def test_highlevel_alter_op(backend):
    """Test alter with op"""

    tb = RCAlterTestbench()
    node = SimHierarchy()
    sim = HighlevelSim(tb.schematic, node, backend=backend)

    with sim.alter_session(backend=backend) as alter:
        vdc_values = [1.0, 2.0, 5.0, 0.5, 1.0]

        for i, vdc_value in enumerate(vdc_values):
            # Alter VDC voltage
            alter.alter_component(tb.schematic.v1, dc=vdc_value)

            # Verify the change took effect
            v1_show = alter.show_component(tb.schematic.v1)
            # Handle both integer and float display (ngspice shows 1.0 as 1)
            expected_dc = str(int(vdc_value)) if vdc_value == int(vdc_value) else str(vdc_value)
            # Use regex to handle variable spacing in ngspice output
            dc_pattern = rf"dc\s+{re.escape(expected_dc)}"
            assert re.search(dc_pattern, v1_show), f"Step {i+1}: Should show dc {expected_dc} in output: {v1_show}"

            # Run operating point to verify circuit behavior
            alter.op()
            voltage = node.vout.dc_voltage

            # In this DC circuit, output should equal input voltage
            assert abs(voltage - vdc_value) < 0.01, f"Step {i+1}: DC output should be ~{vdc_value}V, got {voltage}V"

        # Test altering capacitor capacitance
        alter.alter_component(tb.schematic.c1, capacitance='2u')
        c1_show = alter.show_component(tb.schematic.c1)
        assert "2" in c1_show, "Should show altered capacitance value"

        # Final verification - ensure we can still alter VDC after capacitor change
        alter.alter_component(tb.schematic.v1, dc=3.0)
        final_v1_show = alter.show_component(tb.schematic.v1)
        # Use regex to handle variable spacing in ngspice output
        assert re.search(r"dc\s+3", final_v1_show), f"Final VDC change should work, output: {final_v1_show}"

        alter.op()
        final_voltage = node.vout.dc_voltage
        assert abs(final_voltage - 3.0) < 0.01, f"Final voltage should be ~3V, got {final_voltage}V"

@pytest.mark.parametrize("backend", sim2_backends)
def test_sim_ac_rc_filter_wrdata(backend):
    import math
    import numpy as np
    import tempfile

    r_val = 1e3
    c_val = 1e-9

    with tempfile.NamedTemporaryFile(suffix=".dat") as tmp:
        wrdata_file = tmp.name
        # The HighlevelSim object needs to be created and used within this context
        # so the wrdata_file path is valid.
        tb = lib_test.RcFilterTb(r=R(r_val), c=R(c_val), backend=backend)
        h = tb.sim_ac('dec', '10', '1', '1G', wrdata_file=wrdata_file)

        # Check that we have results
        assert len(h.freq) > 0
        assert hasattr(h, 'out')
        assert len(h.out.ac_voltage) > 0

        # Calculate cutoff frequency
        f_c = 1 / (2 * math.pi * r_val * c_val)

        # Find the frequency in the simulation results closest to the cutoff frequency
        freq_array = np.array(h.freq)
        idx = (np.abs(freq_array - f_c)).argmin()

        # Check the voltage magnitude at the cutoff frequency
        vout_complex = h.out.ac_voltage[idx]
        vout_mag = np.sqrt(vout_complex[0]**2 + vout_complex[1]**2)

        # At the -3dB point, the magnitude should be 1/sqrt(2)
        assert np.isclose(vout_mag, 1/math.sqrt(2), atol=1e-2)
