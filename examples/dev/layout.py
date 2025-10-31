import os
from pathlib import Path

import ordec.layout.ihp130 as ihp130
from ordec.extlibrary import ExtLibrary
from ordec.layout.helpers import expand_geom, flatten, expand_instancearrays
from ordec.layout.makevias import makevias
from ordec.core import *

ihp_path = Path(os.getenv("ORDEC_PDK_IHP_SG13G2"))

@generate_func
def layout_xor() -> Layout:
    tech_layers = ordec.layout.SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds(ihp_path / "libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds", tech_layers)
    return lib['sg13g2_xor2_1'].layout

@generate_func
def layout_dff() -> Layout:
    tech_layers = ordec.layout.SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds(ihp_path / "libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds", tech_layers)
    return lib['sg13g2_sdfrbpq_2'].layout

@generate_func
def layout_ota() -> Layout:
    gds_fn = "../ordec2/example_layouts/OTA_flat.gds"
    top = "OTA"
    layouts = ordec.layout.read_gds(gds_fn, ordec.layout.SG13G2().layers, top)
    return layouts[top]

@generate_func
def layout_expand_geom() -> Layout:
    layers = ihp130.SG13G2().layers
    
    l = Layout(ref_layers=layers)
    for x in (1, -1):
        for y in (1, -1):
            l % LayoutPath(
                width=100,
                endtype=PathEndType.FLUSH,
                layer=layers.Metal1,
                vertices=[
                    Vec2I(x*100, y*500),
                    Vec2I(x*500, y*500),
                    Vec2I(x*500, y*100),
                ],
            )

            l % LayoutPath(
                width=50,
                endtype=PathEndType.SQUARE,
                layer=layers.Metal2,
                vertices=[
                    Vec2I(x*500, y*100),
                    Vec2I(x*500, y*500),
                    Vec2I(x*100, y*500),
                ],
            )

    l % LayoutPath(
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
            Vec2I(200, -200),
            Vec2I(1200, -200),
            Vec2I(1200, 1200),
            Vec2I(-200, 1200),
            Vec2I(-200, 0)
        ],
    )

    l % LayoutRectPoly(
        layer=layers.Metal4,
        vertices = [
            Vec2I(0,0),
            Vec2I(100,100),
            Vec2I(50,50),
            Vec2I(-100, 25),
        ],
    )

    l % LayoutRectPath(
        width=80,
        endtype=PathEndType.SQUARE,
        layer=layers.Metal5,
        vertices = [
            Vec2I(0,0),
            Vec2I(1400,1400),
            Vec2I(-400,600),
            Vec2I(100,100),
        ],
        start_direction=RectDirection.HORIZONTAL,
    )

    return l

@generate_func
def test_gds_sref() -> Layout:
    tech_layers = ihp130.SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds('tests/layout_gds/test_sref_d4.gds', tech_layers)
    return lib['TOP'].layout

@generate_func
def test_gds_aref() -> Layout:
    tech_layers = ihp130.SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds('tests/layout_gds/test_aref.gds', tech_layers)
    return lib['TOP'].layout

@generate_func
def test_ihp130_nmos() -> Layout:
    return ihp130.Nmos(l="300n", w="200000n", ng=20).layout.thaw()

@generate_func
def test_makevias() -> Layout:
    layers = ihp130.SG13G2().layers
    
    l = Layout(ref_layers=layers)
    a = l % LayoutRect(layer=layers.Metal1, rect=Rect4I(0, 0, 205, 800))
    b = l % LayoutRect(layer=layers.Metal2, rect=Rect4I(0, 0, 500, 800))

    makevias(l, a.rect, layers.Via1, Vec2I(80, 80), Vec2I(50, 50), Vec2I(0,0))

    return l
