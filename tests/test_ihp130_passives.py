# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from ordec.core import ParameterError
from ordec.lib import ihp130
from .lib.ihp130_passives import ResDevice, CmimDevice


@pytest.mark.parametrize("kind", ["rsil", "rppd", "rhigh"])
def test_resistor_lvs_clean(kind):
    cell = ResDevice(kind=kind)
    assert ihp130.run_lvs(cell.layout, cell.symbol, use_tempdir=True)


@pytest.mark.parametrize("kind", ["rsil", "rppd", "rhigh"])
def test_resistor_meander_layout_rejected(kind):
    with pytest.raises(ParameterError, match="b != 0 not supported for layout."):
        ResDevice(kind=kind, l="1.0u", w="0.5u", b=2, ps="0.5u").layout


@pytest.mark.parametrize("kind", ["rsil", "rppd", "rhigh"])
def test_resistor_drc_clean(kind):
    cell = ResDevice(kind=kind)
    res = ihp130.run_drc(cell.layout, use_tempdir=True)
    assert res.summary() == {}


def test_cmim_lvs_clean():
    cell = CmimDevice()
    assert ihp130.run_lvs(cell.layout, cell.symbol, use_tempdir=True)


def test_cmim_drc_clean():
    cell = CmimDevice()
    res = ihp130.run_drc(cell.layout, use_tempdir=True)
    assert res.summary() == {}
