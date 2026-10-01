# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import math
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass
from public import public
import functools
from enum import Enum

from ..schematic.spice_in import DeviceMapping
from ..core import *
from ..schematic import spice_params, Netlister
from ..sim.ngspice import NgspiceSetup
from . import generic_mos
from .pdk_common import PdkDict, check_dir, check_file, rundir
from ..layout import makevias, write_gds
from ..layout import klayout
from ..layout.pnr import GridConfig

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
    pdk.stdcell_lef              = check_file(pdk.root / "libs.ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef")
    # Liberty files, one per PVT corner (process_voltage_temperature):
    stdcell_corners = ['fast_1p32V_m40C', 'fast_1p65V_m40C', 'typ_1p20V_25C',
        'typ_1p50V_25C', 'slow_1p08V_125C', 'slow_1p35V_125C']
    pdk.stdcell_lib = {
        cnr: check_file(pdk.root / f"libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_{cnr}.lib")
            for cnr in stdcell_corners
        }
    pdk.stdcell_gds              = check_file(pdk.root / "libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds")
    pdk.stdcell_spice            = check_file(pdk.root / "libs.ref/sg13g2_stdcell/spice/sg13g2_stdcell.spice")
    pdk.iocell_spice_dir         =  check_dir(pdk.root / "libs.ref/sg13g2_io/spice")
    pdk.klayout_lvs_deck         = check_file(pdk.root / "libs.tech/klayout/tech/lvs/sg13g2.lvs")
    pdk.klayout_drc_main_deck    = check_file(pdk.root / "libs.tech/klayout/tech/drc/ihp-sg13g2.drc")
    pdk.klayout_drc_decks_dir    =  check_dir(pdk.root / "libs.tech/klayout/tech/drc/rule_decks")
    pdk.klayout_drc_mod_json     = check_file(pdk.root / "libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech_mod.json")
    pdk.klayout_drc_default_json = check_file(pdk.root / "libs.tech/klayout/tech/drc/rule_decks/sg13g2_tech_default.json")

    return pdk

def ngspice_setup():
    """Return ngspice setup commands and environment variables."""
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
    return NgspiceSetup(
        commands=commands,
        env={"PDK": "ihp-sg13g2", "PDK_ROOT": str(pdk().root)},
    )

@public
class MosCorner(Enum):
    """MOS corner (section mos_<value> of cornerMOSlv.lib)."""
    TT = 'tt'
    SS = 'ss'
    FF = 'ff'
    SF = 'sf'
    FS = 'fs'

@public
class ResCorner(Enum):
    """Resistor corner (section res_<value> of cornerRES.lib)."""
    TYP = 'typ'
    BCS = 'bcs' #: Best case: low resistance
    WCS = 'wcs' #: Worst case: high resistance

@public
class CapCorner(Enum):
    """Capacitor corner (section cap_<value> of cornerCAP.lib)."""
    TYP = 'typ'
    BCS = 'bcs' #: Best case: low capacitance
    WCS = 'wcs' #: Worst case: high capacitance

@public
class HbtCorner(Enum):
    """HBT corner (section hbt_<value> of cornerHBT.lib)."""
    TYP = 'typ'
    BCS = 'bcs' #: Best case: fast
    WCS = 'wcs' #: Worst case: slow

@public
class Corner:
    """
    Process corner for simulation: one MOS, resistor, capacitor and HBT
    corner each, which the PDK varies independently. The MOS corner applies
    to LV and HV devices alike. Pass as ``corner`` to
    :meth:`SimHierarchy.simulate`. Strings are coerced to the enums, e.g.
    ``Corner(mos='ss', cap='wcs')``. The class attributes ``Corner.TT``,
    ``Corner.SS``, ``Corner.FF``, ``Corner.SF`` and ``Corner.FS`` are the
    MOS corners with the other devices typical.
    """
    def __init__(self, mos='tt', res='typ', cap='typ', hbt='typ'):
        self.mos = MosCorner(mos)
        self.res = ResCorner(res)
        self.cap = CapCorner(cap)
        self.hbt = HbtCorner(hbt)

    def __repr__(self):
        return (f"Corner(mos={self.mos.value!r}, res={self.res.value!r}, "
            f"cap={self.cap.value!r}, hbt={self.hbt.value!r})")

    def __eq__(self, other):
        if not isinstance(other, Corner):
            return NotImplemented
        return ((self.mos, self.res, self.cap, self.hbt)
            == (other.mos, other.res, other.cap, other.hbt))

    def __hash__(self):
        return hash((self.mos, self.res, self.cap, self.hbt))

Corner.TT = Corner(mos='tt')
Corner.SS = Corner(mos='ss')
Corner.FF = Corner(mos='ff')
Corner.SF = Corner(mos='sf')
Corner.FS = Corner(mos='fs')

def netlister_corner(netlister) -> Corner:
    corner = Corner.TT if netlister.corner is None else netlister.corner
    if not isinstance(corner, Corner):
        raise TypeError(
            f"ihp130 expects an ihp130.Corner, not {netlister.corner!r}.")
    return corner

def netlister_setup(netlister):
    if netlister.lvs:
        return

    corner = netlister_corner(netlister)
    model_lib = pdk().ngspice_models_dir / "cornerMOSlv.lib"
    netlister.add(".lib", f"\"{model_lib}\" mos_{corner.mos.value}")
    model_lib = pdk().ngspice_models_dir / "cornerRES.lib"
    netlister.add(".lib", f"\"{model_lib}\" res_{corner.res.value}")
    model_lib = pdk().ngspice_models_dir / "cornerCAP.lib"
    netlister.add(".lib", f"\"{model_lib}\" cap_{corner.cap.value}")

    # Add options from .spiceinit
    netlister.add(".option", "tnom=28")
    netlister.add(".option", "warn=1")
    netlister.add(".option", "maxwarns=10")
    #netlister.add(".option", "savecurrents")

def netlister_setup_mos_hv(netlister):
    """HV MOS and varicap models."""
    if netlister.lvs:
        return
    model_lib = pdk().ngspice_models_dir / "cornerMOShv.lib"
    netlister.add(".lib", f"\"{model_lib}\" mos_{netlister_corner(netlister).mos.value}")

def netlister_setup_hbt(netlister):
    if netlister.lvs:
        return
    model_lib = pdk().ngspice_models_dir / "cornerHBT.lib"
    netlister.add(".lib", f"\"{model_lib}\" hbt_{netlister_corner(netlister).hbt.value}")

def netlister_setup_bondpad(netlister):
    """The bondpad model, which no corner library includes."""
    if netlister.lvs:
        return
    netlister.add(".include", f"\"{pdk().ngspice_models_dir / 'sg13g2_bondpad.lib'}\"")

@dataclass(frozen=True)
class ViaRule:
    """One via type of the PDK's via PCells (sg13_tech_info.py), in nm."""
    bottom: str         #: Bottom layer
    cut: str            #: Cut layer
    top: str            #: Top layer
    size: int           #: Cut width
    space: int          #: Cut spacing
    space_dense: int    #: x spacing with more than dense_nr cuts both ways
    dense_nr: int
    enc_bottom: int     #: Bottom enclosure at the sides
    endcap_bottom: int  #: Bottom enclosure at the ends
    enc_top: int        #: Top enclosure at the sides
    endcap_top: int     #: Top enclosure at the ends
    min_bottom: int     #: Minimum bottom plate width and height
    min_top: int        #: Minimum top plate width and height

# In the PDK's order, bottom to top.
VIA_RULES = {
    "SG13G2_CONT_GATPOLY_M1": ViaRule("GatPoly", "Cont", "Metal1", 160, 180, 200, 4, 70, 70, 0, 50, 160, 160),
    "SG13G2_CONT_ACTIV_M1": ViaRule("Activ", "Cont", "Metal1", 160, 180, 200, 4, 70, 70, 0, 50, 160, 160),
    "SG13G2_VIA_M1_M2": ViaRule("Metal1", "Via1", "Metal2", 190, 220, 290, 3, 10, 50, 5, 50, 160, 200),
    "SG13G2_VIA_M2_M3": ViaRule("Metal2", "Via2", "Metal3", 190, 220, 290, 3, 5, 50, 5, 50, 200, 200),
    "SG13G2_VIA_M3_M4": ViaRule("Metal3", "Via3", "Metal4", 190, 220, 290, 3, 5, 50, 5, 50, 200, 200),
    "SG13G2_VIA_M4_M5": ViaRule("Metal4", "Via4", "Metal5", 190, 220, 290, 3, 5, 50, 5, 50, 200, 200),
    "SG13G2_VIA_M5_TM1": ViaRule("Metal5", "TopVia1", "TopMetal1", 420, 420, 420, 0, 100, 100, 420, 420,
        200, 1640),
    "SG13G2_VIA_TM1_TM2": ViaRule("TopMetal1", "TopVia2", "TopMetal2", 900, 1060, 1060, 0, 500, 500, 500, 500,
        1640, 2000),
}

@public
class SG13G2(Cell):
    @viewgen_noctx
    def layers(self):
        s = LayerStack(cell=self)

        s.unit = R('1n')

        # Frontend layers
        # ---------------

        s.Activ = Layer(
            gdslayer_shapes=GdsLayer(layer=1, data_type=0),
            style_fill=rgb_color("#00ff00"),
            pin=s % Layer(
                gdslayer_shapes=GdsLayer(layer=1, data_type=2),
                style_fill=rgb_color("#00ff00"),
                is_pinlayer=True,
            ),
            )
        s.Activ.mask = Layer(
            gdslayer_shapes=GdsLayer(layer=1, data_type=20),
            style_fill=rgb_color("#00ff00"),
            )
        s.Activ.noqrc = Layer(
            gdslayer_shapes=GdsLayer(layer=1, data_type=28),
            style_fill=rgb_color("#ff0000"),
            )
        s.Activ.nofill = Layer(
            gdslayer_shapes=GdsLayer(layer=1, data_type=23),
            style_fill=rgb_color("#00ff00"),
            )

        s.GatPoly = Layer(
            gdslayer_shapes=GdsLayer(layer=5, data_type=0),
            style_fill=rgb_color("#bf4026"),
            pin=s % Layer(
                gdslayer_shapes=GdsLayer(layer=5, data_type=2),
                style_fill=rgb_color("#bf4026"),
                is_pinlayer=True,
            ),
        )
        s.GatPoly.nofill = Layer(
            gdslayer_shapes=GdsLayer(layer=5, data_type=23),
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

        s.nSD = Layer(
            gdslayer_shapes=GdsLayer(layer=7, data_type=0),
            style_fill=rgb_color("#99b8d9"),
            )
        s.nSD.block = Layer(
            gdslayer_shapes=GdsLayer(layer=7, data_type=21),
            style_fill=rgb_color("#00cc66"),
            )

        s.NWell = Layer(
            gdslayer_shapes=GdsLayer(layer=31, data_type=0),
            gdslayer_text=GdsLayer(layer=31, data_type=0),
            style_fill=rgb_color("#268c6b"),
            pin=s % Layer(
                gdslayer_text=GdsLayer(layer=31, data_type=25),
                gdslayer_shapes=GdsLayer(layer=31, data_type=2),
                style_fill=rgb_color("#268c6b"),
                is_pinlayer=True,
            ),
            )

        s.nBuLay = Layer(
            gdslayer_shapes=GdsLayer(layer=32, data_type=0),
            style_fill=rgb_color("#8c8ca6"),
            )

        s.PWell = Layer(
            gdslayer_shapes=GdsLayer(layer=46, data_type=0),
            style_fill=rgb_color("#ffff00"),
            )
        s.PWell.block = Layer(
            gdslayer_shapes=GdsLayer(layer=46, data_type=21),
            style_fill=rgb_color("#ff8000"),
            )

        s.ThickGateOx = Layer(
            gdslayer_shapes=GdsLayer(layer=44, data_type=0),
            style_fill=rgb_color("#ffffcc"),
            )

        s.TRANS = Layer(
            gdslayer_shapes=GdsLayer(layer=26, data_type=0),
            style_fill=rgb_color("#00ffff"),
            )

        s.EmWind = Layer(
            gdslayer_shapes=GdsLayer(layer=33, data_type=0),
            style_fill=rgb_color("#00cc66"),
            )

        s.EmWiHV = Layer(
            gdslayer_shapes=GdsLayer(layer=156, data_type=0),
            style_fill=rgb_color("#00cc66"),
            )

        # Metal stack
        # -----------

        def metal(layer, color):
            """Insert a metal layer with its pin layer; the caller names the metal."""
            pin = s % Layer(
                gdslayer_text=GdsLayer(layer=layer, data_type=25),
                gdslayer_shapes=GdsLayer(layer=layer, data_type=2),
                style_fill=color,
                is_pinlayer=True,
            )
            return s % Layer(
                gdslayer_shapes=GdsLayer(layer=layer, data_type=0),
                style_fill=color,
                pin=pin,
            )

        def via(layer, color):
            return Layer(
                gdslayer_shapes=GdsLayer(layer=layer, data_type=0),
                style_stroke=color,
                style_crossrect=True,
            )

        s.Metal1 = metal(8, rgb_color("#39bfff"))
        s.Via1 = via(19, rgb_color("#ccccff"))
        s.Metal2 = metal(10, rgb_color("#ccccd9"))
        s.Via2 = via(29, rgb_color("#ff3736"))
        s.Metal3 = metal(30, rgb_color("#d80000"))
        s.Via3 = via(49, rgb_color("#9ba940"))
        s.Metal4 = metal(50, rgb_color("#93e837"))
        s.Via4 = via(66, rgb_color("#deac5e"))
        s.Metal5 = metal(67, rgb_color("#dcd146"))
        s.TopVia1 = via(125, rgb_color("#ffe6bf"))
        s.TopMetal1 = metal(126, rgb_color("#ffe6bf"))
        s.TopVia2 = via(133, rgb_color("#ff8000"))
        s.TopMetal2 = metal(134, rgb_color("#ff8000"))

        for m in (s.Metal1, s.Metal2, s.Metal3, s.Metal4, s.Metal5, s.TopMetal1):
            m.noqrc = Layer(
                gdslayer_shapes=GdsLayer(layer=m.gdslayer_shapes.layer, data_type=28),
                style_fill=rgb_color("#ff0000"),
                )
        for m in (s.Metal1, s.Metal2, s.Metal3, s.Metal4, s.Metal5, s.TopMetal1, s.TopMetal2):
            n = m.gdslayer_shapes.layer
            m.mask = Layer(
                gdslayer_shapes=GdsLayer(layer=n, data_type=20),
                style_fill=m.style_fill,
                )
            m.nofill = Layer(
                gdslayer_shapes=GdsLayer(layer=n, data_type=23),
                style_fill=m.style_fill,
                )
            # Metal resistor marker and probe points
            m.res = Layer(
                gdslayer_shapes=GdsLayer(layer=n, data_type=29),
                style_fill=rgb_color("#bf4026"),
                )
            m.iprobe = Layer(
                gdslayer_shapes=GdsLayer(layer=n, data_type=33),
                style_fill=m.style_fill,
                )
            m.diffprb = Layer(
                gdslayer_shapes=GdsLayer(layer=n, data_type=34),
                style_fill=m.style_fill,
                )

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
            gdslayer_text=GdsLayer(layer=40, data_type=0),
            style_fill=rgb_color("#ffffff"),
            )

        s.HeatTrans = Layer(
            gdslayer_shapes=GdsLayer(layer=51, data_type=0),
            gdslayer_text=GdsLayer(layer=51, data_type=0),
            style_fill=rgb_color("#8c8ca6"),
            )

        s.HeatRes = Layer(
            gdslayer_shapes=GdsLayer(layer=52, data_type=0),
            gdslayer_text=GdsLayer(layer=52, data_type=0),
            style_fill=rgb_color("#8c8ca6"),
            )

        s.IND = Layer(
            gdslayer_shapes=GdsLayer(layer=27, data_type=0),
            style_fill=rgb_color("#ffff00"),
            pin=s % Layer(
                gdslayer_text=GdsLayer(layer=27, data_type=25),
                gdslayer_shapes=GdsLayer(layer=27, data_type=2),
                style_fill=rgb_color("#ffff00"),
                is_pinlayer=True,
            ),
            )

        s.IND.boundary = Layer(
            gdslayer_shapes=GdsLayer(layer=27, data_type=4),
            style_fill=rgb_color("#ffff00"),
            )

        s.NoRCX = Layer(
            gdslayer_shapes=GdsLayer(layer=148, data_type=0),
            style_fill=rgb_color("#ff0000"),
            )

        s.DigiBnd = Layer(
            gdslayer_shapes=GdsLayer(layer=16, data_type=0),
            style_fill=rgb_color("#ff0000"),
            )

        s.SRAM = Layer(
            gdslayer_shapes=GdsLayer(layer=25, data_type=0),
            style_fill=rgb_color("#ffff00"),
            )

        s.MemCap = Layer(
            gdslayer_shapes=GdsLayer(layer=69, data_type=0),
            style_fill=rgb_color("#ff00ff"),
            )

        s.Passiv = Layer(
            gdslayer_shapes=GdsLayer(layer=9, data_type=0),
            style_fill=rgb_color("#e61f0d"),
            )

        s.dfpad = Layer(
            gdslayer_shapes=GdsLayer(layer=41, data_type=0),
            style_fill=rgb_color("#5e00e6"),
            )

        s.EdgeSeal = Layer(
            gdslayer_shapes=GdsLayer(layer=39, data_type=0),
            style_fill=rgb_color("#5e00e6"),
            )

        s.EdgeSealBoundary = Layer(
            gdslayer_shapes=GdsLayer(layer=39, data_type=4),
            style_stroke=rgb_color("#5e00e6"),
            )

        s.TEXT = Layer(
            gdslayer_text=GdsLayer(layer=63, data_type=0),
            gdslayer_shapes=GdsLayer(layer=63, data_type=0),
            )

        s.Recog = Layer(
            gdslayer_shapes=GdsLayer(layer=99, data_type=0),
            style_fill=rgb_color("#bdcccc"),
            )
        s.Recog.esd = Layer(
            gdslayer_shapes=GdsLayer(layer=99, data_type=30),
            style_fill=rgb_color("#ffff00"),
            )
        s.Recog.diode = Layer(
            gdslayer_shapes=GdsLayer(layer=99, data_type=31),
            style_fill=rgb_color("#5e00e6"),
            )
        s.Recog.mom = Layer(
            gdslayer_shapes=GdsLayer(layer=99, data_type=39),
            style_fill=rgb_color("#268c6b"),
            )

        s.Vmim = Layer(
            gdslayer_shapes=GdsLayer(layer=129, data_type=0),
            style_fill=rgb_color("#ffe6bf"),
            )

        s.PolyRes = Layer(
            gdslayer_shapes=GdsLayer(layer=128, data_type=0),
            style_fill=rgb_color("#cc6633"),
            pin=s % Layer(
                gdslayer_shapes=GdsLayer(layer=128, data_type=2),
                style_fill=rgb_color("#cc6633"),
                is_pinlayer=True,
            ),
        )

        s.prBoundary = Layer(
            gdslayer_shapes=GdsLayer(layer=189, data_type=4), # data_type 4 or 0?
            style_fill=rgb_color("#9900e6"),
            style_stroke=rgb_color("#ff00ff"),
            )
        s.prBoundary.drawing = Layer(
            gdslayer_shapes=GdsLayer(layer=189, data_type=0),
            style_stroke=rgb_color("#ff00ff"),
            )

        s.NoMetFiller = Layer(
            gdslayer_shapes=GdsLayer(layer=160, data_type=0),
            style_fill=rgb_color("#ff0000"),
            )
        s.LBE = Layer(
            gdslayer_shapes=GdsLayer(layer=157, data_type=0),
            style_fill=rgb_color("#bfbfbf"),
            )
        s.DigiSub = Layer(
            gdslayer_shapes=GdsLayer(layer=60, data_type=0),
            style_fill=rgb_color("#ff00ff"),
            )

        # Further purposes of the PDK layers, as hand-drawn layouts use them:
        # fill, labels, text shapes and boundaries.
        metals = (s.Metal1, s.Metal2, s.Metal3, s.Metal4, s.Metal5, s.TopMetal1, s.TopMetal2)
        vias = (s.Cont, s.Via1, s.Via2, s.Via3, s.Via4, s.TopVia1, s.TopVia2)
        for l in (s.Activ, s.GatPoly) + metals:
            l.filler = Layer(
                gdslayer_shapes=GdsLayer(layer=l.gdslayer_shapes.layer, data_type=22),
                style_fill=l.style_fill,
                )
        for l in (s.Activ, s.GatPoly, s.PolyRes, s.NWell, s.nBuLay, s.PWell, s.Passiv, s.RES, s.SRAM,
            s.prBoundary) + metals:
            l.label = Layer(gdslayer_text=GdsLayer(layer=l.gdslayer_shapes.layer, data_type=1))
        for l in metals:
            l.text = Layer(
                gdslayer_shapes=GdsLayer(layer=l.gdslayer_shapes.layer, data_type=25),
                style_fill=l.style_fill,
                )
        for l in (s.Activ, s.GatPoly, s.PolyRes, s.NWell, s.nBuLay, s.PWell, s.MIM, s.Passiv, s.SRAM) \
            + metals + vias:
            l.boundary = Layer(
                gdslayer_shapes=GdsLayer(layer=l.gdslayer_shapes.layer, data_type=4),
                style_stroke=l.style_fill or l.style_stroke,
                )

        return s

    @viewgen_noctx
    def default_routing_spec(self):
        layers = self.layers
        rs = RoutingSpec(ref_layers=layers)

        route_id = 0
        via1 = VIA_RULES["SG13G2_VIA_M1_M2"]
        topvia1 = VIA_RULES["SG13G2_VIA_M5_TM1"]
        topvia2 = VIA_RULES["SG13G2_VIA_TM1_TM2"]

        # route_pad is the 190nm via cut plus the 10nm enclosure that V1.c
        # demands on all sides (V2.c to V4.c ask for only 5nm). The endcap
        # enclosure (V1.c1 etc., 50nm) comes from the wire running into the
        # pad, so a pad this size widens a 200nm wire by just 5nm per side.
        pad = via1.size + 2*via1.enc_bottom
        def addmetal(layer, route_width=200, route_ext=100+50, route_via=(480,300),
            route_pad=(pad, pad)):
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

        def addvia(layer, rule):
            nonlocal route_id
            rs % RoutingSpecLayer(
                layer=layer,
                route_id=route_id,
                route_via_width=rule.size,
                route_via_height=rule.size,
            )
            route_id += 1

        addmetal(layers.Metal1)
        addvia(layers.Via1, via1)
        addmetal(layers.Metal2)
        addvia(layers.Via2, VIA_RULES["SG13G2_VIA_M2_M3"])
        addmetal(layers.Metal3)
        addvia(layers.Via3, VIA_RULES["SG13G2_VIA_M3_M4"])
        addmetal(layers.Metal4)
        addvia(layers.Via4, VIA_RULES["SG13G2_VIA_M4_M5"])
        m5_pad = topvia1.size + 2*topvia1.enc_bottom
        addmetal(layers.Metal5, route_via=(m5_pad, m5_pad), route_pad=(m5_pad, m5_pad))
        addvia(layers.TopVia1, topvia1)
        tm1_via = topvia2.size + 2*topvia2.enc_bottom
        addmetal(layers.TopMetal1, route_width=topvia1.min_top, route_via=(tm1_via, tm1_via),
            route_pad=(topvia1.min_top, topvia1.min_top))
        addvia(layers.TopVia2, topvia2)
        tm2 = topvia2.min_top
        addmetal(layers.TopMetal2, route_width=tm2, route_via=(tm2, tm2), route_pad=(tm2, tm2))

        return rs

