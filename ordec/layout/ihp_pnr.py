# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
IHP SG13G2 binding of the generic place-and-route engine
(:func:`ordec.layout.pnr.place_and_route`).

The engine is PDK-agnostic: it lays out a cell given a layer set, a per-cell
pin-rectangle lookup, a routing-leaf predicate and a :class:`GridConfig` (the
routing grid + DRC-driven emission geometry). This module supplies all four for
the IHP sg13g2 standard cells -- so every sg13g2 number lives here, not in the
engine -- and exposes a one-argument :func:`place_and_route` that the designs
call directly. A sibling module (e.g. ``sky130_pnr.py``) would bind the same
engine to another PDK.
"""

import functools

from ordec.lib import ihp130
from ordec.layout.pnr import GridConfig, place_and_route as _engine_pnr

# sg13g2 standard-cell reference files, relative to the PDK root.
_STDCELL_LEF = "libs.ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef"


@functools.cache
def lef_pin_rects(fdry_name: str) -> dict:
    """
    Per-pin Metal1 pin rectangles ``{PIN: [(x0, y0, x1, y1), ...]}`` in nm for one
    stdcell LEF macro, foundry pin names kept as-is (A/Y/VDD/...). These are
    clean, per-pin, non-overlapping rectangles, so the router can pick an on-grid
    via-access point that lands on exactly the intended pin.
    """
    lef = ihp130.pdk().root / _STDCELL_LEF
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


def is_sg13g2_leaf(cell) -> bool:
    """A routing leaf is an sg13g2 foundry standard cell, recognised by its LEF
    macro name (e.g. ``sg13g2_inv_1``); any other cell is flattened by P&R."""
    return getattr(cell, "name", "").startswith("sg13g2_")


def sg13g2_grid() -> GridConfig:
    """The sg13g2 routing grid and emitted-geometry profile: track pitches and
    row height from the tech LEF, the wire/via/landing/strap/rail dimensions from
    the sign-off DRC rules. A fresh instance per call, since the engine mutates
    ``n_rows`` while growing the floorplan."""
    return GridConfig(
        # Routing grid (sg13g2 tech LEF):
        x_pitch=480,
        y_pitch=420,
        row_height=3780,
        tracks_per_row=9,
        via_half=95,
        encl=10,
        encl_endcap=50,
        # Emitted geometry (sg13g2 sign-off DRC rules):
        wire_width=210,       # Mn min width
        wire_ext=150,         # via half 95 + 55 endcap (Mn.c1 / V*.c1)
        strap_half_w=105,     # wire_width / 2
        land_half_h=345,      # 690 nm landing -> Mn min area
        m1_land_half_h=145,   # Metal1 endcap landing under a Via1 (V1.c1)
        port_pad_below=600,
        port_pad_above=360,
        strap_vdd_x=-520,     # left margin; right strap mirrors to die_w + 520
        strap_vss_x=-1080,    # just outside VDD
        rail_ext=150,
    )


def place_and_route(cell, cfg=None):
    """Place-and-route ``cell`` with the IHP sg13g2 standard-cell library.

    This binds the PDK-specific inputs -- the layer set, the LEF pin rectangles
    (:func:`lef_pin_rects`), the foundry-leaf predicate and the sg13g2 grid
    (:func:`sg13g2_grid`) -- to the generic engine
    :func:`ordec.layout.pnr.place_and_route`. ``cfg`` defaults to
    :func:`sg13g2_grid`; pass one to override grid/geometry knobs.
    """
    return _engine_pnr(cell, ihp130.SG13G2().layers, lef_pin_rects,
        is_sg13g2_leaf, cfg or sg13g2_grid())
