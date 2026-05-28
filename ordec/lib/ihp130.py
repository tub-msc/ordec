# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
import tempfile
import json
from pathlib import Path
from public import public
import functools

from ..core import *
from ..schematic import spice_params, Netlister
from . import generic_mos
from .pdk_common import PdkDict, check_dir, check_file, rundir
from ..layout import makevias, write_gds
from ..layout import klayout

@functools.cache
def pdk() -> PdkDict:
    """Returns dictionary-like object with import PDK paths."""
    try:
        root = os.environ["ORDEC_PDK_IHP_SG13G2"]
    except KeyError:
        raise Exception("PDK requires environment variable ORDEC_PDK_IHP_SG13G2 to be set.")
    pdk = PdkDict(root=check_dir(Path(root).resolve()))

    pdk.ngspice_models_dir       =  check_dir(pdk.root / "libs.tech/ngspice/models")
    pdk.ngspice_osdi_dir         =  check_dir(pdk.root / "libs.tech/ngspice/osdi")
    pdk.stdcell_spice_dir        =  check_dir(pdk.root / "libs.ref/sg13g2_stdcell/spice")
    pdk.iocell_spice_dir         =  check_dir(pdk.root / "libs.ref/sg13g2_io/spice")
    pdk.klayout_lvs_deck         = check_file(pdk.root / "libs.tech/klayout/tech/lvs/sg13g2.lvs")
    pdk.klayout_drc_main_deck    = check_file(pdk.root / "libs.tech/klayout/tech/drc/ihp-sg13g2.drc")
    pdk.klayout_drc_decks_dir    =  check_dir(pdk.root / "libs.tech/klayout/tech/drc/rule_decks")
    pdk.klayout_drc_mod_json     = check_file(pdk.root / "libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech_mod.json")
    pdk.klayout_drc_default_json = check_file(pdk.root / "libs.tech/klayout/tech/drc/rule_decks/sg13g2_tech_default.json")

    return pdk

@functools.cache
def tech_params() -> dict:
    """Return merged SG13G2 technology and DRC parameters."""
    data = json.loads(pdk().klayout_drc_mod_json.read_text())
    return data["techParams"] | data["drc_rules"] | data["pcells"]

def _tech_dist(name: str) -> R:
    """Read a distance-like tech parameter as a Rational."""
    value = tech_params()[name]
    if isinstance(value, str):
        return R(value)
    return R(f"{value}u")

def _tech_nm(name: str) -> int:
    return int(_tech_dist(name) / R("1n"))

def ngspice_setup():
    """Return ngspice setup commands based on .spiceinit content."""
    commands = [
        "set ngbehavior=hsa",
        "set noinit",
        f"setcs sourcepath = ( {pdk().ngspice_models_dir} {pdk().stdcell_spice_dir} {pdk().iocell_spice_dir} )",
    ]
    for osdi_file in [
        pdk().ngspice_osdi_dir / "psp103.osdi",
        pdk().ngspice_osdi_dir / "psp103_nqs.osdi",
        pdk().ngspice_osdi_dir / "r3_cmc.osdi",
        pdk().ngspice_osdi_dir / "mosvar.osdi"]:
        commands.append(f"osdi '{check_file(osdi_file)}'")
    return commands

def netlister_setup(netlister):
    if netlister.lvs:
        return

    # Load corner library with typical corner
    model_lib = pdk().ngspice_models_dir / "cornerMOSlv.lib"
    netlister.add(".lib", f"\"{model_lib}\" mos_tt")
    model_lib = pdk().ngspice_models_dir / "cornerRES.lib"
    netlister.add(".lib", f"\"{model_lib}\" res_typ")
    model_lib = pdk().ngspice_models_dir / "cornerCAP.lib"
    netlister.add(".lib", f"\"{model_lib}\" cap_typ")

    # Add options from .spiceinit
    netlister.add(".option", "tnom=28")
    netlister.add(".option", "warn=1")
    netlister.add(".option", "maxwarns=10")
    #netlister.add(".option", "savecurrents")

