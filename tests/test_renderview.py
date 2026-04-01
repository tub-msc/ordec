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
from ordec.lib import generic_mos
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

    This ensures that errors raised during import of an .ord file do not break
    the entire test module.
    """
    return lambda: getattr(getattr(import_module(name), cell)(**kwargs), view)

refdir = importlib.resources.files("tests.renderview_ref")

# Use the following format for ref_file: TESTGROUP_NAME_{sch|sym}.svg
testdata = [
    # Test cells from lib.base and lib.generic_mos
    # --------------------------------------------

    testcase(lambda: generic_mos.Inv().schematic,
        refdir / "lib_inverter_sch.svg"),
    testcase(lambda: generic_mos.Inv().symbol,
        refdir / "lib_inverter_sym.svg"),
    testcase(lambda: generic_mos.Ringosc().schematic,
        refdir / "lib_ringosc_sch.svg"),
    testcase(lambda: generic_mos.And2().symbol,
        refdir / "lib_and2_sym.svg"),
    testcase(lambda: generic_mos.Or2().symbol,
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
    testcase(lambda: libtest.NetNamingTest().schematic,
        refdir / "libtest_netnamingtest_sch.svg"),
    
    # Test cells from ordec.examples
    # ----------------------------

    testcase(ord_lambda('ordec.examples.diffpair', 'DiffPair', 'schematic'),
        refdir / "examples_diffpair_sch.svg"),
    testcase(ord_lambda('ordec.examples.diffpair', 'DiffPairTb', 'schematic'),
        refdir / "examples_diffpairtb_sch.svg"),
    
    # Test cells from tests.lib.ord2
    # ------------------------------

    testcase(ord_lambda('tests.lib.ord2.d_ff_soc', 'D_flip_flop', 'schematic'),
        refdir / "ord2test_dffsoc_sch.svg"),
    testcase(ord_lambda('tests.lib.ord2.d_flip_flop', 'D_flip_flop', 'schematic'),
        refdir / "ord2test_dflipflop_sch.svg"),
    testcase(ord_lambda('tests.lib.ord2.d_latch', 'D_latch', 'schematic'),
        refdir / "ord2test_dlatch_sch.svg"),
    testcase(ord_lambda('tests.lib.ord2.d_latch_schem_check', 'D_latch', 'schematic'),
        refdir / "ord2test_dlatch_schem_check_sch.svg"),
    testcase(ord_lambda('tests.lib.ord2.d_latch_soc', 'D_latch', 'schematic'),
        refdir / "ord2test_dlatchsoc_sch.svg"),
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
    testcase(ord_lambda('tests.lib.ord2.ringosc', 'Ringosc', 'schematic'),
        refdir / "ord2test_ringosc_migrated_sch.svg"),
    testcase(ord_lambda('tests.lib.ord2.strongarm', 'Strongarm', 'schematic'),
        refdir / "ord2test_strongarm_sch.svg"),
]

@pytest.mark.parametrize("testcase", testdata, ids=lambda t: t.ref_file.with_suffix("").name)
def test_renderview(testcase, tmp_path, update_ref):
    view = testcase.viewgen()

    render_opts = dict(
        include_nids=False, # Do not include nids to make the output independent of nids.
        enable_grid=False, # Disable grid to make the files smaller.
        enable_css=False # CSS is tested via web/src/schematic.css; use add_style.py to re-inject for visual inspection.
    ) | testcase.render_opts 

    svg = render(view, **render_opts).svg()
    (tmp_path / testcase.ref_file.name).write_bytes(svg) # Write output to tmp_path for user.

    if update_ref:
        testcase.ref_file.write_bytes(svg)
    
    svg_ref = testcase.ref_file.read_bytes()

    # Pytest is better at string diffs than at byte diffs:
    assert svg.decode('ascii') == svg_ref.decode('ascii')
