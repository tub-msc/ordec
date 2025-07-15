# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Comparing symbol + schematic images to reference images.

To copy test results in as reference:

    cp /tmp/pytest-of-[username]/pytest-current/test_renderview*/*.svg [dir]/tests/renderview_ref
"""

import pytest
from pathlib import Path
import importlib.resources
from dataclasses import dataclass, field
from typing import Callable
from importlib import import_module

import ordec.importer
from ordec import lib, render
from ordec.lib import test as libtest
from ordec.base import Cell

@dataclass
class RenderViewTestcase:
    viewgen: Callable
    ref_file: Path
    render_opts: dict = field(default_factory=dict)

def testcase(*args, marks=None, **kwargs):
    obj = RenderViewTestcase(*args, **kwargs)
    if marks == None:
        return obj
    else:
        return pytest.param(obj, marks=marks)
testcase.__test__ = False

def ord_lambda(name, cell, view, **kwargs):
    """
    This function makes it possible to test the views of cells without having
    to import them on the level of the test module.

    This ensures that errors raised by the ORD parser during import of an .ord
    file do not break the entire test module.
    """
    return lambda: getattr(getattr(import_module(name, package='ordec'), cell)(**kwargs), view)

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

    # Test cells from lib.test
    # ------------------------

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

    testcase(ord_lambda('.lib.examples.diffpair', 'DiffPair', 'schematic'),
        refdir / "examples_diffpair_sch.svg"),
    testcase(ord_lambda('.lib.examples.diffpair', 'DiffPairTb', 'schematic'),
        refdir / "examples_diffpairtb_sch.svg"),
    
    # Test cells from lib.ord_test (previously ordec.parser.ord_files)
    # ----------------------------------------------------------------

    testcase(ord_lambda('.lib.ord_test.d_ff_soc', 'D_flip_flop', 'schematic'),
        refdir / "ordtest_dffsoc_sch.svg",
        marks=pytest.mark.xfail),
    testcase(ord_lambda('.lib.ord_test.d_flip_flop', 'D_flip_flop', 'schematic'),
        refdir / "ordtest_dflipflop_sch.svg",
        marks=pytest.mark.xfail),
    testcase(ord_lambda('.lib.ord_test.d_latch', 'D_latch', 'schematic'),
        refdir / "ordtest_dlatch_sch.svg",
        marks=pytest.mark.xfail),
    testcase(ord_lambda('.lib.ord_test.d_latch', 'D_latch', 'schematic'),
        refdir / "ordtest_dlatch_sch.svg",
        marks=pytest.mark.xfail),
    testcase(ord_lambda('.lib.ord_test.d_latch_soc', 'D_latch', 'schematic'),
        refdir / "ordtest_dlatchsoc_sch.svg",
        marks=pytest.mark.xfail),
    testcase(ord_lambda('.lib.ord_test.inv_all_features', 'Inv', 'schematic'),
        refdir / "ordtest_invallfeatures_sch.svg",
        marks=pytest.mark.xfail),
    testcase(ord_lambda('.lib.ord_test.inv_for_loop', 'Inv', 'schematic'),
        refdir / "ordtest_invforloop_sch.svg"),
    testcase(ord_lambda('.lib.ord_test.inv_liop', 'Inv', 'schematic'),
        refdir / "ordtest_invliop_sch.svg"),
    testcase(ord_lambda('.lib.ord_test.inv_structured', 'Inv', 'schematic'),
        refdir / "ordtest_invstructured_sch.svg"),
    testcase(ord_lambda('.lib.ord_test.mux2_structured', 'Mux2', 'schematic'),
        refdir / "ordtest_mux2structured_sch.svg"),
    testcase(ord_lambda('.lib.ord_test.nand', 'Nand', 'schematic'),
        refdir / "ordtest_nand_sch.svg"),
    testcase(ord_lambda('.lib.ord_test.nand', 'Nand', 'symbol'),
        refdir / "ordtest_nand_sym.svg"),
    testcase(ord_lambda('.lib.ord_test.nand_structured', 'Nand', 'schematic'),
        refdir / "ordtest_nandstructured_sch.svg"),
    testcase(ord_lambda('.lib.ord_test.net_definition', 'Inv', 'schematic'),
        refdir / "ordtest_netdefinition_sch.svg"),
    testcase(ord_lambda('.lib.ord_test.resdiv_flat_tb', 'ResdivFlatTb', 'schematic'),
        refdir / "ordtest_resdivflattb_sch.svg"),
    testcase(ord_lambda('.lib.ord_test.ringosc', 'Ringosc', 'schematic'),
        refdir / "ordtest_ringosc_sch.svg"),
    testcase(ord_lambda('.lib.ord_test.ringosc_liop', 'Ringosc', 'schematic'),
        refdir / "ordtest_ringoscliop_sch.svg"),
    testcase(ord_lambda('.lib.ord_test.ringosc_structured', 'Ringosc', 'schematic'),
        refdir / "ordtest_ringoscstructured_sch.svg"),
    testcase(ord_lambda('.lib.ord_test.sr_flip_flop', 'SR_flip_flop', 'schematic'),
        refdir / "ordtest_srflipflop_sch.svg",
        marks=pytest.mark.xfail),
    testcase(ord_lambda('.lib.ord_test.strongarm', 'Strongarm', 'schematic'),
        refdir / "ordtest_strongarm_sch.svg"),
    testcase(ord_lambda('.lib.ord_test.strongarm_liop', 'Strongarm', 'schematic'),
        refdir / "ordtest_strongarmliop_sch.svg"),
    testcase(ord_lambda('.lib.ord_test.strongarm_structured', 'Strongarm', 'schematic'),
        refdir / "ordtest_strongarmstructured_sch.svg"),
]

@pytest.mark.xfail
def test_ord_empty():
    from ordec.lib.ord_test import empty

@pytest.mark.xfail
def test_ord_empty2():
    from ordec.lib.ord_test import empty2

def test_ord_multicell():
    from ordec.lib.ord_test import multicell
    assert issubclass(multicell.Cell1, Cell)
    assert issubclass(multicell.Cell2, Cell)


@pytest.mark.parametrize("testcase", testdata, ids=lambda t: t.ref_file.with_suffix("").name)
def test_renderview(testcase, tmp_path):
    view = testcase.viewgen()

    render_opts = dict(
        include_nids=False, # Do not include nids to make the output independent of nids.
        enable_grid=False, # Disable grid to make the files smaller.
        enable_css=True # To be able to inspect the SVG files for correctness, we need to include the proper CSS.
    ) | testcase.render_opts 

    svg = render(view, **render_opts).svg()
    (tmp_path / testcase.ref_file.name).write_bytes(svg) # Write output to tmp_path for user.

    svg_ref = testcase.ref_file.read_bytes()

    # Pytest is better at string diffs than at byte diffs:
    assert svg.decode('ascii') == svg_ref.decode('ascii')
