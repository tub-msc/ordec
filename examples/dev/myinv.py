from ordec.core import *
from ordec.lib import ihp130
from ordec.schematic.routing import schematic_routing
from ordec.schematic.netlister import Netlister
from ordec.layout import klayout
from pathlib import Path

class MyInv(Cell):
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

@generate_func
def layout_test():
    return ihp130.Nmos(l="130n", w="10u", ng=10).layout
