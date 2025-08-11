# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from public import public

from ..core import *
from .. import helpers

# Passives
# ========

@public
class Res(Cell):
    r = Parameter(R)
    alt_symbol = Parameter(bool, optional=True)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)
        
        if self.alt_symbol:
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
    
    def netlist_ngspice(self, netlister, inst, schematic):
        pins = [inst.symbol.p, inst.symbol.m]
        netlister.add(netlister.name_obj(inst, schematic, prefix="r"), netlister.portmap(inst, pins), f'r={self.r.compat_str()}')

    @classmethod
    def discoverable_instances(cls):
        return [cls('1k')]

@public
class Cap(Cell):
    c = Parameter(R)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)
        
        #Kondensator
        s % SymbolPoly(vertices=[Vec2R(1.25, 1.8), Vec2R(2.75, 1.8)])
        s % SymbolPoly(vertices=[Vec2R(1.25, 2.2), Vec2R(2.75, 2.2)])
        
        #Linien
        s % SymbolPoly(vertices=[Vec2R(2, 2.2), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(2, 1.8), Vec2R(2, 0)])

        #s % SymbolPoly(vertices=[Vec2R(1.6, 1.05), Vec2R(2, 1.25), Vec2R(1.6, 1.45)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    @classmethod
    def discoverable_instances(cls):
        return [cls('1p')]

@public
class Ind(Cell):
    l = Parameter(R)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)
        
        #Kondensator
        #s % SymbolPoly(vertices=[Vec2R(1.25, 1.8), Vec2R(2.75, 1.8)])
        #s % SymbolPoly(vertices=[Vec2R(1.25, 2.2), Vec2R(2.75, 2.2)])
        r=0.35
        s % SymbolArc(pos=Vec2R(2, 3-r), radius=R(r), angle_start=R(-0.25), angle_end=R(0.25))
        s % SymbolArc(pos=Vec2R(2, 3-(3*r)), radius=R(r), angle_start=R(-0.25), angle_end=R(0.25))
        s % SymbolArc(pos=Vec2R(2, 3-(5*r)), radius=R(r), angle_start=R(-0.25), angle_end=R(0.25))
        
        #Linien
        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(2, 3-(6*r)), Vec2R(2, 0)])

        #s % SymbolPoly(vertices=[Vec2R(1.6, 1.05), Vec2R(2, 1.25), Vec2R(1.6, 1.45)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    @classmethod
    def discoverable_instances(cls):
        return [cls('1u')]
 
# Misc
# ====

@public
class Gnd(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)
        
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)  

        #Linien
        s % SymbolPoly(vertices=[Vec2R(2, 2.5), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(1, 2.5), Vec2R(3, 2.5), Vec2R(2, 1),Vec2R(1, 2.5)])

        #s % SymbolPoly(vertices=[Vec2R(1.6, 1.05), Vec2R(2, 1.25), Vec2R(1.6, 1.45)])
        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s
 
    def netlist_ngspice(self, netlister, inst, schematic):
        pins = [inst.symbol.p]
        netlister.add(netlister.name_obj(inst, schematic, prefix="v"), netlister.portmap(inst, pins), '0', f'dc 0')

@public
class NoConn(Cell):
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.a = Pin(pos=Vec2R(0, 2), pintype=PinType.In, align=Orientation.West)

        s % SymbolPoly(vertices=[Vec2R(0, 2), Vec2R(2, 2)])
        s % SymbolPoly(vertices=[Vec2R(1.5, 2.5), Vec2R(2.5, 1.5)])
        s % SymbolPoly(vertices=[Vec2R(1.5, 1.5), Vec2R(2.5, 2.5)])

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def netlist_ngspice(self, netlister, inst, schematic):
        pass

# Voltage & current sources
# =========================

