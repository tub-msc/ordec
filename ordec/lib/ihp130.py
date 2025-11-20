# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
import tempfile
from pathlib import Path
from public import public
import functools

from ..core import *
from ..schematic import helpers
from . import generic_mos
from .pdk_common import PdkDict, check_dir, check_file
from ..layout.makevias import makevias
from ..layout.gds_out import write_gds
from ..layout import klayout

@functools.cache
def pdk() -> PdkDict:
    """Returns dictionary-like object with import PDK paths."""
    try:
        root = os.environ["ORDEC_PDK_IHP_SG13G2"]
    except KeyError:
        raise Exception("PDK requires environment variable ORDEC_PDK_IHP_SG13G2 to be set.")
    pdk = PdkDict(root=check_dir(Path(root).resolve()))

    pdk.ngspice_models_dir =  check_dir(pdk.root / "libs.tech/ngspice/models")
    pdk.ngspice_osdi_dir   =  check_dir(pdk.root / "libs.tech/ngspice/osdi")
    pdk.stdcell_spice_dir  =  check_dir(pdk.root / "libs.ref/sg13g2_stdcell/spice")
    pdk.iocell_spice_dir   =  check_dir(pdk.root / "libs.ref/sg13g2_io/spice")
    pdk.klayout_lvs_deck   = check_file(pdk.root / "libs.tech/klayout/tech/lvs/sg13g2.lvs")
    pdk.klayout_drc_deck   = {
        'minimal':           check_file(pdk.root / "libs.tech/klayout/tech/drc/sg13g2_minimal.lydrc"),
        'maximal':           check_file(pdk.root / "libs.tech/klayout/tech/drc/sg13g2_maximal.lydrc"),
    }

    return pdk

def ngspice_setup(sim):
    """Execute ngspice commands directly based on .spiceinit content"""

    # Set ngspice behavior (from .spiceinit)
    sim.command("set ngbehavior=hsa")
    sim.command("set noinit")

    # Set sourcepath (equivalent to setcs sourcepath commands in .spiceinit)
    sim.command(f"setcs sourcepath = ( {pdk().ngspice_models_dir} {pdk().stdcell_spice_dir} {pdk().iocell_spice_dir} )")

    # Load OSDI models using absolute paths resolved in Python
    osdi_files = [
        pdk().ngspice_osdi_dir / "psp103_nqs.osdi",
        pdk().ngspice_osdi_dir / "r3_cmc.osdi",
        pdk().ngspice_osdi_dir / "mosvar.osdi",
    ]

    for osdi_file in osdi_files:
        sim.command(f"osdi '{check_file(osdi_file)}'")

def netlister_setup(netlister):
    if netlister.lvs:
        return

    # Load corner library with typical corner
    model_lib = pdk().ngspice_models_dir / "cornerMOSlv.lib"
    netlister.add(".lib", f"\"{model_lib}\" mos_tt")

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

        s.NWell = Layer(
            gdslayer_shapes=GdsLayer(layer=31, data_type=0),
            style_fill=rgb_color("#268c6b"),
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
        
        s.prBoundary = Layer(
            gdslayer_shapes=GdsLayer(layer=189, data_type=4), # data_type 4 or 0?
            style_fill=rgb_color("#9900e6"),
            style_stroke=rgb_color("#ff00ff"),
            )

        return s

def layoutgen_mos(cell: Cell, length: R, width: R, num_gates: int, pmos: bool) -> Layout:
    # See also: ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib/ihp/nmos_code.py
    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell)
    s = Solver(l)

    L = int(length/R("1n"))
    W = int(width/R("1n") / num_gates)

    l.mkpath('polys')
    l.mkpath('sd')

    def add_sd(i):
        nonlocal l, s, x_cur
        l.sd[i] = LayoutRect(layer=layers.Metal1)
        sd = l.sd[i]
        s.constrain(sd.rect.width == 160)
        s.constrain(sd.rect.cy == l.activ.rect.cy)
        s.constrain(sd.rect.lx == x_cur)
        if W >= 300:
            s.constrain(sd.rect.height == W)
        else:
            s.constrain(sd.rect.height == 260)

            activ_ext = l % LayoutRect(layer=layers.Activ)
            s.constrain(activ_ext.rect.cx == sd.rect.cx)
            s.constrain(activ_ext.rect.cy == sd.rect.cy)
            s.constrain(activ_ext.rect.width == 300)
            s.constrain(activ_ext.rect.height == 300)
        x_cur = sd.rect.ux    

    def add_poly(i):
        nonlocal l, s, x_cur
        x_cur += 140
        l.polys[i] = LayoutRect(layer=layers.GatPoly)
        poly = l.polys[i]
        s.constrain(poly.rect.cy == l.activ.rect.cy)
        s.constrain(poly.rect.width == L)
        s.constrain(poly.rect.lx == x_cur)
        s.constrain(poly.rect.ly + 100 == l.activ.rect.ly)
        s.constrain(poly.rect.ly == 0)
        x_cur = poly.rect.ux + 140

    l.activ = LayoutRect(layer=layers.Activ)
    s.constrain(l.activ.rect.height == W)
    s.constrain(l.activ.rect.lx == 0)
    x_cur = l.activ.rect.lx + 70

    add_sd(0)
    for i in range(num_gates):
        add_poly(i)
        add_sd(i+1)

    s.constrain(l.activ.rect.ux == x_cur + 70)

    if pmos:
        l.psd = LayoutRect(layer=layers.pSD)
        s.constrain(l.psd.rect.cx == l.activ.rect.cx)
        s.constrain(l.psd.rect.cy == l.activ.rect.cy)
        s.constrain(l.psd.rect.ux == l.activ.rect.ux + 180)
        s.constrain(l.psd.rect.uy == l.activ.rect.uy + 300)

        l.nwell = LayoutRect(layer=layers.NWell)
        s.constrain(l.nwell.rect.cx == l.activ.rect.cx)
        s.constrain(l.nwell.rect.cy == l.activ.rect.cy)
        s.constrain(l.nwell.rect.ux == l.activ.rect.ux + 310)
        s.constrain(l.nwell.rect.uy == l.activ.rect.uy + 385)

    s.solve()

    for i in range(num_gates + 1):
        makevias(l, l.sd[i].rect, layers.Cont, 
            size=Vec2I(160, 160),
            spacing=Vec2I(180, 180),
            margin=Vec2I(50, 50),
            cols=1,
            )
        
    return l


