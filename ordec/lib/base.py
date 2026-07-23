# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import math

from public import public

from ..core import *

# Passives
# ========

@public
class Res(SimLeafCell):
    """Ideal resistor"""
    r = Parameter(R) #: Resistance in ohm
    def ngspice_current_pins(self):
        return {"i": "p"}
    
    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)

        use_box_symbol = False

        if use_box_symbol:
            # Box symbol
            s % SymbolPoly(vertices=[Vec2R(1.5, 3), Vec2R(2.5, 3), Vec2R(2.5, 1), Vec2R(1.5, 1), Vec2R(1.5, 3)])
            s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)])
            s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)])
        else:
            # Zigzag symbol
            zigzag_height = R(2)
            zigzag_width_half = R(0.625)
            zigzag_start = (R(4) - zigzag_height)/R(2)
            s % SymbolPoly(vertices=[
                Vec2R(2, 0),
                Vec2R(2, zigzag_start),
                Vec2R(2 - zigzag_width_half, zigzag_start+zigzag_height*R(1)/R(12) ),
                Vec2R(2 + zigzag_width_half, zigzag_start+zigzag_height*R(3)/R(12) ),
                Vec2R(2 - zigzag_width_half, zigzag_start+zigzag_height*R(5)/R(12) ),
                Vec2R(2 + zigzag_width_half, zigzag_start+zigzag_height*R(7)/R(12) ),
                Vec2R(2 - zigzag_width_half, zigzag_start+zigzag_height*R(9)/R(12) ),
                Vec2R(2 + zigzag_width_half, zigzag_start+zigzag_height*R(11)/R(12)),
                Vec2R(2, zigzag_start+zigzag_height),
                Vec2R(2, 4),
                ])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        pins = [inst.symbol.p, inst.symbol.m]
        netlister.add(netlister.name_obj(inst, prefix="r"), netlister.portmap(inst, pins), f'r={self.r.compat_str()}')

    @classmethod
    def discoverable_instances(cls):
        return [cls('1k')]

@public
class Cap(SimLeafCell):
    """Ideal capacitor"""
    c = Parameter(R) #: Capacitance in farad
    def ngspice_current_pins(self):
        return {"i": "p"}
    ic = Parameter(R, optional=True) #: Initial condition voltage in volt

    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)

        #Kondensator
        s % SymbolPoly(vertices=[Vec2R(1.25, 1.8), Vec2R(2.75, 1.8)])
        s % SymbolPoly(vertices=[Vec2R(1.25, 2.2), Vec2R(2.75, 2.2)])

        #Linien
        s % SymbolPoly(vertices=[Vec2R(2, 2.2), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(2, 1.8), Vec2R(2, 0)])

        #s % SymbolPoly(vertices=[Vec2R(1.6, 1.05), Vec2R(2, 1.25), Vec2R(1.6, 1.45)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        pins = [inst.symbol.p, inst.symbol.m]
        netlist_str = f'c={self.c.compat_str()}'
        if self.ic is not None:
            netlist_str += f' ic={self.ic.compat_str()}'
        netlister.add(netlister.name_obj(inst, prefix="c"), netlister.portmap(inst, pins), netlist_str)

    @classmethod
    def discoverable_instances(cls):
        return [cls('1p')]

@public
class Ind(SimLeafCell):
    """Ideal inductor"""
    l = Parameter(R) #: Inductance in henry
    def ngspice_current_pins(self):
        return {"branch": "p", "i": "p"}

    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)

        r=0.35
        s % SymbolArc(pos=Vec2R(2, 3-r), radius=R(r), angle_start=R(-0.25), angle_end=R(0.25))
        s % SymbolArc(pos=Vec2R(2, 3-(3*r)), radius=R(r), angle_start=R(-0.25), angle_end=R(0.25))
        s % SymbolArc(pos=Vec2R(2, 3-(5*r)), radius=R(r), angle_start=R(-0.25), angle_end=R(0.25))

        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(2, 3-(6*r)), Vec2R(2, 0)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        pins = [inst.symbol.p, inst.symbol.m]
        netlister.add(netlister.name_obj(inst, prefix="l"), netlister.portmap(inst, pins), f'l={self.l.compat_str()}')

    @classmethod
    def discoverable_instances(cls):
        return [cls('1u')]

# Misc
# ====

