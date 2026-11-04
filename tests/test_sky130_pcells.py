# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0
"""
The sky130 layouts against the PDK's device generators (sky130A.tcl), which
run in magic.
"""
import json
from pathlib import Path

import pytest

from ordec.core import *
from ordec.layout import klayout
from ordec.layout.gds_out import write_gds
from ordec.lib import sky130

pytestmark = pytest.mark.magic

# (ORDeC cell, generator device, generator parameters). Magic's w is per finger.
CASES = [
    (sky130.Nmos(w="1u", l="150n"), "nfet_01v8", "w 1.0 l 0.15"),
    (sky130.Nmos(w="1u", l="150n", guard=False), "nfet_01v8", "w 1.0 l 0.15 guard 0"),
    (sky130.Nmos(w="2u", l="150n", nf=2, guard=False), "nfet_01v8", "w 1.0 l 0.15 nf 2 guard 0"),
    (sky130.Nmos(w="420n", l="150n", guard=False), "nfet_01v8", "w 0.42 l 0.15 guard 0"),
    (sky130.Nmos(w="1260n", l="150n", nf=3, m=2), "nfet_01v8", "w 0.42 l 0.15 nf 3 m 2"),
    (sky130.Nmos(w="4u", l="1u", nf=4, m=2, poverlap=True), "nfet_01v8", "w 1.0 l 1.0 nf 4 m 2 poverlap 1"),
    (sky130.Nmos(w="2u", l="300n", nf=2, doverlap=False), "nfet_01v8", "w 1.0 l 0.3 nf 2 doverlap 0"),
    (sky130.Nmos(w="5.02u", l="500n", topc=False, diffcov=50, polycov=50, tbcov=40, rlcov=40,
        viasrc="50", viadrn="50", viagate="0", full_metal=False, grc=False, gtc=False),
        "nfet_01v8", "w 5.02 l 0.5 topc 0 diffcov 50 polycov 50 tbcov 40 rlcov 40 "
        "viasrc 50 viadrn 50 viagate 0 full_metal 0 grc 0 gtc 0"),
    (sky130.Nmos(w="2u", l="1u", viagb="100", viagt="50", viagr="50", viagl="50", viasrc="0", viadrn="0"),
        "nfet_01v8", "w 2.0 l 1.0 viagb 100 viagt 50 viagr 50 viagl 50 viasrc 0 viadrn 0"),
    (sky130.Pmos(w="4u", l="500n", nf=4), "pfet_01v8", "w 1.0 l 0.5 nf 4"),
    (sky130.Pmos(w="420n", l="150n"), "pfet_01v8", "w 0.42 l 0.15"),
    (sky130.Pmos(w="1u", l="150n", guard=False), "pfet_01v8", "w 1.0 l 0.15 guard 0"),
    (sky130.NmosLvt(w="2u", l="150n", nf=2), "nfet_01v8_lvt", "w 1.0 l 0.15 nf 2"),
    (sky130.PmosLvt(w="2u", l="350n", nf=2), "pfet_01v8_lvt", "w 1.0 l 0.35 nf 2"),
    (sky130.PmosHvt(w="2u", l="150n", nf=2), "pfet_01v8_hvt", "w 1.0 l 0.15 nf 2"),
    (sky130.NmosHv(w="2u", l="500n", nf=2), "nfet_g5v0d10v5", "w 1.0 l 0.5 nf 2"),
    (sky130.PmosHv(w="2u", l="500n", nf=2), "pfet_g5v0d10v5", "w 1.0 l 0.5 nf 2"),
    (sky130.Nmos05v0Nvt(w="2u", l="900n", nf=2), "nfet_05v0_nvt", "w 1.0 l 0.9 nf 2"),
    (sky130.Nmos03v3Nvt(w="1u", l="500n"), "nfet_03v3_nvt", "w 1.0 l 0.5"),
    (sky130.RhighPo0p35(l="2u", w="0.35u"), "res_high_po_0p35", "w 0.35 l 2.0"),
    (sky130.RhighPo0p69(l="6u", w="0.69u", nx=2, snake=True), "res_high_po_0p69", "w 0.69 l 6.0 nx 2 snake 1"),
    (sky130.RhighPo1p41(l="2u", w="1.41u"), "res_high_po_1p41", "w 1.41 l 2.0"),
    (sky130.RhighPo2p85(l="2u", w="2.85u"), "res_high_po_2p85", "w 2.85 l 2.0"),
    (sky130.RhighPo5p73(l="6u", w="5.73u"), "res_high_po_5p73", "w 5.73 l 6.0"),
    (sky130.RxhighPo0p35(l="2u", w="0.35u"), "res_xhigh_po_0p35", "w 0.35 l 2.0"),
    (sky130.RxhighPo5p73(l="2u", w="5.73u", guard=False), "res_xhigh_po_5p73", "w 5.73 l 2.0 guard 0"),
    (sky130.Rnd(l="2.1u", w="0.42u"), "res_generic_nd", "w 0.42 l 2.1"),
    (sky130.Rnd(l="2.1u", w="0.42u", nx=3, snake=True), "res_generic_nd", "w 0.42 l 2.1 nx 3 snake 1"),
    (sky130.Rpd(l="2.1u", w="0.42u", nx=2, m=2), "res_generic_pd", "w 0.42 l 2.1 nx 2 m 2"),
    (sky130.RndHv(l="2.1u", w="0.42u"), "res_generic_nd__hv", "w 0.42 l 2.1"),
    (sky130.RpdHv(l="2.1u", w="0.42u", vias=False), "res_generic_pd__hv", "w 0.42 l 2.1 vias 0"),
    (sky130.Rl1(l="1u", w="0.17u"), "res_generic_l1", "w 0.17 l 1.0"),
    (sky130.Rm1(l="1u", w="0.14u"), "res_generic_m1", "w 0.14 l 1.0"),
    (sky130.Rm2(l="1u", w="0.14u", nx=2), "res_generic_m2", "w 0.14 l 1.0 nx 2"),
    (sky130.Rm3(l="2u", w="1u", m=2), "res_generic_m3", "w 1.0 l 2.0 m 2"),
    (sky130.Rm4(l="1u", w="0.3u"), "res_generic_m4", "w 0.3 l 1.0"),
    (sky130.Rm5(l="2u", w="1.6u"), "res_generic_m5", "w 1.6 l 2.0"),
    (sky130.RisoPw(l="26.5u", w="2.65u"), "res_iso_pw", "w 2.65 l 26.5"),
    (sky130.RisoPw(l="26.5u", w="2.65u", m=2, guard=False), "res_iso_pw", "w 2.65 l 26.5 m 2 guard 0"),
    (sky130.Rpoly(l="1.65u", w="0.33u"), "res_generic_po", "w 0.33 l 1.65"),
    (sky130.Rpoly(l="2u", w="1u", endcov=50), "res_generic_po", "w 1.0 l 2.0 endcov 50"),
    (sky130.DiodePw2nd(), "diode_pw2nd_05v5", "w 0.45 l 0.45"),
    (sky130.DiodePw2nd(w="1u", l="2u", nx=2, ny=2, vias=False), "diode_pw2nd_05v5", "w 1.0 l 2.0 nx 2 ny 2 vias 0"),
    (sky130.DiodePw2ndLvt(), "diode_pw2nd_05v5_lvt", "w 0.45 l 0.45"),
    (sky130.DiodePw2ndNvt(), "diode_pw2nd_05v5_nvt", "w 0.45 l 0.45"),
    (sky130.DiodePw2nd11v0(), "diode_pw2nd_11v0", "w 0.45 l 0.45"),
    (sky130.DiodePd2nw(), "diode_pd2nw_05v5", "w 0.45 l 0.45"),
    (sky130.DiodePd2nw(w="1u", l="2u", nx=2), "diode_pd2nw_05v5", "w 1.0 l 2.0 nx 2"),
    (sky130.DiodePd2nwLvt(), "diode_pd2nw_05v5_lvt", "w 0.45 l 0.45"),
    (sky130.DiodePd2nwHvt(), "diode_pd2nw_05v5_hvt", "w 0.45 l 0.45"),
    (sky130.DiodePd2nw11v0(), "diode_pd2nw_11v0", "w 0.45 l 0.45"),
]

