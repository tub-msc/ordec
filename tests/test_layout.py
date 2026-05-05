# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import io
import os
import re
from pathlib import Path
import importlib.resources
import pytest

from ordec.lib.ihp130 import SG13G2
from ordec.layout.gds_in import GdsReaderException
from ordec.layout import *
from ordec.core import *
from ordec.extlibrary import ExtLibrary, ExtLibraryError

def gds_text_from_file(fn):
    with open(fn, 'rb') as f:
        return gds_text(f)

def gds_text_from_layout(layout):
    buf = io.BytesIO()
    write_gds(layout, buf)
    buf.seek(0)
    return gds_text(buf)

# def test_read_gds():
#     ihp_path = Path(os.getenv("ORDEC_PDK_IHP_SG13G2"))
#     gds_fn = ihp_path / "libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds"
#     x = ordec.layout.read_gds(gds_fn, SG13G2().layers, 'sg13g2_xor2_1')
#     print(x)

gds_dir = importlib.resources.files("tests.layout_gds")

def test_extlibrary():
    # This test is very bare-bones at the moment.

    lib = ExtLibrary()
    tech_layers = SG13G2().layers
    lib.read_gds(gds_dir / 'test_polygon.gds', tech_layers)
    
    lib['TOP'].layout

    with pytest.raises(ExtLibraryError, match="No layout source found for cell"):
        lib['undefined'].layout

    with pytest.raises(ExtLibraryError, match="Multiple layout sources found for cell"):
        lib.read_gds(gds_dir / 'test_polygon.gds', tech_layers)

def test_gds_polygon():
    tech_layers = SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds(gds_dir / 'test_polygon.gds', tech_layers)
    layout = lib['TOP'].layout
    #print(layout.tables())
    polys = list(layout.all(LayoutPoly))
    assert len(polys) == 1
    poly = polys[0]
    assert poly.layer == tech_layers.Metal1
    # L-shaped polygon:
    # ┌┐
    # │└┐
    # └─┘
    assert poly.vertices() == [
        Vec2I(320, 0),
        Vec2I(320, 160),
        Vec2I(160, 160),
        Vec2I(160, 320),
        Vec2I(0, 320),
        Vec2I(0, 0),
    ]

@pytest.mark.parametrize("endtype", ['flush', 'square'])
def test_gds_path(endtype):
    tech_layers = SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds(gds_dir / f'test_path_{endtype}.gds', tech_layers)
    layout = lib['TOP'].layout
    #print(layout.tables())
    paths = list(layout.all(LayoutPath))
    assert len(paths) == 1
    path = paths[0]
    assert path.layer == tech_layers.Metal1
    assert path.vertices() == [
        Vec2I(0, 0),
        Vec2I(0, 500),
        Vec2I(500, 500),
    ]
    expected_endtype = getattr(PathEndType, endtype.capitalize())
    assert path.endtype == expected_endtype

def test_gds_path_custom():
    tech_layers = SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds(gds_dir / 'test_path_custom.gds', tech_layers)
    layout = lib['TOP'].layout
    paths = list(layout.all(LayoutPath))
    assert len(paths) == 1
    path = paths[0]
    assert path.layer == tech_layers.Metal1
    assert path.vertices() == [Vec2I(0, 0), Vec2I(0, 500), Vec2I(500, 500)]
    assert path.endtype == PathEndType.Custom
    assert path.ext_bgn == 50
    assert path.ext_end == 100

def test_gds_path_round_unsupported():
    tech_layers = SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds(gds_dir / 'test_path_round.gds', tech_layers)

    with pytest.raises(GdsReaderException, match="GDS Path with path_type=1"):
        layout = lib['TOP'].layout

def test_gds_label():
    tech_layers = SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds(gds_dir / 'test_label.gds', tech_layers)

    layout = lib['TOP'].layout
    label = layout.one(LayoutLabel)

    assert label.pos == Vec2I(2000, 1000)
    assert label.text == "TestLabel"


