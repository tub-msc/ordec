# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from functools import partial
import numpy as np

from ..core import *
from .helpers import poly_orientation
from . import gdsrecords
from .gdsrecords import BOUNDARY, PATH, SREF, AREF, TEXT, NODE, BOX, LAYER, \
    DATATYPE, XY, SNAME, COLROW, TEXTTYPE, STRING, STRANS, MAG, ANGLE, \
    PATHTYPE, BGNEXTN, ENDEXTN

# GDS files are read at record level by gdsrecords, which keeps the raw
# integer coordinates (gdstk converts everything to floats, more or less
# destructively) and does not build one Python object per element.

class GdsReaderException(Exception):
    pass

RECORD_NAMES = {LAYER: 'LAYER', DATATYPE: 'DATATYPE', TEXTTYPE: 'TEXTTYPE',
    XY: 'XY', COLROW: 'COLROW', STRING: 'STRING', SNAME: 'SNAME'}

def gds_to_d4(angle: float|None, strans: int|None) -> D4:
    if strans is None:
        strans = 0
    if angle is None:
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
        return PathEndType.Flush
    elif path_type == 2:
        return PathEndType.Square
    elif path_type == 4:
        return PathEndType.Custom
    elif path_type == 1:
        raise GdsReaderException("GDS Path with path_type=1 (round ends) not supported.")
    else:
        raise GdsReaderException(f"Invalid GDS data: path_type={path_type}.")

