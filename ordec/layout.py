# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from gdsii.library import Library
import gdsii.elements
import gdsii.structure

# python-gdsii was chosen over gdstk. The problem with gdstk is that it converts
# everything to floats (more or less destructively). python-gdsii exposes the
# raw integer values.

from ordec.core import *
from .render import render

class SG13G2(Cell):
    @generate
    def layers(self):
        s = LayerStack(cell=self)

        # Frontend layers
        # ---------------

        s.Activ = Layer(
            gdslayer_shapes=GdsLayer(layer=1, data_type=0),
            style_color="#00ff00",
            )

        s.GatPoly = Layer(
            gdslayer_shapes=GdsLayer(layer=5, data_type=0),
            style_color="#bf4026",
            )
        s.GatPoly.pin = Layer(
            gdslayer_shapes=GdsLayer(layer=5, data_type=2),
            style_color="#bf4026",
            )
        
        s.Cont = Layer(
            gdslayer_shapes=GdsLayer(layer=6, data_type=0),
            style_color="#00ffff",
            )

        s.pSD = Layer(
            gdslayer_shapes=GdsLayer(layer=14, data_type=0),
            style_color="#ccb899",
            )

        s.NWell = Layer(
            gdslayer_shapes=GdsLayer(layer=31, data_type=0),
            style_color="#268c6b",
            )


        # Metal stack
        # -----------

        def addmetal(name, layer, color):
            setattr(s, name, Layer(
                gdslayer_shapes=GdsLayer(layer=layer, data_type=0),
                style_color=color,
            ))
            getattr(s, name).pin = Layer(
                gdslayer_text=GdsLayer(layer=layer, data_type=25),
                gdslayer_shapes=GdsLayer(layer=layer, data_type=2),
                style_color=color,
            )

        addmetal("Metal1", 8, "#39bfff")
        addmetal("Metal2", 10, "#ccccd9")
        addmetal("Metal3", 30, "#d80000")
        addmetal("Metal4", 50, "#93e837")
        addmetal("Metal5", 67, "#dcd146")
        addmetal("TopMetal1", 126, "#ffe6bf")
        addmetal("TopMetal2", 134, "#ff8000")

        # Vias
        # ----

        def addvia(name, layer, color):
            setattr(s, name, Layer(
                gdslayer_shapes=GdsLayer(layer=layer, data_type=0),
                style_color=color,
            ))

        addvia("Via1", 19, "#ccccff")
        addvia("Via2", 29, "#ff3736")
        addvia("Via3", 49, "#9ba940")
        addvia("Via4", 66, "#deac5e")
        addvia("TopVia1", 125, "#ffe6bf")
        addvia("TopVia2", 133, "#ff8000")

        # Other layers
        # ------------

        s.EXTBlock = Layer(
            gdslayer_shapes=GdsLayer(layer=111, data_type=0),
            style_color="#5e00e6",
            )

        s.MIM = Layer(
            gdslayer_shapes=GdsLayer(layer=36, data_type=0),
            style_color="#268c6b",
            )

        s.Substrate = Layer(
            gdslayer_shapes=GdsLayer(layer=40, data_type=0),
            style_color="#ffffff",
            )

        s.HeatTrans = Layer(
            gdslayer_shapes=GdsLayer(layer=51, data_type=0),
            style_color="#8c8ca6",
            )

        s.TEXT = Layer(
            gdslayer_text=GdsLayer(layer=63, data_type=0),
            )

        s.Recog = Layer(
            gdslayer_shapes=GdsLayer(layer=99, data_type=31),
            style_color="#bdcccc",
            )

        s.Vmim = Layer(
            gdslayer_shapes=GdsLayer(layer=129, data_type=0),
            style_color="#ffe6bf",
            )
        
        s.prBoundary = Layer(
            gdslayer_shapes=GdsLayer(layer=189, data_type=4), # data_type 4 or 0?
            style_color="#9900e6",
            )

        return s

def poly_orientation(vertices: list[Vec2R]):
    """
    Returns either 'cw' or 'ccw'.
    Warning: Does not work for complex (i.e. self-intersecting) polygons!
    """

    # See https://en.wikipedia.org/wiki/Curve_orientation#Orientation_of_a_simple_polygon
    B_idx = 0
    B = vertices[0]
    for v_idx, v in enumerate(vertices):
        if (v.x < B.x) or ((v.x == B.x) and (v.y < B.y)):
            B_idx = v_idx
            B = v
    A = vertices[(B_idx - 1) % len(vertices)]
    C = vertices[(B_idx + 1) % len(vertices)]

    det = (B.x-A.x)*(C.y-A.y) - (C.x-A.x)*(B.y-A.y)
    if (A == B) or (B == C) or (det == 0):
        raise ValueError("Invalid polygon.")
    if det < 0:
        return 'cw'
    else:
        return 'ccw'