@public
class Gnd(SimLeafCell):
    """Global ground connection"""
    def ngspice_current_pins(self):
        return {"branch": "p"}
    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)

        s % SymbolPoly(vertices=[Vec2R(2, 2.5), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(1, 2.5), Vec2R(3, 2.5), Vec2R(2, 1),Vec2R(1, 2.5)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        pins = [inst.symbol.p]
        netlister.add(netlister.name_obj(inst, prefix="v"), netlister.portmap(inst, pins), '0', f'dc 0')

@public
class NoConn(SimLeafCell):
    """No connection"""
    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.a = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=West)

        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(2, 2)])
        s % SymbolPoly(vertices=[Vec2R(1.5, 2.5), Vec2R(2.5, 1.5)])
        s % SymbolPoly(vertices=[Vec2R(1.5, 1.5), Vec2R(2.5, 2.5)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        # We need to name the instance, else highlevel.py raises an error at some point.
        netlister.name_obj(inst)
        # But nothing is added to the netlist.

# Voltage & current sources
# =========================

class AcStimulusMixin:
    """
    Mixin for independent sources that can carry a small-signal stimulus for
    AC analysis (SPICE "ac" specification), orthogonal to the DC/transient
    behavior of the source. In an AC analysis, the stimuli of all sources are
    superposed; typically exactly one source has ac_mag set (usually to 1).

    Subclasses must declare the ac_mag and ac_phase Parameters themselves,
    after their other Parameters: declaring them in this mixin would place
    them first in positional parameter order (inherited parameters precede
    newly declared ones), changing the meaning of e.g. Vdc('1').
    """
    def ngspice_current_pins(self):
        return {"branch": "p"}

    @staticmethod
    def ngspice_wave_args(args):
        """
        Format positional waveform arguments (e.g. for SIN/PULSE): trailing
        unset (None) arguments are omitted so ngspice's defaults apply,
        interior unset arguments are emitted as 0 placeholders.
        """
        args = list(args)
        while args and args[-1] is None:
            args.pop()
        return " ".join((R(0) if a is None else a).compat_str() for a in args)

    def ngspice_dc_spec(self):
        """
        The "dc ..." netlist fragment as list (for Netlister.add, which
        flattens list arguments), empty if dc is unset (ngspice then defaults
        to 0 or to the transient value at t=0). Requires a dc Parameter on
        the subclass.
        """
        if self.dc is None:
            return []
        return [f"dc {self.dc.compat_str()}"]

    def ngspice_ac_spec(self):
        """
        The "ac ..." netlist fragment as list (for Netlister.add, which
        flattens list arguments), empty if ac_mag is unset.
        """
        if self.ac_mag is None:
            return []
        spec = f"ac {self.ac_mag.compat_str()}"
        if self.ac_phase is not None:
            spec += f" {self.ac_phase.compat_str()}"
        return [spec]

@public
class Vdc(AcStimulusMixin, SimLeafCell):
    """DC voltage source"""
    dc = Parameter(R, optional=True) #: DC voltage in volt; 0 if unset.
    ac_mag = Parameter(R, optional=True) #: AC magnitude for small-signal (AC) analysis; no AC stimulus if unset.
    ac_phase = Parameter(R, optional=True) #: AC phase in degrees; 0 if unset.

    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)

        #Kreis
        s % SymbolArc(pos=Vec2R(2, 2), radius=R(1))

        #Linien
        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)])

        
        #+
        s % SymbolPoly(vertices=[Vec2R(2, 2.2), Vec2R(2, 2.8)])
        s % SymbolPoly(vertices=[Vec2R(1.7, 2.5), Vec2R(2.3, 2.5)])
        #-
        s % SymbolPoly(vertices=[Vec2R(1.65, 1.5), Vec2R(2.35, 1.5)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        pins = [inst.symbol.p, inst.symbol.m]
        netlister.add(
            netlister.name_obj(inst, prefix="v"),
            netlister.portmap(inst, pins),
            self.ngspice_dc_spec(),
            self.ngspice_ac_spec(),
        )

    @classmethod
    def discoverable_instances(cls):
        return [cls('1')]

@public
class Idc(AcStimulusMixin, SimLeafCell):
    """DC current source"""
    dc = Parameter(R, optional=True) #: DC current in ampere; 0 if unset.
    ac_mag = Parameter(R, optional=True) #: AC magnitude for small-signal (AC) analysis; no AC stimulus if unset.
    ac_phase = Parameter(R, optional=True) #: AC phase in degrees; 0 if unset.

    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)
    
        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)])
        s % SymbolArc(pos=Vec2R(2, 2), radius=R(1))

        # Arrow:
        b = Vec2R(2, 1.25)
        s % SymbolPoly(vertices=[b, Vec2R(2, 2.75)])
        s % SymbolPoly(vertices=[b + Vec2R(-0.5, 0.5), b, b + Vec2R(0.5, 0.5)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        pins = [inst.symbol.p, inst.symbol.m]
        netlister.add(
            netlister.name_obj(inst, prefix="i"),
            netlister.portmap(inst, pins),
            self.ngspice_dc_spec(),
            self.ngspice_ac_spec(),
        )

    @classmethod
    def discoverable_instances(cls):
        return [cls('1u')]

@public
class Vpwl(AcStimulusMixin, SimLeafCell):
    """Piecewise linear voltage source (SPICE PWL)."""
    V = Parameter(tuple) #: Tuple of (time, voltage) tuples defining the waveform.
    ac_mag = Parameter(R, optional=True) #: AC magnitude for small-signal (AC) analysis; no AC stimulus if unset.
    ac_phase = Parameter(R, optional=True) #: AC phase in degrees; 0 if unset.

    @generate
    def symbol(self) -> Symbol:
        """ Defines the schematic symbol for the PWL source. """
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)

        s % SymbolArc(pos=Vec2R(2, 2), radius=R(1))

        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)]) # To positive pin
        s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)]) # To negative pin

        s % SymbolPoly(vertices=[
            Vec2R(1.4, 1.8),
            Vec2R(1.7, 2.4),
            Vec2R(2.0, 1.6),
            Vec2R(2.3, 2.4),
            Vec2R(2.6, 2.4),

        ])
        #+
        s % SymbolPoly(vertices=[Vec2R(2, 2.3), Vec2R(2, 2.9)])
        s % SymbolPoly(vertices=[Vec2R(1.7, 2.6), Vec2R(2.3, 2.6)])
        #-
        s % SymbolPoly(vertices=[Vec2R(1.65, 1.3), Vec2R(2.35, 1.3)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        pins = [inst.symbol.p, inst.symbol.m]

        V_list = self.V
        # Coerce values to Rational
        V_rational = [(R(t), R(v)) for t, v in V_list]

        # Flatten pairs
        pwl_args = " ".join([f"{v.compat_str()}" for t, v_val in V_rational for v in (t, v_val)])

        netlister.add(
            netlister.name_obj(inst, prefix="v"),
            netlister.portmap(inst, pins),
            self.ngspice_ac_spec(),
            f'PWL({pwl_args})'
        )

@public
class Vpulse(AcStimulusMixin, SimLeafCell):
    """Pulse voltage source (SPICE PULSE)."""
    initial_value = Parameter(R, optional=True) #: Voltage before pulse; 0 if unset.
    pulsed_value = Parameter(R) #: Voltage during pulse.
    delay_time = Parameter(R, optional=True) #: Delay before first pulse; 0 if unset.
    rise_time = Parameter(R, optional=True) #: Rise time; ngspice default if unset.
    fall_time = Parameter(R, optional=True) #: Fall time; ngspice default if unset.
    pulse_width = Parameter(R, optional=True) #: Pulse width; ngspice default if unset.
    period = Parameter(R, optional=True) #: Repetition period; ngspice default if unset.
    ac_mag = Parameter(R, optional=True) #: AC magnitude for small-signal (AC) analysis; no AC stimulus if unset.
    ac_phase = Parameter(R, optional=True) #: AC phase in degrees; 0 if unset.

    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)

        s % SymbolArc(pos=Vec2R(2, 2), radius=R(1))

        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)])  # To positive pin 'p'
        s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)])  # To negative pin 'm'

        # Pulse symbol
        s % SymbolPoly(vertices=[
            Vec2R(1.5, 1.75),
            Vec2R(1.5, 2.25),
            Vec2R(2.0, 2.25),
            Vec2R(2.0, 1.75),
            Vec2R(2.5, 1.75),
            Vec2R(2.5, 2.25)
        ])


        # +
        s % SymbolPoly(vertices=[Vec2R(2, 2.55), Vec2R(2, 2.95)]) # Vertical bar
        s % SymbolPoly(vertices=[Vec2R(1.8, 2.75), Vec2R(2.2, 2.75)]) # Horizontal bar
        # -
        s % SymbolPoly(vertices=[Vec2R(1.8, 1.2), Vec2R(2.2, 1.2)]) # Horizontal bar

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        pins = [inst.symbol.p, inst.symbol.m]

        tran_spec = "PULSE({})".format(self.ngspice_wave_args([
            self.initial_value, self.pulsed_value, self.delay_time,
            self.rise_time, self.fall_time, self.pulse_width, self.period,
        ]))

        netlister.add(
            netlister.name_obj(inst, prefix="v"),
            netlister.portmap(inst, pins),
            [] if self.initial_value is None else [f"dc {self.initial_value.compat_str()}"],
            self.ngspice_ac_spec(),
            tran_spec
        )