def read_gds_structure(data, name: str, start: int, end: int, layers: LayerStack, extlib: 'ExtLibrary') -> Layout:
    def conv_xy(xy):
        return [Vec2I(x, y) for x, y in zip(xy[0::2], xy[1::2])]

    def ints(e, rt, n=None) -> tuple[int]:
        """Values of the required integer record rt of element e (n values, if given)."""
        v = e.get(rt)
        if isinstance(v, int):
            v = (v,) # gdsrecords returns a single value bare
        if not (isinstance(v, tuple) and all(isinstance(x, int) for x in v)) \
                or (n is not None and len(v) != n) or (rt == XY and len(v) % 2):
            raise GdsReaderException(f"Invalid GDS data: element lacks a valid {RECORD_NAMES[rt]} record.")
        return v

    def text(e, rt) -> str:
        """Value of the required ASCII string record rt of element e."""
        v = e.get(rt)
        if isinstance(v, bytes):
            try:
                return v.decode('ascii')
            except UnicodeDecodeError:
                pass
        raise GdsReaderException(f"Invalid GDS data: element lacks a valid {RECORD_NAMES[rt]} record.")

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

    # Associating the layout with its ExtLibraryCell makes exports (GDS, LVS)
    # name it consistently with the symbol/schematic of the same cell.
    layout = Layout(ref_layers=layers, cell=extlib[name])
    shape_layers = {} # (gds layer, data type) -> Layer nid
    def lookup_shape_layer(gds_layer, gds_type):
        try:
            return shape_layers[gds_layer, gds_type]
        except KeyError:
            nid = lookup_layer(gds_layer, gds_type, text=False).nid
            shape_layers[gds_layer, gds_type] = nid
            return nid

    quads, elems = gdsrecords.read_structure(data, start, end)

    # Boundaries with five XY points: axis-aligned rectangles (almost all
    # elements of typical library cells, e.g. contacts and vias) become
    # LayoutRects, inserted as one array. A rectangle is closed and its four
    # points are exactly the four corners of its bounding box.
    quads = np.frombuffer(quads, dtype=np.int32).reshape(-1, 12)
    x = quads[:, 2:10:2]
    y = quads[:, 3:10:2]
    lx, ux = x.min(axis=1), x.max(axis=1)
    ly, uy = y.min(axis=1), y.max(axis=1)
    on_corner = ((x == lx[:, None]) | (x == ux[:, None])) & ((y == ly[:, None]) | (y == uy[:, None]))
    corner = (x == ux[:, None]) + 2 * (y == uy[:, None]) # 0 to 3
    is_rect = (quads[:, 2:4] == quads[:, 10:12]).all(axis=1) & (lx < ux) & (ly < uy) \
        & on_corner.all(axis=1) & (np.bitwise_or.reduce(1 << corner, axis=1) == 15)
    # Layer nid per quad, with one lookup per distinct (layer, data type).
    gds_layers, inverse = np.unique(quads[:, 0:2], axis=0, return_inverse=True)
    quad_layers = np.array([lookup_shape_layer(l, d) for l, d in gds_layers.tolist()],
        dtype=np.int64)[inverse.reshape(-1)]

    # All elements are inserted in a single transaction, which is much faster
    # than one transaction per element.
    with layout.updater() as sgu:
        def add(node):
            node.insert_into(sgu, sgu.nid_generate())

        def add_poly(layer, xy):
            if xy[:2] != xy[-2:]:
                raise GdsReaderException(f"Invalid GDS data: Boundary (LayoutPoly) with XY {xy!r} not closed!")
            if len(xy) < 8: # 4 points = 3 vertices + 1 repeated end vertex
                raise GdsReaderException(f"Invalid GDS data: Boundary (LayoutPoly) with XY {xy!r} has less than 3 vertices!")
            vertices = conv_xy(xy[:-2])
            if poly_orientation(vertices) == 'cw':
                vertices.reverse()
                assert poly_orientation(vertices) == 'ccw'
            add(LayoutPoly(layer=layer, vertices=vertices))

        def add_elem(kind, e):
            if kind == BOUNDARY:
                layer = lookup_shape_layer(*ints(e, LAYER, 1), *ints(e, DATATYPE, 1))
                add_poly(layer, list(ints(e, XY)))
            elif kind == TEXT:
                layer = lookup_layer(*ints(e, LAYER, 1), *ints(e, TEXTTYPE, 1), text=True)
                x, y = ints(e, XY, 2)
                add(LayoutLabel(layer=layer, pos=Vec2I(x, y), text=text(e, STRING)))
            elif kind == PATH:
                layer = lookup_shape_layer(*ints(e, LAYER, 1), *ints(e, DATATYPE, 1))
                vertices = conv_xy(ints(e, XY))
                if len(vertices) < 2:
                    raise GdsReaderException(f"Invalid GDS data: Path with XY {e[XY]!r} has less than 2 vertices!")
                endtype = gds_pathtype_to_endtype(e.get(PATHTYPE, 0))
                if endtype == PathEndType.Custom:
                    add(LayoutPath(layer=layer, vertices=vertices, endtype=endtype,
                        ext_bgn=e.get(BGNEXTN, 0), ext_end=e.get(ENDEXTN, 0)))
                else:
                    add(LayoutPath(layer=layer, vertices=vertices, endtype=endtype))
            elif kind == SREF:
                if e.get(MAG) not in (1.0, None):
                    raise GdsReaderException("SRef with magnification != 1.0 not supported.")
                x, y = ints(e, XY, 2)
                add(LayoutInstance(
                    pos=Vec2I(x, y),
                    orientation=gds_to_d4(e.get(ANGLE), e.get(STRANS)),
                    ref=extlib[text(e, SNAME)].frame,
                    ))
            elif kind == AREF:
                if e.get(MAG) not in (1.0, None):
                    raise GdsReaderException("ARef with magnification != 1.0 not supported.")
                pos_origin, pos_col_end, pos_row_end = conv_xy(ints(e, XY, 6))
                cols, rows = ints(e, COLROW, 2)
                add(LayoutInstanceArray(
                    pos=pos_origin,
                    orientation=gds_to_d4(e.get(ANGLE), e.get(STRANS)),
                    ref=extlib[text(e, SNAME)].frame,
                    cols=cols,
                    rows=rows,
                    vec_col=(pos_col_end - pos_origin) // cols,
                    vec_row=(pos_row_end - pos_origin) // rows,
                    ))
            elif kind == BOX:
                raise NotImplementedError("GDS Box element not supported.")
            elif kind == NODE:
                raise NotImplementedError("GDS Node element not supported.")
            else:
                raise GdsReaderException(f"Unknown GDS element: record type {kind:#04x}")

        for layer, row in zip(quad_layers[~is_rect].tolist(), quads[~is_rect, 2:].tolist()):
            add_poly(layer, row)
        for kind, e in elems:
            add_elem(kind, e)

        if is_rect.any():
            sgu.insert_array(LayoutRect, layer=quad_layers[is_rect],
                rect=np.stack([lx, ly, ux, uy], axis=1)[is_rect])

    return layout.freeze()

def create_frame(name, lib) -> Layout:
    # at the moment: frame = layout
    return lib[name].layout

def gds_discover(gds_fn, layers, extlib):
    # The file is read completely and kept in memory by the closures below
    # (later changes of the file on disk are not picked up); structures are
    # only decoded when their layout is requested. Not mmap: a file truncated
    # or rewritten while mapped would crash the process or yield garbage.
    with open(gds_fn, 'rb') as stream:
        data = stream.read()
    try:
        units, structures = gdsrecords.scan(data)
        unit = R(format(units[1], '.4e'))
        structures = [(name.decode('ascii'), start, end) for name, start, end in structures]
    except (ValueError, TypeError, IndexError) as exc:
        raise GdsReaderException(f"Cannot read GDS file {gds_fn}: {exc}") from None
    if unit != layers.unit:
        raise Exception("GDS unit is not equal to layers.unit")

    layout_funcs = {}
    frame_funcs = {}

    for name, start, end in structures:
        # Use functools.partial to create a closure. (Not really partial though,
        # since all argument values are provided.) This postponsed creation of
        # the Layout subgraphs to when they are requested/needed.
        layout_funcs[name] = partial(read_gds_structure, data, name, start, end, layers, extlib)
        frame_funcs[name] = partial(create_frame, name, extlib)

    return layout_funcs, frame_funcs