def read_gds_structure(structure: gdsii.structure.Structure, layers: LayerStack, unit: R) -> Layout:
    def conv_xy(xy):
        x, y = xy
        return Vec2R(unit * x, unit * y)

    layout = Layout(ref_layers=layers)
    for elem in structure:
        if isinstance(elem, gdsii.elements.Boundary):
            l = GdsLayer(elem.layer, elem.data_type)
            try:
                layer = layers.one(Layer.gdslayer_shapes_index.query(l))
            except QueryException:
                print(f"WARNING: ignored Boundary on GDS layer {l}.")
            else:
                if elem.xy[0] != elem.xy[-1]:
                    raise ValueError(f"Invalid GDS data: polygon {elem} not closed!")
                if len(elem.xy) < 4: # 4 = 3 vertices + 1 repeated end vertex
                    raise ValueError(f"Invalid GDS data: polygon {elem} has less than 3 vertices!")
                vertices=[conv_xy(xy) for xy in elem.xy[:-1]]
                if poly_orientation(vertices) == 'cw':
                    vertices.reverse()
                    assert poly_orientation(vertices) == 'ccw'
                layout % LayoutPoly(
                    layer=layer,
                    vertices=vertices
                    )
        elif isinstance(elem, gdsii.elements.Text):
            #print('text', elem.layer, elem.text_type) #, elem.xy, elem.string)
            l = GdsLayer(elem.layer, elem.text_type)
            try:
                layer = layers.one(Layer.gdslayer_text_index.query(l))
            except QueryException:
                print(f"WARNING: ignored Text on GDS layer {l}.")
            else:
                layout % Label(
                    layer=layer,
                    pos=conv_xy(elem.xy[0]),
                    text=elem.string.decode('ascii'),
                    )
        elif isinstance(elem, gdsii.elements.SRef):
            print('sref', elem.struct_name, elem.xy, elem.elflags, elem.mag, elem.angle)
        else:
            print(f"WARNING: {type(elem)} not handled.")

    return layout.freeze()

def read_gds(gds_fn, layers, top=None):
    with open(gds_fn, 'rb') as stream:
        lib = Library.load(stream)

    # This rounds the GDS units to the closest round decimal fractions:
    unit = R(format(lib.physical_unit, '.4e'))
    #logical_unit = R(format(lib.logical_unit, '.4e'))
    # 'unit' is the scaling factor to convert the database numbers to Rational
    # numbers in SI scale (which is what ORDeC uses for now).

    #print(SG13G2().layers.tables())

    layouts = {}

    for structure in lib:
        name = structure.name.decode('ascii')
        if top and name != top:
            continue

        layout = read_gds_structure(structure, layers, unit)

        #for p in layout.all(LayoutPoly):
        #    print(p.layer.full_path_str(), [v.pos for v in p.vertices])

        #print(layout.tables())
        layouts[name] = layout

    return layouts

def to_rgb_tuple(s):
    assert s[0] == '#'
    s = s[1:]
    return tuple(int(s[i:i+2], 16) for i in (0, 2, 4))

def layout_webdata(layout: Layout.Frozen):
    weblayers_list = []
    weblayers_dict = {}
    for poly in layout.all(LayoutPoly):
        # Flat list of coordinates x0, y0, x1, y1 and so on. This is what
        # the JS earcut library wants.
        vertices = [v.pos.tofloat()[xy] for v in poly.vertices for xy in (0,1)]
        layer = poly.layer
        try:
            weblayer = weblayers_dict[layer]
        except KeyError:
            weblayer = {
                'nid': layer.nid,
                'path': layer.full_path_str(),
                'color': to_rgb_tuple(layer.style_color),
                'cssColor': layer.style_color,
                'polys': [],
            }
            weblayers_list.append(weblayer)
            weblayers_dict[layer] = weblayer

        weblayer['polys'].append({
            'nid': poly.nid,
            'vertices': vertices,
        })

    return 'layout_gl', {
        'layers': weblayers_list,
    }