def draw_cont_array(layout: Layout, rect: Rect4I) -> Rect4I:
    """Contact array in an Activ rect as DrawContArray in the PDK PCells, returns its bbox."""
    layers = SG13G2().layers

    # Contact array replicating the PDK tap PCells (DrawContArray).
    cont = VIA_RULES["SG13G2_CONT_ACTIV_M1"]
    spacing = cont.space
    cols = (rect.width - 2*cont.enc_bottom + spacing) // (cont.size + spacing)
    rows = (rect.height - 2*cont.enc_bottom + spacing) // (cont.size + spacing)
    if min(cols, rows) >= 4:
        spacing = cont.space_dense  # Cnt.b1: spacing in arrays of 4 x 4 or more

    return makevias(layout, rect, layers.Cont,
        size=Vec2I(cont.size, cont.size),
        spacing=Vec2I(spacing, spacing),
        margin=Vec2I(cont.enc_bottom, cont.enc_bottom),
        )

def contact_array(layout: Layout, rect: Rect4I, layer: Layer, size: int, spacing: int,
    margin: Vec2I):
    """
    Via array as contactArray in the PDK PCells: as many vias as fit, the
    outer ones at margin from the edges, the rest spread evenly on the 5 nm
    grid. A single via is centered.
    """
    def positions(lo, extent, margin):
        count = (extent - 2*margin + spacing) // (size + spacing)
        if count == 1:
            return [lo + 5 * ((extent - size) // 10)]
        return [lo + 5 * ((margin*(count - 1) + k*(extent - 2*margin - size)) // (5*(count - 1)))
            for k in range(count)]

    for x in positions(rect.lx, rect.width, margin.x):
        for y in positions(rect.ly, rect.height, margin.y):
            layout % LayoutRect(layer=layer, rect=Rect4I(x, y, x + size, y + size))

def metal_cont(layout: Layout, metal: Layer, via: Layer, x1: int, y1: int, x2: int, y2: int,
    width: int, size: int, offset: int, space: int, dy: int = 0) -> LayoutRect:
    """
    Metal line from (x1, y1) to (x2, y2) with vias along it, shifted by dy,
    as MetalCont in the PDK PCells. Returns the metal rect.
    """
    def to_grid(v):  # tog in the PCells
        return v - v % 5

    horizontal = y1 == y2
    lo, hi = sorted((x1, x2) if horizontal else (y1, y2))
    center = y1 if horizontal else x1
    # One row of vias along the line, spread as contactArray spreads them.
    across = to_grid(center - size // 2)
    if horizontal:
        contact_array(layout, Rect4I(lo, across + dy, hi, across + size + dy), via, size, space,
            Vec2I(offset, 0))
    else:
        contact_array(layout, Rect4I(across, lo + dy, across + size, hi + dy), via, size, space,
            Vec2I(0, offset))
    across_lo, across_hi = to_grid(center - width // 2), to_grid(center + width // 2)
    rect = Rect4I(to_grid(lo), across_lo, to_grid(hi), across_hi) if horizontal \
        else Rect4I(across_lo, to_grid(lo), across_hi, to_grid(hi))
    return layout % LayoutRect(layer=metal, rect=Rect4I(rect.lx, rect.ly + dy, rect.ux, rect.uy + dy))

def ring(layout: Layout, layer: Layer, outer: Rect4I, inner: Rect4I):
    """Insert the area between the rects outer and inner as four rects."""
    layout % LayoutRect(layer=layer, rect=Rect4I(outer.lx, outer.ly, outer.ux, inner.ly))
    layout % LayoutRect(layer=layer, rect=Rect4I(outer.lx, inner.uy, outer.ux, outer.uy))
    layout % LayoutRect(layer=layer, rect=Rect4I(outer.lx, inner.ly, inner.lx, inner.uy))
    layout % LayoutRect(layer=layer, rect=Rect4I(inner.ux, inner.ly, outer.ux, inner.uy))

def layoutgen_mos(cell: Cell, length: R, width: R, num_gates: int, nwell: bool,
    contact_sd_odd: bool=True, contact_sd_even: bool=True, hv: bool=False) -> Layout:
    """
    Layout generation function shared for the LV and HV Nmos and Pmos cells.

    The num_gates+1 source/drain regions are numbered left to right, starting
    at 0. contact_sd_odd / contact_sd_even select which of them get a Cont
    array and a Metal1 strip; the others are left as bare diffusion, which
    connects the adjacent channels in series. Skipping the odd regions of a
    device with an even num_gates thus yields a series chain that is only
    contacted at both ends.

    See also: ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib/ihp/nmos_code.py
    and nmosHV_code.py.
    """
    layers = SG13G2().layers
    cont = VIA_RULES["SG13G2_CONT_ACTIV_M1"]
    patch = cont.size + 2*cont.enc_bottom  # Activ around a single Cont
    l = Layout(ref_layers=layers, cell=cell)
    s = Solver(l)

    # Down to the 5 nm grid like the PCell's GridFix, whose epsilon absorbs
    # float noise in the parameters.
    L = 5 * math.floor(length / R("5n") + R("0.001"))
    W = 5 * math.floor(width / num_gates / R("5n") + R("0.001"))

    l.poly = PathNode()
    l.sd = PathNode()

    activ_ext = None

    def sd_contacted(i):
        return contact_sd_even if i % 2 == 0 else contact_sd_odd

    def add_sd(i):
        nonlocal l, s, x_cur, activ_ext
        if not sd_contacted(i):
            # Bare diffusion: the region is part of l.activ, so no node of
            # its own is generated, only the Metal1 pad and the Activ
            # enlargement (which exists solely for the Cont enclosure) are
            # omitted. The gate pitch is left unchanged, so the surrounding
            # geometry does not depend on which regions are contacted, and
            # devices abutting on the region place it via l.activ.
            x_cur = x_cur + cont.size
            return
        l.sd[i] = LayoutRect(layer=layers.Metal1)
        sd = l.sd[i]
        s.constrain(sd.west == (x_cur, l.activ.cy))
        s.constrain(sd.width == cont.size)
        if W >= patch:
            s.constrain(sd.height == W)
        else:
            s.constrain(sd.height == cont.size + 2*cont.endcap_top)

            activ_ext = l % LayoutRect(layer=layers.Activ)
            s.constrain(activ_ext.center == sd.center)
            s.constrain(activ_ext.size == (patch, patch))
        x_cur = sd.ux

    # Cont to GatPoly spacing (Cnt_f, 110). For W < 300, the 300x300 activ_ext
    # patch around each contact reaches 70 beyond the Cont in x, so the
    # spacing must grow to Cnt_c + Gat_d = 140 to keep GatPoly 70 (Gat.d)
    # away from that patch. Same case split as the foundry PCell
    # (smallw_gatpoly_cont_dist in nmos_code.py/pmos_code.py).
    sd_poly_dist = 110 if W >= patch else 140

    def add_poly(i):
        nonlocal l, s, x_cur
        x_cur += sd_poly_dist
        l.poly[i] = LayoutRect(layer=layers.GatPoly)
        poly = l.poly[i]
        s.constrain(poly.west == (x_cur, l.activ.cy))
        s.constrain(poly.size == (L, l.activ.height + 360))
        s.constrain(poly.ly == 0)
        x_cur = poly.ux + sd_poly_dist

    l.activ = LayoutRect(layer=layers.Activ)
    s.constrain(l.activ.height == W)
    s.constrain(l.activ.lx == 0)
    x_cur = l.activ.lx + cont.enc_bottom

    add_sd(0)
    for i in range(num_gates):
        add_poly(i)
        add_sd(i+1)

    s.constrain(l.activ.ux == x_cur + 70)

    if nwell:
        psd_gate_enc = 400 if hv else 300  # pSD.i1 / pSD.i
        l.psd = LayoutRect(layer=layers.pSD)
        s.constrain(l.psd.center == l.activ.center)
        s.constrain(l.psd.size == l.activ.size + Vec2I(360, 2 * psd_gate_enc))

        if activ_ext is None:
            max_activ = l.activ
        else:
            max_activ = activ_ext
        nwell_enc = 620 if hv else 310  # NW.c1 / NW.c
        l.nwell = LayoutRect(layer=layers.NWell)
        s.constrain(l.nwell.center == l.activ.center)
        s.constrain(l.nwell.ux == l.activ.ux + nwell_enc)
        s.constrain(l.nwell.uy == max_activ.uy + nwell_enc)

    if hv:
        l.tgo = LayoutRect(layer=layers.ThickGateOx)
        if nwell:
            # ThickGateOx covers the whole NWell, as in the PCell.
            s.constrain(l.tgo.rect == l.nwell.rect)
        else:
            # ThickGateOx around Activ (TGO.a) and the gate ends (TGO.c).
            s.constrain(l.tgo.center == l.activ.center)
            s.constrain(l.tgo.size == l.activ.size + Vec2I(2 * 270, 2 * (180 + 340)))

    # l.sd[i].rect/l.m1 are assigned after solve() via makevias, which needs
    # the solved geometry; defer the undefined-attribute check until then.
    s.solve(allow_undefined=True)

    # Cnt.c requires 0.07 um Activ enclosure of Cont, which the two sd
    # variants of add_sd() satisfy differently:
    # - W >= 300: the strip spans the full Activ height, so the enclosure
    #   must be kept free here and bounds the row count.
    # - W < 300: the strip is 260 high, and the enclosure comes from the
    #   300x300 activ_ext patch centered on it. The single centered via is
    #   then enclosed by 70 on all sides regardless of the strip margin.
    # In x the strip is exactly one via wide in both variants, so the Cont
    # sits flush with it (margin 0, which also yields cols=1 on its own) and
    # the Activ enclosure comes from activ/activ_ext.
    margin_y = cont.enc_bottom if W >= patch else 0
    for i in range(num_gates + 1):
        if not sd_contacted(i):
            continue
        contact_array(l, l.sd[i].rect, layers.Cont, cont.size, cont.space, Vec2I(0, margin_y))

    label = ("pmos" if nwell else "nmos") + ("HV" if hv else "")
    # The pmosHV PCell labels its HeatTrans "pmos".
    for i in range(num_gates):
        poly = l.poly[i].rect
        l % LayoutRect(layer=layers.HeatTrans, rect=poly)
        l % LayoutLabel(layer=layers.HeatTrans, pos=poly.center, text="pmos" if nwell else label)
    l % LayoutLabel(layer=layers.TEXT, pos=l.poly[0].rect.center, text=label)
    if nwell:
        # The PCell's bulk pin shape
        l % LayoutRect(layer=layers.Substrate, rect=Rect4I(
            l.activ.rect.ux - 300, max_activ.rect.ly, l.activ.rect.ux, max_activ.rect.ly + 300))

    return l


class Mos(SimLeafCell):
    hv = False
    rf_model = None

    l = Parameter(R)  #: Length
    w = Parameter(R)  #: Width
    m = Parameter(int, default=1)  #: Multiplier, i. e. number of devices with separate Activ areas in parallel)
    ng = Parameter(int, default=1)  #: Number of gate fingers

    #: Contact odd-numbered source/drain regions (Cont + Metal1)
    contact_sd_odd = Parameter(bool, default=True)
    #: Contact even-numbered source/drain regions (Cont + Metal1)
    contact_sd_even = Parameter(bool, default=True)

    def ngspice_save_params(self):
        # PSP103 (OSDI) operating-point outputs:
        return ["gm", "gds", "vth", "vgs", "vds", "ids"]

    def ngspice_internal_device(self):
        # The PDK netlists a model subcircuit around a single PSP103
        # (OSDI) device named N<model_name>; needed to save/read device
        # parameters (see Simulator._param_save_directives).
        return f"n{self.model_name}"

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlister_setup)
        if self.hv:
            netlister.require_netlist_setup(netlister_setup_mos_hv)
        netlister.require_ngspice_setup(ngspice_setup)
        pins = [inst.symbol.d, inst.symbol.g, inst.symbol.s, inst.symbol.b]
        model = self.model_name
        params = {
            'l': self.l,
            'w': self.w,
            'm': self.m,
            'ng': self.ng,
        }
        if self.rf_model:
            if netlister.lvs:
                model = self.rf_model
            else:
                params['rfmode'] = 1
        netlister.add(
            netlister.name_obj(inst, prefix="M" if netlister.lvs else "x"),
            netlister.portmap(inst, pins),
            model,
            *spice_params(params))

@public
class Nmos(Mos):
    model_name = "sg13_lv_nmos"

    # Reuse the generic MOS symbol viewgen (not the class: inheriting from
    # generic_mos.Nmos would also drag in its defaulted l/w parameters).
    symbol = generic_mos.Nmos.symbol

    @viewgen_noctx
    def layout(self) -> Layout:
        if self.m != 1:
            raise ParameterError("m != 1 not supported for layout.")
        return layoutgen_mos(self, self.l, self.w, self.ng, nwell=False,
            contact_sd_odd=self.contact_sd_odd,
            contact_sd_even=self.contact_sd_even)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("1u"), l=R("130n"))]

@public
class Pmos(Mos):
    model_name = "sg13_lv_pmos"

    symbol = generic_mos.Pmos.symbol

    @viewgen_noctx
    def layout(self) -> Layout:
        if self.m != 1:
            raise ParameterError("m != 1 not supported for layout.")
        return layoutgen_mos(self, self.l, self.w, self.ng, nwell=True,
            contact_sd_odd=self.contact_sd_odd,
            contact_sd_even=self.contact_sd_even)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("1u"), l=R("130n"))]