@public
class Vsin(AcStimulusMixin, SimLeafCell):
    """Sinusoidal voltage source (SPICE SIN)."""
    dc = Parameter(R, optional=True) #: DC offset; 0 if unset.
    amplitude = Parameter(R) #: Peak amplitude of the sinusoid (transient analysis only).
    freq = Parameter(R) #: Frequency in Hz.
    delay = Parameter(R, optional=True) #: Delay before start of sinusoid; 0 if unset.
    damping = Parameter(R, optional=True) #: Exponential damping factor; 0 if unset.
    ac_mag = Parameter(R, optional=True) #: AC magnitude for small-signal (AC) analysis; no AC stimulus if unset.
    ac_phase = Parameter(R, optional=True) #: AC phase in degrees; 0 if unset.

    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)

        s % SymbolArc(pos=Vec2R(2, 2), radius=R(1))

        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)]) # To positive pin 'p'
        s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)]) # To negative pin 'm'

        sine_wave_points = [
            Vec2R(1.2 + 0.1 * t, 2.0 + 0.6 * math.sin(math.pi * t / 4))
            for t in range(17)
        ]
        s % SymbolPoly(vertices=sine_wave_points)

        # +
        s % SymbolPoly(vertices=[Vec2R(2, 2.5), Vec2R(2, 2.9)]) # Vertical bar
        s % SymbolPoly(vertices=[Vec2R(1.8, 2.75), Vec2R(2.2, 2.75)]) # Horizontal bar
        # -
        s % SymbolPoly(vertices=[Vec2R(1.8, 1.2), Vec2R(2.2, 1.2)]) # Horizontal bar

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        pins = [inst.symbol.p, inst.symbol.m]

        tran_spec = "SIN({})".format(self.ngspice_wave_args([
            self.dc, self.amplitude, self.freq, self.delay, self.damping,
        ]))

        netlister.add(
            netlister.name_obj(inst, prefix="v"),
            netlister.portmap(inst, pins),
            self.ngspice_dc_spec(),
            self.ngspice_ac_spec(),
            tran_spec
        )

