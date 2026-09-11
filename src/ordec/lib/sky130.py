# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
import subprocess
from pathlib import Path
from public import public
import functools

from ..core import *
from ..schematic import spice_params, Netlister
from . import generic_mos
from .pdk_common import PdkDict, TechInfo, check_dir, check_file, rundir, format_si, OHM
from ..layout import makevias, write_gds
from ..layout import klayout
from ..layout.pnr import GridConfig, PdnSpec, PdnStripes, PdnVia
from ..schematic.spice_in import DeviceMapping

@functools.cache
def pdk() -> PdkDict:
    """Returns dictionary-like object with import PDK paths."""
    try:
        root = os.environ["ORDEC_PDK_SKY130A"]
    except KeyError:
        raise Exception("PDK requires environment variable ORDEC_PDK_SKY130A to be set.")
    pdk = PdkDict(root=check_dir(Path(root).resolve()))

    pdk.ngspice_lib = check_file(pdk.root / "libs.tech/ngspice/sky130.lib.spice")

    pdk.klayout_drc_deck = check_file(pdk.root / "libs.tech/klayout/drc/sky130A_mr.drc")
    pdk.klayout_lvs_deck = check_file(pdk.root / "libs.tech/klayout/lvs/sky130.lvs")

    return pdk

@functools.cache
def stdcell_pdk() -> PdkDict:
    """Paths of the sky130_fd_sc_hd standard-cell library.

    Separate from pdk() because a primitives-only sky130A install has no
    libs.ref, and only the P&R flow needs the standard cells.
    """
    lib = PdkDict(root=check_dir(pdk().root / "libs.ref/sky130_fd_sc_hd"))
    lib.lef = check_file(lib.root / "lef/sky130_fd_sc_hd.lef")
    lib.gds = check_file(lib.root / "gds/sky130_fd_sc_hd.gds")
    lib.spice = check_file(lib.root / "spice/sky130_fd_sc_hd.spice")
    return lib

#: FEOL enclosure/spacing checks missing from the PDK's KLayout deck,
#: shipped with ORDeC (see run_drc). The deck reads the values of these
#: tech_rules entries as -rd variables, in um.
supplement_drc_deck = Path(__file__).parent / "sky130_supplement.drc"
supplement_drc_rules = [
    'licon_space', 'licon_encl_diff_min', 'licon_encl_diff',
    'licon_encl_tap', 'licon_encl_poly_min', 'licon_encl_poly',
    'licon_psdm_space', 'licon_gate_space', 'licon_poly_diff_space',
    'licon_encl_npc', 'npc_gate_space', 'res_poly_space',
    'diff_ext_poly', 'poly_endcap', 'implant_encl',
    'implant_space_opposite', 'nwell_encl', 'ndiff_nwell_space',
    'ptap_nwell_space',
]

def netlist_setup(netlister):
    if netlister.lvs:
        return
    # The corner section of the PDK's lib file pulls in the MOSFET corner
    # deck plus the resistor/capacitor models and sets mc_mm_switch=0.
    corner = 'tt' if netlister.corner is None else netlister.corner
    netlister.add(".lib",f"\"{pdk().ngspice_lib}\"",corner)

# SKY130 has no machine-readable tech parameter file in the PDK (unlike
# SG13G2's sg13g2_tech_mod.json), so the rule values used by the layout
# generators, the supplementary DRC deck and cell-level layouts are recorded
# here. All values in nm, rule ids refer to the SkyWater periphery rules
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

def tech_nm(name: str) -> int:
    """Rule value from tech_rules in nm (areas nm^2), mirroring
    ihp130.tech_nm."""
    return tech_rules[name]

public(tech = TechInfo(
    manufacturing_grid=5,
    nominal_vdd=R("1.8"), # standard 1.8 V devices
    conductors=("diff", "tap", "poly", "li1", "met1", "met2", "met3",
        "met4", "met5", "capm", "cap2m"),
    via_connects={
        "licon1": ("diff", "tap", "poly", "li1"),
        "mcon": ("li1", "met1"),
        "via": ("met1", "met2"),
        "via2": ("met2", "met3"),
        "via3": ("met3", "met4", "capm"),
        "via4": ("met4", "met5", "cap2m"),
    },
    device_bodies=("diff", "tap", "capm", "cap2m"),
))

