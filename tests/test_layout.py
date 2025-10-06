# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
import ordec.layout

def test_read_gds():
    ihp_path = Path(os.getenv("ORDEC_PDK_IHP_SG13G2"))
    gds_fn = ihp_path / "libs.ref/sg13g2_stdcell/gds/sg13g2_stdcell.gds"
    x = ordec.layout.read_gds(gds_fn, ordec.layout.SG13G2().layers, 'sg13g2_xor2_1')
    print(x)
