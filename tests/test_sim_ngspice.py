# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
import pytest
from ordec.sim.ngspice import Ngspice, CommandRecorder, ngspice_batch
from ordec.sim.ngspice import NgspiceError, NgspiceFatalError

def test_ngspice_illegal_netlist_1():
    with Ngspice.launch() as sim:
        with pytest.raises(NgspiceFatalError, match=".*Error: Mismatch of .subckt ... .ends statements!.*"):
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


def test_command_recorder():
    rec = CommandRecorder()
    rec.command("set filetype=binary")
    rec.command("source /some/path")
    assert rec.commands == ["set filetype=binary", "source /some/path"]
    assert rec.command("echo test") == ""


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
