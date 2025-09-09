# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import xml.etree.ElementTree as ET
import math
from base64 import b64encode
from contextlib import contextmanager
from .core import *
from enum import Enum
import re

class HAlign(Enum):
    Left = 1
    Right = 2

    def invert(self):
        if self == self.Left:
            return self.Right
        elif self == self.Right:
            return self.Left
        else:    
            return self

class VAlign(Enum):
    Top = 1
    Bottom = 2
    Middle = 3

class ArrowType(Enum):
    Pin = 1
    Port = 2

class Renderer:
    """
    Instantiate the Renderer class and then call one of its render_ methods,
    e.g. render_schematic(). draw_... and other methods are more internal.
    Afterwards, obtain the result via the svg() or png() methods.
    """

    pin_text_space = 0.125
    port_text_space = 0.15 + 0.5
    pixel_per_unit = 35
    conn_point_radius = 0.1625
    css = ""

    def __init__(self, include_nids: bool=True, enable_css: bool=True):
        """
        Args:
            include_nids: controls whether to include id="nid123" attributes.
                These ids make the SVG more useful for interactions, but make
                them less comparable in test scenarios.
        """
        self.include_nids = include_nids

        self.root = ET.Element('svg', xmlns="http://www.w3.org/2000/svg", )
        if enable_css:
            style = ET.SubElement(self.root, 'style', type='text/css')
            style.text = self.css
        self.group_stack = [ET.SubElement(self.root, 'g')]

    @property
    def cur_group(self):
        return self.group_stack[-1]

    @contextmanager
    def subgroup(self, node=None):
        self.group_stack.append(ET.SubElement(self.cur_group, 'g'))
        if node and self.include_nids:
            self.cur_group.attrib['id'] = f'nid{node.nid}'
        try:
            yield 
        finally:
            self.group_stack.pop()

    def draw_label(self, text: str, trans: TD4, halign=HAlign.Left, valign=VAlign.Top, space=None, svg_class=""):
        """
        dominant_baseline: chose "hanging" or "ideographic"
        """

        align = D4.from_td4(trans).unflip()
        pos = trans.transl

        if align in (Orientation.West, Orientation.South):
            halign = halign.invert()

        # g_matrix has same basic translation as trans, but limits rotations of text
        # to 0 or 90 degrees (so that you never have to rotate your head by 180 degrees)
        g_matrix = pos.transl() 
        if align in (Orientation.South, Orientation.North):  
             g_matrix *= D4.R90

        # Furthermore, g_matrix adds some space (padding):
        if space == None:
            space = self.pin_text_space
        g_matrix *= Vec2R(
            x = {HAlign.Left: +1, HAlign.Right: -1}[halign]*space,
            y = {VAlign.Bottom: +1, VAlign.Top: -1, VAlign.Middle: 0}[valign]*space,
            ).transl()

        scale = 0.045 # 1/self.pixel_per_unit (?) Not sure why this is so off.
        tag = ET.SubElement(self.cur_group, 'text', transform=g_matrix.svg_transform(x_scale=scale, y_scale=-scale))

        lines = text.split('\n')
        if len(lines) == 1:
            # Make the XML tree more compact by skipping <tspan> for single-line text: 
            tag.text = lines[0]
        else:
            for idx, line in enumerate(lines):
                y = idx+1-len(lines)
                tspan=ET.SubElement(tag, 'tspan', x="0", y=f"{y}em")
                tspan.text = line

        tag.attrib['dominant-baseline'] = {
            VAlign.Top: 'hanging',
            VAlign.Bottom: 'ideographic',
            VAlign.Middle: 'middle',
            }[valign]
        tag.attrib['text-anchor'] = {HAlign.Left: 'start', HAlign.Right: 'end'}[halign]
        tag.attrib['class'] = svg_class


    def setup_canvas(self, rect: Rect4R, padding: float = 1.0, scale_viewbox: float|int = 1):
        """
        Configures the SVG coordinate system to how we like it, setting
        attributes of the root <svg> tag and the transform attribute of the
        topmost <g>.

        Args:
            rect: Canvas extent.
            padding: Extend canvas by padding units beyond rect in all directions.
            scale_viewbox: Both the <svg> viewbox size and the topmost <g>
                tranform matrix are scaled by this factor. As a result, the
                value of scale_viewbox should have no effect on the resulting
                graphical data. However, some renderers cannot deal with certain
                viewbox scales. For example, Firefox version 128 shows blurry
                graphics when the viewbox is very small (like 5e-6). As a
                workaround for this issue, set scale_viewbox to a large number
                such as 1e6 for layouts.
        """
        
        assert len(self.group_stack) == 1 # ensures that there is no subgroup() currently active.

        lx, ly, ux, uy = rect.tofloat()

        lx_p = lx - padding
        ly_p = ly - padding
        ux_p = ux + padding
        uy_p = uy + padding
        w_p = ux_p - lx_p
        h_p = uy_p - ly_p

        self.root.attrib['width'] = f'{w_p*self.pixel_per_unit}px'
        self.root.attrib['height'] = f'{h_p*self.pixel_per_unit}px'
        self.viewbox = [scale_viewbox*lx_p, scale_viewbox*ly_p, scale_viewbox*w_p, scale_viewbox*h_p]
        self.root.attrib['viewBox'] = ' '.join([str(x) for x in self.viewbox])
        # Not sure why this is the correct transform matrix:
        self.cur_group.attrib['transform']=f"matrix({scale_viewbox} 0 0 {-scale_viewbox} 0 {(uy+ly)*scale_viewbox})"

    def indent_xml_recursive(self, elem, depth):
        if elem.tag in ('text',):
            # Spaces within <text></text> are sometimes rendered. To avoid this,
            # no not add spaces / new lines within <text></text. 
            return
        if elem.text:
            # Also skip elements with leading text to avoid messing up something
            # here. This is likely never the case, unless indent_xml() is called
            # twice.
            return
        if len(elem):
            # For elements that have children, indent children:

            indent = '  '
            indent_here  = '\n' + depth*indent
            indent_below = '\n' + (depth + 1)*indent

            # Increase indentation after <opening> tag:
            elem.text =  indent_below
            for i, subelem in enumerate(elem):
                if not subelem.tail:
                    if i < len(elem)-1:
                        subelem.tail = indent_below
                    else:
                        # Reduce indentation for </closing> tag after last element:
                        subelem.tail = indent_here
                self.indent_xml_recursive(subelem, depth + 1)

    def indent_xml(self):
        """Add newlines and indent SVG without messing up <text>."""
        self.indent_xml_recursive(self.root, 0)

    def inner_svg(self) -> bytes:
        """Like svg(), but without the top <svg> tag."""
        return b''.join(ET.tostring(e) for e in self.root)

    def svg(self) -> bytes:
        """
        Returns SVG XML data as bytes. (Does not depend on cairo or other
        fancy SVG libraries.)
        """
        return ET.tostring(self.root)

    # Use inline SVG (with svg()) instead of svg-as-image (base64-encoded SVG +
    # <img> using old svg_url() and html() methods). Advantages of inline SVG
    # are (1) that the containing HTML can control font loading and
    # (2) easier interaction with containing HTML (click, hover etc.)

    # def svg_url(self) -> str:
    #     """
    #     Returns SVG XML data packed into Base64 encoded URL.
    #     """
    #     return f"data:image/svg+xml;base64,{b64encode(self.svg()).decode('ascii')}"

    # def html(self) -> str:
    #     return f'<img src="{self.svg_url()}" />'

    def webdata(self):
        return 'svg', {'inner': self.inner_svg().decode('ascii'), 'viewbox': self.viewbox}

    def png(self) -> bytes:
        """
        This method is a thin wrapper around the svg() method that uses cairosvg
        to convert the SVG data to a PNG raster image.

        One of the goals of this new render module is to get rid of the
        cairo and pango dependencies, or at least weaken them. Maybe use the
        method only in test code. I am not sure yet if the cairosvg is as
        error-prone as pycairo + pangi via python3-gi, but maybe just avoid it.

        Earlier trials using the 'wand' library did not lead to satisfactory
        results: the fonts and text baselines were messed up. This is strange,
        as ImageMagick's command line tool 'convert' did not have those
        problems.
        """
        import cairosvg
        return cairosvg.svg2png(self.svg())

