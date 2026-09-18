# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import xml.etree.ElementTree as ET
import math
from contextlib import contextmanager
from ..core import *
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

def clean_css(css: str) -> str:
    """remove newlines / unneeded spaces from CSS literal string"""
    return re.sub(r"\s+", " ", css).strip()

def annotation_lines(s: Symbol, inst: SchemInstance|None) -> list[tuple[str, AnnotationKind]]:
    """
    The shown lines of the annotation block of symbol s, as (text, kind),
    with the schematic's SchemAnnotationOverrides applied when drawn as
    instance inst. Instance name lines are omitted for a symbol on its own.
    """
    shown = {a.nid: a.shown for a in s.all(SymbolAnnotation)}
    if inst is not None:
        for o in inst.root.all(SchemAnnotationOverride.ref_idx.query(inst)):
            shown[o.there.nid] = o.shown
    lines = []
    for a in s.all(SymbolAnnotation):
        if not shown[a.nid]:
            continue
        if a.kind == AnnotationKind.InstanceName:
            if inst is None:
                continue
            lines.append((inst.full_path_label(), a.kind))
        else:
            lines.append((a.text, a.kind))
    return lines

def annotation_row_chars(row: list) -> int:
    """Length of a text row; its entries are separated by one space."""
    return sum(len(text) for text, kind in row) + len(row) - 1

def annotation_rows(lines: list, wrap: int) -> list[list]:
    """
    Arranges the lines of an annotation block (see annotation_lines) into
    text rows: consecutive entries share a row as long as it stays within
    wrap characters. wrap=0 is the default arrangement with one entry per
    row; larger values make the block flatter.
    """
    rows = []
    for line in lines:
        if rows and annotation_row_chars(rows[-1] + [line]) <= wrap:
            rows[-1].append(line)
        else:
            rows.append([line])
    return rows

def annotation_anchor(s: Symbol, trans: TD4R, inst: SchemInstance|None) -> tuple[TD4R, int] | None:
    """
    Anchor of the annotation block (position and direction the text extends
    in, see Renderer.draw_label) and its arrangement (wrap, see
    annotation_rows): the instance's annotation_pos and annotation_wrap if
    set, else the block is placed against the symbol's own geometry (a
    symbol on its own, or an instance of a schematic that never ran
    place_annotations; see SchematicRenderer.render_schematic for the
    latter). None if no line of the block is shown.
    """
    if inst is not None and inst.annotation_pos is not None:
        return inst.annotation_pos.transl() * inst.annotation_align, inst.annotation_wrap
    from .annotate import place_block, symbol_obstacles, symbol_body, rect_anchor
    placed = place_block(s, trans, inst, [r.tofloat() for r in symbol_obstacles(s, trans, inst)])
    if placed is None:
        return None
    rect, wrap = placed
    return rect_anchor(rect, symbol_body(s, trans, inst)), wrap

def annotation_extent(s: Symbol, trans: TD4R, inst: SchemInstance|None) -> Rect4R | None:
    """
    Estimated bounding box of the annotation block of s (drawn as instance
    inst, or on its own), or None if no line of it is shown.
    """
    lines = annotation_lines(s, inst)
    if not lines:
        return None
    anchor, wrap = annotation_anchor(s, trans, inst)
    rows = annotation_rows(lines, wrap)
    return Renderer.label_rect(anchor, max(annotation_row_chars(row) for row in rows), len(rows))

