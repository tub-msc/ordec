# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Experimental voltage-controlled oscillator (VCO) example.

The VCO is a pseudodifferential ping oscillator generating 4 phases with 90
degree phase differences.
"""

from itertools import pairwise
import os
import subprocess

from ordec.core import *
from ordec.lib import ihp130
from ordec.lib.base import Res, Cap, Gnd, Vdc, NoConn, Vpwl
from ordec.schematic.routing import schematic_routing
from ordec.schematic.helpers import symbol_place_pins, add_conn_points
from ordec.sim import HighlevelSim
from ordec.report import Report, Plot2D, Markdown
from ordec.layout.makevias import makevias
from ordec.layout import write_gds, gds_str_from_layout
from ordec.layout import helpers

class VcoHalfStage(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vdd_st = Pin(pintype=PinType.Inout, align=Orientation.North)
        s.vss_st = Pin(pintype=PinType.Inout, align=Orientation.South)
        s.vdd = Pin(pintype=PinType.Inout, align=Orientation.North)
        s.vss = Pin(pintype=PinType.Inout, align=Orientation.South)

        s.rst_n = Pin(pintype=PinType.In, align=Orientation.West)
        s.inp = Pin(pintype=PinType.In, align=Orientation.West)
        s.fb  = Pin(pintype=PinType.In, align=Orientation.East)
        s.out = Pin(pintype=PinType.Out, align=Orientation.East)
        s.out_n = Pin(pintype=PinType.Out, align=Orientation.East)

        symbol_place_pins(s, vpadding=2, hpadding=2)
        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol, outline=(0,4,31,26))

        s.vdd_st = Net(pin=self.symbol.vdd_st)
        s.vss_st = Net(pin=self.symbol.vss_st)
        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)
        s.rst_n = Net(pin=self.symbol.rst_n)
        s.inp = Net(pin=self.symbol.inp)
        s.fb = Net(pin=self.symbol.fb)
        s.out = Net(pin=self.symbol.out)
        s.out_n = Net(pin=self.symbol.out_n)

        s.b = Net()

        nmos = ihp130.Nmos(w="300n", l="130n").symbol
        pmos = ihp130.Pmos(w="300n", l="130n").symbol

        s.m1 = SchemInstance(pmos.portmap(s=s.vdd_st, b=s.vdd, g=s.inp, d=s.out), pos=(3, 19))
        s.m2 = SchemInstance(nmos.portmap(s=s.b, b=s.vss, g=s.inp, d=s.out), pos=(3, 13))
        s.m3 = SchemInstance(nmos.portmap(s=s.vss_st, b=s.vss, g=s.rst_n, d=s.b), pos=(3, 7))
        s.m4 = SchemInstance(pmos.portmap(s=s.vdd_st, b=s.vdd, g=s.rst_n, d=s.out), pos=(10, 19))

        s.m5 = SchemInstance(pmos.portmap(s=s.vdd_st, b=s.vdd, g=s.fb, d=s.out), pos=(17, 19))
        s.m6 = SchemInstance(nmos.portmap(s=s.vss_st, b=s.vss, g=s.fb, d=s.out), pos=(17, 13))

        s.m7 = SchemInstance(pmos.portmap(s=s.vdd, b=s.vdd, g=s.out, d=s.out_n), pos=(25, 19))
        s.m8 = SchemInstance(nmos.portmap(s=s.vss, b=s.vss, g=s.out, d=s.out_n), pos=(25, 13))

        #s.m2 = SchemInstance(pmos.portmap(s=s.t, b=s.vdd, g=s.inp, d=s.out), pos=(3, 13))
        #s.m2 = SchemInstance(pmos.portmap(s=s.t, b=s.vdd, g=s.inp, d=s.out), pos=(3, 13))

        s.vdd_st % SchemPort(pos=(1,24), align=Orientation.East)
        s.vdd % SchemPort(pos=(1,26), align=Orientation.East)
        s.vss_st % SchemPort(pos=(1,6), align=Orientation.East)
        s.vss % SchemPort(pos=(1,4), align=Orientation.East)
        s.inp % SchemPort(pos=(1,21), align=Orientation.East)
        s.rst_n % SchemPort(pos=(1,9), align=Orientation.East)
        s.fb % SchemPort(pos=(15,15), align=Orientation.East)
        s.out % SchemPort(pos=(24,18), align=Orientation.West)
        s.out_n % SchemPort(pos=(30,18), align=Orientation.West)
        
        schematic_routing(s)
        add_conn_points(s)

        return s

    @generate
    def layout(self):
        layers = ihp130.SG13G2().layers
        l = Layout(ref_layers=layers, cell=self, symbol=self.symbol)
        s = Solver(l)

        pmos = self.schematic.m1.symbol.cell
        nmos = self.schematic.m2.symbol.cell

        l.m1 = LayoutInstance(ref=pmos.layout)
        l.m2 = LayoutInstance(ref=nmos.layout)
        
        l.m3 = LayoutInstance(ref=nmos.layout)
        l.m4 = LayoutInstance(ref=pmos.layout)

        l.m5 = LayoutInstance(ref=nmos.layout)
        l.m6 = LayoutInstance(ref=pmos.layout)
        
        l.m7 = LayoutInstance(ref=nmos.layout)
        l.m8 = LayoutInstance(ref=pmos.layout)

        grid = ((l.m2, l.m1), (l.m3, l.m4), (l.m5, l.m6), (l.m7, l.m8))

        s.constrain(l.m1.pos == (0, 0))
        s.constrain(l.m1.poly[0].rect.cx == l.m2.poly[0].rect.cx)

        s.constrain(l.m1.activ.rect.ly == l.m2.activ.rect.uy + 1500)

        for left, right in pairwise(grid):
            left_nmos, left_pmos = left
            right_nmos, right_pmos = right
            s.constrain(right_nmos.sd[0].rect.center == left_nmos.sd[1].rect.center)
            s.constrain(right_pmos.sd[0].rect.center == left_pmos.sd[1].rect.center)

        l.mkpath('poly')
        for idx, insts in enumerate(grid):
            l.poly[idx] = LayoutRect(layer=layers.GatPoly) 
            for inst in insts:
                s.constrain(l.poly[idx].rect.contains(inst.poly[0].rect))

        polycont_spec = (
            ('south', 'west', 'rst_n'),
            ('south', 'west', 'inp'),
            ('south', 'east', 'fb'),
            ('north', 'west', False),
        )
        l.mkpath('polycont')
        polycont_m1={}
        for idx, (vert_spec, horiz_spec, add_m1) in enumerate(polycont_spec):
            polyext = l % LayoutRect(layer=layers.GatPoly)
            s.constrain(polyext.rect.size == (300, 300))
            if horiz_spec == 'west':
                s.constrain(polyext.rect.ux == l.poly[idx].rect.ux)
            else:
                assert horiz_spec == 'east'
                s.constrain(polyext.rect.lx == l.poly[idx].rect.lx)
            if vert_spec == 'north':
                s.constrain(polyext.rect.uy == l.m1.activ.rect.ly - 200)
            else:
                assert vert_spec == 'south'
                s.constrain(polyext.rect.ly == l.m2.activ.rect.uy + 200)
            l.polycont[idx] = LayoutRect(layer=layers.Cont)
            s.constrain(l.polycont[idx].rect.size == (160, 160))
            s.constrain(l.polycont[idx].rect.center == polyext.rect.center)
            if add_m1:
                setattr(l, add_m1, LayoutRect(layer=layers.Metal1))
                m1 = getattr(l, add_m1)
                s.constrain(m1.rect.cx == l.polycont[idx].rect.cx + (-25 if horiz_spec=='west' else 25))
                s.constrain(m1.rect.width == 210)
                s.constrain(m1.rect.ly == l.m2.sd[0].rect.uy + 200)
                s.constrain(m1.rect.height == 600)

        l.rst_n % LayoutPin(pin=self.symbol.rst_n)
        l.inp % LayoutPin(pin=self.symbol.inp)
        l.fb % LayoutPin(pin=self.symbol.fb)


        l.outbar_h = LayoutRect(layer=layers.Metal1)
        l.outbar_h % LayoutPin(pin=self.symbol.out)
        s.constrain(l.outbar_h.rect.cy == l.polycont[3].rect.cy)
        s.constrain(l.outbar_h.rect.height == 200)
        s.constrain(l.outbar_h.rect.lx == l.m1.sd[0].rect.lx)
        s.constrain(l.outbar_h.rect.ux == l.polycont[3].rect.ux + 500)


        l.outbar_vmain = LayoutRect(layer=layers.Metal1)
        s.constrain(l.outbar_vmain.rect.contains(l.m3.sd[1].rect))
        s.constrain(l.outbar_vmain.rect.contains(l.m4.sd[1].rect))

        l.outbar_vrst = LayoutRect(layer=layers.Metal1)
        s.constrain(l.outbar_vrst.rect.contains(l.m1.sd[0].rect))
        s.constrain(l.outbar_vrst.rect.ly == l.outbar_h.rect.ly)

        l.outbar_outn = LayoutRect(layer=layers.Metal1)
        s.constrain(l.outbar_outn.rect.uy == l.m8.sd[1].rect.uy)
        s.constrain(l.outbar_outn.rect.ly == l.m7.sd[1].rect.ly)
        s.constrain(l.outbar_outn.rect.lx >= l.m7.sd[1].rect.ux)
        s.constrain(l.outbar_outn.rect.lx >= l.outbar_h.rect.ux + 200)
        s.constrain(l.outbar_outn.rect.width == 160)

        l.outbar_outn % LayoutPin(pin=self.symbol.out_n)

        for sd in (l.m8.sd[1], l.m7.sd[1]):
            r = l % LayoutRect(layer=layers.Metal1)
            s.constrain(r.rect.contains(sd.rect))
            s.constrain(r.rect.ux >= l.outbar_outn.rect.lx)

        l.vddbar = LayoutRect(layer=layers.Metal1)
        l.vddbar % LayoutPin(pin=self.symbol.vdd)
        s.constrain(l.vddbar.rect.southwest == l.m1.sd[0].rect.northwest + (-500,400))
        s.constrain(l.vddbar.rect.height == 400)
        s.constrain(l.vddbar.rect.ux == l.m7.sd[1].rect.ux + 500)

        for sd in (l.m4.sd[0], l.m8.sd[0]):
            r = l % LayoutRect(layer=layers.Metal1)
            s.constrain(r.rect.contains(sd.rect))
            s.constrain(r.rect.uy == l.vddbar.rect.ly)

        l.vssbar = LayoutRect(layer=layers.Metal1)
        l.vssbar % LayoutPin(pin=self.symbol.vss)
        s.constrain(l.vssbar.rect.width == l.vddbar.rect.width)
        s.constrain(l.vssbar.rect.height == 400)
        s.constrain(l.vssbar.rect.northwest == l.m2.sd[0].rect.southwest - (500,500))

        for sd in (l.m2.sd[0], l.m7.sd[0]):
            r = l % LayoutRect(layer=layers.Metal1)
            s.constrain(r.rect.contains(sd.rect))
            s.constrain(r.rect.ly == l.vssbar.rect.uy)

        r = l % LayoutRect(layer=layers.Metal1)
        s.constrain(r.rect.contains(l.m2.sd[1].rect))
        s.constrain(r.rect.height == 600)
        s.constrain(r.rect.uy == l.m2.sd[1].rect.uy)

        l.nwell = LayoutRect(layer=layers.NWell)
        for m in (l.m1, l.m4, l.m6, l.m8):
            s.constrain(l.nwell.rect.contains(m.nwell.rect))

        s.solve()
        return l    

class VcoRing(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vdd_st = Pin(pintype=PinType.Inout, align=Orientation.North)
        s.vss_st = Pin(pintype=PinType.Inout, align=Orientation.South)
        s.vdd = Pin(pintype=PinType.Inout, align=Orientation.North)
        s.vss = Pin(pintype=PinType.Inout, align=Orientation.South)
        s.rst_n = Pin(pintype=PinType.In, align=Orientation.West)

        s.mkpath('out_n')
        s.mkpath('out_p')
        for i in range(2):
            s.out_p[i] = Pin(pintype=PinType.Out, align=Orientation.East)
            s.out_n[i] = Pin(pintype=PinType.Out, align=Orientation.East)

        symbol_place_pins(s, vpadding=2, hpadding=2)
        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol, outline=(0,0,23,22))

        s.vdd_st = Net(pin=self.symbol.vdd_st, route=False)
        s.vss_st = Net(pin=self.symbol.vss_st, route=False)
        s.vdd = Net(pin=self.symbol.vdd, route=False)
        s.vss = Net(pin=self.symbol.vss, route=False)
        s.rst_n = Net(pin=self.symbol.rst_n)

        s.mkpath("stage_p")
        s.mkpath("stage_n")
        s.mkpath("int_n")
        s.mkpath("int_p")
        s.mkpath("out_n")
        s.mkpath("out_p")
        for i in range(2):
            s.int_n[i] = Net()
            s.int_p[i] = Net()
            s.out_n[i] = Net(pin=self.symbol.out_n[i])
            s.out_p[i] = Net(pin=self.symbol.out_p[i])


        for i in range(2):
            xoffset = 10*i
            s.stage_p[i] = SchemInstance(VcoHalfStage().symbol.portmap(
                out=s.int_p[i],
                fb=s.int_n[i],
                vdd=s.vdd,
                out_n=s.out_p[i],
                vdd_st=s.vdd_st,
                vss=s.vss,
                vss_st=s.vss_st,
                rst_n=s.rst_n if i % 2 == 0 else s.vdd,
                inp=s.int_p[i-1] if i > 0 else s.int_n[1],
                ), pos=(5+xoffset,13))
            s.stage_n[i] = SchemInstance(VcoHalfStage().symbol.portmap(
                out=s.int_n[i],
                fb=s.int_p[i],
                out_n=s.out_n[i],
                vdd=s.vdd,
                vdd_st=s.vdd_st,
                vss=s.vss,
                vss_st=s.vss_st,
                rst_n=s.rst_n if i % 2 == 1 else s.vdd,
                inp=s.int_n[i-1] if i > 0 else s.int_p[1],
                ), pos=(5+xoffset,3))

            s.out_p[i] % SchemPort(pos=(xoffset+12,17), align=Orientation.West)
            s.out_n[i] % SchemPort(pos=(xoffset+12,7), align=Orientation.West)

        s.vdd_st % SchemPort(pos=(1,21), align=Orientation.East)
        s.vdd % SchemPort(pos=(1,22), align=Orientation.East)
        s.vss_st % SchemPort(pos=(1,1), align=Orientation.East)
        s.vss % SchemPort(pos=(1,0), align=Orientation.East)
        s.rst_n % SchemPort(pos=(1,10), align=Orientation.East)

        schematic_routing(s)
        add_conn_points(s)

        return s

    @generate
    def layout(self):
        layers = ihp130.SG13G2().layers
        l = Layout(ref_layers=layers, cell=self, symbol=self.symbol)
        s = Solver(l)

        l.mkpath('stage_n')
        l.mkpath('stage_p')
        l.mkpath('out_n')
        l.mkpath('out_p')

        l.nwell = LayoutRect(layer=layers.NWell)
       
        l.vdd_st_bar = LayoutRect(layer=layers.Metal1)
        l.vdd_st_bar % LayoutPin(pin=self.symbol.vdd_st)

        l.vss_st_bar_n = LayoutRect(layer=layers.Metal1)
        l.vss_st_bar_n % LayoutPin(pin=self.symbol.vss_st)

        l.vss_st_bar_p = LayoutRect(layer=layers.Metal1)
        l.vss_st_bar_p % LayoutPin(pin=self.symbol.vss_st)

        for i in range(2):
            l.stage_p[i] = LayoutInstance(ref=VcoHalfStage().layout, orientation=Orientation.MX)
            l.stage_n[i] = LayoutInstance(ref=VcoHalfStage().layout)
            if i == 0:
                l.stage_p[i].orientation *= Orientation.MY
                l.stage_n[i].orientation *= Orientation.MY
            s.constrain(l.stage_n[i].vddbar.rect.southwest == l.stage_p[i].vddbar.rect.southwest)

            if i > 0:
                s.constrain(l.stage_n[i].vddbar.rect.west == l.stage_n[i-1].vddbar.rect.east)

            s.constrain(l.nwell.rect.contains(l.stage_p[i].nwell.rect))
            s.constrain(l.nwell.rect.contains(l.stage_n[i].nwell.rect))

            outbar_n = l.stage_n[i].outbar_outn
            l.out_n[i] = LayoutRect(layer=outbar_n.layer.nid)
            s.constrain(l.out_n[i].rect == outbar_n.rect)
            l.out_n[i] % LayoutPin(pin=self.symbol.out_n[i])

            outbar_p = l.stage_p[i].outbar_outn
            l.out_p[i] = LayoutRect(layer=outbar_p.layer.nid)
            s.constrain(l.out_p[i].rect == outbar_p.rect)
            l.out_p[i] % LayoutPin(pin=self.symbol.out_p[i])

            s.constrain(l.vdd_st_bar.rect.contains(l.stage_p[i].vddbar.rect))
            s.constrain(l.vdd_st_bar.rect.contains(l.stage_n[i].vddbar.rect))

            s.constrain(l.vss_st_bar_n.rect.contains(l.stage_n[i].vssbar.rect))
            s.constrain(l.vss_st_bar_p.rect.contains(l.stage_p[i].vssbar.rect))


        s.constrain(l.stage_p[0].pos==(0,0))

        r = l % LayoutRect(layer=layers.Metal2)
        s.constrain(r.rect.south == l.stage_n[0].rst_n.rect.south)
        s.constrain(r.rect.width == 200)
        s.constrain(r.rect.uy == l.stage_n[0].vddbar.rect.uy + 40)

        v = l % LayoutRect(layer=layers.Via1)
        s.constrain(v.rect.size == Vec2I(190, 190))
        s.constrain(v.rect.north == r.rect.north - (0,50))

        v = l % LayoutRect(layer=layers.Via1)
        s.constrain(v.rect.size == Vec2I(190, 190))
        s.constrain(v.rect.center == l.stage_n[0].rst_n.rect.center)

        r = l % LayoutRect(layer=layers.Metal2)
        s.constrain(r.rect.north == l.stage_p[1].rst_n.rect.north)
        s.constrain(r.rect.width == 200)
        s.constrain(r.rect.ly == l.stage_n[1].vddbar.rect.ly - 40)

        v = l % LayoutRect(layer=layers.Via1)
        s.constrain(v.rect.size == Vec2I(190, 190))
        s.constrain(v.rect.south == r.rect.south + (0,50))

        v = l % LayoutRect(layer=layers.Via1)
        s.constrain(v.rect.size == Vec2I(190, 190))
        s.constrain(v.rect.center == l.stage_p[1].rst_n.rect.center)

        l.rst_n = LayoutRect(layer=layers.Metal2)
        s.constrain(l.rst_n.rect.width == 200)
        s.constrain(l.rst_n.rect.uy == l.stage_p[1].vssbar.rect.uy + 1000)
        s.constrain(l.rst_n.rect.cx == 0.5*l.stage_p[0].rst_n.rect.cx + 0.5*l.stage_n[1].rst_n.rect.cx)
        s.constrain(l.rst_n.rect.ly == l.stage_n[1].rst_n.rect.ly)
        l.rst_n % LayoutPin(pin=self.symbol.rst_n)

        r = l % LayoutRect(layer=layers.Metal2)
        s.constrain(r.rect.contains(l.stage_n[1].rst_n.rect))
        s.constrain(r.rect.lx == l.rst_n.rect.ux)

        v = l % LayoutRect(layer=layers.Via1)
        s.constrain(v.rect.size == Vec2I(190, 190))
        s.constrain(v.rect.center == l.stage_n[1].rst_n.rect.center)

        r = l % LayoutRect(layer=layers.Metal2)
        s.constrain(r.rect.contains(l.stage_p[0].rst_n.rect))
        s.constrain(r.rect.ux == l.rst_n.rect.lx)

        v = l % LayoutRect(layer=layers.Via1)
        s.constrain(v.rect.size == Vec2I(190, 190))
        s.constrain(v.rect.center == l.stage_p[0].rst_n.rect.center)
          
        l.outv_p0 = LayoutPath(2, layer=layers.Metal2, width=200, endtype=PathEndType.SQUARE)
        s.constrain(l.outv_p0[0] == l.stage_n[0].fb.rect.center)
        s.constrain(l.outv_p0[1].x == l.outv_p0[0].x)
        s.constrain(l.outv_p0[1].y == l.stage_p[0].outbar_h.rect.cy)

        l.outv_n0 = LayoutPath(3, layer=layers.Metal2, width=200, endtype=PathEndType.SQUARE)
        s.constrain(l.outv_n0[0] == l.stage_p[0].fb.rect.center)
        s.constrain(l.outv_n0[2] == l.stage_n[0].outbar_h.rect.west + (100, 0))
        s.constrain(l.outv_n0[1] == (l.outv_n0[2].x, l.outv_n0[0].y))

        l.outv_p1 = LayoutPath(2, layer=layers.Metal2, width=200, endtype=PathEndType.SQUARE)
        s.constrain(l.outv_p1[0] == l.stage_n[1].fb.rect.center)
        s.constrain(l.outv_p1[1].x == l.outv_p1[0].x)
        s.constrain(l.outv_p1[1].y == l.stage_p[1].outbar_h.rect.cy)

        l.outv_n1 = LayoutPath(3, layer=layers.Metal2, width=200, endtype=PathEndType.SQUARE)
        s.constrain(l.outv_n1[0] == l.stage_p[1].fb.rect.center)
        s.constrain(l.outv_n1[2] == l.stage_n[1].outbar_h.rect.east - (100,0))
        s.constrain(l.outv_n1[1] == (l.outv_n1[2].x, l.outv_n1[0].y))

        l.outh_n0 = LayoutPath(2, layer=layers.Metal3, width=200, endtype=PathEndType.SQUARE)
        s.constrain(l.outh_n0[0] == l.outv_n0[2])
        s.constrain(l.outh_n0[1].y == l.outh_n0[0].y)
        s.constrain(l.outh_n0[1].x == l.stage_n[1].inp.rect.cx)

        l.outh_p0 = LayoutPath(2, layer=layers.Metal3, width=200, endtype=PathEndType.SQUARE)
        s.constrain(l.outh_p0[0] == l.outv_p0[1])
        s.constrain(l.outh_p0[1].y == l.outh_p0[0].y)
        s.constrain(l.outh_p0[1].x == l.stage_p[1].inp.rect.cx)

        l.outh_n1 = LayoutPath(2, layer=layers.Metal3, width=200, endtype=PathEndType.SQUARE)
        s.constrain(l.outh_n1[0].x == l.outv_p1[0].x)
        s.constrain(l.outh_n1[0].y == l.outh_n0[0].y + 500)
        s.constrain(l.outh_n1[1] == (l.stage_n[0].inp.rect.cx, l.outh_n1[0].y))

        l.outh_p1 = LayoutPath(2, layer=layers.Metal3, width=200, endtype=PathEndType.SQUARE)
        s.constrain(l.outh_p1[0].x == l.outv_n1[2].x)
        s.constrain(l.outh_p1[0].y == l.outh_p0[0].y - 500)
        s.constrain(l.outh_p1[1].y == l.outh_p1[0].y)

        for inp, end in [
                (l.stage_p[0].inp, l.outh_p1[1]),
                (l.stage_n[0].inp, l.outh_n1[1]),
                (l.stage_n[1].inp, l.outh_n0[1]),
                (l.stage_p[1].inp, l.outh_p0[1]),
            ]:
            s.constrain(end.x == inp.rect.cx)

            p = l % LayoutPath(2, layer=layers.Metal2, width=200, endtype=PathEndType.SQUARE)
            s.constrain(p[0] == inp.rect.center)
            s.constrain(p[1] == end)

        for vertex in [
                l.outv_p0[0], l.outv_p0[1],
                l.outv_n0[0], l.outv_n0[2],
                l.outv_p1[0], l.outv_p1[1],
                l.outv_n1[0], l.outv_n1[2],
                l.stage_n[0].inp.rect.center, l.stage_p[0].inp.rect.center,
                l.stage_n[1].inp.rect.center, l.stage_p[1].inp.rect.center,
            ]:
            via = l % LayoutRect(layer=layers.Via1)
            s.constrain(via.rect.size == (190, 190))
            s.constrain(via.rect.center == vertex)

        for vertex in [
                l.outh_p0[0], l.outh_p0[1],
                l.outh_n0[0], l.outh_n0[1],
                l.outh_p1[0], l.outh_p1[1],
                l.outh_n1[0], l.outh_n1[1],
            ]:
            via = l % LayoutRect(layer=layers.Via2)
            s.constrain(via.rect.size == (190, 190))
            s.constrain(via.rect.center == vertex)

        s.solve()

        return l

class Vco(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.vdd = Pin(pintype=PinType.Inout, align=Orientation.North)
        s.vss = Pin(pintype=PinType.Inout, align=Orientation.South)

        s.rst_n = Pin(pintype=PinType.In, align=Orientation.West)
        s.vbias = Pin(pintype=PinType.In, align=Orientation.West)
        s.mkpath('out_n')
        s.mkpath('out_p')
        for i in range(2):
            s.out_p[i] = Pin(pintype=PinType.Out, align=Orientation.East)
            s.out_n[i] = Pin(pintype=PinType.Out, align=Orientation.East)

        symbol_place_pins(s, vpadding=2, hpadding=2)
        return s

    @generate
    def schematic(self):
        s = Schematic(cell=self, symbol=self.symbol, outline=(-2,-2,34,30))

        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)

        s.rst_n = Net(pin=self.symbol.rst_n)
        s.vbias = Net(pin=self.symbol.vbias)

        s.vss_st = Net()
        s.vdd_st = Net()
        s.cm_mid = Net()

        s.mkpath('out_n')
        s.mkpath('out_p')
        
        for i in range(2):
            s.out_p[i] = Net(pin=self.symbol.out_p[i])
            s.out_n[i] = Net(pin=self.symbol.out_n[i])

        nmos = ihp130.Nmos(w="300n", l="130n").symbol
        pmos = ihp130.Pmos(w="300n", l="130n").symbol

        s.ring = SchemInstance(VcoRing().symbol.portmap(
            vss=s.vss,
            vdd=s.vdd,
            vss_st=s.vss_st,
            vdd_st=s.vdd_st,
            rst_n=s.rst_n,
        ), pos=(15,7))

        for i in range(2):
            s.ring % SchemInstanceConn(here=s.out_n[i], there=VcoRing().symbol.out_n[i])
            s.ring % SchemInstanceConn(here=s.out_p[i], there=VcoRing().symbol.out_p[i])
            s.out_p[i] % SchemPort(pos=(22, 9+2*i), align=Orientation.West)
            s.out_n[i] % SchemPort(pos=(22, 10+2*i), align=Orientation.West)

        s.m1 = SchemInstance(nmos.portmap(
            d=s.vss_st,
            s=s.vss,
            b=s.vss,
            g=s.vbias,
            ), pos=(15, 1))

        s.m2 = SchemInstance(pmos.portmap(
            d=s.vdd_st,
            s=s.vdd,
            b=s.vdd,
            g=s.cm_mid,
            ), pos=(15, 16))

        s.m3 = SchemInstance(pmos.portmap(
            d=s.cm_mid,
            g=s.cm_mid,
            s=s.vdd,
            b=s.vdd,
            ), pos=(11, 16), orientation=Orientation.MY)

        s.m4 = SchemInstance(nmos.portmap(
            d=s.cm_mid,
            s=s.vss,
            b=s.vss,
            g=s.vbias,
            ), pos=(7, 1))
        
        s.rst_n % SchemPort(pos=(13,9), align=Orientation.East)
        s.vdd % SchemPort(pos=(4,21), align=Orientation.East)
        s.vss % SchemPort(pos=(4,0), align=Orientation.East)
        s.vbias % SchemPort(pos=(4,6), align=Orientation.East)

        schematic_routing(s)
        add_conn_points(s)

        return s

class VcoTb(Cell):
    
    @generate
    def schematic(self):
        s = Schematic(cell=self, outline=(0,0,40,20))

        s.vss = Net()
        s.vdd = Net()
        s.vbias = Net()
        s.rst_n = Net()

        s.mkpath('out_n')
        s.mkpath('out_p')
        s.mkpath('nc')

        vco = Vco().symbol
        s.dut = SchemInstance(vco.portmap(
            vss=s.vss,
            vdd=s.vdd,
            vbias=s.vbias,
            rst_n=s.rst_n,
            ), pos=(17,6))
        for i in range(2):
            s.out_n[i] = Net()
            s.out_p[i] = Net()

            s.dut % SchemInstanceConn(here=s.out_n[i], there=vco.out_n[i])
            s.dut % SchemInstanceConn(here=s.out_p[i], there=vco.out_p[i])
            s.nc[2*i+0] = SchemInstance(NoConn().symbol.portmap(
                a=s.out_n[i],
                ), pos=(22+5*i, 6), orientation=Orientation.R270)
            s.nc[2*i+1] = SchemInstance(NoConn().symbol.portmap(
                a=s.out_p[i],
                ), pos=(26+5*i, 17), orientation=Orientation.R90)


        s.Gnd = SchemInstance(Gnd().symbol.portmap(
            p=s.vss,
            ), pos=(0,0))
        s.vdd_src = SchemInstance(Vdc('1.2').symbol.portmap(
            m=s.vss,
            p=s.vdd,
            ), pos=(0,10))
        # s.vbias_src = SchemInstance(Vdc('0.5').symbol.portmap(
        #     m=s.vss,
        #     p=s.vbias,
        #     ), pos=(5,10))
        s.vbias_src = SchemInstance(Vpwl(((0, 1.2), (1e-9, 1.2), (30e-9, 0))).symbol.portmap(
            m=s.vss,
            p=s.vbias,
            ), pos=(5,10))
        s.rst_n_src = SchemInstance(Vpwl(((0, 0), (1e-9, 0), (1.1e-9, 1.2))).symbol.portmap(
            m=s.vss,
            p=s.rst_n,
            ), pos=(10,10))

        schematic_routing(s)
        add_conn_points(s)

        return s

    @generate
    def sim_tran(self):
        """Run sync transient simulation."""

        s = SimHierarchy.from_schematic(self.schematic)
        sim = HighlevelSim(s)
        sim.tran(R('10p'), R('30n'))
        return s

    @generate
    def report_tran(self):
        sim = self.sim_tran

        elements = [Markdown("## VCO transient main waveforms")]
        for i in range(2):
            elements.append(Plot2D(
                x=sim.time,
                series={
                    sim.out_n[i].full_path_str(): sim.out_n[i].trans_voltage,
                    sim.out_p[i].full_path_str(): sim.out_p[i].trans_voltage,
                },
                xlabel="Time (s)",
                ylabel="Voltage (V)",
                height=180,
                plot_group="vco_tran",
                ))
        elements.append(Plot2D(
            x=sim.time,
            series={
                'rst_n': sim.rst_n.trans_voltage,
                'vbias': sim.vbias.trans_voltage,
            },
            xlabel="Time (s)",
            ylabel="Voltage (V)",
            height=120,
            plot_group="vco_tran",
            ))
        elements.append(Plot2D(
            x=sim.time,
            series={'vdd_src': [-x for x in sim.vdd_src.trans_current]},
            xlabel="Time (s)",
            ylabel="Current (A)",
            height=120,
            plot_group="vco_tran",
            ))
        return Report(elements)

def count_rectangles(l: Layout, flatten: bool):
    l = l.mutable_copy()
    if flatten:
        helpers.flatten(l)
    return gds_str_from_layout(l).count("BOUNDARY") + gds_str_from_layout(l).count("PATH")

if __name__ == "__main__":
    with open("out.gds", "wb") as f:
        write_gds(VcoRing().layout, f)
        #write_gds(VcoHalfStage().layout, f)

    print("Number of rectangles:", count_rectangles(VcoRing().layout, True))

    #os.system("python3 $ORDEC_PDK_IHP_SG13G2/libs.tech/klayout/tech/drc/run_drc.py --path out.gds --no_density --run_dir=drc_out")
    #os.system("klayout out.gds -m drc_out/out_vcoring_full.lyrdb")
