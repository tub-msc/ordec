# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from ordec.core import Orientation, Pin, PinType, SchemInstanceConn, Symbol
from ordec.extlibrary import ExtLibrary, ExtLibraryError
from ordec.schematic.helpers import symbol_place_pins


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
    sym.A = Pin(pintype=PinType.In, align=Orientation.West)
    sym.Y = Pin(pintype=PinType.Out, align=Orientation.East)
    symbol_place_pins(sym, hpadding=3, vpadding=2)
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
