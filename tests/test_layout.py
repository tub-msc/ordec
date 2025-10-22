# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
import importlib.resources
import pytest

import ordec.layout
from ordec.layout.read_gds import GdsReaderException
from ordec.layout.helpers import poly_orientation, expand_paths, expand_rects
from ordec.core import *
from ordec.extlibrary import ExtLibrary, ExtLibraryError

# def test_read_gds():
#     ihp_path = Path(os.getenv("ORDEC_PDK_IHP_SG13G2"))
#     gds_fn = ihp_path / "libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds"
#     x = ordec.layout.read_gds(gds_fn, ordec.layout.SG13G2().layers, 'sg13g2_xor2_1')
#     print(x)

gds_dir = importlib.resources.files("tests.layout_gds")

def test_extlibrary():
    # This test is very bare-bones at the moment.

    lib = ExtLibrary()
    tech_layers = ordec.layout.SG13G2().layers
    lib.read_gds(gds_dir / 'test_polygon.gds', tech_layers)
    
    lib['TOP'].layout

    with pytest.raises(ExtLibraryError, match="No layout source found for cell"):
        lib['undefined'].layout

    with pytest.raises(ExtLibraryError, match="Multiple layout sources found for cell"):
        lib.read_gds(gds_dir / 'test_polygon.gds', tech_layers)

def test_gds_polygon():
    tech_layers = ordec.layout.SG13G2().layers
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
    tech_layers = ordec.layout.SG13G2().layers
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
    expected_endtype = getattr(PathEndType, endtype.upper())
    assert path.endtype == expected_endtype

def test_gds_path_round_unsupported():
    tech_layers = ordec.layout.SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds(gds_dir / f'test_path_round.gds', tech_layers)

    with pytest.raises(GdsReaderException, match="GDS Path with path_type=1"):
        layout = lib['TOP'].layout

def test_expand_paths_lshapes():
    """
    Tests expand_paths with PathEndType.SQUARE and PathEndType.FLUSH
    for L shapes with different orientations.
    """
    
    layers = ordec.layout.SG13G2().layers
    for x in 1, -1:
        for y in 1, -1:        
            l_flush = Layout(ref_layers=layers)
            l_flush % LayoutPath(
                width=100,
                endtype=PathEndType.FLUSH,
                layer=layers.Metal1,
                vertices=[
                    Vec2I(x*500, 0),
                    Vec2I(0, 0),
                    Vec2I(0, y*500),
                ],
            )

            l_square = l_flush.copy()
            l_square.one(LayoutPath).endtype = PathEndType.SQUARE

            # Test path to poly with PathEndType.FLUSH:
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

            # Test path to poly with PathEndType.SQUARE:
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

def test_expand_paths_complex():
    layers = ordec.layout.SG13G2().layers
    
    l = Layout(ref_layers=layers)
    l.path = LayoutPath(
        width=100,
        endtype=PathEndType.FLUSH,
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

    layers = ordec.layout.SG13G2().layers

    l = Layout(ref_layers=layers)
    l.path = LayoutPath(
        width=100,
        endtype=PathEndType.FLUSH,
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
    layers = ordec.layout.SG13G2().layers

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
            endtype=PathEndType.FLUSH,
            layer=layers.Metal1,
            vertices=vertices,
        )

        with pytest.raises(ValueError):
            expand_paths(l)

def test_expand_rectpoly():
    layers = ordec.layout.SG13G2().layers

    l = Layout(ref_layers=layers)
    l.rpoly_h = LayoutRectPoly(
        layer=layers.Metal1,
        vertices = [
            Vec2I(0, 0),
            Vec2I(100, 100),
            Vec2I(50, 50),
        ],
        start_direction=RectDirection.HORIZONTAL,
    )
    l.rpoly_v = LayoutRectPoly(
        layer=layers.Metal1,
        vertices = [
            Vec2I(0, 0),
            Vec2I(-100, 100),
            Vec2I(-50, 50),
        ],
        start_direction=RectDirection.VERTICAL,
    )

    expand_rects(l)

    assert len(list(l.all(LayoutRectPoly))) == 0
    assert isinstance(l.rpoly_h, LayoutPoly)
    assert l.rpoly_h.vertices() == [
        Vec2I(100, 0),
        Vec2I(100, 100),
        Vec2I(50, 100),
        Vec2I(50, 50),
        Vec2I(0, 50),
        Vec2I(0, 0),
    ]
    assert isinstance(l.rpoly_v, LayoutPoly)
    assert l.rpoly_v.vertices() == [
        Vec2I(0, 100),
        Vec2I(-100, 100),
        Vec2I(-100, 50),
        Vec2I(-50, 50),
        Vec2I(-50, 0),
        Vec2I(0, 0),
    ]

def test_expand_rectpath():
    layers = ordec.layout.SG13G2().layers

    l = Layout(ref_layers=layers)
    l.rpath_h = LayoutRectPath(
        layer=layers.Metal1,
        vertices = [
            Vec2I(0, 0),
            Vec2I(100, 100),
            Vec2I(50, 50),
        ],
        width=10,
        endtype=PathEndType.SQUARE,
        start_direction=RectDirection.HORIZONTAL,
    )
    l.rpath_h2 = LayoutRectPath(
        layer=layers.Metal1,
        vertices = [
            Vec2I(0, 0),
            Vec2I(100, 100),
            Vec2I(100, 50),
        ],
        width=10,
        endtype=PathEndType.SQUARE,
        start_direction=RectDirection.HORIZONTAL,
    )
    l.rpath_h3 = LayoutRectPath(
        layer=layers.Metal1,
        vertices = [
            Vec2I(0, 0),
            Vec2I(100, 100),
            Vec2I(50, 100),
        ],
        width=10,
        endtype=PathEndType.SQUARE,
        start_direction=RectDirection.HORIZONTAL,
    )
    l.rpath_v = LayoutRectPath(
        layer=layers.Metal1,
        vertices = [
            Vec2I(0, 0),
            Vec2I(100, 100),
            Vec2I(50, 50),
        ],
        width=10,
        endtype=PathEndType.SQUARE,
        start_direction=RectDirection.VERTICAL,
    )

    expand_rects(l)
    assert len(list(l.all(LayoutRectPath))) == 0
    assert isinstance(l.rpath_h, LayoutPath)
    assert l.rpath_h.vertices() == [
        Vec2I(0, 0),
        Vec2I(100, 0),
        Vec2I(100, 100),
        Vec2I(50, 100),
        Vec2I(50, 50),
    ]
    assert l.rpath_h.width == 10
    assert l.rpath_h.endtype == PathEndType.SQUARE

    assert isinstance(l.rpath_h2, LayoutPath)
    assert l.rpath_h2.vertices() == [
        Vec2I(0, 0),
        Vec2I(100, 0),
        Vec2I(100, 100),
        Vec2I(100, 50),
    ]

    assert isinstance(l.rpath_h3, LayoutPath)
    assert l.rpath_h3.vertices() == [
        Vec2I(0, 0),
        Vec2I(100, 0),
        Vec2I(100, 100),
        Vec2I(50, 100),
    ]

    assert isinstance(l.rpath_v, LayoutPath)
    assert l.rpath_v.vertices() == [
        Vec2I(0, 0),
        Vec2I(0, 100),
        Vec2I(100, 100),
        Vec2I(100, 50),
        Vec2I(50, 50),
    ]


