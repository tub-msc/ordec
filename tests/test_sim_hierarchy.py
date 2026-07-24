# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import math
import pytest
from ordec.core import *
from ordec.core import SimHierarchy
from ordec.lib import Gnd, Res
from ordec.core.schema import SimHierarchySubcursor
from .lib import sim as lib_test

def my_simhier():
    schematic = lib_test.ResdivHierTb().schematic
    return SimHierarchy.from_schematic(schematic)

def test_setattr_setitem_delattr_delitem():
    simhier = my_simhier()

    with pytest.raises(TypeError):
        simhier.some_name = SimInstance()

    with pytest.raises(TypeError):
        simhier['some_name'] = SimInstance()
    
    with pytest.raises(TypeError):
        del simhier.some_name

    with pytest.raises(TypeError):
        del simhier['some_name']


def test_navigate_siminstances():
    """Test navigation through SimInstances."""
    simhier = my_simhier()

    siminst_I0 = simhier.subcursor().I0
    assert isinstance(siminst_I0, SimInstance)
    assert siminst_I0.eref == simhier.schematic.I0
    assert siminst_I0.parent_inst == None
    # Ensure that the .subcursor() call can be omitted:
    assert siminst_I0 == simhier.I0 == simhier['I0']
    assert siminst_I0.full_path_list() == ['I0']

    assert isinstance(simhier.I0.sub2, SimHierarchySubcursor)
    assert simhier.I0.sub2.simhierarchy == simhier
    assert simhier.I0.sub2.siminst == simhier.I0
    assert simhier.I0.sub2.node == lib_test.ResdivHier1().schematic.sub2
    assert simhier.I0.sub2 == simhier['I0']['sub2'] == simhier.I0.sub2

    siminst_I0_I2 = simhier.I0.sub2.I2
    assert isinstance(siminst_I0_I2, SimInstance)
    assert siminst_I0_I2.eref == lib_test.ResdivHier1().schematic.sub2.I2
    assert siminst_I0_I2.parent_inst == siminst_I0
    assert siminst_I0_I2.full_path_list() == ['I0', 'sub2', 'I2']

def test_navigate_simnets_nets():
    """Test navigation to SimNets pointing to Nets."""
    simhier = my_simhier()

    simnet_gnd = simhier.gnd
    assert isinstance(simnet_gnd, SimNet)
    assert simnet_gnd.eref == simhier.schematic.gnd
    assert simnet_gnd.parent_inst == None
    assert simnet_gnd.full_path_list() == ['gnd']

    simnet_I0_I2_t = simhier.I0.sub2.I2.t
    assert isinstance(simnet_I0_I2_t, SimNet)
    assert simnet_I0_I2_t.eref == lib_test.ResdivHier2(r=100).schematic.t
    assert simnet_I0_I2_t.parent_inst == simhier.I0.sub2.I2
    assert simnet_I0_I2_t.full_path_list() == ['I0', 'sub2', 'I2', 't']

    # Make sure that we can navigate with a symbol subcursor as well, even
    # if the schematic subcursor is available:
    assert simnet_I0_I2_t == simhier.I0.sub2.I2.subcursor_symbol().t

    # This is more interesting in a case where the pin name in the symbol
    # differs from the net name in the schemtic: 
    assert simhier.I0.subcursor_symbol().inputs.b == simhier.I0.b

def test_navigate_simnets_pins():
    """Test navigation to SimNets pointing to Pins."""
    simhier = my_simhier()

    simnet_I3_p = simhier.I3.p
    assert isinstance(simnet_I3_p, SimNet)
    assert simnet_I3_p.eref == Gnd().symbol.p
    assert simnet_I3_p.parent_inst == simhier.I3
    assert simnet_I3_p.full_path_list() == ['I3', 'p']

    simnet_I0_I2_I1_m = simhier.I0.sub2.I2.I1.m
    assert isinstance(simnet_I0_I2_I1_m, SimNet)
    assert simnet_I0_I2_I1_m.eref == Res(r=100).symbol.m
    assert simnet_I0_I2_I1_m.parent_inst == simhier.I0.sub2.I2.I1
    assert simnet_I0_I2_I1_m.full_path_list() == ['I0', 'sub2', 'I2', 'I1', 'm']

def test_no_simpins_before_simulation():
    """SimPin nodes are not created by from_schematic(); only by simulation."""
    simhier = my_simhier()
    assert list(simhier.all(SimPin)) == []


def test_export_no_sim_data():
    """Test that export methods raise ValueError when no simulation data."""
    simhier = my_simhier()
    with pytest.raises(ValueError, match="No simulation data"):
        simhier.to_numpy()
    with pytest.raises(ValueError, match="No simulation data"):
        simhier.write_csv("/tmp/test.csv")


def test_to_numpy_all():
    """Test to_numpy() with all fields (include=None), raw names."""
    import numpy as np
    tb = lib_test.ResdivHierTb()
    h = tb.sim_op_batch
    arr = h.to_numpy(translate_names=False)
    assert isinstance(arr, np.ndarray)
    assert len(arr) == len(h.sim_data)
    for f in h.sim_data.fields:
        assert f.fid in arr.dtype.names