@public
class SG13G2(Cell):
    @generate
    def layers(self):
        s = LayerStack(cell=self)

        s.unit = R('1n')

        # Frontend layers
        # ---------------

        s.Activ = Layer(
            gdslayer_shapes=GdsLayer(layer=1, data_type=0),
            style_fill=rgb_color("#00ff00"),
            )

        s.GatPoly = Layer(
            gdslayer_shapes=GdsLayer(layer=5, data_type=0),
            style_fill=rgb_color("#bf4026"),
            )
        s.GatPoly.pin = Layer(
            gdslayer_shapes=GdsLayer(layer=5, data_type=2),
            style_fill=rgb_color("#bf4026"),
            is_pinlayer=True,
            )
        
        s.Cont = Layer(
            gdslayer_shapes=GdsLayer(layer=6, data_type=0),
            style_stroke=rgb_color("#00ffff"),
            style_crossrect=True,
            )

        s.pSD = Layer(
            gdslayer_shapes=GdsLayer(layer=14, data_type=0),
            style_fill=rgb_color("#ccb899"),
            )

        s.nSD = Layer(
            gdslayer_shapes=GdsLayer(layer=7, data_type=0),
            style_fill=rgb_color("#99b8d9"),
            )

        s.NWell = Layer(
            gdslayer_shapes=GdsLayer(layer=31, data_type=0),
            style_fill=rgb_color("#268c6b"),
            )

        s.nBuLay = Layer(
            gdslayer_shapes=GdsLayer(layer=32, data_type=0),
            style_fill=rgb_color("#8c8ca6"),
            )

        # Metal stack
        # -----------

        def addmetal(name, layer, color):
            setattr(s, name, Layer(
                gdslayer_shapes=GdsLayer(layer=layer, data_type=0),
                style_fill=color,
            ))
            getattr(s, name).pin = Layer(
                gdslayer_text=GdsLayer(layer=layer, data_type=25),
                gdslayer_shapes=GdsLayer(layer=layer, data_type=2),
                style_fill=color,
                is_pinlayer=True,
            )

        def addvia(name, layer, color):
            setattr(s, name, Layer(
                gdslayer_shapes=GdsLayer(layer=layer, data_type=0),
                style_stroke=color,
                style_crossrect=True,
            ))

        addmetal("Metal1", 8, rgb_color("#39bfff"))
        addvia("Via1", 19, rgb_color("#ccccff"))
        addmetal("Metal2", 10, rgb_color("#ccccd9"))
        addvia("Via2", 29, rgb_color("#ff3736"))
        addmetal("Metal3", 30, rgb_color("#d80000"))
        addvia("Via3", 49, rgb_color("#9ba940"))
        addmetal("Metal4", 50, rgb_color("#93e837"))
        addvia("Via4", 66, rgb_color("#deac5e"))
        addmetal("Metal5", 67, rgb_color("#dcd146"))
        addvia("TopVia1", 125, rgb_color("#ffe6bf"))
        addmetal("TopMetal1", 126, rgb_color("#ffe6bf"))
        addvia("TopVia2", 133, rgb_color("#ff8000"))
        addmetal("TopMetal2", 134, rgb_color("#ff8000"))

        # Other layers
        # ------------

        s.EXTBlock = Layer(
            gdslayer_shapes=GdsLayer(layer=111, data_type=0),
            style_fill=rgb_color("#5e00e6"),
            )

        s.RES = Layer(
            gdslayer_shapes=GdsLayer(layer=24, data_type=0),
            style_fill=rgb_color("#ff9966"),
            )

        s.SalBlock = Layer(
            gdslayer_shapes=GdsLayer(layer=28, data_type=0),
            style_fill=rgb_color("#996633"),
            )

        s.MIM = Layer(
            gdslayer_shapes=GdsLayer(layer=36, data_type=0),
            style_fill=rgb_color("#268c6b"),
            )

        s.Substrate = Layer(
            gdslayer_shapes=GdsLayer(layer=40, data_type=0),
            style_fill=rgb_color("#ffffff"),
            )

        s.HeatTrans = Layer(
            gdslayer_shapes=GdsLayer(layer=51, data_type=0),
            style_fill=rgb_color("#8c8ca6"),
            )

        s.TEXT = Layer(
            gdslayer_text=GdsLayer(layer=63, data_type=0),
            )

        s.Recog = Layer(
            gdslayer_shapes=GdsLayer(layer=99, data_type=31),
            style_fill=rgb_color("#bdcccc"),
            )

        s.Vmim = Layer(
            gdslayer_shapes=GdsLayer(layer=129, data_type=0),
            style_fill=rgb_color("#ffe6bf"),
            )

        s.PolyRes = Layer(
            gdslayer_shapes=GdsLayer(layer=128, data_type=0),
            style_fill=rgb_color("#cc6633"),
            )
        s.PolyRes.pin = Layer(
            gdslayer_shapes=GdsLayer(layer=128, data_type=2),
            style_fill=rgb_color("#cc6633"),
            is_pinlayer=True,
            )
        
        s.prBoundary = Layer(
            gdslayer_shapes=GdsLayer(layer=189, data_type=4), # data_type 4 or 0?
            style_fill=rgb_color("#9900e6"),
            style_stroke=rgb_color("#ff00ff"),
            )

        return s

    @generate
    def default_routing_spec(self):
        layers = self.layers
        rs = RoutingSpec(ref_layers=layers)

        route_id = 0
        def addmetal(layer, route_width=200, route_ext=100+50, route_via=(480,300)):
            nonlocal route_id
            rs % RoutingSpecLayer(
                layer=layer,
                route_id=route_id,
                route_wire_width=route_width,
                route_wire_ext=route_ext,
                route_via_width=route_via[0],
                route_via_height=route_via[1],
            )
            route_id += 1

        def addvia(layer, route_via=(190,190)):
            nonlocal route_id
            rs % RoutingSpecLayer(
                layer=layer,
                route_id=route_id,
                route_via_width=route_via[0],
                route_via_height=route_via[1],
            )
            route_id += 1

        addmetal(layers.Metal1)
        addvia(layers.Via1)
        addmetal(layers.Metal2)
        addvia(layers.Via2)
        addmetal(layers.Metal3)
        # Todo: settings about Metal3 not checked yet.
        addvia(layers.Via3)
        addmetal(layers.Metal4)
        addvia(layers.Via4)
        addmetal(layers.Metal5)
        addvia(layers.TopVia1)
        addmetal(layers.TopMetal1)
        addvia(layers.TopVia2)
        addmetal(layers.TopMetal2)

        return rs

