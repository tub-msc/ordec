# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests basic DRC + LVS in IHP130.
"""

from ordec.core import *
from ordec.lib import ihp130
from ordec.schematic.routing import schematic_routing

class Inv(Cell):
    lvs_variant = Parameter(str, default='clean')

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

        s.vdd % SchemPort(pos=(2, 13), align=Orientation.East, ref=self.symbol.vdd)
        s.vss % SchemPort(pos=(2, 1), align=Orientation.East, ref=self.symbol.vss)
        s.a % SchemPort(pos=(1, 7), align=Orientation.East, ref=self.symbol.a)
        s.y % SchemPort(pos=(9, 7), align=Orientation.West, ref=self.symbol.y)
        
        schematic_routing(s)

        return s

    @generate
    def layout(self):
        layers = ihp130.SG13G2().layers
        l = Layout(ref_layers=layers, cell=self)

        ntap = ihp130.Ntap(l="0.7u", w="0.7u")
        ptap = ihp130.Ptap(l="0.7u", w="0.7u")
        nmos = ihp130.Nmos(w="1u", l="130n")
        pmos = ihp130.Pmos(w="1u", l="130n")

        l.ntap =  LayoutInstance(ref=ntap.layout, pos=(200, 2600))
        l.ptap =  LayoutInstance(ref=ptap.layout, pos=(200, 50))
        l.nmos =  LayoutInstance(ref=nmos.layout, pos=(1500, -80))
        l.pmos =  LayoutInstance(ref=pmos.layout, pos=(1500, 2470))

        # Example use of the new LayoutInstanceSubcursor:
        l % LayoutRect(layer=layers.Metal1, rect=(l.ntap.m1.rect.ux, l.ntap.m1.rect.ly, l.pmos.sd[0].rect.lx, l.ntap.m1.rect.ly + 160))

        l % LayoutRect(layer=layers.Metal1.pin, rect=(800, 2650, 1570, 2810))
        l % LayoutLabel(layer=layers.Metal1.pin, pos=(850, 2700), text="vdd")
         
        l % LayoutRect(layer=layers.Metal1, rect=(800, 100, 1570, 260))
        l % LayoutRect(layer=layers.Metal1.pin, rect=(800, 100, 1570, 260))
        l % LayoutLabel(layer=layers.Metal1.pin, pos=(850, 150), text="vss")

        if self.lvs_variant!="missing_y":
            l % LayoutRect(layer=layers.Metal1, rect=(2080, 1100, 2240, 2650))
            l % LayoutRect(layer=layers.Metal1.pin, rect=(2080, 1100, 2240, 2650))
            l % LayoutLabel(layer=layers.Metal1.pin, pos=(2190, 1150), text="y")
        
        l % LayoutRect(layer=layers.NWell, rect=(-240, 2250, 2680, 4115))

        l % LayoutRect(layer=layers.GatPoly, rect=(1840, 1200, 1970, 2470))
        l % LayoutRect(layer=layers.GatPoly, rect=(1500, 1400, 1970, 1850))
        l % LayoutRect(layer=layers.Cont, rect=(1600, 1500, 1760, 1660))
        l % LayoutRect(layer=layers.Metal1, rect=(500, 1500, 1900, 1660))

        l % LayoutRect(layer=layers.Metal1.pin, rect=(500, 1500, 1900, 1660))
        l % LayoutLabel(layer=layers.Metal1.pin, pos=(700,1580), text="a")

        return l

def test_lvs_clean():
    assert ihp130.run_lvs(Inv().layout, Inv().schematic)

def test_lvs_missing_y():
    c = Inv(lvs_variant="missing_y")
    assert not ihp130.run_lvs(c.layout, c.schematic)

def test_drc_clean():
    res = ihp130.run_drc(Inv().layout)

    assert res.summary() == {
        'AFil.g/g1': 1,
        'AFil.g2/g3': 1,
        'GFil.g': 1,
        'M1.j/k': 1,
        'M2.j/k': 1,
        'M3.j/k': 1,
        'M4.j/k': 1,
        'M5.j/k': 1,
        'M1Fil.h/k': 1,
        'M2Fil.h/k': 1,
        'M3Fil.h/k': 1,
        'M4Fil.h/k': 1,
        'M5Fil.h/k': 1,
        'TM1.c/d': 1,
        'TM2.c/d': 1
    }

if __name__=="__main__":
    # Generate GDS + schematic netlist for manual inspection:
    ihp130.run_lvs(Inv().layout, Inv().schematic, use_tempdir=False)
