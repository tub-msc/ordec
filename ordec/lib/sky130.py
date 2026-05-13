# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
from public import public
import functools

from ..core import *
from ..schematic import spice_params
from . import generic_mos
from .pdk_common import PdkDict, check_dir, check_file

@functools.cache
def pdk() -> PdkDict:
    """Returns dictionary-like object with import PDK paths."""
    try:
        root = os.environ["ORDEC_PDK_SKY130A"]
    except KeyError:
        raise Exception("PDK requires environment variable ORDEC_PDK_SKY130A to be set.")
    pdk = PdkDict(root=check_dir(Path(root).resolve()))

    corners = ['ff', 'fs', 'leak', 'sf', 'ss', 'tt', 'wafer']
    pdk.ngspice_deck = {
        cnr: check_file(pdk.root / f"libs.tech/ngspice/corners/{cnr}.spice")
            for cnr in corners
        }

    return pdk
    
def netlist_setup(netlister):
    netlister.add(".include",f"\"{pdk().ngspice_deck['tt']}\"")
    netlister.add(".param","mc_mm_switch=0")

class Mos(SimLeafCell):
    l = Parameter(R) #: Length
    w = Parameter(R) #: Width
    nf = Parameter(int, default=1) #: Number of fingers
    diff_ext = Parameter(R, default=R("0.265u")) #: Diffusion extension for drain/source
    ad = Parameter(R, default=None) #: Drain area (auto-calculated if None)
    as_ = Parameter(R, default=None) #: Source area (auto-calculated if None)
    pd = Parameter(R, default=None) #: Drain perimeter (auto-calculated if None)
    ps = Parameter(R, default=None) #: Source perimeter (auto-calculated if None)
    nrd = Parameter(R, default=R(0)) #: Drain diffusion squares for series R (0 = none)
    nrs = Parameter(R, default=R(0)) #: Source diffusion squares for series R (0 = none)
    sa = Parameter(R, default=R(0)) #: OD-to-poly distance, one side (0 = no stress model)
    sb = Parameter(R, default=R(0)) #: OD-to-poly distance, other side (0 = no stress model)
    sd = Parameter(R, default=R(0)) #: Poly-to-poly distance for multi-finger (0 = no stress model)

    @classmethod
    def params_rewrite(cls, params: dict) -> dict:
        """Auto-calculate ad/as/pd/ps for interdigitated S-G-D-G-S-... layout."""
        w = params['w']
        diff_ext = params['diff_ext']
        nf = params['nf']

        # Number of drain/source diffusion regions:
        # nf=1: S-G-D (1 drain, 1 source)
        # nf=2: S-G-D-G-S (1 drain, 2 sources)
        # nf=3: S-G-D-G-S-G-D (2 drains, 2 sources)
        n_drain = (nf + 1) // 2
        n_source = (nf + 2) // 2

        # Area: each diffusion region is w × diff_ext
        if params.get('ad') is None:
            params['ad'] = n_drain * w * diff_ext
        if params.get('as_') is None:
            params['as_'] = n_source * w * diff_ext

        # Perimeter: 2×diff_ext per region (sides facing isolation), plus W
        # contribution from edge diffusions only. Edge diffusion count:
        # - odd nf: 1 drain edge, 1 source edge
        # - even nf: 0 drain edges (internal), 2 source edges
        if params.get('pd') is None:
            n_edge_drain = 1 if nf % 2 == 1 else 0
            params['pd'] = 2 * n_drain * diff_ext + n_edge_drain * w
        if params.get('ps') is None:
            n_edge_source = 1 if nf % 2 == 1 else 2
            params['ps'] = 2 * n_source * diff_ext + n_edge_source * w

        return params

    def ngspice_save_params(self):
        return ["gm", "gds", "vth", "vdsat", "region"]

    def ngspice_netlist(self, netlister, inst):
        netlister.require_netlist_setup(netlist_setup)
        pins = [inst.symbol.d, inst.symbol.g, inst.symbol.s, inst.symbol.b]
        # sky130 uses ".option scale=1.0u", so ngspice scales:
        # - linear dimensions (l, w, pd, ps, sa, sb, sd) by 1e-6
        # - areas (ad, as) by 1e-12
        # We pre-scale from SI to µm/µm² so ngspice gets the right values.
        netlister.add(
            netlister.name_obj(inst, prefix="x"),
            netlister.portmap(inst, pins),
            self.model_name,
            *spice_params({
                'l': self.l * R('1e6'),
                'w': self.w * R('1e6'),
                'nf': self.nf,
                'ad': self.ad * R('1e12'),
                'as': self.as_ * R('1e12'),
                'pd': self.pd * R('1e6'),
                'ps': self.ps * R('1e6'),
                'nrd': self.nrd,
                'nrs': self.nrs,
                'sa': self.sa * R('1e6'),
                'sb': self.sb * R('1e6'),
                'sd': self.sd * R('1e6'),
            }))