def layoutgen_mos(cell: Cell, length: R, width: R, num_gates: int, nwell: bool) -> Layout:
    """
    Layout generation function shared for Nmos and Pmos cells.

    Notice: Placement of Cont vias differs slightly from the foundry-provieded PCell.

    See also: ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib/ihp/nmos_code.py
    """
    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell)
    s = Solver(l)

    L = int(length/R("1n"))
    W = int(width/R("1n") / num_gates)

    l.poly = PathNode()
    l.sd = PathNode()

    activ_ext = None

    def add_sd(i):
        nonlocal l, s, x_cur, activ_ext
        l.sd[i] = LayoutRect(layer=layers.Metal1)
        sd = l.sd[i]
        s.constrain(sd.west == (x_cur, l.activ.cy))
        s.constrain(sd.width == 160)
        if W >= 300:
            s.constrain(sd.height == W)
        else:
            s.constrain(sd.height == 260)

            activ_ext = l % LayoutRect(layer=layers.Activ)
            s.constrain(activ_ext.center == sd.center)
            s.constrain(activ_ext.size == (300, 300))
        x_cur = sd.ux

    def add_poly(i):
        nonlocal l, s, x_cur
        x_cur += 110
        l.poly[i] = LayoutRect(layer=layers.GatPoly)
        poly = l.poly[i]
        s.constrain(poly.west == (x_cur, l.activ.cy))
        s.constrain(poly.size == (L, l.activ.height + 360))
        s.constrain(poly.ly == 0)
        x_cur = poly.ux + 110

    l.activ = LayoutRect(layer=layers.Activ)
    s.constrain(l.activ.height == W)
    s.constrain(l.activ.lx == 0)
    x_cur = l.activ.lx + 70

    add_sd(0)
    for i in range(num_gates):
        add_poly(i)
        add_sd(i+1)

    s.constrain(l.activ.ux == x_cur + 70)

    if nwell:
        l.psd = LayoutRect(layer=layers.pSD)
        s.constrain(l.psd.center == l.activ.center)
        s.constrain(l.psd.size == l.activ.size + Vec2I(360, 600))

        if activ_ext is None:
            max_activ = l.activ
        else:
            max_activ = activ_ext
        l.nwell = LayoutRect(layer=layers.NWell)
        s.constrain(l.nwell.center == l.activ.center)
        s.constrain(l.nwell.ux == l.activ.ux + 310)
        s.constrain(l.nwell.uy == max_activ.uy + 310)

    s.solve()

    for i in range(num_gates + 1):
        makevias(l, l.sd[i].rect, layers.Cont, 
            size=Vec2I(160, 160),
            spacing=Vec2I(180, 180),
            margin=Vec2I(50, 50),
            cols=1,
            )
        
    return l


