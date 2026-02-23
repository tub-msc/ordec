# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
import pytest

from ordec.core import *
from ordec.extlibrary import ExtLibrary

def test_read_lef_symbol():
    lef = Path(os.getenv("ORDEC_PDK_IHP_SG13G2")) / "libs.ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef"

    lib = ExtLibrary()
    lib.read_lef(lef)

    inv = lib["sg13g2_inv_1"].symbol
    pin_names = {pin.full_path_str() for pin in inv.all(Pin)}
    assert pin_names == {"A", "Y", "VDD", "VSS"}

    assert inv.A.pintype == PinType.In
    assert inv.Y.pintype == PinType.Out
    assert inv.VSS.pintype == PinType.Inout
    assert inv.VDD.pintype == PinType.Inout
