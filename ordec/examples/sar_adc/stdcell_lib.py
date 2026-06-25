# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
IHP SG13G2 standard cells, loaded straight from the PDK reference files instead
of being reimplemented by hand:

- symbols    <- LEF   (correct pin directions)
- layouts    <- GDS   (sign-off-clean foundry geometry)
- schematics <- SPICE (transistor-level netlists)

The combined library is exposed as ``extlib``; e.g. ``extlib["sg13g2_inv_1"]``
gives a cell with ``.symbol``, ``.schematic`` and ``.layout`` views. The SAR ADC
schematics alias these directly (``Inv = extlib["sg13g2_inv_1"]`` etc.), so the
design instantiates real foundry cells with their native pin names.

Place-and-route for these cells lives in :mod:`ordec.layout.ihp_pnr`
(``place_and_route``, ``lef_pin_rects``), the PDK binding of the generic engine.
"""

import os
from pathlib import Path

from ordec.core import *
from ordec.extlibrary import ExtLibrary
from ordec.lib import ihp130

_root = Path(os.environ["ORDEC_PDK_IHP_SG13G2"]) / "libs.ref/sg13g2_stdcell"

# read_lef first so its symbols (proper pin directions) win over read_spice's.
# The sg13_lv_nmos/pmos -> Nmos/Pmos device map is shared from ihp130.
extlib = ExtLibrary()
extlib.read_lef(_root / "lef/sg13g2_stdcell.lef")
extlib.read_gds(_root / "gds/sg13g2_stdcell.gds", ihp130.SG13G2().layers)
extlib.read_spice(_root / "spice/sg13g2_stdcell.spice", device_map=ihp130.device_map)