class Mos(SimLeafCell):
    l = Parameter(R)  #: Length
    w = Parameter(R)  #: Width
    m = Parameter(int, default=1)  #: Multiplier, i. e. number of devices with separate Activ areas in parallel)
    ng = Parameter(int, default=1)  #: Number of gate fingers

    def ngspice_save_params(self):
        return ["gm", "gds", "vth", "vdsat", "region"]

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlister_setup)
        netlister.require_ngspice_setup(ngspice_setup)
        pins = [inst.symbol.d, inst.symbol.g, inst.symbol.s, inst.symbol.b]
        netlister.add(
            netlister.name_obj(inst, prefix="M" if netlister.lvs else "x"),
            netlister.portmap(inst, pins),
            self.model_name,
            *spice_params({
                'l': self.l,
                'w': self.w,
                'm': self.m,
                'ng': self.ng,
            }))

@public
class Nmos(Mos, generic_mos.Nmos):
    model_name = "sg13_lv_nmos"

    @generate
    def layout(self) -> Layout:
        if self.m != 1:
            raise ParameterError("m != 1 not supported for layout.")
        return layoutgen_mos(self, self.l, self.w, self.ng, nwell=False)

@public
class Pmos(Mos, generic_mos.Pmos):
    model_name = "sg13_lv_pmos"

    @generate
    def layout(self) -> Layout:
        if self.m != 1:
            raise ParameterError("m != 1 not supported for layout.")
        return layoutgen_mos(self, self.l, self.w, self.ng, nwell=True)

def layoutgen_tap(cell: Cell, length: R, width: R, nwell: bool):
    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell)
    s = Solver(l)

    L = int(length/R("1n"))
    W = int(width/R("1n"))

    l.activ = LayoutRect(layer=layers.Activ)
    s.constrain(l.activ.size == (L, W))
    s.constrain(l.activ.southwest == (0, 0))

    l.m1 = LayoutRect(layer=layers.Metal1)

    # TODO: add Metal1 pin?!

    if nwell:
        l.nwell = LayoutRect(layer=layers.NWell)
        s.constrain(l.nwell.center == l.activ.center)
        s.constrain(l.nwell.size == l.activ.size + Vec2I(480, 480))

        l.nbulay = LayoutRect(layer=layers.nBuLay)
        s.constrain(l.nbulay.rect == l.nwell.rect)
    else:
        l.psd = LayoutRect(layer=layers.pSD)
        s.constrain(l.psd.center == l.activ.center)
        s.constrain(l.psd.size == l.activ.size + Vec2I(60, 60))

    s.solve()

    vias_rect = makevias(l, l.activ.rect, layers.Cont, 
        size=Vec2I(160, 160),
        spacing=Vec2I(180, 180),
        margin=Vec2I(70, 70),
        )
    # Shrink M1 to via stack, with 50 nm extension north and south:
    l.m1.rect = (vias_rect.lx, vias_rect.ly - 50, vias_rect.ux, vias_rect.uy + 50)

    return l


@public
class Ntap(Cell):
    l = Parameter(R)  #: Length
    w = Parameter(R)  #: Width

    @generate
    def layout(self) -> Layout:
        return layoutgen_tap(self, self.l, self.w, nwell=True)

@public
class Ptap(Cell):
    l = Parameter(R)  #: Length
    w = Parameter(R)  #: Width

    @generate
    def layout(self) -> Layout:
        return layoutgen_tap(self, self.l, self.w, nwell=False)


