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
"""

import functools
import os
from pathlib import Path

from ordec.core import *
from ordec.extlibrary import ExtLibrary
from ordec.schematic.spice_in import DeviceMapping
from ordec.lib import ihp130
from ordec.layout.pnr import place_and_route as _engine_pnr

_root = Path(os.environ["ORDEC_PDK_IHP_SG13G2"]) / "libs.ref/sg13g2_stdcell"

# IHP stdcell netlists are flat and use only sg13_lv_nmos/pmos (node order d g s b).
_MOS_PINS = ["d", "g", "s", "b"]
_device_map = {
    "sg13_lv_nmos": DeviceMapping(ihp130.Nmos, _MOS_PINS,
        real_params=("l", "w"), int_params=("ng", "m")),
    "sg13_lv_pmos": DeviceMapping(ihp130.Pmos, _MOS_PINS,
        real_params=("l", "w"), int_params=("ng", "m")),
}

# read_lef first so its symbols (proper pin directions) win over read_spice's.
extlib = ExtLibrary()
extlib.read_lef(_root / "lef/sg13g2_stdcell.lef")
extlib.read_gds(_root / "gds/sg13g2_stdcell.gds", ihp130.SG13G2().layers)
extlib.read_spice(_root / "spice/sg13g2_stdcell.spice", device_map=_device_map)


@functools.cache
def lef_pin_rects(fdry_name: str) -> dict:
    """
    Per-pin Metal1 pin rectangles ``{PIN: [(x0, y0, x1, y1), ...]}`` in nm for one
    stdcell LEF macro, foundry pin names kept as-is (A/Y/VDD/...). These are
    clean, per-pin, non-overlapping rectangles, so the router can pick an on-grid
    via-access point that lands on exactly the intended pin.
    """
    lef = _root / "lef/sg13g2_stdcell.lef"
    out = {}
    in_macro = pin = None
    on_m1 = False
    for line in lef.read_text().splitlines():
        t = line.split()
        if not t:
            continue
        if t[0] == "MACRO":
            in_macro = (t[1] == fdry_name)
        elif in_macro and t[0] == "PIN":
            pin = t[1]; out[pin] = []; on_m1 = False
        elif in_macro and t[0] == "END" and len(t) > 1 and t[1] == fdry_name:
            break
        elif in_macro and pin is not None and t[0] == "LAYER":
            on_m1 = (t[1] == "Metal1")
        elif in_macro and pin is not None and t[0] == "END" and len(t) > 1 \
                and t[1] == pin:
            pin = None
        elif in_macro and pin is not None and on_m1 and t[0] == "RECT":
            x0, y0, x1, y1 = (round(float(v) * 1000) for v in t[1:5])
            out[pin].append((x0, y0, x1, y1))
    return out


def _is_sg13g2_leaf(cell) -> bool:
    """A routing leaf is an sg13g2 foundry standard cell, recognised by its LEF
    macro name (e.g. ``sg13g2_inv_1``); any other cell is flattened by P&R."""
    return getattr(cell, "name", "").startswith("sg13g2_")


def place_and_route(cell, cfg=None):
    """Place-and-route ``cell`` with the sg13g2 standard-cell library.

    This binds the PDK-specific inputs -- the layer set, the LEF pin rectangles
    (:func:`lef_pin_rects`) and the foundry-leaf predicate -- to the generic
    engine :func:`ordec.layout.pnr.place_and_route`.
    """
    return _engine_pnr(cell, ihp130.SG13G2().layers, lef_pin_rects,
        _is_sg13g2_leaf, cfg=cfg)