def test_gds_sref_d4():
    tech_layers = SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds(gds_dir / 'test_sref_d4.gds', tech_layers)

    expected_pos_orientations = {
        (Vec2I(0, 0), R0),
        (Vec2I(6000, 0), R90),
        (Vec2I(9000, 3000), R180),
        (Vec2I(10000, 2000), R270),
        (Vec2I(0, -1000), MX),
        (Vec2I(10000, -3000), MX90),
        (Vec2I(9000, -4000), MY),
        (Vec2I(6000, -1000), MY90),
    }

    layout = lib['TOP'].layout
    for inst in layout.all(LayoutInstance):
        assert inst.ref == lib['SUB'].frame

        pos_orientation = (inst.pos, inst.orientation)
        assert pos_orientation in expected_pos_orientations
        expected_pos_orientations.remove(pos_orientation)
    assert len(expected_pos_orientations) == 0

def test_gds_sref_bad_mag():
    tech_layers = SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds(gds_dir / 'test_sref_bad_mag.gds', tech_layers)

    with pytest.raises(GdsReaderException, match="SRef with magnification"):
        lib['TOP'].layout

def test_gds_sref_bad_angle():
    tech_layers = SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds(gds_dir / 'test_sref_bad_angle.gds', tech_layers)

    with pytest.raises(GdsReaderException, match="SRef with angle"):
        lib['TOP'].layout

def test_gds_sref_nested():
    """
    Test flatten() of nested LayoutInstances (SRefs) through example GDS file.
    """
    tech_layers = SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds(gds_dir / 'test_sref_nested.gds', tech_layers)
    layout = lib['TOP'].layout.thaw()

    assert layout.one(LayoutInstance).ref == lib['SUB1'].frame
    assert lib['SUB1'].frame.one(LayoutInstance).ref == lib['SUB2'].frame

    flatten(layout)
    assert len(list(layout.all(LayoutInstance))) == 0

    poly = layout.one(LayoutPoly)
    assert poly.layer == tech_layers.Metal1
    assert poly.vertices() == [
        Vec2I(3000, 15000),
        Vec2I(3000, 14000),
        Vec2I(4000, 14000),
        Vec2I(4000, 12000),
        Vec2I(5000, 12000),
        Vec2I(5000, 15000),
    ]

def test_gds_aref():
    tech_layers = SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds(gds_dir / 'test_aref.gds', tech_layers)

    layout = lib['TOP'].layout

    sub_poly_vertices = lib['SUB'].layout.one(LayoutPoly).vertices()
    # The polys are reversed in the ARef because ainst.orientation mirrors.
    # origin_idx_reversed is 0 at the moment, but this could change when
    # the GDS poly vertexes are rearranged.
    origin_idx_reversed = len(sub_poly_vertices) - 1 - sub_poly_vertices.index(Vec2I(0, 0))

    ainst = layout.one(LayoutInstanceArray)
    assert ainst.pos == Vec2I(10000, 10000)
    assert ainst.orientation == MX90
    assert ainst.ref == lib['SUB'].frame
    assert ainst.cols == 3
    assert ainst.rows == 2
    assert ainst.vec_col == Vec2I(4000, 0)
    assert ainst.vec_row == Vec2I(2000, 3000)

    pos_expected_orig = {
        Vec2I(10000, 10000),
        Vec2I(12000, 13000),
        Vec2I(14000, 10000),
        Vec2I(16000, 13000),
        Vec2I(18000, 10000),
        Vec2I(20000, 13000),
    }

    # Test correct handling of LayoutInstanceArray by expand_instancearrays():
    layout_expand = layout.thaw()
    expand_instancearrays(layout_expand)

    assert len(list(layout_expand.all(LayoutInstanceArray))) == 0
    pos_expected = pos_expected_orig.copy()
    for inst in layout_expand.all(LayoutInstance):
        assert inst.orientation == ainst.orientation
        assert inst.ref == ainst.ref
        assert inst.pos in pos_expected
        pos_expected.remove(inst.pos)
    assert len(pos_expected) == 0

    # Test correct handling of LayoutInstanceArray by flatten():
    layout_flatten = layout.thaw()
    flatten(layout_flatten)

    assert len(list(layout_flatten.all(LayoutInstanceArray))) == 0
    pos_expected = pos_expected_orig.copy()
    for poly in layout_flatten.all(LayoutPoly):
        pos0 = poly.vertices()[origin_idx_reversed]
        assert pos0 in pos_expected
        pos_expected.remove(pos0)
    assert len(pos_expected) == 0