@public
class Nmos(Mos, generic_mos.Nmos):
    model_name = "sky130_fd_pr__nfet_01v8"

@public
class Pmos(Mos, generic_mos.Pmos):
    model_name = "sky130_fd_pr__pfet_01v8"

@public
class Inv(Cell):
    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        # Define pins for the inverter
        s.vdd = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)
        s.vss = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.a = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=West)
        s.y = Pin(pos=Vec2R(4, 2), pintype=PinType.Out, align=East)

        # Draw the inverter symbol
        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1, 2)])  # Input line
        s % SymbolPoly(vertices=[Vec2R(3.25, 2), Vec2R(4, 2)])  # Output line
        s % SymbolPoly(vertices=[Vec2R(1, 1), Vec2R(1, 3), Vec2R(2.75, 2), Vec2R(1, 1)])  # Triangle
        s % SymbolArc(pos=Vec2R(3, 2), radius=R(0.25))  # Output bubble

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)

        return s

    @generate
    def schematic(self) -> Schematic:
        s = Schematic(cell=self, symbol=self.symbol)
        s.a = Net(pin=self.symbol.a)
        s.y = Net(pin=self.symbol.y)
        s.vdd = Net(pin=self.symbol.vdd)
        s.vss = Net(pin=self.symbol.vss)

        nmos = Nmos(l="0.15u", w="0.495u").symbol
        pmos = Pmos(l="0.15u", w="0.99u").symbol

        s.pd = SchemInstance(nmos.portmap(s=s.vss, b=s.vss, g=s.a, d=s.y), pos=Vec2R(3, 2))
        s.pu = SchemInstance(pmos.portmap(s=s.vdd, b=s.vdd, g=s.a, d=s.y), pos=Vec2R(3, 8))

        s.vdd % SchemPort(pos=Vec2R(2, 13), align=East, ref=self.symbol.vdd)
        s.vss % SchemPort(pos=Vec2R(2, 1), align=East, ref=self.symbol.vss)
        s.a % SchemPort(pos=Vec2R(1, 7), align=East, ref=self.symbol.a)
        s.y % SchemPort(pos=Vec2R(9, 7), align=West, ref=self.symbol.y)

        s.vss % SchemWire([Vec2R(2, 1), Vec2R(5, 1), Vec2R(8, 1), Vec2R(8, 4), Vec2R(7, 4)])
        s.vss % SchemWire([Vec2R(5, 1), s.pd.pos + nmos.s.pos])
        s.vdd % SchemWire([Vec2R(2, 13), Vec2R(5, 13), Vec2R(8, 13), Vec2R(8, 10), Vec2R(7, 10)])
        s.vdd % SchemWire([Vec2R(5, 13), s.pu.pos + pmos.s.pos])
        s.a % SchemWire([Vec2R(3, 4), Vec2R(2, 4), Vec2R(2, 7), Vec2R(2, 10), Vec2R(3, 10)])
        s.a % SchemWire([Vec2R(1, 7), Vec2R(2, 7)])
        s.y % SchemWire([Vec2R(5, 6), Vec2R(5, 7), Vec2R(5, 8)])
        s.y % SchemWire([Vec2R(5, 7), Vec2R(9, 7)])

        s.outline = Rect4R(lx=0, ly=1, ux=10, uy=13)
        
        s.check(add_conn_points=True)
        return s

