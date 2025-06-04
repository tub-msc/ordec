# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import math
from base64 import b64encode
import io
from enum import Enum
import cairo
import gi
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo

from . import Symbol, Pin, SchemPoly, SchemArc, SchemRect, Schematic, SchemInstance, SchemPort, PinType, SchemConnPoint, SchemTapPoint
from .geoprim import Rect4R, Vec2R, TD4, D4, Orientation

def to_cairo_matrix(trans: TD4):
    x0, y0 = trans.transl.tofloat()
    xx=-1 if trans.negx else 1
    yy=-1 if trans.negy else 1
    if trans.flipxy:
        return cairo.Matrix(xx=0, xy=xx, yy=0, yx=yy, x0=x0, y0=y0)
    else:
        return cairo.Matrix(xx=xx, xy=0, yy=yy, yx=0, x0=x0, y0=y0)

class LabelAlign(Enum):
    BASELINE = 0
    CENTER = 1
    TOP = 2

def get_parent(node, t):
    while not isinstance(node, t):
        node = node.parent
    return node

class Renderer:
    pango_custom_scale = 0.05
    padding = 1
    scale = 30
    pin_rect_size = 0.4
    pin_text_space = 0.125
    port_text_space = 0.15
    font_narrow_factor = 0.9

    def surface_dimensions(self):
        lx, ly, ux, uy = self.outline.tofloat()
        w, h = ux - lx, uy - ly
        surface_w = (w + 2*self.padding)*self.scale
        surface_h = (h + 2*self.padding)*self.scale

        offx = (self.padding-lx)*self.scale
        offy = surface_h-(self.padding-ly)*self.scale

        return offx, offy, surface_w, surface_h

    # We could add rendering options to the __init__ function here:
    def __init__(self, outline: Rect4R):
        self.outline = outline

    def init_context(self):
        ctx = cairo.Context(self.surface)
        ctx.set_matrix(cairo.Matrix(1,0,0,-1, 0, 0))
        ctx.scale(self.scale, self.scale)
        ctx.set_line_join(cairo.LineJoin.BEVEL)
        ctx.set_line_cap(cairo.LineCap.BUTT)
        ctx.set_antialias(cairo.Antialias.NONE) # Should only affect ImageRenderer
        self.ctx = ctx

        fo =  cairo.FontOptions()
        #o.set_antialias(cairo.Antialias.GOOD)
        fo.set_antialias(cairo.Antialias.NONE)
        fo.set_hint_style(cairo.HintStyle.FULL)
        fo.set_hint_metrics(cairo.HintMetrics.ON)

        self.pango_ctx = PangoCairo.create_context(ctx)
        PangoCairo.context_set_font_options(self.pango_ctx, fo)
        #PangoCairo.context_set_resolution(self.pango_ctx, 4)

        self.font = Pango.font_description_from_string('Inconsolata Normal 10')

        # Measure "e":
        ref_e = Pango.Layout.new(self.pango_ctx)
        ref_e.set_font_description(self.font)
        ref_e.set_markup("e", -1)
        ink_box_e, log_box_e = ref_e.get_extents()
        # Memorize font's e half height:
        self.font_eh = (ink_box_e.y + ink_box_e.height/2) / Pango.SCALE * self.pango_custom_scale

    def draw_unit_grid(self, rect: Rect4R):
        ctx = self.ctx
        lx, ly, ux, uy = rect.pos.tofloat()
        for x in range(math.floor(lx), math.ceil(ux)+1):
            for y in range(math.floor(ly), math.ceil(uy)+1):
                ctx.rectangle(x-0.05, y-0.05, 0.1, 0.1)
        ctx.fill()

    def draw_schem_rect(self, rect: Rect4R):
        ctx = self.ctx
        lx, ly, ux, uy = rect.tofloat()
        ctx.rectangle(lx, ly, ux-lx, uy-ly)
        ctx.stroke()

    def draw_schem_poly(self, poly: SchemPoly, trans: TD4 = TD4()):
        ctx = self.ctx
        x, y = (trans * poly.vertices[0]).tofloat()
        ctx.move_to(x, y)
        for point in poly.vertices[1:-1]:
            x, y = (trans * point).tofloat()
            ctx.line_to(x,y)
        if poly.vertices.closed():
            ctx.close_path()
        else:
            x, y = (trans * poly.vertices[-1]).tofloat()
            ctx.line_to(x,y)
        ctx.stroke()

    def draw_schem_connpoint(self, p: SchemConnPoint, trans: TD4 = TD4()):
        ctx = self.ctx
        x, y = (trans * p.pos).tofloat()
        ctx.arc(x, y, 0.1625, 0, 2*math.pi)
        ctx.fill()

    def draw_schem_arc(self, arc: SchemArc, trans: TD4):
        ctx = self.ctx
        x, y = (trans * arc.pos).tofloat()
        radius = float(arc.radius)
        s, e = trans.arc(arc.angle_start, arc.angle_end)
        angle_start = float(s)*2*math.pi
        angle_end = float(e)*2*math.pi
        ctx.arc(x, y, radius, angle_start, angle_end)
        ctx.stroke()

    def draw_label(self, label: str, trans: TD4, space=0, halign: LabelAlign = LabelAlign.BASELINE):
        align = D4(trans.set(transl=Vec2R(x=0,y=0))).unflip()
        pos = trans.transl

        ctx = self.ctx
        x, y = pos.tofloat()

        layout = Pango.Layout.new(self.pango_ctx)
        layout.set_font_description(self.font)
        if align in (Orientation.West, Orientation.South):
            layout.set_alignment(Pango.Alignment.LEFT)
        else:
            layout.set_alignment(Pango.Alignment.RIGHT)
        layout.set_markup(label, -1)

        ink_box,log_box = layout.get_extents()
        b = layout.get_baseline()/Pango.SCALE * self.pango_custom_scale
        w = log_box.width / Pango.SCALE * self.pango_custom_scale
        h = log_box.height / Pango.SCALE * self.pango_custom_scale
        w *= self.font_narrow_factor

        ctx.save()
        ctx.translate(x, y)

        ctx.scale(1,-1)
        if align in (Orientation.South, Orientation.North):  
             ctx.rotate(-math.pi/2)

        # x positioning:
        if align in (Orientation.West, Orientation.South):
            ctx.translate(-(w+space), 0)
        else:
            ctx.translate(space, 0)

        # y positioning:
        if halign == LabelAlign.BASELINE:
            ctx.translate(0, -h-space)
        elif halign == LabelAlign.CENTER:
            ctx.translate(0, -self.font_eh)
        else:
            assert halign == LabelAlign.TOP
            ctx.translate(0, space)

        ctx.scale(self.pango_custom_scale,self.pango_custom_scale)
        ctx.scale(self.font_narrow_factor,1) # narrower fonts
        PangoCairo.show_layout(ctx, layout)
        ctx.restore()

    def draw_pin(self, pin: Pin, trans: TD4):
        ctx = self.ctx

        #x, y = (trans * pin.pos).tofloat()
        #ctx.rectangle(x-self.pin_rect_size/2, y-self.pin_rect_size/2, self.pin_rect_size, self.pin_rect_size)
        #ctx.arc(x, y, 0.1625, 0, 2*math.pi)

        trans_local = trans*TD4(transl=pin.pos)*D4.R180.value*pin.align.value
        #ctx.fill()
        ctx.set_source_rgb(1,0,0)
        self.draw_pinportarrow(pin.pintype, trans_local, center=True, halfheight=0.2, width=0.4)

        label = str(pin.path()[2:])


        # Flip by 180 degrees, as the text face the opposite of the pin direction:
        self.draw_label(label, trans_local, space=self.pin_text_space)
    
    def draw_pinportarrow(self, pt: PinType, trans: TD4, halfheight=0.25, width=0.5, center=False):
        arrow_left = pt in (PinType.Inout, PinType.Out)
        arrow_right = pt in (PinType.Inout, PinType.In)

        left_tip = halfheight if arrow_left else 0
        right_tip = halfheight if arrow_right else 0
        
        ctx = self.ctx
        ctx.save()
        if center:
            ctx.set_matrix(to_cairo_matrix(trans*TD4(transl=Vec2R(x=0,y=width/2)))*ctx.get_matrix())
        else:
            ctx.set_matrix(to_cairo_matrix(trans)*ctx.get_matrix())

        ctx.move_to(0, 0)
        ctx.line_to(halfheight, -right_tip)
        ctx.line_to(halfheight, -width+left_tip)
        ctx.line_to(0, -width)
        ctx.line_to(-halfheight, -width+left_tip)
        ctx.line_to(-halfheight, -right_tip)
        ctx.close_path()
        #ctx.set_source_rgb(0.2,0.6,1.0)
        ctx.fill()
        #ctx.set_source_rgb(0,0,0)
        #ctx.stroke()

        ctx.restore()

    def draw_schem_port(self, port: SchemPort):
        ctx = self.ctx
        trans = TD4(transl=port.pos)*port.align.value
        ctx.set_source_rgb(0.2,0.6,1.0)
        self.draw_pinportarrow(port.ref.pintype, trans)
        width = 0.5
        self.draw_label(str(port.ref.path()[2:]), trans*D4.R180.value*TD4(transl=Vec2R(x=0, y=width)), space=self.port_text_space, halign=LabelAlign.CENTER)

    def draw_schem_tappoint(self, p: SchemTapPoint):
        ctx = self.ctx
       
        ctx.save()
        tran = TD4(transl=p.pos)*p.align.value
        ctx.set_matrix(to_cairo_matrix(tran)*ctx.get_matrix())

        parent_schematic = get_parent(p, Schematic)

        is_default_supply = parent_schematic.default_supply == p.parent
        is_default_ground = parent_schematic.default_ground == p.parent

        #ctx.arc(0.5, 0, 0.15, 0, 2*math.pi)
        #ctx.stroke()
        #ctx.fill()

        if is_default_supply:
            ctx.move_to(0, 0)
            ctx.line_to(0, 1.0)
            ctx.move_to(0.25, 0.5)
            ctx.line_to(0, 1.0)
            ctx.line_to(-0.25, 0.5)
        elif is_default_ground:
            ctx.move_to(0, 0)
            ctx.line_to(0, 0.5)

            ctx.move_to(-0.375, 0.5)
            ctx.line_to(0.375, 0.5)

            ctx.move_to(-0.25, 0.75)
            ctx.line_to(0.25, 0.75)

            ctx.move_to(-0.125, 1.0)
            ctx.line_to(0.125, 1.0)
        else:
            ctx.move_to(0, 0)
            ctx.line_to(0, 0.5)

        ctx.stroke()
        #ctx.fill()
        ctx.restore()
        
        if not (is_default_supply or is_default_ground):
            label = str(p.parent.path()[2:])
            self.draw_label(label, tran*TD4(transl=Vec2R(x=0, y=0.5)), space=self.port_text_space, halign=LabelAlign.CENTER)

    def draw_symbol(self, s: Symbol, trans: TD4, inst_name: str="?"):
        ctx = self.ctx
        ctx.set_line_width(0.1)
        ctx.set_source_rgb(0.5,0.5,0.5)
        for rect in s.traverse(SchemRect):
            pos = trans * rect.pos
            if rect == s.outline:
                ctx.set_source_rgb(0.5,0.7,0.5)
                self.draw_schem_rect(pos)

                #str(s.path()[0])
                cell = s.path()[0]
                cell_name = type(cell).__name__
                #params_str = cell.params_str()
                params_str = "\n".join(cell.params_list())

                self.draw_label(cell_name, TD4(transl=pos.north_east())*D4.R90.value, space=self.pin_text_space, halign=LabelAlign.TOP)
                self.draw_label(params_str, TD4(transl=pos.south_east())*D4.R90.value, space=self.pin_text_space, halign=LabelAlign.BASELINE)

                ctx.set_source_rgb(1,0,0)
                self.draw_label(f"<b>{inst_name}</b>", TD4(transl=pos.north_west())*D4.MX90.value, space=self.pin_text_space, halign=LabelAlign.TOP)
            else:
                ctx.set_source_rgb(0.5,0.5,0.5)
                self.draw_schem_rect(pos)
        
        ctx.set_line_width(0.1)
        ctx.set_source_rgb(0,0,0)
        for poly in s.traverse(SchemPoly):
            self.draw_schem_poly(poly, trans)
        for arc in s.traverse(SchemArc):
            self.draw_schem_arc(arc, trans)

        ctx.set_source_rgb(1,0,0)
        for pin in s.traverse(Pin):
            self.draw_pin(pin, trans)

    def render(self, obj):
        if isinstance(obj, Symbol):
            self.render_symbol(obj)
        elif isinstance(obj, Schematic):
            self.render_schematic(obj)
        else:
            raise TypeError(f"Unsupported object {obj} for rending.")

    def render_symbol(self, s):
        ctx = self.ctx
    
        ctx.set_source_rgb(0.8, 0.8, 0.8)
        self.draw_unit_grid(s.outline)

        self.draw_symbol(s, TD4())

    def render_schematic(self, s):
        ctx = self.ctx
        ctx.set_line_width(0.1)

        ctx.set_source_rgb(0.8, 0.8, 0.8)
        self.draw_unit_grid(s.outline)

        ctx.set_source_rgb(0.8, 0.8, 0)
        for poly in s.traverse(SchemPoly):
            self.draw_schem_poly(poly)

        for p in s.traverse(SchemConnPoint):
            self.draw_schem_connpoint(p)

        for p in s.traverse(SchemTapPoint):
            self.draw_schem_tappoint(p)

        for inst in s.traverse(SchemInstance):
            trans = inst.loc_transform()
            self.draw_symbol(inst.ref, trans, str(inst.name))

        for port in s.traverse(SchemPort):
            self.draw_schem_port(port)


    def as_html(self) -> str:
        return f'<img src="{self.as_url()}" />'

