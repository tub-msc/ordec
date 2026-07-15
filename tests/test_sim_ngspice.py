# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
import pytest
from ordec.sim.ngspice import Ngspice, ngspice_batch, NgspiceError
from ordec.sim.simulator import parse_signal_name


def test_parse_signal_name():
    """Test parsing of ngspice rawfile signal names."""
    # Voltage nodes
    assert parse_signal_name("v(vdd)") == ("vdd", None)
    assert parse_signal_name("v(xdut.a)") == ("xdut.a", None)

    # Internal model nodes (device type prefix stripped, # splits path/param)
    assert parse_signal_name("v(n.xdut.xm1.model#GP)") == ("xdut.xm1.model", "GP")
    assert parse_signal_name("v(m.xdut.mm1#internal)") == ("xdut.mm1", "internal")

    # Branch currents
    assert parse_signal_name("i(vgnd)") == ("vgnd", "branch")

    # Subcircuit port currents
    assert parse_signal_name("i(xdut:vss)") == ("xdut", "vss")

    # Device parameters
    assert parse_signal_name("@m.xdut.mm2[gm]") == ("xdut.mm2", "gm")
    assert parse_signal_name("i(@m.xdut.mm2[id])") == ("xdut.mm2", "id")
    assert parse_signal_name("v(@m.xi0.mm1[vdsat])") == ("xi0.mm1", "vdsat")

    # Unknown format
    assert parse_signal_name("time") == ("time", None)


def test_ngspice_illegal_netlist_1():
    with Ngspice.launch() as sim:
        with pytest.raises(NgspiceError, match=".*Error: Mismatch of .subckt ... .ends statements!.*"):
            sim.load_netlist(".title test\n.ends\n.end")

def test_ngspice_illegal_netlist_2():
    with Ngspice.launch() as sim:
        with pytest.raises(NgspiceError, match=".*unknown subckt: x0 1 2 3 invalid.*"):
            sim.load_netlist(".title test\nx0 1 2 3 invalid\n.end")

def test_ngspice_illegal_netlist_3():
    broken_netlist = """.title test
    MN0 d 0 0 0 N1 w=hello
    .end
    """
    with Ngspice.launch() as sim:
        with pytest.raises(NgspiceError, match=r"Undefined parameter \[hello\]"):
            sim.load_netlist(broken_netlist)

# TODO: Currently, not all problems seem to be caught and raised in Python as exception (see sky130 with Rational params).

def test_ngspice_version():
    with Ngspice.launch() as sim:
        version_str = sim.command("version -f")
        version_number = int(re.search(r"\*\* ngspice-([0-9]+)(.[0-9]+)?\s+", version_str).group(1))
        assert version_number >= 39

def test_ngspice_op_no_auto_gnd():
    netlist_voltage_divider = """.title voltage divider netlist
    V1 in 0 3
    R1 in a 1k
    R2 a gnd 1k
    R3 gnd 0 1k
    .end
    """

    def voltages(sim_array):
        return {f.fid[2:-1]: sim_array.column(f.fid)[0]
                for f in sim_array.fields
                if f.fid.startswith("v(") and f.fid.endswith(")")}

    # Default behavior: net 'gnd' is automatically ground.
    with Ngspice.launch() as sim:
        # Reset no_auto_gnd to ensure clean state
        sim.command("unset no_auto_gnd")
        sim.load_netlist(netlist_voltage_divider, no_auto_gnd=False)
        op = voltages(sim.op())
    assert op['a'] == 1.5

    # Altered no_auto_gnd behavior
    with Ngspice.launch() as sim:
        sim.load_netlist(netlist_voltage_divider, no_auto_gnd=True)
        op = voltages(sim.op())
    assert op['a'] == 2.0
    assert op['gnd'] == 1.0



def test_ngspice_batch_op():
    netlist = """.title batch op test
V1 in 0 3
R1 in a 1k
R2 a 0 1k
.op
.end
"""
    sa = ngspice_batch(netlist)
    voltages = {f.fid: sa.column(f.fid)[0]
                for f in sa.fields if f.fid.startswith("v(")}
    assert voltages['v(a)'] == pytest.approx(1.5, abs=1e-10)
    assert voltages['v(in)'] == pytest.approx(3.0, abs=1e-10)


def test_ngspice_batch_tran():
    netlist = """.title batch tran test
V1 in 0 1
R1 in out 1k
C1 out 0 1u
.tran 10u 5m
.end
"""
    sa = ngspice_batch(netlist)
    time_col = sa.column("time")
    assert len(time_col) > 1
    out_col = sa.column("v(out)")
    # RC charging: final value should approach 1V
    assert out_col[-1] == pytest.approx(1.0, abs=0.01)


def test_ngspice_batch_error():
    netlist = """.title bad netlist
x0 1 2 3 nonexistent_subckt
.op
.end
"""
    with pytest.raises(NgspiceError):
        ngspice_batch(netlist)

