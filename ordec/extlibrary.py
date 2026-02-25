# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from .layout.gds_in import gds_discover
from .core import *
from public import public

@public
class ExtLibraryError(Exception):
    pass

@public
class ExtLibrary:
    """TODO: Document me"""
    def __init__(self):
        self.layout_funcs = {}
        self.frame_funcs = {}
        self.symbol_funcs = {}
        self.schematic_funcs = {}

    def read_gds(self, gds_fn: str, layers: LayerStack):
        """TODO: Document me"""
        layout_funcs_add, frame_funcs_add = gds_discover(gds_fn, layers, self)
        for name in layout_funcs_add.keys():
            if name in self.layout_funcs:
                raise ExtLibraryError(f"Multiple layout sources found for cell {name!r}.")
        for name in frame_funcs_add.keys():
            if name in self.frame_funcs:
                raise ExtLibraryError(f"Multiple frame sources found for cell {name!r}.")
        self.layout_funcs |= layout_funcs_add
        self.frame_funcs |= frame_funcs_add

    def read_yosys_json(self, json_data: dict):
        """
        Add schematic(s) from Yosys JSON data.

        Args:
            json_data: Yosys JSON as dict.
        """
        from .schematic.verilog_in import yosys_json_discover
        symbol_funcs_add, schematic_funcs_add = yosys_json_discover(json_data, self)
        for name in symbol_funcs_add.keys():
            if name in self.symbol_funcs:
                raise ExtLibraryError(f"Multiple symbol sources found for cell {name!r}.")
        for name in schematic_funcs_add.keys():
            if name in self.schematic_funcs:
                raise ExtLibraryError(f"Multiple schematic sources found for cell {name!r}.")

        self.symbol_funcs |= symbol_funcs_add
        self.schematic_funcs |= schematic_funcs_add

    def read_lef(self, path):
        from .lef_in import lef_discover
        symbol_funcs_add = lef_discover(path, self)
        for name in symbol_funcs_add.keys():
            if name in self.symbol_funcs:
                raise ExtLibraryError(f"Multiple symbol sources found for cell {name!r}.")
        self.symbol_funcs |= symbol_funcs_add

    def read_verilog(self, verilog: str):
        """
        Add schematic from a synthesized Verilog netlist.

        Args:
            verilog: Synthesized Verilog netlist as string.
        """
        from .schematic.verilog_in import verilog_to_yosys_json
        json_data = verilog_to_yosys_json(verilog)
        self.read_yosys_json(json_data)

    def __getitem__(self, name):
        return ExtLibraryCell(self, name)

class ExtLibraryCell(Cell):
    extlib = Parameter(ExtLibrary)
    name = Parameter(str)

    @generate
    def layout(self) -> Layout:
        print(f"generating layout {self.name}")
        try:
            layout_func = self.extlib.layout_funcs[self.name]
        except KeyError:
            raise ExtLibraryError(f"No layout source found for cell {self.name!r}.") from None
        return layout_func()

    @generate
    def frame(self) -> Layout:
        print(f"generating frame {self.name}")
        try:
            frame_func = self.extlib.frame_funcs[self.name]
        except KeyError:
            raise ExtLibraryError(f"No layout source found for cell {self.name!r}.") from None
        return frame_func()

    @generate
    def symbol(self) -> Symbol:
        print(f"generating symbol {self.name}")
        try:
            symbol_func = self.extlib.symbol_funcs[self.name]
        except KeyError:
            raise ExtLibraryError(f"No symbol source found for cell {self.name!r}.") from None
        return symbol_func()

    @generate
    def schematic(self) -> Schematic:
        print(f"generating schematic {self.name}")
        try:
            schematic_func = self.extlib.schematic_funcs[self.name]
        except KeyError:
            raise ExtLibraryError(f"No schematic source found for cell {self.name!r}.") from None
        return schematic_func()