def test_to_numpy_include():
    """Test to_numpy() with specific nodes in include, raw names."""
    import numpy as np
    tb = lib_test.ResdivHierTb()
    h = tb.sim_op_batch
    arr = h.to_numpy(include=[h.r, h.I2.p], translate_names=False)
    assert isinstance(arr, np.ndarray)
    assert len(arr) == len(h.sim_data)
    assert h.r.voltage_field in arr.dtype.names
    assert h.I2.p.current_field in arr.dtype.names
    # DC op-point has no independent variable, so just 2 fields
    assert len(arr.dtype.names) == 2


def test_to_numpy_invalid_include():
    """Test to_numpy() raises TypeError for invalid include nodes."""
    tb = lib_test.ResdivHierTb()
    h = tb.sim_op_batch
    with pytest.raises(TypeError, match="SimNet, SimPin, or SimParam"):
        h.to_numpy(include=[h.I0])


def test_write_csv_all(tmp_path):
    """Test write_csv() with all fields (include=None), raw names."""
    import csv
    tb = lib_test.ResdivHierTb()
    h = tb.sim_op_batch
    outfile = tmp_path / "sim_all.csv"
    h.write_csv(outfile, translate_names=False)
    with open(outfile) as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    assert len(rows) == len(h.sim_data)
    for f in h.sim_data.fields:
        assert f.fid in header


def test_write_csv_include(tmp_path):
    """Test write_csv() with specific nodes in include, raw names."""
    import csv
    tb = lib_test.ResdivHierTb()
    h = tb.sim_op_batch
    outfile = tmp_path / "sim_include.csv"
    h.write_csv(outfile, include=[h.r, h.I2.p], translate_names=False)
    with open(outfile) as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    assert len(rows) == len(h.sim_data)
    assert h.r.voltage_field in header
    assert h.I2.p.current_field in header
    # DC op-point has no independent variable, so just 2 fields
    assert len(header) == 2


def test_to_numpy_with_time_axis():
    """Test to_numpy() includes time axis for transient simulation, raw names."""
    import numpy as np
    tb = lib_test.VpwlTb()
    h = tb.sim_tran_batch
    assert h.time_field is not None
    arr = h.to_numpy(include=[h.out], translate_names=False)
    assert h.time_field in arr.dtype.names
    assert h.out.voltage_field in arr.dtype.names
    # time + 1 voltage field
    assert len(arr.dtype.names) == 2
    # First column should be time
    assert arr.dtype.names[0] == h.time_field


def test_write_csv_with_time_axis(tmp_path):
    """Test write_csv() includes time axis for transient simulation, raw names."""
    import csv
    tb = lib_test.VpwlTb()
    h = tb.sim_tran_batch
    assert h.time_field is not None
    outfile = tmp_path / "sim_tran.csv"
    h.write_csv(outfile, include=[h.out], translate_names=False)
    with open(outfile) as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    assert h.time_field in header
    assert h.out.voltage_field in header
    # time + 1 voltage field
    assert len(header) == 2
    # First column should be time
    assert header[0] == h.time_field


def test_to_numpy_ac_complex():
    """Test to_numpy() with AC simulation (complex values), raw names."""
    import numpy as np
    tb = lib_test.AcRC()
    h = tb.sim_ac_batch
    assert h.freq_field is not None
    arr = h.to_numpy(include=[h.out], translate_names=False)
    # freq + 1 voltage field
    assert len(arr.dtype.names) == 2
    assert arr.dtype.names[0] == h.freq_field
    assert h.out.voltage_field in arr.dtype.names
    # AC data should be complex
    assert np.iscomplexobj(arr[h.out.voltage_field])
    # Verify data integrity
    assert len(arr) == len(h.sim_data)
    for i in range(min(5, len(arr))):
        assert arr[h.out.voltage_field][i] == h.out.voltage[i]


def test_to_numpy_dc_sweep():
    """Test to_numpy() with DC sweep simulation, raw names."""
    import numpy as np
    tb = lib_test.InvTb()
    h = tb.sim_dc_batch
    assert h.sim_type == SimType.DCSWEEP
    assert h.sweep_field is not None
    arr = h.to_numpy(include=[h.i, h.o], translate_names=False)
    # sweep + 2 voltage fields
    assert len(arr.dtype.names) == 3
    assert arr.dtype.names[0] == h.sweep_field
    assert h.i.voltage_field in arr.dtype.names
    assert h.o.voltage_field in arr.dtype.names
    # Verify data integrity
    assert len(arr) == len(h.sim_data)
    for i in range(min(5, len(arr))):
        assert arr[h.i.voltage_field][i] == h.i.voltage[i]
        assert arr[h.o.voltage_field][i] == h.o.voltage[i]


