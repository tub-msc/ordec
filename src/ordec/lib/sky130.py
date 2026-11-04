# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
import math
import subprocess
from pathlib import Path
from public import public
import functools
from importlib import resources
from dataclasses import dataclass, replace

from ..core import *
from ..schematic import spice_params, Netlister
from . import generic_mos, pdk_dirs
from .pdk_common import PdkDict, check_dir, check_file, rundir
from ..layout import makevias, write_gds, flatten
from ..layout.style import read_layout_style
from ..layout import klayout, magic

@functools.cache
def pdk() -> PdkDict:
    """Returns dictionary-like object with import PDK paths."""
    root = os.environ.get("ORDEC_PDK_SKY130A", pdk_dirs.sky130a)
    if root is None:
        raise Exception("PDK requires environment variable ORDEC_PDK_SKY130A to be set.")
    pdk = PdkDict(root=check_dir(Path(root).resolve()))

    pdk.ngspice_lib = check_file(pdk.root / "libs.tech/ngspice/sky130.lib.spice")

    pdk.klayout_drc_deck = check_file(pdk.root / "libs.tech/klayout/drc/sky130A_mr.drc")
    pdk.klayout_density_deck = check_file(pdk.root / "libs.tech/klayout/drc/met_min_ca_density.lydrc")
    pdk.klayout_lvs_deck = check_file(pdk.root / "libs.tech/klayout/lvs/sky130.lvs")

    pdk.magic_rcfile = check_file(pdk.root / "libs.tech/magic/sky130A.magicrc")

    return pdk

def netlist_setup(netlister):
    if netlister.lvs:
        return
    # The corner section of the PDK's lib file pulls in the MOSFET corner
    # deck plus the resistor/capacitor models and sets mc_mm_switch=0.
    corner = 'tt' if netlister.corner is None else netlister.corner
    netlister.add(".lib",f"\"{pdk().ngspice_lib}\"",corner)

# SKY130 has no machine-readable tech parameter file in the PDK (unlike
# SG13G2's sg13g2_tech_mod.json), so the rule values used by the layout
# generators and cell-level layouts are recorded here. All values in nm, rule
# ids refer to the SkyWater periphery rules
# (skywater-pdk.readthedocs.io/en/main/rules).
tech_rules = {
    'licon_size': 170,          # licon.1
    'licon_space': 170,         # licon.2
    'licon_encl_diff_min': 40,  # licon.5a
    'licon_encl_diff': 60,      # licon.5c (used on all sides by the generators)
    'licon_encl_tap': 120,      # licon.7
    'licon_encl_poly_min': 50,  # licon.8
    'licon_encl_poly': 80,      # licon.8a (used on all sides by the generators)
    'licon_encl_npc': 100,      # licon.15
    'licon_gate_space': 55,     # licon.11
    'licon_poly_diff_space': 190, # licon.14
    'licon_psdm_space': 110,    # licon.9
    'li_width': 170,            # li.1
    'li_encl_licon_end': 80,    # li.5
    'mcon_size': 170,           # ct.1
    'mcon_space': 190,          # ct.2
    'met1_encl_mcon': 30,       # m1.4
    'met1_encl_mcon_end': 60,   # m1.5
    'met1_min_area': 83000,     # m1.6 (nm^2, 0.083 um^2)
    'poly_width': 150,          # poly.1a
    'poly_endcap': 130,         # poly.8
    'diff_ext_poly': 250,       # poly.7
    'channel_width_min': 420,   # difftap.2
    'implant_encl': 125,        # nsd.5a/psd.5a
    'implant_space_opposite': 130, # nsd.7/psd.7
    'nwell_encl': 180,          # difftap.8/difftap.10
    'ndiff_nwell_space': 340,   # difftap.9
    'ptap_nwell_space': 130,    # difftap.11
    'nwell_width': 840,         # nwell.1
    'npc_gate_space': 90,       # npc.4
    'npc_space': 270,           # npc.2
    'res_poly_width': 330,      # poly.3
    'res_poly_length': 1650,    # generic_po PCell lmin
    'res_poly_space': 480,      # poly.9
    'res_licon_body_space': 100, # no deck rule, from the magic PCell geometry
    'capm_width': 1000,         # capm.1
    'capm_encl_met3': 140,      # capm.3_a (met3 enclosure of capm)
    'capm_encl_via3': 140,      # capm.4
    'via3_size': 200,           # via3.1_a
    'via3_space': 200,          # via3.2
    'met4_encl_via3': 100,      # via3.6 style top enclosure, chosen generous
    # Metal stack widths, spacings, cut sizes and minimum areas, from the
    # sky130A_mr.drc deck (met3 and li have no min-area rule there):
    'poly_space': 210,          # poly.2
    'li_space': 170,            # li.3
    'met1_width': 140,          # m1.1
    'met1_space': 140,          # m1.2
    'met2_width': 140,          # m2.1
    'met2_space': 140,          # m2.2
    'met2_min_area': 67600,     # m2.6 (nm^2, 0.0676 um^2)
    'met3_width': 300,          # m3.1
    'met3_space': 300,          # m3.2
    'met4_width': 300,          # m4.1
    'met4_space': 300,          # m4.2
    'met4_min_area': 240000,    # m4.4a (nm^2, 0.24 um^2)
    'met5_width': 1600,         # m5.1
    'met5_space': 1600,         # m5.2
    'met5_min_area': 4000000,   # m5.4 (nm^2, 4.0 um^2)
    'via_size': 150,            # via.1a
    'via_space': 170,           # via.2
    'via2_size': 200,           # via2.1a
    'via2_space': 200,          # via2.2
    'via4_size': 800,           # via4.1_a
    'via4_space': 800,          # via4.2
    # Metal enclosures of the cut levels (all-side minimum, _end for the
    # larger two-adjacent-edges rule):
    'met1_encl_via': 55,        # via.4a
    'met1_encl_via_end': 85,    # via.5a
    'met2_encl_via': 55,        # m2.4
    'met2_encl_via_end': 85,    # m2.5
    'met2_encl_via2': 40,       # via2.4
    'met2_encl_via2_end': 85,   # via2.5 (the deck text says m3, its code checks m2)
    'met3_encl_via2': 65,       # m3.4
    'met3_encl_via2_end': 85,   # via2.5
    'met3_encl_via3': 60,       # via3.4
    'met3_encl_via3_end': 90,   # via3.5
    'met4_encl_via4': 190,      # via4.4
    'met5_encl_via4': 310,      # m5.3
}

@public
class SKY130(Cell):
    @viewgen_noctx
    def layers(self):
        s = LayerStack(cell=self)

        s.unit = R('1n')

        def layer(layer, data_type):
            return s % Layer(gdslayer_shapes=GdsLayer(layer=layer, data_type=data_type))

        def pin(layer, text=5):
            return s % Layer(
                gdslayer_text=GdsLayer(layer=layer, data_type=text),
                gdslayer_shapes=GdsLayer(layer=layer, data_type=16),
                is_pinlayer=True,
            )

        # Frontend layers
        # ---------------

        s.nwell = Layer(gdslayer_shapes=GdsLayer(layer=64, data_type=20), pin=pin(64))
        s.dnwell = layer(64, 18)
        s.pwell = Layer(gdslayer_shapes=GdsLayer(layer=64, data_type=44), pin=s % Layer(
            gdslayer_text=GdsLayer(layer=64, data_type=59),
            gdslayer_shapes=GdsLayer(layer=122, data_type=16),
            is_pinlayer=True,
        ))
        s.pwell.res = Layer(gdslayer_shapes=GdsLayer(layer=64, data_type=13))
        s.diff = Layer(gdslayer_shapes=GdsLayer(layer=65, data_type=20), pin=pin(65, 6))
        s.diff.res = Layer(gdslayer_shapes=GdsLayer(layer=65, data_type=13))
        s.diff.hv = Layer(gdslayer_shapes=GdsLayer(layer=65, data_type=8))
        s.tap = layer(65, 44)
        s.poly = Layer(gdslayer_shapes=GdsLayer(layer=66, data_type=20), pin=pin(66))
        s.poly.res = Layer(gdslayer_shapes=GdsLayer(layer=66, data_type=13))
        s.poly.short = Layer(gdslayer_shapes=GdsLayer(layer=66, data_type=15))
        s.poly.gate = Layer(gdslayer_shapes=GdsLayer(layer=66, data_type=9))
        s.poly.model = Layer(gdslayer_text=GdsLayer(layer=66, data_type=83))
        s.licon1 = layer(66, 44)
        s.npc = layer(95, 20)
        s.nsdm = layer(93, 44)
        s.psdm = layer(94, 20)
        s.hvtp = layer(78, 44)
        s.hvtr = layer(18, 20)
        s.lvtn = layer(125, 44)
        s.ldntm = layer(11, 44)
        s.hvntm = layer(125, 20)
        s.hvi = layer(75, 20)
        s.tunm = layer(80, 20)
        s.rpm = layer(86, 20)
        s.urpm = layer(79, 20)
        s.pwbm = layer(19, 44)
        s.pwde = layer(124, 20)
        s.vhvi = layer(74, 21)
        s.uhvi = layer(74, 22)
        s.ncm = layer(92, 44)

        # Metal stack (li1 + met1..met5)
        # ------------------------------

        def metal(n):
            m = s % Layer(gdslayer_shapes=GdsLayer(layer=n, data_type=20), pin=pin(n))
            return m

        s.li1 = metal(67)
        s.mcon = layer(67, 44)
        s.met1 = metal(68)
        s.via = layer(68, 44)
        s.met2 = metal(69)
        s.via2 = layer(69, 44)
        s.met3 = metal(70)
        s.via3 = layer(70, 44)
        s.met4 = metal(71)
        s.via4 = layer(71, 44)
        s.met5 = metal(72)

        for m in (s.li1, s.met1, s.met2, s.met3, s.met4, s.met5):
            n = m.gdslayer_shapes.layer
            # Metal resistor marker and short, as res_generic_l1 etc. draw them
            m.res = Layer(gdslayer_shapes=GdsLayer(layer=n, data_type=13))
            m.short = Layer(gdslayer_shapes=GdsLayer(layer=n, data_type=15))

        # Other layers
        # ------------

        s.capm = layer(89, 44)
        s.cap2m = layer(97, 44)
        s.pad = Layer(gdslayer_shapes=GdsLayer(layer=76, data_type=20), pin=pin(76))
        s.nsm = layer(61, 20)

        s.npn = layer(82, 20)
        s.pnp = layer(82, 44)
        s.inductor = layer(82, 24)
        s.capacitor = layer(82, 64)

        # Identification layers (areaid)
        s.areaid = PathNode()
        for name, data_type in (("sl", 1), ("ce", 2), ("fe", 3), ("sc", 4), ("ed", 19), ("de", 23),
                ("st", 53), ("en", 57), ("le", 60), ("hl", 63), ("sd", 70), ("po", 81), ("lvt", 108),
                ("re", 125)):
            s.areaid[name] = Layer(gdslayer_shapes=GdsLayer(layer=81, data_type=data_type))

        s.TEXT = Layer(gdslayer_text=GdsLayer(layer=83, data_type=44))

        s.prBoundary = layer(235, 4)

        return s

    @viewgen_noctx
    def layout_style(self):
        return read_layout_style(self.layers,
            resources.files(__package__) / 'sky130_layout_style.toml', 'sky130')

    @viewgen_noctx
    def default_routing_spec(self):
        """
        SRouter parameters for the met1..met5 stack. Wire widths sit at or
        above the width minima, via cuts are the exact via.1a/via2.1a/via3.1/
        via4.1 sizes, run-in pads cover the all-sides via enclosures (via.4a/b
        55, via2.4 40, via3.4 60, m3.4 and m4.3 65, via4.4 190, m5.3 310) with
        the wire supplying the endcap enclosure (via.5a/b, via2.5: 85, via3.5:
        90), and standalone pads cover the endcap on all sides plus the
        minimum metal areas (m1.6, m3.6, m4.4a, m5.4).
        """
        layers = self.layers
        rs = RoutingSpec(ref_layers=layers)

        route_id = 0

        def addmetal(layer, route_width, route_ext, route_via, route_pad):
            nonlocal route_id
            rs % RoutingSpecLayer(
                layer=layer,
                route_id=route_id,
                route_wire_width=route_width,
                route_wire_ext=route_ext,
                route_via_width=route_via[0],
                route_via_height=route_via[1],
                route_pad_width=route_pad[0],
                route_pad_height=route_pad[1],
            )
            route_id += 1

        def addvia(layer, route_via):
            nonlocal route_id
            rs % RoutingSpecLayer(
                layer=layer,
                route_id=route_id,
                route_via_width=route_via[0],
                route_via_height=route_via[1],
            )
            route_id += 1

        addmetal(layers.met1, 170, 160, (330, 270), (260, 260))
        addvia(layers.via, (150, 150))
        # The 170 wire is narrower than via2's cut, so it cannot supply the 85
        # endcap (via2.5). The met2 run-in pad does, in x for all wire directions.
        addmetal(layers.met2, 170, 200, (370, 300), (370, 280))
        addvia(layers.via2, (200, 200))
        addmetal(layers.met3, 300, 200, (500, 500), (330, 330))
        addvia(layers.via3, (200, 200))
        # via4's enclosure sets the met4 pad on both ends of a stack.
        addmetal(layers.met4, 300, 200, (1180, 1180), (1180, 1180))
        addvia(layers.via4, (800, 800))
        addmetal(layers.met5, 1600, 800, (2000, 2000), (1600, 1600))

        return rs