class RendererSVG(Renderer):
    def __enter__(self):
        self.outbuf = io.BytesIO()

        offx, offy, w, h = self.surface_dimensions()
        self.surface = cairo.SVGSurface(self.outbuf, w, h)
        self.surface.set_device_offset(offx, offy)
        
        self.init_context()

        return self

    def __exit__(self, type, value, traceback):
        self.surface.finish()
    
    def as_url(self) -> str:
        return f'data:image/svg+xml;base64,{b64encode(self.outbuf.getvalue()).decode("ascii")}'
    
class RendererImage(Renderer):
    def __enter__(self):
        self.outbuf = io.BytesIO()

        offx, offy, w, h = self.surface_dimensions()
        self.surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, math.ceil(w), math.ceil(h))
        self.surface.set_device_offset(offx, offy)
        
        self.init_context()

        return self

    def __exit__(self, type, value, traceback):
        # finish destroys the buffer, so it is not useful for us here.
        #self.surface.finish()
        pass
    
    def as_png(self):
        outbuf = io.BytesIO()
        self.surface.write_to_png(outbuf)
        return outbuf.getvalue()

    def as_url(self):
        return f'data:image/png;base64,{b64encode(self.as_png()).decode("ascii")}'


def render_svg(object) -> RendererSVG:
    with RendererSVG(object.outline.pos) as r:
        r.render(object)
    return r

def render_image(object) -> RendererImage:
    with RendererImage(object.outline.pos) as r:
        r.render(object)
    return r