def test_flatten():
    layers = SG13G2().layers

    sublayout = Layout(ref_layers=layers)
    poly_orig = sublayout % LayoutPoly(
        layer=layers.Metal1,
        vertices=[(0, 0), (100, 0), (100, 100), (0, 100)],
    )
    path_orig = sublayout % LayoutPath(
        layer=layers.Metal2,
        endtype=PathEndType.Square,
        width=150,
        vertices=[(0, 0), (1000, 0), (1000, 1000)],
    )
    rect_orig = sublayout % LayoutRect(
        layer=layers.Metal5,
        rect=(900, 900, 1100, 1100),
    )
    label_orig = sublayout % LayoutLabel(
        layer=layers.Metal1,
        pos=(50, 50),
        text="Hello world!",
    )
    sublayout = sublayout.freeze() 

    pos = Vec2I(500, 3000)
    for orientation in D4:
        tran = pos.transl() * orientation

        layout = Layout(ref_layers=layers)
        layout % LayoutInstance(
            ref=sublayout,
            pos=pos,
            orientation=orientation
        )

        # Layout instance should be gone...
        flatten(layout)
        assert len(list(layout.all(LayoutInstance))) == 0

        # ...and be replaced by the flattened LayoutPoly...
        poly = layout.one(LayoutPoly)
        assert poly.layer == poly_orig.layer
        expected_vertices = [tran * v for v in poly_orig.vertices()]
        if orientation.det() < 0:
            expected_vertices.reverse()
        assert poly.vertices() == expected_vertices

        # ...and the flattened LayoutPath...
        path = layout.one(LayoutPath)
        assert path.layer == path_orig.layer
        assert path.endtype == path_orig.endtype
        assert path.width == path_orig.width
        assert path.vertices() == [tran * v for v in path_orig.vertices()]

        # ...and the flattened LayoutRect...
        rect = layout.one(LayoutRect)
        assert rect.layer == rect_orig.layer
        assert rect.rect == tran * rect_orig.rect

        # ...and the flattened LayoutLabe;!
        label = layout.one(LayoutLabel)
        assert label.layer == label_orig.layer
        assert label.pos == tran * label_orig.pos
        assert label.text == label_orig.text

def test_expand_paths_lshapes():
    """
    Tests expand_paths with PathEndType.Square and PathEndType.Flush
    for L shapes with different orientations.
    """
    
    layers = SG13G2().layers
    for x in 1, -1:
        for y in 1, -1:        
            l_flush = Layout(ref_layers=layers)
            l_flush % LayoutPath(
                width=100,
                endtype=PathEndType.Flush,
                layer=layers.Metal1,
                vertices=[
                    Vec2I(x*500, 0),
                    Vec2I(0, 0),
                    Vec2I(0, y*500),
                ],
            )

            l_square = l_flush.copy()
            l_square.one(LayoutPath).endtype = PathEndType.Square

            # Test path to poly with PathEndType.Flush:
            expand_paths(l_flush)

            assert len(list(l_flush.all(LayoutPath))) == 0

            polys = list(l_flush.all(LayoutPoly))
            assert len(polys) == 1
            poly = polys[0]

            assert poly.layer == layers.Metal1
            assert poly.vertices() == [
                Vec2I(-y*50, y*500),
                Vec2I(-y*50, -x*50),
                Vec2I(x*500, -x*50),
                Vec2I(x*500, x*50),
                Vec2I(y*50, x*50),
                Vec2I(y*50, y*500),
            ]
            assert poly_orientation(poly.vertices()) == 'ccw'

            # Test path to poly with PathEndType.Square:
            expand_paths(l_square)

            polys = list(l_square.all(LayoutPoly))
            assert len(polys) == 1
            poly = polys[0]
            assert poly.vertices() == [
                Vec2I(-y*50, y*550),
                Vec2I(-y*50, -x*50),
                Vec2I(x*550, -x*50),
                Vec2I(x*550, x*50),
                Vec2I(y*50, x*50),
                Vec2I(y*50, y*550),
            ]