def _layoutgen_resistor(
        cell: Cell,
        kind: str,
        *,
        add_res: bool = False,
        add_psd: bool = False,
        add_nsd: bool = False) -> Layout:
    """
    Generate an SG13G2 poly resistor.

    This is still simpler than the foundry PCells and currently supports only
    the straight-body case. The IHP resistor PCells have several asymmetry and
    contact-push corner cases for bent devices which are intentionally kept out
    of scope until ORDeC has a PCell-compatible implementation.
    """
    if cell.m != 1:
        raise ParameterError("m != 1 not supported for layout.")
    if cell.b != 0:
        raise ParameterError("b != 0 not supported for layout.")

    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    width = int(cell.w / R("1n"))
    length = int(cell.l / R("1n"))
    ps = int(cell.ps / R("1n"))
    bends = cell.b

    if width < _tech_nm(f"{kind}_minW"):
        raise ParameterError(f"w below {kind} minimum width.")
    if length < _tech_nm(f"{kind}_minL"):
        raise ParameterError(f"l below {kind} minimum length.")
    if bends != 0 and ps < _tech_nm(f"{kind}_minPS"):
        raise ParameterError(f"ps below {kind} minimum spacing.")

    cont_size = _tech_nm("Cnt_a")
    poly_over_cont = _tech_nm("Cnt_d")
    contbar_poly_over = _tech_nm("CntB_d")
    contbar_min_len = _tech_nm("CntB_a1")
    metal_x_enc = _tech_nm("M1_c1")
    metal_y_enc = max(_tech_nm("M1_c1"), _tech_nm(f"{kind}_met_over_cont"))
    cont_to_body = _tech_nm(f"{kind}_cont_to_body")
    head_len = cont_to_body + cont_size + poly_over_cont

    if width - 2 * contbar_poly_over < contbar_min_len:
        raise ParameterError("Width too small for resistor terminal contact bars.")

    def make_terminal(name, x0, base_y, direction):
        if direction > 0:
            head_rect = Rect4I(x0, base_y, x0 + width, base_y + head_len)
            cont_rect = Rect4I(
                x0 + contbar_poly_over,
                base_y + cont_to_body,
                x0 + width - contbar_poly_over,
                base_y + cont_to_body + cont_size,
            )
        else:
            head_rect = Rect4I(x0, base_y - head_len, x0 + width, base_y)
            cont_rect = Rect4I(
                x0 + contbar_poly_over,
                base_y - (cont_to_body + cont_size),
                x0 + width - contbar_poly_over,
                base_y - cont_to_body,
            )
        term_rect = Rect4I(
            cont_rect.lx - metal_x_enc,
            cont_rect.ly - metal_y_enc,
            cont_rect.ux + metal_x_enc,
            cont_rect.uy + metal_y_enc,
        )
        setattr(l, f"poly_head_{name}", LayoutRect(layer=layers.GatPoly, rect=head_rect))
        setattr(l, f"cont_{name}", LayoutRect(layer=layers.Cont, rect=cont_rect))
        setattr(l, f"term_{name}", LayoutRect(layer=layers.Metal1, rect=term_rect))
        return head_rect, cont_rect, term_rect

    body_x_lo = 0
    body_y_lo = 0
    body_x_hi = width
    body_y_hi = length

    body_rect = Rect4I(0, 0, width, length)
    l.poly_body = LayoutRect(layer=layers.PolyRes, rect=body_rect)

    if add_res:
        l.res = LayoutRect(layer=layers.RES, rect=body_rect)

    make_terminal("m", 0, 0, -1)
    make_terminal("p", 0, length, 1)

    total_x_lo = body_x_lo
    total_x_hi = body_x_hi
    total_y_lo = min(body_y_lo, l.poly_head_m.ly, l.poly_head_p.ly)
    total_y_hi = max(body_y_hi, l.poly_head_m.uy, l.poly_head_p.uy)

    if add_psd or add_nsd:
        sd_enc = _tech_nm("Rhi_c" if add_nsd else "Rppd_b")
        sal_enc = _tech_nm("Sal_c")

        if add_psd:
            l.psd = LayoutRect(
                layer=layers.pSD,
                rect=(total_x_lo - sd_enc, total_y_lo - sd_enc, total_x_hi + sd_enc, total_y_hi + sd_enc),
            )

        if add_nsd:
            l.nsd = LayoutRect(
                layer=layers.nSD,
                rect=(total_x_lo - sd_enc, total_y_lo - sd_enc, total_x_hi + sd_enc, total_y_hi + sd_enc),
            )

        l.salblock = LayoutRect(
            layer=layers.SalBlock,
            # Straight Rppd/Rhigh devices keep SalBlock flush with the resistor
            # body in the longitudinal direction; only the lateral enclosure is
            # present. Extending SalBlock beyond the body collapses the required
            # 0.20 um spacing to the terminal contact.
            rect=(body_x_lo - sal_enc, body_y_lo, body_x_hi + sal_enc, body_y_hi),
        )
        l.extblock = LayoutRect(
            layer=layers.EXTBlock,
            rect=(total_x_lo - sal_enc, total_y_lo - sal_enc, total_x_hi + sal_enc, total_y_hi + sal_enc),
        )
    else:
        ext_enc = _tech_nm("Rsil_e")
        l.extblock = LayoutRect(
            layer=layers.EXTBlock,
            rect=(total_x_lo - ext_enc, total_y_lo - ext_enc, total_x_hi + ext_enc, total_y_hi + ext_enc),
        )

    l.term_m.create_pin(cell.symbol.m)
    l.term_p.create_pin(cell.symbol.p)

    return l