@public
class NmosHv(Mos):
    """High-voltage (3.3 V) NMOS with thick gate oxide."""
    model_name = "sg13_hv_nmos"
    hv = True

    symbol = generic_mos.Nmos.symbol

    @viewgen_noctx
    def layout(self) -> Layout:
        if self.m != 1:
            raise ParameterError("m != 1 not supported for layout.")
        return layoutgen_mos(self, self.l, self.w, self.ng, nwell=False, hv=True,
            contact_sd_odd=self.contact_sd_odd,
            contact_sd_even=self.contact_sd_even)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("0.6u"), l=R("0.45u"))]

@public
class PmosHv(Mos):
    """High-voltage (3.3 V) PMOS with thick gate oxide."""
    model_name = "sg13_hv_pmos"
    hv = True

    symbol = generic_mos.Pmos.symbol

    @viewgen_noctx
    def layout(self) -> Layout:
        if self.m != 1:
            raise ParameterError("m != 1 not supported for layout.")
        return layoutgen_mos(self, self.l, self.w, self.ng, nwell=True, hv=True,
            contact_sd_odd=self.contact_sd_odd,
            contact_sd_even=self.contact_sd_even)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("0.3u"), l=R("0.4u"))]

def layoutgen_rfmos(cell: Cell, nwell: bool, hv: bool) -> Layout:
    """
    Layout generation function shared for the RF Nmos and Pmos cells, as the
    PCell rfmosfet_base_code.py with its default options: one contact row,
    Metal2 on the source/drain rows, gate ring and guard ring.
    """
    if cell.m != 1:
        raise ParameterError("m != 1 not supported for layout.")
    if not (cell.contact_sd_odd and cell.contact_sd_even):
        raise ParameterError("RF MOS layouts contact all source/drain regions.")
    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    ng = cell.ng
    W = 5 * math.floor(cell.w / ng / R("5n") + R("0.001"))  # GridFix as in the PCell
    L = int(cell.l / R("1n"))
    # Space between the gates and at both ends
    dc, ec = (390, 350) if L < 140 and W >= 1000 else (380, 345)
    hact = 2*ec + (ng - 1)*dc + ng*L
    cont, via1 = VIA_RULES["SG13G2_CONT_ACTIV_M1"], VIA_RULES["SG13G2_VIA_M1_M2"]
    via_space = via1.space if W < 1520 else via1.space_dense
    row = 155                    # y of the first source/drain contact line
    dgatx, dgaty = 130, 235      # Activ to gate ring
    wgat = 300                   # gate ring width
    dguard, wguard = 360, 320    # gate ring to guard ring, guard ring width

    l % LayoutRect(layer=layers.Activ, rect=Rect4I(0, 0, W, hact))
    l.poly = PathNode()
    for i in range(ng):
        y = ec + i*(dc + L)
        l.poly[i] = LayoutRect(layer=layers.GatPoly, rect=Rect4I(-dgatx, y, W + dgatx, y + L))
    # Poly bars left and right of the Activ join the fingers, ending 75 inside
    # the Activ's ends (the PCell's u for one contact row).
    for x in (-dgatx - wgat, W + dgatx):
        l % LayoutRect(layer=layers.GatPoly, rect=Rect4I(x, 75, x + wgat, hact - 75))

    # Source/drain rows: metal 280 wide (the PCell's metWidth - 0.02), 50 in from the Activ ends
    l.sd = PathNode()
    for k in range(ng + 1):
        dy = k*(dc + L)
        l.sd[k] = metal_cont(l, layers.Metal1, layers.Cont, 50, row, W - 50, row,
            280, cont.size, 50, cont.space, dy)
        metal_cont(l, layers.Metal2, layers.Via1, 50, row, W - 50, row, 200, via1.size, 50, via_space, dy)
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(W // 2, ec // 2), text="S")
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(W // 2, ec // 2 + dc + L), text="D")

    gate_ring = Rect4I(-dgatx - wgat, -dgaty - wgat, W + dgatx + wgat, hact + dgaty + wgat)
    ring(l, layers.Metal1, gate_ring, Rect4I(-dgatx, -dgaty, W + dgatx, hact + dgaty))
    x_gate = dgatx + wgat // 2
    # Contacts join the poly bars to the gate ring's Metal1, starting 95 in
    # from the bars' ends (the PCell's u + 20), Metal1 200 wide (viaW + 10).
    l.term_g = metal_cont(l, layers.Metal1, layers.Cont, -x_gate, 95, -x_gate, hact - 95,
        200, cont.size, 50, via_space)
    metal_cont(l, layers.Metal1, layers.Cont, W + x_gate, 95, W + x_gate, hact - 95,
        200, cont.size, 50, via_space)
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(-x_gate, hact // 2), text="G")

    xl, yb = gate_ring.lx - dguard - wguard, gate_ring.ly - dguard - wguard
    xr, yt = gate_ring.ux + dguard + wguard, gate_ring.uy + dguard + wguard
    guard_half = wguard // 2
    # The guard ring's contacts start 80 in from the ends of the lower and
    # upper bars, 110 on the side bars.
    l.term_b = metal_cont(l, layers.Metal1, layers.Cont, xl, yb + guard_half, xr, yb + guard_half,
        wguard, cont.size, 80, cont.space)
    metal_cont(l, layers.Metal1, layers.Cont, xl, yt - guard_half, xr, yt - guard_half,
        wguard, cont.size, 80, cont.space)
    for x in (xl + guard_half, xr - guard_half):
        metal_cont(l, layers.Metal1, layers.Cont, x, yb + wguard, x, yt - wguard,
            wguard, cont.size, 110, cont.space)
    ring(l, layers.Activ, Rect4I(xl, yb, xr, yt),
        Rect4I(xl + wguard, yb + wguard, xr - wguard, yt - wguard))
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(W // 2, yb + guard_half), text="TIE")
    name = ("rfpmos" if nwell else "rfnmos") + ("HV" if hv else "")
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(W // 2, yt - guard_half), text=name)

    def around_guard(dist):
        return Rect4I(xl - dist, yb - dist, xr + dist, yt + dist)

    # A PMOS sits in an NWell with pSD over its source and drain. An NMOS's
    # guard ring ties the substrate, so its pSD is a ring over the guard
    # ring. HV devices add ThickGateOx.
    if nwell:
        l % LayoutRect(layer=layers.pSD, rect=Rect4I(xl + 500, yb + 600, xr - 500, yt - 600))
        if hv:
            l % LayoutRect(layer=layers.ThickGateOx, rect=around_guard(310))
        l % LayoutRect(layer=layers.NWell, rect=around_guard(660 if hv else 310))
    else:
        wpsd = 380  # pSD ring width, centered on the guard ring
        psd_over = (wpsd - wguard) // 2
        ring(l, layers.pSD, around_guard(psd_over), around_guard(psd_over - wpsd))
        if hv:
            l % LayoutRect(layer=layers.ThickGateOx, rect=around_guard(psd_over + 350))

    l.sd[0].create_pin(cell.symbol.s)
    l.sd[1].create_pin(cell.symbol.d)
    l.term_g.create_pin(cell.symbol.g)
    l.term_b.create_pin(cell.symbol.b)
    return l

@public
class RfNmos(Nmos):
    """RF NMOS with gate ring and guard ring."""
    rf_model = "rfnmos"

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_rfmos(self, nwell=False, hv=False)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("1u"), l=R("0.72u"))]

@public
class RfPmos(Pmos):
    """RF PMOS with gate ring and guard ring."""
    rf_model = "rfpmos"

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_rfmos(self, nwell=True, hv=False)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("1u"), l=R("0.72u"))]

@public
class RfNmosHv(NmosHv):
    """High-voltage RF NMOS with gate ring and guard ring."""
    rf_model = "rfnmoshv"

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_rfmos(self, nwell=False, hv=True)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("1u"), l=R("0.72u"))]

@public
class RfPmosHv(PmosHv):
    """High-voltage RF PMOS with gate ring and guard ring."""
    rf_model = "rfpmoshv"

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_rfmos(self, nwell=True, hv=True)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("1u"), l=R("0.72u"))]