def check_grid(cell: Cell, grid: R, *names: str):
    """Reject parameters off the grid, which magic's generators would round."""
    for name in names:
        v = getattr(cell, name)
        if v / grid != int(v / grid):
            raise ParameterError(f"{name} = {v} must be a multiple of {grid}.")

def check_counts(params: dict, *names: str):
    """Reject repeat counts below 1."""
    for name in names:
        if params[name] < 1:
            raise ParameterError(f"{name} must be at least 1.")

def rnd(v) -> int:
    """A distance rounded to the 5 nm grid, half away from zero, as magic's box commands do."""
    return int(math.copysign(5 * ((abs(v) + 2.5) // 5), v))

def rect_grow(r: tuple, d: int) -> tuple:
    return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)

def rects_cells(rects: list) -> tuple:
    """Coordinates and the covered cells of the grid they span."""
    xs = sorted({r[0] for r in rects} | {r[2] for r in rects})
    ys = sorted({r[1] for r in rects} | {r[3] for r in rects})
    xi, yi = {x: i for i, x in enumerate(xs)}, {y: j for j, y in enumerate(ys)}
    cells = set()
    for r in rects:
        cells.update((i, j) for i in range(xi[r[0]], xi[r[2]]) for j in range(yi[r[1]], yi[r[3]]))
    return xs, ys, cells

def rects_of_cells(xs: list, ys: list, cells: set) -> list:
    """Cells as rects, joined along y, then along x."""
    runs = {}
    for i in range(len(xs) - 1):
        j = 0
        while j < len(ys) - 1:
            if (i, j) in cells:
                j0 = j
                while (i, j) in cells:
                    j += 1
                runs.setdefault((ys[j0], ys[j]), []).append(i)
            j += 1
    rects = []
    for (ly, uy), columns in runs.items():
        i0 = prev = columns[0]
        for i in columns[1:] + [None]:
            if i != prev + 1 if i is not None else True:
                rects.append((xs[i0], ly, xs[prev + 1], uy))
                i0 = i
            prev = i
    return rects

def rects_subtract(a: list, b: list) -> list:
    if not a or not b:
        return list(a)
    xs, ys, _ = rects_cells(a + b)
    def cover(rects):
        xi, yi = {x: i for i, x in enumerate(xs)}, {y: j for j, y in enumerate(ys)}
        return {(i, j) for r in rects for i in range(xi[r[0]], xi[r[2]]) for j in range(yi[r[1]], yi[r[3]])}
    return rects_of_cells(xs, ys, cover(a) - cover(b))

def slots_along(lo: int, hi: int, size: int, sep: int) -> tuple:
    """Number and first position of the slots along one axis, as magic's cifSlotFunc."""
    while True:
        n = (hi - lo + sep - 160) // (size + sep)
        if n <= 0:
            return 0, lo
        first = int((lo + hi + sep - n*(size + sep)) / 2)
        if first % 5 == 0:
            return n, first
        hi += 2 * (abs(first) % 5) * (1 if first < 0 else -1)

def rects_grow_min(rects: list, d: int) -> list:
    """Magic's grow-min operator (cifGrowMinFunc). It works on the tiles of magic's
    plane, the maximal horizontal strips of material and of space."""
    if not rects:
        return []
    xs, ys, cells = rects_cells(rects)
    yi = {y: j for j, y in enumerate(ys)}

    def neighbours(j, lx, ux):
        """Tiles of a row of the plane touching the x range, as [solid, left, right]."""
        row = [[False, -math.inf, xs[0]]]
        for i in range(len(xs) - 1):
            solid = (i, j) in cells
            if row[-1][0] == solid:
                row[-1][2] = xs[i + 1]
            else:
                row.append([solid, xs[i], xs[i + 1]])
        if row[-1][0]:
            row.append([False, xs[-1], math.inf])
        else:
            row[-1][2] = math.inf
        return [n for n in row if n[1] < ux and n[2] > lx]

    def min_box(lx, ly, ux, uy):
        """SetMinBoxGrid: at least d in both directions, outward onto the 5 nm grid."""
        if ux - lx < d:
            lx, ux = int((lx + ux - d) / 2), int((lx + ux + d) / 2)
        if uy - ly < d:
            ly, uy = int((ly + uy - d) / 2), int((ly + uy + d) / 2)
        return (lx - lx % 5, ly - ly % 5, ux + -ux % 5, uy + -uy % 5)

    grown = []
    for ly, lx, uy, ux in rects_of_cells(ys, xs, {(j, i) for i, j in cells}):
        width, height = ux - lx, uy - ly
        below, above = neighbours(yi[ly] - 1, lx, ux), neighbours(yi[uy], lx, ux)
        area = (lx, ly, ux, uy)
        if width < d:
            grow_x = (d - width) // 2
            area = (lx - grow_x, ly, ux + grow_x, uy)
            if height < d:
                free_bot, free_top = not any(n[0] for n in below), not any(n[0] for n in above)
                step = int(math.sqrt(d*d - 0.25*(d + width)**2 + 0.5))
                grow_y = (d - height) // 2
                if free_top and not free_bot:
                    area = (area[0], ly - step, area[2], uy)
                elif free_bot and not free_top:
                    area = (area[0], ly, area[2], uy + step)
                else:
                    area = (area[0], ly - grow_y, area[2], uy + grow_y)
                area = min_box(*area)
        grown.append(area)
        # What runs between the same type of tile above and below, on its own.
        for b in below:
            for t in above:
                if b[0] != t[0]:
                    continue
                if b[1] <= t[1] <= b[2]:
                    x0, x1 = max(t[1], lx), min(b[2], ux)
                elif b[1] <= t[2] <= b[2]:
                    x0, x1 = max(b[1], lx), min(t[2], ux)
                else:
                    continue
                if x1 - x0 < d or height < d:
                    grow_x = (d - (x1 - x0)) // 2 if x1 - x0 < d else 0
                    grow_y = (d - height) // 2 if height < d else 0
                    grown.append(min_box(x0 - grow_x, ly - grow_y, x1 + grow_x, uy + grow_y))
    return grown

def rects_close(rects: list, gap: int) -> list:
    """Morphological closing: fill notches and gaps narrower than gap."""
    if not rects:
        return []
    d = (gap - 1) // 2
    grown = [rect_grow(r, d) for r in rects]
    xs, ys, cells = rects_cells(grown)
    outer = (xs[0] - 2*d, ys[0] - 2*d, xs[-1] + 2*d, ys[-1] + 2*d)
    # Shrink: grow the complement of the grown rects.
    complement = rects_subtract([outer], grown)
    return rects_subtract([outer], [rect_grow(r, d) for r in complement])

class Paint:
    """
    Shapes by magic type (sky130A.tcl draws them), and the mask layers derived
    from them by the gdsii style of magic's cifoutput section (sky130A.tech).
    """
    NDIFF = ("ndiff", "mvndiff", "ndc", "mvndc", "nnd")
    PDIFF = ("pdiff", "mvpdiff", "pdc", "mvpdc")
    NTAP = ("nsd", "mvnsd", "nsc", "mvnsc")
    PTAP = ("psd", "mvpsd", "psc", "mvpsc")
    MVDIFF = ("mvndiff", "mvpdiff", "mvndc", "mvpdc", "mvnsd", "mvpsd", "mvnsc", "mvpsc")
    DIFFCUT = ("ndc", "pdc", "nsc", "psc", "mvndc", "mvpdc", "mvnsc", "mvpsc")

    def __init__(self):
        self.types = {}

    def paint(self, type: str, rect: tuple) -> tuple:
        self.types.setdefault(type, []).append(rect)
        return rect

    def of(self, *types) -> list:
        return list(dict.fromkeys(r for t in types for r in self.types.get(t, [])))

    def draw(self, l: Layout):
        layers = l.ref_layers

        def shapes(layer, rects):
            for r in rects:
                l % LayoutRect(layer=layer, rect=Rect4I(*r))

        def cuts(layer, rects, border, size, sep):
            # Overlapping contacts form one area, as in magic's plane.
            for r in rects_of_cells(*rects_cells(rects)) if rects else []:
                # squares-grid: as many cuts as fit, centered
                nx = (r[2] - r[0] - 2*border + sep) // (size + sep)
                ny = (r[3] - r[1] - 2*border + sep) // (size + sep)
                x0 = r[0] + 5 * ((r[2] - r[0] - nx*size - (nx - 1)*sep) // 10)
                y0 = r[1] + 5 * ((r[3] - r[1] - ny*size - (ny - 1)*sep) // 10)
                for i in range(nx):
                    for j in range(ny):
                        x, y = x0 + i*(size + sep), y0 + j*(size + sep)
                        l % LayoutRect(layer=layer, rect=Rect4I(x, y, x + size, y + size))

        ndiff, pdiff = self.of(*self.NDIFF), self.of(*self.PDIFF)
        ntap, ptap = self.of(*self.NTAP), self.of(*self.PTAP)
        ndiffres, pdiffres = self.of("rdn", "mvrdn"), self.of("rdp", "mvrdp")
        polyres = rects_subtract(self.of("xhrpoly", "uhrpoly"), self.of("xpc"))
        shapes(layers.diff, ndiff + pdiff + ndiffres + pdiffres)
        shapes(layers.diff.res, ndiffres + pdiffres)
        shapes(layers.tap, ntap + ptap)
        shapes(layers.poly, self.of("poly", "pc", "mrp1", "xpc") + polyres)
        shapes(layers.poly.res, self.of("mrp1") + polyres)
        # An mcon also paints li1 and met1, a precision resistor's end li1.
        for type_, res, metal in (("li", "rli", layers.li1), ("m1", "rm1", layers.met1), ("m2", "rm2", layers.met2),
                ("m3", "rm3", layers.met3), ("m4", "rm4", layers.met4), ("m5", "rm5", layers.met5)):
            shapes(metal, self.of(type_, res) + (self.of("mcon") if type_ in ("li", "m1") else [])
                + (self.of("xpc") if type_ == "li" else []))
            shapes(metal.res, self.of(res))
        shapes(layers.dnwell, self.of("dnwell"))
        if self.of("rpw"):
            # NWELL: the DNWELL region around the p-well resistor
            shapes(layers.pwell.res, rects_subtract(self.of("rpw"), rects_subtract(self.of("rpw"), self.of("dnwell"))))
            shapes(layers.nwell, rects_subtract(self.of("nwell", "dnwell"), self.of("rpw", "pwell")))
        else:
            shapes(layers.nwell, self.of("nwell"))
        shapes(layers.prBoundary, self.of("boundary"))

        # POLYRES extends to the edge of the contact cut.
        reach = [rect_grow(r, 60) for r in polyres]
        shapes(layers.poly.res, rects_subtract(reach, rects_subtract(reach, self.of("xpc"))))

        # RPM, URPM
        def poly_implant(res):
            if not self.of(res):
                return []
            return rects_close(rects_grow_min([rect_grow(r, 200) for r in self.of(res, "xpc")], 1270), 845)
        shapes(layers.rpm, poly_implant("xhrpoly"))
        shapes(layers.urpm, poly_implant("uhrpoly"))

        # PSDM, NSDM
        base_n = [rect_grow(r, 125) for r in ndiff + ntap + ndiffres]
        base_p = [rect_grow(r, 125) for r in pdiff + ptap + pdiffres] \
            + [rect_grow(r, 110) for r in polyres + self.of("xpc")]
        def implant(base, other):
            return rects_close(base + rects_subtract(rects_close(base, 380), other), 375)
        shapes(layers.nsdm, implant(base_n, base_p))
        shapes(layers.psdm, implant(base_p, base_n))

        # LVTN, HVTP
        def threshold(gates):
            return rects_close(rects_close([rect_grow(r, 180) for r in gates], 380), 375)
        shapes(layers.lvtn, threshold(self.of("pfetlvt", "nfetlvt", "mvnnfet", "nnfet", "mvvar", "nsonos")))
        shapes(layers.hvtp, threshold(self.of("pfethvt", "varhvt")))
        shapes(layers.areaid.le, [rect_grow(r, 100) for r in self.of("nnfet")])

        # SONOS, LDNTM
        shapes(layers.tunm, rects_close([rect_grow(r, 250) for r in self.of("nsonos")], 505))
        if self.of("nsonos"):
            shapes(layers.ldntm, rects_close([rect_grow(r, 185) for r in self.of("ndiff", "ndc")], 695))

        # HVNTM
        block = [rect_grow(r, 185) for r in self.of("mvpsd", "mvpsc")]
        hvntm = []
        if self.of("mvnfet", "mvnnfet", "nnfet", "mvrdn"):
            hvntm += self.of("mvndiff", "mvndc", "mvrdn")
        if self.of("mvvar"):
            hvntm += self.of("mvnsd", "mvnsc")
        shapes(layers.hvntm, rects_subtract(rects_close([rect_grow(r, 185) for r in
            rects_subtract(hvntm, block)], 695), block))

        # HVI
        mv = self.of(*self.MVDIFF, "mvrdn", "mvrdp")
        thkox = [rect_grow(r, 185) for r in mv + self.of("mvvar")]
        if mv:
            thkox += self.of("nwell")
        hvi = []
        if thkox:
            # grow-min works on magic's tiles, the maximal horizontal strips:
            # thin ones widen to the 840 nm of CNTM.
            xs, ys, cells = rects_cells(rects_close(thkox, 695))
            strips = rects_of_cells(ys, xs, {(j, i) for i, j in cells})
            for ly, lx, uy, ux in strips:
                grow_x = rnd(max(0, 840 - (ux - lx)) / 2)
                # Only a strip free above and below grows in y.
                free = not any(o[1] < ux and lx < o[3] and uy_ly for o in strips
                    for uy_ly in [o[2] == ly or o[0] == uy])
                grow_y = rnd(max(0, 840 - (uy - ly)) / 2) if free else 0
                hvi.append((lx - grow_x, ly - grow_y, ux + grow_x, uy + grow_y))
        shapes(layers.hvi, rects_close(hvi, 700))

        # CONT, MCON
        cuts(layers.licon1, self.of(*self.DIFFCUT, "pc_cut"), 0, 170, 170)
        cuts(layers.mcon, self.of("mcon"), 0, 170, 190)
        # Slots of the precision resistors' contacts. Magic's "short" slot axis
        # swaps where a 2 um slot fits across in both directions (xpc_horiz), and
        # lies across the contact, along its smaller side if only one row fits.
        for r in rects_of_cells(*rects_cells(self.of("xpc"))) if self.of("xpc") else []:
            width, height = r[2] - r[0], r[3] - r[1]
            short, long = ((2000, 350), (190, 520)) if min(width, height) > 2014 else ((190, 520), (2000, 350))
            strip = short[0] + 160 <= min(width, height) < 2*short[0] + short[1] + 160
            vertical = height > width if strip else height >= width
            along_x, along_y = (short, long) if vertical else (long, short)
            nx, x0 = slots_along(r[0], r[2], *along_x)
            ny, y0 = slots_along(r[1], r[3], *along_y)
            for i in range(nx):
                for j in range(ny):
                    x, y = x0 + i*sum(along_x), y0 + j*sum(along_y)
                    l % LayoutRect(layer=layers.licon1, rect=Rect4I(x, y, x + along_x[0], y + along_y[0]))

        # NPC
        npc = []
        for r in self.of("pc_cut"):
            nx = (r[2] - r[0] + 170) // 340
            ny = (r[3] - r[1] + 170) // 340
            x0 = r[0] + 5 * ((r[2] - r[0] - nx*170 - (nx - 1)*170) // 10)
            y0 = r[1] + 5 * ((r[3] - r[1] - ny*170 - (ny - 1)*170) // 10)
            npc += [rect_grow((x0 + i*340, y0 + j*340, x0 + i*340 + 170, y0 + j*340 + 170), 100)
                for i in range(nx) for j in range(ny)]
        diffcut = [rect_grow(r, 90) for r in self.of(*self.DIFFCUT)]
        npc = rects_close(rects_subtract(rects_close(npc, 270), diffcut), 270)
        shapes(layers.npc, rects_close(npc, 265))
        shapes(layers.npc, rects_close([rect_grow(r, 95) for r in self.of("xpc") + polyres], 265))

M1_MIN_AREA = 83000  # m1.6, in nm²

@dataclass(frozen=True)
class MosRules:
    """Rules of a device of magic's MOS generator (sky130::ruleset and *_draw), in nm."""
    gate_type: str
    diff_type: str
    diff_contact_type: str
    plus_diff_type: str
    plus_contact_type: str
    sub_type: str = "psub"
    dev_sub_type: str = ""
    guard_sub_type: str = ""
    poly_surround: int = 80
    diff_surround: int = 60
    gate_to_diffcont: int = 145
    gate_to_polycont: int = 275
    gate_extension: int = 130
    diff_extension: int = 290
    contact_size: int = 170
    via_size: int = 170
    metal_surround: int = 80
    sub_surround: int = 180
    diff_spacing: int = 280
    poly_spacing: int = 210
    diff_poly_space: int = 75
    diff_gate_space: int = 200
    metal_spacing: int = 230
    diff_tap_space: int = None
    min_effl: int = 0
    min_allc: int = 0
    guard_sub_surround: int = 0
    diff_overlap_cont: int = 0
    dev_sub_dist: int = 0
    dev_sub_space: int = 0
    sub_surround_dev: int = None
    id_type: str = ""
    id_surround: int = 0

def box(x: int, y: int, e: int, w: int, n: int, s: int) -> tuple:
    """Box at (x, y) grown by the given amounts, as magic's box grow."""
    return (x - w, y - s, x + e, y + n)

def bbox_of(rects: list) -> tuple:
    return (min(e[0] for e in rects), min(e[1] for e in rects), max(e[2] for e in rects), max(e[3] for e in rects))

def via_extent(full: int, via_size: int, coverage: str) -> tuple:
    """Length of a via row of coverage percent of full and its offset from
    the center. A coverage of "+50" or "-50" anchors it at the lower or upper end."""
    length = max(full * abs(int(coverage)) / 100, via_size)
    end = (full - via_size) / 2
    anchor = str(coverage)[0]
    if anchor == "+":
        return length, length / 2 - end
    if anchor == "-":
        return length, end - length / 2
    return length, 0

def mcon_draw(p: Paint, r: tuple, vert: bool) -> tuple:
    """As sky130::mcon_draw, returns the m1 rect."""
    p.paint("mcon", r)
    if vert or r[2] - r[0] < r[3] - r[1]:
        return p.paint("m1", (r[0] - 30, r[1] - 60, r[2] + 30, r[3] + 60))
    return p.paint("m1", (r[0] - 60, r[1] - 30, r[2] + 60, r[3] + 30))

def draw_contact(p: Paint, x: int, y: int, w: int, h: int, s: int, o: int, size: int,
    atype: str, ctype: str, vert: bool) -> tuple:
    """As sky130::draw_contact, returns the rect of atype. Contacts on substrate
    diffusions are surrounded along their length only."""
    w, h = rnd(max(w, size) / 2), rnd(max(h, size) / 2)
    p.paint(ctype, (x - w, y - h, x + w, y + h))
    if atype in ("psd", "nsd"):
        ext = p.paint(atype, box(x, y, w, w, h + s, h + s) if vert else box(x, y, w + s, w + s, h, h))
    else:
        ext = p.paint(atype, box(x, y, w + s, w + s, h + s, h + s))
    p.paint("li", box(x, y, w, w, h + o, h + o) if vert else box(x, y, w + o, w + o, h, h))
    return ext

def guard_ring(p: Paint, cell: Cell, r: MosRules, gw: int, gh: int):
    """As sky130::guard_ring, returns its li rects."""
    size, ms = r.contact_size, r.metal_surround
    ds = 0 if r.plus_diff_type in ("psd", "nsd") else r.diff_surround
    hx, hw, hh = rnd(size / 2), rnd(gw / 2), rnd(gh / 2)
    difft = size + 2*ds
    hdifft, hdiffw, hdiffh = rnd(difft / 2), rnd((gw + difft) / 2), rnd((gh + difft) / 2)
    sides = (box(0, hh, hdiffw, hdiffw, hdifft, hdifft), box(0, -hh, hdiffw, hdiffw, hdifft, hdifft),
        box(hw, 0, hdifft, hdifft, hdiffh, hdiffh), box(-hw, 0, hdifft, hdifft, hdiffh, hdiffh))
    for side in sides:
        p.paint(r.plus_diff_type, side)
        if r.guard_sub_surround > 0:
            p.paint(r.guard_sub_type or r.sub_type, rect_grow(side, r.guard_sub_surround))
    ring = []
    if cell.full_metal:
        hmetw, hmeth = rnd((gw + size) / 2), rnd((gh + size) / 2)
        ring = [p.paint("li", box(0, hh, hmetw, hmetw, hx, hx)), p.paint("li", box(0, -hh, hmetw, hmetw, hx, hx)),
            p.paint("li", box(hw, 0, hx, hx, hmeth, hmeth)), p.paint("li", box(-hw, 0, hx, hx, hmeth, hmeth))]

    ch = max((gh - size - 2*(ms + r.metal_spacing)) * cell.rlcov / 100, size)
    cw = max((gw - size - 2*(ms + r.metal_spacing)) * cell.tbcov / 100, size)
    args = (ds, ms, size, r.plus_diff_type, r.plus_contact_type)
    if cell.tbcov > 0:
        if cell.gtc:
            draw_contact(p, 0, hh, cw, 0, *args, vert=False)
        if cell.gbc:
            draw_contact(p, 0, -hh, cw, 0, *args, vert=False)
    if cell.rlcov > 0:
        if cell.grc:
            draw_contact(p, hw, 0, 0, ch, *args, vert=True)
        if cell.glc:
            draw_contact(p, -hw, 0, 0, ch, *args, vert=True)

    for coverage, x, y, vert in ((cell.viagb, 0, -hh, False), (cell.viagt, 0, hh, False),
            (cell.viagr, hw, 0, True), (cell.viagl, -hw, 0, True)):
        if int(coverage) != 0:
            length, offset = via_extent((gh if vert else gw) - r.via_size, r.via_size, coverage)
            half = rnd(length / 2)
            if vert:
                mcon_draw(p, box(x, y + rnd(offset), rnd(r.via_size / 2), rnd(r.via_size / 2), half, half), True)
            else:
                mcon_draw(p, box(x + rnd(offset), y, half, half, rnd(r.via_size / 2), rnd(r.via_size / 2)), False)

    p.paint("boundary", (-hw, -hh, hw, hh))
    if r.sub_type != "psub":
        p.paint(r.sub_type, rect_grow((-hw, -hh, hw, hh), hx + ds + r.sub_surround))
    return ring

def mos_device(p: Paint, cell: Cell, r: MosRules, x: int, y: int, w: int, l: int,
    evens: bool, topc: bool, botc: bool) -> dict:
    """
    As sky130::mos_device: one finger at (x, y). Returns its bounding box and
    the shapes making up its terminals.
    """
    hw, hl = rnd(w / 2), rnd(l / 2)
    he = r.min_effl / 2
    if cell.nf == 1 or he < l / 2:
        he = l / 2
    he = rnd(he)
    g2d, g2p = r.gate_to_diffcont, r.gate_to_polycont

    p.paint(r.diff_type, box(x, y, hl + rnd(max(r.diff_extension, g2d)), hl + rnd(max(r.diff_extension, g2d)), hw, hw))
    if r.gate_extension > g2p:
        stem_n = stem_s = r.gate_extension
    else:
        stem_n = g2p if topc else r.gate_extension
        stem_s = g2p if botc else r.gate_extension
    stem = p.paint("poly", box(x, y, hl, hl, hw + rnd(stem_n), hw + rnd(stem_s)))
    ext = [stem]

    # Rule 1: diffusion dogbone
    ddover = 0
    cdwmin = r.contact_size + 2*r.diff_surround
    if w < cdwmin:
        cgrow = r.diff_poly_space - (g2d - cdwmin / 2)
        if cgrow > 0:
            g2d += cgrow
        ddover = (cdwmin - w) / 2
    # Rule 2: poly dogbone
    gporig = g2p
    cplmin = r.contact_size + 2*r.poly_surround
    if l < cplmin:
        cgrow = r.diff_poly_space - (g2p - cplmin / 2)
        if cgrow > 0:
            g2p += cgrow
    # Rule 3: both dogboned
    if w < cdwmin and l < cplmin:
        g2p += (cplmin - w) / 2
    # Rule 4: overlapping poly contacts
    if cell.poverlap and cell.m > 1 and g2p - gporig < ddover:
        g2p = gporig + ddover

    cdwfull = w - 2*(r.diff_surround + r.diff_overlap_cont)
    cplfull = l - 2*r.poly_surround
    cdw = cdwfull * cell.diffcov / 100
    cpl = cplfull if cell.poverlap and cell.m > 1 else cplfull * cell.polycov / 100

    size_half = rnd(r.via_size / 2)
    dx = he + rnd(g2d)
    sd = {}
    for side, viatype in ((1, cell.viasrc if evens else cell.viadrn), (-1, cell.viadrn if evens else cell.viasrc)):
        cx = x + side*dx
        top = None
        if int(viatype) != 0:
            length, offset = via_extent(cdwfull, r.via_size, viatype)
            half = rnd(length / 2)
            top = mcon_draw(p, box(cx, y + rnd(offset), size_half, size_half, half, half), True)
        ext.append(draw_contact(p, cx, y, 0, cdw, r.diff_surround, r.metal_surround, r.contact_size,
            r.diff_type, r.diff_contact_type, True))
        li = (cx - rnd(r.contact_size / 2), y - rnd(max(cdw, r.contact_size) / 2) - r.metal_surround,
            cx + rnd(r.contact_size / 2), y + rnd(max(cdw, r.contact_size) / 2) + r.metal_surround)
        sd[side] = ("met1", top) if top is not None else ("li1", li)

    diffarea = bbox_of(ext)
    gate = []
    for present, side in ((topc, 1), (botc, -1)):
        if not present:
            continue
        cy = y + side*(hw + rnd(g2p))
        top = None
        if int(cell.viagate) != 0:
            length, offset = via_extent(cplfull, r.via_size, cell.viagate)
            half = rnd(length / 2)
            top = mcon_draw(p, box(x + rnd(offset), cy, half, half, size_half, size_half), False)
            if cell.gate_min_area:
                # The generator's pad fails m1.6 until routed.
                width = 5 * -(-M1_MIN_AREA // (5 * (top[3] - top[1])))
                if width > top[2] - top[0]:
                    grow = 5 * -(-(width - (top[2] - top[0])) // 10)
                    top = p.paint("m1", (top[0] - grow, top[1], top[2] + grow, top[3]))
        w_half, h_half = rnd(max(cpl, r.contact_size) / 2), rnd(r.contact_size / 2)
        p.paint("pc_cut", (x - w_half, cy - h_half, x + w_half, cy + h_half))
        ext.append(p.paint("poly", rect_grow((x - w_half, cy - h_half, x + w_half, cy + h_half), r.poly_surround)))
        li = p.paint("li", box(x, cy, w_half + r.metal_surround, w_half + r.metal_surround, h_half, h_half))
        gate.append(top if top is not None else li)

    gaterect = (x - hl, y - hw, x + hl, y + hw)
    p.paint(r.gate_type, gaterect)
    if r.sub_surround_dev is not None:
        ext.append(p.paint(r.dev_sub_type, rect_grow(gaterect, r.sub_surround_dev)))
    if r.dev_sub_type != "":
        sub = p.paint(r.dev_sub_type, rect_grow(diffarea, r.sub_surround))
        if r.dev_sub_dist > 0:
            ext.append(sub)
    return dict(bbox=bbox_of(ext), sd=sd, gate=gate, stem=stem)

def layoutgen_mos(cell: Cell, r: MosRules) -> Layout:
    """
    Layout generation function of the MOS devices and varactors, as magic's
    sky130::mos_draw: nf fingers in x, m rows in y, optional guard ring. Each
    distance is rounded to the 5 nm grid, as magic does, so w/nf and l must be
    multiples of 10 nm to be drawn as given.
    """
    check_grid(cell, R("10n"), "l")
    if (cell.w / cell.nf) / R("10n") != int((cell.w / cell.nf) / R("10n")):
        raise ParameterError(f"w/nf = {cell.w / cell.nf} must be a multiple of 10n.")
    l = Layout(ref_layers=SKY130().layers, cell=cell, symbol=cell.symbol)
    layers = l.ref_layers
    p = Paint()

    w, L = int(cell.w / cell.nf / R("1n")), int(cell.l / R("1n"))
    nf, m = cell.nf, cell.m
    poverlap, doverlap = cell.poverlap, cell.doverlap
    topc, botc = cell.topc or poverlap, cell.botc or poverlap
    intc = nf > 1 and L < r.min_allc
    if intc:
        topc = botc = True
        poverlap = False
    size, ds, ps = r.contact_size, r.diff_surround, r.poly_surround
    diff_tap_space = r.diff_spacing if r.diff_tap_space is None else r.diff_tap_space

    # Device dimensions, from one device drawn on a scratch Paint.
    bbox = mos_device(Paint(), cell, r, 0, 0, w, L, True, topc, botc)["bbox"]
    fw, fh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    lw, lh = bbox[2] + bbox[0], bbox[3] + bbox[1]

    if r.dev_sub_dist > 0:
        poverlap = doverlap = False
        dx = fw + max(r.dev_sub_space, r.poly_spacing)
        dy = fh + max(r.dev_sub_space, r.poly_spacing)
    else:
        dy = fh - (2*ps + size) if poverlap else fh + r.poly_spacing
        dx = fw - (2*ds + size) if doverlap else fw + r.diff_spacing

    corex = (nf - 1)*dx + fw
    corey = (m - 1)*dy + fh
    corellx = (corex - fw + lw) / 2
    corelly = (corey - fh + lh) / 2
    if not topc and w < size + 2*ds:
        corey += (size + 2*ds - w) / 2

    if cell.guard or r.id_type:
        if r.dev_sub_dist > 0 and r.dev_sub_dist + r.sub_surround > diff_tap_space:
            gx = corex + 2*(r.dev_sub_dist + ds) + size
        else:
            gx = corex + 2*(diff_tap_space + ds) + size
        if r.dev_sub_dist > 0 and r.dev_sub_dist + r.sub_surround > r.diff_gate_space:
            gy = corey + 2*(r.dev_sub_dist + ds) + size
        else:
            gy = corey + 2*(r.diff_gate_space + ds) + size
        # With a small dogboned diffusion and a missing poly contact, the
        # guard ring distance may be limited by diffusion spacing.
        sdiff = (size + 2*ds - w) / 2 + diff_tap_space - (r.gate_extension + r.diff_gate_space)
        if sdiff > 0:
            if not topc:
                gy += sdiff
                corelly += sdiff / 2
            if not botc:
                gy += sdiff
                corelly -= sdiff / 2
    ring = guard_ring(p, cell, r, gx, gy) if cell.guard else []
    if r.id_type:
        p.paint(r.id_type, rect_grow(box(0, 0, rnd(gx / 2), rnd(gx / 2), rnd(gy / 2), rnd(gy / 2)), r.id_surround))

    # Fingers from the left, rows from the bottom. Without a top or bottom
    # contact on every finger, the contacts alternate along x and y.
    l.poly = PathNode()
    l.sd = PathNode()
    sd_by_x = {}
    gate_pin = None
    x0, y0 = -rnd(corellx), -rnd(corelly)
    for i in range(nf):
        for j in range(m):
            top, bot = topc, botc
            if intc:
                top, bot = (i + j) % 2 == 1, (i + j) % 2 == 0
            dev = mos_device(p, cell, r, x0 + i*dx, y0 + j*dy, w, L, i % 2 == 1, top, bot)
            if j == 0:
                l.poly[i] = LayoutRect(layer=layers.poly, rect=Rect4I(*dev["stem"]))
                for layer, rect in dev["sd"].values():
                    sd_by_x[(rect[0] + rect[2]) // 2] = layer, rect
                if i == 0:
                    gate_contacted = bool(dev["gate"])
                    gate_pin = dev["gate"][0] if gate_contacted else dev["stem"]

    p.draw(l)
    for i, x in enumerate(sorted(sd_by_x)):
        layer, rect = sd_by_x[x]
        l.sd[i] = LayoutRect(layer=layers[layer], rect=Rect4I(*rect))
    # s on the even regions, d on the odd ones, as in ihp130. (Magic names
    # them the other way around, so its viasrc is our viadrn.) Without
    # doverlap each finger has regions of its own, mirrored from finger to
    # finger: s, d, d, s, ...
    l.sd[0].create_pin(cell.symbol.s)
    l.sd[1].create_pin(cell.symbol.d)
    if not gate_contacted:
        gate_layer = layers.poly
    else:
        gate_layer = layers.met1 if int(cell.viagate) != 0 else layers.li1
    (l % LayoutRect(layer=gate_layer, rect=Rect4I(*gate_pin))).create_pin(cell.symbol.g)
    if r.dev_sub_type == "nwell":
        # The well of the first device, not a side of the guard ring's.
        sd = l.sd[0].rect
        l.nwell = LayoutRect(layer=layers.nwell, rect=Rect4I(*next(w for w in p.of("nwell")
            if w[0] <= sd.lx and w[1] <= sd.ly and sd.ux <= w[2] and sd.uy <= w[3])))
    if ring:
        l.guard = LayoutRect(layer=layers.li1, rect=Rect4I(*ring[0]))
        l.guard.create_pin(cell.symbol.b)
    elif r.dev_sub_type == "nwell":
        l.nwell.create_pin(cell.symbol.b)
    return l

class GuardRing(SimLeafCell):
    """Guard ring options of magic's generators (sky130::guard_ring), with their defaults."""
    guard = Parameter(bool, default=True) #: Guard ring
    glc = Parameter(bool, default=True) #: Guard ring contacts on the left
    grc = Parameter(bool, default=True) #: Guard ring contacts on the right
    gtc = Parameter(bool, default=True) #: Guard ring contacts on the top
    gbc = Parameter(bool, default=True) #: Guard ring contacts on the bottom
    tbcov = Parameter(int, default=100) #: Top and bottom guard ring contact coverage in percent
    rlcov = Parameter(int, default=100) #: Left and right guard ring contact coverage in percent
    full_metal = Parameter(bool, default=True) #: Continuous li1 guard ring
    #: mcon coverage in percent of the guard ring's bottom, top, right and left side
    viagb = Parameter(str, default="0")
    viagt = Parameter(str, default="0")
    viagr = Parameter(str, default="0")
    viagl = Parameter(str, default="0")

class Mos(GuardRing):
    """
    The usual parameters are l, w, nf and m, mirroring the SG13G2 devices.
    The remaining parameters are simulation-only overrides for the BSIM4
    model's diffusion parasitics and stress effects; unset, ad/as/pd/ps are
    derived from w/nf/diff_ext at netlist time and the rest fall back to the
    model subcircuit's defaults.
    """
    l = Parameter(R) #: Length
    w = Parameter(R) #: Width
    nf = Parameter(int, default=1) #: Number of fingers
    m = Parameter(int, default=1) #: Multiplier (parallel devices)
    diff_ext = Parameter(R, optional=True) #: Diffusion extension for drain/source (default 265 nm)
    ad = Parameter(R, optional=True) #: Drain area (auto-calculated if unset)
    as_ = Parameter(R, optional=True) #: Source area (auto-calculated if unset)
    pd = Parameter(R, optional=True) #: Drain perimeter (auto-calculated if unset)
    ps = Parameter(R, optional=True) #: Source perimeter (auto-calculated if unset)
    nrd = Parameter(R, optional=True) #: Drain diffusion squares for series R
    nrs = Parameter(R, optional=True) #: Source diffusion squares for series R
    sa = Parameter(R, optional=True) #: OD-to-poly distance, one side (stress model)
    sb = Parameter(R, optional=True) #: OD-to-poly distance, other side (stress model)
    sd = Parameter(R, optional=True) #: Poly-to-poly distance for multi-finger (stress model)

    # Layout options of magic's generator (sky130::mos_draw), with its defaults:
    topc = Parameter(bool, default=True) #: Top poly contact
    botc = Parameter(bool, default=True) #: Bottom poly contact
    diffcov = Parameter(int, default=100) #: Diffusion contact coverage in percent
    polycov = Parameter(int, default=100) #: Poly contact coverage in percent
    poverlap = Parameter(bool, default=False) #: Overlap poly contacts of adjacent rows
    doverlap = Parameter(bool, default=True) #: Overlap diffusion contacts of adjacent fingers
    #: mcon coverage in percent of source, drain and gate. "+50" and "-50"
    #: anchor it at one end.
    viasrc = Parameter(str, default="100")
    viadrn = Parameter(str, default="100")
    viagate = Parameter(str, default="100")
    #: Widen the gate's met1 pads to the m1.6 minimum area, unlike the generator
    gate_min_area = Parameter(bool, default=True)

    # Dimension minimums (poly.1a, difftap.2 per finger).
    min_l = R("150n")
    min_w = R("420n")

    @classmethod
    def params_check(cls, params):
        l, w, nf, m = params['l'], params['w'], params['nf'], params['m']
        if l is None or w is None:
            return
        if nf < 1:
            raise ParameterError("nf must be at least 1.")
        if m < 1:
            raise ParameterError("m must be at least 1.")
        if l < cls.min_l:
            raise ParameterError(f"l = {l} below the poly.1a minimum of {cls.min_l}.")
        if w/nf < cls.min_w:
            raise ParameterError(f"w/nf = {w/nf} below the difftap.2 minimum"
                f" channel width of {cls.min_w} per finger.")
        # The layouts draw l and w/nf as given, so they must be on the
        # manufacturing grid.
        grid = R("5n")
        if l / grid != int(l / grid) or w / nf / grid != int(w / nf / grid):
            raise ParameterError(f"l = {l} and w/nf = {w/nf} must be multiples of {grid}.")

    def diffusion_params(self) -> dict:
        """ad/as/pd/ps for an interdigitated S-G-D-G-S-... layout, taking
        explicitly set parameters over the derived values."""
        diff_ext = self.diff_ext if self.diff_ext is not None else R("0.265u")
        # w is the total width, each finger (and diffusion region) is w/nf wide.
        wf = self.w / self.nf

        # Number of drain/source diffusion regions:
        # nf=1: S-G-D (1 drain, 1 source)
        # nf=2: S-G-D-G-S (1 drain, 2 sources)
        # nf=3: S-G-D-G-S-G-D (2 drains, 2 sources)
        n_drain = (self.nf + 1) // 2
        n_source = (self.nf + 2) // 2

        # Perimeter: 2×diff_ext per region (sides facing isolation), plus a
        # wf contribution from edge diffusions only. Edge diffusion count:
        # - odd nf: 1 drain edge, 1 source edge
        # - even nf: 0 drain edges (internal), 2 source edges
        n_edge_drain = 1 if self.nf % 2 == 1 else 0
        n_edge_source = 1 if self.nf % 2 == 1 else 2

        return {
            # Area: each diffusion region is wf × diff_ext
            'ad': self.ad if self.ad is not None else n_drain * wf * diff_ext,
            'as_': self.as_ if self.as_ is not None else n_source * wf * diff_ext,
            'pd': self.pd if self.pd is not None else 2 * n_drain * diff_ext + n_edge_drain * wf,
            'ps': self.ps if self.ps is not None else 2 * n_source * diff_ext + n_edge_source * wf,
        }

    def ngspice_save_params(self):
        # BSIM4 operating-point outputs:
        return ["gm", "gds", "vth", "vdsat", "id", "vgs", "vds"]

    def ngspice_internal_device(self):
        # The PDK netlists a model subcircuit around a single BSIM4 device
        # named m<model_name>; needed to save/read device parameters (see
        # Simulator._param_save_directives).
        return f"m{self.model_name}"

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlist_setup)
        pins = [inst.symbol.d, inst.symbol.g, inst.symbol.s, inst.symbol.b]
        if netlister.lvs:
            # KLayout's SPICE reader wants plain SI values on an M card,
            # matching the mos4 devices the LVS deck extracts.
            netlister.add(
                netlister.name_obj(inst, prefix="M"),
                netlister.portmap(inst, pins),
                self.model_name,
                *spice_params({
                    'l': self.l,
                    'w': self.w,
                    'm': self.m,
                }))
            return
        # sky130 uses ".option scale=1.0u", so ngspice scales:
        # - linear dimensions (l, w, pd, ps, sa, sb, sd) by 1e-6
        # - areas (ad, as) by 1e-12
        # We pre-scale from SI to µm/µm² so ngspice gets the right values.
        diffusion = self.diffusion_params()
        params = {
            'l': self.l * R('1e6'),
            'w': self.w * R('1e6'),
            'nf': self.nf,
            # m is ngspice's parallel-device multiplier on the instance,
            # mult only scales the model's Monte-Carlo mismatch sigma.
            'm': self.m,
            'mult': self.m,
            'ad': diffusion['ad'] * R('1e12'),
            'as': diffusion['as_'] * R('1e12'),
            'pd': diffusion['pd'] * R('1e6'),
            'ps': diffusion['ps'] * R('1e6'),
        }
        # Unset advanced parameters are left to the model subcircuit's
        # defaults (all zero: no series resistance, no stress model).
        for name, scale in (('nrd', R(1)), ('nrs', R(1)),
                ('sa', R('1e6')), ('sb', R('1e6')), ('sd', R('1e6'))):
            value = getattr(self, name)
            if value is not None:
                params[name] = value * scale
        netlister.add(
            netlister.name_obj(inst, prefix="x"),
            netlister.portmap(inst, pins),
            self.model_name,
            *spice_params(params))

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_mos(self, self.rules)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("1u"), l=cls.min_l)] if hasattr(cls, "model_name") else []

NFET = dict(gate_type="nfet", diff_type="ndiff", diff_contact_type="ndc", plus_diff_type="psd",
    plus_contact_type="psc", min_effl=185, min_allc=260)
PFET = dict(gate_type="pfet", diff_type="pdiff", diff_contact_type="pdc", plus_diff_type="nsd",
    plus_contact_type="nsc", sub_type="nwell", dev_sub_type="nwell", gate_to_polycont=320,
    min_effl=185, min_allc=260)
MVNFET = dict(gate_type="mvnfet", diff_type="mvndiff", diff_contact_type="mvndc", plus_diff_type="mvpsd",
    plus_contact_type="mvpsc", diff_spacing=310, diff_tap_space=380, diff_gate_space=380)

@public
class Nmos(Mos):
    """1.8 V NMOS."""
    model_name = "sky130_fd_pr__nfet_01v8"
    rules = MosRules(**NFET)

    # Reuse the generic MOS symbol viewgen (not the class: inheriting from
    # generic_mos.Nmos would also drag in its defaulted l/w parameters).
    symbol = generic_mos.Nmos.symbol

@public
class NmosLvt(Nmos):
    """1.8 V low-threshold NMOS."""
    model_name = "sky130_fd_pr__nfet_01v8_lvt"
    rules = MosRules(**NFET | dict(gate_type="nfetlvt"))
    min_l = R("150n")

@public
class NmosHv(Nmos):
    """5 V NMOS (g5v0d10v5)."""
    model_name = "sky130_fd_pr__nfet_g5v0d10v5"
    rules = MosRules(**MVNFET)
    min_l = R("500n")

@public
class Nmos05v0Nvt(Nmos):
    """5 V native NMOS."""
    model_name = "sky130_fd_pr__nfet_05v0_nvt"
    rules = MosRules(**MVNFET | dict(gate_type="mvnnfet", diff_spacing=300))
    min_l = R("900n")

@public
class Nmos03v3Nvt(Nmos):
    """3.3 V native NMOS."""
    model_name = "sky130_fd_pr__nfet_03v3_nvt"
    rules = MosRules(**MVNFET | dict(gate_type="nnfet", diff_spacing=300))
    min_l = R("500n")

@public
class Pmos(Mos):
    """1.8 V PMOS."""
    model_name = "sky130_fd_pr__pfet_01v8"
    rules = MosRules(**PFET)

    symbol = generic_mos.Pmos.symbol

@public
class PmosLvt(Pmos):
    """1.8 V low-threshold PMOS."""
    model_name = "sky130_fd_pr__pfet_01v8_lvt"
    rules = MosRules(**PFET | dict(gate_type="pfetlvt"))
    min_l = R("350n")

@public
class PmosHvt(Pmos):
    """1.8 V high-threshold PMOS."""
    model_name = "sky130_fd_pr__pfet_01v8_hvt"
    rules = MosRules(**PFET | dict(gate_type="pfethvt"))

@public
class PmosHv(Pmos):
    """5 V PMOS (g5v0d10v5)."""
    model_name = "sky130_fd_pr__pfet_g5v0d10v5"
    rules = MosRules(gate_type="mvpfet", diff_type="mvpdiff", diff_contact_type="mvpdc",
        plus_diff_type="mvnsd", plus_contact_type="mvnsc", sub_type="nwell", dev_sub_type="nwell",
        guard_sub_surround=330, gate_to_polycont=320, diff_spacing=310, diff_tap_space=380,
        diff_gate_space=380)
    min_l = R("500n")

def met1_min_area_rect(mcon_rect: Rect4I, grow_axis: str) -> tuple:
    """
    met1 rect over an mcon array with m1.4/m1.5 enclosures, stretched along
    grow_axis (on the manufacturing grid) if needed to reach the m1.6
    minimum area.
    """
    mg = 5  # manufacturing grid
    encl, encl_end = 30, 60  # m1.4, m1.5
    if grow_axis == 'y':
        fix_lo = mcon_rect.lx - encl
        fix_hi = mcon_rect.ux + encl
        grow_lo, grow_hi = mcon_rect.ly, mcon_rect.uy
    else:
        fix_lo = mcon_rect.ly - encl
        fix_hi = mcon_rect.uy + encl
        grow_lo, grow_hi = mcon_rect.lx, mcon_rect.ux
    span = grow_hi - grow_lo + 2*encl_end
    min_span = -(-M1_MIN_AREA // (fix_hi - fix_lo))
    span = max(span, -(-min_span // mg) * mg)
    grow = (span - (grow_hi - grow_lo)) // 2 // mg * mg
    if grow_axis == 'y':
        return (fix_lo, grow_lo - grow, fix_hi, grow_lo - grow + span)
    else:
        return (grow_lo - grow, fix_lo, grow_lo - grow + span, fix_hi)

def layoutgen_tap(cell: Cell, length: R, width: R, nwell: bool):
    layers = SKY130().layers
    l = Layout(ref_layers=layers, cell=cell)
    s = Solver(l)

    L = int(length/R("1n"))
    W = int(width/R("1n"))

    l.tap = LayoutRect(layer=layers.tap)
    s.constrain(l.tap.size == (L, W))
    s.constrain(l.tap.southwest == (0, 0))

    # N+ tap connects an nwell, P+ tap the substrate (nsd.5b/psd.5b):
    implant_layer = layers.nsdm if nwell else layers.psdm
    l.implant = LayoutRect(layer=implant_layer)
    s.constrain(l.implant.center == l.tap.center)
    s.constrain(l.implant.size == l.tap.size + Vec2I(250, 250))  # nsd.5a/psd.5a

    if nwell:
        l.nwell = LayoutRect(layer=layers.nwell)
        s.constrain(l.nwell.center == l.tap.center)
        # Enclosure of difftap.8/difftap.10, width of nwell.1:
        s.constrain(l.nwell.width == max(L + 360, 840))
        s.constrain(l.nwell.height == max(W + 360, 840))

    # l.li.rect/l.m1.rect are assigned after solve() from the contact stack,
    # which needs the solved geometry, so the undefined-attribute check is deferred.
    l.li = LayoutRect(layer=layers.li1)
    l.m1 = LayoutRect(layer=layers.met1)
    s.solve(allow_undefined=True)

    # licon.1, licon.2, licon.7:
    licon_rect = makevias(l, l.tap.rect, layers.licon1,
        size=Vec2I(170, 170),
        spacing=Vec2I(170, 170),
        margin=Vec2I(120, 120),
        )
    # li1 over the licon array, extended for li.5 end enclosure:
    l.li.rect = (licon_rect.lx, licon_rect.ly - 80, licon_rect.ux, licon_rect.uy + 80)

    # ct.1, ct.2:
    mcon_rect = makevias(l, l.li.rect, layers.mcon,
        size=Vec2I(170, 170),
        spacing=Vec2I(190, 190),
        margin=Vec2I(0, 0),
        )
    l.m1.rect = met1_min_area_rect(mcon_rect, grow_axis='y')

    return l


@public
class Ntap(Cell):
    l = Parameter(R)  #: Length
    w = Parameter(R)  #: Width

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_tap(self, self.l, self.w, nwell=True)

    @classmethod
    def discoverable_instances(cls):
        return [cls(l=R("0.7u"), w=R("0.7u"))]

@public
class Ptap(Cell):
    l = Parameter(R)  #: Length
    w = Parameter(R)  #: Width

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_tap(self, self.l, self.w, nwell=False)

    @classmethod
    def discoverable_instances(cls):
        return [cls(l=R("0.7u"), w=R("0.7u"))]


@dataclass(frozen=True)
class ResRules:
    """Rules of a device of magic's resistor generator (sky130::ruleset and *_draw), in nm."""
    res_type: str
    end_type: str
    end_surround: int
    end_spacing: int
    res_to_endcont: int
    res_spacing: int
    end_contact_type: str = ""
    end_to_end_space: int = None
    end_contact_size: int = None
    plus_diff_type: str = "psd"
    plus_contact_type: str = "psc"
    sub_type: str = "psub"
    guard_sub_type: str = ""
    guard_sub_surround: int = 0
    res_diff_spacing: int = 0
    mask_clearance: int = 0
    overlap_compress: int = 0
    well_res_type: str = ""
    well_res_overlap: int = 0
    end_overlap_cont: int = 0
    n_guard_end_spacing: int = None      #: end_spacing with n_guard, if different
    n_guard_res_diff_spacing: int = None #: res_diff_spacing with n_guard, if different
    rho: float = 0              #: Typical-corner sheet resistance in ohms
    dw: float = 0               #: Effective width offset of the model in um
    term: float = 0             #: Contact resistance in ohms
    diff_surround: int = 60
    contact_size: int = 170
    via_size: int = 170
    metal_surround: int = 80
    metal_spacing: int = 230
    sub_surround: int = 180
    #: Extent of the model's body beyond l at each end, in nm
    lvs_extend: int = 0
    #: The guard ring is the bulk terminal (a well), not the common substrate.
    bulk_on_guard: bool = False

LAYER_LI1, LAYER_MET1 = "li1", "met1"
METAL_OF = {"li": "li1", "m1": "met1", "m2": "met2", "m3": "met3", "m4": "met4", "m5": "met5"}

def res_end(p: Paint, cell: Cell, r: ResRules, x: int, y: int, epl: int, cpl: int, size: int, hesz: int, hepl: int,
    via_side: int = 0) -> tuple:
    """End material and contact of a resistor at (x, y), returns its rects. A nonzero
    via_side draws mcons reaching towards the body, which lies in that direction."""
    ext = [p.paint(r.end_type, box(x, y, hepl, hepl, hesz, hesz))]
    # A metal resistor's end is its own metal.
    term = (METAL_OF.get(r.end_type), ext[0]) if r.end_type in METAL_OF else None
    if r.end_contact_type:
        half_w, half_h = rnd(max(cpl, size) / 2) + r.metal_surround, rnd(size / 2)
        term = (LAYER_LI1, (x - half_w, y - half_h, x + half_w, y + half_h))
        if via_side != 0 and cell.vias:
            ch = max(r.res_to_endcont, r.via_size)
            half_w, half_via = rnd(max(epl, r.via_size) / 2), rnd(r.via_size / 2)
            far, near = half_via, rnd(ch - r.via_size / 2)
            term = (LAYER_MET1, mcon_draw(p, box(x, y, half_w, half_w, near if via_side > 0 else far,
                far if via_side > 0 else near), False))
        ext.append(draw_contact(p, x, y, cpl, 0, r.end_surround, r.metal_surround, size,
            r.end_type, r.end_contact_type, False))
    return ext, term

def res_device(p: Paint, cell: Cell, r: ResRules, x: int, y: int, w: int, l: int) -> dict:
    """As sky130::res_device: one straight resistor at (x, y)."""
    size = r.contact_size if r.end_contact_size is None else r.end_contact_size
    hw, hl = rnd(w / 2), rnd(l / 2)
    well = r.well_res_overlap > 0
    reach = rnd(r.res_to_endcont)
    if well:
        reach += rnd(r.well_res_overlap + size / 2 + r.end_surround)
    end = r.well_res_type if well else r.end_type
    ext = [p.paint(end, (x - hw, y + hl, x + hw, y + hl + reach)),
        p.paint(end, (x - hw, y - hl - reach, x + hw, y - hl))]
    if well:
        # The end of a row overlapping the row below paints over its body.
        p.types[r.res_type] = rects_subtract(p.of(r.res_type), ext)
    p.paint(r.res_type, (x - hw, y - hl, x + hw, y + hl))

    epl = w - 2*r.end_surround
    if well:
        epl -= 2*r.well_res_overlap
    cpl = epl * cell.endcov / 100 if not cell.roverlap and cell.endcov > 0 else epl
    if epl - cpl < 2*r.end_overlap_cont:
        cpl = epl - 2*r.end_overlap_cont
    hepl = rnd(epl / 2 + r.end_surround)
    hesz = size / 2 if r.end_type in ("psd", "nsd") else size / 2 + r.end_surround
    hesz = rnd(hesz)

    terms = {}
    for side in (1, -1):
        rects, term = res_end(p, cell, r, x, y + side*(hl + rnd(r.res_to_endcont)), epl, cpl, size, hesz, hepl,
            via_side=-side)
        ext += rects
        terms[side] = term
    return dict(bbox=bbox_of(ext), terms=terms)

def res_snake_device(p: Paint, cell: Cell, r: ResRules, x: int, y: int, w: int, l: int) -> dict:
    """As sky130::res_snake_device: nx stripes joined at alternating ends, at (x, y)."""
    size = r.contact_size if r.end_contact_size is None else r.end_contact_size
    nf = cell.nx
    hw, hl = rnd(w / 2), rnd(l / 2)
    well = r.well_res_overlap > 0
    epl = w - 2*r.end_surround
    if well:
        epl -= 2*r.well_res_overlap
    cpl = epl * cell.endcov / 100 if cell.endcov > 0 else epl
    hepl, hesz = rnd(epl / 2 + r.end_surround), rnd(size / 2 + r.end_surround)
    mc, reach = r.mask_clearance, rnd(r.res_to_endcont)
    extra = rnd(r.well_res_overlap + size / 2 + r.end_surround) if well else 0
    end = r.well_res_type if well else r.end_type

    terms = {}
    def terminal(tx, direction, side):
        """Contact at the stripe's end, with the portion between them."""
        cy = y + direction*(hl + mc + reach)
        rects, terms[side] = res_end(p, cell, r, tx, cy, epl, cpl, size, hesz, hepl)
        edge = y + direction*hl
        if mc > 0:
            p.paint(r.res_type, (tx - hw, min(edge, edge + direction*mc), tx + hw, max(edge, edge + direction*mc)))
        y0, y1 = edge + direction*mc, edge + direction*(mc + reach + extra)
        rects.append(p.paint(end, (tx - hw, min(y0, y1), tx + hw, max(y0, y1))))
        return rects

    ext = terminal(x, -1, -1)
    deltax = r.res_spacing + w
    deltay = l - w
    ly = y - hl
    for i in range(nf):
        tx = x + i*deltax
        # With a negative clearance, the first contact reaches into its stripe.
        p.paint(r.res_type, (tx - hw, ly - min(mc, 0) if i == 0 else ly, tx + hw, y + hl))
        if i < nf - 1:
            cy = ly + (deltay if i % 2 == 0 else 0)
            p.paint(r.res_type, (tx - hw, cy, tx - hw + deltax, cy + w))
    ext.append((x - hw, ly, x + (nf - 1)*deltax + hw, y + hl))
    ext += terminal(x + (nf - 1)*deltax, 1 if nf % 2 == 1 else -1, 1)
    return dict(bbox=bbox_of(ext), terms=terms)

def layoutgen_res(cell: Cell, r: ResRules) -> Layout:
    """Layout generation function of the resistors, as sky130::res_draw."""
    check_grid(cell, R("10n"), "w", "l")
    l = Layout(ref_layers=SKY130().layers, cell=cell, symbol=cell.symbol)
    layers = l.ref_layers
    p = Paint()
    r = cell.guard_rules(r)

    if cell.snake and cell.w > cell.l:
        raise ParameterError("A snake needs w <= l (magic silently sets w = l instead).")
    w, L = int(cell.w / R("1n")), int(cell.l / R("1n"))
    snake = cell.snake and cell.nx > 1
    nx = 1 if snake else cell.nx
    device = res_snake_device if snake else res_device
    size = r.contact_size if r.end_contact_size is None else r.end_contact_size
    if snake and L - w < -r.mask_clearance:
        raise ParameterError("The first link of this snake runs over its first contact (magic then loses the contact's cuts).")
    bbox = device(Paint(), cell, r, 0, 0, w, L)["bbox"]
    fw, fh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    lw, lh = bbox[2] + bbox[0], bbox[3] + bbox[1]

    space = r.end_spacing if r.end_to_end_space is None else r.end_to_end_space
    if cell.roverlap and snake and cell.nx % 2 == 1 and cell.m > 1:
        dy = fh - r.overlap_compress
    elif not cell.roverlap or snake:
        dy = fh + space
    else:
        dy = fh - (2*(r.end_surround + r.well_res_overlap) + size)
    dx = fw + r.res_spacing

    corex, corey = (nx - 1)*dx + fw, (cell.m - 1)*dy + fh
    corellx, corelly = (corex - fw + lw) / 2, (corey - fh + lh) / 2

    ring = []
    if cell.guard:
        guard_ds = 0 if r.plus_diff_type in ("psd", "nsd") else r.diff_surround
        gx = corex + 2*(r.res_diff_spacing + guard_ds) + r.contact_size
        gy = corey + 2*(r.end_spacing + guard_ds) + r.contact_size
        ring = guard_ring(p, cell, r, gx, gy)

    x0, y0 = -rnd(corellx), -rnd(corelly)
    terms = {}
    for i in range(nx):
        for j in range(cell.m):
            dev = device(p, cell, r, x0 + i*dx, y0 + j*dy, w, L)
            if i == 0 and j == 0:
                terms = dev["terms"]
    p.draw(l)

    # Pins on the ends of the first device. A metal resistor's ends are its
    # own metal, reaching res_to_endcont beyond the body.
    for side, pin in ((1, cell.symbol.p), (-1, cell.symbol.n)):
        if terms[side] is not None:
            (l % LayoutRect(layer=layers[terms[side][0]], rect=Rect4I(*terms[side][1]))).create_pin(pin)
    if ring and r.bulk_on_guard:
        (l % LayoutRect(layer=layers.li1, rect=Rect4I(*ring[0]))).create_pin(cell.symbol[cell.bulk])
    return l


class Res(GuardRing):
    """
    Shared base class of the resistors. The layout options are the ones of
    magic's generator (sky130::res_draw), with its defaults: nx and m repeat
    the device in x and y, or nx folds it into a snake of nx stripes joined at
    alternating ends. Metal resistors have no guard ring.
    """
    l = Parameter(R)
    w = Parameter(R)
    m = Parameter(int, default=1)
    nx = Parameter(int, default=1)  #: Repeats in x, or stripes of a snake
    snake = Parameter(bool, default=False)
    roverlap = Parameter(bool, default=False)  #: Overlap the ends of adjacent devices
    endcov = Parameter(int, default=100)  #: End contact coverage in percent
    vias = Parameter(bool, default=True)  #: mcons on the end contacts

    bulk = None  # third model pin, if any
    lvs_model = None  # name in the LVS deck, if it differs from the model's

    @classmethod
    def params_check(cls, params):
        check_counts(params, "m", "nx")
        for name in ("l", "w"):
            minimum = getattr(cls, f"min_{name}", None)
            if None not in (params[name], minimum) and params[name] < minimum:
                raise ParameterError(f"{name} = {params[name]} below the minimum of {minimum}.")

    def nominal_resistance(self) -> float:
        """
        Nominal typical-corner resistance in ohms of the body that lvs_length
        gives, with the sheet resistance, end resistance and effective width
        of the ngspice models, for all repeats in parallel.
        """
        r = self.rules
        w = float(self.w) * 1e6 + r.dw
        l = float(self.lvs_length()) * 1e6 - 2 * r.lvs_extend * 1e-3
        return (2*r.term + l*r.rho) / w / self.parallel()

    def guard_rules(self, r: ResRules) -> ResRules:
        return r

    def lvs_length(self) -> R:
        """Length of the extracted body: its area over its width."""
        r = self.rules
        if self.snake and self.nx > 1:
            return self.nx * self.l + (self.nx - 1) * R(f"{r.res_spacing}n") \
                + 2 * R(f"{r.mask_clearance + r.lvs_extend}n")
        return self.l + 2 * R(f"{r.lvs_extend}n")

    def ngspice_current_pins(self):
        return {"i": "p"}

    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)
        s % SymbolAnnotation(key='r', value=str(R(f'{self.nominal_resistance():.3g}')))

        s.n = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, orient=South, show_arrow=False, show_label=False, rotate_label=False)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, orient=North, show_arrow=False, show_label=False, rotate_label=False)
        s % SymbolPoly(vertices=resistor_zigzag())
        if self.bulk:
            s[self.bulk] = Pin(pos=Vec2R(4, 2), pintype=PinType.Inout, orient=East, show_arrow=False, rotate_label=False)
            s % SymbolPoly(vertices=[Vec2R(2.6, 2), Vec2R(4, 2)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlist_setup)
        pins = [inst.symbol.p, inst.symbol.n]
        if self.bulk:
            pins.append(inst.symbol[self.bulk])
        if netlister.lvs:
            # KLayout compares the extracted W and L, in SI units on the card.
            netlister.add(
                netlister.name_obj(inst, prefix="R"),
                netlister.portmap(inst, pins),
                self.lvs_model or self.model_name,
                *spice_params({"w": self.w, "l": self.lvs_length(), "m": self.parallel()}),
            )
            return
        netlister.add(
            netlister.name_obj(inst, prefix=self.spice_prefix),
            netlister.portmap(inst, pins),
            self.model_name,
            *spice_params(self.spice_params()),
        )

    def spice_params(self) -> dict:
        # With ".option scale=1.0u" the dimensions are given in um.
        return {"w": self.w * R("1e6"), "l": self.lvs_length() * R("1e6"), "m": self.parallel()}

    def parallel(self) -> int:
        return self.m * (1 if self.snake else self.nx)

    spice_prefix = "R"

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_res(self, self.rules)

    @classmethod
    def discoverable_instances(cls):
        return [cls(l=cls.min_l, w=cls.min_w)] if hasattr(cls, "model_name") else []


def resistor_zigzag() -> list[Vec2R]:
    """The zigzag line of the resistor symbols, as in ihp130."""
    height, half, start = R(2), R("0.625"), R(1)
    return [
        Vec2R(2, 0),
        Vec2R(2, start),
        Vec2R(2 - half, start + height / 12),
        Vec2R(2 + half, start + height * 3 / 12),
        Vec2R(2 - half, start + height * 5 / 12),
        Vec2R(2 + half, start + height * 7 / 12),
        Vec2R(2 - half, start + height * 9 / 12),
        Vec2R(2 + half, start + height * 11 / 12),
        Vec2R(2, start + height),
        Vec2R(2, 4),
    ]

def res_po_rules(res_type: str, rho: float, term: float, mask_clearance: int, end_spacing=480,
    res_diff_spacing=480) -> ResRules:
    """Precision poly resistors: one contact slot in the xpc end, no well."""
    return ResRules(res_type=res_type, end_type="xpc", end_contact_type="xpc", end_surround=80,
        n_guard_end_spacing=525, n_guard_res_diff_spacing=785,
        end_contact_size=190, end_spacing=end_spacing, end_to_end_space=520, res_to_endcont=1985,
        res_spacing=480, res_diff_spacing=res_diff_spacing, mask_clearance=mask_clearance,
        overlap_compress=360, rho=rho, term=term, lvs_extend=60)

class PolyGuard(Res):
    """The poly resistors' guard ring options of magic's generator."""
    hv_guard = Parameter(bool, default=False)  #: 5 V guard ring
    n_guard = Parameter(bool, default=False)  #: N+ guard ring in an N-well

    def guard_rules(self, r: ResRules) -> ResRules:
        kind = ("mvn" if self.n_guard else "mvp") if self.hv_guard else ("n" if self.n_guard else "p")
        changes = dict(plus_diff_type=f"{kind}sd", plus_contact_type=f"{kind}sc",
            guard_sub_surround=330 if self.hv_guard else 180)
        if self.n_guard:
            changes["sub_type"] = "nwell"
            if r.n_guard_end_spacing is not None:
                changes.update(end_spacing=r.n_guard_end_spacing, res_diff_spacing=r.n_guard_res_diff_spacing)
        return replace(r, **changes)

class ResPo(PolyGuard):
    """
    Shared base class of the precision poly resistors, whose width is fixed by
    the model. Their ends are slots in the xpc layer with the model's b as a
    third pin on the substrate, named sub.
    """
    bulk = "sub"
    spice_prefix = "x"
    min_l = R("0.5u")

    def spice_params(self) -> dict:
        # mult only scales the model's mismatch, m is ngspice's parallel count.
        return {"l": self.lvs_length() * R("1e6"), "m": self.parallel(), "mult": self.parallel()}

    @classmethod
    def params_check(cls, params):
        super().params_check(params)
        if params['w'] is not None and params['w'] != cls.width:
            raise ParameterError(f"w of {cls.__name__} must be {cls.width}.")

    @classmethod
    def discoverable_instances(cls):
        return [cls(l=R("2u"), w=cls.width)] if hasattr(cls, "width") else []

@public
class Rpoly(PolyGuard):
    """Salicided generic polysilicon resistor (res_generic_po, 48.2 ohm/sq)."""
    model_name = "sky130_fd_pr__res_generic_po"
    # res_spacing is the generator's 210 raised to poly.9, see the docs.
    rules = ResRules(res_type="mrp1", end_type="poly", end_contact_type="pc_cut", end_surround=80,
        end_spacing=480, end_to_end_space=520, res_to_endcont=1985, res_spacing=480, res_diff_spacing=480,
        mask_clearance=520, overlap_compress=360, rho=48.2)
    min_l, min_w = R("1.65u"), R("0.33u")

@public
class RhighPo0p69(ResPo):
    """P+ poly resistor of width 0.69 um (res_high_po_0p69, 319.8 ohm/sq)."""
    model_name = "sky130_fd_pr__res_high_po_0p69"
    width = R("0.69u")
    rules = res_po_rules("xhrpoly", 319.8, 194.82, 520)

@public
class RhighPo0p35(RhighPo0p69):
    """P+ poly resistor of width 0.35 um (res_high_po_0p35, 319.8 ohm/sq)."""
    model_name = "sky130_fd_pr__res_high_po_0p35"
    width = R("0.35u")
    rules = res_po_rules("xhrpoly", 319.8, 194.82, -2160)

@public
class RhighPo1p41(RhighPo0p69):
    """P+ poly resistor of width 1.41 um (res_high_po_1p41, 319.8 ohm/sq)."""
    model_name = "sky130_fd_pr__res_high_po_1p41"
    width = R("1.41u")

@public
class RhighPo2p85(RhighPo0p69):
    """P+ poly resistor of width 2.85 um (res_high_po_2p85, 319.8 ohm/sq)."""
    model_name = "sky130_fd_pr__res_high_po_2p85"
    width = R("2.85u")

@public
class RhighPo5p73(RhighPo0p69):
    """P+ poly resistor of width 5.73 um (res_high_po_5p73, 319.8 ohm/sq)."""
    model_name = "sky130_fd_pr__res_high_po_5p73"
    width = R("5.73u")

@public
class RxhighPo0p35(ResPo):
    """P- poly resistor of width 0.35 um (res_xhigh_po_0p35, 2000 ohm/sq)."""
    model_name = "sky130_fd_pr__res_xhigh_po_0p35"
    width = R("0.35u")
    rules = res_po_rules("uhrpoly", 2000, 188.2, 520)

@public
class RxhighPo0p69(RxhighPo0p35):
    """P- poly resistor of width 0.69 um (res_xhigh_po_0p69, 2000 ohm/sq)."""
    model_name = "sky130_fd_pr__res_xhigh_po_0p69"
    width = R("0.69u")

@public
class RxhighPo1p41(RxhighPo0p35):
    """P- poly resistor of width 1.41 um (res_xhigh_po_1p41, 2000 ohm/sq)."""
    model_name = "sky130_fd_pr__res_xhigh_po_1p41"
    width = R("1.41u")

@public
class RxhighPo2p85(RxhighPo0p35):
    """P- poly resistor of width 2.85 um (res_xhigh_po_2p85, 2000 ohm/sq)."""
    model_name = "sky130_fd_pr__res_xhigh_po_2p85"
    width = R("2.85u")

@public
class RxhighPo5p73(RxhighPo0p35):
    """P- poly resistor of width 5.73 um (res_xhigh_po_5p73, 2000 ohm/sq)."""
    model_name = "sky130_fd_pr__res_xhigh_po_5p73"
    width = R("5.73u")

class ResDiff(Res):
    """Shared base class of the diffusion resistors, with the model's b as third pin."""
    spice_prefix = "x"
    min_l, min_w = R("2.1u"), R("0.42u")

    def spice_params(self) -> dict:
        return {"w": self.w * R("1e6"), "l": self.lvs_length() * R("1e6"), "m": self.parallel(), "mult": self.parallel()}

DIFF_RES = dict(end_surround=60, end_spacing=440, res_to_endcont=370, res_diff_spacing=440,
    mask_clearance=220, overlap_compress=360)

@public
class Rnd(ResDiff):
    """N+ diffusion resistor (res_generic_nd, 120 ohm/sq), ``sub`` on the substrate."""
    model_name = "sky130_fd_pr__res_generic_nd"
    bulk = "sub"
    rules = ResRules(res_type="rdn", end_type="ndiff", end_contact_type="ndc", res_spacing=300,
        rho=120, dw=0.017, **DIFF_RES)

@public
class Rpd(ResDiff):
    """P+ diffusion resistor (res_generic_pd, 197 ohm/sq), ``nw`` on its well."""
    model_name = "sky130_fd_pr__res_generic_pd"
    bulk = "nw"
    rules = ResRules(res_type="rdp", end_type="pdiff", end_contact_type="pdc", plus_diff_type="nsd",
        plus_contact_type="nsc", sub_type="nwell", res_spacing=280, rho=197, dw=0.034, bulk_on_guard=True, **DIFF_RES)

@public
class RndHv(Rnd):
    """5 V N+ diffusion resistor (res_generic_nd__hv, 120 ohm/sq), ``sub`` on the substrate."""
    model_name = "sky130_fd_pr__res_generic_nd__hv"
    lvs_model = "sky130_fd_pr__res_generic_nd_hv"
    rules = ResRules(res_type="mvrdn", end_type="mvndiff", end_contact_type="mvndc", plus_diff_type="mvpsd",
        plus_contact_type="mvpsc", res_spacing=300, rho=114, dw=0.017, **DIFF_RES)

@public
class RpdHv(Rpd):
    """5 V P+ diffusion resistor (res_generic_pd__hv, 197 ohm/sq), ``nw`` on its well."""
    model_name = "sky130_fd_pr__res_generic_pd__hv"
    lvs_model = "sky130_fd_pr__res_generic_pd_hv"
    rules = ResRules(res_type="mvrdp", end_type="mvpdiff", end_contact_type="mvpdc", plus_diff_type="mvnsd",
        plus_contact_type="mvnsc", sub_type="nwell", guard_sub_surround=330, res_spacing=300, rho=191, dw=0.034,
        bulk_on_guard=True, **DIFF_RES)

class ResMetal(Res):
    """Shared base class of the metal resistors: a marker over the metal, no contacts or guard ring."""
    guard = Parameter(bool, default=False)

METAL_RES = dict(end_surround=0, end_spacing=0, res_to_endcont=200)

@public
class Rl1(ResMetal):
    """li1 resistor (res_generic_l1)."""
    model_name = "sky130_fd_pr__res_generic_l1"
    rules = ResRules(res_type="rli", end_type="li", end_to_end_space=230, res_spacing=230, rho=12.2, dw=0.017, **METAL_RES)
    min_l, min_w = R("0.17u"), R("0.17u")

@public
class Rm1(ResMetal):
    """met1 resistor (res_generic_m1)."""
    model_name = "sky130_fd_pr__res_generic_m1"
    rules = ResRules(res_type="rm1", end_type="m1", end_to_end_space=280, res_spacing=140, rho=0.125, dw=-0.039, **METAL_RES)
    min_l, min_w = R("0.14u"), R("0.14u")

@public
class Rm2(ResMetal):
    """met2 resistor (res_generic_m2)."""
    model_name = "sky130_fd_pr__res_generic_m2"
    rules = ResRules(res_type="rm2", end_type="m2", end_to_end_space=280, res_spacing=140, rho=0.125, dw=-0.039, **METAL_RES)
    min_l, min_w = R("0.14u"), R("0.14u")

@public
class Rm3(ResMetal):
    """met3 resistor (res_generic_m3)."""
    model_name = "sky130_fd_pr__res_generic_m3"
    rules = ResRules(res_type="rm3", end_type="m3", end_to_end_space=280, res_spacing=140, rho=0.047, dw=-0.025, **METAL_RES)
    min_l, min_w = R("0.3u"), R("0.3u")

@public
class Rm4(ResMetal):
    """met4 resistor (res_generic_m4)."""
    model_name = "sky130_fd_pr__res_generic_m4"
    rules = ResRules(res_type="rm4", end_type="m4", end_to_end_space=280, res_spacing=140, rho=0.047, dw=-0.025, **METAL_RES)
    min_l, min_w = R("0.3u"), R("0.3u")

@public
class Rm5(ResMetal):
    """met5 resistor (res_generic_m5)."""
    model_name = "sky130_fd_pr__res_generic_m5"
    rules = ResRules(res_type="rm5", end_type="m5", end_to_end_space=1600, res_spacing=140, rho=0.0285, dw=-0.09, **METAL_RES)
    min_l, min_w = R("1.6u"), R("1.6u")

@public
class RisoPw(Res):
    """Isolated p-well resistor (res_iso_pw, 975 ohm/sq), ``nw`` on the DNWell around it."""
    model_name = "sky130_fd_pr__res_iso_pw"
    bulk = "nw"
    spice_prefix = "x"
    rules = ResRules(res_type="rpw", end_type="psd", end_contact_type="psc", well_res_type="pwell",
        plus_diff_type="nsd", plus_contact_type="nsc", sub_type="dnwell", sub_surround=230,
        guard_sub_type="nwell", guard_sub_surround=630, end_surround=60, end_spacing=630,
        end_to_end_space=1150, end_overlap_cont=60, end_contact_size=530, overlap_compress=-170,
        res_to_endcont=265, res_spacing=1400, res_diff_spacing=630, well_res_overlap=200,
        rho=3816, term=992, bulk_on_guard=True)
    min_l, min_w = R("26.5u"), R("2.65u")

    # The model takes the parameters of the diffusion resistors' models.
    spice_params = ResDiff.spice_params


def layoutgen_cmim(cell: Cell) -> Layout:
    """Generate the SKY130 met3/met4 MiM capacitor (cap_mim_m3_1)."""
    if cell.m != 1:
        raise ParameterError("m != 1 not supported for layout.")

    layers = SKY130().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    tr = tech_rules
    width = int(cell.w / R("1n"))
    length = int(cell.l / R("1n"))
    if width < tr['capm_width'] or length < tr['capm_width']:
        raise ParameterError("w and l must be at least capm.1 minimum width.")

    l.capm = LayoutRect(layer=layers.capm, rect=(0, 0, width, length))
    l.term_n = LayoutRect(
        layer=layers.met3,
        rect=(-tr['capm_encl_met3'], -tr['capm_encl_met3'],
            width + tr['capm_encl_met3'], length + tr['capm_encl_met3']),
    )
    via_bbox = makevias(l, l.capm.rect, layers.via3,
        size=Vec2I(tr['via3_size'], tr['via3_size']),
        spacing=Vec2I(tr['via3_space'], tr['via3_space']),
        margin=Vec2I(tr['capm_encl_via3'], tr['capm_encl_via3']),
        )
    l.term_p = LayoutRect(
        layer=layers.met4,
        rect=(
            via_bbox.lx - tr['met4_encl_via3'],
            via_bbox.ly - tr['met4_encl_via3'],
            via_bbox.ux + tr['met4_encl_via3'],
            via_bbox.uy + tr['met4_encl_via3'],
        ),
    )

    # The n pin must sit on the met3 ring outside capm: the LVS deck attaches
    # met3 labels to met3.not(capm) only.
    l.term_n_edge = LayoutRect(
        layer=layers.met3,
        rect=(-tr['capm_encl_met3'], -tr['capm_encl_met3'],
            width + tr['capm_encl_met3'], 0),
    )
    l.term_n_edge.create_pin(cell.symbol.n)
    l.term_p.create_pin(cell.symbol.p)

    return l


@public
class Cmim(SimLeafCell):
    """SKY130 MiM capacitor between met3 and met4 (cap_mim_m3_1)."""
    l = Parameter(R, default=R("5u"))
    w = Parameter(R, default=R("5u"))
    m = Parameter(int, default=1)

    def ngspice_current_pins(self):
        return {"i": "p"}

    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.n = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)

        s % SymbolPoly(vertices=[Vec2R(1.25, 1.8), Vec2R(2.75, 1.8)])
        s % SymbolPoly(vertices=[Vec2R(1.25, 2.2), Vec2R(2.75, 2.2)])
        s % SymbolPoly(vertices=[Vec2R(2, 2.2), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(2, 1.8), Vec2R(2, 0)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlist_setup)
        pins = [inst.symbol.p, inst.symbol.n]
        if netlister.lvs:
            # The LVS deck's MIMCap class compares plate area and perimeter
            # and disables the C value. KLayout reads A/P in SI units.
            netlister.add(
                netlister.name_obj(inst, prefix="C"),
                netlister.portmap(inst, pins),
                "sky130_fd_pr__model__cap_mim",
                *spice_params({
                    "a": self.w * self.l,
                    "p": (self.w + self.l) * 2,
                }))
            return
        netlister.add(
            netlister.name_obj(inst, prefix="x"),
            netlister.portmap(inst, pins),
            "sky130_fd_pr__cap_mim_m3_1",
            *spice_params({
                "w": self.w * R("1e6"),
                "l": self.l * R("1e6"),
                "mf": self.m,
            }))

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_cmim(self)

    @classmethod
    def discoverable_instances(cls):
        return [cls()]

@public
class Inv(Cell):
    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        # Define pins for the inverter
        s.vdd = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, orient=North)
        s.vss = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, orient=South)
        s.a = Pin(pos=Vec2R(0, 2), pintype=PinType.In, orient=West)
        s.y = Pin(pos=Vec2R(4, 2), pintype=PinType.Out, orient=East)

        # Draw the inverter symbol
        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1, 2)])  # Input line
        s % SymbolPoly(vertices=[Vec2R(3.25, 2), Vec2R(4, 2)])  # Output line
        s % SymbolPoly(vertices=[Vec2R(1, 1), Vec2R(1, 3), Vec2R(2.75, 2), Vec2R(1, 1)])  # Triangle
        s % SymbolArc(pos=Vec2R(3, 2), radius=R(0.25))  # Output bubble

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)

        return s

    @viewgen_noctx
    def schematic(self) -> Schematic:
        s = Schematic(cell=self, symbol=self.symbol)
        s.a = Net(pin=self.symbol.a)
        s.y = Net(pin=self.symbol.y)
        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)

        nmos = Nmos(l="0.15u", w="0.495u").symbol
        pmos = Pmos(l="0.15u", w="0.99u").symbol

        s.pd = SchemInstance(nmos.portmap(s=s.vss, b=s.vss, g=s.a, d=s.y), pos=Vec2R(3, 2))
        s.pu = SchemInstance(pmos.portmap(s=s.vdd, b=s.vdd, g=s.a, d=s.y), pos=Vec2R(3, 8))

        s.vdd % SchemPort(pos=Vec2R(2, 13), orient=East, ref=self.symbol.vdd)
        s.vss % SchemPort(pos=Vec2R(2, 1), orient=East, ref=self.symbol.vss)
        s.a % SchemPort(pos=Vec2R(1, 7), orient=East, ref=self.symbol.a)
        s.y % SchemPort(pos=Vec2R(9, 7), orient=West, ref=self.symbol.y)

        s.vss % SchemWire([Vec2R(2, 1), Vec2R(5, 1), Vec2R(8, 1), Vec2R(8, 4), Vec2R(7, 4)])
        s.vss % SchemWire([Vec2R(5, 1), s.pd.pos + nmos.s.pos])
        s.vdd % SchemWire([Vec2R(2, 13), Vec2R(5, 13), Vec2R(8, 13), Vec2R(8, 10), Vec2R(7, 10)])
        s.vdd % SchemWire([Vec2R(5, 13), s.pu.pos + pmos.s.pos])
        s.a % SchemWire([Vec2R(3, 4), Vec2R(2, 4), Vec2R(2, 7), Vec2R(2, 10), Vec2R(3, 10)])
        s.a % SchemWire([Vec2R(1, 7), Vec2R(2, 7)])
        s.y % SchemWire([Vec2R(5, 6), Vec2R(5, 7), Vec2R(5, 8)])
        s.y % SchemWire([Vec2R(5, 7), Vec2R(9, 7)])

        s.outline = Rect4R(lx=0, ly=1, ux=10, uy=13)
        
        s.check(add_conn_points=True)
        s.place_annotations()
        return s

