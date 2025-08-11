# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec import (
    Cell,
    Vec2R,
    Rect4R,
    Rational as R,
    SchemInstance,
    Net,
    Schematic,
    generate,
)
from ordec.lib import (
    Vdc,
    Res,
    Gnd,
)
from ordec import helpers
from ordec.lib.ihp130 import Nmos, Pmos, Inv


class TBSimpleInv(Cell):
    """Simple inverter testbench for IHP130"""
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.gnd = Net()
        s.input_node = Net()
        s.output_node = Net()

        # Simple DC voltage source
        vdc_inst = Vdc(dc=R("1.8")).symbol
        s.vdc = SchemInstance(
            vdc_inst.portmap(p=s.vdd, m=s.gnd),
            pos=Vec2R(2, 8),
        )

        # IHP130 Inverter
        inv = Inv().symbol
        s.inv = SchemInstance(
            inv.portmap(
                a=s.input_node,
                vdd=s.vdd,
                vss=s.gnd,
                y=s.output_node,
            ),
            pos=Vec2R(8, 5),
        )

        # Ground reference
        gnd_inst = Gnd().symbol
        s.gnd_inst = SchemInstance(
            gnd_inst.portmap(p=s.gnd),
            pos=Vec2R(12, 12),
        )
        
        s.outline = Rect4R(lx=0, ly=2, ux=20, uy=14)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)
        return s


class TBRingOscIhp130(Cell):
    """3-stage ring oscillator using IHP130 inverters"""
    @generate
    def schematic(self):
        s = Schematic(cell=self)

        s.vdd = Net()
        s.gnd = Net()
        s.y0 = Net()
        s.y1 = Net()
        s.y2 = Net()

        # Power supply
        vdc_inst = Vdc(dc=R("1.8")).symbol
        s.vdc = SchemInstance(
            vdc_inst.portmap(p=s.vdd, m=s.gnd),
            pos=Vec2R(2, 12),
        )

        # Three IHP130 inverters in a ring
        inv = Inv().symbol
        s.inv0 = SchemInstance(
            inv.portmap(vdd=s.vdd, vss=s.gnd, a=s.y2, y=s.y0),
            pos=Vec2R(6, 4),
        )
        s.inv1 = SchemInstance(
            inv.portmap(vdd=s.vdd, vss=s.gnd, a=s.y0, y=s.y1),
            pos=Vec2R(12, 4),
        )
        s.inv2 = SchemInstance(
            inv.portmap(vdd=s.vdd, vss=s.gnd, a=s.y1, y=s.y2),
            pos=Vec2R(18, 4),
        )

        # Ring connection: inv0 -> inv1 -> inv2 -> inv0

        # Ground reference
        gnd_inst = Gnd().symbol
        s.gnd_inst = SchemInstance(
            gnd_inst.portmap(p=s.gnd),
            pos=Vec2R(24, 12),
        )
        
        s.outline = Rect4R(lx=0, ly=2, ux=26, uy=14)

        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)
        return s