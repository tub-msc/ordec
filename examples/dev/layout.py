import os
from pathlib import Path
import ordec.layout
from ordec.extlibrary import ExtLibrary
from ordec.layout.helpers import expand_geom, flatten, expand_instancearrays
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
    layers = ordec.layout.SG13G2().layers
    
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

    expand_geom(l)

    return l

@generate_func
def test_gds_sref() -> Layout:
    tech_layers = ordec.layout.SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds('tests/layout_gds/test_sref_d4.gds', tech_layers)
    l = lib['TOP'].layout.thaw()
    flatten(l)
    return l

@generate_func
def test_gds_aref() -> Layout:
    tech_layers = ordec.layout.SG13G2().layers
    lib = ExtLibrary()
    lib.read_gds('tests/layout_gds/test_aref.gds', tech_layers)
    l = lib['TOP'].layout.thaw()
    expand_instancearrays(l)
    flatten(l)
    #print(l.tables())
    return l


@generate_func
def test_constraints() -> Layout:
    layers = ordec.layout.SG13G2().layers
    l = Layout(ref_layers=layers)

    l.activ = LayoutRect(layer=layers.Activ)
    l.poly = LayoutRect(layer=layers.GatPoly)
    l.cont_d = LayoutRect(layer=layers.Cont)
    l.cont_s = LayoutRect(layer=layers.Cont)

    s = Solver(l)

    L = 130
    W = 130

    s.constrain(l.activ.rect.height == W)
    s.constrain(l.activ.rect.lx == 0)

    s.constrain(l.activ.rect.cx == l.poly.rect.cx)
    s.constrain(l.activ.rect.cy == l.poly.rect.cy)
    s.constrain(l.activ.rect.ly == l.poly.rect.ly + 180)
    s.constrain(l.poly.rect.width == L)
    s.constrain(l.poly.rect.ly == 0)

    s.constrain(l.cont_d.rect.cy == l.activ.rect.cy)
    s.constrain(l.cont_s.rect.cy == l.activ.rect.cy)

    s.constrain(l.cont_d.rect.is_square(160))
    s.constrain(l.cont_s.rect.is_square(160))

    s.constrain(l.cont_d.rect.lx - l.activ.rect.lx == 70)
    s.constrain(l.poly.rect.lx - l.cont_d.rect.ux == 110)
    s.constrain(l.activ.rect.ux - l.cont_s.rect.ux ==  70)

    s.solve()

    expand_geom(l)

    return l