@public
class Ringosc(Cell):
    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.vdd = Pin(pintype=PinType.Inout, orient=North)
        s.vss = Pin(pintype=PinType.Inout, orient=South)
        s.y = Pin(pintype=PinType.Out, orient=East)

        s.place_pins(vpadding=2, hpadding=2)
        return s

    @viewgen_noctx
    def schematic(self) -> Schematic:
        s = Schematic(cell=self, symbol=self.symbol)

        s.y0 = Net()
        s.y1 = Net()
        s.y2 = Net(pin=self.symbol.y)
        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)

        inv = Inv().symbol
        s.i0 = SchemInstance(inv.portmap(vdd=s.vdd, vss=s.vss, a=s.y2, y=s.y0), pos=Vec2R(4, 2))
        s.i1 = SchemInstance(inv.portmap(vdd=s.vdd, vss=s.vss, a=s.y0, y=s.y1), pos=Vec2R(10, 2))
        s.i2 = SchemInstance(inv.portmap(vdd=s.vdd, vss=s.vss, a=s.y1, y=s.y2), pos=Vec2R(16, 2))

        s.vdd % SchemPort(pos=Vec2R(2, 7), orient=East)
        s.vss % SchemPort(pos=Vec2R(2, 1), orient=East)
        s.y2 % SchemPort(pos=Vec2R(22, 4), orient=West)

        s.outline = Rect4R(lx=0, ly=0, ux=24, uy=8)

        s.y0 % SchemWire(vertices=[s.i0.pos+inv.y.pos, s.i1.pos+inv.a.pos])
        s.y1 % SchemWire(vertices=[s.i1.pos+inv.y.pos, s.i2.pos+inv.a.pos])
        s.y2 % SchemWire(vertices=[s.i2.pos+inv.y.pos, Vec2R(21, 4), Vec2R(22, 4)])
        s.y2 % SchemWire(vertices=[Vec2R(21, 4), Vec2R(21, 8), Vec2R(3, 8), Vec2R(3, 4), s.i0.pos+inv.a.pos])

        s.vss % SchemWire(vertices=[Vec2R(2, 1), Vec2R(6, 1), Vec2R(12, 1), Vec2R(18, 1), Vec2R(18, 2)])
        s.vss % SchemWire(vertices=[Vec2R(6, 1), Vec2R(6, 2)])
        s.vss % SchemWire(vertices=[Vec2R(12, 1), Vec2R(12, 2)])

        s.vdd % SchemWire(vertices=[Vec2R(2, 7), Vec2R(6, 7), Vec2R(12, 7), Vec2R(18, 7), Vec2R(18, 6)])
        s.vdd % SchemWire(vertices=[Vec2R(6, 7), Vec2R(6, 6)])
        s.vdd % SchemWire(vertices=[Vec2R(12, 7), Vec2R(12, 6)])

        s.check(add_conn_points=True)
        s.place_annotations()
        return s

