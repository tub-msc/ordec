# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import logging

from .layout.gds_in import gds_discover
from .core import *
from public import public

logger = logging.getLogger(__name__)

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

    def read_spice(self, path, device_map: dict):
        """
        Add schematic(s) from a SPICE subcircuit netlist file.

        Each ``.subckt`` becomes a schematic; device instances are mapped to
        ORDeC leaf cells via device_map (model name -> DeviceMapping).

        Symbols are auto-generated from the subckt port lists as a fallback
        only: a symbol already registered by another reader (e.g. read_lef,
        which also provides pin directions) takes precedence. Call read_lef
        before read_spice to get correct pin directions.

        Args:
            path: Filesystem path to a SPICE netlist file.
            device_map: Mapping of SPICE model name to
                ordec.schematic.spice_in.DeviceMapping.
        """
        from .schematic.spice_in import spice_subckt_discover
        symbol_funcs_add, schematic_funcs_add = spice_subckt_discover(path, self, device_map)
        for name in schematic_funcs_add.keys():
            if name in self.schematic_funcs:
                raise ExtLibraryError(f"Multiple schematic sources found for cell {name!r}.")
        self.schematic_funcs |= schematic_funcs_add
        # Auto-generated symbols are a fallback: only fill in names that have no
        # symbol source yet (so a prior read_lef wins, without a conflict error).
        for name, func in symbol_funcs_add.items():
            self.symbol_funcs.setdefault(name, func)

    def __getitem__(self, name):
        return ExtLibraryCell(self, name)

class ExtLibraryCell(Cell):
    extlib = Parameter(ExtLibrary)
    name = Parameter(str)

    def unescaped_name(self):
        # Name exports (netlists, GDS, LVS) after the external cell alone; the
        # default would stringify all parameters and embed the ExtLibrary's
        # repr (including its memory address). Cells of the same name from
        # different ExtLibrary instances cannot collide: Directory.unique_name
        # suffixes duplicate basenames, and layout/schematic names are paired
        # via the shared cell object, not by string comparison.
        return self.name

    @generate
    def layout(self) -> Layout:
        logger.debug("generating layout %s", self.name)
        try:
            layout_func = self.extlib.layout_funcs[self.name]
        except KeyError:
            raise ExtLibraryError(f"No layout source found for cell {self.name!r}.") from None
        return layout_func()

    @generate
    def frame(self) -> Layout:
        logger.debug("generating frame %s", self.name)
        try:
            frame_func = self.extlib.frame_funcs[self.name]
        except KeyError:
            raise ExtLibraryError(f"No layout source found for cell {self.name!r}.") from None
        return frame_func()

    @generate
    def symbol(self) -> Symbol:
        logger.debug("generating symbol %s", self.name)
        try:
            symbol_func = self.extlib.symbol_funcs[self.name]
        except KeyError:
            raise ExtLibraryError(f"No symbol source found for cell {self.name!r}.") from None
        return symbol_func()

    @generate
    def schematic(self) -> Schematic:
        logger.debug("generating schematic %s", self.name)
        try:
            schematic_func = self.extlib.schematic_funcs[self.name]
        except KeyError:
            raise ExtLibraryError(f"No schematic source found for cell {self.name!r}.") from None
        return schematic_func()
