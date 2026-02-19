# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
import pytest
from ordec.sim.ngspice import Ngspice
from ordec.sim.ngspice_common import NgspiceError, NgspiceFatalError
from ordec.core.simarray import Quantity

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

    def voltages(op):
        return {name:value for qty, name, subname, value in op if qty==Quantity.VOLTAGE}

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
