# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Load the IHP SG13G2 standard cell library into a single ExtLibrary.

The standard cells are a component *on top of* the IHP130 PDK (not part of it),
so all wiring lives here in the example rather than in ordec.lib.ihp130:

- symbols  <- LEF   (read_lef, provides correct pin directions)
- layouts  <- GDS   (read_gds)
- schematics <- SPICE (read_spice, transistor-level netlists)

Run with the integrated web server from this directory::

    ordec -bm stdcells

This exposes the symbol, schematic and layout of every standard cell, plus an
inverter voltage-transfer-curve testbench and DRC/LVS reports defined below.
"""

from ordec.core import *
from ordec.extlibrary import ExtLibrary
from ordec.lib import ihp130
from ordec.lib.base import Vdc, Gnd, NoConn

stdcell_root = ihp130.pdk().root / "libs.ref/sg13g2_stdcell"

# Build the combined library. Order matters: read_lef first so its symbols (with
# proper pin directions) win over the auto-generated symbols from read_spice.
extlib = ExtLibrary()
extlib.read_lef(stdcell_root / "lef/sg13g2_stdcell.lef")
extlib.read_gds(stdcell_root / "gds/sg13g2_stdcell.gds", ihp130.SG13G2().layers)
extlib.read_spice(stdcell_root / "spice/sg13g2_stdcell.spice", device_map=ihp130.device_map)

inv = extlib["sg13g2_inv_1"]

class InvTb(Cell):
    """DC voltage-transfer-curve testbench for the inv standard cell."""

    @generate
    def schematic(self) -> Schematic:
        s = Schematic(cell=self)

        s.vdd = Net()
        s.vss = Net()
        s.i = Net()
        s.o = Net()

        s.i_inv = SchemInstance(
            inv.symbol.portmap(VDD=s.vdd, VSS=s.vss, A=s.i, Y=s.o), pos=Vec2R(11, 9)
        )
        s.i_nc = SchemInstance(NoConn().symbol.portmap(a=s.o), pos=Vec2R(20, 9))
        s.i_gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(11, 0))
        s.i_vdd = SchemInstance(
            Vdc(dc=1.2).symbol.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 6)
        )
        s.i_in = SchemInstance(
            Vdc(dc=0).symbol.portmap(m=s.vss, p=s.i), pos=Vec2R(5, 6)
        )

        s.outline = Rect4R(lx=0, ly=0, ux=20, uy=14)
        s.check(add_conn_points=True, add_terminal_taps=True)
        return s

    @generate
    def sim_dc(self) -> SimHierarchy:
        h = SimHierarchy.from_schematic(self.schematic)
        h.simulate().dc_sweep(self.schematic.i_in, 0, self.schematic.i_vdd.cell.dc, 100)
        return h

    @generate
    def report_vtc(self) -> Report:
        h = self.sim_dc
        r = Report()
        r.markdown(
            f"# Inverter voltage transfer curve\n"
            "Input swept from 0 V to the supply; output is the inverter response."
        )
        r.plot2d(
            x=list(h.i.voltage),
            series={"Vout": list(h.o.voltage)},
            xlabel="Vin (V)",
            ylabel="Vout (V)",
            height=300,
        )
        return r


@generate_func
def inv_drc() -> DrcReport:
    return ihp130.run_drc(inv.layout, variant="minimal")


@generate_func
def inv_lvs() -> LvsReport:
    # TODO: Not working yet due to name mismatch!

    return ihp130.run_lvs(inv.layout, inv.symbol, return_report=True)