class Renderer:
    """
    Instantiate the Renderer class and then call one of its render_ methods,
    e.g. render_schematic(). draw_... and other methods are more internal.
    Afterwards, obtain the result via the svg() method.
    """

    pin_text_space = 0.125
    port_text_space = 0.15 + 0.5
    # Estimated character width in schematic units (11pt Inconsolata at 75%
    # stretch, scaled by 0.045), for layout that has to reserve text space.
    label_char_width = 0.3
    pixel_per_unit = 25
    conn_point_radius = 0.1625
    # font_size_internal_pt must match the font-size in the css class
    # attribute. It has no effect on the rendered text size: draw_label()
    # divides it back out via its scale transform. Its value is a more-or-less
    # arbitrary constant kept near the browser default (12pt), so that text
    # degrades gracefully in contexts where the CSS is not applied.
    font_size_internal_pt = 11
    # The actual rendered font size, measured in schematic coordinates where
    # the grid pitch is 1: 0.66 makes one line of text about 2/3 of a grid
    # square tall, regardless of font_size_internal_pt and pixel_per_unit.
    font_size_actual_grid_units = 0.66
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
    def subgroup(self, node=None, existing_group=None, data_nid=None):
        if existing_group:
            self.group_stack.append(existing_group)
        else:
            self.group_stack.append(ET.SubElement(self.cur_group, 'g'))
        if data_nid is not None and self.include_nids:
            self.cur_group.attrib['data-nid'] = str(data_nid)
        try:
            yield
        finally:
            self.group_stack.pop()

    @classmethod
    def label_rect(cls, trans: TD4R, n_chars: int, n_lines: int, halign=HAlign.Left, valign=VAlign.Top, space=None) -> Rect4R:
        """
        Estimated bounding box of a label drawn by draw_label with the same
        arguments, using label_char_width per character.
        """
        align = trans.d4.unflip()
        if align in (West, South):
            halign = halign.invert()
        frame = trans.transl.transl()
        if align in (North, South):
            frame *= R90
        if space is None:
            space = cls.pin_text_space
        length = (space + cls.label_char_width * n_chars) * {HAlign.Left: 1, HAlign.Right: -1}[halign]
        depth = cls.font_size_actual_grid_units * n_lines
        if valign == VAlign.Top:
            y0, y1 = -(space + depth), 0
        elif valign == VAlign.Bottom:
            y0, y1 = 0, space + depth
        else:
            y0, y1 = -depth/2, depth/2
        return frame * Rect4R(min(0, length), y0, max(0, length), y1)

    def draw_label(self, text: str|list[list[tuple[str, str]]], trans: TD4R, halign=HAlign.Left, valign=VAlign.Top, space=None, svg_class: str=""):
        """
        Draws text (possibly multi-line, separated by newlines) extending from
        the translation of trans in the direction of its D4 component. Text
        is never rotated by 180 degrees: for West and South, halign is
        inverted instead.

        text is either a string drawn with svg_class, or a list of rows, each
        a list of (text, svg_class) spans that are drawn in one line,
        separated by spaces.
        """

        align = trans.d4.unflip()
        pos = trans.transl

        if align in (West, South):
            halign = halign.invert()

        # g_matrix has same basic translation as trans, but limits rotations of text
        # to 0 or 90 degrees (so that you never have to rotate your head by 180 degrees)
        g_matrix = pos.transl()
        if align in (South, North):
             g_matrix *= R90

        # Furthermore, g_matrix adds some space (padding):
        if space is None:
            space = self.pin_text_space
        g_matrix *= Vec2R(
            x = {HAlign.Left: +1, HAlign.Right: -1}[halign]*space,
            y = {VAlign.Bottom: +1, VAlign.Top: -1, VAlign.Middle: 0}[valign]*space,
            ).transl()

        # The CSS font-size resolves in the <text> element's local coordinate
        # system, where one em is font_size_internal_pt*96/72 user units
        # (1in = 96px = 72pt, see
        # https://www.w3.org/TR/css-values-4/#absolute-lengths).
        # The scale below divides that out again, so that
        # one em spans font_size_actual_grid_units schematic units.
        # Rounding avoids float noise (0.045000000000000005) in the SVG.
        # The negative y_scale un-flips the y-axis flip of setup_canvas.
        scale = round(self.font_size_actual_grid_units / (self.font_size_internal_pt * 96/72), 6)
        tag = ET.SubElement(self.cur_group, 'text', transform=g_matrix.svg_transform(x_scale=scale, y_scale=-scale))

        if isinstance(text, str):
            rows = [[(line, svg_class)] for line in text.split('\n')]
        else:
            rows = text
        if len(rows) == 1 and len(rows[0]) == 1:
            # Make the XML tree more compact by skipping <tspan> for single-line text:
            tag.text, svg_class = rows[0][0]
        else:
            svg_class = ""
            # Rows stack away from the anchor: downwards for Top, upwards
            # for Bottom, centered for Middle.
            first = {VAlign.Top: 0, VAlign.Bottom: 1-len(rows),
                VAlign.Middle: -(len(rows)-1)/2}[valign]
            for idx, row in enumerate(rows):
                tspan = ET.SubElement(tag, 'tspan', x="0", y=f"{first+idx}em")
                if len(row) == 1:
                    spans = [tspan]
                else:
                    spans = [ET.SubElement(tspan, 'tspan') for span in row]
                for span, (span_text, span_class) in zip(spans, row):
                    span.text = span_text
                    if span_class:
                        span.attrib['class'] = span_class
                for span in spans[:-1]:
                    span.tail = ' '

        tag.attrib['dominant-baseline'] = {
            VAlign.Top: 'hanging',
            VAlign.Bottom: 'ideographic',
            VAlign.Middle: 'middle',
            }[valign]
        tag.attrib['text-anchor'] = {HAlign.Left: 'start', HAlign.Right: 'end'}[halign]
        if svg_class:
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
        # This matrix maps (x, y) to (x, (uy+ly)-y), both scaled by
        # scale_viewbox: it flips the y axis (schematic y points up, SVG y
        # points down) by mirroring about the canvas midline y=(uy+ly)/2,
        # which maps the canvas y range [ly, uy] onto itself. This also
        # holds for the padded range, because the padding is symmetric.
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

    def webdata(self):
        return 'svg', {
            'inner': self.inner_svg().decode('ascii'),
            # The complete standalone document, so that consumers needing a
            # file (the scoreboard audit trail, see web/src/course.js) do not
            # have to re-assemble the root tag from the fragments above.
            'document': self.svg().decode('ascii'),
            'viewbox': self.viewbox,
            'width': self.root.attrib.get('width'),
            'height': self.root.attrib.get('height'),
        }

