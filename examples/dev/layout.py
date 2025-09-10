import os
from pathlib import Path
import ordec.layout
from ordec.core import *

ihp_path = Path(os.getenv("ORDEC_PDK_IHP_SG13G2"))

@generate_func
def sg13g2_xor2_1_layout() -> Layout:
    gds_fn = ihp_path / "libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds"
    top = 'sg13g2_xor2_1'
    #top = 'sg13g2_sdfrbpq_2'
    #top = 'sg13g2_inv_1'
    layouts = ordec.layout.read_gds(gds_fn, ordec.layout.SG13G2().layers, top)
    return layouts[top]


@generate_func
def sg13g2_iopad() -> Layout:
    gds_fn = ihp_path / "libs.ref/sg13g2_sram/gds/RM_IHPSG13_1P_1024x64_c2_bm_bist.gds"
    top = "RM_IHPSG13_1P_1024x64_c2_bm_bist"
    layouts = ordec.layout.read_gds(gds_fn, ordec.layout.SG13G2().layers, top)
    print(layouts.keys())
    return layouts[top]

#layout = sg13g2_xor2_1_layout()
#print(render(layout).svg().decode('utf-8'))