# -- RawfileMonitor + batch-mode progress/cancellation ------------------------

import struct
import threading
import time
from ordec.core import R
from ordec.core.genrun import GenRun, GenCancelled
from ordec.sim.ngspice import RawfileMonitor, format_time


@pytest.mark.parametrize("t, expected", [
    (0.0, "0s"),
    (2.5e-12, "2.5ps"),
    (1.2345e-9, "1.235ns"),      # rounded to 4 significant digits
    (0.0012345678901234, "1.235ms"),
    (0.09999999999999999, "100ms"),  # float noise must not leak through
    (1.5, "1.5s"),
    (3.0, "3s"),                 # no stray trailing "." from R
])
def test_format_time(t, expected):
    assert format_time(t) == expected


def write_synthetic_rawfile(path, n_vars=3, times=(), is_complex=False,
        truncate_tail=0):
    """Build a rawfile as ngspice batch mode would while still writing:
    header with 'No. Points: 0', then one row per entry in times."""
    flags = "complex" if is_complex else "real"
    header = ("Title: synthetic\nDate: today\nPlotname: Transient Analysis\n"
        f"Flags: {flags}\nNo. Variables: {n_vars}\nNo. Points: 0\n"
        "Variables:\n")
    header += "".join(f"\t{i}\tv{i}\tvoltage\n" for i in range(n_vars))
    header += "Binary:\n"
    data = b""
    val_size = 16 if is_complex else 8
    for t in times:
        row = struct.pack("<d", t) + b"\0" * (val_size - 8)
        row += b"\0" * (val_size * (n_vars - 1))
        data += row
    if truncate_tail:
        data = data[:-truncate_tail]
    path.write_bytes(header.encode("ascii") + data)


def test_rawfile_monitor(tmp_path):
    fn = tmp_path / "sim.raw"
    monitor = RawfileMonitor(fn, R(2))

    assert monitor.poll() is None  # no file yet

    fn.write_bytes(b"Title: incomplete hea")
    assert monitor.poll() is None  # header incomplete

    write_synthetic_rawfile(fn, times=())
    assert monitor.poll() is None  # header only, no rows yet

    write_synthetic_rawfile(fn, times=(0.5,))
    assert monitor.poll() == pytest.approx((0.25, 0.5))

    # Partial trailing row must not be interpreted as data.
    write_synthetic_rawfile(fn, times=(0.5, 1.0), truncate_tail=4)
    assert monitor.poll() == pytest.approx((0.25, 0.5))

    write_synthetic_rawfile(fn, times=(0.5, 1.0))
    assert monitor.poll() == pytest.approx((0.5, 1.0))

    # Fraction is clamped to 1.0 (tstart/roundoff can overshoot slightly).
    write_synthetic_rawfile(fn, times=(0.5, 1.0, 2.5))
    assert monitor.poll() == pytest.approx((1.0, 2.5))


def test_rawfile_monitor_complex(tmp_path):
    fn = tmp_path / "sim.raw"
    monitor = RawfileMonitor(fn, R(4))
    write_synthetic_rawfile(fn, times=(1.0, 2.0), is_complex=True)
    assert monitor.poll() == pytest.approx((0.5, 2.0))


def test_ngspice_batch_tran_progress():
    netlist = """.title batch tran progress test
V1 in 0 pulse(0 1 0 1u 1u 1m 2m)
R1 in out 1k
C1 out 0 1u
.tran 1u 500m
.end
"""
    events = []
    run = GenRun(on_progress=lambda s, f, d: events.append((s, f, d)))
    with run.activate():
        sa = ngspice_batch(netlist, tran_tstop=R('500m'))
    assert len(sa.column("time")) > 1
    tran = [(f, d) for s, f, d in events if s == "Transient simulation"]
    # Sampling is wall-clock-driven: assert invariants, not counts.
    assert len(tran) >= 1
    fractions = [f for f, d in tran]
    assert all(0.0 <= f <= 1.0 for f in fractions)
    assert fractions == sorted(fractions)
    # Every update carries the simulated time against the total.
    assert all(d.endswith(" / 500ms") for f, d in tran)


def test_ngspice_batch_cancel():
    netlist = """.title batch cancel test
V1 in 0 pulse(0 1 0 1u 1u 1m 2m)
R1 in out 1k
C1 out 0 1u
.tran 10n 10
.end
"""
    run = GenRun()
    result = []
    def worker():
        try:
            with run.activate():
                ngspice_batch(netlist, tran_tstop=R(10))
        except (GenCancelled, NgspiceError):
            result.append("cancelled")
    t = threading.Thread(target=worker)
    t.start()
    time.sleep(1.0)  # let ngspice get going
    run.request_cancel()
    t.join(timeout=10)
    assert not t.is_alive()
    assert result == ["cancelled"]