@public
class Ipwl(AcStimulusMixin, SimLeafCell):
    """Piecewise linear current source (SPICE PWL)."""
    I = Parameter(tuple) #: Tuple of (time, current) tuples defining the waveform.
    ac_mag = Parameter(R, optional=True) #: AC magnitude for small-signal (AC) analysis; no AC stimulus if unset.
    ac_phase = Parameter(R, optional=True) #: AC phase in degrees; 0 if unset.

    @generate
    def symbol(self) -> Symbol:
        """ Defines the schematic symbol for the PWL current source. """
        s = Symbol(cell=self)

        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)
        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)

        s % SymbolArc(pos=Vec2R(2, 2), radius=R(1))
        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)]) # To positive pin 'p'
        s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)]) # To negative pin 'm'

        s % SymbolPoly(vertices=[
            Vec2R(1.4, 1.7),
            Vec2R(1.7, 2.3),
            Vec2R(2.0, 1.5),
            Vec2R(2.3, 2.3),
            Vec2R(2.6, 2.3),
        ])

        arrow_tip_y = 2.7
        arrow_base_y = 2.3
        arrow_barb_y = 2.5
        arrow_width = 0.2

        # Shaft
        s % SymbolPoly(vertices=[Vec2R(2, arrow_base_y), Vec2R(2, arrow_tip_y)])
        # Head
        s % SymbolPoly(vertices=[
            Vec2R(2 - arrow_width, arrow_barb_y), # Left barb base
            Vec2R(2, arrow_tip_y),                # Tip
            Vec2R(2 + arrow_width, arrow_barb_y)  # Right barb base
        ])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        pins = [inst.symbol.p, inst.symbol.m]

        I_list = self.I
        # Coerce values to Rational
        I_rational = [(R(t), R(v)) for t, v in I_list]

        # Flatten pairs
        pwl_values = " ".join([f"{val.compat_str()}" for t, v_val in I_rational for val in (t, v_val)])

        netlister.add(
            netlister.name_obj(inst, prefix="i"),
            netlister.portmap(inst, pins),
            self.ngspice_ac_spec(),
            f'PWL({pwl_values})'
        )

