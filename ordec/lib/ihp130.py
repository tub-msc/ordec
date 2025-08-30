# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
import logging
from pathlib import Path
from public import public

from ..core import *
from .. import helpers
from ..ord1.implicit_processing import schematic_routing
from ..sim2.ngspice_common import NgspiceError
from . import generic_mos

def _get_ihp_pdk_path():
    """Helper function to determine the IHP PDK path."""
    env_var_path = os.getenv("ORDEC_PDK_IHP_SG13G2")
    if env_var_path:
        return Path(env_var_path)
    else:
        _MODULE_DIR = Path(__file__).parent
        _PROJECT_ROOT = _MODULE_DIR.parent.parent
        return _PROJECT_ROOT / "ihp-sg13g2"

_IHP_PDK_PATH = _get_ihp_pdk_path()
_IHP_SG13G2_RELATIVE_MODEL_PATH = "libs.tech/ngspice/models/cornerMOSlv.lib"
_IHP_SG13G2_MODEL_FULL_PATH = (_IHP_PDK_PATH / _IHP_SG13G2_RELATIVE_MODEL_PATH).resolve()

if not _IHP_SG13G2_MODEL_FULL_PATH.is_file():
    print(f"WARNING: IHP SG13G2 model file not found at expected path: {_IHP_SG13G2_MODEL_FULL_PATH}")
    print(f"Ensure the files exist, or set the environmental variable ORDEC_PDK_IHP_SG13G2")

def setup_ihp_sg13g2_commands(sim):
    """Execute ngspice commands directly based on .spiceinit content"""
    pdk_path = _IHP_PDK_PATH

    osdi_path = pdk_path / "libs.tech/ngspice/osdi"
    models_path = Path(pdk_path) / "libs.tech/ngspice/models"
    stdcell_path = Path(pdk_path) / "libs.ref/sg13g2_stdcell/spice"
    io_path = Path(pdk_path) / "libs.ref/sg13g2_io/spice"

    # Set ngspice behavior (from .spiceinit)
    try:
        sim.command("set ngbehavior=hsa")
        sim.command("set noinit")
    except NgspiceError as e:
        logging.warning(f"Failed to set ngspice behavior: {e}")

    # Set sourcepath (equivalent to setcs sourcepath commands in .spiceinit)
    try:
        cmd = f"setcs sourcepath = ( {models_path} {stdcell_path} {io_path} )"
        sim.command(cmd)
    except NgspiceError as e:
        logging.warning(f"Failed to set sourcepath: {e}")

    # Load OSDI models using absolute paths resolved in Python
    psp103_path = osdi_path / "psp103_nqs.osdi"
    if psp103_path.exists():
        try:
            sim.command(f"osdi '{psp103_path.resolve()}'")
        except NgspiceError as e:
            logging.warning(f"Failed to load OSDI model {psp103_path.resolve()}: {e}")

    r3_cmc_path = osdi_path / "r3_cmc.osdi"
    if r3_cmc_path.exists():
        try:
            sim.command(f"osdi '{r3_cmc_path.resolve()}'")
        except NgspiceError as e:
            logging.warning(f"Failed to load OSDI model {r3_cmc_path.resolve()}: {e}")

    mosvar_path = osdi_path / "mosvar.osdi"
    if mosvar_path.exists():
        try:
            sim.command(f"osdi '{mosvar_path.resolve()}'")
        except NgspiceError as e:
            logging.warning(f"Failed to load OSDI model {mosvar_path.resolve()}: {e}")

def setup_ihp_sg13g2(netlister):
    # Register simulation setup commands
    netlister.require_sim_setup(setup_ihp_sg13g2_commands)

    # Load corner library with typical corner
    netlister.add(".lib", f"\"{_IHP_SG13G2_MODEL_FULL_PATH}\" mos_tt")

    # Add options from .spiceinit
    netlister.add(".option", "tnom=28")
    netlister.add(".option", "warn=1")
    netlister.add(".option", "maxwarns=10")
    netlister.add(".option", "savecurrents")

class Mos(Cell):
    l = Parameter(R)  #: Length
    w = Parameter(R)  #: Width
    m = Parameter(int, default=1)  #: Multiplier (number of devices in parallel)
    ng = Parameter(int, default=1)  #: Number of gate fingers

    def netlist_ngspice(self, netlister, inst, schematic):
        netlister.require_setup(setup_ihp_sg13g2)
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

# The standard HighlevelSim now supports simulation setup hooks through netlister.require_sim_setup()
# No need for custom HighlevelSim class or monkey-patching
