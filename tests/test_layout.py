# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
import importlib.resources
import pytest

import ordec.layout
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