def test_expand_paths_custom():
    """Tests expand_paths with PathEndType.Custom."""
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)
    l % LayoutPath(
        width=100,
        endtype=PathEndType.Custom,
        ext_bgn=30,
        ext_end=70,
        layer=layers.Metal1,
        vertices=[Vec2I(0, 0), Vec2I(500, 0)],
    )
    expand_paths(l)
    poly = l.one(LayoutPoly)
    assert poly.vertices() == [
        Vec2I(570, 50),
        Vec2I(-30, 50),
        Vec2I(-30, -50),
        Vec2I(570, -50),
    ]

def test_path_infer_custom_endtype():
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)
    p = l % LayoutPath(width=100, ext_bgn=30, ext_end=70, layer=layers.Metal1,
        vertices=[Vec2I(0, 0), Vec2I(500, 0)])
    assert p.endtype == PathEndType.Custom

    with pytest.raises(ValueError, match="PathEndType must be Custom"):
        l % LayoutPath(width=100, ext_bgn=30, ext_end=70, layer=layers.Metal1,
            endtype=PathEndType.Square,
            vertices=[Vec2I(0, 0), Vec2I(500, 0)])

def test_layoutpoly_vertex_count():
    """Test GenericPoly.__new__ with an integer vertex count.

    LayoutPoly(n, ...) creates the polygon node plus n empty PolyVec2I
    nodes (no pos set), whose positions can then be set via constraints.
    """
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)
    l.poly = LayoutPoly(3, layer=layers.Metal1)

    # Three PolyVec2I nodes should exist with correct order and no pos:
    verts = list(l.all(PolyVec2I))
    assert len(verts) == 3
    assert all(isinstance(v.pos, Vec2LinearTerm) for v in verts)

def test_expand_paths_complex():
    layers = SG13G2().layers
    
    l = Layout(ref_layers=layers)
    l.path = LayoutPath(
        width=100,
        endtype=PathEndType.Flush,
        layer=layers.Metal3,
        vertices=[
            Vec2I(0, 0),
            Vec2I(0, 1000),
            Vec2I(1000, 1000),
            Vec2I(1000, 0),
            Vec2I(800, 0),
            Vec2I(800, 800),
            Vec2I(200, 800),
            Vec2I(200, 0),
        ],
    )

    expand_paths(l)

    assert isinstance(l.path, LayoutPoly)
    assert l.path.vertices() ==[
        Vec2I(250, 0),
        Vec2I(250, 750),
        Vec2I(750, 750),
        Vec2I(750, -50),
        Vec2I(1050, -50),
        Vec2I(1050, 1050),
        Vec2I(-50, 1050),
        Vec2I(-50, 0),
        Vec2I(50, 0),
        Vec2I(50, 950),
        Vec2I(950, 950),
        Vec2I(950, 50),
        Vec2I(850, 50),
        Vec2I(850, 850),
        Vec2I(150, 850),
        Vec2I(150, 0),
    ]

def test_expand_paths_straight_segment():
    """
    Tests whether expand_paths correctly drops unneeded vertices
    on two straight segments (0 degree turns).
    """

    layers = SG13G2().layers

    l = Layout(ref_layers=layers)
    l.path = LayoutPath(
        width=100,
        endtype=PathEndType.Flush,
        layer=layers.Metal1,
        vertices=[
            Vec2I(0, 0),
            Vec2I(0, 500),
            Vec2I(0, 1000),
        ],
    )

    expand_paths(l)

    assert isinstance(l.path, LayoutPoly)
    assert l.path.vertices() == [
        Vec2I(-50, 1000),
        Vec2I(-50, 0),
        Vec2I(50, 0),
        Vec2I(50, 1000),
    ]

