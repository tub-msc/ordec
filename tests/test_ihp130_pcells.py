# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0
"""
The ihp130 layouts against the PDK's PCells (sg13g2_pycell_lib), which run in
KLayout and need the PDK's submodules pycell4klayout-api and pypreprocessor.
"""
import json
import subprocess
from pathlib import Path

import pytest

from ordec.core import *
from ordec.layout import klayout
from ordec.layout.gds_out import write_gds
from ordec.lib import ihp130

# (ORDeC cell, PCell name, PCell parameters). Not covered on purpose: bent
# resistors (stripes drawn l - w long, so that LVS measures l) and Cmim
# below 2.4u (the PCell fails TM1.a there), see the ihp130 docs.
CASES = [
    (ihp130.Nmos(w="1u", l="130n"), "nmos", dict(w="1u", l="0.13u", ng="1")),
    (ihp130.Nmos(w="5u", l="1u", ng=5), "nmos", dict(w="5u", l="1u", ng="5")),
    (ihp130.Pmos(w="1.2u", l="0.2u", ng=4), "pmos", dict(w="1.2u", l="0.2u", ng="4")),
    (ihp130.NmosHv(w="0.6u", l="0.45u"), "nmosHV", dict(w="0.6u", l="0.45u", ng="1")),
    (ihp130.PmosHv(w="3u", l="0.5u", ng=3), "pmosHV", dict(w="3u", l="0.5u", ng="3")),
    (ihp130.RfNmos(w="1u", l="0.72u"), "rfnmos", dict(w="1u", l="0.72u", ng="1")),
    (ihp130.RfPmos(w="10u", l="0.13u", ng=2), "rfpmos", dict(w="10u", l="0.13u", ng="2")),
    (ihp130.RfNmosHv(w="1u", l="0.72u"), "rfnmosHV", dict(w="1u", l="0.72u", ng="1")),
    (ihp130.RfPmosHv(w="1u", l="0.72u"), "rfpmosHV", dict(w="1u", l="0.72u", ng="1")),
    (ihp130.RfNmos(w="4u", l="0.13u", ng=2, cnt_rows=2, met2_cont=False, guard_ring="U"), "rfnmos",
        dict(w="4u", l="0.13u", ng="2", cnt_rows=2, Met2Cont="No", guard_ring="U")),
    (ihp130.RfPmos(w="2u", l="0.2u", cnt_rows=3, gat_ring=False, guard_ring="TB"), "rfpmos",
        dict(w="2u", l="0.2u", ng="1", cnt_rows=3, gat_ring="No", guard_ring="Top+Bottom")),
    (ihp130.RfNmosHv(w="1u", l="0.72u", guard_ring=None), "rfnmosHV",
        dict(w="1u", l="0.72u", ng="1", guard_ring="No")),
    (ihp130.Ntap1(w="0.78u", l="0.78u"), "ntap1", dict(w="0.78u", l="0.78u")),
    (ihp130.Ptap1(w="1u", l="2u"), "ptap1", dict(w="1u", l="2u")),
    (ihp130.Rsil(w="0.5u", l="0.5u"), "rsil", dict(w="0.5u", l="0.5u")),
    (ihp130.Rppd(w="2u", l="10u"), "rppd", dict(w="2u", l="10u")),
    (ihp130.Rhigh(w="0.5u", l="0.96u"), "rhigh", dict(w="0.5u", l="0.96u")),
    (ihp130.Cmim(w="20u", l="5u"), "cmim", dict(w="20u", l="5u")),
    (ihp130.Rfcmim(w="7u", l="7u", wfeed="3u"), "rfcmim", dict(w="7u", l="7u", wfeed="3u")),
    (ihp130.Svaricap(w="9.74u", l="0.8u", nx=2), "SVaricap", dict(w="9.74u", l="0.8u", Nx=2)),
    (ihp130.Bondpad(size="80u"), "bondpad", dict(diameter="80u")),
    (ihp130.Bondpad(size="60u", shape=1, bottom_metal=1), "bondpad",
        dict(diameter="60u", shape="square", bottomMetal="1")),
    (ihp130.Inductor2(w="2u", s="2.1u", d="15.48u", nr_r=1), "inductor2",
        dict(w="2u", s="2.1u", d="15.48u", nr_r=1)),
    (ihp130.Inductor3(w="2u", s="2.1u", d="25.84u", nr_r=2), "inductor3",
        dict(w="2u", s="2.1u", d="25.84u", nr_r=2)),
    (ihp130.Npn13G2(nx=2), "npn13G2", dict(Nx=2)),
    (ihp130.Npn13G2l(el=1), "npn13G2L", dict(Nx=1, le="1u")),
    (ihp130.Npn13G2v(el=2, nx=2), "npn13G2V", dict(Nx=2, le="2u")),
    (ihp130.PnpMPA(w="0.7u", l="2u"), "pnpMPA", dict(w="0.7u", l="2u")),
    (ihp130.Isolbox(w="8u", l="5u", cont_ring="U"), "isolbox", dict(w="8u", l="5u", cont_ring="U")),
    (ihp130.Isolbox(w="6u", l="7u", cont_ring="O", wellwidth="1.5u", pwell_w="1u"), "isolbox",
        dict(w="6u", l="7u", cont_ring="O", wellwidth="1.5u", pwell_w="1u")),
    (ihp130.Dantenna(w="0.78u", l="0.78u"), "dantenna", dict(w="0.78u", l="0.78u")),
    (ihp130.Dpantenna(w="1.5u", l="4u"), "dpantenna", dict(w="1.5u", l="4u")),
    (ihp130.SchottkyNbl1(nx=2, ny=2), "schottky", dict(Nx=2, Ny=2)),
    (ihp130.Diodevdd2kv(), "esd", dict(model="diodevdd_2kv")),
    (ihp130.Sealring(l="150u", w="210u", edge_box="10u"), "sealring",
        dict(l="150u", w="210u", edgeBox="10u")),
    (ihp130.ViaStack(b_layer="Activ", t_layer="Metal3", vn_columns=1, vn_rows=3), "via_stack",
        dict(b_layer="Activ", t_layer="Metal3", vn_columns=1, vn_rows=3)),
    (ihp130.NoFillerStack(w="10u", l="10u"), "NoFillerStack", dict(w="10u", l="10u")),
]

