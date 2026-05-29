# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from ordec.core import ParameterError
from ordec.lib import ihp130
from .lib.thinwrap import thin_wrapper_cell


@pytest.mark.parametrize("kind", [ihp130.Rsil, ihp130.Rppd, ihp130.Rhigh])
def test_resistor_lvs_clean(kind):
    cell = thin_wrapper_cell(kind())
    assert ihp130.run_lvs(cell.layout, cell.symbol, use_tempdir=True)


@pytest.mark.parametrize("kind", [ihp130.Rsil, ihp130.Rppd, ihp130.Rhigh])
def test_resistor_meander_layout_rejected(kind):
    with pytest.raises(ParameterError, match="b != 0 not supported for layout."):
        thin_wrapper_cell(kind(l="1.0u", w="0.5u", b=2, ps="0.5u")).layout


@pytest.mark.parametrize("kind", [ihp130.Rsil, ihp130.Rppd, ihp130.Rhigh])
def test_resistor_drc_clean(kind):
    cell = thin_wrapper_cell(kind())
    res = ihp130.run_drc(cell.layout, use_tempdir=True)
    assert res.summary() == {}


def test_cmim_lvs_clean():
    cell = thin_wrapper_cell(ihp130.Cmim())
    assert ihp130.run_lvs(cell.layout, cell.symbol, use_tempdir=True)


def test_cmim_drc_clean():
    cell = thin_wrapper_cell(ihp130.Cmim())
    res = ihp130.run_drc(cell.layout, use_tempdir=True)
    assert res.summary() == {}
