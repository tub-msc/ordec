from ordec.core import *
from ordec.sim import Simulator
from ordec.lib import Res, Cap, Gnd, Vpulse, Vsin

class RC(Cell):
    pulse_source = True

    @generate
    def schematic(self):
        s = Schematic(cell=self)
        s.vdd = Net()
        s.vss = Net()
        s.a = Net()

        res = Res(r=100).symbol
        cap = Cap(c="100u").symbol


        if self.pulse_source:
            vcc = Vpulse(
                initial_value=0,
                pulsed_value=1,
                rise_time="1n",
                pulse_width=1,
                period=2,
            ).symbol
        else:
            vcc = Vsin(
                ac=1,
                freq="1k"
            ).symbol


        s.gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(6, -1))
        s.vcc = SchemInstance(vcc.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 5))
        s.res = SchemInstance(res.portmap(m=s.a, p=s.vdd), pos=Vec2R(10, 8), orientation = West)
        s.cap = SchemInstance(cap.portmap(m=s.vss, p=s.a), pos=Vec2R(12, 5))

        s.auto_wire()
        s.check(add_conn_points=True, add_terminal_taps=True)
        return s

    @generate(auto_refresh=False)
    def sim_op(self):
        s = SimHierarchy.from_schematic(self.schematic)
        sim = Simulator(s)
        sim.op()
        return s

    @generate
    def sim_tran(self):
        s = SimHierarchy.from_schematic(self.schematic)
        sim = Simulator(s)
        sim.tran('10u', '50m')
        return s

    @generate
    def sim_ac(self):
        s = SimHierarchy.from_schematic(self.schematic)
        sim = Simulator(s)
        sim.ac('dec', '10', '1', '10M')
        return s
