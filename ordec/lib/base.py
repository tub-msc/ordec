# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..base import *
from .. import helpers

__all__=["Res", "Cap", "Ind", "Gnd", "NoConn", "Vdc", "Idc",
    "PieceWiseLinearVoltageSource", "PulseVoltageSource", "SinusoidalVoltageSource",
    "PieceWiseLinearCurrentSource", "PulseCurrentSource", "SinusoidalCurrentSource"]

# Passives
# ========

class Res(Cell):
    spiceSymbol = "R"

    @generate(Symbol)
    def symbol(self, node):
        node.m = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.p = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        
        if self.params.get("alt_symbol", False):
            # Box symbol
            node % SymbolPoly(vertices=[Vec2R(x=1.5, y=3), Vec2R(x=2.5, y=3), Vec2R(x=2.5, y=1), Vec2R(x=1.5, y=1), Vec2R(x=1.5, y=3)])
            node % SymbolPoly(vertices=[Vec2R(x=2, y=3), Vec2R(x=2, y=4)])
            node % SymbolPoly(vertices=[Vec2R(x=2, y=1), Vec2R(x=2, y=0)])
        else:
            # Zigzag symbol
            zigzag_height = R(2)
            zigzag_width_half = R(0.625)
            zigzag_start = (R(4) - zigzag_height)/R(2)
            node % SymbolPoly(vertices=[
                Vec2R(x=2, y=0),
                Vec2R(x=2, y=zigzag_start),
                Vec2R(x=2 - zigzag_width_half, y=zigzag_start+zigzag_height*R(1)/R(12) ),
                Vec2R(x=2 + zigzag_width_half, y=zigzag_start+zigzag_height*R(3)/R(12) ),
                Vec2R(x=2 - zigzag_width_half, y=zigzag_start+zigzag_height*R(5)/R(12) ),
                Vec2R(x=2 + zigzag_width_half, y=zigzag_start+zigzag_height*R(7)/R(12) ),
                Vec2R(x=2 - zigzag_width_half, y=zigzag_start+zigzag_height*R(9)/R(12) ),
                Vec2R(x=2 + zigzag_width_half, y=zigzag_start+zigzag_height*R(11)/R(12)),
                Vec2R(x=2, y=zigzag_start+zigzag_height),
                Vec2R(x=2, y=4),
                ])
        
        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
    
    def netlist_ngspice(self, netlister, inst, schematic):
        param_r = self.params.r
        pins = [inst.symbol.p, inst.symbol.m]
        netlister.add(netlister.name_obj(inst, schematic, prefix="r"), netlister.portmap(inst, pins), f'r={param_r.compat_str()}')

class Cap(Cell):
    spiceSymbol = "C"

    @generate(Symbol)
    def symbol(self, node):
        node.m = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.p = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        
        #Kondensator
        node % SymbolPoly(vertices=[Vec2R(x=1.25, y=1.8), Vec2R(x=2.75, y=1.8)])
        node % SymbolPoly(vertices=[Vec2R(x=1.25, y=2.2), Vec2R(x=2.75, y=2.2)])
        
        #Linien
        node % SymbolPoly(vertices=[Vec2R(x=2, y=2.2), Vec2R(x=2, y=4)])
        node % SymbolPoly(vertices=[Vec2R(x=2, y=1.8), Vec2R(x=2, y=0)])


        #node % SymbolPoly(vertices=[Vec2R(x=1.6, y=1.05), Vec2R(x=2, y=1.25), Vec2R(x=1.6, y=1.45)])

        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
   
class Ind(Cell):
    spiceSymbol = "L"

    @generate(Symbol)
    def symbol(self, node):
        
        node.m = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.p = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        
        #Kondensator
        #node % SymbolPoly(vertices=[Vec2R(x=1.25, y=1.8), Vec2R(x=2.75, y=1.8)])
        #node % SymbolPoly(vertices=[Vec2R(x=1.25, y=2.2), Vec2R(x=2.75, y=2.2)])
        r=0.35
        node % SymbolArc(pos=Vec2R(x=2,y=3-r), radius=R(r), angle_start=R(-0.25), angle_end=R(0.25))
        node % SymbolArc(pos=Vec2R(x=2,y=3-(3*r)), radius=R(r), angle_start=R(-0.25), angle_end=R(0.25))
        node % SymbolArc(pos=Vec2R(x=2,y=3-(5*r)), radius=R(r), angle_start=R(-0.25), angle_end=R(0.25))
        
        #Linien
        node % SymbolPoly(vertices=[Vec2R(x=2, y=3), Vec2R(x=2, y=4)])
        node % SymbolPoly(vertices=[Vec2R(x=2, y=3-(6*r)), Vec2R(x=2, y=0)])


        #node % SymbolPoly(vertices=[Vec2R(x=1.6, y=1.05), Vec2R(x=2, y=1.25), Vec2R(x=1.6, y=1.45)])

        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
 
  