def layoutgen_tap(cell: Cell, length: R, width: R, nwell: bool, label: str = None):
    """With label ("well" or "sub!"), LVS extracts the tap as a device."""
    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol if label else None)
    s = Solver(l)

    L = int(length/R("1n"))
    W = int(width/R("1n"))

    l.activ = LayoutRect(layer=layers.Activ)
    s.constrain(l.activ.size == (W, L))
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

    # l.m1.rect is assigned after solve() from the via stack, which needs the
    # solved geometry; defer the undefined-attribute check until then.
    s.solve(allow_undefined=True)

    vias_rect = draw_cont_array(l, l.activ.rect)
    # Shrink M1 to via stack, with 50 nm extension north and south:
    l.m1.rect = (vias_rect.lx, vias_rect.ly - 50, vias_rect.ux, vias_rect.uy + 50)

    if label:
        if nwell:
            l.nwell.create_pin(cell.symbol.well)
        else:
            l.substrate = LayoutRect(layer=layers.Substrate, rect=l.activ.rect)
        for layer in (layers.TEXT, layers.NWell if nwell else layers.Substrate):
            l % LayoutLabel(layer=layer, pos=Vec2I(W // 2, 10), text=label)
        l.m1.create_pin(cell.symbol.tie)

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


class Tap1(SimLeafCell):
    """
    Tap devices ntap1 and ptap1: the resistance from ``tie`` into the well or
    substrate. Unlike :class:`Ntap` and :class:`Ptap`, they show up in
    netlists and LVS.
    """
    l = Parameter(R)
    w = Parameter(R)

    def check_size(self):
        if self.w < R("0.78u") or self.l < R("0.78u"):
            raise ParameterError(f"w and l must be at least 0.78u ({self.model_name}_minLW).")

    def resistance(self) -> R:
        """As the PDK's xschem symbol computes it."""
        return 1 / (self.w * self.l / R("9.8e-10") + 2 * (self.w + self.l) / R("9.8e-4"))

    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.tie = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)
        s[self.bulk] = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)

        s % SymbolPoly(vertices=resistor_zigzag())
        s % SymbolPoly(vertices=[Vec2R(1.4, 1), Vec2R(2.6, 1)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlister_setup)
        netlister.require_ngspice_setup(ngspice_setup)

        pins = [inst.symbol.tie, inst.symbol[self.bulk]]
        if netlister.lvs:
            prefix = "R"
            params = {"A": self.w * self.l, "P": 2 * (self.w + self.l)}
        else:
            prefix = "x"
            params = {"R": self.resistance(), "w": self.w, "l": self.l}
        netlister.add(
            netlister.name_obj(inst, prefix=prefix),
            netlister.portmap(inst, pins),
            self.model_name,
            *spice_params(params),
        )

    @classmethod
    def discoverable_instances(cls):
        return [cls(l=R("0.78u"), w=R("0.78u"))]

@public
class Ntap1(Tap1):
    """Tap device from Metal1 into an NWell, pins ``tie`` and ``well``."""
    model_name = "ntap1"
    bulk = "well"

    @viewgen_noctx
    def layout(self) -> Layout:
        self.check_size()
        return layoutgen_tap(self, self.l, self.w, nwell=True, label="well")

@public
class Ptap1(Tap1):
    """Tap device from Metal1 into the substrate, pins ``tie`` and ``sub``."""
    model_name = "ptap1"
    bulk = "sub"

    @viewgen_noctx
    def layout(self) -> Layout:
        self.check_size()
        return layoutgen_tap(self, self.l, self.w, nwell=False, label="sub!")


@dataclass(frozen=True)
class ResistorRules:
    """Per-kind SG13G2 poly resistor limits in nm, as in the foundry PCells."""
    name: str
    minW: int
    minL: int
    minPS: int          #: minimum stripe spacing of bent resistors
    cont_to_body: int   #: terminal contact to body distance
    met_over_cont: int  #: Metal1 enclosure of the terminal contact along the stripe
    # For the resistance label, as the PCell computes it
    rspec: float        #: body sheet resistance in Ohm
    rzspec: float       #: body to contact transition resistance in Ohm um
    lwd: float          #: width delta in um

def eng_string(x: float) -> str:
    """Format x > 0 with three digits and an SI prefix, as eng_string in the PDK PCells."""
    exp3 = 3 * (math.floor(math.log10(x)) // 3)
    mant = x / 10**exp3
    mant = round(mant, 2 - math.floor(math.log10(mant)))
    prefix = "yzafpnum kMGTPEZY"[exp3 // 3 + 8] if exp3 else ""
    return f"{int(mant) if mant == int(mant) else mant}{prefix}"

def layoutgen_resistor(
        cell: Cell,
        rules: ResistorRules,
        *,
        add_res: bool = False,
        add_psd: bool = False,
        add_nsd: bool = False,
        add_salblock: bool = False) -> Layout:
    """
    Generate an SG13G2 poly resistor: straight (b=0) or meandered (b bends,
    b+1 stripes of length l, ps apart, joined at alternating ends). Bent
    Rppd and Rhigh require a larger ps instead of the foundry PCell's
    contact pushing.
    """
    if cell.m != 1:
        raise ParameterError("m != 1 not supported for layout.")
    if cell.b < 0:
        raise ParameterError("b must be non-negative.")

    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    width = int(cell.w / R("1n"))
    length = int(cell.l / R("1n"))
    ps = int(cell.ps / R("1n"))
    bends = cell.b

    kind = rules.name
    max_lw = 1_000_000  # maxW / maxL of the foundry PCells (1 mm)
    if width < rules.minW:
        raise ParameterError(f"w below {kind} minimum width.")
    if length < rules.minL:
        raise ParameterError(f"l below {kind} minimum length.")
    if width > max_lw:
        raise ParameterError(f"w above {kind} maximum width.")
    if length > max_lw:
        raise ParameterError(
            f"l above {kind} maximum length. Use series segments.")
    if bends != 0 and ps < rules.minPS:
        raise ParameterError(f"ps below {kind} minimum spacing.")
    sal_enc = 200  # Sal.c: SalBlock enclosure
    if bends >= 2 and add_salblock:
        # Keep the SalBlock covers legal next to the salicided terminal
        # heads (the foundry PCell would push the contacts out instead).
        ps_floor = sal_enc + 200  # plus Sal.d: SalBlock to Cont spacing
        if ps < ps_floor:
            raise ParameterError(
                f"bent {kind} with b >= 2 needs ps >= {ps_floor} nm "
                "(SalBlock enclosure plus spacing next to the terminal "
                "contacts); set ps on the instance.")

    cont = VIA_RULES["SG13G2_CONT_GATPOLY_M1"]
    cont_size = cont.size             # Cnt.a
    poly_over_cont = cont.enc_bottom  # Cnt.d: GatPoly enclosure of Cont
    contbar_poly_over = 70  # CntB.d: GatPoly enclosure of the contact bar
    contbar_min_len = 340   # CntB.a1: minimum contact bar length
    metal_x_enc = cont.endcap_top  # M1.c1: Metal1 enclosure of Cont
    metal_y_enc = max(metal_x_enc, rules.met_over_cont)
    cont_to_body = rules.cont_to_body
    head_len = cont_to_body + cont_size + poly_over_cont

    if width - 2 * contbar_poly_over < contbar_min_len:
        raise ParameterError("Width too small for resistor terminal contact bars.")

    def make_terminal(x0, base_y, up):
        """
        Insert a poly head with contact bar at the body edge (x0, base_y),
        growing in +y if up, else in -y. Returns the head and the Metal1
        terminal, for the caller to name.
        """
        # Drawn with the body edge at y=0 and the head growing in +y, then
        # placed at (x0, base_y), mirrored in y unless up.
        place = TD4I(transl=Vec2I(x0, base_y), d4=D4.R0 if up else D4.MX)
        head_rect = place * Rect4I(0, 0, width, head_len)
        cont_rect = place * Rect4I(
            contbar_poly_over,
            cont_to_body,
            width - contbar_poly_over,
            cont_to_body + cont_size,
        )
        term_rect = Rect4I(
            cont_rect.lx - metal_x_enc,
            cont_rect.ly - metal_y_enc,
            cont_rect.ux + metal_x_enc,
            cont_rect.uy + metal_y_enc,
        )
        l % LayoutRect(layer=layers.Cont, rect=cont_rect)
        head = l % LayoutRect(layer=layers.GatPoly, rect=head_rect)
        term = l % LayoutRect(layer=layers.Metal1, rect=term_rect)
        return head, term

    stripes = bends + 1
    pitch = width + ps
    # LVS measures a bent body as its shortest port-adjacent edge plus w,
    # so each stripe is drawn l - w long to restore the l parameter.
    stripe_len = length if bends == 0 else length - width
    if bends and stripe_len < rules.minL:
        raise ParameterError(
            f"bent {kind} stripes are drawn l - w long; l = {length} nm "
            f"with w = {width} nm leaves less than {kind} minimum length.")

    # Connector j joins stripes j and j+1, at the top for even j, at the
    # bottom for odd j. n sits below stripe 0, p at the last free end.
    body_rects = [
        Rect4I(i * pitch, 0, i * pitch + width, stripe_len)
        for i in range(stripes)
    ]
    bend_rects = [
        Rect4I(j * pitch, stripe_len, (j + 1) * pitch + width, stripe_len + width)
        if j % 2 == 0 else
        Rect4I(j * pitch, -width, (j + 1) * pitch + width, 0)
        for j in range(bends)
    ]

    if bends == 0:
        l.poly_body = LayoutRect(layer=layers.PolyRes, rect=body_rects[0])
        if add_res:
            l.res = LayoutRect(layer=layers.RES, rect=body_rects[0])
    else:
        l.poly_body = PathNode()
        for i, rect in enumerate(body_rects):
            l.poly_body[i] = LayoutRect(layer=layers.PolyRes, rect=rect)
        l.poly_bend = PathNode()
        for j, rect in enumerate(bend_rects):
            l.poly_bend[j] = LayoutRect(layer=layers.PolyRes, rect=rect)
        if add_res:
            # RES must match the body exactly (rsil core = PolyRes AND
            # RES). Covering the heads would grow the extracted body.
            l.res = PathNode()
            for i, rect in enumerate(body_rects + bend_rects):
                l.res[i] = LayoutRect(layer=layers.RES, rect=rect)

    l.poly_head_n, l.term_n = make_terminal(0, 0, up=False)
    if stripes % 2 == 1:
        l.poly_head_p, l.term_p = make_terminal((stripes - 1) * pitch, stripe_len, up=True)
    else:
        l.poly_head_p, l.term_p = make_terminal((stripes - 1) * pitch, 0, up=False)

    body_x_lo = 0
    body_y_lo = min([0] + [r.ly for r in bend_rects])
    body_x_hi = (stripes - 1) * pitch + width
    body_y_hi = max([stripe_len] + [r.uy for r in bend_rects])

    total_x_lo = body_x_lo
    total_x_hi = body_x_hi
    total_y_lo = min(body_y_lo, l.poly_head_n.ly, l.poly_head_p.ly)
    total_y_hi = max(body_y_hi, l.poly_head_n.uy, l.poly_head_p.uy)

    if add_psd or add_nsd:
        sd_enc = 180  # Rppd.b / Rhi.c: pSD / nSD enclosure of the resistor

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

        # SalBlock defines the resistor core, so it covers stripes and bend
        # connectors but stays flush where a terminal head attaches (keeps
        # the spacing to the terminal contact).
        sal_rects = [Rect4I(body_x_lo - sal_enc, 0, body_x_hi + sal_enc, stripe_len)]
        if bends:
            top_bends = [r for r in bend_rects if r.ly == stripe_len]
            bot_bends = [r for r in bend_rects if r.uy == 0]
            sal_rects.append(Rect4I(
                min(r.lx for r in top_bends) - sal_enc, stripe_len,
                max(r.ux for r in top_bends) + sal_enc, stripe_len + width + sal_enc))
            if bot_bends:
                sal_rects.append(Rect4I(
                    min(r.lx for r in bot_bends) - sal_enc, -width - sal_enc,
                    max(r.ux for r in bot_bends) + sal_enc, 0))
        if bends == 0:
            l.salblock = LayoutRect(layer=layers.SalBlock, rect=sal_rects[0])
        else:
            l.salblock = PathNode()
            for i, rect in enumerate(sal_rects):
                l.salblock[i] = LayoutRect(layer=layers.SalBlock, rect=rect)
        l.extblock = PathNode()
        for i, rect in enumerate([(l.psd if add_psd else l.nsd).rect] + sal_rects):
            l.extblock[i] = LayoutRect(layer=layers.EXTBlock, rect=rect)
    else:
        ext_enc = 180  # Rsil.e: EXTBlock enclosure
        l.extblock = LayoutRect(
            layer=layers.EXTBlock,
            rect=(total_x_lo - ext_enc, total_y_lo - ext_enc, total_x_hi + ext_enc, total_y_hi + ext_enc),
        )

    for rect in body_rects + bend_rects:
        l % LayoutRect(layer=layers.HeatRes, rect=rect)
        l % LayoutLabel(layer=layers.HeatRes, pos=rect.center, text=kind)
    # Resistance label, computed as in the PCell
    kappa = 1.85  # the same for all resistors
    w_um = width / 1000
    weff = w_um + rules.lwd
    r = (length / 1000 / weff * (bends + 1) * rules.rspec
        + (2 / kappa * weff + ps / 1000) * bends / weff * rules.rspec
        + 2 / w_um * rules.rzspec)
    r_text = eng_string(r) if kind == "rsil" else f"{r:.3f}"
    l % LayoutLabel(layer=layers.TEXT, pos=body_rects[0].center, text=f"{kind} r={r_text}")

    l.term_n.create_pin(cell.symbol.n)
    l.term_p.create_pin(cell.symbol.p)

    return l


def layoutgen_cmim(cell: Cell) -> Layout:
    """Generate the fixed SG13G2 MiM capacitor layout."""
    if cell.m != 1:
        raise ParameterError("m != 1 not supported for layout.")

    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    width = int(cell.w / R("1n"))
    length = int(cell.l / R("1n"))
    min_lw = 1140       # cmim_minLW of the foundry PCell
    max_lw = 1_000_000  # cmim_maxLW of the foundry PCell (1 mm)
    if width < min_lw or length < min_lw:
        raise ParameterError("w and l must be at least cmim_minLW.")
    if width > max_lw or length > max_lw:
        raise ParameterError("w and l must be at most cmim_maxLW.")

    mim_c = 600                 # Mim.c: Metal5 enclosure of MIM
    mim_d = 360                 # Mim.d: MIM enclosure of TopVia1
    tv1 = VIA_RULES["SG13G2_VIA_M5_TM1"]
    tv1_size = tv1.size                # TV1.a
    tv1_space = tv1_size + tv1.space   # TV1.a + TV1.b (spacing), pitch of the via array
    tv1_enc = tv1.enc_top              # TV1.d: TopMetal1 enclosure of TopVia1

    # The TopMetal1 plate (via array plus enclosure) must meet TM1.a. At
    # cmim_minLW only one via fits and the plate is too narrow.
    tm1_min = tv1.min_top  # TM1.a
    for side, name in ((width, "w"), (length, "l")):
        if cmim_plate_span(side, mim_d, tv1_size, tv1_space, tv1_enc) < tm1_min:
            needed = cmim_min_side_for_tm1(mim_d, tv1_size, tv1_space, tv1_enc, tm1_min, min_lw, max_lw)
            raise ParameterError(
                f"{name} = {side} nm gives a TopMetal1 plate narrower than "
                f"TM1.a ({tm1_min} nm). Cmim needs w and l >= {needed} nm.")

    l.mim = LayoutRect(layer=layers.MIM, rect=(0, 0, width, length))
    l.term_n = LayoutRect(
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
    l.term_p = LayoutRect(
        layer=layers.TopMetal1,
        rect=(
            via_bbox.lx - tv1_enc,
            via_bbox.ly - tv1_enc,
            via_bbox.ux + tv1_enc,
            via_bbox.uy + tv1_enc,
        ),
    )

    l.term_n.create_pin(cell.symbol.n)
    l.term_p.create_pin(cell.symbol.p)

    return l


def cmim_plate_span(side: int, mim_d: int, tv1_size: int, tv1_gap: int,
                     tv1_enc: int) -> int:
    """TopMetal1 plate width along one side of a Cmim: the TopVia1 array
    (same arithmetic as makevias) plus the TV1.d enclosure on both ends."""
    count = (side - 2 * mim_d + tv1_gap) // (tv1_size + tv1_gap)
    if count < 1:
        return 0
    return count * tv1_size + (count - 1) * tv1_gap + 2 * tv1_enc


def cmim_min_side_for_tm1(mim_d: int, tv1_size: int, tv1_gap: int,
        tv1_enc: int, tm1_min: int, min_lw: int, max_lw: int) -> int:
    """Smallest Cmim side (10 nm steps) whose top plate meets TM1.a."""
    side = min_lw
    while cmim_plate_span(side, mim_d, tv1_size, tv1_gap, tv1_enc) < tm1_min:
        side += 10
        if side > max_lw:
            break
    return side


def resistor_zigzag() -> list[Vec2R]:
    """Resistor line of a 4 x 4 symbol, from pin (2, 0) to pin (2, 4)."""
    zigzag_height = R(2)
    zigzag_width_half = R(0.625)
    zigzag_start = (R(4) - zigzag_height) / R(2)
    return [
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
    ]


class Res(SimLeafCell):
    """
    Shared base class for SG13G2 resistors.

    Besides the resistor terminals ``p`` and ``n``, the symbol has a third
    pin ``bn`` connecting the device's bulk/substrate node. ``bn`` is part
    of the LVS comparison and requires care in hierarchical designs; see
    :ref:`ihp130_substrate_lvs`.

    ``b`` bends fold the body into ``b + 1`` stripes of length ``l`` each,
    ``ps`` apart, joined at alternating ends, so a large resistance becomes
    a compact meander. With three or more stripes, Rppd and Rhigh need
    ``ps`` >= 400 nm on SG13G2.
    """
    l = Parameter(R)
    w = Parameter(R)
    b = Parameter(int, default=0)
    ps = Parameter(R, default=R("0.18u"))
    m = Parameter(int, default=1)

    def ngspice_current_pins(self):
        return {"i": "p"}

    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.n = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)
        s.bn = Pin(pos=Vec2R(4, 2), pintype=PinType.In, align=East)

        s % SymbolPoly(vertices=resistor_zigzag())
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
            pins = [inst.symbol.p, inst.symbol.n, inst.symbol.bn]
            prefix = "R"
        else:
            pins = [inst.symbol.p, inst.symbol.n, inst.symbol.bn]
            prefix = "x"
        netlister.add(
            netlister.name_obj(inst, prefix=prefix),
            netlister.portmap(inst, pins),
            self.model_name,
            *spice_params(params),
        )


@public
class Rsil(Res):
    """
    Salicided polysilicon resistor (low sheet resistance). For the
    substrate pin ``bn`` and its LVS handling, see
    :ref:`ihp130_substrate_lvs`.
    """
    model_name = "rsil"

    @viewgen_noctx
    def layout(self) -> Layout:
        rules = ResistorRules(
            name="rsil",
            minW=500,
            minL=500,
            minPS=180,
            cont_to_body=120,
            met_over_cont=30,
            rspec=7.0,
            rzspec=4.5,
            lwd=0.01,
        )
        return layoutgen_resistor(self, rules, add_res=True)

    @classmethod
    def discoverable_instances(cls):
        return [cls(l=R("0.50u"), w=R("0.50u"))]


@public
class Rppd(Res):
    """
    Unsalicided p+ polysilicon resistor (medium sheet resistance). For the
    substrate pin ``bn`` and its LVS handling, see
    :ref:`ihp130_substrate_lvs`.
    """
    model_name = "rppd"

    @viewgen_noctx
    def layout(self) -> Layout:
        rules = ResistorRules(
            name="rppd",
            minW=500,
            minL=500,
            minPS=180,
            cont_to_body=200,
            met_over_cont=70,
            rspec=260.0,
            rzspec=35.0,
            lwd=0.006,
        )
        return layoutgen_resistor(self, rules, add_psd=True, add_salblock=True)

    @classmethod
    def discoverable_instances(cls):
        return [cls(l=R("0.50u"), w=R("0.50u"))]


@public
class Rhigh(Res):
    """
    High-resistive polysilicon resistor (high sheet resistance). For the
    substrate pin ``bn`` and its LVS handling, see
    :ref:`ihp130_substrate_lvs`.
    """
    model_name = "rhigh"

    @viewgen_noctx
    def layout(self) -> Layout:
        rules = ResistorRules(
            name="rhigh",
            minW=500,
            minL=960,
            minPS=180,
            cont_to_body=200,
            met_over_cont=30,
            rspec=1360.0,
            rzspec=80.0,
            lwd=-0.04,
        )
        return layoutgen_resistor(self, rules, add_psd=True, add_nsd=True, add_salblock=True)

    @classmethod
    def discoverable_instances(cls):
        return [cls(l=R("0.96u"), w=R("0.50u"))]


@public
class Cmim(SimLeafCell):
    """Fixed SG13G2 MIM capacitor."""
    l = Parameter(R)
    w = Parameter(R)
    m = Parameter(int, default=1)
    ic = Parameter(R, optional=True)

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
        netlister.require_netlist_setup(netlister_setup)
        netlister.require_ngspice_setup(ngspice_setup)

        pins = [inst.symbol.p, inst.symbol.n]
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

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_cmim(self)

    @classmethod
    def discoverable_instances(cls):
        return [cls(l=R("6.99u"), w=R("6.99u"))]


def layoutgen_rfcmim(cell: Cell) -> Layout:
    """Generate the SG13G2 RF MiM capacitor layout, as the PCell rfcmim_code.py."""
    if not (R("7u") <= cell.w <= R("1m") and R("7u") <= cell.l <= R("1m")):
        raise ParameterError("w and l must be within rfcmim_minLW and rfcmim_maxLW.")
    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    lu = 5 * (int(cell.l / R("1n")) // 5)
    wu = 5 * (int(cell.w / R("1n")) // 5)
    wf = 5 * (int(cell.wfeed / R("1n")) // 5)
    feed = 5 * ((wu - wf) // 10)       # lower edge of the centered feeds
    mim_c = 600                        # Mim.c: Metal5 enclosure of MIM
    mim_d = 360                        # Mim.d: MIM enclosure of Vmim
    tv1 = VIA_RULES["SG13G2_VIA_M5_TM1"]
    cont = VIA_RULES["SG13G2_CONT_ACTIV_M1"]
    ring_in, ring_out = 3600, 5600     # inner and outer edge of the guard ring
    ring_mid = (ring_in + ring_out) // 2

    l.mim = LayoutRect(layer=layers.MIM, rect=Rect4I(0, 0, lu, wu))
    contact_array(l, l.mim.rect, layers.Vmim, tv1.size, tv1.space,
        Vec2I(mim_d + tv1.enc_top, mim_d + tv1.enc_top))
    l % LayoutRect(layer=layers.TopMetal1, rect=Rect4I(mim_d, mim_d, lu - mim_d, wu - mim_d))
    l % LayoutRect(layer=layers.Metal5, rect=Rect4I(-mim_c, -mim_c, lu + mim_c, wu + mim_c))
    l % LayoutRect(layer=layers.PWell.block, rect=Rect4I(-3000, -3000, lu + 3000, wu + 3000))
    l.term_p = LayoutRect(layer=layers.TopMetal1, rect=Rect4I(-ring_out, feed, mim_d, feed + wf))
    l.term_n = LayoutRect(layer=layers.Metal5,
        rect=Rect4I(lu + mim_c, feed, lu + ring_out, feed + wf))
    for layer in (layers.Activ, layers.Metal1, layers.Metal2, layers.Metal3, layers.Metal4,
        layers.Metal5, layers.TopMetal1):
        l % LayoutRect(layer=layer.noqrc,
            rect=Rect4I(-ring_out, -ring_out, lu + ring_out, wu + ring_out))

    # Guard ring, open where the Metal5 feed leaves on the right
    # pSD 30 over the Activ ring on both sides (the PCell's 3.57 and 5.63)
    ring(l, layers.pSD,
        Rect4I(-ring_out - 30, -ring_out - 30, lu + ring_out + 30, wu + ring_out + 30),
        Rect4I(-ring_in + 30, -ring_in + 30, lu + ring_in - 30, wu + ring_in - 30))
    l.term_bn = PathNode()
    for i, rect in enumerate((
        Rect4I(-ring_out, -ring_out, lu + ring_out, -ring_in),
        Rect4I(-ring_out, wu + ring_in, lu + ring_out, wu + ring_out),
        Rect4I(-ring_out, -ring_in, -ring_in, wu + ring_in),
        Rect4I(lu + ring_in, -ring_in, lu + ring_out, feed),
        Rect4I(lu + ring_in, feed + wf, lu + ring_out, wu + ring_in))):
        l % LayoutRect(layer=layers.Activ, rect=rect)
        l.term_bn[i] = LayoutRect(layer=layers.Metal1, rect=rect)
        contact_array(l, rect, layers.Cont, cont.size, cont.space, Vec2I(360, 360))

    l_um, w_um = float(cell.l / R("1u")) + 0.01, float(cell.w / R("1u")) + 0.01
    c = l_um * w_um * 1.5e-15 + 2 * (l_um + w_um) * 4e-17  # for the label, as in the PCell
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(-ring_mid, feed + wf // 2), text="PLUS")
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(lu + ring_mid, feed + wf // 2), text="MINUS")
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(lu // 2, -ring_mid), text="TIE")
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(lu // 2, wu + 2000), text="rfcmim")
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(lu // 2, -2000), text=f"C={eng_string(c)}")

    l.term_p.create_pin(cell.symbol.p)
    l.term_n.create_pin(cell.symbol.n)
    l.term_bn[0].create_pin(cell.symbol.bn)
    return l

@public
class Rfcmim(SimLeafCell):
    """
    RF MiM capacitor: plate ``p`` fed by TopMetal1, plate ``n`` fed by
    Metal5, in a guard ring on the substrate ``bn``.
    """
    w = Parameter(R)
    l = Parameter(R)
    wfeed = Parameter(R)  #: Feed width

    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)
        s.n = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.bn = Pin(pos=Vec2R(0, 2), pintype=PinType.Inout, align=West)

        s % SymbolPoly(vertices=[Vec2R(1.25, 1.8), Vec2R(2.75, 1.8)])
        s % SymbolPoly(vertices=[Vec2R(1.25, 2.2), Vec2R(2.75, 2.2)])
        s % SymbolPoly(vertices=[Vec2R(2, 2.2), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(2, 1.8), Vec2R(2, 0)])
        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1, 2)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlister_setup)
        netlister.require_ngspice_setup(ngspice_setup)

        netlister.add(
            netlister.name_obj(inst, prefix="C" if netlister.lvs else "x"),
            netlister.portmap(inst, [inst.symbol.p, inst.symbol.n, inst.symbol.bn]),
            "rfcmim" if netlister.lvs else "cap_rfcmim",
            *spice_params({"w": self.w, "l": self.l, "wfeed": self.wfeed}),
        )

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_rfcmim(self)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("10u"), l=R("10u"), wfeed=R("5u"))]

def layoutgen_svaricap(cell: Cell) -> Layout:
    """
    Generate the SG13G2 HV varicap layout, as the PCell SVaricap_code.py: nx
    pairs of gate fingers in one NWell, the g2 fingers hanging from a gate
    rail above them, the g1 fingers from a rail below. The NWell contacts
    are a column left of the fingers.
    """
    if cell.w not in (R("3.74u"), R("9.74u")) or cell.l not in (R("0.3u"), R("0.8u")):
        raise ParameterError("w must be 3.74u or 9.74u, l 0.3u or 0.8u.")
    if not 1 <= cell.nx <= 10:
        raise ParameterError("nx must be 1 to 10.")
    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    W = int(cell.w / R("1n"))
    L = int(cell.l / R("1n"))
    nx = cell.nx
    gate_s = 250                 # space between the fingers
    rail = 500                   # height of the gate rails
    x1, y1 = 730, 390 + gate_s   # lower left corner of the first finger
    step = 2 * (gate_s + L)      # a g2 and a g1 finger
    xr = x1 - gate_s + nx*step   # right end of the rails
    yb, yt = y1 - gate_s - rail, y1 + W + rail  # outer edges of the rails
    # How far the Activ, NWell and nBuLay edges lie inside the rails' outer
    # edges (gate_o_*), and beyond the rails' right end (*_o_gate).
    gate_o_activ = 350
    gate_o_nwell, gate_o_nbulay = (110, 350) if W == 3740 else (-145, 100)
    nwell_o_gate, nbulay_o_gate = 570, 330
    cont = VIA_RULES["SG13G2_CONT_GATPOLY_M1"]
    cont_w, cont_s = cont.size, cont.space
    met_w = cont_w + 2*cont.endcap_top
    # Each finger's Metal1 runs into its rail up to the rail's contact line,
    # which lies on the rail's middle.
    to_line = rail // 2 - met_w // 2

    for i in range(nx):
        x = x1 + i*step
        xg = x + step - gate_s
        l % LayoutRect(layer=layers.GatPoly, rect=Rect4I(x, y1, x + L, y1 + W))
        l % LayoutRect(layer=layers.GatPoly, rect=Rect4I(xg - L, y1 - gate_s, xg, y1 - gate_s + W))
        # Contacts along each finger, ending 80 before its free end
        xc = x + L // 2
        metal_cont(l, layers.Metal1, layers.Cont, xc, y1 + 80, xc, y1 + W - 10,
            met_w, cont_w, 50, cont_s)
        l % LayoutRect(layer=layers.Metal1,
            rect=Rect4I(xc - met_w // 2, y1 + W - 10, xc + met_w // 2, y1 + W + to_line))
        xc = xg - L // 2
        metal_cont(l, layers.Metal1, layers.Cont, xc, y1 - gate_s + 10, xc, y1 - gate_s + W - 80,
            met_w, cont_w, 50, cont_s)
        l % LayoutRect(layer=layers.Metal1,
            rect=Rect4I(xc - met_w // 2, y1 - gate_s - to_line, xc + met_w // 2, y1 - gate_s + 10))

    # Activ islands with pSD at the outer edge of each rail: one per 10 um of
    # finger span, centered on the fingers, one less if the outer ones would
    # reach over the first finger.
    tap_w, tap_h, psd_over = 240, 760, 100
    psd_step = 10000
    span = 2*nx*L + (2*nx - 1)*gate_s
    nr_psd = (span - tap_w) // psd_step + 1
    if nr_psd > 1:
        x_psd = (span - (nr_psd - 1)*psd_step) // 2 + x1 - tap_w // 2
        if x_psd < x1 + L + 5:
            nr_psd -= 1
            x_psd = (span - (nr_psd - 1)*psd_step) // 2 + x1 - tap_w // 2
    else:
        x_psd = x1 + (span - tap_w) // 2
    for k in range(nr_psd):
        x = x_psd + k*psd_step
        l % LayoutRect(layer=layers.Activ,
            rect=Rect4I(x, yt - gate_o_activ, x + tap_w, yt - gate_o_activ + tap_h))
        l % LayoutRect(layer=layers.Activ,
            rect=Rect4I(x, yb + gate_o_activ - tap_h, x + tap_w, yb + gate_o_activ))
        l % LayoutRect(layer=layers.pSD, rect=Rect4I(x - psd_over, yt + psd_over - gate_o_activ,
            x + tap_w + psd_over, yt + psd_over - gate_o_activ + tap_h))
        l % LayoutRect(layer=layers.pSD, rect=Rect4I(x - psd_over, yb - psd_over + gate_o_activ - tap_h,
            x + tap_w + psd_over, yb - psd_over + gate_o_activ))

    l % LayoutRect(layer=layers.GatPoly, rect=Rect4I(x1, y1 + W, xr, yt))
    l % LayoutRect(layer=layers.GatPoly, rect=Rect4I(x1, yb, xr, y1 - gate_s))
    l.term_g1 = metal_cont(l, layers.Metal1, layers.Cont, x1 + 20, yb + rail // 2, xr - 20, yb + rail // 2,
        met_w, cont_w, 50, cont_s)
    l.term_g2 = metal_cont(l, layers.Metal1, layers.Cont, x1 + 20, yt - rail // 2, xr - 20, yt - rail // 2,
        met_w, cont_w, 50, cont_s)
    # The NWell contacts: a column 340 left of the fingers, at their middle
    yc = y1 + (W - gate_s) // 2
    l.term_nw = metal_cont(l, layers.Metal1, layers.Cont, x1 - 340, yc - 480, x1 - 340, yc + 480,
        cont_w + 2*20, cont_w, 50, cont_s)

    # Activ and nBuLay start 490 left of the fingers, the NWell at the
    # cell's origin.
    l % LayoutRect(layer=layers.Activ,
        rect=Rect4I(x1 - 490, yb + gate_o_activ, xr + nbulay_o_gate, yt - gate_o_activ))
    l % LayoutRect(layer=layers.NWell,
        rect=Rect4I(x1 - 730, yb + gate_o_nwell, xr + nwell_o_gate, yt - gate_o_nwell))
    l % LayoutRect(layer=layers.nBuLay,
        rect=Rect4I(x1 - 490, yb + gate_o_nbulay, xr + nbulay_o_gate, yt - gate_o_nbulay))
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(x1 - 490, yb + gate_o_nbulay + gate_o_activ),
        text="SVaricap")

    l.term_g1.create_pin(cell.symbol.g1)
    l.term_g2.create_pin(cell.symbol.g2)
    l.term_nw.create_pin(cell.symbol.nw)
    return l

@public
class Svaricap(SimLeafCell):
    """
    HV MOS varicap: gates ``g1`` and ``g2`` against their common NWell
    ``nw``, ``bn`` the substrate.
    """
    w = Parameter(R)  #: Width, 3.74u or 9.74u
    l = Parameter(R)  #: Length, 0.3u or 0.8u
    nx = Parameter(int, default=1)  #: Number of columns (Nx)

    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        # Same places as in the PDK symbol. Its pin names don't match the
        # drawing, xschem netlists the pins by their order.
        s.g1 = Pin(pos=Vec2R(0, 2), pintype=PinType.Inout, align=West)
        s.g2 = Pin(pos=Vec2R(4, 2), pintype=PinType.Inout, align=East)
        s.nw = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)
        s.bn = Pin(pos=Vec2R(2, 0), pintype=PinType.In, align=South)

        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1.2, 2)])
        s % SymbolPoly(vertices=[Vec2R(4, 2), Vec2R(2.8, 2)])
        for x in (1.2, 1.6, 2.4, 2.8):
            s % SymbolPoly(vertices=[Vec2R(x, 1.4), Vec2R(x, 2.6)])
        s % SymbolPoly(vertices=[Vec2R(1.6, 2), Vec2R(2.4, 2)])
        s % SymbolPoly(vertices=[Vec2R(2, 2), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(2, 0), Vec2R(2, 0.8)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlister_setup)
        netlister.require_netlist_setup(netlister_setup_mos_hv)
        netlister.require_ngspice_setup(ngspice_setup)

        netlister.add(
            netlister.name_obj(inst, prefix="C" if netlister.lvs else "x"),
            netlister.portmap(inst,
                [inst.symbol.g1, inst.symbol.nw, inst.symbol.g2, inst.symbol.bn]),
            "sg13_hv_svaricap",
            *spice_params({"w": self.w, "l": self.l, "Nx": self.nx}),
        )

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_svaricap(self)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("3.74u"), l=R("0.3u"))]

@public
class Cpara(SimLeafCell):
    """Parasitic capacitance for simulation only: no LVS device, no layout."""
    c = Parameter(R)  #: Capacitance (C)

    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)
        s.n = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)

        s % SymbolPoly(vertices=[Vec2R(1.25, 2.2), Vec2R(2.75, 2.2)])
        s % SymbolArc(pos=Vec2R(2, 0.4), radius=R(1.4), angle_start=R(0.17), angle_end=R(0.33))
        s % SymbolPoly(vertices=[Vec2R(2, 2.2), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(2, 1.8), Vec2R(2, 0)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        if netlister.lvs:
            return
        netlister.require_netlist_setup(netlister_setup)
        netlister.require_ngspice_setup(ngspice_setup)

        netlister.add(
            netlister.name_obj(inst, prefix="x"),
            netlister.portmap(inst, [inst.symbol.p, inst.symbol.n]),
            "cparasitic",
            *spice_params({"C": self.c}),
        )

    @classmethod
    def discoverable_instances(cls):
        return [cls(c=R("10f"))]

def layoutgen_bondpad(cell: Cell) -> Layout:
    """
    Generate the SG13G2 bond pad layout, as the PCell bondpad_code.py with
    TopMetal2 on top: an octagon (shape=0) or a square (shape=1), with stack
    metal rings and vias from Metal<bottom_metal> up, with fill full plates
    instead of the rings, with add_filler_ex fill blocking 10 um around.
    """
    if cell.shape not in (0, 1) or cell.padtype != 0:
        raise ParameterError("Layout supports the octagon and square bondpad (shape=0 or 1, padtype=0) only.")
    if not 1 <= cell.bottom_metal <= 6:
        raise ParameterError("bottom_metal must be 1 to 6 (TopMetal1).")
    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    def to_grid(v):  # tog in the PCell
        return 5 * math.floor(v / 5 + 0.001)

    def octagon(rx, ry, off):
        return [Vec2I(-rx, -ry + off), Vec2I(-rx, ry - off), Vec2I(-rx + off, ry),
            Vec2I(rx - off, ry), Vec2I(rx, ry - off), Vec2I(rx, -ry + off),
            Vec2I(rx - off, -ry), Vec2I(-rx + off, -ry)]

    def corner(r):
        return to_grid(r * (1 - 1 / (math.sqrt(2) + 1)))

    met_over = 1400       # Pad.gR
    met_over_pass = 2100  # Pas.c
    rad = to_grid(int(cell.size / R("1n")) / 2)
    stripe_width = 2 * to_grid(met_over + math.sqrt(2) * VIA_RULES["SG13G2_VIA_TM1_TM2"].size * 0.5)
    # The via rules from Metal1 up, the stack has those from bottom_metal.
    rules = [VIA_RULES[k] for k in ("SG13G2_VIA_M1_M2", "SG13G2_VIA_M2_M3", "SG13G2_VIA_M3_M4",
        "SG13G2_VIA_M4_M5", "SG13G2_VIA_M5_TM1", "SG13G2_VIA_TM1_TM2")]
    stack = rules[cell.bottom_metal - 1:] if cell.stack else []
    nofill_layers = (layers.Activ, layers.GatPoly, layers.Metal1, layers.Metal2, layers.Metal3,
        layers.Metal4, layers.Metal5, layers.TopMetal1, layers.TopMetal2) if cell.add_filler_ex else ()
    nofill_rad = rad + 10000

    if cell.shape == 1:
        box = Rect4I(-rad, -rad, rad, rad)
        for layer in nofill_layers:
            l % LayoutRect(layer=layer.nofill, rect=Rect4I(-nofill_rad, -nofill_rad, nofill_rad, nofill_rad))
        l.term_pad = LayoutRect(layer=layers.TopMetal2, rect=box)
        l % LayoutRect(layer=layers.dfpad, rect=box)
        half = rad - met_over_pass
        l % LayoutRect(layer=layers.Passiv, rect=Rect4I(-half, -half, half, half))
        half = rad - stripe_width
        ring_vertices = [Vec2I(-rad, -rad), Vec2I(-rad, rad), Vec2I(rad, rad), Vec2I(rad, -rad),
            Vec2I(-rad, -rad), Vec2I(-half, -half), Vec2I(half, -half), Vec2I(half, half),
            Vec2I(-half, half), Vec2I(-half, -half)]
        for metal, rule in enumerate(stack, cell.bottom_metal):
            via, vs, vd = getattr(layers, rule.cut), rule.size, rule.space
            if cell.fill:
                l % LayoutRect(layer=getattr(layers, rule.bottom), rect=box)
                # Via field inside the ring, shifted on every other level
                shift = 0 if metal % 2 else 2 * vd
                half = rad - stripe_width - 4000
                contact_array(l, Rect4I(-half, -half, half, half), via, vs, 4 * vd, Vec2I(shift, shift))
            else:
                l % LayoutPoly(layer=getattr(layers, rule.bottom), vertices=ring_vertices)
            margin = to_grid((stripe_width - vs) / 2)
            contact_array(l, Rect4I(-rad, rad - stripe_width, rad, rad), via, vs, vd, Vec2I(margin, margin))
            contact_array(l, Rect4I(-rad, -rad, rad, -rad + stripe_width), via, vs, vd, Vec2I(margin, margin))
            contact_array(l, Rect4I(-rad, -rad, -rad + stripe_width, rad), via, vs, vd,
                Vec2I(margin, margin + vs + vd + 10))
            contact_array(l, Rect4I(rad - stripe_width, -rad, rad, rad), via, vs, vd,
                Vec2I(margin, margin + vs + vd + 10))
        l.term_pad.create_pin(cell.symbol.pad)
        return l

    offset = corner(rad)
    for layer in nofill_layers:
        l % LayoutPoly(layer=layer.nofill, vertices=octagon(nofill_rad, nofill_rad, corner(nofill_rad)))
    l % LayoutPoly(layer=layers.TopMetal2, vertices=octagon(rad, rad + 5, offset))
    l.term_pad = LayoutRect(layer=layers.TopMetal2,
        rect=Rect4I(-rad + offset, -rad + offset, rad - offset, rad - offset))
    l % LayoutPoly(layer=layers.dfpad, vertices=octagon(rad, rad + 5, offset))
    inner_rad = rad - met_over_pass
    l % LayoutPoly(layer=layers.Passiv, vertices=octagon(inner_rad, inner_rad, corner(inner_rad)))

    # Metal ring as one polygon: the outer octagon, then the inner one
    # backwards.
    inner_rad = rad - stripe_width
    outer = octagon(rad, rad + 5, offset)
    inner = octagon(inner_rad, inner_rad, corner(inner_rad))
    ring_vertices = [Vec2I(-rad, 0), *outer[1:], outer[0], Vec2I(-rad, 0),
        Vec2I(-inner_rad, 0), inner[0], *inner[:0:-1], Vec2I(-inner_rad, 0)]
    if stack and cell.fill:
        # The PCell's via field inside the plates does not come out, its
        # mask stays on Activ (with the field's squares inside it).
        l % LayoutPoly(layer=layers.Activ, vertices=inner)
    for rule in stack:
        via, vs, vd = getattr(layers, rule.cut), rule.size, rule.space
        l % LayoutPoly(layer=getattr(layers, rule.bottom), vertices=outer if cell.fill else ring_vertices)
        off = offset + vd
        margin = stripe_width // 2 - vd
        contact_array(l, Rect4I(-rad, -rad + off, -rad + stripe_width, rad - off), via, vs, vd,
            Vec2I(margin, 0))
        contact_array(l, Rect4I(rad - stripe_width, -rad + off, rad, rad - off), via, vs, vd,
            Vec2I(margin, 0))
        contact_array(l, Rect4I(-rad + off, rad - stripe_width, rad - off, rad), via, vs, vd,
            Vec2I(0, margin))
        contact_array(l, Rect4I(-rad + off, -rad, rad - off, -rad + stripe_width), via, vs, vd,
            Vec2I(0, margin))
        # Vias on the diagonal edges, mirrored into all four corners
        step = vs + to_grid(vd / math.sqrt(2) + 5)
        x, y = -rad + to_grid(stripe_width / math.sqrt(2)), rad - offset
        while y < rad - stripe_width / 2 - 1.5 * vs - vd:
            l % LayoutRect(layer=via, rect=Rect4I(x, y, x + vs, y + vs))
            l % LayoutRect(layer=via, rect=Rect4I(x, -y - vs, x + vs, -y))
            l % LayoutRect(layer=via, rect=Rect4I(-x - vs, y, -x, y + vs))
            l % LayoutRect(layer=via, rect=Rect4I(-x - vs, -y - vs, -x, -y))
            x, y = x + step, y + step

    l.term_pad.create_pin(cell.symbol.pad)
    return l

@public
class Bondpad(SimLeafCell):
    """Bond pad on ``pad``, a placeholder model in simulation and plain metal in LVS."""
    size = Parameter(R)  #: Diameter
    shape = Parameter(int, default=0)  #: 0 octagon, 1 square, 2 circle (layout: 0 and 1)
    padtype = Parameter(int, default=0)  #: 0 bond pad, 1 probe pad (layout: 0)
    stack = Parameter(bool, default=True)  #: Metal rings with vias from bottom_metal up
    fill = Parameter(bool, default=False)  #: Full metal plates instead of the rings
    bottom_metal = Parameter(int, default=3)  #: Lowest metal of the stack, 1 to 6 (TopMetal1)
    add_filler_ex = Parameter(bool, default=False)  #: Fill blocking around the pad

    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.pad = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)

        s % SymbolPoly(vertices=[Vec2R(1.5, 1), Vec2R(2.5, 1), Vec2R(3.5, 2), Vec2R(3.5, 3),
            Vec2R(2.5, 4), Vec2R(1.5, 4), Vec2R(0.5, 3), Vec2R(0.5, 2), Vec2R(1.5, 1)])
        s % SymbolPoly(vertices=[Vec2R(1, 1.5), Vec2R(3, 3.5)])
        s % SymbolPoly(vertices=[Vec2R(1, 3.5), Vec2R(3, 1.5)])
        s % SymbolPoly(vertices=[Vec2R(2, 0), Vec2R(2, 1)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        if netlister.lvs:
            return
        netlister.require_netlist_setup(netlister_setup)
        netlister.require_netlist_setup(netlister_setup_bondpad)
        netlister.require_ngspice_setup(ngspice_setup)

        netlister.add(
            netlister.name_obj(inst, prefix="x"),
            netlister.portmap(inst, [inst.symbol.pad]),
            "bondpad",
            *spice_params({"size": self.size, "shape": self.shape, "padtype": self.padtype}),
        )

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_bondpad(self)

    @classmethod
    def discoverable_instances(cls):
        return [cls(size=R("80u"))]

def layoutgen_inductor(cell: Cell, three: bool) -> Layout:
    """
    Layout generation function shared for Inductor2 and Inductor3, as the
    PCell inductors_code.py with its defaults (QRC blocked, no substrate
    etching). Uses um floats like the PCell and rounds to nm at the end.
    """
    if cell.m != 1:
        raise ParameterError("m != 1 not supported for layout.")
    if cell.w < R("2u") or cell.s < R("2.1u"):
        raise ParameterError("w and s must be at least Wmin and Smin.")
    if cell.nr_r < (2 if three else 1):
        raise ParameterError("nr_r must be at least minNr_t.")
    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    def gridfix(v):
        return math.floor(v * 200 + 0.001) * 0.005

    def to_nm(v):
        return int(math.copysign(math.floor(abs(v) * 1000 + 0.5), v))

    def poly(layer, points):
        l % LayoutPoly(layer=layer, vertices=[Vec2I(to_nm(x), to_nm(y)) for x, y in points])

    def rect(layer, x1, y1, x2, y2):
        return l % LayoutRect(layer=layer,
            rect=Rect4I(to_nm(min(x1, x2)), to_nm(min(y1, y2)), to_nm(max(x1, x2)), to_nm(max(y1, y2))))

    tv2 = VIA_RULES["SG13G2_VIA_TM1_TM2"]
    cut, cut_space, pitch = tv2.size / 1000, tv2.space / 1000, (tv2.size + tv2.space) / 1000

    def vias(x0, y0, dx, dy):
        """Via array from (x0, y0), plus its mirror image at x = 0 shifted by (dx, dy)."""
        for i in range(nr_vias):
            for j in range(nr_vias):
                x, y = x0 + j*pitch, y0 + i*pitch
                rect(layers.TopVia2, x, y, x + cut, y + cut)
                rect(layers.TopVia2, dx - x, y + dy, dx - x - cut, y + dy + cut)

    sqrt2 = math.sqrt(2)
    var = 1 + sqrt2
    grid = 0.01
    w = gridfix(float(cell.w / R("1u")) * 0.5) * 2
    s = gridfix(float(cell.s / R("1u")))
    d = d1 = gridfix(float(cell.d / R("1u")) * 0.5) * 2
    nr_r = cell.nr_r
    nr_vias = round((w + 0.06) / pitch - 0.5)
    via_margin = (w - nr_vias*cut - (nr_vias - 1)*cut_space - 1) / 2
    # Smallest inner diameter, as inductor_minD in the PCell
    if nr_r == 1:
        d_min = gridfix((s + w + w) * (1 + sqrt2) / 2 + grid * 2) * 2
    elif nr_r == 2:
        d_min = gridfix((gridfix(w / sqrt2 + s / 2) + gridfix(s * 0.4143) + 0.02 + w)
            * 2 * (1 + sqrt2) + 0.01)
    else:
        d_min = gridfix(((gridfix(w / sqrt2 + s / 2) + gridfix(s * 0.4143)) * 2 + 2 * s + 4 * w)
            * (1 + sqrt2))
    d = max(d, d_min)
    # A turn is an octagon of inner diameter d: lat_sm is the length of its
    # sides, cateta_sm how far its 45 degree corners cut in.
    lat_sm = gridfix(d / (2 * var)) * 2
    cateta_sm = (d - lat_sm) / 2
    lead_len = 30   # from the pins at y = 0 up to the coil

    if three:
        rect(layers.TopMetal2, -w / 2, -1, w / 2, lead_len)
        l.term_lc = rect(layers.TopMetal2, -w / 2, -1, w / 2, 1)
        rect(layers.IND.pin, -w / 2, -1, w / 2, 1)
        l % LayoutLabel(layer=layers.IND.pin, pos=Vec2I(0, 0), text="LC")
    x1 = gridfix(lat_sm / 2) - w
    y2 = nr_r*w + (nr_r - 1)*s + lead_len - w
    # The turns cross between x = -x_cross and x_cross. 0.4143 is tan(22.5
    # degrees): how far a trace's corner shifts along the octagon's side.
    x_cross = gridfix(w / sqrt2 + s / 2)
    d1_via_cross = gridfix(w * 0.4143) + grid
    x_via = x_cross + (gridfix(s * 0.4143) + grid) + grid
    if three or nr_r % 2 == 0:
        rect(layers.TopMetal2, -x_via, lead_len, x_via, w + lead_len)
    if nr_r > 2:
        x_start = x_via + s + w
    else:
        x_start = s + w / 2 if three else s / 2
    if nr_r != 1:
        vias(x_start + 0.5 + via_margin, y2 + 0.5 + via_margin, 0, 0)

    for k in range(nr_r):
        xs = x_start if k == 0 else x1
        turn = [(xs, y2), (xs, y2 + w), (lat_sm / 2, y2 + w), (d / 2, y2 + w + cateta_sm),
            (d / 2, y2 + w + cateta_sm + lat_sm), (lat_sm / 2, y2 + w + d), (x_via, y2 + w + d),
            (x_via, y2 + w * 2 + d), (lat_sm / 2 + d1_via_cross, y2 + d + 2 * w),
            ((d + 2 * w) / 2, y2 + w + cateta_sm + lat_sm + d1_via_cross),
            ((d + 2 * w) / 2, y2 + w + cateta_sm - d1_via_cross), (lat_sm / 2 + d1_via_cross, y2)]
        poly(layers.TopMetal2, turn)
        poly(layers.TopMetal2, [(-x, y) for x, y in turn])
        if k % 2 == 0:
            if not three and nr_r % 2 == 1 and k == nr_r - 1:
                poly(layers.TopMetal2, [(x_via, y2+w+d), (x_via, y2+w*2+d), (-x_via, y2+w*2+d),
                    (-x_via, y2+w+d)])
            else:
                # Crossing to the next turn: TopMetal1 underpass, TopMetal2 overpass
                poly(layers.TopMetal1, [(x_via+w, y2+w+d), (x_via+w, y2+w*2+d), (x_cross, y2+w*2+d),
                    (x_cross-(w+s+2*grid), y2+w*3+s+d+2*grid), (-x_via-w, y2+w*3+s+d+2*grid),
                    (-x_via-w, y2+w*2+s+d+2*grid), (-x_cross, y2+w*2+s+d+2*grid),
                    (w+s+2*grid-x_cross, y2+w+d)])
                poly(layers.TopMetal2, [(-x_via, y2+w+d), (-x_via, y2+w*2+d), (-x_cross, y2+w*2+d),
                    (w+s+2*grid-x_cross, y2+w*3+s+d+2*grid), (x_via, y2+w*3+s+d+2*grid),
                    (x_via, y2+w*2+s+d+2*grid), (x_cross+3*grid, y2+w*2+s+d+2*grid),
                    (x_cross-(w+s-grid), y2+w+d)])
                vias(x_via + 0.5 + via_margin, y2 + w + d + 0.5 + via_margin, 0, s + w)
            if k != 0:
                poly(layers.TopMetal2, [(x_via, y2), (x_via, y2 + w), (x_cross + grid, y2 + w),
                    (x_cross - (w + s) + grid, y2 + 2 * w + s), (-x_via, y2 + 2 * w + s),
                    (-x_via, y2 + w + s), (-x_cross, y2 + w + s), (-x_cross + w + s, y2)])
                poly(layers.TopMetal1, [(-x_via - w, y2), (-x_via - w, y2 + w),
                    (-x_cross - grid, y2 + w), (-x_cross + w + s - grid, y2 + 2 * w + s),
                    (x_via + w + grid, y2 + 2 * w + s), (x_via + w + grid, y2 + w + s),
                    (x_cross, y2 + w + s), (x_cross - (w + s), y2)])
                vias(x_via + grid + 0.5 + via_margin, y2 + w + s + 0.5 + via_margin, grid, -(s + w))
        y2 = y2 - w - s
        x1 = x_via
        d = d + 2 * (s + w + grid)
        lat_sm = gridfix(d / (2 * var)) * 2
        cateta_sm = (d - lat_sm) / 2

    # Leads, with the pins at their ends on the IND edge as in the PCell
    if nr_r <= 2:
        x1 = w + s if three else (w + s) / 2
    else:
        x1 = x1 + w / 2 + s + w
    lead = layers.TopMetal2 if not three and nr_r == 1 else layers.TopMetal1
    y_end = nr_r * w + (nr_r - 1) * s + lead_len
    for x, text in ((x1, "LB"), (-x1, "LA")):
        rect(lead, x - w / 2, -1, x + w / 2, y_end)
        rect(layers.IND.pin, x - w / 2, -1, x + w / 2, 1)
        l % LayoutLabel(layer=layers.IND.pin, pos=Vec2I(to_nm(x), 0), text=text)
    l.term_lb = rect(lead, x1 - w / 2, -1, x1 + w / 2, 1)
    l.term_la = rect(lead, -x1 - w / 2, -1, -x1 + w / 2, 1)
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(0, to_nm(y2 + cateta_sm / 2 + lat_sm)),
        text="inductor3" if three else "inductor2")
    if three:
        l.term_la.create_pin(cell.symbol.la)
        l.term_lb.create_pin(cell.symbol.lb)
        l.term_lc.create_pin(cell.symbol.lc)
    else:
        l.term_la.create_pin(cell.symbol.p)
        l.term_lb.create_pin(cell.symbol.m)

    # The marker and blocking layers reach 30 um beyond the outer turn.
    d = d - 2 * s + 2 * 30
    lat_sm = gridfix(d / (2 * var)) * 2
    cateta_sm = (d - lat_sm) / 2
    octagon = [(lat_sm / 2, 0), (d / 2, cateta_sm), (d / 2, cateta_sm + lat_sm), (lat_sm / 2, d),
        (-lat_sm / 2, d), (-d / 2, cateta_sm + lat_sm), (-d / 2, cateta_sm), (-lat_sm / 2, 0)]
    for layer in (layers.PWell.block, layers.Activ.nofill, layers.GatPoly.nofill,
        layers.Metal1.nofill, layers.Metal2.nofill, layers.Metal3.nofill,
        layers.Metal4.nofill, layers.Metal5.nofill, layers.TopMetal1.nofill,
        layers.TopMetal2.nofill, layers.IND, layers.NoRCX):
        poly(layer, octagon)
    # Parameters for the LVS extraction
    y = 2 * nr_r * w + 2 * (nr_r - 1) * s + (d1 - lat_sm) / 4 + lat_sm
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(to_nm(-d / 2), to_nm(y)),
        text=f"  width={w:.1f}\n  space={s:.1f}\n  diameter={d1:.2f}\n  turns={nr_r:d}")
    return l

class Inductor(SimLeafCell):
    """Shared base class of the octagonal inductors on TopMetal2, ``b`` the substrate."""
    center_tap = False
    w = Parameter(R)  #: Width
    s = Parameter(R)  #: Space
    d = Parameter(R)  #: Inner diameter
    nr_r = Parameter(int)  #: Number of turns
    m = Parameter(int, default=1)

    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        top, bottom = self.ends
        s[top] = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)
        s[bottom] = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.b = Pin(pos=Vec2R(4, 2), pintype=PinType.In, align=East)
        if self.center_tap:
            s.lc = Pin(pos=Vec2R(0, 2), pintype=PinType.Inout, align=West)
            s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(2, 2)])

        s % SymbolPoly(vertices=[Vec2R(2, 4), Vec2R(2, 3.2)])
        s % SymbolPoly(vertices=[Vec2R(2, 0.8), Vec2R(2, 0)])
        for y in (1.1, 1.7, 2.3, 2.9):
            s % SymbolArc(pos=Vec2R(2, y), radius=R(0.3), angle_start=R(-0.25), angle_end=R(0.25))
        s % SymbolPoly(vertices=[Vec2R(3, 2), Vec2R(4, 2)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        netlister.add(
            netlister.name_obj(inst, prefix="L" if netlister.lvs else "x"),
            netlister.portmap(inst, [inst.symbol[p] for p in self.netlist_pins]),
            self.model_name,
            *spice_params({"w": self.w, "s": self.s, "d": self.d, "nr_r": self.nr_r, "m": self.m}),
        )

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("10u"), s=R("10u"), d=R("222u"), nr_r=2)]

@public
class Inductor2(Inductor):
    """Inductor from ``p`` to ``m``. The PDK has no simulation model for it."""
    model_name = "inductor"
    ends = ("p", "m")
    netlist_pins = ("p", "m", "b")

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_inductor(self, three=False)

@public
class Inductor3(Inductor):
    """
    Inductor from ``la`` to ``lb`` with center tap ``lc``. The PDK has no simulation
    model for it.
    """
    model_name = "inductor3"
    ends = ("la", "lb")
    center_tap = True
    netlist_pins = ("la", "lc", "lb", "b")

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_inductor(self, three=True)

class Npn(SimLeafCell):
    """
    Base class of the SG13G2 npn HBTs: collector ``c``, base ``b``, emitter
    ``e``, substrate ``bn``. With ``thermal``, simulation uses the ``_5t``
    model, its extra pin ``t`` gives the temperature rise (not used in LVS).
    """
    nx = Parameter(int, default=1)  #: Number of emitters (Nx)
    thermal = Parameter(bool, default=False)  #: Temperature output pin t

    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.c = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)
        s.b = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=West)
        s.e = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.bn = Pin(pos=Vec2R(4, 2), pintype=PinType.In, align=East)
        if self.thermal:
            s.t = Pin(pos=Vec2R(4, 3), pintype=PinType.Out, align=East)
            s % SymbolPoly(vertices=[Vec2R(3.2, 3), Vec2R(4, 3)])

        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1.3, 2)])
        s % SymbolPoly(vertices=[Vec2R(1.3, 1.25), Vec2R(1.3, 2.75)])
        s % SymbolPoly(vertices=[Vec2R(2, 4), Vec2R(2, 3), Vec2R(1.3, 2.4)])
        s % SymbolPoly(vertices=[Vec2R(2, 0), Vec2R(2, 1), Vec2R(1.3, 1.6)])
        s % SymbolPoly(vertices=[Vec2R(1.66, 1.06), Vec2R(2, 1), Vec2R(1.88, 1.33)])
        s % SymbolPoly(vertices=[Vec2R(2.6, 2), Vec2R(4, 2)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlister_setup)
        netlister.require_netlist_setup(netlister_setup_hbt)
        netlister.require_ngspice_setup(ngspice_setup)

        pins = [inst.symbol.c, inst.symbol.b, inst.symbol.e, inst.symbol.bn]
        model = self.model_name
        if netlister.lvs:
            prefix = "Q"
        else:
            prefix = "x"
            if self.thermal:
                pins.append(inst.symbol.t)
                model += "_5t"
        netlister.add(
            netlister.name_obj(inst, prefix=prefix),
            netlister.portmap(inst, pins),
            model,
            *spice_params(self.netlist_params(netlister.lvs)),
        )

    @classmethod
    def discoverable_instances(cls):
        return [cls()]

def layoutgen_npn13g2(cell: Cell) -> Layout:
    """
    Generate the SG13G2 npn13G2 layout, as the PCell npn13G2_code.py. The
    emitter size is fixed, so the PCell's coordinates are used as they are.
    """
    if not 1 <= cell.nx <= 10:
        raise ParameterError("nx must be 1 to 10.")
    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    step_x = 1850
    x_last = step_x * (cell.nx - 1)
    for x in range(0, x_last + 1, step_x):
        l % LayoutRect(layer=layers.EmWind, rect=Rect4I(x - 35, -450, x + 35, 450))
        l % LayoutRect(layer=layers.HeatTrans, rect=Rect4I(x - 85, -500, x + 85, 500))
        l % LayoutLabel(layer=layers.HeatTrans, pos=Vec2I(x, 0), text="npn13G2")
        l % LayoutPoly(layer=layers.Activ.mask, vertices=[
            Vec2I(x + 925, 980), Vec2I(x - 925, 980), Vec2I(x - 925, -620),
            Vec2I(x - 445, -620), Vec2I(x - 235, -830), Vec2I(x + 235, -830),
            Vec2I(x + 445, -620), Vec2I(x + 925, -620)])
        l % LayoutRect(layer=layers.Activ, rect=Rect4I(x - 925, 980, x + 925, 1280))
        l % LayoutPoly(layer=layers.nSD.block, vertices=[
            Vec2I(x + 975, -2430), Vec2I(x + 975, -900), Vec2I(x + 555, -480),
            Vec2I(x + 555, 690), Vec2I(x + 305, 940), Vec2I(x - 305, 940), Vec2I(x - 555, 690),
            Vec2I(x - 555, -480), Vec2I(x - 975, -900), Vec2I(x - 975, -2430)])
        l % LayoutRect(layer=layers.Cont, rect=Rect4I(x - 825, 1050, x + 825, 1210))
        l % LayoutRect(layer=layers.Cont, rect=Rect4I(x - 760, -1220, x + 760, -1060))
        l % LayoutRect(layer=layers.Metal1, rect=Rect4I(x - 350, -785, x + 350, 770))
        for y in (510, 100, -310, -720):
            l % LayoutRect(layer=layers.Via1, rect=Rect4I(x - 300, y, x - 110, y + 190))
            l % LayoutRect(layer=layers.Via1, rect=Rect4I(x + 110, y, x + 300, y + 190))

    if cell.nx == 1:
        l.term_c = LayoutRect(layer=layers.Metal1, rect=Rect4I(-925, 1010, 925, 1250))
    else:
        l.term_c = LayoutRect(layer=layers.Metal1, rect=Rect4I(-925, 1020, x_last + 925, 1460))
    l.term_b = LayoutRect(layer=layers.Metal1, rect=Rect4I(-975, -1260, x_last + 975, -1020))
    l.term_e = LayoutRect(layer=layers.Metal2, rect=Rect4I(-925, -785, x_last + 925, 770))
    l % LayoutRect(layer=layers.TRANS, rect=Rect4I(-2450, -2430, x_last + 2450, 2880))
    ring(l, layers.pSD,
        Rect4I(-3350, -3330, x_last + 3350, 3780), Rect4I(-2450, -2430, x_last + 2450, 2880))
    ring(l, layers.Activ,
        Rect4I(-3150, -3130, x_last + 3150, 3580), Rect4I(-2650, -2630, x_last + 2650, 3080))
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(15, 2310), text="npn13G2")
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(-1977, -2546), text=f"Ae={cell.nx}*1*0.07*0.90")

    for node, pin, text in ((l.term_c, cell.symbol.c, "C"), (l.term_b, cell.symbol.b, "B"),
        (l.term_e, cell.symbol.e, "E")):
        node.create_pin(pin)
        l % LayoutLabel(layer=layers.TEXT, pos=node.rect.center, text=text)
    return l