def _layoutgen_cmim(cell: Cell) -> Layout:
    """Generate the fixed SG13G2 MiM capacitor layout."""
    if cell.m != 1:
        raise ParameterError("m != 1 not supported for layout.")

    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    width = int(cell.w / R("1n"))
    length = int(cell.l / R("1n"))
    min_lw = _tech_nm("cmim_minLW")
    if width < min_lw or length < min_lw:
        raise ParameterError("w and l must be at least cmim_minLW.")

    mim_c = _tech_nm("Mim_c")
    mim_d = _tech_nm("Mim_d")
    tv1_size = _tech_nm("TV1_a")
    tv1_space = _tech_nm("TV1_a") + _tech_nm("TV1_b")
    tv1_enc = _tech_nm("TV1_d")

    l.mim = LayoutRect(layer=layers.MIM, rect=(0, 0, width, length))
    l.term_m = LayoutRect(
        layer=layers.Metal5,
        rect=(-mim_c, -mim_c, width + mim_c, length + mim_c),
    )
    via_bbox = makevias(
        l,
        l.mim.rect,
        layers.Vmim,
        size=Vec2I(tv1_size, tv1_size),
        spacing=Vec2I(tv1_space, tv1_space),
        margin=Vec2I(mim_d, mim_d),
    )
    makevias(
        l,
        l.mim.rect,
        layers.TopVia1,
        size=Vec2I(tv1_size, tv1_size),
        spacing=Vec2I(tv1_space, tv1_space),
        margin=Vec2I(mim_d, mim_d),
    )
    l.term_p = LayoutRect(
        layer=layers.TopMetal1,
        rect=(
            via_bbox.lx - tv1_enc,
            via_bbox.ly - tv1_enc,
            via_bbox.ux + tv1_enc,
            via_bbox.uy + tv1_enc,
        ),
    )

    l.term_m.create_pin(cell.symbol.m)
    l.term_p.create_pin(cell.symbol.p)

    return l