# Misc
# ====

class Gnd(Cell):
    spiceSymbol = "V"

    @generate(Symbol)
    def symbol(self, node):
        node.p = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)  

        
        #Linien
        node % SymbolPoly(vertices=[Vec2R(x=2, y=2.5), Vec2R(x=2, y=4)])
        node % SymbolPoly(vertices=[Vec2R(x=1, y=2.5), Vec2R(x=3, y=2.5), Vec2R(x=2, y=1),Vec2R(x=1, y=2.5)])

        #node % SymbolPoly(vertices=[Vec2R(x=1.6, y=1.05), Vec2R(x=2, y=1.25), Vec2R(x=1.6, y=1.45)])
        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
 
    def netlist_ngspice(self, netlister, inst, schematic):
        pins = [inst.symbol.p]
        netlister.add(netlister.name_obj(inst, schematic, prefix="v"), netlister.portmap(inst, pins), '0', f'dc 0')

class NoConn(Cell):
    @generate(Symbol)
    def symbol(self, node):
        node.a = Pin(pos=Vec2R(x=0, y=2), pintype=PinType.In, align=Orientation.West)

        node % SymbolPoly(vertices=[Vec2R(x=0, y=2), Vec2R(x=2, y=2)])
        node % SymbolPoly(vertices=[Vec2R(x=1.5, y=2.5), Vec2R(x=2.5, y=1.5)])
        node % SymbolPoly(vertices=[Vec2R(x=1.5, y=1.5), Vec2R(x=2.5, y=2.5)])

        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)

    def netlist_ngspice(self, netlister, inst, schematic):
        pass

# Voltage & current sources
# =========================

class Vdc(Cell):
    #V: Rational = field(mandatory=True) 

    @generate(Symbol)
    def symbol(self, node):    
        node.m = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.p = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        
        #Kreis
        node % SymbolArc(pos=Vec2R(x=2,y=2), radius=R(1))
        
        #Linien
        node % SymbolPoly(vertices=[Vec2R(x=2, y=3), Vec2R(x=2, y=4)])
        node % SymbolPoly(vertices=[Vec2R(x=2, y=1), Vec2R(x=2, y=0)])

        if self.params.get("alt_symbol", False):
            #Pfeil
            node % SymbolPoly(vertices=[Vec2R(x=0.5, y=1), Vec2R(x=0.5, y=3)])
            node % SymbolPoly(vertices=[Vec2R(x=0.5, y=3)+Vec2R(x=-0.2, y=-0.2), Vec2R(x=0.5, y=3)])
            node % SymbolPoly(vertices=[Vec2R(x=0.5, y=3)+Vec2R(x=0.2, y=-0.2), Vec2R(x=0.5, y=3)])
    
            #+/-
            node % SymbolPoly(vertices=[Vec2R(x=1.5, y=2.1), Vec2R(x=2.5, y=2.1)])
            node % SymbolPoly(vertices=[Vec2R(x=1.5, y=1.9), Vec2R(x=1.8, y=1.9)])
            node % SymbolPoly(vertices=[Vec2R(x=1.9, y=1.9), Vec2R(x=2.1, y=1.9)])
            node % SymbolPoly(vertices=[Vec2R(x=2.2, y=1.9), Vec2R(x=2.5, y=1.9)])
            #node % SymbolPoly(vertices=[Vec2R(x=1.6, y=1.05), Vec2R(x=2, y=1.25), Vec2R(x=1.6, y=1.45)])
        else:
            #+
            node % SymbolPoly(vertices=[Vec2R(x=2, y=2.2), Vec2R(x=2, y=2.8)])
            node % SymbolPoly(vertices=[Vec2R(x=1.7, y=2.5), Vec2R(x=2.3, y=2.5)])
            #-
            node % SymbolPoly(vertices=[Vec2R(x=1.65, y=1.5), Vec2R(x=2.35, y=1.5)])
            

        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)
 
    def netlist_ngspice(self, netlister, inst, schematic):
        param_dc = self.params.dc
        pins = [inst.symbol.p, inst.symbol.m]
        netlister.add(netlister.name_obj(inst, schematic, prefix="v"), netlister.portmap(inst, pins) , f'dc {param_dc.compat_str()}')