@public
class Npn13G2(Npn):
    """HBT with emitters of 0.07 x 0.9 um."""
    model_name = "npn13G2"

    def netlist_params(self, lvs: bool) -> dict:
        # LVS needs Nx. xschem writes m=Nx instead, which LVS reads as
        # parallel devices.
        if lvs:
            return {"le": R("900n"), "we": R("70n"), "Nx": self.nx}
        return {"Nx": self.nx}

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_npn13g2(self)

def layoutgen_npn13g2l(cell: Cell, hv: bool) -> Layout:
    """
    Layout generation function shared for Npn13G2l and Npn13G2v (hv), as the
    PCells npn13G2L_code.py and npn13G2V_code.py.
    """
    nx_max, el_max = (8, R(5)) if hv else (4, R("2.5"))
    if not 1 <= cell.nx <= nx_max or not 1 <= cell.el <= el_max:
        raise ParameterError(f"nx must be 1 to {nx_max}, el 1 to {el_max}.")
    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    le = int(cell.el * 1000)
    we = int(cell.we / R("1n"))
    em_x, em_y = (3810 if hv else 3865), 3100                # emWindOrigin
    activ_enc_x, activ_enc_y = (1110 if hv else 1365), 280   # Activ_enc_hori, Activ_enc_vert
    col_dist, col_w = (790, 320) if hv else (975, 390)       # Col_Metal1_distance, _width
    bas_dist, bas_w = (295, 170) if hv else (320, 160)       # Bas_Metal1_distance, _width
    emi_enc_x, emi_enc_y = (70, 280) if hv else (95, 200)    # Emi_Metal1_enc_hori, _vert
    # Count the base contact rows in floats like the PCell, which gives
    # one row less for some el (e.g. 1.15).
    le_um = float(cell.el) * 1e-6 * 1e6
    rows = int((le_um + 0.21) / (0.16 + 0.18)) + 1
    if hv:
        vias = (le + 460) // 410
        if le + 2*emi_enc_y < 410*vias + 250:  # emitter Metal1 shorter than the via column
            vias -= 1

    pitch = we + 2*(col_dist + col_w)
    x_last = pitch * (cell.nx - 1)
    col_lo, col_hi = 2820, 4100 + le  # collector strips, at the PCell's heights
    bas_lo, bas_hi = 2100, 3380 + le  # base strips
    for dx in range(0, x_last + 1, pitch):
        x0, x1 = em_x + dx, em_x + dx + we
        l % LayoutRect(layer=layers.EmWiHV if hv else layers.EmWind,
            rect=Rect4I(x0, em_y, x1, em_y + le))
        l % LayoutRect(layer=layers.HeatTrans,
            rect=Rect4I(x0 - 50, em_y - 50, x1 + 50, em_y + le + 50))
        # Activ, masked between the emitter and the base
        y0, y1 = em_y - activ_enc_y, em_y + le + activ_enc_y
        for lx, ux in ((x0 - activ_enc_x, x0 - 705), (x0 - emi_enc_x, x1 + emi_enc_x),
            (x1 + 705, x1 + activ_enc_x)):
            l % LayoutRect(layer=layers.Activ, rect=Rect4I(lx, y0, ux, y1))
        l % LayoutRect(layer=layers.Activ.mask, rect=Rect4I(x0 - 705, y0, x0 - emi_enc_x, y1))
        l % LayoutRect(layer=layers.Activ.mask, rect=Rect4I(x1 + emi_enc_x, y0, x1 + 705, y1))
        # Metal1 strips on both sides of the emitter: the outer collector
        # strips reach up to the collector bar above the emitters, the inner
        # base strips down to the base bar below them.
        l % LayoutRect(layer=layers.Metal1,
            rect=Rect4I(x0 - col_dist - col_w, col_lo, x0 - col_dist, col_hi))
        l % LayoutRect(layer=layers.Metal1,
            rect=Rect4I(x1 + col_dist, col_lo, x1 + col_dist + col_w, col_hi))
        l % LayoutRect(layer=layers.Metal1,
            rect=Rect4I(x0 - bas_dist - bas_w, bas_lo, x0 - bas_dist, bas_hi))
        l % LayoutRect(layer=layers.Metal1,
            rect=Rect4I(x1 + bas_dist, bas_lo, x1 + bas_dist + bas_w, bas_hi))
        l % LayoutRect(layer=layers.Metal1,
            rect=Rect4I(x0 - emi_enc_x, em_y - emi_enc_y, x1 + emi_enc_x, em_y + le + emi_enc_y))
        # Contacts and vias at the PCell's coordinates
        if hv:
            for i in range(vias + 1):
                y = 2870 + 410*i
                l % LayoutRect(layer=layers.Via1, rect=Rect4I(dx + 3775, y, dx + 3965, y + 190))
            l % LayoutRect(layer=layers.Cont, rect=Rect4I(dx + 3790, 3040, dx + 3950, 3160 + le))
            cont_x = (2800, 3350, 4230, 4780)
        else:
            l % LayoutRect(layer=layers.Via1, rect=Rect4I(dx + 3805, 3000, dx + 3995, 3200 + le))
            for x in (2680, 3820, 4960):
                l % LayoutRect(layer=layers.Cont,
                    rect=Rect4I(dx + x, 2950, dx + x + 160, 3250 + le))
            cont_x = (3385, 4255)
        for i in range(rows):
            y = 2890 + 340*i
            for x in cont_x:
                l % LayoutRect(layer=layers.Cont, rect=Rect4I(dx + x, y, dx + x + 160, y + 160))

    xc0, xc1 = em_x - col_dist - col_w, x_last + em_x + we + col_dist + col_w
    l.term_c = LayoutRect(layer=layers.Metal1, rect=Rect4I(xc0, col_hi, xc1, col_hi + 650))
    l.term_b = LayoutRect(layer=layers.Metal1,
        rect=Rect4I(em_x - bas_dist - bas_w, bas_lo - 650, x_last + em_x + we + bas_dist + bas_w, bas_lo))
    l.term_e = LayoutRect(layer=layers.Metal2,
        rect=Rect4I(xc0, em_y - emi_enc_y, xc1, em_y + le + emi_enc_y))
    # Guard ring along the cell's edge (the cell is symmetric around its
    # emitters): pSD 900 wide, its Activ from 200 to 700 in from the edge,
    # TRANS on the inside.
    xr, yt = 2*em_x + we + x_last, 6200 + le

    def inset(d):
        return Rect4I(d, d, xr - d, yt - d)

    l % LayoutRect(layer=layers.TRANS, rect=inset(900))
    ring(l, layers.pSD, inset(0), inset(900))
    ring(l, layers.Activ, inset(200), inset(700))

    name = "npn13G2V" if hv else "npn13G2L"
    # The PCell labels only the first emitter's HeatTrans.
    l % LayoutLabel(layer=layers.HeatTrans, pos=Vec2I(em_x + we // 2, em_y + le // 2), text=name)
    ae = f"Ae={cell.nx}*{le_um:.2f}*0.12" if hv else f"Ae={cell.nx}*1*{le_um:.2f}*0.07"
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(1500, 1000), text=ae)
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(1750, 1000), text=name)

    for node, pin, text in ((l.term_c, cell.symbol.c, "C"), (l.term_b, cell.symbol.b, "B"),
        (l.term_e, cell.symbol.e, "E")):
        node.create_pin(pin)
        l % LayoutLabel(layer=layers.TEXT, pos=node.rect.center, text=text)
    return l

