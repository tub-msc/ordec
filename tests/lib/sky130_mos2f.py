# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Testcase for the multi-finger MOS LVS pathway: a two-finger NMOS with its
fingers strapped, built on the generator's sd[i]/poly[i] rects.
"""

from ordec.core import *
from ordec.lib import sky130


class Mos2f(Cell):
    def nmos(self):
        return sky130.Nmos(w="1u", l="300n", nf=2, guard=False, topc=False, botc=False)

    @viewgen_noctx
    def symbol(self):
        s = Symbol(cell=self)
        s.d = Pin(pintype=PinType.Inout, orient=North)
        s.g = Pin(pintype=PinType.In, orient=West)
        s.s = Pin(pintype=PinType.Inout, orient=South)
        s.b = Pin(pintype=PinType.Inout, orient=South)
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
                orient=nmos[name].orient)
        s.auto_wire()
        return s

    @viewgen_noctx
    def layout(self):
        layers = sky130.SKY130().layers
        l = Layout(ref_layers=layers, cell=self, symbol=self.symbol)
        s = Solver(l)
        ptap = sky130.Ptap(l="0.7u", w="0.7u")
        l.m = LayoutInstance(ref=self.nmos().layout)
        l.tap = LayoutInstance(ref=ptap.layout)
        s.constrain(l.m.pos == (0, 0))
        s.constrain(l.tap.pos == (-2000, -350))

        # Poly strap joining both gate fingers above the diffusion. The LVS
        # deck reads poly labels, so the pin can sit directly on the strap.
        l.gstrap = LayoutRect(layer=layers.poly)
        s.constrain(l.gstrap.lx == l.m.poly[0].lx)
        s.constrain(l.gstrap.ux == l.m.poly[1].ux)
        s.constrain(l.gstrap.ly == l.m.poly[0].uy)
        s.constrain(l.gstrap.height == 150)
        l.gstrap % LayoutPin(pin=self.symbol.g)

        # met1 strap joining the two source columns, routed below the drain:
        l.sdrop0 = LayoutRect(layer=layers.met1)
        s.constrain(l.sdrop0.x_extent == l.m.sd[0].x_extent)
        s.constrain(l.sdrop0.uy == l.m.sd[0].ly + 50)
        s.constrain(l.sdrop0.ly == l.m.sd[0].ly - 400)
        l.sdrop2 = LayoutRect(layer=layers.met1)
        s.constrain(l.sdrop2.x_extent == l.m.sd[2].x_extent)
        s.constrain(l.sdrop2.uy == l.m.sd[2].ly + 50)
        s.constrain(l.sdrop2.ly == l.m.sd[2].ly - 400)
        l.sstrap = LayoutRect(layer=layers.met1)
        s.constrain(l.sstrap.lx == l.m.sd[0].lx)
        s.constrain(l.sstrap.ux == l.m.sd[2].ux)
        s.constrain(l.sstrap.uy == l.m.sd[0].ly - 230)
        s.constrain(l.sstrap.height == 170)
        l.sstrap % LayoutPin(pin=self.symbol.s)

        # The drain pin extends past the sd column, as an onward route would.
        # The bare column alone is below met1 minimum area at this size.
        l.dpin = LayoutRect(layer=layers.met1)
        s.constrain(l.dpin.x_extent == l.m.sd[1].x_extent)
        s.constrain(l.dpin.ly == l.m.sd[1].ly)
        s.constrain(l.dpin.uy == l.m.sd[1].uy + 300)
        l.dpin % LayoutPin(pin=self.symbol.d)

        l.bpin = LayoutRect(layer=layers.met1)
        s.constrain(l.bpin.rect == l.tap.m1.rect)
        l.bpin % LayoutPin(pin=self.symbol.b)
        s.solve()
        return l
