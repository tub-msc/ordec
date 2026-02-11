# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.core import *
from ordec.sim.sim_hierarchy import SimHierarchy, build_hier_schematic
from ordec.lib.base import Gnd, Res
from ordec.core.schema import SimHierarchySubcursor
from .lib import sim as lib_test

def my_simhier():
    schematic = lib_test.ResdivHierTb().schematic
    simhier = SimHierarchy()
    build_hier_schematic(simhier, schematic)
    return simhier

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
    assert simnet_I0_I2_t.eref == lib_test.ResdivHier2(r=R(100)).schematic.t
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
    assert simnet_I0_I2_I1_m.eref == Res(r=R(100)).symbol.m
    assert simnet_I0_I2_I1_m.parent_inst == simhier.I0.sub2.I2.I1
    assert simnet_I0_I2_I1_m.full_path_list() == ['I0', 'sub2', 'I2', 'I1', 'm']