@public
def run_drc(l: Layout, variant='maximal'):
    if variant not in ('minimal', 'maximal'):
        raise ValueError("variant must be either 'minimal' or 'maximal'.")

    with tempfile.TemporaryDirectory() as cwd_str:
        cwd = Path(cwd_str)
        with open(cwd / "layout.gds", "wb") as f:
            name_of_layout = write_gds(l, f)

        klayout.run(pdk().klayout_drc_deck[variant], cwd,
            in_gds="layout.gds",
            report_file="drc.xml",
            log_file="drc.log",
            cell=name_of_layout[l],
            )

        log = (cwd / "drc.log").read_text() # currently ignored
        return klayout.parse_rdb(cwd / "drc.xml", name_of_layout)

@public
def run_lvs(layout: Layout, schematic: Schematic):
    layout = layout.freeze()
    schematic = schematic.freeze()

    nl = Netlister(lvs=True)
    nl.netlist_hier(schematic, top_as_subckt=True)
    #tmp_tmp = Path.cwd() / 'tmp/tmp'
    #tmp_tmp.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as cwd_str:
        tmp_dir = Path(cwd_str)

        # The LVS script sometimes creates files in the parent directory of the
        # input data. To avoid issues connected to this, use a subdirectory for
        # all files.
        cwd = tmp_ddir / 'lvs'
        cwd.mkdir(exist_ok=True)

        path_schematic = cwd / 'schematic.cir'
        path_layout = cwd / 'layout.gds'

        print(nl.out())
        path_schematic.write_text(nl.out())

        with open(path_layout, "wb") as f:
            write_gds(layout, f)

        klayout.run(
            ihp130.pdk().klayout_lvs_deck,
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

            topcell='MyInv', # TODO
            input='myinv.gds',
            schematic='schematic.cir',
            
            #topcell='sg13g2_inv_1',
            #input='sg13g2_inv_1.gds',
            #schematic='sg13g2_inv_1.cdl',
            )


class Mos(Cell):
    l = Parameter(R)  #: Length
    w = Parameter(R)  #: Width
    m = Parameter(int, default=1)  #: Multiplier (number of devices in parallel)
    ng = Parameter(int, default=1)  #: Number of gate fingers

    def netlist_ngspice(self, netlister, inst, schematic):
        netlister.require_netlist_setup(netlister_setup)
        netlister.require_ngspice_setup(ngspice_setup)
        pins = [inst.symbol.d, inst.symbol.g, inst.symbol.s, inst.symbol.b]
        netlister.add(
            netlister.name_obj(inst, schematic, prefix="x"),
            netlister.portmap(inst, pins),
            self.model_name,
            *helpers.spice_params({
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
        return layoutgen_mos(self, self.l, self.w, self.ng, pmos=False)

@public
class Pmos(Mos, generic_mos.Pmos):
    model_name = "sg13_lv_pmos"

    @generate
    def layout(self) -> Layout:
        return layoutgen_mos(self, self.l, self.w, self.ng, pmos=True)
