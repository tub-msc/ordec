# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *
from ordec.lib import ihp130


_RESISTORS = {
    "rsil": ihp130.Rsil,
    "rppd": ihp130.Rppd,
    "rhigh": ihp130.Rhigh,
}


class ResDevice(Cell):
    kind = Parameter(str, default="rhigh")
    l = Parameter(R, default=R("0.96u"))
    w = Parameter(R, default=R("0.50u"))
    b = Parameter(int, default=0)
    ps = Parameter(R, default=R("0.18u"))

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.p = Pin(pos=(2, 4), pintype=PinType.Inout, align=North)
        s.m = Pin(pos=(2, 0), pintype=PinType.Inout, align=South)

        s % SymbolPoly(vertices=[(2, 0), (2, 4)])
        s % SymbolPoly(vertices=[(1.2, 1.2), (2.8, 1.2), (2.8, 2.8), (1.2, 2.8), (1.2, 1.2)])
        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol, outline=(0, 0, 10, 12))

        s.p = Net(pin=self.symbol.p)
        s.m = Net(pin=self.symbol.m)
        s.bn = Net()

        dev = _RESISTORS[self.kind](l=self.l, w=self.w, b=self.b, ps=self.ps).symbol
        s.r = SchemInstance(dev.portmap(p=s.p, m=s.m, bn=s.bn), pos=(3, 4))

        s.p % SchemPort(pos=(2, 11), align=East)
        s.m % SchemPort(pos=(2, 1), align=East)

        s.auto_wire()
        return s

    @generate
    def layout(self):
        layers = ihp130.SG13G2().layers
        l = Layout(ref_layers=layers, cell=self, symbol=self.symbol)
        s = Solver(l)

        dev = _RESISTORS[self.kind](l=self.l, w=self.w, b=self.b, ps=self.ps)
        l.dev = LayoutInstance(ref=dev.layout)
        s.constrain(l.dev.pos == (0, 0))

        l.pin_p = LayoutRect(layer=layers.Metal1)
        l.pin_m = LayoutRect(layer=layers.Metal1)
        s.constrain(l.pin_p.southwest == l.dev.term_p.southwest)
        s.constrain(l.pin_p.northeast == l.dev.term_p.northeast)
        s.constrain(l.pin_m.southwest == l.dev.term_m.southwest)
        s.constrain(l.pin_m.northeast == l.dev.term_m.northeast)

        l.pin_p % LayoutPin(pin=self.symbol.p)
        l.pin_m % LayoutPin(pin=self.symbol.m)

        s.solve()
        return l


class CmimDevice(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.p = Pin(pos=(2, 4), pintype=PinType.Inout, align=North)
        s.m = Pin(pos=(2, 0), pintype=PinType.Inout, align=South)

        s % SymbolPoly(vertices=[(1.25, 1.8), (2.75, 1.8)])
        s % SymbolPoly(vertices=[(1.25, 2.2), (2.75, 2.2)])
        s % SymbolPoly(vertices=[(2, 2.2), (2, 4)])
        s % SymbolPoly(vertices=[(2, 1.8), (2, 0)])
        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol, outline=(0, 0, 10, 12))

        s.p = Net(pin=self.symbol.p)
        s.m = Net(pin=self.symbol.m)

        dev = ihp130.Cmim().symbol
        s.c = SchemInstance(dev.portmap(p=s.p, m=s.m), pos=(3, 4))

        s.p % SchemPort(pos=(2, 11), align=East)
        s.m % SchemPort(pos=(2, 1), align=East)

        s.auto_wire()
        return s

    @generate
    def layout(self):
        layers = ihp130.SG13G2().layers
        l = Layout(ref_layers=layers, cell=self, symbol=self.symbol)
        s = Solver(l)

        dev = ihp130.Cmim()
        l.dev = LayoutInstance(ref=dev.layout)
        s.constrain(l.dev.pos == (0, 0))

        l.pin_p = LayoutRect(layer=layers.TopMetal1)
        l.pin_m = LayoutRect(layer=layers.Metal5)
        s.constrain(l.pin_p.southwest == l.dev.term_p.southwest)
        s.constrain(l.pin_p.northeast == l.dev.term_p.northeast)
        s.constrain(l.pin_m.southwest == l.dev.term_m.southwest)
        s.constrain(l.pin_m.northeast == l.dev.term_m.northeast)

        l.pin_p % LayoutPin(pin=self.symbol.p)
        l.pin_m % LayoutPin(pin=self.symbol.m)

        s.solve()
        return l
