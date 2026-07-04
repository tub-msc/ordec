# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
IHP SG13G2 standard cells, loaded straight from the PDK reference files instead
of being reimplemented by hand:

- symbols    <- LEF   (correct pin directions)
- layouts    <- GDS   (sign-off-clean foundry geometry)
- schematics <- SPICE (transistor-level netlists)

The combined library is exposed as ``extlib``; e.g. ``extlib["sg13g2_inv_1"]``
gives a cell with ``.symbol``, ``.schematic`` and ``.layout`` views. It is
built lazily on first access (PEP 562 module ``__getattr__``), so merely
importing this module does not require the PDK environment variable
``ORDEC_PDK_IHP_SG13G2``; accessing ``extlib`` without it raises the clear
error from :func:`ordec.lib.ihp130.pdk`.

Place-and-route for these cells lives in :mod:`ordec.layout.ihp_pnr`
(``place_and_route``, ``lef_pin_rects``), the PDK binding of the generic
engine.
"""

import functools

from ordec.extlibrary import ExtLibrary
from ordec.lib import ihp130


@functools.cache
def stdcell_lib() -> ExtLibrary:
    """Build (once) and return the combined sg13g2 standard-cell library."""
    root = ihp130.pdk().root / "libs.ref/sg13g2_stdcell"
    lib = ExtLibrary()
    # read_lef first so its symbols (proper pin directions) win over read_spice's.
    # The sg13_lv_nmos/pmos -> Nmos/Pmos device map is shared from ihp130.
    lib.read_lef(root / "lef/sg13g2_stdcell.lef")
    lib.read_gds(root / "gds/sg13g2_stdcell.gds", ihp130.SG13G2().layers)
    lib.read_spice(root / "spice/sg13g2_stdcell.spice",
        device_map=ihp130.device_map)
    return lib


def __getattr__(name):
    if name == "extlib":
        return stdcell_lib()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
