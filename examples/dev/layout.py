import os
from pathlib import Path
import ordec.layout
from ordec.core import *

@generate_func
def sg13g2_xor2_1_layout() -> Layout:
    ihp_path = Path(os.getenv("ORDEC_PDK_IHP_SG13G2"))
    gds_fn = ihp_path / "libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds"
    top = 'sg13g2_xor2_1'
    layouts = ordec.layout.read_gds(gds_fn, ordec.layout.SG13G2().layers, top)
    return layouts[top]
