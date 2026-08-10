# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
IHP SG13G2 binding of :mod:`ordec.layout.digital_pnr`.

Every sg13g2 number and layer name lives here rather than in the engine, packed
into the :class:`PnrTarget` the engine takes. :func:`place_and_route` is the
one-argument form the designs call. A sibling module (``sky130_pnr.py``) would
bind the same engine to another PDK.

It sits next to :mod:`ordec.lib.ihp130_stdcells`, the other sg13g2 companion a
placed-and-routed design imports.
"""

import functools

from ordec.layout.digital_pnr import (GridConfig, PnrTarget, RoutingStack,
    place_and_route as engine_pnr)
from ordec.lib import ihp130

@functools.cache
def lef_macros() -> dict:
    """Parse the sg13g2 standard-cell LEF once, returning its macros by name."""
    import sc_leflib

    lef = ihp130.pdk().root / "libs.ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef"
    return sc_leflib.parse(str(lef))["macros"]


@functools.cache
def lef_pin_rects(macro_name: str) -> dict:
    """Read the per-pin Metal1 pin rectangles for one stdcell LEF macro.

        The LEF rectangles are clean, per-pin and non-overlapping, with the foundry
        pin names kept as-is, so the router can pick a via-access point that lands
        on exactly the intended pin.

        Args:
            macro_name (str): the LEF macro name, e.g. ``sg13g2_inv_1``.

        Returns:
            dict: ``{PIN: [(x0, y0, x1, y1), ...]}`` in nm.
        """
    macro = lef_macros()[macro_name]
    rects = {}
    upper = set()   # non-Metal1 layers in the macro's PIN or OBS geometry
    for pin, pin_data in macro["pins"].items():
        rects[pin] = []
        for port in pin_data["ports"]:
            for geom in port["layer_geometries"]:
                if geom["layer"] != "Metal1":
                    upper.add(geom["layer"])
                    continue
                for shape in geom["shapes"]:
                    # LEF also allows POLYGON here. The sg13g2 pins are all
                    # rectangles, and a polygon pin would need a polygon-exact
                    # via-access engine anyway.
                    if "rect" not in shape:
                        continue
                    x0, y0, x1, y1 = (round(v * 1000) for v in shape["rect"])
                    rects[pin].append((x0, y0, x1, y1))
    for port in macro.get("obs") or []:
        for geom in port:
            if geom["layer"] != "Metal1":
                upper.add(geom["layer"])
    if upper:
        # The engine routes Metal2..Metal5 freely over the placed cells, so a
        # cell with its own geometry up there (e.g. sg13g2_sdfbbp_1's Metal2/Via1
        # pin and obstruction shapes) would be silently shorted or violated.
        raise ValueError(
            f"{macro_name}: LEF pin/obstruction geometry on {sorted(upper)}. "
            "The P&R engine requires Metal1-only leaf cells, since it routes "
            "on the metals above them")
    return rects


def is_sg13g2_leaf(cell) -> bool:
    """Test whether a cell is an sg13g2 foundry standard cell.

        Args:
            cell: the cell to test.

        Returns:
            bool: true if its name starts with ``sg13g2_``, so it is placed as-is
            as a routing leaf. Any other cell is flattened.
        """
    return getattr(cell, "name", "").startswith("sg13g2_")


@functools.cache
def sg13g2_grid() -> GridConfig:
    """Build the sg13g2 routing-grid and emitted-geometry profile.

        Track pitches and row height come from the tech LEF. The wire, via, landing,
        strap and rail dimensions and the manufacturing grid come from the sign-off
        DRC rules.

        Returns:
            GridConfig: the profile, frozen and shared. The engine derives its
            per-floorplan variants with ``dataclasses.replace``.
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
        # Supply naming (sg13g2 stdcell library pins + ORDeC net conventions):
        vdd_pin="VDD",
        vss_pin="VSS",
        vdd_net="vdd",
        vss_net="vss",
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
        mesh_half_w=210,      # 420 nm Metal5 mesh straps (2x wire width)
    )


@functools.cache
def sg13g2_layers() -> RoutingStack:
    """Bind the engine's routing codes to the sg13g2 metal and via layers.

        sg13g2 routes on Metal2 to Metal5, with Metal1 for pin access only and Via1
        to Via4, so the codes map 1:1 onto the like-numbered PDK layers.

        Returns:
            RoutingStack: the sg13g2 layer binding.
        """
    layers = ihp130.SG13G2().layers
    return RoutingStack(
        layer_set=layers,
        m1=layers.Metal1, m2=layers.Metal2, m3=layers.Metal3,
        m4=layers.Metal4, m5=layers.Metal5,
        via1=layers.Via1, via2=layers.Via2, via3=layers.Via3, via4=layers.Via4,
    )


def sg13g2_target(cfg: GridConfig = None) -> PnrTarget:
    """Build the sg13g2 :class:`PnrTarget` for the engine.

        Args:
            cfg: an optional :class:`GridConfig` to use instead of
                :func:`sg13g2_grid`, e.g. ``replace(sg13g2_grid(),
                power_mesh=False)``.

        Returns:
            PnrTarget: the layer stack, grid, LEF pin rectangles and foundry-leaf
            predicate.
        """
    return PnrTarget(stack=sg13g2_layers(), grid=cfg or sg13g2_grid(),
        pin_rects=lef_pin_rects, is_leaf=is_sg13g2_leaf)


def place_and_route(cell, cfg=None, layout=None):
    """Place-and-route ``cell`` with the IHP sg13g2 standard-cell library.

        The one-argument form a design's layout view generator calls::

            viewgen layout -> Layout:
                place_and_route(self)

        Args:
            cell: the cell to lay out, whose schematic instantiates sg13g2 leaves.
            cfg: an optional :class:`GridConfig`, defaulting to :func:`sg13g2_grid`.
            layout: the :class:`Layout` to build into, defaulting to the enclosing
                ``viewgen layout`` root.

        Returns:
            The DRC/LVS-clean :class:`Layout` for ``cell``.
        """
    return engine_pnr(cell, sg13g2_target(cfg), layout)
