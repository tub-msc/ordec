# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from gdsii.library import Library
import gdsii.elements
import gdsii.structure

from ordec.core import *

# python-gdsii was chosen over gdstk. The problem with gdstk is that it converts
# everything to floats (more or less destructively). python-gdsii exposes the
# raw integer values.


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
        return Vec2I(x, y)

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
    if unit != layers.unit:
        raise Exception("GDS unit is not equal to layers.unit")
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
