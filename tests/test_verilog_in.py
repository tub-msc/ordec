# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest

from ordec.core import *
from ordec.extlibrary import ExtLibrary, ExtLibraryError
from ordec.lib import ihp130
from ordec.schematic.verilog_in import run_yosys


def _yosys_json_example():
    return {
        "modules": {
            "top": {
                "ports": {
                    "a": {"direction": "input", "bits": [2]},
                    "b": {"direction": "output", "bits": [3, 4]},
                },
                "cells": {
                    "u0": {
                        "type": "MYBUF2",
                        "port_directions": {"A": "input", "Y": "output"},
                        "connections": {"A": [2], "Y": [3]},
                    }
                },
                "netnames": {
                    "a": {"bits": [2]},
                    "b": {"bits": [3, 4]},
                },
            }
        }
    }


def _install_mybuf2_symbol(lib: ExtLibrary):
    sym = Symbol(caption="MYBUF2", cell=lib["MYBUF2"])
    sym.A = Pin(pintype=PinType.In, align=West)
    sym.Y = Pin(pintype=PinType.Out, align=East)
    sym.place_pins(hpadding=3, vpadding=2)
    frozen = sym.freeze()
    lib.symbol_funcs["MYBUF2"] = lambda: frozen


def test_extlibrary_read_verilog_schematic_without_inferred_symbols():
    lib = ExtLibrary()
    lib.read_yosys_json(_yosys_json_example())
    with pytest.raises(ExtLibraryError, match="No symbol source found for cell 'MYBUF2'"):
        lib["top"].schematic


def test_extlibrary_read_verilog_symbol_and_schematic():
    lib = ExtLibrary()
    _install_mybuf2_symbol(lib)
    lib.read_yosys_json(_yosys_json_example())

    top_symbol = lib["top"].symbol
    assert top_symbol.a.pintype == PinType.In
    assert top_symbol.b[0].pintype == PinType.Out
    assert top_symbol.b[1].pintype == PinType.Out

    top_schematic = lib["top"].schematic
    inst = top_schematic.u0
    assert inst.symbol.caption == "MYBUF2"
    assert len(list(top_schematic.all(SchemInstanceConn.ref_idx.query(inst)))) == 2


def test_extlibrary_read_verilog_duplicate_sources():
    lib = ExtLibrary()
    data = _yosys_json_example()
    lib.read_yosys_json(data)

    with pytest.raises(ExtLibraryError, match="Multiple (symbol|schematic) sources found for cell"):
        lib.read_yosys_json(data)


def synthesize(source_files: list[Path], top: str, liberty: Path, out: Path):
    """
    Synthesizes the (System)Verilog source files to a flat netlist of
    standard cells from the liberty file, written to the Verilog file out.
    """
    run_yosys([
        f"read_slang {' '.join(str(f) for f in source_files)} --top {top}",
        f"synth -top {top}",
        "flatten",
        "opt",
        f"dfflibmap -liberty {liberty}",
        f"abc -liberty {liberty}",
        "splitnets",
        "rename -hide */w:*[*",
        "opt_clean -purge",
        f"write_verilog {out}",
    ])


def test_counter_synth(tmp_path):
    """Yosys integration: RTL -> synthesized netlist -> ExtLibrary schematic."""
    pdk = ihp130.pdk()
    netlist = tmp_path / 'counter_synth.v'
    synthesize([Path(__file__).parent / 'lib/counter.v'], 'counter', pdk.stdcell_liberty, netlist)

    lib = ExtLibrary()
    lib.read_lef(pdk.stdcell_lef)
    lib.read_verilog(netlist.read_text())

    symbol = lib['counter'].symbol
    assert symbol.clk_i.pintype == PinType.In
    assert [symbol.val_o[i].pintype for i in range(8)] == [PinType.Out] * 8

    stdcells = [inst.symbol.cell.name for inst in lib['counter'].schematic.all(SchemInstance)]
    assert all(name.startswith('sg13g2_') for name in stdcells)
    # One flip-flop per counter bit shows that dfflibmap mapped to the liberty cells.
    assert sum(name.startswith('sg13g2_dfrbp') for name in stdcells) == 8