@public
class Ringosc(Cell):
    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.vdd = Pin(pintype=PinType.Inout, align=North)
        s.vss = Pin(pintype=PinType.Inout, align=South)
        s.y = Pin(pintype=PinType.Out, align=East)

        s.place_pins(vpadding=2, hpadding=2)
        return s

    @generate
    def schematic(self) -> Schematic:
        s = Symbol(cell=self, symbol=self.symbol)

        s.y0 = Net()
        s.y1 = Net()
        s.y2 = Net()
        s.vdd = Net()
        s.vss = Net()

        inv = Inv().symbol
        s.i0 = SchemInstance(inv.portmap(vdd=s.vdd, vss=s.vss, a=s.y2, y=s.y0), pos=Vec2R(4, 2))
        s.i1 = SchemInstance(inv.portmap(vdd=s.vdd, vss=s.vss, a=s.y0, y=s.y1), pos=Vec2R(10, 2))
        s.i2 = SchemInstance(inv.portmap(vdd=s.vdd, vss=s.vss, a=s.y1, y=s.y2), pos=Vec2R(16, 2))

        s.vdd % SchemPort(pos=Vec2R(2, 7), align=East)
        s.vss % SchemPort(pos=Vec2R(2, 1), align=East)
        s.y2 % SchemPort(pos=Vec2R(22, 4), align=West)

        s.outline = Rect4R(lx=0, ly=0, ux=24, uy=8)

        s.y0 % SchemWire(vertices=[s.i0.pos+inv.y.pos, s.i1.pos+inv.a.pos])
        s.y1 % SchemWire(vertices=[s.i1.pos+inv.y.pos, s.i2.pos+inv.a.pos])
        s.y2 % SchemWire(vertices=[s.i2.pos+inv.y.pos, Vec2R(21, 4), Vec2R(22, 4)])
        s.y2 % SchemWire(vertices=[Vec2R(21, 4), Vec2R(21, 8), Vec2R(3, 8), Vec2R(3, 4), s.i0.pos+inv.a.pos])

        s.vss % SchemWire(vertices=[Vec2R(2, 1), Vec2R(6, 1), Vec2R(12, 1), Vec2R(18, 1), Vec2R(18, 2)])
        s.vss % SchemWire(vertices=[Vec2R(6, 1), Vec2R(6, 2)])
        s.vss % SchemWire(vertices=[Vec2R(12, 1), Vec2R(12, 2)])

        s.vdd % SchemWire(vertices=[Vec2R(2, 7), Vec2R(6, 7), Vec2R(12, 7), Vec2R(18, 7), Vec2R(18, 6)])
        s.vdd % SchemWire(vertices=[Vec2R(6, 7), Vec2R(6, 6)])
        s.vdd % SchemWire(vertices=[Vec2R(12, 7), Vec2R(12, 6)])

        s.check(add_conn_points=True)
        return s

@public
class And2(Cell):
    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.vdd = Pin(pos=Vec2R(2.5, 5), pintype=PinType.Inout, align=North)
        s.vss = Pin(pos=Vec2R(2.5, 0), pintype=PinType.Inout, align=South)
        s.a = Pin(pos=Vec2R(0, 3), pintype=PinType.In, align=West)
        s.b = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=West)
        s.y = Pin(pos=Vec2R(5, 2.5), pintype=PinType.Out, align=East)

        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1, 2)])
        s % SymbolPoly(vertices=[Vec2R(0, 3), Vec2R(1, 3)])
        s % SymbolPoly(vertices=[Vec2R(4, 2.5), Vec2R(5, 2.5)])
        s % SymbolPoly(vertices=[Vec2R(2.75, 1.25), Vec2R(1, 1.25), Vec2R(1, 3.75), Vec2R(2.75, 3.75)])
        s % SymbolArc(pos=Vec2R(2.75, 2.5), radius=R(1.25), angle_start=R(-0.25), angle_end=R(0.25))
        s.outline = Rect4R(lx=0, ly=0, ux=5, uy=5)

        return s

@public
class Or2(Cell):
    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.vdd = Pin(pos=Vec2R(2.5, 5), pintype=PinType.Inout, align=North)
        s.vss = Pin(pos=Vec2R(2.5, 0), pintype=PinType.Inout, align=South)
        s.a = Pin(pos=Vec2R(0, 3), pintype=PinType.In, align=West)
        s.b = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=West)
        s.y = Pin(pos=Vec2R(5, 2.5), pintype=PinType.Out, align=East)

        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(1.3, 2)])
        s % SymbolPoly(vertices=[Vec2R(0, 3), Vec2R(1.3, 3)])
        s % SymbolPoly(vertices=[Vec2R(4, 2.5), Vec2R(5, 2.5)])
        s % SymbolPoly(vertices=[Vec2R(1, 3.75), Vec2R(1.95, 3.75)])
        s % SymbolPoly(vertices=[Vec2R(1, 1.25), Vec2R(1.95, 1.25)])
        s % SymbolArc(pos=Vec2R(-1.02, 2.5), radius=R(2.4), angle_start=R(-0.085), angle_end=R(0.085))
        s % SymbolArc(pos=Vec2R(1.95, 1.35), radius=R(2.4), angle_start=R(0.08), angle_end=R(0.25))
        s % SymbolArc(pos=Vec2R(1.95, 3.65), radius=R(2.4), angle_start=R(-0.25), angle_end=R(-0.08))
        s.outline = Rect4R(lx=0, ly=0, ux=5, uy=5)

        return s
