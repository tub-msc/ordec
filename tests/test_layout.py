# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
import importlib.resources
import pytest

import ordec.layout
from ordec.layout.helpers import paths_to_poly
from ordec.core import *

# def test_read_gds():
#     ihp_path = Path(os.getenv("ORDEC_PDK_IHP_SG13G2"))
#     gds_fn = ihp_path / "libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds"
#     x = ordec.layout.read_gds(gds_fn, ordec.layout.SG13G2().layers, 'sg13g2_xor2_1')
#     print(x)

gds_dir = importlib.resources.files("tests.layout_gds")

def test_gds_polygon():
    gds_fn = gds_dir / 'test_polygon.gds'
    tech_layers = ordec.layout.SG13G2().layers
    layout = ordec.layout.read_gds(gds_fn, tech_layers, 'TOP')['TOP']
    #print(layout.tables())
    polys = list(layout.all(LayoutPoly))
    assert len(polys) == 1
    poly = polys[0]
    assert poly.layer == tech_layers.Metal1
    vertices = [v.pos for v in poly.vertices]
    # L-shaped polygon:
    # ┌┐
    # │└┐
    # └─┘
    assert vertices == [
        Vec2I(320, 0),
        Vec2I(320, 160),
        Vec2I(160, 160),
        Vec2I(160, 320),
        Vec2I(0, 320),
        Vec2I(0, 0),
    ]

@pytest.mark.parametrize("endtype", ['flush', 'square'])
def test_gds_path(endtype):
    gds_fn = gds_dir / f'test_path_{endtype}.gds'
    tech_layers = ordec.layout.SG13G2().layers
    layout = ordec.layout.read_gds(gds_fn, tech_layers, 'TOP')['TOP']
    #print(layout.tables())
    paths = list(layout.all(LayoutPath))
    assert len(paths) == 1
    path = paths[0]
    assert path.layer == tech_layers.Metal1
    vertices = [v.pos for v in path.vertices]
    assert vertices == [
        Vec2I(0, 0),
        Vec2I(0, 500),
        Vec2I(500, 500),
    ]
    expected_endtype = getattr(PathEndType, endtype.upper())
    assert path.endtype == expected_endtype

def test_gds_path_round_unsupported():
    gds_fn = gds_dir / f'test_path_round.gds'
    tech_layers = ordec.layout.SG13G2().layers
    with pytest.raises(ordec.layout.GdsReaderException, match="GDS Path with path_type=1"):
        ordec.layout.read_gds(gds_fn, tech_layers, 'TOP')['TOP']

def test_paths_to_poly_lshapes():
    """
    Tests paths_to_poly with PathEndType.SQUARE and PathEndType.FLUSH
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
            paths_to_poly(l_flush)

            assert len(list(l_flush.all(LayoutPath))) == 0

            polys = list(l_flush.all(LayoutPoly))
            assert len(polys) == 1
            poly = polys[0]

            assert poly.layer == layers.Metal1

            vertices = [v.pos for v in poly.vertices]

            assert vertices == [
                Vec2I(x*500, x*50),
                Vec2I(y*50, x*50),
                Vec2I(y*50, y*500),
                Vec2I(-y*50, y*500),
                Vec2I(-y*50, -x*50),
                Vec2I(x*500, -x*50),
            ]

            # Test path to poly with PathEndType.SQUARE:
            paths_to_poly(l_square)

            polys = list(l_square.all(LayoutPoly))
            assert len(polys) == 1
            poly = polys[0]
            vertices = [v.pos for v in poly.vertices]

            assert vertices == [
                Vec2I(x*550, x*50),
                Vec2I(y*50, x*50),
                Vec2I(y*50, y*550),
                Vec2I(-y*50, y*550),
                Vec2I(-y*50, -x*50),
                Vec2I(x*550, -x*50),
            ]

def test_paths_to_poly_straight_segment():
    """
    Tests whether paths_to_poly correctly drops unneeded vertices
    on two straight segments (0 degree turns).
    """

    layers = ordec.layout.SG13G2().layers

    l = Layout(ref_layers=layers)
    l % LayoutPath(
        width=100,
        endtype=PathEndType.FLUSH,
        layer=layers.Metal1,
        vertices=[
            Vec2I(0, 0),
            Vec2I(0, 500),
            Vec2I(0, 1000),
        ],
    )

    paths_to_poly(l)

    polys = list(l.all(LayoutPoly))
    assert len(polys) == 1
    poly = polys[0]
    vertices = [v.pos for v in poly.vertices]
    assert vertices == [
        Vec2I(50, 0),
        Vec2I(50, 1000),
        Vec2I(-50, 1000),
        Vec2I(-50, 0),
    ]

def test_paths_to_poly_invalid():
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
            paths_to_poly(l)
