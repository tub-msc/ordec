# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0
import subprocess

import pytest

from ordec.layout import gdsrecords
from ordec.lib import sky130

pytestmark = pytest.mark.magic


def test_run_magic(tmp_path):
    (tmp_path / "gen.tcl").write_text(
        "load top\n"
        "magic::gencell sky130::sky130_fd_pr__nfet_01v8 m1 w $w l 0.15\n"
        "select top cell\n"
        "gds write $gds\n")
    sky130.run_magic("gen.tcl", tmp_path, capture="gen.log", w=1.0, gds="top.gds")
    _, structures = gdsrecords.scan((tmp_path / "top.gds").read_bytes())
    assert any(name.startswith(b"sky130_fd_pr__nfet_01v8_") for name, _, _ in structures)

    (tmp_path / "fail.tcl").write_text("no_such_command\n")
    with pytest.raises(subprocess.CalledProcessError):
        sky130.run_magic("fail.tcl", tmp_path, capture="fail.log")
    assert "no_such_command" in (tmp_path / "fail.log").read_text()