class _Resistor(SimLeafCell):
    """Shared base class for SG13G2 resistors."""
    l = Parameter(R)
    w = Parameter(R)
    b = Parameter(int, default=0)
    ps = Parameter(R, default=R("0.18u"))
    m = Parameter(int, default=1)

    def ngspice_current_pins(self):
        return {"i": "p"}

    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)
        s.bn = Pin(pos=Vec2R(4, 2), pintype=PinType.In, align=East)

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
        s % SymbolPoly(vertices=[Vec2R(2.6, 2), Vec2R(4, 2)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlister_setup)
        netlister.require_ngspice_setup(ngspice_setup)

        params = {
            "w": self.w,
            "l": self.l,
            "m": self.m,
            "b": self.b,
        }
        if (not netlister.lvs) or (self.b != 0):
            params["ps"] = self.ps
        if netlister.lvs:
            pins = [inst.symbol.p, inst.symbol.m, inst.symbol.bn]
            prefix = "R"
        else:
            pins = [inst.symbol.p, inst.symbol.m, inst.symbol.bn]
            prefix = "x"
        netlister.add(
            netlister.name_obj(inst, prefix=prefix),
            netlister.portmap(inst, pins),
            self.model_name,
            *spice_params(params),
        )


@public
class Rsil(_Resistor):
    model_name = "rsil"
    l = Parameter(R, default=R("0.50u"))
    w = Parameter(R, default=R("0.50u"))

    @generate
    def layout(self) -> Layout:
        return _layoutgen_resistor(self, "rsil", add_res=True)

    @classmethod
    def discoverable_instances(cls):
        return [cls()]


@public
class Rppd(_Resistor):
    model_name = "rppd"
    l = Parameter(R, default=R("0.50u"))
    w = Parameter(R, default=R("0.50u"))

    @generate
    def layout(self) -> Layout:
        return _layoutgen_resistor(self, "rppd", add_psd=True)

    @classmethod
    def discoverable_instances(cls):
        return [cls()]


@public
class Rhigh(_Resistor):
    model_name = "rhigh"
    l = Parameter(R, default=R("0.96u"))
    w = Parameter(R, default=R("0.50u"))

    @generate
    def layout(self) -> Layout:
        return _layoutgen_resistor(self, "rhigh", add_psd=True, add_nsd=True)

    @classmethod
    def discoverable_instances(cls):
        return [cls()]


@public
class Cmim(SimLeafCell):
    """Fixed SG13G2 MIM capacitor."""
    l = Parameter(R, default=R("6.99u"))
    w = Parameter(R, default=R("6.99u"))
    m = Parameter(int, default=1)
    ic = Parameter(R, optional=True)

    def ngspice_current_pins(self):
        return {"i": "p"}

    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)

        s % SymbolPoly(vertices=[Vec2R(1.25, 1.8), Vec2R(2.75, 1.8)])
        s % SymbolPoly(vertices=[Vec2R(1.25, 2.2), Vec2R(2.75, 2.2)])
        s % SymbolPoly(vertices=[Vec2R(2, 2.2), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(2, 1.8), Vec2R(2, 0)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlister_setup)
        netlister.require_ngspice_setup(ngspice_setup)

        pins = [inst.symbol.p, inst.symbol.m]
        params = {
            "w": self.w,
            "l": self.l,
            "m": self.m,
        }
        if netlister.lvs:
            prefix = "C"
        else:
            prefix = "x"
            if self.ic is not None:
                params["ic"] = self.ic
        netlister.add(
            netlister.name_obj(inst, prefix=prefix),
            netlister.portmap(inst, pins),
            "cap_cmim",
            *spice_params(params),
        )

    @generate
    def layout(self) -> Layout:
        return _layoutgen_cmim(self)

    @classmethod
    def discoverable_instances(cls):
        return [cls()]

# klayout-new -b -r '/home/tobias/workspace/ordec/lvs/drc_run_2025_11_26_13_11_34/main.drc'
#     -rd drc_json_default='/home/tobias/workspace/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/sg13g2_tech_default.json'
#     -rd         drc_json='/home/tobias/workspace/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech_mod.json'


def _copy_drc_item_shapes(src_report: DrcReport, dst_report: DrcReport, item_map: dict[int, DrcItem]):
    for box in src_report.all(DrcBox):
        dst_report % DrcBox(item=item_map[box.item.nid], order=box.order, tag=box.tag, rect=box.rect)

    for edge in src_report.all(DrcEdge):
        dst_report % DrcEdge(item=item_map[edge.item.nid], order=edge.order, tag=edge.tag, p1=edge.p1, p2=edge.p2)

    for edge_pair in src_report.all(DrcEdgePair):
        dst_report % DrcEdgePair(
            item=item_map[edge_pair.item.nid],
            order=edge_pair.order,
            tag=edge_pair.tag,
            edge1_p1=edge_pair.edge1_p1,
            edge1_p2=edge_pair.edge1_p2,
            edge2_p1=edge_pair.edge2_p1,
            edge2_p2=edge_pair.edge2_p2,
        )

    for poly in src_report.all(DrcPoly):
        new_poly = dst_report % DrcPoly(item=item_map[poly.item.nid], order=poly.order, tag=poly.tag)
        for order, pos in enumerate(poly.vertices()):
            dst_report % PolyVec2I(ref=new_poly, order=order, pos=pos)

    for path in src_report.all(DrcPath):
        new_path = dst_report % DrcPath(
            item=item_map[path.item.nid],
            order=path.order,
            tag=path.tag,
            width=path.width,
            endtype=path.endtype,
        )
        for order, pos in enumerate(path.vertices()):
            dst_report % PolyVec2I(ref=new_path, order=order, pos=pos)

    for text in src_report.all(DrcText):
        dst_report % DrcText(item=item_map[text.item.nid], order=text.order, tag=text.tag, pos=text.pos, text=text.text)

    for value in src_report.all(DrcValue):
        dst_report % DrcValue(item=item_map[value.item.nid], order=value.order, tag=value.tag, value=value.value)


def merge_drc_reports(reports: list[DrcReport], layout: Layout) -> DrcReport:
    """Merge several parsed KLayout DRC reports into one schema report."""
    if len(reports) == 1:
        return reports[0]

    merged = DrcReport(ref_layout=layout, top_cell_name=reports[0].top_cell_name if reports else "")
    category_by_name = {}

    for report in reports:
        for category in report.all(DrcCategory):
            if category.name not in category_by_name:
                category_by_name[category.name] = merged % DrcCategory(
                    name=category.name,
                    description=category.description,
                )

    for report in reports:
        item_map = {}
        for item in report.all(DrcItem):
            item_map[item.nid] = merged % DrcItem(
                category=category_by_name[item.category.name],
                cell=item.cell,
            )
        _copy_drc_item_shapes(report, merged, item_map)

    return merged

@public
def run_drc(l: Layout, variant='maximal', use_tempdir: bool=True):
    if variant not in ('minimal', 'maximal'):
        raise ValueError("variant must be either 'minimal' or 'maximal'.")

    directory = Directory()

    with rundir('drc', use_tempdir) as cwd:
        with open(cwd / "layout.gds", "wb") as f:
            write_gds(l, f, directory)

        klayout_shared_opts = dict(
            threads=str(os.cpu_count()),
            drc_json_default=pdk().klayout_drc_default_json,
            drc_json=pdk().klayout_drc_mod_json,
            topcell=directory.name_subgraph(l),
            input="layout.gds",
            run_mode="deep",
            precheck_drc="false",
            disable_extra_rules="false",
            no_feol="false",
            no_beol="false",
            no_forbidden="false",
            no_pin="false",
            no_offgrid="false",
            no_recommended="false",
        )

        reports = []

        (cwd / 'main.log').unlink(missing_ok=True)
        klayout.run(pdk().klayout_drc_main_deck, cwd,
            report="main.lyrdb",
            log="main.log",
            table_name="main",
            tables="main",
            **klayout_shared_opts
            )
        reports.append(klayout.parse_rdb(cwd / "main.lyrdb", l, directory))

        if variant == 'maximal':
            (cwd / 'maximal.log').unlink(missing_ok=True)
            klayout.run(pdk().klayout_drc_decks_dir / 'sg13g2_maximal.drc', cwd,
                report="maximal.lyrdb",
                log="maximal.log",
                table_name="sg13g2_maximal",
                **klayout_shared_opts
                )
            reports.append(klayout.parse_rdb(cwd / "maximal.lyrdb", l, directory))

        return merge_drc_reports(reports, l)


@public
def run_lvs(layout: Layout, symbol: Symbol, use_tempdir: bool=True) -> bool:
    """
    Returns:
        True if LVS is clean, else False.
    """
    #layout = layout.freeze()
    #schematic = schematic.freeze()

    directory = Directory()
    nl = Netlister(directory, lvs=True)
    nl.netlist_hier_symbol(symbol)
    
    with rundir('lvs', use_tempdir) as cwd:
        # Note: The LVS script sometimes creates files in the parent directory
        # of the input data. This seems to be fixed with the current LVS
        # options, though. If the issue returns, add here: cwd = cwd / 'lvs'

        (cwd / 'schematic.cir').write_text(nl.out())

        (cwd / 'out.log').unlink(missing_ok=True)

        with open(cwd / 'layout.gds', "wb") as f:
            name_of_layout = write_gds(layout, f, directory=directory)

        klayout.run(
            pdk().klayout_lvs_deck,
            str(cwd),
            run_mode='deep',
            no_net_names='false',
            spice_comments='false',
            net_only='false',
            top_lvl_pins='true',
            no_simplify='false',
            no_series_res='false',
            no_parallel_res='false',
            combine_devices='false',
            purge='false',
            purge_nets='false',
            verbose='false',
            report='out.lvsdb',
            log='out.log',
            target_netlist='extracted.cir',
            topcell=directory.name_subgraph(layout),
            input='layout.gds',
            schematic='schematic.cir',
            )

        log = (cwd / "out.log").read_text()
        if log.find("INFO : Congratulations! Netlists match.") >= 0:
            return True
        elif log.find("ERROR : Netlists don't match") >= 0:
            return False
        else:
            raise Exception("Failed to evaluate LVS log file.")