@public
class SKY130(Cell):
    @viewgen_noctx
    def layers(self):
        s = LayerStack(cell=self)

        s.unit = R('1n')

        # Frontend layers
        # ---------------

        s.nwell = Layer(
            gdslayer_shapes=GdsLayer(layer=64, data_type=20),
            style_fill=rgb_color("#268c6b"),
            )

        s.dnwell = Layer(
            gdslayer_shapes=GdsLayer(layer=64, data_type=18),
            style_fill=rgb_color("#8c8ca6"),
            )

        s.diff = Layer(
            gdslayer_shapes=GdsLayer(layer=65, data_type=20),
            style_fill=rgb_color("#00ff00"),
            )

        s.tap = Layer(
            gdslayer_shapes=GdsLayer(layer=65, data_type=44),
            style_fill=rgb_color("#ccb899"),
            )

        s.poly = Layer(
            gdslayer_shapes=GdsLayer(layer=66, data_type=20),
            style_fill=rgb_color("#bf4026"),
            )
        s.poly.pin = Layer(
            gdslayer_text=GdsLayer(layer=66, data_type=5),
            gdslayer_shapes=GdsLayer(layer=66, data_type=16),
            style_fill=rgb_color("#bf4026"),
            is_pinlayer=True,
            )

        s.poly.res = Layer(
            gdslayer_shapes=GdsLayer(layer=66, data_type=13),
            style_fill=rgb_color("#cc6633"),
            )

        s.licon1 = Layer(
            gdslayer_shapes=GdsLayer(layer=66, data_type=44),
            style_stroke=rgb_color("#00ffff"),
            style_crossrect=True,
            )

        s.npc = Layer(
            gdslayer_shapes=GdsLayer(layer=95, data_type=20),
            style_fill=rgb_color("#e6b8e6"),
            )

        s.nsdm = Layer(
            gdslayer_shapes=GdsLayer(layer=93, data_type=44),
            style_fill=rgb_color("#99b8d9"),
            )

        s.psdm = Layer(
            gdslayer_shapes=GdsLayer(layer=94, data_type=20),
            style_fill=rgb_color("#e8c8a0"),
            )

        s.hvtp = Layer(
            gdslayer_shapes=GdsLayer(layer=78, data_type=44),
            style_fill=rgb_color("#9999cc"),
            )

        s.lvtn = Layer(
            gdslayer_shapes=GdsLayer(layer=125, data_type=44),
            style_fill=rgb_color("#6b8c26"),
            )

        # Metal stack (li1 + met1..met5)
        # ------------------------------

        def addmetal(name, layer, color):
            setattr(s, name, Layer(
                gdslayer_shapes=GdsLayer(layer=layer, data_type=20),
                style_fill=color,
            ))
            getattr(s, name).pin = Layer(
                gdslayer_text=GdsLayer(layer=layer, data_type=5),
                gdslayer_shapes=GdsLayer(layer=layer, data_type=16),
                style_fill=color,
                is_pinlayer=True,
            )

        def addvia(name, layer, data_type, color):
            setattr(s, name, Layer(
                gdslayer_shapes=GdsLayer(layer=layer, data_type=data_type),
                style_stroke=color,
                style_crossrect=True,
            ))

        addmetal("li1", 67, rgb_color("#a6a6d9"))
        addvia("mcon", 67, 44, rgb_color("#ccccff"))
        addmetal("met1", 68, rgb_color("#39bfff"))
        addvia("via", 68, 44, rgb_color("#ff3736"))
        addmetal("met2", 69, rgb_color("#ccccd9"))
        addvia("via2", 69, 44, rgb_color("#9ba940"))
        addmetal("met3", 70, rgb_color("#d80000"))
        addvia("via3", 70, 44, rgb_color("#deac5e"))
        addmetal("met4", 71, rgb_color("#93e837"))
        addvia("via4", 71, 44, rgb_color("#ffe6bf"))
        addmetal("met5", 72, rgb_color("#dcd146"))

        # Other layers
        # ------------

        # Marker and pin-marker layers of the standard-cell GDS. The pwell
        # has no drawing layer (the p-substrate is implicit), only its pin
        # and label markers.
        s.nwell.pin = Layer(
            gdslayer_shapes=GdsLayer(layer=64, data_type=16),
            gdslayer_text=GdsLayer(layer=64, data_type=5),
            style_fill=rgb_color("#268c6b"),
            is_pinlayer=True,
            )
        s.pwell = Layer()
        s.pwell.pin = Layer(
            gdslayer_shapes=GdsLayer(layer=122, data_type=16),
            gdslayer_text=GdsLayer(layer=64, data_type=59),
            style_fill=rgb_color("#8c8ca6"),
            is_pinlayer=True,
            )
        s.poly.short = Layer(
            gdslayer_shapes=GdsLayer(layer=66, data_type=15),
            style_fill=rgb_color("#bf4026"),
            )
        s.met5.short = Layer(
            gdslayer_shapes=GdsLayer(layer=72, data_type=15),
            style_fill=rgb_color("#dcd146"),
            )
        s.areaid_standardc = Layer(
            gdslayer_shapes=GdsLayer(layer=81, data_type=4),
            style_stroke=rgb_color("#808080"),
            )
        s.areaid_diode = Layer(
            gdslayer_shapes=GdsLayer(layer=81, data_type=23),
            style_stroke=rgb_color("#808080"),
            )
        s.outline = Layer(
            gdslayer_shapes=GdsLayer(layer=236, data_type=0),
            style_stroke=rgb_color("#808080"),
            )

        s.capm = Layer(
            gdslayer_shapes=GdsLayer(layer=89, data_type=44),
            style_fill=rgb_color("#26a68b"),
            )

        s.cap2m = Layer(
            gdslayer_shapes=GdsLayer(layer=97, data_type=44),
            style_fill=rgb_color("#66a68b"),
            )

        s.TEXT = Layer(
            gdslayer_text=GdsLayer(layer=83, data_type=44),
            )

        s.prBoundary = Layer(
            gdslayer_shapes=GdsLayer(layer=235, data_type=4),
            style_fill=rgb_color("#9900e6"),
            style_stroke=rgb_color("#ff00ff"),
            )

        return s

    @viewgen_noctx
    def default_routing_spec(self):
        """
        SRouter parameters for the met1..met5 stack. Wire widths sit above
        the m1.1/m2.1/m3.1 minima, via cuts are the exact via.1a/via2.1a
        sizes, run-in pads cover the all-sides via enclosures (via.4a/b 55,
        via2.4 40, met3 over via2 65) with the wire supplying the endcap
        enclosure (via.5a/b, via2.5: 85), and standalone pads cover the
        endcap on all sides plus the m1.6/m3.6 minimum metal areas.

        met4 and met5 carry via stacks and power stripes rather than dense
        routing, so their pads are sized for the coarse via4 in one step:
        the via4.4 and m5.3 enclosures have no smaller endcap variant, so
        run-in and standalone pads coincide on both layers.
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
        # The met2 run-in pad covers via2's 40 all-sides enclosure and
        # via1's 55; the 85 endcap comes from the wire. At a met2/met3
        # turn via SRouter does not extend the met2 wire past the cut, so
        # such junctions need an explicit 370 met2 pad in the layout.
        addmetal(layers.met2, 170, 200, (370, 300), (280, 280))
        addvia(layers.via2, (200, 200))
        addmetal(layers.met3, 300, 200, (500, 500), (330, 330))
        addvia(layers.via3, (tech_nm('via3_size'), tech_nm('via3_size')))
        # met4 pads must enclose via4 (800) by 190 on all sides (via4.4),
        # which also covers via3's 100 (met4 over via3) by a wide margin.
        m4_pad = tech_nm('via4_size') + 2 * tech_nm('met4_encl_via4')
        addmetal(layers.met4, tech_nm('met4_width'),
            tech_nm('via4_size') // 2 + tech_nm('met4_encl_via4'),
            (m4_pad, m4_pad), (m4_pad, m4_pad))
        addvia(layers.via4, (tech_nm('via4_size'), tech_nm('via4_size')))
        m5_pad = tech_nm('via4_size') + 2 * tech_nm('met5_encl_via4')
        addmetal(layers.met5, tech_nm('met5_width'),
            tech_nm('via4_size') // 2 + tech_nm('met5_encl_via4'),
            (m5_pad, m5_pad), (m5_pad, m5_pad))

        return rs


def layoutgen_mos(cell: Cell, length: R, width: R, num_gates: int, nwell: bool) -> Layout:
    """
    Layout generation function shared for Nmos and Pmos cells.

    Each source/drain column is a full local-interconnect stack: licon1
    contacts in the diffusion, an li1 strip, mcon contacts and a met1 strip,
    so that sd[i] connects at met1 like the SG13G2 generator's sd strips.
    """
    layers = SKY130().layers
    l = Layout(ref_layers=layers, cell=cell)
    s = Solver(l)

    tr = tech_rules
    L = int(length/R("1n"))
    if int(width/R("1n")) % num_gates != 0:
        raise ParameterError("w must divide evenly into the finger count,"
            " otherwise drawn and netlisted width diverge.")
    W = int(width/R("1n") / num_gates)

    if cell.m != 1:
        raise ParameterError("m != 1 not supported for layout.")

    l.poly = PathNode()
    l.sd = PathNode()
    l.li = PathNode()

    sd_width = tr['licon_size']
    m1_width = sd_width + 2*tr['met1_encl_mcon']

    def add_sd(i):
        nonlocal l, s, x_cur
        # met1 strip, the connection point exposed to parent layouts:
        l.sd[i] = LayoutRect(layer=layers.met1)
        sd = l.sd[i]
        s.constrain(sd.west == (x_cur - tr['met1_encl_mcon'], l.diff.cy))
        s.constrain(sd.size == (m1_width, W))
        # li1 strip, flush with the licon column in x, extending past the
        # diffusion so li.5 (0.08 end enclosure of licon) is met:
        l.li[i] = LayoutRect(layer=layers.li1)
        li = l.li[i]
        s.constrain(li.west == (x_cur, l.diff.cy))
        s.constrain(li.size == (sd_width,
            W + 2*(tr['li_encl_licon_end'] - tr['licon_encl_diff'])))
        x_cur += sd_width

    def add_poly(i):
        nonlocal l, s, x_cur
        x_cur += tr['licon_gate_space']
        l.poly[i] = LayoutRect(layer=layers.poly)
        poly = l.poly[i]
        s.constrain(poly.west == (x_cur, l.diff.cy))
        s.constrain(poly.size == (L, W + 2*tr['poly_endcap']))
        s.constrain(poly.ly == 0)
        x_cur = poly.ux + tr['licon_gate_space']

    l.diff = LayoutRect(layer=layers.diff)
    s.constrain(l.diff.height == W)
    s.constrain(l.diff.lx == 0)
    x_cur = tr['licon_encl_diff']

    add_sd(0)
    for i in range(num_gates):
        add_poly(i)
        add_sd(i+1)

    s.constrain(l.diff.ux == x_cur + tr['licon_encl_diff'])

    # N+/P+ implant over the diffusion (nsd.5a/psd.5a):
    implant_layer = layers.psdm if nwell else layers.nsdm
    l.implant = LayoutRect(layer=implant_layer)
    s.constrain(l.implant.center == l.diff.center)
    s.constrain(l.implant.size == l.diff.size + Vec2I(2*tr['implant_encl'],
        2*tr['implant_encl']))

    if nwell:
        l.nwell = LayoutRect(layer=layers.nwell)
        s.constrain(l.nwell.center == l.diff.center)
        s.constrain(l.nwell.width == l.diff.width + 2*tr['nwell_encl'])
        s.constrain(l.nwell.height == max(W + 2*tr['nwell_encl'],
            tr['nwell_width']))

    s.solve()

    for i in range(num_gates + 1):
        li = l.li[i]
        # licon1 contacts within the diffusion (licon.5a/5c enclosure):
        makevias(l, Rect4I(li.lx, l.diff.ly, li.ux, l.diff.uy), layers.licon1,
            size=Vec2I(tr['licon_size'], tr['licon_size']),
            spacing=Vec2I(tr['licon_space'], tr['licon_space']),
            margin=Vec2I(0, tr['licon_encl_diff']),
            )
        # mcon contacts within the met1 strip (m1.4/m1.5 enclosure):
        makevias(l, l.sd[i].rect, layers.mcon,
            size=Vec2I(tr['mcon_size'], tr['mcon_size']),
            spacing=Vec2I(tr['mcon_space'], tr['mcon_space']),
            margin=Vec2I(tr['met1_encl_mcon'], tr['met1_encl_mcon_end']),
            )

    return l

class Mos(SimLeafCell):
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

    # Dimension minimums (poly.1a, difftap.2 per finger), from tech_rules.
    min_l = R(f"{tech_rules['poly_width']}n")
    min_w = R(f"{tech_rules['channel_width_min']}n")

    fingers_param = 'nf' #: Gate-finger count parameter name
    drain_current_param = 'id' #: Drain current in ngspice_save_params

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

@public
class Nmos(Mos):
    model_name = "sky130_fd_pr__nfet_01v8"

    # Reuse the generic MOS symbol viewgen (not the class: inheriting from
    # generic_mos.Nmos would also drag in its defaulted l/w parameters).
    symbol = generic_mos.Nmos.symbol

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_mos(self, self.l, self.w, self.nf, nwell=False)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("1u"), l=R("150n"))]

@public
class Pmos(Mos):
    model_name = "sky130_fd_pr__pfet_01v8"

    symbol = generic_mos.Pmos.symbol

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_mos(self, self.l, self.w, self.nf, nwell=True)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("1u"), l=R("150n"))]

@public
class PmosHvt(Pmos):
    """High-Vt PMOS, the flavor the sky130hd standard cells use.

    Exists for netlisting standard-cell schematics (spice_in / LVS). No
    layout generator, since layoutgen_mos does not draw the hvtp implant.
    """
    model_name = "sky130_fd_pr__pfet_01v8_hvt"

    @viewgen_noctx
    def layout(self) -> Layout:
        raise NotImplementedError(
            "layoutgen_mos does not draw the hvtp implant")

    @classmethod
    def discoverable_instances(cls):
        return []


def met1_min_area_rect(mcon_rect: Rect4I, grow_axis: str) -> tuple:
    """
    met1 rect over an mcon array with m1.4/m1.5 enclosures, stretched along
    grow_axis (on the manufacturing grid) if needed to reach the m1.6
    minimum area.
    """
    tr = tech_rules
    mg = tech.manufacturing_grid
    if grow_axis == 'y':
        fix_lo = mcon_rect.lx - tr['met1_encl_mcon']
        fix_hi = mcon_rect.ux + tr['met1_encl_mcon']
        grow_lo, grow_hi = mcon_rect.ly, mcon_rect.uy
    else:
        fix_lo = mcon_rect.ly - tr['met1_encl_mcon']
        fix_hi = mcon_rect.uy + tr['met1_encl_mcon']
        grow_lo, grow_hi = mcon_rect.lx, mcon_rect.ux
    span = grow_hi - grow_lo + 2*tr['met1_encl_mcon_end']
    min_span = -(-tr['met1_min_area'] // (fix_hi - fix_lo))
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

    tr = tech_rules
    L = int(length/R("1n"))
    W = int(width/R("1n"))

    l.tap = LayoutRect(layer=layers.tap)
    s.constrain(l.tap.size == (L, W))
    s.constrain(l.tap.southwest == (0, 0))

    # N+ tap connects an nwell, P+ tap the substrate (nsd.5b/psd.5b):
    implant_layer = layers.nsdm if nwell else layers.psdm
    l.implant = LayoutRect(layer=implant_layer)
    s.constrain(l.implant.center == l.tap.center)
    s.constrain(l.implant.size == l.tap.size + Vec2I(2*tr['implant_encl'],
        2*tr['implant_encl']))

    if nwell:
        l.nwell = LayoutRect(layer=layers.nwell)
        s.constrain(l.nwell.center == l.tap.center)
        s.constrain(l.nwell.width == max(L + 2*tr['nwell_encl'],
            tr['nwell_width']))
        s.constrain(l.nwell.height == max(W + 2*tr['nwell_encl'],
            tr['nwell_width']))

    # l.li.rect/l.m1.rect are assigned after solve() from the contact stack,
    # which needs the solved geometry, so the undefined-attribute check is deferred.
    l.li = LayoutRect(layer=layers.li1)
    l.m1 = LayoutRect(layer=layers.met1)
    s.solve(allow_undefined=True)

    licon_rect = makevias(l, l.tap.rect, layers.licon1,
        size=Vec2I(tr['licon_size'], tr['licon_size']),
        spacing=Vec2I(tr['licon_space'], tr['licon_space']),
        margin=Vec2I(tr['licon_encl_tap'], tr['licon_encl_tap']),
        )
    # li1 over the licon array, extended for li.5 end enclosure:
    l.li.rect = (licon_rect.lx, licon_rect.ly - tr['li_encl_licon_end'],
        licon_rect.ux, licon_rect.uy + tr['li_encl_licon_end'])

    mcon_rect = makevias(l, l.li.rect, layers.mcon,
        size=Vec2I(tr['mcon_size'], tr['mcon_size']),
        spacing=Vec2I(tr['mcon_space'], tr['mcon_space']),
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


def layoutgen_res_poly(cell: Cell) -> Layout:
    """
    Generate a straight sky130_fd_pr__res_generic_po resistor: a salicided
    poly body marked with the poly res purpose, terminal heads with a
    licon/npc contact row and the li1/mcon/met1 stack on each end.
    """
    if cell.m != 1:
        raise ParameterError("m != 1 not supported for layout.")

    layers = SKY130().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    tr = tech_rules
    width = int(cell.w / R("1n"))
    length = int(cell.l / R("1n"))
    ps = int(cell.ps / R("1n"))
    bends = cell.b
    if bends < 0:
        raise ParameterError("b must be non-negative.")
    if width < tr['res_poly_width']:
        raise ParameterError("w below poly.3 minimum resistor width.")
    if length < tr['res_poly_length']:
        raise ParameterError("l below generic_po minimum length.")
    if bends != 0 and ps < tr['res_poly_space']:
        raise ParameterError("ps below poly.9 minimum resistor spacing.")

    licon = tr['licon_size']
    body_gap = tr['res_licon_body_space']
    head_len = body_gap + licon + tr['licon_encl_poly']

    # b bends fold the body into b+1 stripes of length l, ps apart, joined
    # at alternating ends. Connector j joins stripes j and j+1, at the top
    # for even j, at the bottom for odd j. n sits below stripe 0, p at the
    # last stripe's free end.
    stripes = bends + 1
    pitch = width + ps

    def stripe_x(i):
        return i * pitch

    body_rects = [
        Rect4I(stripe_x(i), 0, stripe_x(i) + width, length)
        for i in range(stripes)
    ]
    bend_rects = [
        Rect4I(stripe_x(j), length, stripe_x(j + 1) + width, length + width)
        if j % 2 == 0 else
        Rect4I(stripe_x(j), -width, stripe_x(j + 1) + width, 0)
        for j in range(bends)
    ]

    # Body poly with the res purpose marker defining the extracted resistor:
    l.poly_body = PathNode()
    l.res_marker = PathNode()
    for i, rect in enumerate(body_rects + bend_rects):
        l.poly_body[i] = LayoutRect(layer=layers.poly, rect=rect)
        l.res_marker[i] = LayoutRect(layer=layers.poly.res, rect=rect)

    def make_terminal(name, x0, base_y, direction):
        if direction > 0:
            head_rect = Rect4I(x0, base_y, x0 + width, base_y + head_len)
            licon_ly = base_y + body_gap
        else:
            head_rect = Rect4I(x0, base_y - head_len, x0 + width, base_y)
            licon_ly = base_y - body_gap - licon
        setattr(l, f"head_{name}", LayoutRect(layer=layers.poly, rect=head_rect))
        licon_rect = makevias(l,
            Rect4I(x0, licon_ly, x0 + width, licon_ly + licon), layers.licon1,
            size=Vec2I(licon, licon),
            spacing=Vec2I(tr['licon_space'], tr['licon_space']),
            margin=Vec2I(tr['licon_encl_poly'], 0),
            )
        setattr(l, f"npc_{name}", LayoutRect(layer=layers.npc, rect=(
            licon_rect.lx - tr['licon_encl_npc'],
            licon_rect.ly - tr['licon_encl_npc'],
            licon_rect.ux + tr['licon_encl_npc'],
            licon_rect.uy + tr['licon_encl_npc'])))
        setattr(l, f"li_{name}", LayoutRect(layer=layers.li1, rect=(
            licon_rect.lx - tr['li_encl_licon_end'], licon_rect.ly,
            licon_rect.ux + tr['li_encl_licon_end'], licon_rect.uy)))
        mcon_rect = makevias(l, getattr(l, f"li_{name}").rect, layers.mcon,
            size=Vec2I(tr['mcon_size'], tr['mcon_size']),
            spacing=Vec2I(tr['mcon_space'], tr['mcon_space']),
            margin=Vec2I(0, 0),
            )
        setattr(l, f"term_{name}", LayoutRect(layer=layers.met1,
            rect=met1_min_area_rect(mcon_rect, grow_axis='x')))
        return getattr(l, f"term_{name}")

    make_terminal("n", 0, 0, -1).create_pin(cell.symbol.n)
    if stripes % 2 == 1:
        make_terminal("p", stripe_x(stripes - 1), length, 1).create_pin(cell.symbol.p)
    else:
        make_terminal("p", stripe_x(stripes - 1), 0, -1).create_pin(cell.symbol.p)

    return l


@public
class Rpoly(SimLeafCell):
    """
    Salicided generic polysilicon resistor (sky130_fd_pr__res_generic_po,
    about 48 ohm/sq). Two-terminal device without a bulk connection.

    ``b`` bends fold the body into ``b + 1`` stripes of length ``l`` each,
    ``ps`` apart, joined at alternating ends, so a large resistance becomes
    a compact meander. ``ps`` must be at least 480 nm (poly.9).
    """
    model_name = "sky130_fd_pr__res_generic_po"
    l = Parameter(R, default=R("1.65u"))
    w = Parameter(R, default=R("0.33u"))
    b = Parameter(int, default=0)
    ps = Parameter(R, default=R("0.48u"))
    m = Parameter(int, default=1)

    # Typical-corner model constants (rp1 sheet resistance and the fitted
    # effective width offset of the dw correction):
    display_rsh = 48.2
    display_dw = 0.005e-6

    def effective_length(self) -> R:
        """Electrical length of the body: each bend counts as the stripe
        gap plus two corner squares at the usual 0.56 corner factor."""
        return (self.b + 1) * self.l + self.b * (self.ps + R("1.12")*self.w)

    def display_resistance(self) -> float:
        """Nominal typical-corner resistance for the schematic display."""
        w = float(self.w)
        leff = float(self.effective_length())
        return self.display_rsh*leff/(w + self.display_dw) / self.m

    def display_params(self):
        # Out-of-range parameters (caught later by layout/netlist checks)
        # must not break the schematic display:
        if float(self.w) + self.display_dw <= 0 or self.m < 1:
            return self.params_list()
        return self.params_list() + [f"R≈{format_si(self.display_resistance())}{OHM}"]

    def ngspice_current_pins(self):
        return {"i": "p"}

    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.n = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)

        zigzag_height = R(2)
        zigzag_width_half = R(0.625)
        zigzag_start = (R(4) - zigzag_height) / R(2)
        s % SymbolPoly(vertices=[
            Vec2R(2, 0),
            Vec2R(2, zigzag_start),
            Vec2R(2 - zigzag_width_half, zigzag_start + zigzag_height * R(1) / R(12)),
            Vec2R(2 + zigzag_width_half, zigzag_start + zigzag_height * R(3) / R(12)),
            Vec2R(2 - zigzag_width_half, zigzag_start + zigzag_height * R(5) / R(12)),
            Vec2R(2 + zigzag_width_half, zigzag_start + zigzag_height * R(7) / R(12)),
            Vec2R(2 - zigzag_width_half, zigzag_start + zigzag_height * R(9) / R(12)),
            Vec2R(2 + zigzag_width_half, zigzag_start + zigzag_height * R(11) / R(12)),
            Vec2R(2, zigzag_start + zigzag_height),
            Vec2R(2, 4),
        ])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlist_setup)
        pins = [inst.symbol.p, inst.symbol.n]
        if netlister.lvs:
            # KLayout compares the extracted body's W and L (the deck
            # disables the R parameter), in SI units on the card. It derives
            # W from the terminals and L as body area / W, so each bend
            # connector contributes its full area as 2*w + ps of length.
            l_lvs = (self.b + 1) * self.l + self.b * (2*self.w + self.ps)
            params = {"w": self.w, "l": l_lvs}
        else:
            # ngspice semiconductor resistor with the PDK's R model. With
            # ".option scale=1.0u" the dimensions are given in um.
            params = {
                "w": self.w * R("1e6"),
                "l": self.effective_length() * R("1e6"),
                "m": self.m,
            }
        netlister.add(
            netlister.name_obj(inst, prefix="R"),
            netlister.portmap(inst, pins),
            self.model_name,
            *spice_params(params),
        )

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_res_poly(self)

    @classmethod
    def discoverable_instances(cls):
        return [cls()]


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

    # Typical-corner constants fitted to the ngspice model: 2 fF/um^2 area
    # capacitance plus 164 aF/um perimeter capacitance.
    display_ca = 2.0e-3
    display_cp = 1.64e-10

    def display_capacitance(self) -> float:
        """Nominal typical-corner capacitance (area plus perimeter term),
        for the schematic display."""
        w = float(self.w)
        l = float(self.l)
        return (self.display_ca*w*l + self.display_cp*2*(w + l)) * self.m

    def display_params(self):
        return self.params_list() + [f"C≈{format_si(self.display_capacitance())}F"]

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
        s.vdd = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)
        s.vss = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.a = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=West)
        s.y = Pin(pos=Vec2R(4, 2), pintype=PinType.Out, align=East)

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

        s.vdd % SchemPort(pos=Vec2R(2, 13), align=East, ref=self.symbol.vdd)
        s.vss % SchemPort(pos=Vec2R(2, 1), align=East, ref=self.symbol.vss)
        s.a % SchemPort(pos=Vec2R(1, 7), align=East, ref=self.symbol.a)
        s.y % SchemPort(pos=Vec2R(9, 7), align=West, ref=self.symbol.y)

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
        return s

@public
class Ringosc(Cell):
    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.vdd = Pin(pintype=PinType.Inout, align=North)
        s.vss = Pin(pintype=PinType.Inout, align=South)
        s.y = Pin(pintype=PinType.Out, align=East)

        s.place_pins(vpadding=2, hpadding=2)
        return s

    @viewgen_noctx
    def schematic(self) -> Schematic:
        s = Symbol(cell=self, symbol=self.symbol)

        s.y0 = Net()
        s.y1 = Net()
        s.y2 = Net()
        s.vdd = Net()
        s.vss = Net()

        inv = Inv().symbol
        s.i0 = SchemInstance(inv.portmap(vdd=s.vdd, vss=s.vss, a=s.y2, y=s.y0), pos=Vec2R(4, 2))
        s.i1 = SchemInstance(inv.portmap(vdd=s.vdd, vss=s.vss, a=s.y0, y=s.y1), pos=Vec2R(10, 2))
        s.i2 = SchemInstance(inv.portmap(vdd=s.vdd, vss=s.vss, a=s.y1, y=s.y2), pos=Vec2R(16, 2))

        s.vdd % SchemPort(pos=Vec2R(2, 7), align=East)
        s.vss % SchemPort(pos=Vec2R(2, 1), align=East)
        s.y2 % SchemPort(pos=Vec2R(22, 4), align=West)

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
        return s

@public
class And2(Cell):
    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.vdd = Pin(pos=Vec2R(2.5, 5), pintype=PinType.Inout, align=North)
        s.vss = Pin(pos=Vec2R(2.5, 0), pintype=PinType.Inout, align=South)
        s.a = Pin(pos=Vec2R(0, 3), pintype=PinType.In, align=West)
        s.b = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=West)
        s.y = Pin(pos=Vec2R(5, 2.5), pintype=PinType.Out, align=East)

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

        s.vdd = Pin(pos=Vec2R(2.5, 5), pintype=PinType.Inout, align=North)
        s.vss = Pin(pos=Vec2R(2.5, 0), pintype=PinType.Inout, align=South)
        s.a = Pin(pos=Vec2R(0, 3), pintype=PinType.In, align=West)
        s.b = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=West)
        s.y = Pin(pos=Vec2R(5, 2.5), pintype=PinType.Out, align=East)

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
        beol: bool=True, offgrid: bool=True) -> DrcReport:
    """Run the KLayout DRC decks over a layout.

    The PDK's sky130A_mr.drc deck covers widths, spacings and BEOL via
    enclosures; the FEOL enclosure/spacing rules it lacks (licon, npc,
    implant and nwell enclosures) are checked by the supplementary deck
    shipped with ORDeC.

    Args:
        l: the Layout to check.
        use_tempdir: run in a temporary directory instead of ./drc.
        feol: enable the PDK deck's front-end-of-line checks.
        beol: enable the PDK deck's back-end-of-line checks.
        offgrid: enable the PDK deck's manufacturing grid/angle checks.
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

        if feol:
            run_deck(supplement_drc_deck, "supplement.log",
                report="supplement.lyrdb",
                **{name: f"{tech_rules[name]/1000:g}"
                    for name in supplement_drc_rules},
                **klayout_shared_opts
                )
            klayout.parse_rdb(cwd / "supplement.lyrdb", report, directory)

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