def test_expand_paths_invalid():
    layers = SG13G2().layers

    invalid_paths = [
        [ # too few vertices in path
            Vec2I(123, 456),
        ],
        [ # single, non-rectilinear segment
            Vec2I(0, 0),
            Vec2I(500, 500),
        ],
        [ # 180 degree turn
            Vec2I(0, 0),
            Vec2I(100, 0),
            Vec2I(0, 0),
        ],
        [ # 45 degree turn
            Vec2I(0, 0),
            Vec2I(0, 1000),
            Vec2I(500, 1500),
            Vec2I(1500, 1500),
        ]
    ]

    for vertices in invalid_paths:
        l = Layout(ref_layers=layers)
        l % LayoutPath(
            width=100,
            endtype=PathEndType.Flush,
            layer=layers.Metal1,
            vertices=vertices,
        )

        with pytest.raises(ValueError):
            expand_paths(l)

def test_expand_rect():
    layers = SG13G2().layers

    l = Layout(ref_layers=layers)
    l.rect = LayoutRect(
        layer=layers.Metal1,
        rect=Rect4I(100, 500, 200, 700),
    )
    expand_rects(l)
    assert len(list(l.all(LayoutRect))) == 0

    assert isinstance(l.rect, LayoutPoly)
    assert l.rect.layer == layers.Metal1
    assert l.rect.vertices() == [
        Vec2I(100, 500),
        Vec2I(200, 500),
        Vec2I(200, 700),
        Vec2I(100, 700),
    ]

def test_write_gds():
    layers = SG13G2().layers

    class Sub(Cell):
        @generate
        def layout(self) -> Layout:
            l = Layout(ref_layers=layers, cell=self)
            l % LayoutPoly(layer=layers.Metal2.pin, vertices=[
                (200, 0), (200, 200), (100, 200), (100, 100), (0, 100), (0, 0)])
            return l

    class Sub2(Cell):
        @generate
        def layout(self) -> Layout:
            l = Layout(ref_layers=layers, cell=self)
            l % LayoutPoly(layer=layers.Metal2.pin, vertices=[
                (100, 0), (100, 100), (200, 100), (200, 200), (0, 200), (0, 0)])
            return l

    class Top(Cell):
        @generate
        def layout(self) -> Layout:
            l = Layout(ref_layers=layers, cell=self)
            l % LayoutRect(layer=layers.Metal1.pin, rect=(100, 200, 300, 400))
            l % LayoutLabel(layer=layers.Metal1.pin, pos=(200, 300), text="My Label")
            l % LayoutPath(
                layer=layers.GatPoly,
                vertices=[(0, 0), (500, 0), (500, 500), (500, 1200)],
                width=100,
                endtype=PathEndType.Square,
            )
            l % LayoutInstance(pos=(-100, -100), orientation=MY, ref=Sub().layout)
            l % LayoutInstance(pos=(-400, -400), orientation=R0, ref=Sub().layout)

            l % LayoutInstanceArray(
                pos=(0, 2000),
                orientation=R0,
                ref=Sub2().layout,
                cols=4,
                rows=2,
                vec_col=(250, 0),
                vec_row=(0, 300),
                )
            return l

    # To generate reference file:           
    #with open("out.gds", "wb") as f:
    #    write_gds(Top().layout, f)

    assert gds_text_from_layout(Top().layout) == gds_text_from_file(gds_dir / 'test_write_gds.gds')

def test_write_gds_without_cell():
    layers = SG13G2().layers

    l = Layout(ref_layers=layers)
    l % LayoutPoly(layer=layers.Metal2.pin, vertices=[
        (200, 0), (200, 200), (100, 200), (100, 100), (0, 100), (0, 0)])
    l = l.freeze()

    reference = gds_text_from_file(gds_dir / 'test_write_gds_without_cell.gds')
    reference = re.sub(r"\'__subgraph[0-9a-f]+\'", f"'__subgraph{id(l.subgraph):x}'", reference)

    assert gds_text_from_layout(l) == reference

def test_write_gds_layers_mismatch():
    layers = SG13G2().layers
    layers_other = LayerStack(unit=R('1n')).freeze()

    sub = Layout(ref_layers=layers)
    sub = sub.freeze()

    top = Layout(ref_layers=layers_other)
    top % LayoutInstance(pos=(0, 0), ref=sub)
    top = top.freeze()

    with pytest.raises(ValueError, match="ref_layers mismatch during write_gds"):
        gds_text_from_layout(top)

