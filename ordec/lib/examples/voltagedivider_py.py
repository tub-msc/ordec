from ordec.core import *
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

        s.I0 = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(5, 0))
        s.I1 = SchemInstance(Vdc(dc=R(1)).symbol.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 6))
        s.I2 = SchemInstance(res.portmap(m=s.vss, p=s.a), pos=Vec2R(5, 6))
        s.I3 = SchemInstance(res.portmap(m=s.a, p=s.b), pos=Vec2R(5, 11))
        s.I4 = SchemInstance(res.portmap(m=s.b, p=s.vdd), pos=Vec2R(5, 16))
        
        s.vss % SchemWire([Vec2R(7, 4), Vec2R(7, 5), Vec2R(7, 6)])
        s.vss % SchemWire([Vec2R(2, 6), Vec2R(2, 5), Vec2R(7, 5)])
        s.vdd % SchemWire([Vec2R(2, 10), Vec2R(2, 21), Vec2R(7, 21), Vec2R(7, 20)])
        s.a % SchemWire([Vec2R(7, 10), Vec2R(7, 11)])
        s.b % SchemWire([Vec2R(7, 15), Vec2R(7, 16)])
        helpers.schem_check(s, add_conn_points=True)
        return s

    @generate(auto_refresh=False)
    def sim_dc(self):
        s = SimHierarchy()
        sim = HighlevelSim(self.schematic, s)
        sim.op()
        return s