default_css_schematic = """
svg {
    stroke-linecap: butt;
    stroke-linejoin: bevel;
}
text {
    font-size: 11pt;
    font-family: "Inconsolata", monospace;
    font-stretch: 75%;
}
.instanceName {
    font-weight: bold;
    fill: #f00;
}
.pinLabel, .pinArrow {
    fill: #f00;
}
.params, .cellName {
    fill: #80b380;
}
.symbolOutline {
    stroke: #80b380;
}
.symbolPoly {
    stroke: #000;
}
.symbolOutline, .symbolPoly, .schemWire, .tapPoint {
    fill: none;
    stroke-width: 0.1;
}
#grid {
    fill: #ccc;
}
.schemWire, .tapPoint {
    stroke: #cc0;
}
.schemWire {
    stroke-linecap: square;
}
.connPoint, .tapPointLabel {
    fill: #cc0;
}
.portArrow, .portLabel {
    fill: #39f;
}
"""
default_css_schematic = re.sub(r"\s+", " ", default_css_schematic).strip() # remove newlines / unneeded spaces

class SchematicRenderer(Renderer):
    css = default_css_schematic

    def __init__(self, include_nids: bool=True, enable_css: bool=True, enable_grid: bool=True):
        self.enable_grid = enable_grid
        return super().__init__(include_nids=include_nids, enable_css=enable_css)

    def draw_grid(self, rect: Rect4R, dot_size: float = 0.1):
        lx, ly, ux, uy = rect.tofloat()
        with self.subgroup():
            self.cur_group.attrib['id']='grid'

            for x in range(math.floor(lx), math.ceil(ux)+1):
                for y in range(math.floor(ly), math.ceil(uy)+1):
                    ET.SubElement(self.cur_group, 'rect',
                        x=str(x - dot_size/2), y=str(y - dot_size/2),
                        height=str(dot_size), width=str(dot_size)
                        )

    def render_symbol(self, s: Symbol):
        self.setup_canvas(s.outline)
        if self.enable_grid:
            self.draw_grid(s.outline)
        self.draw_symbol(s, TD4())

    def render_schematic(self, s: Schematic):
        self.setup_canvas(s.outline)
        if self.enable_grid:
            self.draw_grid(s.outline)

        for poly in s.all(SchemWire):
            p = ET.SubElement(self.cur_group, 'path', d=poly.svg_path())
            p.attrib['class'] = 'schemWire'

        for p in s.all(SchemConnPoint):
            cx, cy = p.pos.tofloat()
            circle = ET.SubElement(self.cur_group, 'circle', cx=str(cx), cy=str(cy), r=str(self.conn_point_radius))
            circle.attrib['class']='connPoint'

        for p in s.all(SchemTapPoint):
            self.draw_schem_tappoint(p)

        for inst in s.all(SchemInstance):
            with self.subgroup(node=inst):
                trans = inst.loc_transform()
                self.draw_symbol(inst.symbol, trans, inst.full_path_str())

        for port in s.all(SchemPort):
            with self.subgroup(node=port):
                self.draw_schem_port(port)

    def draw_symbol(self, s: Symbol, trans: TD4, inst_name: str="?"):
        # Draw outline
        rect = trans * s.outline
        lx, ly, ux, uy = rect.tofloat()
        outline = ET.SubElement(self.cur_group, 'rect',
            x=str(lx), y=str(ly), width=str(ux-lx), height=str(uy-ly))
        outline.attrib['class'] = 'symbolOutline'

        #params_str = cell.params_str()
        params_str = "\n".join(s.cell.params_list())

        self.draw_label(type(s.cell).__name__,
            rect.north_east().transl() * D4.R90, svg_class="cellName")
        self.draw_label(params_str, rect.south_east().transl() * D4.R90,
            valign=VAlign.Bottom, svg_class="params")
        self.draw_label(inst_name, rect.north_west().transl() * D4.MX90,
            svg_class="instanceName")
        
        for poly in s.all(SymbolPoly):
            p = ET.SubElement(self.cur_group, 'path', d=poly.svg_path(),
                transform=trans.svg_transform())
            p.attrib['class'] = 'symbolPoly'
        
        for arc in s.all(SymbolArc):
            p = ET.SubElement(self.cur_group, 'path', d=arc.svg_path(),
                transform=trans.svg_transform())
            p.attrib['class'] = 'symbolPoly'
        
        for pin in s.all(Pin):
            self.draw_pin(pin, trans)

    def draw_pin(self, pin: Pin, trans: TD4):
        # Flip by 180 degrees, as the text face the opposite of the pin direction:
        trans_local = trans * pin.pos.transl() * D4.R180 * pin.align

        self.draw_arrow(ArrowType.Pin, pin.pintype, trans_local)

        label = str(pin.full_path_str())
        self.draw_label(label, trans_local,
            valign=VAlign.Bottom, svg_class='pinLabel')

    def draw_arrow(self, arrowtype: ArrowType, pt: PinType, trans: TD4):
        if arrowtype == ArrowType.Pin:
            svg_class = 'pinArrow'
            center = True
            halfheight = 0.2
            width = 0.4
        else:
            svg_class='portArrow'
            center=False
            halfheight=0.25
            width=0.5
        arrow_left = pt in (PinType.Inout, PinType.Out)
        arrow_right = pt in (PinType.Inout, PinType.In)

        left_tip = halfheight if arrow_left else 0
        right_tip = halfheight if arrow_right else 0
        
        if center:
            m = trans * Vec2R(x=0,y=width/2).transl()
        else:
            m = trans

        d = ' '.join([
            "M0 0",
            f"L{halfheight} {-right_tip}",
            f"L{halfheight} {-width+left_tip}",
            f"L0 {-width}",
            f"L{-halfheight} {-width+left_tip}",
            f"L{-halfheight} {-right_tip}",
            "Z",
            ])

        p=ET.SubElement(self.cur_group, 'path', d=d, transform=m.svg_transform())
        p.attrib['class']=svg_class

    def draw_schem_port(self, p: SchemPort):
        trans = p.pos.transl() * p.align
        self.draw_arrow(ArrowType.Port, p.ref.pin.pintype, trans)
        
        label = p.ref.pin.full_path_str()
        self.draw_label(label, trans*D4.R180,
            space=self.port_text_space, halign=HAlign.Left, valign=VAlign.Middle,
            svg_class='portLabel')

    def draw_schem_tappoint(self, p: SchemTapPoint):
        is_default_supply = p.root.default_supply == p.ref
        is_default_ground = p.root.default_ground == p.ref
        if is_default_supply:
            d = ' '.join([
                "M0 0",
                "L0 1.0",
                "M0.25 0.5",
                "L0 1.0",
                "L-0.25 0.5",
                ])
        elif is_default_ground:
            d = ' '.join([
                "M0 0",
                "L0 0.5",
                "M-0.375 0.5",
                "L0.375 0.5",
                "M-0.25 0.75",
                "L0.25 0.75",
                "M-0.125, 1.0",
                "L0.125 1.0",
                ])
        else:
            d = ' '.join([
                "M0 0",
                "L0 0.5",
                ])

        tran = p.loc_transform()

        path = ET.SubElement(self.cur_group, 'path', d=d, transform=tran.svg_transform())
        path.attrib['class'] = 'tapPoint'
        
        if not (is_default_supply or is_default_ground):
            label = p.ref.full_path_str()
            self.draw_label(label, tran,
                space=self.port_text_space, valign=VAlign.Middle,
                svg_class="tapPointLabel")


