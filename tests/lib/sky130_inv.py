# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *
from ordec.lib import sky130

class Inv(Cell):
    variant = Parameter(str, default='clean')

    @viewgen_noctx
    def symbol(self):
        s = Symbol(cell=self)

        s.vdd = Pin(pos=(2, 4), pintype=PinType.Inout, align=North)
        s.vss = Pin(pos=(2, 0), pintype=PinType.Inout, align=South)
        s.a = Pin(pos=(0, 2), pintype=PinType.In, align=West)
        s.y = Pin(pos=(4, 2), pintype=PinType.Out, align=East)

        s % SymbolPoly(vertices=[(0, 2), (1, 2)])
        s % SymbolPoly(vertices=[(3.25, 2), (4, 2)])
        s % SymbolPoly(vertices=[(1, 1), (1, 3), (2.75, 2), (1, 1)])
        s % SymbolArc(pos=(3, 2), radius=R(0.25))

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    @viewgen_noctx
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol, outline=(0,0,10,14))

        s.a = Net(pin=self.symbol.a)
        s.y = Net(pin=self.symbol.y)
        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)

        nmos = sky130.Nmos(w="1u", l="150n").symbol
        pmos = sky130.Pmos(w="1u", l="150n").symbol

        s.pd = SchemInstance(nmos.portmap(s=s.vss, b=s.vss, g=s.a, d=s.y), pos=(3, 2))
        s.pu = SchemInstance(pmos.portmap(s=s.vdd, b=s.vdd, g=s.a, d=s.y), pos=(3, 8))

        s.vdd % SchemPort(pos=(2, 13), align=East)
        s.vss % SchemPort(pos=(2, 1), align=East)
        s.a % SchemPort(pos=(1, 7), align=East)
        s.y % SchemPort(pos=(9, 7), align=West)

        s.auto_wire()

        return s

    @viewgen_noctx
    def layout(self):
        layers = sky130.SKY130().layers
        l = Layout(ref_layers=layers, cell=self, symbol=self.symbol)
        s = Solver(l)

        ntap = sky130.Ntap(l="0.7u", w="0.7u")
        ptap = sky130.Ptap(l="0.7u", w="0.7u")
        nmos = sky130.Nmos(w="1u", l="150n")
        pmos = sky130.Pmos(w="1u", l="150n")

        l.ntap = LayoutInstance(ref=ntap.layout)
        l.ptap = LayoutInstance(ref=ptap.layout)
        l.nmos = LayoutInstance(ref=nmos.layout)
        l.pmos = LayoutInstance(ref=pmos.layout)

        s.constrain(l.nmos.pos == (0, 0))
        s.constrain(l.pmos.pos.y == l.nmos.pos.y + 2500)

        l.m1_vdd = LayoutRect(layer=layers.met1)
        s.constrain(l.m1_vdd.southwest == l.ntap.m1.southeast)
        s.constrain(l.m1_vdd.southeast == l.pmos.sd[0].southwest)

        s.constrain(l.m1_vdd.ux == l.pmos.sd[0].lx)
        s.constrain(l.m1_vdd.height == (100 if self.variant=='thin_m1' else 170))
        s.constrain(l.m1_vdd.width == 800)

        l.m1_vss = LayoutRect(layer=layers.met1)
        s.constrain(l.m1_vss.southwest == l.ptap.m1.southeast)
        s.constrain(l.m1_vss.southeast == l.nmos.sd[0].southwest)
        s.constrain(l.m1_vss.height == (100 if self.variant=='thin_m1' else 170))
        s.constrain(l.m1_vss.width == 800)

        if self.variant=="vss_vdd_pins_swapped":
            l.m1_vss % LayoutPin(pin=self.symbol.vdd)
            l.m1_vdd % LayoutPin(pin=self.symbol.vss)
        else:
            l.m1_vss % LayoutPin(pin=self.symbol.vss)
            l.m1_vdd % LayoutPin(pin=self.symbol.vdd)

        if self.variant!="missing_y":
            l.m1_y = LayoutRect(layer=layers.met1)
            s.constrain(l.m1_y.south == l.nmos.sd[1].north)
            s.constrain(l.m1_y.north == l.pmos.sd[1].south)
            s.constrain(l.m1_y.width == 230)
            l.m1_y % LayoutPin(pin=self.symbol.y)

        l.nwell = LayoutRect(layer=layers.nwell)
        s.constrain(l.nwell.contains(l.ntap.nwell.rect))
        s.constrain(l.nwell.contains(l.pmos.nwell.rect))

        # Gate connection: poly bar between the fingers, with a contact pad
        # on field poly (licon + npc + li1 + mcon + met1 stack).
        l.polybar = LayoutRect(layer=layers.poly)
        s.constrain(l.polybar.south == l.nmos.poly[0].north)
        s.constrain(l.polybar.north == l.pmos.poly[0].south)
        s.constrain(l.polybar.width == l.pmos.poly[0].width)

        l.polyext = LayoutRect(layer=layers.poly)
        s.constrain(l.polyext.size == (500, 500))
        s.constrain(l.polyext.east == l.polybar.west)

        l.polycont = LayoutRect(layer=layers.licon1)
        s.constrain(l.polycont.size == (170, 170))
        s.constrain(l.polycont.center == l.polyext.center)

        # licon.15/licon.18: poly licons need an npc cover:
        l.npc = LayoutRect(layer=layers.npc)
        s.constrain(l.npc.size == (370, 370))
        s.constrain(l.npc.center == l.polycont.center)

        # li1 landing for the mcon, stacked over the licon:
        l.li_a = LayoutRect(layer=layers.li1)
        s.constrain(l.li_a.x_extent == l.polycont.x_extent)
        s.constrain(l.li_a.cy == l.polycont.cy)
        s.constrain(l.li_a.height == 330)

        l.mcon_a = LayoutRect(layer=layers.mcon)
        s.constrain(l.mcon_a.size == (170, 170))
        s.constrain(l.mcon_a.center == l.polycont.center)

        l.m1_a = LayoutRect(layer=layers.met1)
        s.constrain(l.m1_a.y_extent == l.li_a.y_extent)
        s.constrain(l.m1_a.ux == l.polycont.ux + 200)
        s.constrain(l.m1_a.width == 1500)
        l.m1_a % LayoutPin(pin=self.symbol.a)

        s.solve()
        return l
