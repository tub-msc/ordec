# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
DRC + LVS of the abutted series NMOS pair in IHP130 (moved out of the
former test_ihp130_inv.py, whose generic tests live in test_pdks.py).
"""

import ordec.importer

from .lib.ihp130_nmos_series import SeriesNmos


def test_series_nmos_drc_clean():
    """The uncontacted source/drain needs no Activ of its own to pass DRC."""
    assert SeriesNmos().drc.summary() == {}


def test_series_nmos_lvs_clean():
    """The abutted pair matches its two-transistor series schematic, with the
    shared bare diffusion as the internal source/drain node."""
    assert SeriesNmos().lvs.clean()