class Idc(Cell):
    spiceSymbol = "I"
    #V: Rational = field(mandatory=True) 
    @generate(Symbol)
    def symbol(self, node):
        
        node.m = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.p = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        
        if self.params.get("alt_symbol", False):
             #Kreis
            node % SymbolArc(pos=Vec2R(x=2,y=4-2*0.7), radius=R(7,10))
            node % SymbolArc(pos=Vec2R(x=2,y=0+2*0.7), radius=R(7,10))
            
            #Linien
            node % SymbolPoly(vertices=[Vec2R(x=2, y=3), Vec2R(x=2, y=4)])
            node % SymbolPoly(vertices=[Vec2R(x=2, y=1), Vec2R(x=2, y=0)])
            #Pfeil
            node % SymbolPoly(vertices=[Vec2R(x=0.5, y=1), Vec2R(x=0.5, y=3)])
            node % SymbolPoly(vertices=[Vec2R(x=0.5, y=1)+Vec2R(x=-0.2, y=0.2), Vec2R(x=0.5, y=1)])
            node % SymbolPoly(vertices=[Vec2R(x=0.5, y=1)+Vec2R(x=0.2, y=0.2), Vec2R(x=0.5, y=1)])

        else:
            node % SymbolPoly(vertices=[Vec2R(x=2, y=3), Vec2R(x=2, y=4)])
            node % SymbolPoly(vertices=[Vec2R(x=2, y=1), Vec2R(x=2, y=0)])
            node % SymbolArc(pos=Vec2R(x=2,y=2), radius=R(1))

            # Pfeil:
            b = Vec2R(x=2, y=1.25)
            node % SymbolPoly(vertices=[b, Vec2R(x=2, y=2.75)])
            node % SymbolPoly(vertices=[b + Vec2R(x=-0.5, y=0.5), b, b + Vec2R(x=0.5, y=0.5)])
        
        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)

    def netlist_ngspice(self, netlister, inst, schematic):
        param_dc = self.params.dc
        pins = [inst.symbol.p, inst.symbol.m]
        netlister.add(netlister.name_obj(inst, schematic, prefix="i"), netlister.portmap(inst, pins) , f'dc {param_dc.compat_str()}')

class PieceWiseLinearVoltageSource(Cell):
    """
    Represents a Piecewise Linear Voltage Source.
    Expects a parameter 'V' which is a list of (time, voltage) tuples.
    Example: V=[(0, 0), (1e-9, 1.8), (5e-9, 1.8), (6e-9, 0)]
    """
    spiceSymbol = "V" 
    
    @generate(Symbol)
    def symbol(self, node):
        """ Defines the schematic symbol for the PWL source. """
        node.m = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.p = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        
        
        node % SymbolArc(pos=Vec2R(x=2,y=2), radius=R(1))
        
    
        node % SymbolPoly(vertices=[Vec2R(x=2, y=3), Vec2R(x=2, y=4)]) # To positive pin
        node % SymbolPoly(vertices=[Vec2R(x=2, y=1), Vec2R(x=2, y=0)]) # To negative pin

    
        node % SymbolPoly(vertices=[
            Vec2R(x=1.4, y=1.8), 
            Vec2R(x=1.7, y=2.4), 
            Vec2R(x=2.0, y=1.6),
            Vec2R(x=2.3, y=2.4),
            Vec2R(x=2.6, y=2.4),
            
        ])
        #+
        node % SymbolPoly(vertices=[Vec2R(x=2, y=2.3), Vec2R(x=2, y=2.9)])
        node % SymbolPoly(vertices=[Vec2R(x=1.7, y=2.6), Vec2R(x=2.3, y=2.6)])
        #-
        node % SymbolPoly(vertices=[Vec2R(x=1.65, y=1.3), Vec2R(x=2.35, y=1.3)])
    
        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)