def test_layoutinstance_subcursor():
    layers = SG13G2().layers

    layout1 = Layout(ref_layers=layers)
    layout1.myrect = LayoutRect(
        layer=layers.Metal1,
        rect=Rect4I(100, 500, 200, 700),
    )
    layout1 = layout1.freeze()

    layout2 = Layout(ref_layers=layers)
    layout2.layout1_inst = LayoutInstance(pos=(1000, 2000), orientation=R90, ref=layout1)
    layout2 = layout2.freeze()

    assert layout2.layout1_inst.myrect.parent == layout2.layout1_inst.subcursor()
    assert layout2.layout1_inst.myrect.rect == layout2.layout1_inst.loc_transform() * layout1.myrect.rect
    assert layout2.layout1_inst.subcursor().parent == layout2.layout1_inst

    layout3 = Layout(ref_layers=layers) 
    layout3.layout2_inst = LayoutInstance(pos=(50, 50), orientation=MX, ref=layout2)
    layout3 = layout3.freeze()

    assert layout3.layout2_inst.layout1_inst.myrect.rect == \
        layout3.layout2_inst.loc_transform() * \
        layout2.layout1_inst.loc_transform() * layout1.myrect.rect

def test_layoutinstancearray_subcursor():
    """
    Tests the handling of LayoutInstanceArrays by LayoutInstanceSubcursor.
    """
    layers = SG13G2().layers

    layout1 = Layout(ref_layers=layers)
    layout1.myrect = LayoutRect(
        layer=layers.Metal1,
        rect=Rect4I(100, 500, 200, 700),
    )
    layout1 = layout1.freeze()

    
    layout2 = Layout(ref_layers=layers)
    # I1 has columns AND rows:
    layout2.I1 = LayoutInstanceArray(
        pos=(1000, 2000), orientation=R90, ref=layout1,
        cols=5, rows=7, vec_col=Vec2I(900, 0), vec_row=Vec2I(0, 900))
    # I2 has only columns:
    layout2.I2 = LayoutInstanceArray(
        pos=(1000, 2000), orientation=R90, ref=layout1,
        cols=5, vec_col=Vec2I(900, 0))
    # I3 has only rows:
    layout2.I3 = LayoutInstanceArray(
        pos=(1000, 2000), orientation=R90, ref=layout1,
        rows=7, vec_row=Vec2I(0, 900))
    layout2 = layout2.freeze()

    # Test I1:

    with pytest.raises(AttributeError, match=r"Missing index \[\] for LayoutInstanceArray"):
        layout2.I1.myrect.rect
    with pytest.raises(IndexError):
        layout2.I1[0, -8]
    with pytest.raises(IndexError):
        layout2.I1[6, 0]
    with pytest.raises(IndexError):
        layout2.I1[2]

    assert layout2.I1[0,0].myrect.rect == \
        layout2.I1.loc_transform() * layout1.myrect.rect
    assert layout2.I1[1,0].myrect.rect == \
        layout2.I1.vec_col.transl() * layout2.I1[0,0].myrect.rect
    assert layout2.I1[0,2].myrect.rect == \
        (layout2.I1.vec_row*2).transl() * layout2.I1[0,0].myrect.rect
    assert layout2.I1[4, 2].myrect.rect == \
        (layout2.I1.vec_col*4).transl() * (layout2.I1.vec_row*2).transl() * \
        layout2.I1[0,0].myrect.rect
    # Check negative-index logic:
    assert layout2.I1[4, 6].myrect.rect == layout2.I1[-1, -1].myrect.rect

    # Test I2:

    with pytest.raises(IndexError):
        layout2.I2[6]
    with pytest.raises(IndexError):
        layout2.I2[0, 0]

    assert layout2.I2[0].myrect.rect == \
        layout2.I2.loc_transform() * layout1.myrect.rect
    assert layout2.I2[2].myrect.rect == \
        (layout2.I1.vec_col * 2).transl() * layout2.I2[0].myrect.rect

    # Test I3:

    with pytest.raises(IndexError):
        layout2.I3[11]
    with pytest.raises(IndexError):
        layout2.I3[0, 0]

    assert layout2.I3[0].myrect.rect == \
        layout2.I3.loc_transform() * layout1.myrect.rect
    assert layout2.I3[6].myrect.rect == \
        (layout2.I3.vec_row * 6).transl() * layout2.I3[0].myrect.rect