#: Device map for spice_in. The standard-cell netlists are written against
#: the ngspice scale option of 1 um, so their real parameters carry that
#: scale.
device_map = {
    "sky130_fd_pr__nfet_01v8": DeviceMapping(Nmos, ("d", "g", "s", "b"),
        real_params=("l", "w"), real_scale=R("1u")),
    "sky130_fd_pr__pfet_01v8_hvt": DeviceMapping(PmosHvt, ("d", "g", "s", "b"),
        real_params=("l", "w"), real_scale=R("1u")),
}


# The sky130hd routing-grid and emitted-geometry profile the P&R engine works
# from. Track pitches and row height come from the standard-cell tech LEF,
# the wire, via, landing, stripe and rail dimensions from the sign-off DRC
# rules (tech_rules). The stack is non-uniform: met3 and met4 run on every
# 2nd base track and met5 on every 10th, met5 carries no signal routing at
# all, and signal pins sit on li1 below the met1 rails.
public(grid = GridConfig(
    # Routing grid (sky130hd tech LEF). Every layer's tracks sit at half its
    # pitch plus multiples of it, so the base grids are the met2/met1 half
    # pitches and each layer runs at an offset of half its multiple. The
    # supply rails lie between tracks, on the row boundaries.
    x_pitch=230,
    y_pitch=170,
    row_height=2720,
    tracks_per_row=16,
    via_half=(tech_nm('via_size') // 2, tech_nm('via2_size') // 2,
        tech_nm('via3_size') // 2, tech_nm('via4_size') // 2),
    encl=tech_nm('met1_encl_via'),
    encl_endcap=tech_nm('met1_encl_via_end'),
    manufacturing_grid=tech.manufacturing_grid,
    # Supply naming (sky130_fd_sc_hd pins + ORDeC net conventions):
    vdd_pin="VPWR",
    vss_pin="VGND",
    vdd_net="vdd",
    vss_net="vss",
    # Emitted geometry (sign-off DRC rules). met2 wires run at 170 nm,
    # above the m2.1 minimum so a via1 fits their width. met5 is unrouted.
    wire_width=(170, tech_nm('met3_width'), tech_nm('met4_width'),
        tech_nm('met5_width')),
    wire_space=(tech_nm('met2_space'), tech_nm('met3_space'),
        tech_nm('met4_space'), tech_nm('met5_space')),
    wire_ext=(200, 200, 200, 710),
    land_half_h=(200, 200, 400, 1250),   # min-area landings (m2.6, m4.4a, m5.4)
    m1_land_half_w=130,   # (via 150 + 2 * 55) / 2 (via.4a)
    m1_land_half_h=160,   # (via 150 + 2 * 85) / 2 (via.5a)
    min_area_tracks=(2, 1, 3, 5),
    port_pad_inner=800,   # met4 port pad reaches the m4.4a minimum area
    track_mult=(2, 4, 4, 20),
    track_off=(1, 2, 2, 10),
    # Via landing pads: these wires are narrower than cut + 2 * enclosure,
    # so every via carries explicit pads on both metals.
    via_land=(
        ((0, 0), (130, 160)),      # met1 side unused, met2 (via.4a, via.5a)
        ((140, 185), (165, 185)),  # met2 (via2.4, via2.5), met3 (m3.4)
        ((160, 190), (200, 200)),  # met3 (via3.4, via3.5), met4 (via3.6)
        ((590, 590), (710, 710)),  # met4 (via4.4), met5 (m5.3)
    ),
    # Signal pins are on li1, reached through an mcon under the met1 landing.
    sub_via_half=tech_nm('mcon_size') // 2,
    sub_encl=0,
    sub_encl_endcap=0,
    # The met1 landing over an mcon encloses the mcon below and the via1
    # above: thin in y (Via1 all-side enclosure via.4a, which also covers
    # the mcon) so near-rail pins clear the rails, grown along x to the
    # m1.6 min area with at least the via.5a endcap enclosure there.
    sub_land_half_h=tech_nm('via_size') // 2 + tech_nm('met1_encl_via'),
    sub_land_half_w_min=tech_nm('via_size') // 2
        + tech_nm('met1_encl_via_end'),
    sub_land_min_area=tech_nm('met1_min_area'),
    abut_pins=("VNB", "VPB"),     # well pins, connected by abutment
    well_tap_dist=10000,          # max un-tapped row run (tapvpwrvgnd cells)
    use_m5=False,                 # met5 wires cannot fit the base y grid
    # Power distribution: met4 stripes (vertical, tapping the rails through
    # via1..via3 stacks) crossed by met5 stripes (horizontal, connected by
    # via4). Both are routing-window layers, so the stripes reserve their
    # tracks as hard blockages.
    pdn=PdnSpec(stripes=(
        PdnStripes(level=3,       # met4
            width=1200,           # >= via4 + 2 * via4.4, for the met5 crossing
            pitch=27600,          # one supply pair per pitch as the die grows
            spacing=tech_nm('met4_space'),
            via=PdnVia(cut=tech_nm('via3_size'),
                cut_pitch=tech_nm('via3_size') + tech_nm('via3_space'),
                encl_above=tech_nm('met4_encl_via3'),
                encl_below=tech_nm('met3_encl_via3_end'))),  # via3.5 pair
        PdnStripes(level=4,       # met5
            width=tech_nm('met5_width'),
            pitch=27200,
            spacing=tech_nm('met5_space'),
            via=PdnVia(cut=tech_nm('via4_size'),
                cut_pitch=tech_nm('via4_size') + tech_nm('via4_space'),
                encl_above=tech_nm('met5_encl_via4'),
                encl_below=tech_nm('met4_encl_via4'))),
        )),
    ))
