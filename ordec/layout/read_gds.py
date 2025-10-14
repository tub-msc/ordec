# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from gdsii.library import Library
import gdsii.elements
import gdsii.structure

from ..core import *
from .helpers import poly_orientation

# python-gdsii was chosen over gdstk. The problem with gdstk is that it converts
# everything to floats (more or less destructively). python-gdsii exposes the
# raw integer values.


class GdsReaderException(Exception):
    pass

def read_gds_structure(structure: gdsii.structure.Structure, layers: LayerStack, unit: R) -> Layout:
    def conv_xy(xy):
        x, y = xy
        return Vec2I(x, y)

    def lookup_layer(gds_layer, gds_type, text:bool=False):
        l = GdsLayer(gds_layer, gds_type)
        if text:
            index = Layer.gdslayer_text_index
        else:
            index = Layer.gdslayer_shapes_index
        try:
            return layers.one(index.query(l))
        except QueryException:
            if text:
                elemtype = "text"
            else:
                elemtype = "shape"
            raise GdsReaderException(f"Unknown GDS layer {l} for {elemtype}.")

    layout = Layout(ref_layers=layers)
    for elem in structure:
        if isinstance(elem, gdsii.elements.Boundary):
            layer = lookup_layer(elem.layer, elem.data_type, text=False)    
            if elem.xy[0] != elem.xy[-1]:
                raise GdsReaderException(f"Invalid GDS data: Boundary (LayoutPoly) {elem!r} not closed!")
            if len(elem.xy) < 4: # 4 = 3 vertices + 1 repeated end vertex
                raise GdsReaderException(f"Invalid GDS data: Boundary (LayoutPoly) {elem!r} has less than 3 vertices!")
            vertices=[conv_xy(xy) for xy in elem.xy[:-1]]
            if poly_orientation(vertices) == 'cw':
                vertices.reverse()
                assert poly_orientation(vertices) == 'ccw'
            layout % LayoutPoly(
                layer=layer,
                vertices=vertices
                )
        elif isinstance(elem, gdsii.elements.Text):
            layer = lookup_layer(elem.layer, elem.text_type, text=True)    
            layout % LayoutLabel(
                layer=layer,
                pos=conv_xy(elem.xy[0]),
                text=elem.string.decode('ascii'),
                )
        elif isinstance(elem, gdsii.elements.Path):
            layer = lookup_layer(elem.layer, elem.data_type, text=False)    
            if len(elem.xy) < 1:
                raise GdsReaderException(f"Invalid GDS data: Path {elem} has less than 3 vertices!")
            vertices=[conv_xy(xy) for xy in elem.xy]
            if elem.path_type == 0:
                endtype = PathEndType.FLUSH
            elif elem.path_type == 2:
                endtype = PathEndType.SQUARE
            elif elem.path_type == 1:
                raise GdsReaderException("GDS Path with path_type=1 (round ends) not supported.")
            elif elem.path_type == 4:
                raise GdsReaderException("GDS Path with path_type=4 (custom square ends) not supported.")
            else:
                raise GdsReaderException(f"Invalid GDS data: path_type={elem.path_type}.")
            layout % LayoutPath(
                layer=layer,
                vertices=vertices,
                endtype=endtype,
                )
        elif isinstance(elem, gdsii.elements.SRef):
            raise NotImplementedError("GDS SRef handler missing.")
            #print('sref', elem.struct_name, elem.xy, elem.elflags, elem.mag, elem.angle)
        elif isinstance(elem, gdsii.elements.ARef):
            raise NotImplementedError("GDS ARef handler missing.")
        elif isinstance(elem, gdsii.elements.Box):
            raise NotImplementedError("GDS Box handler missing.")
        elif isinstance(elem, gdsii.elements.Node):
            raise NotImplementedError("GDS Node handler missing.")
        else:
            raise GdsReaderException("Unknown GDS element: {elem!r}")

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
        #    print(p.layer.full_path_str(), p.vertices())

        #print(layout.tables())
        layouts[name] = layout

    return layouts