PIN_PURPOSE = 16  # Pin shapes are not compared: the generators draw none.


def generator_variant(cell):
    """The cell without the deviations from the generators that can be switched off."""
    if isinstance(cell, sky130.Mos):
        return type(cell)(**cell.params | {"gate_min_area": False})
    return cell


def test_pcell_geometry(tmp_path):
    sky130.run_magic(Path(__file__).parent / "lib/sky130_magic_ref.tcl", tmp_path, cases="".join(
        f"c{i} sky130_fd_pr__{device} {{{params}}}\n" for i, (_, device, params) in enumerate(CASES)))

    cases = []
    for i, (cell, _, _) in enumerate(CASES):
        gds = tmp_path / f"o{i}.gds"
        with open(gds, "wb") as f:
            write_gds(generator_variant(cell).layout, f)
        cases.append(dict(id=str(i), gds=str(gds), ref_gds=str(tmp_path / f"c{i}.gds")))
    (tmp_path / "cases.json").write_text(json.dumps(cases))
    klayout.run(Path(__file__).parent / "lib/sky130_pcell_xor.py", tmp_path,
        cases="cases.json", result_file="result.json")
    result = json.loads((tmp_path / "result.json").read_text())

    failures = []
    for i, (cell, _, _) in enumerate(CASES):
        drawn = {k: area for k, area in result[str(i)].items() if int(k.split("/")[1]) != PIN_PURPOSE}
        if drawn:
            failures.append(f"{cell}: {drawn}")
    assert not failures, "XOR area in um² per layer:\n" + "\n".join(failures)
