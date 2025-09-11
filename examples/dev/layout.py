import os
from pathlib import Path
import ordec.layout
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
