# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
import pytest
from ordec.sim2.ngspice import Ngspice, NgspiceError, NgspiceFatalError, Netlister
from ordec import Rational as R
from ordec.lib import test as lib_test

def test_ngspice_illegal_netlist_1():
    with Ngspice.launch(debug=True) as sim:
        with pytest.raises(NgspiceFatalError, match=".*Error: Mismatch of .subckt ... .ends statements!.*"):
            sim.load_netlist(".title test\n.ends\n.end")

def test_ngspice_illegal_netlist_2():
    with Ngspice.launch(debug=True) as sim:
        with pytest.raises(NgspiceError, match=".*unknown subckt: x0 1 2 3 invalid.*"):
            sim.load_netlist(".title test\nx0 1 2 3 invalid\n.end")

@pytest.mark.skip(reason="Ngspice seems to hang here.")
def test_ngspice_illegal_netlist_3():
    broken_netlist = """.title test
    MN0 d 0 0 0 N1 w=hello
    .end
    """
    with Ngspice.launch(debug=True) as sim:
        sim.load_netlist(broken_netlist)

# TODO: Not all problems seem to currently be caught and raises in Python as exception at the moment (see sky130 with Rational params).

def test_ngspice_version():
    with Ngspice.launch(debug=True) as sim:
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

    def voltages(op):
        return {name:value for vtype, name, subname, value in op if vtype=='voltage'}

    # Default behavior: net 'gnd' is automatically ground.
    with Ngspice.launch(debug=True) as sim:
        sim.load_netlist(netlist_voltage_divider, no_auto_gnd=False)
        op = voltages(sim.op())
    assert op['a'] == 1.5

    # Altered no_auto_gnd behavior
    with Ngspice.launch(debug=True) as sim:
        sim.load_netlist(netlist_voltage_divider, no_auto_gnd=True)
        op = voltages(sim.op())
    assert op['a'] == 2.0
    assert op['gnd'] == 1.0

def test_sim_dc_flat():
    h = lib_test.ResdivFlatTb().sim_dc
    assert h.a.dc_voltage == 0.3333333
    assert h.b.dc_voltage == 0.6666667

def test_sim_dc_hier():
    h = lib_test.ResdivHierTb().sim_dc
    assert h.r.dc_voltage == 0.3589744
    assert h.I0.I1.m.dc_voltage == 0.5897436

def test_generic_mos_netlister():
    nl = Netlister()
    nl.netlist_hier(lib_test.NmosSourceFollowerTb().schematic)
    netlist = nl.out()

    assert netlist.count('.model nmosgeneric NMOS level=1') == 1
    assert netlist.count('.model pmosgeneric PMOS level=1') == 1

def test_generic_mos_nmos_sourcefollower():
    assert lib_test.NmosSourceFollowerTb(vin=R(2)).sim_dc.o.dc_voltage == 0.6837722
    assert lib_test.NmosSourceFollowerTb(vin=R(3)).sim_dc.o.dc_voltage == 1.683772

def test_generic_mos_inv():
    assert lib_test.InvTb(vin=R(0)).sim_dc.o.dc_voltage  == 5.0
    assert lib_test.InvTb(vin=R('2.5')).sim_dc.o.dc_voltage == 2.5
    assert lib_test.InvTb(vin=R(5)).sim_dc.o.dc_voltage == 3.13125e-08