@public
class And2(Cell):
    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.vdd = Pin(pos=Vec2R(2.5, 5), pintype=PinType.Inout, orient=North)
        s.vss = Pin(pos=Vec2R(2.5, 0), pintype=PinType.Inout, orient=South)
        s.a = Pin(pos=Vec2R(0, 3), pintype=PinType.In, orient=West)
        s.b = Pin(pos=Vec2R(0, 2), pintype=PinType.In, orient=West)
        s.y = Pin(pos=Vec2R(5, 2.5), pintype=PinType.Out, orient=East)

        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1, 2)])
        s % SymbolPoly(vertices=[Vec2R(0, 3), Vec2R(1, 3)])
        s % SymbolPoly(vertices=[Vec2R(4, 2.5), Vec2R(5, 2.5)])
        s % SymbolPoly(vertices=[Vec2R(2.75, 1.25), Vec2R(1, 1.25), Vec2R(1, 3.75), Vec2R(2.75, 3.75)])
        s % SymbolArc(pos=Vec2R(2.75, 2.5), radius=R(1.25), angle_start=R(-0.25), angle_end=R(0.25))
        s.outline = Rect4R(lx=0, ly=0, ux=5, uy=5)

        return s

@public
class Or2(Cell):
    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.vdd = Pin(pos=Vec2R(2.5, 5), pintype=PinType.Inout, orient=North)
        s.vss = Pin(pos=Vec2R(2.5, 0), pintype=PinType.Inout, orient=South)
        s.a = Pin(pos=Vec2R(0, 3), pintype=PinType.In, orient=West)
        s.b = Pin(pos=Vec2R(0, 2), pintype=PinType.In, orient=West)
        s.y = Pin(pos=Vec2R(5, 2.5), pintype=PinType.Out, orient=East)

        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1.3, 2)])
        s % SymbolPoly(vertices=[Vec2R(0, 3), Vec2R(1.3, 3)])
        s % SymbolPoly(vertices=[Vec2R(4, 2.5), Vec2R(5, 2.5)])
        s % SymbolPoly(vertices=[Vec2R(1, 3.75), Vec2R(1.95, 3.75)])
        s % SymbolPoly(vertices=[Vec2R(1, 1.25), Vec2R(1.95, 1.25)])
        s % SymbolArc(pos=Vec2R(-1.02, 2.5), radius=R(2.4), angle_start=R(-0.085), angle_end=R(0.085))
        s % SymbolArc(pos=Vec2R(1.95, 1.35), radius=R(2.4), angle_start=R(0.08), angle_end=R(0.25))
        s % SymbolArc(pos=Vec2R(1.95, 3.65), radius=R(2.4), angle_start=R(-0.25), angle_end=R(-0.08))
        s.outline = Rect4R(lx=0, ly=0, ux=5, uy=5)

        return s