@public
class Vdc(Cell):
    dc = Parameter(R)
    alt_symbol = Parameter(bool, optional=True)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)
        
        #Kreis
        s % SymbolArc(pos=Vec2R(2, 2), radius=R(1))
        
        #Linien
        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)])
        s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)])

        if self.alt_symbol:
            #Pfeil
            s % SymbolPoly(vertices=[Vec2R(0.5, 1), Vec2R(0.5, 3)])
            s % SymbolPoly(vertices=[Vec2R(0.5, 3)+Vec2R(-0.2, -0.2), Vec2R(0.5, 3)])
            s % SymbolPoly(vertices=[Vec2R(0.5, 3)+Vec2R(0.2, -0.2), Vec2R(0.5, 3)])
    
            #+/-
            s % SymbolPoly(vertices=[Vec2R(1.5, 2.1), Vec2R(2.5, 2.1)])
            s % SymbolPoly(vertices=[Vec2R(1.5, 1.9), Vec2R(1.8, 1.9)])
            s % SymbolPoly(vertices=[Vec2R(1.9, 1.9), Vec2R(2.1, 1.9)])
            s % SymbolPoly(vertices=[Vec2R(2.2, 1.9), Vec2R(2.5, 1.9)])
            #s % SymbolPoly(vertices=[Vec2R(1.6, 1.05), Vec2R(2, 1.25), Vec2R(1.6, 1.45)])
        else:
            #+
            s % SymbolPoly(vertices=[Vec2R(2, 2.2), Vec2R(2, 2.8)])
            s % SymbolPoly(vertices=[Vec2R(1.7, 2.5), Vec2R(2.3, 2.5)])
            #-
            s % SymbolPoly(vertices=[Vec2R(1.65, 1.5), Vec2R(2.35, 1.5)])
            
        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s
 
    def netlist_ngspice(self, netlister, inst, schematic):
        pins = [inst.symbol.p, inst.symbol.m]
        netlister.add(netlister.name_obj(inst, schematic, prefix="v"), netlister.portmap(inst, pins) , f'dc {self.dc.compat_str()}')

    @classmethod
    def discoverable_instances(cls):
        return [cls('1')]

@public
class Idc(Cell):
    dc = Parameter(R)
    alt_symbol = Parameter(bool, optional=True)

    @generate
    def symbol(self):
        s = Symbol(cell=self)
        
        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)
        
        if self.alt_symbol:
             #Kreis
            s % SymbolArc(pos=Vec2R(2, 4-2*0.7), radius=R(7,10))
            s % SymbolArc(pos=Vec2R(2, 0+2*0.7), radius=R(7,10))
            
            #Linien
            s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)])
            s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)])
            #Pfeil
            s % SymbolPoly(vertices=[Vec2R(0.5, 1), Vec2R(0.5, 3)])
            s % SymbolPoly(vertices=[Vec2R(0.5, 1)+Vec2R(-0.2, 0.2), Vec2R(0.5, 1)])
            s % SymbolPoly(vertices=[Vec2R(0.5, 1)+Vec2R(0.2, 0.2), Vec2R(0.5, 1)])

        else:
            s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)])
            s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)])
            s % SymbolArc(pos=Vec2R(2, 2), radius=R(1))

            # Pfeil:
            b = Vec2R(2, 1.25)
            s % SymbolPoly(vertices=[b, Vec2R(2, 2.75)])
            s % SymbolPoly(vertices=[b + Vec2R(-0.5, 0.5), b, b + Vec2R(0.5, 0.5)])
        
        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

    def netlist_ngspice(self, netlister, inst, schematic):
        pins = [inst.symbol.p, inst.symbol.m]
        netlister.add(netlister.name_obj(inst, schematic, prefix="i"), netlister.portmap(inst, pins) , f'dc {self.dc.compat_str()}')

    @classmethod
    def discoverable_instances(cls):
        return [cls('1u')]

@public
class PieceWiseLinearVoltageSource(Cell):
    """
    Represents a Piecewise Linear Voltage Source.
    Expects a parameter 'V' which is a list of (time, voltage) tuples.
    Example: V=[(0, 0), (1e-9, 1.8), (5e-9, 1.8), (6e-9, 0)]
    """
    
    @generate
    def symbol(self):
        """ Defines the schematic symbol for the PWL source. """
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)
        
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

