# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from functools import partial
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

def gds_to_d4(angle: float|None, strans: int|None) -> D4:
    if strans == None:
        strans = 0
    if angle == None:
        angle = 0
    try:
        orientation = {
            0.0: D4.R0,
            90.0: D4.R90,
            180.0: D4.R180,
            270.0: D4.R270
        }[angle]
    except KeyError:
        raise GdsReaderException(f"SRef with angle {angle} not supported (must be multiple of 90).")
    if strans & (1<<15): # mirror x flag
        orientation = orientation * D4.MX
    return orientation

def gds_pathtype_to_endtype(path_type: int) -> PathEndType:
    if path_type == 0:
        return PathEndType.FLUSH
    elif path_type == 2:
        return PathEndType.SQUARE
    elif path_type == 1:
        raise GdsReaderException("GDS Path with path_type=1 (round ends) not supported.")
    elif path_type == 4:
        raise GdsReaderException("GDS Path with path_type=4 (custom square ends) not supported.")
    else:
        raise GdsReaderException(f"Invalid GDS data: path_type={path_type}.")

def read_gds_structure(structure: gdsii.structure.Structure, layers: LayerStack, unit: R, extlib: 'ExtLibrary') -> Layout:
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
            layout % LayoutPath(
                layer=layer,
                vertices=vertices,
                endtype=gds_pathtype_to_endtype(elem.path_type),
                )
        elif isinstance(elem, gdsii.elements.SRef):
            if elem.mag not in (1.0, None):
                raise GdsReaderException("SRef with magnification != 1.0 not supported.")
            ref_name = elem.struct_name.decode('ascii')
            layout % LayoutInstance(
                pos=conv_xy(elem.xy[0]),
                orientation=gds_to_d4(elem.angle, elem.strans),
                ref=extlib[ref_name].frame,
                )
        elif isinstance(elem, gdsii.elements.ARef):
            if elem.mag not in (1.0, None):
                raise GdsReaderException("ARef with magnification != 1.0 not supported.")
            ref_name = elem.struct_name.decode('ascii')
            try:    
                pos_origin, pos_col_end, pos_row_end = [conv_xy(xy) for xy in elem.xy]            
            except ValueError:
                raise GdsReaderException(f"Found ARef with len(elem.xy) of {len(elem.xy)}, expected 3.") from None
            layout % LayoutInstanceArray(
                pos=pos_origin,
                orientation=gds_to_d4(elem.angle, elem.strans),
                ref=extlib[ref_name].frame,
                cols=elem.cols,
                rows=elem.rows,
                vec_col=(pos_col_end - pos_origin) // elem.cols,
                vec_row=(pos_row_end - pos_origin) // elem.rows,
                )
        elif isinstance(elem, gdsii.elements.Box):
            raise NotImplementedError("GDS Box element not supported.")
        elif isinstance(elem, gdsii.elements.Node):
            raise NotImplementedError("GDS Node element not supported.")
        else:
            raise GdsReaderException("Unknown GDS element: {elem!r}")

    return layout.freeze()

def create_frame(name, lib) -> Layout:
    # at the moment: frame = layout
    return lib[name].layout

def gds_discover(gds_fn, layers, extlib):
    with open(gds_fn, 'rb') as stream:
        lib = Library.load(stream)

    unit = R(format(lib.physical_unit, '.4e'))
    if unit != layers.unit:
        raise Exception("GDS unit is not equal to layers.unit")
    
    layout_funcs = {}
    frame_funcs = {}

    for structure in lib:
        name = structure.name.decode('ascii')
        # Use functools.partial to create a closure. (Not really partial though,
        # since all argument values are provided.) This postponsed creation of
        # the Layout subgraphs to when they are requested/needed.
        layout_funcs[name] = partial(read_gds_structure, structure, layers, unit, extlib)
        frame_funcs[name] = partial(create_frame, name, extlib)

    return layout_funcs, frame_funcs
