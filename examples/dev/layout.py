import os
from pathlib import Path
import ordec.layout
from ordec.layout.helpers import paths_to_poly
from ordec.core import *

ihp_path = Path(os.getenv("ORDEC_PDK_IHP_SG13G2"))

@generate_func
def layout_xor() -> Layout:
    gds_fn = ihp_path / "libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds"
    top = 'sg13g2_xor2_1'
    layouts = ordec.layout.read_gds(gds_fn, ordec.layout.SG13G2().layers, top)
    return layouts[top]

@generate_func
def layout_dff() -> Layout:
    gds_fn = ihp_path / "libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds"
    top = 'sg13g2_sdfrbpq_2'
    layouts = ordec.layout.read_gds(gds_fn, ordec.layout.SG13G2().layers, top)
    return layouts[top]


@generate_func
def layout_ota() -> Layout:
    gds_fn = "../ordec2/example_layouts/OTA_flat.gds"
    top = "OTA"
    layouts = ordec.layout.read_gds(gds_fn, ordec.layout.SG13G2().layers, top)
    return layouts[top]

@generate_func
def layout_paths2poly() -> Layout:
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

    paths_to_poly(l)

    return l
