# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from ordec.core import *
from ordec.extlibrary import ExtLibrary
from ordec.lib import ihp130

@pytest.mark.ihp130
def test_read_lef_symbol():
    lef = ihp130.pdk().stdcell_lef

    lib = ExtLibrary()
    lib.read_lef(lef)

    inv = lib["sg13g2_inv_1"].symbol
    pin_names = {pin.full_path_str() for pin in inv.all(Pin)}
    assert pin_names == {"A", "Y", "VDD", "VSS"}

    assert inv.A.pintype == PinType.In
    assert inv.Y.pintype == PinType.Out
    assert inv.VSS.pintype == PinType.Inout
    assert inv.VDD.pintype == PinType.Inout

@pytest.mark.xfail(reason="Undesirable behavior of sc-leflib, raising cryptic LefReaderException instead of FileNotFoundError.")
def test_read_lef_file_not_found():
    lib = ExtLibrary()
    with pytest.raises(FileNotFoundError):
        lib.read_lef("/does_not_exist")