@public
def run_drc(l: Layout, use_tempdir: bool=True, feol: bool=True,
        beol: bool=True, offgrid: bool=True, density: bool=False) -> DrcReport:
    """Run the PDK's KLayout DRC decks over a layout.

    The sky130A_mr.drc deck covers widths, spacings and BEOL via enclosures.
    It lacks FEOL enclosure/spacing rules (licon, npc, implant and nwell
    enclosures), and the PDK has no KLayout antenna deck.

    Args:
        l: the Layout to check.
        use_tempdir: run in a temporary directory instead of ./drc.
        feol: enable the PDK deck's front-end-of-line checks.
        beol: enable the PDK deck's back-end-of-line checks.
        offgrid: enable the PDK deck's manufacturing grid/angle checks.
        density: also run the PDK's metal density deck. It measures over
            prBoundary, so the layout needs one.
    """
    directory = Directory()

    def flag(b):
        return "true" if b else "false"

    with rundir('drc', use_tempdir) as cwd:
        with open(cwd / "layout.gds", "wb") as f:
            write_gds(l, f, directory)

        klayout_shared_opts = dict(
            thr="1",
            top_cell=directory.name_subgraph(l),
            input="layout.gds",
        )

        def run_deck(deck, log, **opts):
            # The decks log to stdout (captured to a file), so a failure must
            # re-raise with the log before the tempdir removes it.
            try:
                klayout.run(deck, cwd, capture=log, **opts)
            except subprocess.CalledProcessError as e:
                text = (cwd / log).read_text(errors='replace')
                raise Exception(f"KLayout DRC run failed:\n{text}") from e

        run_deck(pdk().klayout_drc_deck, "main.log",
            report="main.lyrdb",
            feol=flag(feol),
            beol=flag(beol),
            offgrid=flag(offgrid),
            seal="false",
            floating_met="false",
            **klayout_shared_opts
            )
        report = DrcReport(ref_layout=l, top_cell_name=directory.name_subgraph(l))
        klayout.parse_rdb(cwd / "main.lyrdb", report, directory)

        if density:
            # Without a boundary, the deck divides by zero and flags nothing.
            flat = l.mutable_copy()
            flatten(flat)
            if not any(r.layer == l.ref_layers.prBoundary for r in flat.all(LayoutRect)):
                raise ValueError("The density deck needs a prBoundary.")
            run_deck(pdk().klayout_density_deck, "density.log", report="density.lyrdb", **klayout_shared_opts)
            klayout.parse_rdb(cwd / "density.lyrdb", report, directory)

        return report