def test_expand_pins():
    sym = Symbol()
    sym.my_pin = Pin()
    sym.my = PathNode()
    sym.my.pin = Pin()
    sym = sym.freeze()

    layers = SG13G2().layers

    layout = Layout(ref_layers=layers, symbol=sym)

    r1 = layout % LayoutRect(layer=layers.Metal1, rect=(0,0,100,100))
    r1.create_pin(sym.my_pin)

    r2 = layout % LayoutRect(layer=layers.Metal1, rect=(200,0,300,100))
    r2.create_pin(sym.my.pin)

    expand_rects(layout)
    expand_pins(layout, Directory())

    labels = []
    for lbl in layout.all(LayoutLabel):
        labels.append((lbl.pos, lbl.text))

    labels.sort()
    assert labels == [(Vec2I(50, 50), "my_pin"), (Vec2I(250, 50), "my_pin0")]


def test_compare_identical_different_order():
    """compare() returns None for identical geometry with different vertex/NID ordering."""
    layers = SG13G2().layers

    a = Layout(ref_layers=layers)
    a % LayoutRect(layer=layers.Metal1, rect=(0, 0, 100, 200))
    a % LayoutPoly(layer=layers.Metal2, vertices=[
        Vec2I(0, 0), Vec2I(300, 0), Vec2I(300, 300), Vec2I(0, 300)])
    a % LayoutLabel(layer=layers.Metal1, pos=(50, 100), text="A")

    b = Layout(ref_layers=layers)
    # Reversed insertion order
    b % LayoutLabel(layer=layers.Metal1, pos=(50, 100), text="A")
    # Polygon with rotated vertex list (same shape)
    b % LayoutPoly(layer=layers.Metal2, vertices=[
        Vec2I(300, 300), Vec2I(0, 300), Vec2I(0, 0), Vec2I(300, 0)])
    b % LayoutRect(layer=layers.Metal1, rect=(0, 0, 100, 200))

    assert compare(a, b) is None

def test_compare_different_vertices():
    """compare() detects a rectangle with slightly different vertices."""
    layers = SG13G2().layers

    a = Layout(ref_layers=layers)
    a % LayoutRect(layer=layers.Metal1, rect=(0, 0, 100, 200))

    b = Layout(ref_layers=layers)
    b % LayoutRect(layer=layers.Metal1, rect=(0, 0, 101, 200))

    result = compare(a, b)
    assert result is not None
    assert "Polygon mismatch" in result

def test_compare_fewer_objects():
    """compare() detects when layout_b has fewer geometric objects."""
    layers = SG13G2().layers

    a = Layout(ref_layers=layers)
    a % LayoutRect(layer=layers.Metal1, rect=(0, 0, 100, 200))
    a % LayoutRect(layer=layers.Metal2, rect=(50, 50, 150, 250))

    b = Layout(ref_layers=layers)
    b % LayoutRect(layer=layers.Metal1, rect=(0, 0, 100, 200))

    result = compare(a, b)
    assert result is not None
    assert "Only in layout_a" in result

def test_compare_extra_object():
    """compare() detects when layout_b has an additional geometric object."""
    layers = SG13G2().layers

    a = Layout(ref_layers=layers)
    a % LayoutRect(layer=layers.Metal1, rect=(0, 0, 100, 200))

    b = Layout(ref_layers=layers)
    b % LayoutRect(layer=layers.Metal1, rect=(0, 0, 100, 200))
    b % LayoutRect(layer=layers.Metal2, rect=(50, 50, 150, 250))

    result = compare(a, b)
    assert result is not None
    assert "Only in layout_b" in result