# Drawn layers that differ on purpose: the antenna diodes add the Metal1 end
# caps (M1.c1) that their PCells miss.
DEVIATIONS = {"dantenna": {"8/0"}, "dpantenna": {"8/0"}}

PIN_PURPOSE = 2  # Pin shapes are not compared yet (the PCells draw them inconsistently).


def test_pcell_geometry(tmp_path):
    cases = []
    for i, (cell, pcell, params) in enumerate(CASES):
        gds = tmp_path / f"{i}.gds"
        with open(gds, "wb") as f:
            write_gds(cell.layout, f)
        cases.append(dict(id=str(i), pcell=pcell, params=params, gds=str(gds)))
    (tmp_path / "cases.json").write_text(json.dumps(cases))

    try:
        klayout.run(Path(__file__).parent / "lib/ihp130_pcell_xor.py", tmp_path,
            capture="klayout.log", pdk_root=ihp130.pdk().root,
            cases="cases.json", result_file="result.json")
    except subprocess.CalledProcessError:
        # Typically the PDK's submodules are missing, see docs/dev/setup.rst.
        pytest.fail("KLayout failed:\n" + (tmp_path / "klayout.log").read_text())
    result = json.loads((tmp_path / "result.json").read_text())

    failures = []
    for i, (cell, pcell, _) in enumerate(CASES):
        drawn = {k: area for k, area in result[str(i)].items()
            if int(k.split("/")[1]) != PIN_PURPOSE and k not in DEVIATIONS.get(pcell, ())}
        if drawn:
            failures.append(f"{cell}: {drawn}")
    assert not failures, "XOR area in um² per layer:\n" + "\n".join(failures)


# Symbol pins without a LayoutPin: nodes without a shape of their own, i.e.
# the common substrate and the HBT's thermal node.
SHAPELESS_PINS = {
    ihp130.Nmos: {"b"}, ihp130.NmosHv: {"b"},
    ihp130.Ptap1: {"sub"},
    ihp130.Rsil: {"bn"}, ihp130.Rppd: {"bn"}, ihp130.Rhigh: {"bn"},
    ihp130.Svaricap: {"bn"},
    ihp130.Inductor2: {"b"}, ihp130.Inductor3: {"b"},
    ihp130.Npn13G2: {"bn"}, ihp130.Npn13G2l: {"bn", "t"}, ihp130.Npn13G2v: {"bn", "t"},
    ihp130.Isolbox: {"isosub", "sub"},
    ihp130.Dantenna: {"d0"},
}


def test_layout_pins():
    for cell, _, _ in CASES:
        if isinstance(cell, (ihp130.Via, ihp130.ViaStack, ihp130.NoFillerStack, ihp130.Sealring)):
            continue  # layout-only cells
        symbol_pins = {str(p.npath.name) for p in cell.symbol.all(Pin)}
        layout_pins = {str(p.pin.npath.name) for p in cell.layout.all(LayoutPin)}
        assert symbol_pins - layout_pins == SHAPELESS_PINS.get(type(cell), set()) & symbol_pins, cell
