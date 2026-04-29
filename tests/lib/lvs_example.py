# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
LVS example with intentional mismatch for testing the LVS viewer.

Uses the working Inv cell from ihp130_inv but with a modified PMOS width
in the layout to create a parameter mismatch.
"""

from ordec.core import *
from ordec.core.schema import LvsReport
from ordec.lib import ihp130
from ordec.lib.ihp130 import run_lvs
from .ihp130_inv import Inv


class LvsTestInv(Inv):
    """Inverter with intentional LVS mismatch (PMOS W parameter).

    Inherits from the working Inv but overrides the layout to use
    W=1.2u for PMOS instead of W=1u.
    """

    @generate
    def layout(self):
        """Layout with W=1.2u for PMOS (mismatch vs schematic W=1u)."""
        layers = ihp130.SG13G2().layers
        l = Layout(ref_layers=layers, cell=self, symbol=self.symbol)
        s = Solver(l)

        ntap = ihp130.Ntap(l="0.7u", w="0.7u")
        ptap = ihp130.Ptap(l="0.7u", w="0.7u")
        nmos = ihp130.Nmos(w="1u", l="130n")
        pmos = ihp130.Pmos(w="1.2u", l="130n")  # MISMATCH: schematic has W=1u

        l.ntap = LayoutInstance(ref=ntap.layout)
        l.ptap = LayoutInstance(ref=ptap.layout)
        l.nmos = LayoutInstance(ref=nmos.layout)
        l.pmos = LayoutInstance(ref=pmos.layout)

        s.constrain(l.nmos.pos == (0, 0))
        s.constrain(l.pmos.pos.y == l.nmos.pos.y + 2500)

        l.m1_vdd = LayoutRect(layer=layers.Metal1)
        s.constrain(l.m1_vdd.southwest == l.ntap.m1.southeast)
        s.constrain(l.m1_vdd.southeast == l.pmos.sd[0].southwest)
        s.constrain(l.m1_vdd.ux == l.pmos.sd[0].lx)
        s.constrain(l.m1_vdd.height == 160)
        s.constrain(l.m1_vdd.width == 800)

        l.m1_vss = LayoutRect(layer=layers.Metal1)
        s.constrain(l.m1_vss.southwest == l.ptap.m1.southeast)
        s.constrain(l.m1_vss.southeast == l.nmos.sd[0].southwest)
        s.constrain(l.m1_vss.height == 160)
        s.constrain(l.m1_vss.width == 800)

        l.m1_vss % LayoutPin(pin=self.symbol.vss)
        l.m1_vdd % LayoutPin(pin=self.symbol.vdd)

        l.m1_y = LayoutRect(layer=layers.Metal1)
        s.constrain(l.m1_y.south == l.nmos.sd[1].north)
        s.constrain(l.m1_y.north == l.pmos.sd[1].south)
        s.constrain(l.m1_y.width == 160)
        l.m1_y % LayoutPin(pin=self.symbol.y)

        l.nwell = LayoutRect(layer=layers.NWell)
        s.constrain(l.nwell.contains(l.ntap.nwell.rect))
        s.constrain(l.nwell.contains(l.pmos.nwell.rect))

        l.polybar = LayoutRect(layer=layers.GatPoly)
        s.constrain(l.polybar.south == l.nmos.poly[0].north)
        s.constrain(l.polybar.north == l.pmos.poly[0].south)
        s.constrain(l.polybar.width == l.pmos.poly[0].width)

        l.polyext = LayoutRect(layer=layers.GatPoly)
        s.constrain(l.polyext.size == (500, 500))
        s.constrain(l.polyext.east == l.polybar.west)

        l.polycont = LayoutRect(layer=layers.Cont)
        s.constrain(l.polycont.size == (160, 160))
        s.constrain(l.polycont.center == l.polyext.center)

        l.m1_a = LayoutRect(layer=layers.Metal1)
        s.constrain(l.m1_a.y_extent == l.polycont.y_extent)
        s.constrain(l.m1_a.ux == l.polycont.ux + 200)
        s.constrain(l.m1_a.width == 1500)
        l.m1_a % LayoutPin(pin=self.symbol.a)

        s.solve()
        return l


@generate_func
def layout() -> Layout:
    """Layout with intentional LVS mismatch."""
    return LvsTestInv().layout


@generate_func
def schematic() -> Schematic:
    """Reference schematic for LVS comparison."""
    return LvsTestInv().schematic


@generate_func
def lvs_report() -> LvsReport:
    """Run LVS on layout with intentional mismatch.

    Expected error:
    - Parameter mismatch: PMOS W=1.2u in layout vs W=1u in schematic
    """
    inv = LvsTestInv()
    return run_lvs(inv.layout, inv.symbol, return_report=True)
