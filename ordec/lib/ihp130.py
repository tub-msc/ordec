# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
import logging
from pathlib import Path
from public import public
import functools

from ..core import *
from ..schematic import helpers
from . import generic_mos
from .pdk_common import PdkDict, check_dir, check_file

@functools.cache
def pdk() -> PdkDict:
    """Returns dictionary-like object with import PDK paths."""
    try:
        root = os.environ["ORDEC_PDK_IHP_SG13G2"]
    except KeyError:
        raise Exception("PDK requires environment variable ORDEC_PDK_IHP_SG13G2 to be set.")
    pdk = PdkDict(root=check_dir(Path(root).resolve()))

    pdk.ngspice_models_dir = check_dir(pdk.root / "libs.tech/ngspice/models")
    pdk.ngspice_osdi_dir   = check_dir(pdk.root / "libs.tech/ngspice/osdi")
    pdk.stdcell_spice_dir  = check_dir(pdk.root / "libs.ref/sg13g2_stdcell/spice")
    pdk.iocell_spice_dir   = check_dir(pdk.root / "libs.ref/sg13g2_io/spice")

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
    # Load corner library with typical corner
    model_lib = pdk().ngspice_models_dir / "cornerMOSlv.lib"
    netlister.add(".lib", f"\"{model_lib}\" mos_tt")

    # Add options from .spiceinit
    netlister.add(".option", "tnom=28")
    netlister.add(".option", "warn=1")
    netlister.add(".option", "maxwarns=10")
    #netlister.add(".option", "savecurrents")

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

@public
class Pmos(Mos, generic_mos.Pmos):
    model_name = "sg13_lv_pmos"

@public
class Inv(Cell):
    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        # Define pins for the inverter
        s.vdd = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)
        s.vss = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.a = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=Orientation.West)
        s.y = Pin(pos=Vec2R(4, 2), pintype=PinType.Out, align=Orientation.East)

        # Draw the inverter symbol
        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1, 2)])  # Input line
        s % SymbolPoly(vertices=[Vec2R(3.25, 2), Vec2R(4, 2)])  # Output line
        s % SymbolPoly(vertices=[Vec2R(1, 1), Vec2R(1, 3), Vec2R(2.75, 2), Vec2R(1, 1)])  # Triangle
        s % SymbolArc(pos=Vec2R(3, 2), radius=R(0.25))  # Output bubble

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)

        return s

    @generate
    def schematic(self) -> Schematic:
        s = Schematic(cell=self, symbol=self.symbol)
        s.a = Net(pin=self.symbol.a)
        s.y = Net(pin=self.symbol.y)
        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)

        # IHP130 specific parameters - using values from the old code
        nmos_params = {
            "l": R("0.13u"),
            "w": R("0.495u"),
            "m": 1,
            "ng": 1,
        }
        nmos = Nmos(**nmos_params).symbol

        pmos_params = {
            "l": R("0.13u"),
            "w": R("0.99u"),
            "m": 1,
            "ng": 1,
        }
        pmos = Pmos(**pmos_params).symbol

        s.pd = SchemInstance(nmos.portmap(s=s.vss, b=s.vss, g=s.a, d=s.y), pos=Vec2R(3, 2))
        s.pu = SchemInstance(pmos.portmap(s=s.vdd, b=s.vdd, g=s.a, d=s.y), pos=Vec2R(3, 8))

        s.vdd % SchemPort(pos=Vec2R(2, 13), align=Orientation.East, ref=self.symbol.vdd)
        s.vss % SchemPort(pos=Vec2R(2, 1), align=Orientation.East, ref=self.symbol.vss)
        s.a % SchemPort(pos=Vec2R(1, 7), align=Orientation.East, ref=self.symbol.a)
        s.y % SchemPort(pos=Vec2R(9, 7), align=Orientation.West, ref=self.symbol.y)

        s.vss % SchemWire([Vec2R(2, 1), Vec2R(5, 1), Vec2R(8, 1), Vec2R(8, 4), Vec2R(7, 4)])
        s.vss % SchemWire([Vec2R(5, 1), s.pd.pos + nmos.s.pos])
        s.vdd % SchemWire([Vec2R(2, 13), Vec2R(5, 13), Vec2R(8, 13), Vec2R(8, 10), Vec2R(7, 10)])
        s.vdd % SchemWire([Vec2R(5, 13), s.pu.pos + pmos.s.pos])
        s.a % SchemWire([Vec2R(3, 4), Vec2R(2, 4), Vec2R(2, 7), Vec2R(2, 10), Vec2R(3, 10)])
        s.a % SchemWire([Vec2R(1, 7), Vec2R(2, 7)])
        s.y % SchemWire([Vec2R(5, 6), Vec2R(5, 7), Vec2R(5, 8)])
        s.y % SchemWire([Vec2R(5, 7), Vec2R(9, 7)])

        s.outline = Rect4R(lx=0, ly=1, ux=10, uy=13)

        helpers.schem_check(s, add_conn_points=True)
        return s
