# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from gdsii.library import Library
import gdsii.elements
import gdsii.structure

# python-gdsii was chosen over gdstk. The problem with gdstk is that it converts
# everything to floats (more or less destructively). python-gdsii exposes the
# raw integer values.

from ordec.core import *

class SG13G2(Cell):
    @generate
    def layers(self):
        s = LayerStack(cell=self)

        s.Activ = Layer(
            gdslayer_shapes=GdsLayer(layer=1, data_type=0),
            )

        s.GatPoly = Layer(
            gdslayer_shapes=GdsLayer(layer=5, data_type=0),
            )
        
        s.Cont = Layer(
            gdslayer_shapes=GdsLayer(layer=6, data_type=0),
            )

        s.Metal1 = Layer(
            gdslayer_shapes=GdsLayer(layer=8, data_type=0),
            )
        s.Metal1.pin = Layer(
            gdslayer_text=GdsLayer(layer=8, data_type=25),
            gdslayer_shapes=GdsLayer(layer=8, data_type=2),
            )

        s.Metal2 = Layer(
            gdslayer_shapes=GdsLayer(layer=10, data_type=0),
            )
        s.Metal2.pin = Layer(
            gdslayer_shapes=GdsLayer(layer=10, data_type=2),
            gdslayer_text=GdsLayer(layer=10, data_type=25),
            )

        s.pSD = Layer(
            gdslayer_shapes=GdsLayer(layer=14, data_type=0),
            )

        s.Via1 = Layer(
            gdslayer_shapes=GdsLayer(layer=19, data_type=0),
            )

        s.NWell = Layer(
            gdslayer_shapes=GdsLayer(layer=31, data_type=0),
            )

        s.TEXT = Layer(
            gdslayer_text=GdsLayer(layer=63, data_type=0),
            )

        s.Recog = Layer(
            gdslayer_shapes=GdsLayer(layer=99, data_type=31),
            )

        s.prBoundary = Layer(
            gdslayer_shapes=GdsLayer(layer=189, data_type=4), # data_type 4 or 0?
            )

        return s


def read_gds_structure(structure: gdsii.structure.Structure, layers: LayerStack, unit: R) -> Layout:

    def conv_xy(xy):
        x, y = xy
        return Vec2R(unit * x, unit * y)

    layout = Layout(ref_layers=layers)
    
    for elem in structure:
        if isinstance(elem, gdsii.elements.Boundary):
            #print('boundary', elem.layer, elem.data_type) #, elem.xy)
            #layers_shapes.add(GdsLayer(elem.layer, elem.data_type))
            layer = layers.one(Layer.gdslayer_shapes_index.query(GdsLayer(elem.layer, elem.data_type)))
            layout % RectPoly(
                layer=layer,
                vertices=[conv_xy(xy) for xy in elem.xy]
                )
        elif isinstance(elem, gdsii.elements.Text):
            #print('text', elem.layer, elem.text_type) #, elem.xy, elem.string)
            layer = layers.one(Layer.gdslayer_text_index.query(GdsLayer(elem.layer, elem.text_type)))
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

        #for p in layout.all(RectPoly):
        #    print(p.layer.full_path_str(), [v.pos for v in p.vertices])

        #print(layout.tables())
        layouts[name] = layout

    return layouts
