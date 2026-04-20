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
    
    # Test cells from tests.lib.ord
    # ------------------------------

    testcase(ord_lambda('tests.lib.ord.d_ff_soc', 'D_flip_flop', 'schematic'),
        refdir / "ordtest_dffsoc_sch.svg"),
    testcase(ord_lambda('tests.lib.ord.d_flip_flop', 'D_flip_flop', 'schematic'),
        refdir / "ordtest_dflipflop_sch.svg"),
    testcase(ord_lambda('tests.lib.ord.d_latch', 'D_latch', 'schematic'),
        refdir / "ordtest_dlatch_sch.svg"),
    testcase(ord_lambda('tests.lib.ord.d_latch_schem_check', 'D_latch', 'schematic'),
        refdir / "ordtest_dlatch_schem_check_sch.svg"),
    testcase(ord_lambda('tests.lib.ord.d_latch_soc', 'D_latch', 'schematic'),
        refdir / "ordtest_dlatchsoc_sch.svg"),
    testcase(ord_lambda('tests.lib.ord.inverter', 'Inv', 'schematic'),
        refdir / "ordtest_inverter_sch.svg"),
    testcase(ord_lambda('tests.lib.ord.inverter_constraints', 'Inv', 'schematic'),
        refdir / "ordtest_inverter_constraints_sch.svg"),
    testcase(ord_lambda('tests.lib.ord.nand', 'Nand', 'schematic'),
        refdir / "ordtest_nand_sch.svg"),
    testcase(ord_lambda('tests.lib.ord.reg', 'MultibitReg_Arrays', 'schematic', bits=3),
        refdir / "ordtest_reg_sch.svg"),
    testcase(ord_lambda('tests.lib.ord.nmux', 'Nto1', 'schematic', N=8),
        refdir / "ordtest_nmux_sch.svg"),
    testcase(ord_lambda('tests.lib.ord.ringosc', 'Ringosc', 'schematic'),
        refdir / "ordtest_ringosc_migrated_sch.svg"),
    testcase(ord_lambda('tests.lib.ord.strongarm', 'Strongarm', 'schematic'),
        refdir / "ordtest_strongarm_sch.svg"),
]

@pytest.mark.parametrize("testcase", testdata, ids=lambda t: t.ref_file.with_suffix("").name)
def test_renderview(testcase, tmp_path, update_ref):
    view = testcase.viewgen()

    render_opts = dict(
        include_nids=False, # Do not include nids to make the output independent of nids.
        enable_grid=False, # Disable grid to make the files smaller.
        enable_css=False # CSS is tested via web/src/schematic.css; use add_style.py to re-inject for visual inspection.
    ) | testcase.render_opts 

    svg = view.render(**render_opts).svg()
    (tmp_path / testcase.ref_file.name).write_bytes(svg) # Write output to tmp_path for user.

    if update_ref:
        testcase.ref_file.write_bytes(svg)
    
    svg_ref = testcase.ref_file.read_bytes()

    # Pytest is better at string diffs than at byte diffs:
    assert svg.decode('ascii') == svg_ref.decode('ascii')