class SchematicRenderer(Renderer):
    css = clean_css("""
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
        .pinLabel, .pinArrow, .params, .cellName {
            fill: #000;
        }
        .symbolOutline {
            stroke: none;
        }
        .symbolPoly {
            stroke: #000;
        }
        .symbolOutline, .symbolPoly, .schemWire, .tapPoint {
            fill: none;
            stroke-width: 0.1;
        }
        g[data-srcline] .symbolOutline {
            pointer-events: all;
        }
        .grid {
            fill: #ccc;
        }
        .detail {
            display: none;
        }
        .schemWire, .tapPoint {
            stroke: #0066cc;
        }
        .schemWire {
            stroke-linecap: square;
        }
        .connPoint, .tapPointLabel {
            fill: #0066cc;
        }
        .portArrow, .portLabel {
            fill: #0066cc;
        }
        .errorMarker {
            fill: rgba(255, 0, 0, 0.25);
            stroke: none;
        }
    """)

    def __init__(self, include_nids: bool=True, enable_css: bool=True, enable_grid: bool=True):
        self.enable_grid = enable_grid
        return super().__init__(include_nids=include_nids, enable_css=enable_css)

    def draw_grid(self, rect: Rect4R, dot_size: float = 0.1):
        lx, ly, ux, uy = rect.tofloat()
        with self.subgroup():
            self.cur_group.attrib['class']='grid detail'

            for x in range(math.floor(lx), math.ceil(ux)+1):
                for y in range(math.floor(ly), math.ceil(uy)+1):
                    ET.SubElement(self.cur_group, 'rect',
                        x=str(x - dot_size/2), y=str(y - dot_size/2),
                        height=str(dot_size), width=str(dot_size)
                        )

    def render_symbol(self, s: Symbol):
        # The annotation block usually lies outside the outline.
        canvas = s.outline
        extent = annotation_extent(s, TD4R(), None)
        if extent is not None:
            canvas = canvas.extend(Vec2R(extent.lx, extent.ly)).extend(Vec2R(extent.ux, extent.uy))
        self.setup_canvas(canvas)
        if self.enable_grid:
            self.draw_grid(s.outline)
        self.draw_symbol(s, TD4R())

    def render_schematic(self, s: Schematic):
        from .annotate import block_rects, symbol_body, rect_anchor
        # Instances that were never placed (schematics built outside the
        # viewgen pipeline) get their annotation blocks placed here, without
        # storing the result.
        self.annotation_anchors = {}
        canvas = s.outline
        rects = block_rects(s)
        for inst in s.all(SchemInstance):
            if inst.nid not in rects:
                continue
            rect, wrap = rects[inst.nid]
            if inst.annotation_pos is None:
                body = symbol_body(inst.symbol, inst.loc_transform(), inst)
                self.annotation_anchors[inst.nid] = (rect_anchor(rect, body), wrap)
            canvas = canvas.extend(rect.southwest).extend(rect.northeast)
        self.setup_canvas(canvas)
        if self.enable_grid:
            self.draw_grid(s.outline)

        for poly in s.all(SchemWire):
            p = ET.SubElement(self.cur_group, 'path', d=poly.svg_path())
            p.attrib['class'] = 'schemWire'
            if self.include_nids:
                p.attrib['data-nid'] = str(poly.ref.nid)

        for p in s.all(SchemConnPoint):
            cx, cy = p.pos.tofloat()
            circle = ET.SubElement(self.cur_group, 'circle', cx=str(cx), cy=str(cy), r=str(self.conn_point_radius))
            circle.attrib['class'] = 'connPoint'
            if self.include_nids:
                circle.attrib['data-nid'] = str(p.ref.nid)

        for p in s.all(SchemTapPoint):
            self.draw_schem_tappoint(p)

        for inst in s.all(SchemInstance):
            with self.subgroup(node=inst, data_nid=inst.nid):
                # Source location for click-to-source
                if self.include_nids and inst.src_loc is not None:
                    self.cur_group.attrib['data-srcfile'] = str(inst.src_loc.filename)
                    self.cur_group.attrib['data-srcline'] = str(inst.src_loc.line)
                    self.cur_group.attrib['data-srccol'] = str(inst.src_loc.column)
                self.draw_symbol(inst.symbol, inst.loc_transform(), inst)

        for port in s.all(SchemPort):
            with self.subgroup(node=port, data_nid=port.ref.nid):
                self.draw_schem_port(port)

        for err in s.all(SchemErrorMarker):
            self.draw_error_marker(err)

    def draw_error_marker(self, err: SchemErrorMarker):
        cx, cy = err.pos.tofloat()
        circle = ET.SubElement(self.cur_group, 'circle',
            cx=str(cx), cy=str(cy), r='0.5')
        circle.attrib['class'] = 'errorMarker'
        circle.attrib['data-error'] = err.error_type.value

    #: Block (anchor, wrap) by instance nid, filled by render_schematic.
    annotation_anchors = {}

    annotation_class = {
        AnnotationKind.CellName: 'cellName',
        AnnotationKind.InstanceName: 'instanceName',
        AnnotationKind.Param: 'params',
    }

    def draw_symbol(self, s: Symbol, trans: TD4R, inst: SchemInstance|None=None):
        # The outline rect is not drawn (stroke: none), but stays in the SVG
        # as the hit area for click-to-source (see pointer-events rule in css
        # and svg.js) and to identify instance groups in the web UI.
        rect = trans * s.outline
        lx, ly, ux, uy = rect.tofloat()
        outline = ET.SubElement(self.cur_group, 'rect',
            x=str(lx), y=str(ly), width=str(ux-lx), height=str(uy-ly))
        outline.attrib['class'] = 'symbolOutline'

        for t in s.all(SymbolText):
            if t.kind == AnnotationKind.InstanceName:
                if inst is None:
                    continue
                text = inst.full_path_label()
            else:
                text = t.text
            self.draw_label(text, trans * t.pos.transl() * t.align,
                svg_class=self.annotation_class[t.kind])

        lines = annotation_lines(s, inst)
        if lines:
            if inst is not None and inst.nid in self.annotation_anchors:
                anchor, wrap = self.annotation_anchors[inst.nid]
            else:
                anchor, wrap = annotation_anchor(s, trans, inst)
            lines = [(text, self.annotation_class[kind]) for text, kind in lines]
            self.draw_label(annotation_rows(lines, wrap), anchor)

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

    def draw_pin(self, pin: Pin, trans: TD4R):
        # Flip by 180 degrees, as the text face the opposite of the pin direction:
        trans_local = trans * pin.pos.transl() * R180 * pin.align

        if pin.show_arrow:
            self.draw_arrow(ArrowType.Pin, pin.pintype, trans_local)

        label = pin.full_path_label()
        # Labels go below horizontal stubs and left of vertical stubs. This
        # keeps the area above horizontal stubs free, where symbols like the
        # MOS place their annotation block.
        if trans_local.d4.unflip() in (East, West):
            valign = VAlign.Top
        else:
            valign = VAlign.Bottom
        # Hidden labels stay in the SVG for the detail view (see css).
        svg_class = 'pinLabel' if pin.show_label else 'pinLabel detail'
        self.draw_label(label, trans_local, valign=valign, svg_class=svg_class)

    def draw_arrow(self, arrowtype: ArrowType, pt: PinType, trans: TD4R):
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

        label = p.ref.pin.full_path_label()
        self.draw_label(label, trans*R180,
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
        if self.include_nids:
            path.attrib['data-nid'] = str(p.ref.nid)

        if not (is_default_supply or is_default_ground):
            label = p.ref.full_path_label()
            self.draw_label(label, tran,
                space=self.port_text_space, valign=VAlign.Middle,
                svg_class="tapPointLabel")

def render(obj, **kwargs) -> Renderer:
    if isinstance(obj, Symbol):
        r = SchematicRenderer(**kwargs)
        r.render_symbol(obj)
    elif isinstance(obj, Schematic):
        r = SchematicRenderer(**kwargs)
        r.render_schematic(obj)
    else:
        raise TypeError(f"Unsupported object {obj} for rendering.")
    r.indent_xml()
    return r