def test_compare_label_mismatch():
    """compare() detects differing labels."""
    layers = SG13G2().layers

    a = Layout(ref_layers=layers)
    a % LayoutLabel(layer=layers.Metal1, pos=(50, 100), text="A")

    b = Layout(ref_layers=layers)
    b % LayoutLabel(layer=layers.Metal1, pos=(50, 100), text="B")

    result = compare(a, b)
    assert result is not None
    assert "Label mismatch" in result

def test_compare_pin_mismatch():
    """compare() detects differing LayoutPin nodes."""
    sym = Symbol()
    sym.pin_a = Pin()
    sym.pin_b = Pin()
    sym = sym.freeze()

    layers = SG13G2().layers

    a = Layout(ref_layers=layers, symbol=sym)
    r1 = a % LayoutRect(layer=layers.Metal1, rect=(0, 0, 100, 100))
    r1.create_pin(sym.pin_a)

    b = Layout(ref_layers=layers, symbol=sym)
    r2 = b % LayoutRect(layer=layers.Metal1, rect=(0, 0, 100, 100))
    r2.create_pin(sym.pin_b)

    result = compare(a, b)
    assert result is not None
    assert "Pin mismatch" in result


def test_expand_pins_rect():
    """expand_pins places label at center for a simple rectangle."""
    sym = Symbol()
    sym.my_pin = Pin()
    sym = sym.freeze()

    layers = SG13G2().layers
    layout = Layout(ref_layers=layers, symbol=sym)

    r = layout % LayoutRect(layer=layers.Metal1, rect=(0, 0, 100, 100))
    r.create_pin(sym.my_pin)

    expand_rects(layout)
    expand_pins(layout, Directory())

    lbl = list(layout.all(LayoutLabel))[0]
    assert lbl.pos == Vec2I(50, 50)


def test_expand_pins_concave_L():
    """expand_pins places label inside an L-shaped concave polygon."""
    sym = Symbol()
    sym.my_pin = Pin()
    sym = sym.freeze()

    layers = SG13G2().layers
    layout = Layout(ref_layers=layers, symbol=sym)

    # L-shape (CCW): centroid (100, 133) falls outside in the notch
    verts = [
        Vec2I(0, 0), Vec2I(200, 0), Vec2I(200, 100),
        Vec2I(100, 100), Vec2I(100, 300), Vec2I(0, 300),
    ]
    poly = layout % LayoutPoly(layer=layers.Metal1, vertices=verts)
    poly.create_pin(sym.my_pin)

    expand_pins(layout, Directory())

    lbl = list(layout.all(LayoutLabel))[0]
    assert lbl.pos == Vec2I(50, 133)


def test_expand_pins_concave_U():
    """expand_pins places label inside a U-shaped concave polygon."""
    sym = Symbol()
    sym.my_pin = Pin()
    sym = sym.freeze()

    layers = SG13G2().layers
    layout = Layout(ref_layers=layers, symbol=sym)

    # U-shape (CCW): centroid (150, 175) falls outside in the notch
    verts = [
        Vec2I(0, 0), Vec2I(300, 0), Vec2I(300, 300), Vec2I(200, 300),
        Vec2I(200, 100), Vec2I(100, 100), Vec2I(100, 300), Vec2I(0, 300),
    ]
    poly = layout % LayoutPoly(layer=layers.Metal1, vertices=verts)
    poly.create_pin(sym.my_pin)

    expand_pins(layout, Directory())

    lbl = list(layout.all(LayoutLabel))[0]
    assert lbl.pos == Vec2I(50, 175)


def test_create_pin_method():
    """create_pin() method creates LayoutPin with correct ref."""
    sym = Symbol()
    sym.my_pin = Pin()
    sym = sym.freeze()

    layers = SG13G2().layers
    layout = Layout(ref_layers=layers, symbol=sym)

    r = layout % LayoutRect(layer=layers.Metal1, rect=(0, 0, 100, 100))
    pin_cursor = r.create_pin(sym.my_pin)

    assert isinstance(pin_cursor, LayoutPin.Mutable)
    assert pin_cursor.ref.nid == r.nid
    assert pin_cursor.pin.nid == sym.my_pin.nid
