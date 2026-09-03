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
from .pdk_common import PdkDict, check_dir, check_file, rundir, format_si, OHM
from ..layout import makevias, write_gds
from ..layout import klayout

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
}

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
    if W < tr['channel_width_min']:
        raise ParameterError(f"Channel width below difftap.2 minimum of"
            f" {tr['channel_width_min']} nm per finger.")
    if L < tr['poly_width']:
        raise ParameterError(f"Channel length below poly.1a minimum of"
            f" {tr['poly_width']} nm.")

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

    def diffusion_params(self) -> dict:
        """ad/as/pd/ps for an interdigitated S-G-D-G-S-... layout, taking
        explicitly set parameters over the derived values."""
        diff_ext = self.diff_ext if self.diff_ext is not None else R("0.265u")

        # Number of drain/source diffusion regions:
        # nf=1: S-G-D (1 drain, 1 source)
        # nf=2: S-G-D-G-S (1 drain, 2 sources)
        # nf=3: S-G-D-G-S-G-D (2 drains, 2 sources)
        n_drain = (self.nf + 1) // 2
        n_source = (self.nf + 2) // 2

        # Perimeter: 2×diff_ext per region (sides facing isolation), plus W
        # contribution from edge diffusions only. Edge diffusion count:
        # - odd nf: 1 drain edge, 1 source edge
        # - even nf: 0 drain edges (internal), 2 source edges
        n_edge_drain = 1 if self.nf % 2 == 1 else 0
        n_edge_source = 1 if self.nf % 2 == 1 else 2

        return {
            # Area: each diffusion region is w × diff_ext
            'ad': self.ad if self.ad is not None else n_drain * self.w * diff_ext,
            'as_': self.as_ if self.as_ is not None else n_source * self.w * diff_ext,
            'pd': self.pd if self.pd is not None else 2 * n_drain * diff_ext + n_edge_drain * self.w,
            'ps': self.ps if self.ps is not None else 2 * n_source * diff_ext + n_edge_source * self.w,
        }

    def ngspice_save_params(self):
        return ["gm", "gds", "vth", "vdsat", "region"]

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

def met1_min_area_rect(mcon_rect: Rect4I, grow_axis: str) -> tuple:
    """
    met1 rect over an mcon array with m1.4/m1.5 enclosures, stretched along
    grow_axis (on the 5 nm grid) if needed to reach the m1.6 minimum area.
    """
    tr = tech_rules
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
    span = max(span, -(-min_span // 5) * 5)
    grow = (span - (grow_hi - grow_lo)) // 2 // 5 * 5
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

        klayout.run(pdk().klayout_drc_deck, cwd,
            capture="main.log",
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

        klayout.run(supplement_drc_deck, cwd,
            capture="supplement.log",
            report="supplement.lyrdb",
            **{name: f"{tech_rules[name]/1000:g}" for name in supplement_drc_rules},
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
