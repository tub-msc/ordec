# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *
from ordec.lib import ihp130
from ordec.schematic.routing import schematic_routing

class Inv(Cell):
    variant = Parameter(str, default='clean')

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vdd = Pin(pos=(2, 4), pintype=PinType.Inout, align=Orientation.North)
        s.vss = Pin(pos=(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.a = Pin(pos=(0, 2), pintype=PinType.In, align=Orientation.West)
        s.y = Pin(pos=(4, 2), pintype=PinType.Out, align=Orientation.East)

        s % SymbolPoly(vertices=[(0, 2), (1, 2)])
        s % SymbolPoly(vertices=[(3.25, 2), (4, 2)])
        s % SymbolPoly(vertices=[(1, 1), (1, 3), (2.75, 2), (1, 1)])
        s % SymbolArc(pos=(3, 2), radius=R(0.25))

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol, outline=(0,0,10,14))

        s.a = Net(pin=self.symbol.a)
        s.y = Net(pin=self.symbol.y)
        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)

        nmos = ihp130.Nmos(w="1u", l="130n").symbol
        pmos = ihp130.Pmos(w="1u", l="130n").symbol

        s.pd = SchemInstance(nmos.portmap(s=s.vss, b=s.vss, g=s.a, d=s.y), pos=(3, 2))
        s.pu = SchemInstance(pmos.portmap(s=s.vdd, b=s.vdd, g=s.a, d=s.y), pos=(3, 8))

        s.vdd % SchemPort(pos=(2, 13), align=Orientation.East)
        s.vss % SchemPort(pos=(2, 1), align=Orientation.East)
        s.a % SchemPort(pos=(1, 7), align=Orientation.East)
        s.y % SchemPort(pos=(9, 7), align=Orientation.West)
        
        schematic_routing(s)

        return s

    @generate
    def layout(self):
        layers = ihp130.SG13G2().layers
        l = Layout(ref_layers=layers, cell=self, symbol=self.symbol)
        s = Solver(l)

        ntap = ihp130.Ntap(l="0.7u", w="0.7u")
        ptap = ihp130.Ptap(l="0.7u", w="0.7u")
        nmos = ihp130.Nmos(w="1u", l="130n")
        pmos = ihp130.Pmos(w="1u", l="130n")

        l.ntap =  LayoutInstance(ref=ntap.layout)
        l.ptap =  LayoutInstance(ref=ptap.layout)
        l.nmos =  LayoutInstance(ref=nmos.layout)
        l.pmos =  LayoutInstance(ref=pmos.layout)

        s.constrain(l.nmos.pos == (0, 0))
        s.constrain(l.pmos.pos.y == l.nmos.pos.y + 2500)

        # Example use of the new LayoutInstanceSubcursor:
        l.m1_vdd = LayoutRect(layer=layers.Metal1)
        s.constrain(l.m1_vdd.rect.southwest == l.ntap.m1.rect.southeast)
        s.constrain(l.m1_vdd.rect.southeast == l.pmos.sd[0].rect.southwest)

        s.constrain(l.m1_vdd.rect.ux == l.pmos.sd[0].rect.lx)
        s.constrain(l.m1_vdd.rect.height == (100 if self.variant=='thin_m1' else 160))
        s.constrain(l.m1_vdd.rect.width == 800)

        l.m1_vss = LayoutRect(layer=layers.Metal1)
        s.constrain(l.m1_vss.rect.southwest == l.ptap.m1.rect.southeast)
        s.constrain(l.m1_vss.rect.southeast == l.nmos.sd[0].rect.southwest)
        s.constrain(l.m1_vss.rect.height == (100 if self.variant=='thin_m1' else 160))
        s.constrain(l.m1_vss.rect.width == 800)

        if self.variant=="vss_vdd_pins_swapped":
            l.m1_vss % LayoutPin(pin=self.symbol.vdd)
            l.m1_vdd % LayoutPin(pin=self.symbol.vss)
        else:
            l.m1_vss % LayoutPin(pin=self.symbol.vss)
            l.m1_vdd % LayoutPin(pin=self.symbol.vdd)

        if self.variant!="missing_y":
            l.m1_y = LayoutRect(layer=layers.Metal1)
            s.constrain(l.m1_y.rect.south == l.nmos.sd[1].rect.north)
            s.constrain(l.m1_y.rect.north == l.pmos.sd[1].rect.south)
            s.constrain(l.m1_y.rect.width == 160)
            l.m1_y % LayoutPin(pin=self.symbol.y)
        
        l.nwell = LayoutRect(layer=layers.NWell)
        s.constrain(l.nwell.rect.contains(l.ntap.nwell.rect))
        s.constrain(l.nwell.rect.contains(l.pmos.nwell.rect))

        l.polybar = LayoutRect(layer=layers.GatPoly)
        s.constrain(l.polybar.rect.south == l.nmos.poly[0].rect.north)
        s.constrain(l.polybar.rect.north == l.pmos.poly[0].rect.south)
        s.constrain(l.polybar.rect.width == l.pmos.poly[0].rect.width)

        l.polyext = LayoutRect(layer=layers.GatPoly)
        s.constrain(l.polyext.rect.size == (500, 500))
        s.constrain(l.polyext.rect.east == l.polybar.rect.west)

        l.polycont = LayoutRect(layer=layers.Cont)
        s.constrain(l.polycont.rect.size == (160, 160))
        s.constrain(l.polycont.rect.center == l.polyext.rect.center)

        l.m1_a = LayoutRect(layer=layers.Metal1)
        s.constrain(l.m1_a.rect.y_extent == l.polycont.rect.y_extent)
        s.constrain(l.m1_a.rect.ux == l.polycont.rect.ux + 200)
        s.constrain(l.m1_a.rect.width == 1500)
        l.m1_a % LayoutPin(pin=self.symbol.a)

        s.solve()
        return l
