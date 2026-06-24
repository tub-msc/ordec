# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Generalization tests for the place-and-route engine (ordec/examples/sar_adc/
pnr.py). SarLogic exercises one netlist; these synthetic cells exercise shapes
unlike it -- a long linear inverter chain and a register array with high
fan-out clock/reset -- so a clean result is evidence the engine generalises
rather than being tuned to SarLogic. (These caught a real bug: a supply whose
boustrophedon rows share a single rail got no strap, leaving its port floating.)
"""

import pytest
import ordec.importer
from ordec.lib import ihp130
from ordec.examples.sar_adc import pnr_test_cells as ptc


@pytest.mark.parametrize("n", [4, 8, 16])
def test_invchain_pnr_drc_lvs(n):
    c = ptc.InvChain(n=n)
    assert ihp130.run_drc(c.layout, use_tempdir=True).summary() == {}
    assert ihp130.run_lvs(c.layout, c.symbol, use_tempdir=True)


@pytest.mark.parametrize("n", [4, 8])
def test_dffarray_pnr_drc_lvs(n):
    c = ptc.DffArray(n=n)
    assert ihp130.run_drc(c.layout, use_tempdir=True).summary() == {}
    assert ihp130.run_lvs(c.layout, c.symbol, use_tempdir=True)
