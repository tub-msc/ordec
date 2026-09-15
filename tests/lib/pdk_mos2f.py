# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *
from ordec.lib import ihp130, sky130


class Mos2f(Cell):
    """
    Single two-finger Nmos with the gate fingers strapped in poly and the two
    source columns strapped in met1, plus a substrate tap. Exercises the
    multi-finger LVS pathway (two extracted parallel devices vs. one
    netlisted card) for both layout-capable PDKs, using the identical
    construction on top of the PDK generators' common sd[i]/poly[i]/m1
    interface.
    """
    pdk = Parameter(str)

    def pdklib(self):
        return {'ihp130': ihp130, 'sky130': sky130}[self.pdk]

    def nmos(self):
        if self.pdk == 'ihp130':
            return ihp130.Nmos(w="1u", l="130n", ng=2)
        return sky130.Nmos(w="1u", l="150n", nf=2)

    @viewgen_noctx
    def symbol(self):
        s = Symbol(cell=self)
        s.d = Pin(pintype=PinType.Inout, align=North)
        s.g = Pin(pintype=PinType.In, align=West)
        s.s = Pin(pintype=PinType.Inout, align=South)
        s.b = Pin(pintype=PinType.Inout, align=South)
        s.place_pins()
        return s

    @viewgen_noctx
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol)
        s.d = Net(pin=self.symbol.d)
        s.g = Net(pin=self.symbol.g)
        s.s = Net(pin=self.symbol.s)
        s.b = Net(pin=self.symbol.b)
        nmos = self.nmos().symbol
        s.m = SchemInstance(nmos.portmap(d=s.d, g=s.g, s=s.s, b=s.b), pos=(3, 2))
        for name in ('d', 'g', 's', 'b'):
            getattr(s, name) % SchemPort(pos=s.m.pos + nmos[name].pos,
                align=nmos[name].align)
        s.auto_wire()
        return s

    @viewgen_noctx
    def layout(self):
        pdklib = self.pdklib()
        layers = pdklib.SG13G2().layers if self.pdk == 'ihp130' else pdklib.SKY130().layers
        poly_layer = layers.GatPoly if self.pdk == 'ihp130' else layers.poly
        m1_layer = layers.Metal1 if self.pdk == 'ihp130' else layers.met1

        l = Layout(ref_layers=layers, cell=self, symbol=self.symbol)
        s = Solver(l)
        ptap = pdklib.Ptap(l="0.7u", w="0.7u")
        l.m = LayoutInstance(ref=self.nmos().layout)
        l.tap = LayoutInstance(ref=ptap.layout)
        s.constrain(l.m.pos == (0, 0))
        s.constrain(l.tap.pos == (-1200, 0))

        # Poly strap joining both gate fingers above the diffusion:
        l.gstrap = LayoutRect(layer=poly_layer)
        s.constrain(l.gstrap.lx == l.m.poly[0].lx)
        s.constrain(l.gstrap.ux == l.m.poly[1].ux)
        s.constrain(l.gstrap.ly == l.m.poly[0].uy)
        s.constrain(l.gstrap.height == 150)
        if self.pdk == 'sky130':
            # The SKY130 LVS deck reads poly labels, so the pin can sit
            # directly on the strap.
            l.gstrap % LayoutPin(pin=self.symbol.g)
        else:
            # SG13G2 has no poly text layer, so the gate is contacted up to Metal1.
            l.gpad = LayoutRect(layer=poly_layer)
            s.constrain(l.gpad.size == (500, 500))
            s.constrain(l.gpad.south == l.gstrap.north)
            l.gcont = LayoutRect(layer=layers.Cont)
            s.constrain(l.gcont.size == (160, 160))
            s.constrain(l.gcont.center == l.gpad.center)
            l.gm1 = LayoutRect(layer=m1_layer)
            s.constrain(l.gm1.center == l.gcont.center)
            s.constrain(l.gm1.size == (1500, 160))
            l.gm1 % LayoutPin(pin=self.symbol.g)

        # met1 strap joining the two source columns, routed below the drain:
        l.sdrop0 = LayoutRect(layer=m1_layer)
        s.constrain(l.sdrop0.x_extent == l.m.sd[0].x_extent)
        s.constrain(l.sdrop0.uy == l.m.sd[0].ly + 50)
        s.constrain(l.sdrop0.ly == -400)
        l.sdrop2 = LayoutRect(layer=m1_layer)
        s.constrain(l.sdrop2.x_extent == l.m.sd[2].x_extent)
        s.constrain(l.sdrop2.uy == l.m.sd[2].ly + 50)
        s.constrain(l.sdrop2.ly == -400)
        l.sstrap = LayoutRect(layer=m1_layer)
        s.constrain(l.sstrap.lx == l.m.sd[0].lx)
        s.constrain(l.sstrap.ux == l.m.sd[2].ux)
        s.constrain(l.sstrap.uy == -230)
        s.constrain(l.sstrap.height == 170)
        l.sstrap % LayoutPin(pin=self.symbol.s)

        # The drain pin extends past the sd column, as an onward route would.
        # The bare column alone is below Metal1 minimum area at this size.
        l.dpin = LayoutRect(layer=m1_layer)
        s.constrain(l.dpin.x_extent == l.m.sd[1].x_extent)
        s.constrain(l.dpin.ly == l.m.sd[1].ly)
        s.constrain(l.dpin.uy == l.m.sd[1].uy + 300)
        l.dpin % LayoutPin(pin=self.symbol.d)

        l.bpin = LayoutRect(layer=m1_layer)
        s.constrain(l.bpin.rect == l.tap.m1.rect)
        l.bpin % LayoutPin(pin=self.symbol.b)
        s.solve()
        return l