class PulseVoltageSource(Cell):
    """
    Represents a Pulse Voltage Source.
    Requires parameters: initial_value, pulsed_value, delay_time,
                         rise_time, fall_time, pulse_width, period.
    """
    spiceSymbol = "V"

    @generate(Symbol)
    def symbol(self, node):
        node.m = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.p = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)

        node % SymbolArc(pos=Vec2R(x=2, y=2), radius=R(1))

        node % SymbolPoly(vertices=[Vec2R(x=2, y=3), Vec2R(x=2, y=4)])  # To positive pin 'p'
        node % SymbolPoly(vertices=[Vec2R(x=2, y=1), Vec2R(x=2, y=0)])  # To negative pin 'm'

        # Pulse symbol
        node % SymbolPoly(vertices=[
            Vec2R(x=1.5, y=1.5),
            Vec2R(x=1.5, y=2.5),
            Vec2R(x=2.0, y=2.5),
            Vec2R(x=2.0, y=1.5),
            Vec2R(x=2.5, y=1.5),
            Vec2R(x=2.5, y=2.5)
        ])


        # + 
        node % SymbolPoly(vertices=[Vec2R(x=2, y=2.55), Vec2R(x=2, y=2.95)]) # Vertical bar
        node % SymbolPoly(vertices=[Vec2R(x=1.8, y=2.75), Vec2R(x=2.2, y=2.75)]) # Horizontal bar
        # - 
        node % SymbolPoly(vertices=[Vec2R(x=1.8, y=1.2), Vec2R(x=2.2, y=1.2)]) # Horizontal bar


        # Outline
        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)


class SinusoidalVoltageSource(Cell):
    """
    Represents a Sinusoidal Voltage Source.
    Requires parameters: offset, amplitude, frequency, delay.
    Optional parameter: damping_factor (defaults to 0).
    """
    spiceSymbol = "V"

    @generate(Symbol)
    def symbol(self, node):
        import numpy as np # TODO: Get rid of numpy dependency
        node.m = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.p = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)

        node % SymbolArc(pos=Vec2R(x=2, y=2), radius=R(1))

        node % SymbolPoly(vertices=[Vec2R(x=2, y=3), Vec2R(x=2, y=4)]) # To positive pin 'p'
        node % SymbolPoly(vertices=[Vec2R(x=2, y=1), Vec2R(x=2, y=0)]) # To negative pin 'm'

        sine_wave_points = [
            Vec2R(x=1.2 + 0.1 * t, y=2.0 + 0.6 * np.sin(np.pi * t / 4))
            for t in range(17)
        ]
        node % SymbolPoly(vertices=sine_wave_points)
        
        # +
        node % SymbolPoly(vertices=[Vec2R(x=2, y=2.5), Vec2R(x=2, y=2.9)]) # Vertical bar
        node % SymbolPoly(vertices=[Vec2R(x=1.8, y=2.75), Vec2R(x=2.2, y=2.75)]) # Horizontal bar
        # - 
        node % SymbolPoly(vertices=[Vec2R(x=1.8, y=1.2), Vec2R(x=2.2, y=1.2)]) # Horizontal bar
        
        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)


class PieceWiseLinearCurrentSource(Cell):
    spiceSymbol = "I"

    @generate(Symbol)
    def symbol(self, node):
        """ Defines the schematic symbol for the PWL current source. """
        node.p = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)
        node.m = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)

    
        node % SymbolArc(pos=Vec2R(x=2, y=2), radius=R(1))

        
        node % SymbolPoly(vertices=[Vec2R(x=2, y=3), Vec2R(x=2, y=4)]) # To positive pin 'p'
        node % SymbolPoly(vertices=[Vec2R(x=2, y=1), Vec2R(x=2, y=0)]) # To negative pin 'm'

        
        node % SymbolPoly(vertices=[
            Vec2R(x=1.4, y=1.7),
            Vec2R(x=1.7, y=2.3),
            Vec2R(x=2.0, y=1.5),
            Vec2R(x=2.3, y=2.3),
            Vec2R(x=2.6, y=2.3),
        ])


        arrow_tip_y = 2.7
        arrow_base_y = 2.3
        arrow_barb_y = 2.5
        arrow_width = 0.2 

        # Shaft
        node % SymbolPoly(vertices=[Vec2R(x=2, y=arrow_base_y), Vec2R(x=2, y=arrow_tip_y)])
        # Head
        node % SymbolPoly(vertices=[
            Vec2R(x=2 - arrow_width, y=arrow_barb_y), # Left barb base
            Vec2R(x=2, y=arrow_tip_y),                # Tip
            Vec2R(x=2 + arrow_width, y=arrow_barb_y)  # Right barb base
        ])

        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)


