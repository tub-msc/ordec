# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import io
from typing import IO
from public import public
from gdsii.library import Library
from gdsii.structure import Structure
from gdsii.record import Record
import gdsii.elements as elements
from gdsii import types, tags

from ..core import *
from .helpers import expand_rectpolys, expand_rectpaths, expand_rects

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

class GdsGenerator:
    def name_of_layout(self, layout: Layout):
        try:
            return self.layout_names[layout].encode('ascii')
        except KeyError:
            if layout.cell is None:
                basename = f"__{id(layout.subgraph):x}"
            else:
                basename = layout.cell.escaped_name()
            name = basename
            suffix = 0
            while name in self.layout_names:
                name = f"{basename}_{suffix}"
                suffix += 1
            self.layout_names[layout] = name
            return name.encode('ascii')

    def layout_to_struc(self, layout: Layout):
        struc = Structure(name=self.name_of_layout(layout))

        if layout.ref_layers != self.layers:
            raise ValueError(f"ref_layers mismatch during write_gds: {layout.ref_layers!r} != {self.layers!r}")

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
                struct_name=self.name_of_layout(inst.ref),
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
                struct_name=self.name_of_layout(insta.ref),
                xy=[pos_origin, pos_col_end, pos_row_end],
                cols=insta.cols,
                rows=insta.rows,
            )
            e.angle, e.strans = d4_to_gds(insta.orientation)

            struc.append(e)

        self.lib.append(struc)
        return layouts_want

    def __init__(self, layers: LayerStack):
        self.layout_names = {}
        self.layers = layers
        self.lib = Library(
            version=3,
            name=b'LIB',
            physical_unit=float(layers.unit),
            logical_unit=0.001, # Not sure what this is exactly supposed to mean.
        )

    def add_layout(self, layout: Layout):
        layouts_want = {layout}
        layouts_have = set()
        layout_next = layout
        while True:
            want = self.layout_to_struc(layout_next)
            
            layouts_have.add(layout_next)
            layouts_want |= want

            try:
                layout_next = (layouts_want - layouts_have).pop()
            except KeyError:
                break

    def save(self, file: IO[bytes]):
        self.lib.sort(key=lambda e:e.name)
        self.lib.save(file)

@public
def write_gds(layout: Layout, file: IO[bytes]) -> dict[str,Layout]:
    """Write layout 'layout' as GDS binary data to file-like object 'file'."""

    g = GdsGenerator(layout.ref_layers)
    g.add_layout(layout)
    g.save(file)
    return g.layout_names
    

@public
def gds_str(file: IO[bytes]) -> str:
    """
    Reads GDS data from file-like object 'file' and returns text
    representation. Used mainly for testing.

    Hides modification and access times.
    """
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

@public
def gds_str_from_file(fn: str) -> str:
    """
    Opens given GDS filename and returns text representation.
    Used mainly for testing.
    """
    with open(fn, 'rb') as f:
        return gds_str(f)

@public
def gds_str_from_layout(layout: Layout) -> str:
    """
    Converts given layout into GDS data (using write_gds) and returns text
    representation. Used mainly for testing.
    """
    gds_out = io.BytesIO()
    write_gds(layout, gds_out)
    gds_out.seek(0)
    return gds_str(gds_out)
