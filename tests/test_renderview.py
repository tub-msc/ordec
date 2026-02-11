# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Comparing symbol + schematic images to reference images.

To copy test results into the renderview_ref directory, run pytest with
--update-ref option.
"""

import pytest
from pathlib import Path
import importlib.resources
from dataclasses import dataclass, field
from typing import Callable
from importlib import import_module

import ordec.importer
from ordec import lib
from ordec.render import render
from .lib import schematics as libtest

@dataclass
class RenderViewTestcase:
    viewgen: Callable
    ref_file: Path
    render_opts: dict = field(default_factory=dict)

def testcase(*args, marks=None, **kwargs):
    obj = RenderViewTestcase(*args, **kwargs)
    if marks is None:
        return obj
    else:
        return pytest.param(obj, marks=marks)
testcase.__test__ = False

def ord_lambda(name, cell, view, **kwargs):
    """
    This function makes it possible to test the views of cells without having
    to import them on the level of the test module.

    This ensures that errors raised by the ORD ord1 during import of an .ord
    file do not break the entire test module.
    """
    return lambda: getattr(getattr(import_module(name), cell)(**kwargs), view)

refdir = importlib.resources.files("tests.renderview_ref")

# Use the following format for ref_file: TESTGROUP_NAME_{sch|sym}.svg
testdata = [
    # Test cells from lib.base and lib.generic_mos
    # --------------------------------------------

    testcase(lambda: lib.Inv().schematic,
        refdir / "lib_inverter_sch.svg"),
    testcase(lambda: lib.Inv().symbol,
        refdir / "lib_inverter_sym.svg"),
    testcase(lambda: lib.Ringosc().schematic,
        refdir / "lib_ringosc_sch.svg"),
    testcase(lambda: lib.And2().symbol,
        refdir / "lib_and2_sym.svg"),
    testcase(lambda: lib.Or2().symbol,
        refdir / "lib_or2_sym.svg"),

    # Test cells from tests.lib.schematics
    # ------------------------------------

    testcase(lambda: libtest.RotateTest().schematic,
        refdir / "libtest_rotatetest_sch.svg"),
    testcase(lambda: libtest.PortAlignTest().schematic,
        refdir / "libtest_portaligntest_sch.svg"),
    testcase(lambda: libtest.TapAlignTest().schematic,
        refdir / "libtest_tapaligntest_sch.svg"),
    testcase(lambda: libtest.MultibitReg_Arrays(bits=5).symbol,
        refdir / "libtest_multibitreg_arrays5_sym.svg"),
    testcase(lambda: libtest.MultibitReg_Arrays(bits=5).schematic,
        refdir / "libtest_multibitreg_arrays5_sch.svg"),
    testcase(lambda: libtest.MultibitReg_Arrays(bits=32).symbol,
        refdir / "libtest_multibitreg_arrays32_sym.svg"),
    testcase(lambda: libtest.MultibitReg_ArrayOfStructs(bits=5).symbol,
        refdir / "libtest_multibitreg_arrayofstructs5_sym.svg"),
    testcase(lambda: libtest.MultibitReg_StructOfArrays(bits=5).symbol,
        refdir / "libtest_multibitreg_structofarrays5_sym.svg"),
    testcase(lambda: libtest.TestNmosInv(variant='default', add_conn_points=True, add_terminal_taps=False).schematic,
        refdir / "libtest_testnmosinv.svg"),
    testcase(lambda: libtest.TestNmosInv(variant='no_wiring', add_conn_points=False, add_terminal_taps=True).schematic,
        refdir / "libtest_testnmosinv_nowiring.svg"),
    
    # Test cells from lib.examples
    # ----------------------------

    testcase(ord_lambda('ordec.lib.examples.diffpair', 'DiffPair', 'schematic'),
        refdir / "examples_diffpair_sch.svg"),
    testcase(ord_lambda('ordec.lib.examples.diffpair', 'DiffPairTb', 'schematic'),
        refdir / "examples_diffpairtb_sch.svg"),
    
    # Test cells from tests.lib.ord1
    # ------------------------------

    testcase(ord_lambda('tests.lib.ord1.d_ff_soc', 'D_flip_flop', 'schematic'),
        refdir / "ord1test_dffsoc_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.d_flip_flop', 'D_flip_flop', 'schematic'),
        refdir / "ord1test_dflipflop_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.d_latch', 'D_latch', 'schematic'),
        refdir / "ord1test_dlatch_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.d_latch_schem_check', 'D_latch', 'schematic'),
        refdir / "ord1test_dlatch_schem_check_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.d_latch_soc', 'D_latch', 'schematic'),
        refdir / "ord1test_dlatchsoc_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.inv_all_features', 'Inv', 'schematic'),
        refdir / "ord1test_invallfeatures_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.inv_origin_centered', 'Inv', 'schematic'),
             refdir / "ord1test_invorigincentered_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.inv_for_loop', 'Inv', 'schematic'),
        refdir / "ord1test_invforloop_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.inv_liop', 'Inv', 'schematic'),
        refdir / "ord1test_invliop_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.inv_structured', 'Inv', 'schematic'),
        refdir / "ord1test_invstructured_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.mux2_structured', 'Mux2', 'schematic'),
        refdir / "ord1test_mux2structured_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.nand', 'Nand', 'schematic'),
        refdir / "ord1test_nand_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.nand', 'Nand', 'symbol'),
        refdir / "ord1test_nand_sym.svg"),
    testcase(ord_lambda('tests.lib.ord1.nand_structured', 'Nand', 'schematic'),
        refdir / "ord1test_nandstructured_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.net_definition', 'Inv', 'schematic'),
        refdir / "ord1test_netdefinition_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.resdiv_flat_tb', 'ResdivFlatTb', 'schematic'),
        refdir / "ord1test_resdivflattb_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.ringosc', 'Ringosc', 'schematic'),
        refdir / "ord1test_ringosc_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.ringosc_liop', 'Ringosc', 'schematic'),
        refdir / "ord1test_ringoscliop_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.ringosc_structured', 'Ringosc', 'schematic'),
        refdir / "ord1test_ringoscstructured_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.sr_flip_flop', 'SR_flip_flop', 'schematic'),
        refdir / "ord1test_srflipflop_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.strongarm', 'Strongarm', 'schematic'),
        refdir / "ord1test_strongarm_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.strongarm_liop', 'Strongarm', 'schematic'),
        refdir / "ord1test_strongarmliop_sch.svg"),
    testcase(ord_lambda('tests.lib.ord1.strongarm_structured', 'Strongarm', 'schematic'),
        refdir / "ord1test_strongarmstructured_sch.svg"),

    # Test cells from tests.lib.ord2
    # ------------------------------

    testcase(ord_lambda('tests.lib.ord2.inverter', 'Inv', 'schematic'),
        refdir / "ord2test_inverter_sch.svg"),
    testcase(ord_lambda('tests.lib.ord2.inverter_constraints', 'Inv', 'schematic'),
        refdir / "ord2test_inverter_constraints_sch.svg"),
    testcase(ord_lambda('tests.lib.ord2.nand', 'Nand', 'schematic'),
        refdir / "ord2test_nand_sch.svg"),
    testcase(ord_lambda('tests.lib.ord2.reg', 'MultibitReg_Arrays', 'schematic', bits=3),
        refdir / "ord2test_reg_sch.svg"),
    testcase(ord_lambda('tests.lib.ord2.nmux', 'Nto1', 'schematic', N=8),
        refdir / "ord2test_nmux_sch.svg"),
]

@pytest.mark.parametrize("testcase", testdata, ids=lambda t: t.ref_file.with_suffix("").name)
def test_renderview(testcase, tmp_path, update_ref):
    view = testcase.viewgen()

    render_opts = dict(
        include_nids=False, # Do not include nids to make the output independent of nids.
        enable_grid=False, # Disable grid to make the files smaller.
        enable_css=True # To be able to inspect the SVG files for correctness, we need to include the proper CSS.
    ) | testcase.render_opts 

    svg = render(view, **render_opts).svg()
    (tmp_path / testcase.ref_file.name).write_bytes(svg) # Write output to tmp_path for user.

    if update_ref:
        testcase.ref_file.write_bytes(svg)
    
    svg_ref = testcase.ref_file.read_bytes()

    # Pytest is better at string diffs than at byte diffs:
    assert svg.decode('ascii') == svg_ref.decode('ascii')