class PulseCurrentSource(Cell):
    """
    Represents a Pulse Current Source.
    Uses a symbol with an internal pulse shape and an arrow indicating direction.
    Requires parameters: initial_value, pulsed_value, delay_time,
                         rise_time, fall_time, pulse_width, period.
    """
    spiceSymbol = "I"

    @generate(Symbol)
    def symbol(self, node):
        node.m = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.p = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)

        # Draw the symbol
        # Circle
        node % SymbolArc(pos=Vec2R(x=2, y=2), radius=R(1))

        # Lines
        node % SymbolPoly(vertices=[Vec2R(x=2, y=3), Vec2R(x=2, y=4)]) # To positive pin 'p'
        node % SymbolPoly(vertices=[Vec2R(x=2, y=1), Vec2R(x=2, y=0)]) # To negative pin 'm'

        # Pulse symbol
        node % SymbolPoly(vertices=[
            Vec2R(x=1.5, y=1.3),
            Vec2R(x=1.5, y=2.3),
            Vec2R(x=2.0, y=2.3),
            Vec2R(x=2.0, y=1.3),
            Vec2R(x=2.5, y=1.3),
            Vec2R(x=2.5, y=2.3)
        ])

        # Arrow pointing UP (from m towards p) 
        arrow_tip_y = 3.0
        arrow_base_y = 2.5 
        arrow_barb_y = 2.7
        arrow_width = 0.3 
        node % SymbolPoly(vertices=[Vec2R(x=2, y=arrow_base_y), Vec2R(x=2, y=arrow_tip_y)]) # Shaft
        node % SymbolPoly(vertices=[
            Vec2R(x=2 - arrow_width, y=arrow_barb_y), # Left barb base
            Vec2R(x=2, y=arrow_tip_y),                # Tip
            Vec2R(x=2 + arrow_width, y=arrow_barb_y)  # Right barb base
        ])

        node.outline = node % Rect4R(lx=0, ly=0, ux=4, uy=4)


class SinusoidalCurrentSource(Cell):
    """
    Represents a Sinusoidal Current Source.
    Uses a symbol with an internal sine shape and an arrow indicating direction.
    Requires parameters: offset, amplitude, frequency, delay.
    Optional parameter: damping_factor (defaults to 0).
    """
    spiceSymbol = "I"

    @generate(Symbol)
    def symbol(self, node):
        import numpy as np # TODO: Get rid of numpy dependency
        node.m = Pin(pos=Vec2R(x=2, y=0), pintype=PinType.Inout, align=Orientation.South)
        node.p = Pin(pos=Vec2R(x=2, y=4), pintype=PinType.Inout, align=Orientation.North)

        # Circle
        node % SymbolArc(pos=Vec2R(x=2, y=2), radius=R(1))

        # Lines
        node % SymbolPoly(vertices=[Vec2R(x=2, y=3), Vec2R(x=2, y=4)]) # To positive pin 'p'
        node % SymbolPoly(vertices=[Vec2R(x=2, y=1), Vec2R(x=2, y=0)]) # To negative pin 'm'

        # Sinusoidal symbol 
        sine_wave_points = [
            Vec2R(x=1.2 + 0.1 * t, y=1.9 + 0.6 * np.sin(np.pi * t / 4))
            for t in range(17)
        ]
        node % SymbolPoly(vertices=sine_wave_points)

        # Arrow pointing UP
        arrow_tip_y = 3.0 
        arrow_base_y = 2.5
        arrow_barb_y = 2.7
        arrow_width = 0.3 

        node % SymbolPoly(vertices=[Vec2R(x=2, y=arrow_base_y), Vec2R(x=2, y=arrow_tip_y)]) # Shaft
        node % SymbolPoly(vertices=[
            Vec2R(x=2 - arrow_width, y=arrow_barb_y), # Left barb base
            Vec2R(x=2, y=arrow_tip_y),                # Tip
            Vec2R(x=2 + arrow_width, y=arrow_barb_y)  # Right barb base
        ])

        # Outline
        node.outline = Rect4R(lx=0, ly=0, ux=4, uy=4)