@public
class Npn13G2l(Npn):
    """HBT with emitters of 0.07 um x ``el``."""
    model_name = "npn13G2l"
    we = R("70n")

    el = Parameter(R)  #: Emitter length in um (El)

    def netlist_params(self, lvs: bool) -> dict:
        if lvs:
            return {"le": self.el * R("1u"), "we": self.we, "Nx": self.nx}
        return {"Nx": self.nx, "El": self.el}

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_npn13g2l(self, hv=False)

    @classmethod
    def discoverable_instances(cls):
        return [cls(el=R(1))]

@public
class Npn13G2v(Npn13G2l):
    """HBT with emitters of 0.12 um x ``el``."""
    model_name = "npn13G2v"
    we = R("120n")

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_npn13g2l(self, hv=True)

def layoutgen_pnpmpa(cell: Cell) -> Layout:
    """
    Generate the SG13G2 pnpMPA layout, as the PCell pnpMPA_code.py, centered on
    the emitter.
    """
    if cell.m != 1:
        raise ParameterError("m != 1 not supported for layout.")
    if not (R("0.3u") <= cell.w <= R("2u") and R("0.68u") <= cell.l <= R("1m")):
        raise ParameterError("w must be 0.3u to 2u, l 0.68u to 1m.")
    layers = SG13G2().layers
    l = Layout(ref_layers=layers, cell=cell, symbol=cell.symbol)

    def box(x, y):
        return Rect4I(-x, -y, x, y)

    # Half sizes, named as in the PCell
    wact = 5 * (int(cell.w / R("1n")) // 10)
    hact = 5 * (int(cell.l / R("1n")) // 10)
    wpsd, hpsd = wact + 210, hact + 180
    w2act, h2act = wpsd + 180, hpsd + 180  # pSD.c
    dw2act, dh2act = max(wact, 300), 290
    wbulay, hbulay = w2act + dw2act + 50, h2act + dh2act + 50
    wnwell, hnwell = wbulay + 260, hbulay + 260
    w2psd, h2psd, d2psd = wnwell + 500, hnwell + 500, 750
    w3act, h3act, d3act = w2psd + 200, h2psd + 200, 350
    cont = VIA_RULES["SG13G2_CONT_ACTIV_M1"]
    m1_c1 = cont.endcap_top  # M1.c1

    # Wider contact spacing (Cnt.b1) from 4 x 4 contacts on. The base
    # uses the emitter's spacing, as in the PCell.
    vg4 = (cont.size + cont.space)*4 + cont.size + 2*m1_c1
    spacing = cont.space_dense if 2 * (min(wact, hact) - 20) >= vg4 else cont.space
    l.term_e = LayoutRect(layer=layers.Metal1, rect=box(wact - 20, hact - 20))
    contact_array(l, l.term_e.rect, layers.Cont, cont.size, spacing, Vec2I(m1_c1, m1_c1))
    l % LayoutRect(layer=layers.Activ, rect=box(wact, hact))
    l % LayoutRect(layer=layers.pSD, rect=box(wpsd, hpsd))

    ring(l, layers.Activ, box(w2act + dw2act, h2act + dh2act), box(w2act, h2act))
    l.term_b = PathNode()
    for i, x in enumerate((-w2act - dw2act + 20, w2act + 20)):
        l.term_b[i] = LayoutRect(layer=layers.Metal1,
            rect=Rect4I(x, -h2act - 20, x + dw2act - 40, h2act + 20))
        contact_array(l, l.term_b[i].rect, layers.Cont, cont.size, spacing, Vec2I(m1_c1, m1_c1))
    for y in (h2act + 20, -h2act - dh2act + 20):
        l % LayoutRect(layer=layers.Metal1,
            rect=Rect4I(-w2act - dw2act + 20, y, w2act + dw2act - 20, y + dh2act - 40))
    l % LayoutRect(layer=layers.nBuLay, rect=box(wbulay, hbulay))
    l % LayoutRect(layer=layers.NWell, rect=box(wnwell, hnwell))

    ring(l, layers.pSD, box(w2psd + d2psd, h2psd + d2psd), box(w2psd, h2psd))
    ring(l, layers.Activ, box(w3act + d3act, h3act + d3act), box(w3act, h3act))
    l.term_c = PathNode()
    for i, y in enumerate((h3act, -h3act - d3act)):
        l.term_c[i] = LayoutRect(layer=layers.Metal1,
            rect=Rect4I(-w3act - d3act, y, w3act + d3act, y + d3act))
        contact_array(l, l.term_c[i].rect, layers.Cont, cont.size, cont.space, Vec2I(95, m1_c1))
    for x in (-w3act - d3act, w3act):
        m1 = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(x, -h3act, x + d3act, h3act))
        contact_array(l, m1.rect, layers.Cont, cont.size, cont.space, Vec2I(95, 85))

    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(0, 0), text="PLUS")
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(-w2act - dw2act / 2, 0), text="MINUS")
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(0, -hnwell - 250), text="pnpMPA")
    l % LayoutLabel(layer=layers.TEXT, pos=Vec2I(0, h3act + d3act // 2), text="TIE")

    l.term_e.create_pin(cell.symbol.e)
    l.term_b[0].create_pin(cell.symbol.b)
    l.term_c[0].create_pin(cell.symbol.c)
    return l

@public
class PnpMPA(SimLeafCell):
    """
    Substrate pnp: emitter ``e`` of ``w`` x ``l`` in an NWell as base ``b``,
    the substrate as collector ``c``.
    """
    w = Parameter(R)
    l = Parameter(R)
    m = Parameter(int, default=1)

    @viewgen_noctx
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.e = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)
        s.b = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=West)
        s.c = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)

        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1.3, 2)])
        s % SymbolPoly(vertices=[Vec2R(1.3, 1.25), Vec2R(1.3, 2.75)])
        s % SymbolPoly(vertices=[Vec2R(2, 4), Vec2R(2, 3), Vec2R(1.3, 2.4)])
        s % SymbolPoly(vertices=[Vec2R(2, 0), Vec2R(2, 1), Vec2R(1.3, 1.6)])
        s % SymbolPoly(vertices=[Vec2R(1.77, 3.03), Vec2R(1.65, 2.7), Vec2R(1.99, 2.76)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlister_setup)
        netlister.require_netlist_setup(netlister_setup_hbt)
        netlister.require_ngspice_setup(ngspice_setup)

        netlister.add(
            netlister.name_obj(inst, prefix="Q" if netlister.lvs else "x"),
            netlister.portmap(inst, [inst.symbol.c, inst.symbol.b, inst.symbol.e]),
            "pnpMPA",
            *spice_params({"a": self.w * self.l, "p": 2 * (self.w + self.l), "m": self.m}),
        )

    @viewgen_noctx
    def layout(self) -> Layout:
        return layoutgen_pnpmpa(self)

    @classmethod
    def discoverable_instances(cls):
        return [cls(w=R("1u"), l=R("2u"))]


#: Device map for spice_in:
device_map = {
    "sg13_lv_nmos": DeviceMapping(Nmos, ("d", "g", "s", "b"), real_params=("l", "w"), int_params=("ng", "m")),
    "sg13_lv_pmos": DeviceMapping(Pmos, ("d", "g", "s", "b"), real_params=("l", "w"), int_params=("ng", "m")),
    "sg13_hv_nmos": DeviceMapping(NmosHv, ("d", "g", "s", "b"), real_params=("l", "w"), int_params=("ng", "m")),
    "sg13_hv_pmos": DeviceMapping(PmosHv, ("d", "g", "s", "b"), real_params=("l", "w"), int_params=("ng", "m")),
    "rfnmos": DeviceMapping(RfNmos, ("d", "g", "s", "b"), real_params=("l", "w"), int_params=("ng", "m")),
    "rfpmos": DeviceMapping(RfPmos, ("d", "g", "s", "b"), real_params=("l", "w"), int_params=("ng", "m")),
    "rfnmoshv": DeviceMapping(RfNmosHv, ("d", "g", "s", "b"), real_params=("l", "w"), int_params=("ng", "m")),
    "rfpmoshv": DeviceMapping(RfPmosHv, ("d", "g", "s", "b"), real_params=("l", "w"), int_params=("ng", "m")),
    "ntap1": DeviceMapping(Ntap1, ("tie", "well"), real_params=("l", "w")),
    "ptap1": DeviceMapping(Ptap1, ("tie", "sub"), real_params=("l", "w")),
    "rsil": DeviceMapping(Rsil, ("p", "n", "bn"), real_params=("l", "w", "ps"), int_params=("b", "m")),
    "rppd": DeviceMapping(Rppd, ("p", "n", "bn"), real_params=("l", "w", "ps"), int_params=("b", "m")),
    "rhigh": DeviceMapping(Rhigh, ("p", "n", "bn"), real_params=("l", "w", "ps"), int_params=("b", "m")),
    "cap_cmim": DeviceMapping(Cmim, ("p", "n"), real_params=("l", "w"), int_params=("m",)),
    "npn13G2": DeviceMapping(Npn13G2, ("c", "b", "e", "bn"), int_params=("nx",)),
    "npn13G2l": DeviceMapping(Npn13G2l, ("c", "b", "e", "bn"), real_params=("el",), int_params=("nx",)),
    "npn13G2v": DeviceMapping(Npn13G2v, ("c", "b", "e", "bn"), real_params=("el",), int_params=("nx",)),
    "pnpMPA": DeviceMapping(PnpMPA, ("c", "b", "e"), int_params=("m",)),
    "cap_rfcmim": DeviceMapping(Rfcmim, ("p", "n", "bn"), real_params=("w", "l", "wfeed")),
    "rfcmim": DeviceMapping(Rfcmim, ("p", "n", "bn"), real_params=("w", "l", "wfeed")),
    "sg13_hv_svaricap": DeviceMapping(Svaricap, ("g1", "nw", "g2", "bn"), real_params=("w", "l"), int_params=("nx",)),
    "cparasitic": DeviceMapping(Cpara, ("p", "n"), real_params=("c",)),
    "bondpad": DeviceMapping(Bondpad, ("pad",), real_params=("size",), int_params=("shape", "padtype")),
    "inductor": DeviceMapping(Inductor2, ("p", "m", "b"), real_params=("w", "s", "d"), int_params=("nr_r", "m")),
    "inductor3": DeviceMapping(Inductor3, ("la", "lc", "lb", "b"), real_params=("w", "s", "d"),
        int_params=("nr_r", "m")),
}
# TODO: In the future, this device_map dictionary should be automatically derived
# from the PDK's cell definitions?!


# klayout-new -b -r '/home/tobias/workspace/ordec/lvs/drc_run_2025_11_26_13_11_34/main.drc'
#     -rd drc_json_default='/home/tobias/workspace/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/sg13g2_tech_default.json'
#     -rd         drc_json='/home/tobias/workspace/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech_mod.json'


@public
def run_drc(l: Layout, variant='maximal', use_tempdir: bool=True,
        antenna: bool=True, density: bool=False) -> DrcReport:
    """Run the KLayout DRC sign-off decks over a layout.

    Args:
        l: the Layout to check.
        variant: 'minimal' runs the main deck alone, 'maximal' also runs the
            sg13g2_maximal deck.
        use_tempdir: run in a temporary directory instead of ./drc.
        antenna: also run the PDK's antenna deck.
        density: also run the PDK's density deck.
    """
    if variant not in ('minimal', 'maximal'):
        raise ValueError("variant must be either 'minimal' or 'maximal'.")

    directory = Directory()

    with rundir('drc', use_tempdir) as cwd:
        with open(cwd / "layout.gds", "wb") as f:
            write_gds(l, f, directory)

        klayout_shared_opts = dict(
            # threads=1 is a workaround for an intermittent KLayout SIGSEGV in
            # multithreaded deep-mode DRC. Single-threaded runs seem reliable
            # and are only marginally slower.
            threads="1",
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

        (cwd / 'main.log').unlink(missing_ok=True)
        klayout.run(pdk().klayout_drc_main_deck, cwd,
            report="main.lyrdb",
            log="main.log",
            table_name="main",
            tables="main",
            **klayout_shared_opts
            )
        report = DrcReport(ref_layout=l, top_cell_name=directory.name_subgraph(l))
        klayout.parse_rdb(cwd / "main.lyrdb", report, directory)

        if variant == 'maximal':
            (cwd / 'maximal.log').unlink(missing_ok=True)
            klayout.run(pdk().klayout_drc_decks_dir / 'sg13g2_maximal.drc', cwd,
                report="maximal.lyrdb",
                log="maximal.log",
                table_name="sg13g2_maximal",
                **klayout_shared_opts
                )
            klayout.parse_rdb(cwd / "maximal.lyrdb", report, directory)

        if antenna:
            (cwd / 'antenna.log').unlink(missing_ok=True)
            klayout.run(pdk().klayout_drc_decks_dir / 'antenna.drc', cwd,
                report="antenna.lyrdb",
                log="antenna.log",
                **klayout_shared_opts
                )
            klayout.parse_rdb(cwd / "antenna.lyrdb", report, directory)

        if density:
            (cwd / 'density.log').unlink(missing_ok=True)
            klayout.run(pdk().klayout_drc_decks_dir / 'density.drc', cwd,
                report="density.lyrdb",
                log="density.log",
                **klayout_shared_opts
                )
            klayout.parse_rdb(cwd / "density.lyrdb", report, directory)

        return report


@public
def run_lvs(layout: Layout, symbol: Symbol, use_tempdir: bool=True) -> LvsReport:
    """
    Run LVS (Layout vs. Schematic) check.

    Args:
        layout: The Layout to check.
        symbol: The Symbol containing the reference schematic.
        use_tempdir: If True, use a temporary directory for intermediate files.
    """
    directory = klayout.LvsDirectory()
    nl = Netlister(directory, lvs=True)
    nl.netlist_hier_symbol(symbol)

    schematic = symbol.cell.schematic

    with rundir('lvs', use_tempdir) as cwd:
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

        return klayout.parse_lvsdb(cwd / 'out.lvsdb', layout, schematic, directory)

# The sg13g2 routing-grid and emitted-geometry profile the P&R engine works
# from. Track pitches and row height come from the tech LEF; the wire, via,
# landing, strap and rail dimensions and the manufacturing grid come from the
# sign-off DRC rules. Frozen, so the engine derives its per-floorplan variants
# with dataclasses.replace rather than mutating it.
via1 = VIA_RULES["SG13G2_VIA_M1_M2"]   # the grid's via
public(grid = GridConfig(
    # Routing grid (sg13g2 tech LEF):
    x_pitch=480,
    y_pitch=420,
    row_height=3780,
    tracks_per_row=9,
    via_half=via1.size // 2,
    encl=via1.enc_bottom,
    encl_endcap=via1.endcap_bottom,
    manufacturing_grid=5, # sg13g2 layout quantum (MANUFACTURINGGRID)
    # Supply naming (sg13g2 stdcell library pins + ORDeC net conventions):
    vdd_pin="VDD",
    vss_pin="VSS",
    vdd_net="vdd",
    vss_net="vss",
    # Emitted geometry (sg13g2 sign-off DRC rules):
    wire_width=210,       # Mn min width
    wire_ext=via1.size // 2 + 55,  # via half + 55 endcap (Mn.c1 / V*.c1)
    strap_half_w=105,     # wire_width / 2
    land_half_h=345,      # 690 nm landing -> Mn min area
    m1_land_half_h=via1.size // 2 + via1.endcap_bottom,  # Metal1 endcap landing under a Via1 (V1.c1)
    min_area_tracks=2,    # 2 * pitch * 210 nm wire >= 0.144 um^2 Mn min area
    port_pad_inner=600,   # from the edge rail into the block
    port_pad_outer=360,   # from the edge rail into the parent's channel
    strap_vdd_x=-520,     # left margin; right strap mirrors to die_w + 520
    strap_vss_x=-1080,    # just outside VDD
    rail_ext=150,
    mesh_half_w=210,      # 420 nm Metal5 mesh straps (2x wire width)
    ))
