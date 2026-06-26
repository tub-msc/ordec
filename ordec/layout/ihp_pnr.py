# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
IHP SG13G2 binding of the generic place-and-route engine
(:func:`ordec.layout.pnr.place_and_route`).

The engine is PDK-agnostic: it lays out a cell given a :class:`RoutingStack`
(routing codes -> PDK layers), a per-cell pin-rectangle lookup, a routing-leaf
predicate and a :class:`GridConfig` (the routing grid + DRC-driven emission
geometry). This module supplies all four for the IHP sg13g2 standard cells -- so
every sg13g2 number and layer name lives here, not in the engine -- and exposes a
one-argument :func:`place_and_route` that the designs call directly. A sibling
module (e.g. ``sky130_pnr.py``) would bind the same engine to another PDK.
"""

import functools

from ordec.lib import ihp130
from ordec.layout.pnr import GridConfig, RoutingStack, place_and_route as engine_pnr

@functools.cache
def lef_pin_rects(macro_name: str) -> dict:
    """Read the per-pin Metal1 pin rectangles for one stdcell LEF macro.

    The rectangles are clean, per-pin and non-overlapping (foundry pin names kept
    as-is: A/Y/VDD/...), so the router can pick an on-grid via-access point that
    lands on exactly the intended pin. Cached per macro.

    Args:
        macro_name (str): the LEF macro name (e.g. ``sg13g2_inv_1``).

    Returns:
        dict: ``{PIN: [(x0, y0, x1, y1), ...]}`` in nm.
    """
    lef = ihp130.pdk().root / "libs.ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef"
    rects = {}
    in_macro = pin = None
    on_metal1 = False
    for line in lef.read_text().splitlines():
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0] == "MACRO":
            in_macro = (tokens[1] == macro_name)
        elif in_macro and tokens[0] == "PIN":
            pin = tokens[1]; rects[pin] = []; on_metal1 = False
        elif in_macro and tokens[0] == "END" and len(tokens) > 1 and tokens[1] == macro_name:
            break
        elif in_macro and pin is not None and tokens[0] == "LAYER":
            on_metal1 = (tokens[1] == "Metal1")
        elif in_macro and pin is not None and tokens[0] == "END" and len(tokens) > 1 \
                and tokens[1] == pin:
            pin = None
        elif in_macro and pin is not None and on_metal1 and tokens[0] == "RECT":
            x0, y0, x1, y1 = (round(float(v) * 1000) for v in tokens[1:5])
            rects[pin].append((x0, y0, x1, y1))
    return rects


def is_sg13g2_leaf(cell) -> bool:
    """Test whether a cell is an sg13g2 foundry standard cell (a routing leaf).

    Args:
        cell: the cell to test.

    Returns:
        bool: true if its name starts with ``sg13g2_`` (placed as-is); false for
        any other cell, which P&R flattens.
    """
    return getattr(cell, "name", "").startswith("sg13g2_")


def sg13g2_grid() -> GridConfig:
    """Build the sg13g2 routing-grid + emitted-geometry profile for the engine.

    Track pitches and row height come from the tech LEF; the wire/via/landing/strap/
    rail dimensions and the manufacturing grid come from the sign-off DRC rules.

    Returns:
        GridConfig: a fresh instance per call, since the engine mutates ``n_rows``
        while growing the floorplan.
    """
    return GridConfig(
        # Routing grid (sg13g2 tech LEF):
        x_pitch=480,
        y_pitch=420,
        row_height=3780,
        tracks_per_row=9,
        via_half=95,
        encl=10,
        encl_endcap=50,
        manufacturing_grid=5, # sg13g2 layout quantum (MANUFACTURINGGRID)
        # Emitted geometry (sg13g2 sign-off DRC rules):
        wire_width=210,       # Mn min width
        wire_ext=150,         # via half 95 + 55 endcap (Mn.c1 / V*.c1)
        strap_half_w=105,     # wire_width / 2
        land_half_h=345,      # 690 nm landing -> Mn min area
        m1_land_half_h=145,   # Metal1 endcap landing under a Via1 (V1.c1)
        min_area_tracks=2,    # 2 * pitch * 210 nm wire >= 0.144 um^2 Mn min area
        port_pad_below=600,
        port_pad_above=360,
        strap_vdd_x=-520,     # left margin; right strap mirrors to die_w + 520
        strap_vss_x=-1080,    # just outside VDD
        rail_ext=150,
    )


def sg13g2_layers() -> RoutingStack:
    """Bind the engine's abstract routing stack to the sg13g2 metal/via layers.

    sg13g2 routes on Metal2..Metal5 (Metal1 is pin access only), with Via1..Via4,
    so the engine's codes map 1:1 onto the like-numbered PDK layers.

    Returns:
        RoutingStack: the sg13g2 layer binding for the engine.
    """
    layers = ihp130.SG13G2().layers
    return RoutingStack(
        layer_set=layers,
        m1=layers.Metal1, m2=layers.Metal2, m3=layers.Metal3,
        m4=layers.Metal4, m5=layers.Metal5,
        via1=layers.Via1, via2=layers.Via2, via3=layers.Via3, via4=layers.Via4,
    )


def place_and_route(cell, cfg=None):
    """Place-and-route ``cell`` with the IHP sg13g2 standard-cell library.

    Binds the PDK-specific inputs -- the layer stack (:func:`sg13g2_layers`), the
    LEF pin rectangles (:func:`lef_pin_rects`), the foundry-leaf predicate and the
    sg13g2 grid (:func:`sg13g2_grid`) -- to the generic engine
    :func:`ordec.layout.pnr.place_and_route`.

    Args:
        cell: the cell to lay out (its schematic instantiates sg13g2 leaf cells).
        cfg: an optional :class:`GridConfig`; defaults to
            :func:`sg13g2_grid`. Pass one to override grid/geometry knobs.

    Returns:
        A frozen, DRC/LVS-clean :class:`Layout` for ``cell``.
    """
    return engine_pnr(cell, sg13g2_layers(), lef_pin_rects,
        is_sg13g2_leaf, cfg or sg13g2_grid())
