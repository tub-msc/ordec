# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from gdsii.library import Library
from gdsii.structure import Structure
from gdsii.record import Record
import gdsii.elements as elements
from gdsii import types, tags
from public import public
from typing import IO

from ..core import *
from .helpers import expand_rectpolys, expand_rectpaths, expand_rects

def name_of_layout(layout: Layout):
    if layout.cell is None:
        return f"__{id(layout.subgraph):x}".encode('ascii')
    else:
        return repr(layout.cell).encode('ascii')

def d4_to_gds(d4: D4) -> tuple[float,int]:
    return {
        D4.R0: (0.0, 0),
        D4.R90: (90.0, 0),
        D4.R180: (180.0, 0),
        D4.R270: (270.0, 0),
        D4.MX: (0.0, (1<<15)),
        D4.MX90: (90.0, (1<<15)),
        D4.MY: (180.0, (1<<15)),
        D4.MY90: (270.0, (1<<15)),
    }[d4]

def layout_to_struc(layout: Layout):
    struc = Structure(name=name_of_layout(layout))

    layout = layout.mutable_copy()
    # Expand objects that are not supported by GDSII:
    expand_rectpolys(layout)
    expand_rectpaths(layout)
    expand_rects(layout)

    layouts_want = set()

    for poly in layout.all(LayoutPoly):
        gdslayer = poly.layer.gdslayer_shapes
        vertices = poly.vertices()
        vertices.append(vertices[0]) # close loop
        struc.append(elements.Boundary(
            layer=gdslayer.layer,
            data_type=gdslayer.data_type,
            xy=vertices,
        ))
    for label in layout.all(LayoutLabel):
        gdslayer = label.layer.gdslayer_text
        struc.append(elements.Text(
            layer=gdslayer.layer,
            text_type=gdslayer.data_type,
            xy=[label.pos],
            string=label.text.encode('ascii'),
        ))
    for path in layout.all(LayoutPath):
        gdslayer = path.layer.gdslayer_shapes
        e = elements.Path(
            layer=gdslayer.layer,
            data_type=gdslayer.data_type,
            xy=path.vertices()
        )
        e.width = path.width
        e.path_type = {PathEndType.FLUSH: 0, PathEndType.SQUARE: 2}[path.endtype]
        struc.append(e)
    for inst in layout.all(LayoutInstance):
        layouts_want.add(inst.ref)
        e = elements.SRef(
            struct_name=name_of_layout(inst.ref),
            xy=[inst.pos],
        )
        e.angle, e.strans = d4_to_gds(inst.orientation)

        struc.append(e)
    for insta in layout.all(LayoutInstanceArray):
        layouts_want.add(insta.ref)
        pos_origin = insta.pos
        pos_col_end = insta.pos + insta.cols*insta.vec_col
        pos_row_end = insta.pos + insta.rows*insta.vec_row
        e = elements.ARef(
            struct_name=name_of_layout(insta.ref),
            xy=[pos_origin, pos_col_end, pos_row_end],
            cols=insta.cols,
            rows=insta.rows,
        )
        e.angle, e.strans = d4_to_gds(insta.orientation)

        struc.append(e)

    return struc, layouts_want

@public
def write_gds(layout: Layout, file: IO[bytes]):
    """Write layout to GDS file."""

    layers = layout.ref_layers

    lib = Library(
        version=3,
        name=b'LIB',
        physical_unit=float(layers.unit),
        logical_unit=0.001, # Not sure what this is exactly supposed to mean.
        )

    layouts_want = {layout}
    layouts_have = set()
    layout_next = layout
    while True:
        struc, want = layout_to_struc(layout_next)
        lib.append(struc)    
        layouts_have.add(layout_next)
        layouts_want |= want

        try:
            layout_next = (layouts_want - layouts_have).pop()
        except KeyError:
            break
    lib.sort(key=lambda e:e.name)
    lib.save(file)

@public
def gds_to_str(file: IO[bytes]):
    lines = []
    level = 0
    indent = '  '
    for r in Record.iterate(file):
        line_out = (r.tag_name,)
        data = r.data
        if r.tag in (tags.ENDLIB, tags.ENDSTR, tags.ENDEXTN, tags.ENDEL):
            level -= 1

        if isinstance(data, bytes):
            data = data.decode('ascii')
        if isinstance(data, tuple) and len(data) == 1:
            data = data[0]
        if data is None or r.tag in (tags.BGNSTR, tags.BGNLIB):
            # hide data of BGNSTR and BGNLIB, which are modification/access times.
            lines.append(f"{level*indent}{r.tag_name}")
        else:
            lines.append(f"{level*indent}{r.tag_name}: {data!r}")

        if r.tag in (tags.BGNLIB, tags.BGNSTR, tags.BGNEXTN, tags.PATH, tags.BOX, tags.SREF, tags.AREF, tags.TEXT, tags.BOUNDARY, tags.NODE):
            level += 1
    return '\n'.join(lines)