@public
def run_lvs(layout: Layout, symbol: Symbol, use_tempdir: bool=True,
        substrate_net: str='vss') -> LvsReport:
    """
    Run LVS (Layout vs. Schematic) check.

    Args:
        layout: The Layout to check.
        symbol: The Symbol containing the reference schematic.
        use_tempdir: If True, use a temporary directory for intermediate files.
        substrate_net: Name of the net that ties the substrate (via p+ taps).
            The LVS deck models the substrate as a global net of this name
            and merges it with same-named labeled nets, so it must match the
            netlisted name of the ground net.
    """
    directory = klayout.LvsDirectory()
    nl = Netlister(directory, lvs=True)
    nl.netlist_hier_symbol(symbol)

    schematic = symbol.cell.schematic

    with rundir('lvs', use_tempdir) as cwd:
        (cwd / 'schematic.cir').write_text(nl.out())

        with open(cwd / 'layout.gds', "wb") as f:
            write_gds(layout, f, directory=directory)

        # Remove any report of a previous run in this directory, so a tool
        # failure below cannot be mistaken for a fresh result:
        (cwd / 'out.lvsdb').unlink(missing_ok=True)
        try:
            klayout.run(
                pdk().klayout_lvs_deck,
                str(cwd),
                capture='out.log',
                thr='1',
                run_mode='deep',
                lvs_sub=substrate_net,
                spice_net_names='true',
                spice_comments='false',
                net_only='false',
                top_lvl_pins='true',
                # Multi-finger devices are netlisted as one card, so parallel
                # extracted fingers must be combined:
                combine='true',
                purge='false',
                purge_nets='false',
                verbose='false',
                report='out.lvsdb',
                target_netlist='extracted.cir',
                input='layout.gds',
                schematic='schematic.cir',
                )
        except subprocess.CalledProcessError as e:
            # The deck exits nonzero on a netlist mismatch, which is a valid
            # LVS result reported through the lvsdb parsed below. Without an
            # lvsdb, klayout itself failed.
            if not (cwd / 'out.lvsdb').is_file():
                log = (cwd / 'out.log').read_text(errors='replace')
                raise Exception(f"KLayout LVS run failed:\n{log}") from e

        return klayout.parse_lvsdb(cwd / 'out.lvsdb', layout, schematic, directory)


