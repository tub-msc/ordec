from ordec.core import *
from ordec.lib import ihp130
from ordec.schematic.routing import schematic_routing
from ordec.schematic.netlister import Netlister
from ordec.layout import klayout
from ordec.layout.gds_out import write_gds
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

    @generate
    def layout(self):
        layers = ihp130.SG13G2().layers
        l = Layout(ref_layers=layers, cell=self)

        ntap = ihp130.Ntap(l="1u", w="1u")
        ptap = ihp130.Ptap(l="1u", w="1u")
        nmos = ihp130.Nmos(w="1u", l="130n")
        pmos = ihp130.Pmos(w="1u", l="130n")

        l % LayoutInstance(ref=ntap.layout, pos=(0, 2500))
        l % LayoutInstance(ref=ptap.layout, pos=(0, -50))
        l % LayoutInstance(ref=nmos.layout, pos=(1500, -80))
        l % LayoutInstance(ref=pmos.layout, pos=(1500, 2470))

        l % LayoutRect(layer=layers.Metal1, rect=(800, 2650, 1570, 2810))
        l % LayoutRect(layer=layers.Metal1.pin, rect=(800, 2650, 1570, 2810))
        l % LayoutLabel(layer=layers.Metal1.pin, pos=(850, 2700), text="vdd")
         
        l % LayoutRect(layer=layers.Metal1, rect=(800, 100, 1570, 260))
        l % LayoutRect(layer=layers.Metal1.pin, rect=(800, 100, 1570, 260))
        l % LayoutLabel(layer=layers.Metal1.pin, pos=(850, 150), text="vss")

        #l % LayoutRect(layer=layers.Metal1, rect=(2140, 1100, 2300, 2650))
        #l % LayoutRect(layer=layers.Metal1.pin, rect=(2140, 1100, 2300, 2650))
        #l % LayoutLabel(layer=layers.Metal1.pin, pos=(2190, 1150), text="y")
        
        l % LayoutRect(layer=layers.NWell, rect=(-240, 2250, 2680, 4115))

        l % LayoutRect(layer=layers.GatPoly, rect=(1870, 1200, 2000, 2470))
        l % LayoutRect(layer=layers.GatPoly, rect=(1500, 1400, 2000, 1850))
        l % LayoutRect(layer=layers.Cont, rect=(1600, 1500, 1760, 1660))
        l % LayoutRect(layer=layers.Metal1, rect=(500, 1500, 1900, 1660))

        l % LayoutRect(layer=layers.Metal1.pin, rect=(500, 1500, 1900, 1660))
        l % LayoutLabel(layer=layers.Metal1.pin, pos=(700,1580), text="a")

        return l

if __name__ == "__main__":
    layout = MyInv().layout
    #with open("out.gds", "wb") as f:
    #    write_gds(layout, f)
    
    #r=ihp130.run_drc(layout)
    #print(r.pretty())

    ret=ihp130.run_lvs(layout, MyInv().schematic, use_tempdir=False)
    print(ret)
