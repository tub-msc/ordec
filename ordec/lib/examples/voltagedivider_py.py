from ordec.base import *
from ordec import helpers
from ordec.sim2.sim_hierarchy import HighlevelSim
from ordec.lib import Res, Gnd, Vdc

class VoltageDivider(Cell):
    @generate
    def schematic(self):
        s = Schematic(cell=self, outline=Rect4R(lx=0, ly=0, ux=9, uy=21))
        s.vdd = Net()
        s.vss = Net()
        s.a = Net()
        s.b = Net()

        res = Res(r=R(100)).symbol

        s.I0 = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(x=5,y=0))
        s.I1 = SchemInstance(Vdc(dc=R(1)).symbol.portmap(m=s.vss, p=s.vdd), pos=Vec2R(x=0,y=6))
        s.I2 = SchemInstance(res.portmap(m=s.vss, p=s.a), pos=Vec2R(x=5,y=6))
        s.I3 = SchemInstance(res.portmap(m=s.a, p=s.b), pos=Vec2R(x=5,y=11))
        s.I4 = SchemInstance(res.portmap(m=s.b, p=s.vdd), pos=Vec2R(x=5,y=16))
        
        s.vss % SchemWire([Vec2R(x=7, y=4), Vec2R(x=7, y=5), Vec2R(x=7, y=6)])
        s.vss % SchemWire([Vec2R(x=2, y=6), Vec2R(x=2, y=5), Vec2R(x=7, y=5)])
        s.vdd % SchemWire([Vec2R(x=2, y=10), Vec2R(x=2, y=21), Vec2R(x=7, y=21), Vec2R(x=7, y=20)])
        s.a % SchemWire([Vec2R(x=7, y=10), Vec2R(x=7, y=11)])
        s.b % SchemWire([Vec2R(x=7, y=15), Vec2R(x=7, y=16)])
        helpers.schem_check(s, add_conn_points=True)
        return s

    @generate
    def sim_dc(self):
        s = SimHierarchy()
        sim = HighlevelSim(self.schematic, s)
        sim.op()
        return s