@public
class Ipulse(AcStimulusMixin, SimLeafCell):
    """Pulse current source (SPICE PULSE)."""
    initial_value = Parameter(R, optional=True) #: Current before pulse; 0 if unset.
    pulsed_value = Parameter(R) #: Current during pulse.
    delay_time = Parameter(R, optional=True) #: Delay before first pulse; 0 if unset.
    rise_time = Parameter(R, optional=True) #: Rise time; ngspice default if unset.
    fall_time = Parameter(R, optional=True) #: Fall time; ngspice default if unset.
    pulse_width = Parameter(R, optional=True) #: Pulse width; ngspice default if unset.
    period = Parameter(R, optional=True) #: Repetition period; ngspice default if unset.
    ac_mag = Parameter(R, optional=True) #: AC magnitude for small-signal (AC) analysis; no AC stimulus if unset.
    ac_phase = Parameter(R, optional=True) #: AC phase in degrees; 0 if unset.

    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)

        # Draw the symbol
        # Circle
        s % SymbolArc(pos=Vec2R(2, 2), radius=R(1))

        # Lines
        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)]) # To positive pin 'p'
        s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)]) # To negative pin 'm'

        # Pulse symbol
        s % SymbolPoly(vertices=[
            Vec2R(1.5, 1.3),
            Vec2R(1.5, 2.3),
            Vec2R(2.0, 2.3),
            Vec2R(2.0, 1.3),
            Vec2R(2.5, 1.3),
            Vec2R(2.5, 2.3)
        ])

        # Arrow pointing UP (from m towards p)
        arrow_tip_y = 3.0
        arrow_base_y = 2.5
        arrow_barb_y = 2.7
        arrow_width = 0.3
        s % SymbolPoly(vertices=[Vec2R(2, arrow_base_y), Vec2R(2, arrow_tip_y)]) # Shaft
        s % SymbolPoly(vertices=[
            Vec2R(2 - arrow_width, arrow_barb_y), # Left barb base
            Vec2R(2, arrow_tip_y),                # Tip
            Vec2R(2 + arrow_width, arrow_barb_y)  # Right barb base
        ])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        pins = [inst.symbol.p, inst.symbol.m]

        tran_spec = "PULSE({})".format(self.ngspice_wave_args([
            self.initial_value, self.pulsed_value, self.delay_time,
            self.rise_time, self.fall_time, self.pulse_width, self.period,
        ]))

        netlister.add(
            netlister.name_obj(inst, prefix="i"),
            netlister.portmap(inst, pins),
            [] if self.initial_value is None else [f"dc {self.initial_value.compat_str()}"],
            self.ngspice_ac_spec(),
            tran_spec
        )

@public
class Isin(AcStimulusMixin, SimLeafCell):
    """Sinusoidal current source (SPICE SIN)."""
    dc = Parameter(R, optional=True) #: DC offset; 0 if unset.
    amplitude = Parameter(R) #: Peak amplitude of the sinusoid (transient analysis only).
    freq = Parameter(R) #: Frequency in Hz.
    delay = Parameter(R, optional=True) #: Delay before start of sinusoid; 0 if unset.
    damping = Parameter(R, optional=True) #: Exponential damping factor; 0 if unset.
    ac_mag = Parameter(R, optional=True) #: AC magnitude for small-signal (AC) analysis; no AC stimulus if unset.
    ac_phase = Parameter(R, optional=True) #: AC phase in degrees; 0 if unset.

    @generate
    def symbol(self) -> Symbol:
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=North)

        # Circle
        s % SymbolArc(pos=Vec2R(2, 2), radius=R(1))

        # Lines
        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)]) # To positive pin 'p'
        s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)]) # To negative pin 'm'

        # Sinusoidal symbol
        sine_wave_points = [
            Vec2R(1.2 + 0.1 * t, 1.9 + 0.6 * math.sin(math.pi * t / 4))
            for t in range(17)
        ]
        s % SymbolPoly(vertices=sine_wave_points)

        # Arrow pointing UP
        arrow_tip_y = 3.0
        arrow_base_y = 2.5
        arrow_barb_y = 2.7
        arrow_width = 0.3

        s % SymbolPoly(vertices=[Vec2R(2, arrow_base_y), Vec2R(2, arrow_tip_y)]) # Shaft
        s % SymbolPoly(vertices=[
            Vec2R(2 - arrow_width, arrow_barb_y), # Left barb base
            Vec2R(2, arrow_tip_y),                # Tip
            Vec2R(2 + arrow_width, arrow_barb_y)  # Right barb base
        ])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def ngspice_netlist(self, netlister, inst):
        pins = [inst.symbol.p, inst.symbol.m]

        tran_spec = "SIN({})".format(self.ngspice_wave_args([
            self.dc, self.amplitude, self.freq, self.delay, self.damping,
        ]))

        netlister.add(
            netlister.name_obj(inst, prefix="i"),
            netlister.portmap(inst, pins),
            self.ngspice_dc_spec(),
            self.ngspice_ac_spec(),
            tran_spec
        )
