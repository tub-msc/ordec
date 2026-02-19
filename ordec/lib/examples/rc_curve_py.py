from ordec.core import *
from ordec.schematic import helpers
from ordec.sim.sim_hierarchy import HighlevelSim
from ordec.schematic.routing import schematic_routing
from ordec.lib import Res, Cap, Gnd, PulseVoltageSource, SinusoidalVoltageSource

class RC(Cell):
    pulse_source = True

    @generate
    def schematic(self):
        s = Schematic(cell=self)
        s.vdd = Net()
        s.vss = Net()
        s.a = Net()

        res = Res(r=R("100")).symbol
        cap = Cap(c=R("100u")).symbol


        if self.pulse_source:
            vcc = PulseVoltageSource(
                initial_value=R(0),
                pulsed_value=R(1),
                rise_time=R("1n"),
                pulse_width=R("1"),
                period=R("2"),
            ).symbol
        else:
            vcc = SinusoidalVoltageSource(
                amplitude=R(1),
                frequency=R("1k")
            ).symbol


        s.gnd = SchemInstance(Gnd().symbol.portmap(p=s.vss), pos=Vec2R(6, -1))
        s.vcc = SchemInstance(vcc.portmap(m=s.vss, p=s.vdd), pos=Vec2R(0, 5))
        s.res = SchemInstance(res.portmap(m=s.a, p=s.vdd), pos=Vec2R(10, 8), orientation = Orientation.West)
        s.cap = SchemInstance(cap.portmap(m=s.vss, p=s.a), pos=Vec2R(12, 5))

        s.outline = schematic_routing(s)
        helpers.schem_check(s, add_conn_points=True, add_terminal_taps=True)
        return s

    @generate(auto_refresh=False)
    def sim_dc(self):
        s = SimHierarchy()
        sim = HighlevelSim(self.schematic, s)
        sim.op()
        return s

    @generate
    def sim_tran(self):
        s = SimHierarchy()
        sim = HighlevelSim(self.schematic, s)
        sim.tran('10u', '50m')
        return s

    @generate
    def sim_ac(self):
        s = SimHierarchy()
        sim = HighlevelSim(self.schematic, s)
        sim.ac('dec', '10', '1', '10meg')
        return s