@public
def run_magic(script, cwd, **kwargs):
    """
    Run a magic Tcl script with the PDK's magic technology, which includes
    the PDK's device generators (sky130A.tcl). The arguments are those of
    :func:`ordec.layout.magic.run`.
    """
    # The startup file loads the technology from PDK_ROOT/sky130A.
    magic.run(script, cwd, pdk().magic_rcfile, env={'PDK_ROOT': str(pdk().root.parent)}, **kwargs)


@public
def run_magic_drc(l: Layout, use_tempdir: bool=True) -> DrcReport:
    """
    Run the full DRC of the PDK's magic technology (sky130A.tech) over a
    layout.

    Args:
        l: the Layout to check.
        use_tempdir: run in a temporary directory instead of ./magic_drc.
    """
    directory = Directory()
    with rundir('magic_drc', use_tempdir) as cwd:
        with open(cwd / "layout.gds", "wb") as f:
            write_gds(l, f, directory)
        top = directory.name_subgraph(l)
        # Remove the report of a previous run in this directory, so a failure
        # below cannot be mistaken for a fresh result. magic.log goes with the
        # tempdir, so a failure re-raises with it.
        (cwd / "drc.txt").unlink(missing_ok=True)
        try:
            run_magic(magic.DRC_SCRIPT, cwd, capture="magic.log", gds="layout.gds", top=top, report="drc.txt")
        except subprocess.CalledProcessError as e:
            text = (cwd / "magic.log").read_text(errors='replace')
            raise Exception(f"Magic DRC run failed:\n{text}") from e
        report = DrcReport(ref_layout=l, top_cell_name=top)
        magic.parse_drc(cwd / "drc.txt", report, directory)
        return report