@public
class PulseVoltageSource(Cell):
    """
    Represents a Pulse Voltage Source.
    Requires parameters: initial_value, pulsed_value, delay_time,
                         rise_time, fall_time, pulse_width, period.
    """
    
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)

        s % SymbolArc(pos=Vec2R(2, 2), radius=R(1))

        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)])  # To positive pin 'p'
        s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)])  # To negative pin 'm'

        # Pulse symbol
        s % SymbolPoly(vertices=[
            Vec2R(1.5, 1.5),
            Vec2R(1.5, 2.5),
            Vec2R(2.0, 2.5),
            Vec2R(2.0, 1.5),
            Vec2R(2.5, 1.5),
            Vec2R(2.5, 2.5)
        ])


        # + 
        s % SymbolPoly(vertices=[Vec2R(2, 2.55), Vec2R(2, 2.95)]) # Vertical bar
        s % SymbolPoly(vertices=[Vec2R(1.8, 2.75), Vec2R(2.2, 2.75)]) # Horizontal bar
        # - 
        s % SymbolPoly(vertices=[Vec2R(1.8, 1.2), Vec2R(2.2, 1.2)]) # Horizontal bar

        s.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

@public
class SinusoidalVoltageSource(Cell):
    """
    Represents a Sinusoidal Voltage Source.
    Requires parameters: offset, amplitude, frequency, delay.
    Optional parameter: damping_factor (defaults to 0).
    """
    offset = Parameter(R, optional=True)
    amplitude = Parameter(R)  
    frequency = Parameter(R)
    delay = Parameter(R, optional=True)
    damping_factor = Parameter(R, optional=True)

    @generate
    def symbol(self):
        s = Symbol(cell=self)

        import numpy as np # TODO: Get rid of numpy dependency
        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)

        s % SymbolArc(pos=Vec2R(2, 2), radius=R(1))

        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)]) # To positive pin 'p'
        s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)]) # To negative pin 'm'

        sine_wave_points = [
            Vec2R(1.2 + 0.1 * t, 2.0 + 0.6 * np.sin(np.pi * t / 4))
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

    def netlist_ngspice(self, netlister, inst, schematic):
        pins = [inst.symbol.p, inst.symbol.m]
        # NGSPICE sine format: SIN(VOFF VAMP FREQ TD THETA PHASE)
        # VOFF = offset voltage, VAMP = amplitude, FREQ = frequency 
        # TD = delay, THETA = damping factor, PHASE = phase (default 0)
        offset = self.params.get('offset', R(0))
        delay = self.params.get('delay', R(0))
        damping = self.params.get('damping_factor', R(0))
        netlister.add(
            netlister.name_obj(inst, schematic, prefix="v"), 
            netlister.portmap(inst, pins),
            f'SIN({offset.compat_str()} {self.amplitude.compat_str()} {self.frequency.compat_str()} {delay.compat_str()} {damping.compat_str()})'
        )

@public
class PieceWiseLinearCurrentSource(Cell):
    @generate
    def symbol(self):
        """ Defines the schematic symbol for the PWL current source. """
        s = Symbol(cell=self)

        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)
        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)

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

@public
class PulseCurrentSource(Cell):
    """
    Represents a Pulse Current Source.
    Uses a symbol with an internal pulse shape and an arrow indicating direction.
    Requires parameters: initial_value, pulsed_value, delay_time,
                         rise_time, fall_time, pulse_width, period.
    """
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)

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

        s.outline = s % Rect4R(lx=0, ly=0, ux=4, uy=4)
        return s

@public
class SinusoidalCurrentSource(Cell):
    """
    Represents a Sinusoidal Current Source.
    Uses a symbol with an internal sine shape and an arrow indicating direction.
    Requires parameters: offset, amplitude, frequency, delay.
    Optional parameter: damping_factor (defaults to 0).
    """
    @generate
    def symbol(self):
        s = Symbol(cell=self)

        import numpy as np # TODO: Get rid of numpy dependency
        s.m = Pin(pos=Vec2R(2, 0), pintype=PinType.Inout, align=Orientation.South)
        s.p = Pin(pos=Vec2R(2, 4), pintype=PinType.Inout, align=Orientation.North)

        # Circle
        s % SymbolArc(pos=Vec2R(2, 2), radius=R(1))

        # Lines
        s % SymbolPoly(vertices=[Vec2R(2, 3), Vec2R(2, 4)]) # To positive pin 'p'
        s % SymbolPoly(vertices=[Vec2R(2, 1), Vec2R(2, 0)]) # To negative pin 'm'

        # Sinusoidal symbol 
        sine_wave_points = [
            Vec2R(1.2 + 0.1 * t, 1.9 + 0.6 * np.sin(np.pi * t / 4))
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