def test_translate_names():
    """Test translate_names=True converts ngspice names to ORDB paths."""
    import numpy as np
    tb = lib_test.ResdivHierTb()
    h = tb.sim_op_batch

    # Voltage and current translation
    arr = h.to_numpy(include=[h.r, h.I2.p])
    assert 'r.voltage' in arr.dtype.names
    assert 'I2.p.current' in arr.dtype.names
    assert h.r.voltage_field not in arr.dtype.names
    assert arr['r.voltage'][0] == h.r.voltage[0]
    assert arr['I2.p.current'][0] == h.I2.p.current[0]

    # Nested hierarchy paths
    arr = h.to_numpy(include=[h.I0.I0.I0.p])
    assert 'I0.I0.I0.p.current' in arr.dtype.names


def test_translate_names_axes(tmp_path):
    """Test that independent variable axes are translated correctly."""
    import csv
    import numpy as np

    # Transient: time axis
    h_tran = lib_test.VpwlTb().sim_tran_batch
    arr = h_tran.to_numpy(include=[h_tran.out])
    assert arr.dtype.names[0] == 'time'
    assert 'out.voltage' in arr.dtype.names

    # AC: frequency axis
    h_ac = lib_test.AcRC().sim_ac_batch
    arr = h_ac.to_numpy(include=[h_ac.out])
    assert arr.dtype.names[0] == 'frequency'

    # DC sweep: sweep axis
    h_sweep = lib_test.InvTb().sim_dc_batch
    arr = h_sweep.to_numpy(include=[h_sweep.i])
    assert arr.dtype.names[0] == 'sweep'

    # write_csv uses same translation
    outfile = tmp_path / "sim.csv"
    h_tran.write_csv(outfile, include=[h_tran.out])
    with open(outfile) as f:
        header = next(csv.reader(f))
    assert header == ['time', 'out.voltage']

def test_bode_helpers():
    """Test the pure mag_db/phase_deg helpers, including phase unwrap."""
    from ordec.sim import mag_db, phase_deg

    assert mag_db([10, 1, 0.1]) == pytest.approx([20.0, 0.0, -20.0])
    assert mag_db([0]) == pytest.approx([-6000.0])  # clamped to floor

    # Response circling through -170deg -> +170deg: raw phase jumps by
    # +340deg; unwrap turns that into a continuous -190deg.
    vals = [
        complex(math.cos(math.radians(a)), math.sin(math.radians(a)))
        for a in (0, -90, -170, 170)
    ]
    assert phase_deg(vals, unwrap=False) == pytest.approx([0, -90, -170, 170])
    assert phase_deg(vals) == pytest.approx([0, -90, -170, -190])


def test_bode_plot():
    """Test Bode report building from AC results, via the Report method
    (which lazily wraps ordec.sim.helpers.bode_plot)."""
    import cmath
    from ordec.core.schema import Report

    h = lib_test.AcRC().sim_ac_batch
    report = Report()
    report.bode_plot(h.inp, h.out)
    _, data = report.webdata()

    mag, phase = data["elements"]
    assert mag["ylabel"] == "Magnitude (dB)"
    assert phase["ylabel"] == "Phase (°)"
    for plot in (mag, phase):
        assert plot["element_type"] == "plot2d"
        assert plot["xscale"] == "log"
        assert plot["x"] == [f.real for f in h.freq]
        assert [s["name"] for s in plot["series"]] == ["inp", "out"]
    # Both plots share one PlotGroup for x-axis synchronization.
    assert mag["plot_group"] == phase["plot_group"] is not None

    out_v = list(h.out.voltage)
    assert mag["series"][1]["values"] == pytest.approx(
        [20 * math.log10(abs(v)) for v in out_v])
    assert phase["series"][1]["values"] == pytest.approx(
        [math.degrees(cmath.phase(v)) for v in out_v])


def test_bode_plot_ref():
    """Test that ref= divides all signals by the reference signal."""
    from ordec.core.schema import Report
    from ordec.sim import bode_plot

    h = lib_test.AcRC().sim_ac_batch
    report = Report()
    bode_plot(report, h.out, ref=h.inp)
    _, data = report.webdata()

    mag = data["elements"][0]
    expected = [
        20 * math.log10(abs(v / r))
        for v, r in zip(h.out.voltage, h.inp.voltage)
    ]
    assert mag["series"][0]["values"] == pytest.approx(expected)


def test_bode_plot_errors():
    from ordec.core.schema import Report
    from ordec.sim import bode_plot

    h_ac = lib_test.AcRC().sim_ac_batch
    report = Report()
    with pytest.raises(ValueError, match="at least one signal"):
        bode_plot(report)
    with pytest.raises(TypeError, match="SimNet or SimPin"):
        bode_plot(report, ("raw", [1.0, 2.0]))
    # Signals from two different SimHierarchies must be rejected.
    h_other = lib_test.SineRL().sim_ac_batch
    with pytest.raises(ValueError, match="same SimHierarchy"):
        bode_plot(report, h_ac.out, h_other.out)
    # Non-AC results have no frequency axis.
    h_tran = lib_test.VpwlTb().sim_tran_batch
    with pytest.raises(ValueError, match="no AC results"):
        bode_plot(report, h_tran.out)
