# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
import tempfile
from pathlib import Path
from public import public
import functools

from ..core import *
from ..schematic import helpers
from ..schematic.netlister import Netlister
from . import generic_mos
from .pdk_common import PdkDict, check_dir, check_file, rundir
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

    pdk.ngspice_models_dir       =  check_dir(pdk.root / "libs.tech/ngspice/models")
    pdk.ngspice_osdi_dir         =  check_dir(pdk.root / "libs.tech/ngspice/osdi")
    pdk.stdcell_spice_dir        =  check_dir(pdk.root / "libs.ref/sg13g2_stdcell/spice")
    pdk.iocell_spice_dir         =  check_dir(pdk.root / "libs.ref/sg13g2_io/spice")
    pdk.klayout_lvs_deck         = check_file(pdk.root / "libs.tech/klayout/tech/lvs/sg13g2.lvs")
    pdk.klayout_drc_decks_dir    =  check_dir(pdk.root / "libs.tech/klayout/tech/drc/rule_decks")
    pdk.klayout_drc_mod_json     = check_file(pdk.root / "libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech_mod.json")
    pdk.klayout_drc_default_json = check_file(pdk.root / "libs.tech/klayout/tech/drc/rule_decks/sg13g2_tech_default.json")

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

    l.mkpath('poly')
    l.mkpath('sd')

    activ_ext = None

    def add_sd(i):
        nonlocal l, s, x_cur, activ_ext
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
        x_cur += 110
        l.poly[i] = LayoutRect(layer=layers.GatPoly)
        poly = l.poly[i]
        s.constrain(poly.rect.cy == l.activ.rect.cy)
        s.constrain(poly.rect.width == L)
        s.constrain(poly.rect.lx == x_cur)
        s.constrain(poly.rect.ly + 180 == l.activ.rect.ly)
        s.constrain(poly.rect.ly == 0)
        x_cur = poly.rect.ux + 110

    l.activ = LayoutRect(layer=layers.Activ)
    s.constrain(l.activ.rect.height == W)
    s.constrain(l.activ.rect.lx == 0)
    x_cur = l.activ.rect.lx + 70

    add_sd(0)
    for i in range(num_gates):
        add_poly(i)
        add_sd(i+1)

    s.constrain(l.activ.rect.ux == x_cur + 70)

    if nwell:
        l.psd = LayoutRect(layer=layers.pSD)
        s.constrain(l.psd.rect.cx == l.activ.rect.cx)
        s.constrain(l.psd.rect.cy == l.activ.rect.cy)
        s.constrain(l.psd.rect.ux == l.activ.rect.ux + 180)
        s.constrain(l.psd.rect.uy == l.activ.rect.uy + 300)

        if activ_ext is None:
            max_activ = l.activ
        else:
            max_activ = activ_ext
        l.nwell = LayoutRect(layer=layers.NWell)
        s.constrain(l.nwell.rect.cx == l.activ.rect.cx)
        s.constrain(l.nwell.rect.cy == max_activ.rect.cy)
        s.constrain(l.nwell.rect.ux == l.activ.rect.ux + 310)
        s.constrain(l.nwell.rect.uy == max_activ.rect.uy + 310)

    s.solve()

    for i in range(num_gates + 1):
        makevias(l, l.sd[i].rect, layers.Cont, 
            size=Vec2I(160, 160),
            spacing=Vec2I(180, 180),
            margin=Vec2I(50, 50),
            cols=1,
            )
        
    return l