default_css_layout = """
svg {
    stroke-linecap: butt;
    stroke-linejoin: bevel;
}
"""

# In general, we want the following, but it is somehow slow in browsers:
# path {
#     mix-blend-mode: screen;
#     vector-effect: non-scaling-stroke;
# }
# .isolate {
#     isolation:isolate;
# }
# Look into this issue further if possible (Firefox WebRender etc.)


default_css_layout = re.sub(r"\s+", " ", default_css_layout).strip() # remove newlines / unneeded spaces

class LayoutRenderer(Renderer):
    css = default_css_layout

    def __init__(self, *args, **kwargs):
        self.auto_outline = None
        return super().__init__(*args, **kwargs)

    def setup_canvas(self, rect: Rect4R, padding: float = 1.0, scale_viewbox: float = 1.0):
        # Initialize the coordinate system to how we like it:
        super().setup_canvas(rect, padding, scale_viewbox)

        self.root.attrib['width'] = '300px'
        self.root.attrib['height'] = '300px'

    def auto_outline_add(self, point: Vec2R):
        if self.auto_outline:
            self.auto_outline = self.auto_outline.extend(point)
        else:
            self.auto_outline = Rect4R(point.x, point.y, point.x, point.y)

    def render_layout(self, l: Layout):
        self.layer_groups = {}
        for poly in l.all(RectPoly):

            layer_nid = poly.layer.nid
            try:
                layer_g = self.layer_groups[layer_nid]
            except KeyError:    
                layer_g = ET.SubElement(self.cur_group, 'g')
                self.layer_groups[layer_nid] = layer_g
                layer = poly.layer
                layer_g.attrib['id'] = f'layer_nid{layer.nid}'
                layer_g.attrib['data-layer-path'] = layer.full_path_str()
                layer_g.attrib['style'] = f"fill:{layer.style_color};"
            
            p = ET.SubElement(layer_g, 'path', d=poly.svg_path())
            p.attrib['class'] = 'rectPoly'
            for vertex in poly.vertices:
                self.auto_outline_add(vertex.pos)

        self.setup_canvas(self.auto_outline, padding=0.0, scale_viewbox=1e9)
        self.cur_group.attrib['class'] = 'isolate'

def render(obj, **kwargs) -> Renderer:
    if isinstance(obj, Symbol):
        r = SchematicRenderer(**kwargs)
        r.render_symbol(obj)
    elif isinstance(obj, Schematic):
        r = SchematicRenderer(**kwargs)
        r.render_schematic(obj)
    elif isinstance(obj, Layout):
        r = LayoutRenderer(**kwargs)
        r.render_layout(obj)
    else:
        raise TypeError(f"Unsupported object {obj} for rending.")
    r.indent_xml()
    return r
