from ordec import Cell, Schematic, Vec2R, Rect4R, Rational as R, SchemPoly, SchemRect, SchemInstance, Net, SimHierarchy, generate, helpers
from ordec.sim2.sim_hierarchy import HighlevelSim
from ordec.lib import Res, Gnd, Vdc

class VoltageDivider(Cell):
    @generate(Schematic)
    def schematic(self, node):
        node.vdd = Net()
        node.vss = Net()
        node.a = Net()
        node.b = Net()

        s_vdc = Vdc(dc=R(1)).symbol
        s_gnd = Gnd().symbol
        s_res = Res(r=R(100)).symbol

        node % SchemInstance(pos=Vec2R(x=5,y=0), ref=s_gnd, portmap={s_gnd.p: node.vss})
        node % SchemInstance(pos=Vec2R(x=0,y=6), ref=s_vdc, portmap={s_vdc.m: node.vss, s_vdc.p: node.vdd})
        node % SchemInstance(pos=Vec2R(x=5,y=6), ref=s_res, portmap={s_res.m: node.vss, s_res.p: node.a})
        node % SchemInstance(pos=Vec2R(x=5,y=11), ref=s_res, portmap={s_res.m: node.a,  s_res.p: node.b})
        node % SchemInstance(pos=Vec2R(x=5,y=16), ref=s_res, portmap={s_res.m: node.b,  s_res.p: node.vdd})
        
        node.vss % SchemPoly(vertices=[Vec2R(x=7, y=4), Vec2R(x=7, y=5), Vec2R(x=7, y=6)])
        node.vss % SchemPoly(vertices=[Vec2R(x=2, y=6), Vec2R(x=2, y=5), Vec2R(x=7, y=5)])
        node.vdd % SchemPoly(vertices=[Vec2R(x=2, y=10), Vec2R(x=2, y=21), Vec2R(x=7, y=21), Vec2R(x=7, y=20)])
        node.a % SchemPoly(vertices=[Vec2R(x=7, y=10), Vec2R(x=7, y=11)])
        node.b % SchemPoly(vertices=[Vec2R(x=7, y=15), Vec2R(x=7, y=16)])
        
        node.outline = node % SchemRect(pos=Rect4R(lx=0, ly=0, ux=9, uy=21))

        helpers.schem_check(node, add_conn_points=True)

    @generate(SimHierarchy)
    def sim_dc(self, node):
        sim = HighlevelSim(self.schematic, node)
        sim.op()