class Mos(Cell):
    l = Parameter(R)  #: Length
    w = Parameter(R)  #: Width
    m = Parameter(int, default=1)  #: Multiplier, i. e. number of devices with separate Activ areas in parallel)
    ng = Parameter(int, default=1)  #: Number of gate fingers

    def netlist_ngspice(self, netlister, inst):
        netlister.require_netlist_setup(netlister_setup)
        netlister.require_ngspice_setup(ngspice_setup)
        pins = [inst.symbol.d, inst.symbol.g, inst.symbol.s, inst.symbol.b]
        netlister.add(
            netlister.name_obj(inst, prefix="M" if netlister.lvs else "x"),
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
    s.constrain(l.activ.rect.height == W)
    s.constrain(l.activ.rect.width == L)
    s.constrain(l.activ.rect.lx == 0)
    s.constrain(l.activ.rect.ly == 0)

    l.m1 = LayoutRect(layer=layers.Metal1)

    # TODO: add Metal1 pin?!

    if nwell:
        l.nwell = LayoutRect(layer=layers.NWell)
        s.constrain(l.nwell.rect.cx == l.activ.rect.cx)
        s.constrain(l.nwell.rect.cy == l.activ.rect.cy)
        s.constrain(l.nwell.rect.ux == l.activ.rect.ux + 240)
        s.constrain(l.nwell.rect.uy == l.activ.rect.uy + 240)

        l.nbulay = LayoutRect(layer=layers.nBuLay)
        s.constrain(l.nbulay.rect.lx == l.nwell.rect.lx)
        s.constrain(l.nbulay.rect.ly == l.nwell.rect.ly)
        s.constrain(l.nbulay.rect.ux == l.nwell.rect.ux)
        s.constrain(l.nbulay.rect.uy == l.nwell.rect.uy)


    else:
        l.psd = LayoutRect(layer=layers.pSD)
        s.constrain(l.psd.rect.cx == l.activ.rect.cx)
        s.constrain(l.psd.rect.cy == l.activ.rect.cy)
        s.constrain(l.psd.rect.ux == l.activ.rect.ux + 30)
        s.constrain(l.psd.rect.uy == l.activ.rect.uy + 30)

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

# klayout-new -b -r '/home/tobias/workspace/ordec/lvs/drc_run_2025_11_26_13_11_34/main.drc'
#     -rd drc_json_default='/home/tobias/workspace/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/sg13g2_tech_default.json'
#     -rd         drc_json='/home/tobias/workspace/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech_mod.json'


def drc_build_main_deck():
    drc_decks_dir = pdk().klayout_drc_decks_dir
    drc_deck = []
    drc_deck.append((drc_decks_dir / 'main.drc').read_text())
    for fn in drc_decks_dir.glob("*.drc"):
        if fn.stem in ('antenna', 'density', 'sg13g2_maximal', 'main', 'layers_def', 'tail'):
            continue
        drc_deck.append(fn.read_text())
    drc_deck.append((drc_decks_dir / 'tail.drc').read_text())

    return "\n".join(drc_deck)

@public
def run_drc(l: Layout, variant='maximal', use_tempdir: bool=True):
    if variant not in ('minimal', 'maximal'):
        raise ValueError("variant must be either 'minimal' or 'maximal'.")

    drc_decks_dir = pdk().klayout_drc_decks_dir

    directory = Directory()

    with rundir('drc', use_tempdir) as cwd:
        with open(cwd / "layout.gds", "wb") as f:
            write_gds(l, f, directory)

        klayout_shared_opts = dict(
            thr=str(os.cpu_count()), # Number of threads for density checks
            drc_json_default=pdk().klayout_drc_default_json,
            drc_json=pdk().klayout_drc_mod_json,
            topcell=directory.name_subgraph(l),
            input="layout.gds",
            run_mode="deep",
            precheck_drc="false",
            disable_extra_rules="false",
            no_feol="false",
            no_beol="false",
            no_offgrid="false",
            density="true",
        )

        (cwd / 'main.log').unlink(missing_ok=True)
        (cwd / 'main.drc').write_text(drc_build_main_deck())
        (cwd / 'layers_def.drc').write_text((drc_decks_dir / 'layers_def.drc').read_text())

        klayout.run(cwd / 'main.drc', cwd,
            report="main.lyrdb",
            log="main.log",
            table_name="main",
            **klayout_shared_opts
            )

        # (cwd / 'density.log').unlink(missing_ok=True)
        # klayout.run(drc_decks_dir / 'density.drc', cwd,
        #    report="density.lyrdb",
        #    log="density.log",
        #    table_name="density",
        #    **klayout_shared_opts
        #    )
    
        log = (cwd / "main.log").read_text() # currently ignored
        return klayout.parse_rdb(cwd / "main.lyrdb", directory)


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
