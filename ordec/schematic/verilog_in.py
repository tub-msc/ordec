# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from functools import partial
from collections import OrderedDict
from pathlib import Path
from typing import Any
from public import public
import json
import subprocess
import tempfile

from ..core import *
from .helpers import symbol_place_pins, schem_check
from .routing import adjust_outline_initial

@public
def verilog_to_yosys_json(verilog: str) -> dict[str, Any]:
    if not isinstance(verilog, str):
        raise TypeError(f"Expected str, got {type(verilog).__name__}.")

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        in_fn = td_path / "in.v"
        out_fn = td_path / "out.json"
        in_fn.write_text(verilog, encoding='utf-8')
        cmd = [
            "yosys",
            "-q",
            "-p",
            f"read_verilog {in_fn}; write_json {out_fn}",
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return json.loads(out_fn.read_text(encoding='utf-8'))

@public
def yosys_json_discover(json_data: dict[str, Any], extlib: 'ExtLibrary'):
    modules = json_data.get('modules')
    if not isinstance(modules, dict) or len(modules) == 0:
        raise ValueError("Yosys JSON has no modules.")
    if len(modules) != 1:
        raise ValueError("Yosys JSON must contain exactly one module for schematic import.")

    symbol_funcs = {}
    schematic_funcs = {}
    for module_name, module_data in modules.items():
        symbol_funcs[module_name] = partial(
            create_symbol,
            extlib=extlib,
            name=module_name,
            port_spec=module_port_spec(module_data),
        )
        schematic_funcs[module_name] = partial(
            create_schematic,
            extlib=extlib,
            module_name=module_name,
            module_data=module_data,
        )

    return symbol_funcs, schematic_funcs


def norm_direction(direction: Any) -> str:
    d = str(direction).strip().lower()
    if d in ('input', 'in'):
        return 'input'
    if d in ('output', 'out'):
        return 'output'
    return 'inout'


def module_port_spec(module_data: dict[str, Any]) -> OrderedDict[str, tuple[str, int]]:
    spec = OrderedDict()
    for port_name, port_data in module_data.get('ports', {}).items():
        direction = norm_direction(port_data.get('direction', 'inout'))
        bits = port_data.get('bits', [])
        width = len(bits)
        if width < 1:
            width = 1
        spec[port_name] = (direction, width)
    return spec


def create_symbol(extlib, name, port_spec: OrderedDict[str, tuple[str, int]]) -> Symbol:
    sym = Symbol(caption=name, cell=extlib[name])
    for port_name, (direction, width) in port_spec.items():
        if direction == 'input':
            p = Pin(pintype=PinType.In, align=Orientation.West)
        elif direction == 'output':
            p = Pin(pintype=PinType.Out, align=Orientation.East)
        else:
            p = Pin(pintype=PinType.Inout, align=Orientation.North)
        if width == 1:
            sym[port_name] = p
        else:
            sym[port_name] = PathNode()
            for i in range(width):
                sym[port_name][i] = p
    symbol_place_pins(sym, hpadding=3, vpadding=2)
    return sym.freeze()


def create_schematic(extlib, module_name, module_data: dict[str, Any]) -> Schematic:
    cell = extlib[module_name]
    symbol = cell.symbol
    schematic = Schematic(cell=cell, symbol=symbol)

    port_bits = {}
    for port_name, port_data in module_data.get('ports', {}).items():
        bits = port_data.get('bits', [])
        width = len(bits)
        for i, bit in enumerate(bits):
            if width == 1:
                pin = symbol[port_name]
            else:
                pin = symbol[port_name][i]
            port_bits.setdefault(bit, pin)

    bit_names = {}
    for net_name, net_data in module_data.get('netnames', {}).items():
        bits = net_data.get('bits', [])
        for i, bit in enumerate(bits):
            if bit in bit_names:
                continue
            if len(bits) == 1:
                bit_names[bit] = net_name
            else:
                bit_names[bit] = f"{net_name}[{i}]"

    used_paths = set()

    def unique_path(base_name: str) -> str:
        if base_name not in used_paths:
            used_paths.add(base_name)
            return base_name
        i = 1
        while True:
            name = f"{base_name}__{i}"
            if name not in used_paths:
                used_paths.add(name)
                return name
            i += 1

    bits_all = set()
    for port_data in module_data.get('ports', {}).values():
        bits_all.update(port_data.get('bits', []))
    for cell_data in module_data.get('cells', {}).values():
        for bits in cell_data.get('connections', {}).values():
            bits_all.update(bits)

    def bit_sort_key(bit):
        if isinstance(bit, int):
            return (0, bit)
        return (1, str(bit))

    bit_to_net = {}
    for bit in sorted(bits_all, key=bit_sort_key):
        base_name = bit_names.get(bit)
        if base_name is None:
            if isinstance(bit, int):
                base_name = f"bit_{bit}"
            else:
                base_name = f"const_{bit}"
        path_name = unique_path(base_name)
        pin = port_bits.get(bit)
        if pin is None:
            schematic[path_name] = Net()
        else:
            schematic[path_name] = Net(pin=pin)
        bit_to_net[bit] = schematic[path_name]

    port_count_by_align = {
        Orientation.West: 0,
        Orientation.East: 0,
        Orientation.North: 0,
        Orientation.South: 0,
    }

    def next_port_pos(align: D4) -> Vec2R:
        i = port_count_by_align[align]
        port_count_by_align[align] = i + 1
        if align == Orientation.West:
            return Vec2R(24, 2 * i + 1)
        if align == Orientation.East:
            return Vec2R(0, 2 * i + 1)
        if align == Orientation.North:
            return Vec2R(2 * i + 1, 24)
        return Vec2R(2 * i + 1, 0)

    for bit, pin in port_bits.items():
        schematic % SchemPort(ref=bit_to_net[bit], pos=next_port_pos(pin.align*D4.R180), align=pin.align*D4.R180)

    cur_y =0
    for inst_i, (cell_name, cell_data) in enumerate(module_data.get('cells', {}).items()):
        cell_type = cell_data.get('type')
        if not isinstance(cell_type, str):
            raise ValueError(f"Invalid cell type in module {module_name!r}: {cell_type!r}.")
        inst_name = unique_path(cell_name)
        schematic[inst_name] = SchemInstance(
            symbol=extlib[cell_type].symbol,
            pos=Vec2R(10, cur_y)
        )
        cur_y += extlib[cell_type].symbol.outline.height + 2
        inst = schematic[inst_name]
        for port_name, bits in cell_data.get('connections', {}).items():
            width = len(bits)
            for i, bit in enumerate(bits):
                if width == 1:
                    there = inst.symbol[port_name]
                else:
                    there = inst.symbol[port_name][i]
                schematic % SchemInstanceConn(ref=inst, here=bit_to_net[bit], there=there)

        connected_pins = {
            c.there.nid for c in schematic.all(SchemInstanceConn.ref_idx.query(inst))
        }
        for pin in inst.symbol.all(Pin):
            if pin.nid in connected_pins:
                continue
            nc_name = unique_path(f"nc_{inst_name}_{pin.nid}")
            schematic[nc_name] = Net(route=False)
            schematic % SchemInstanceConn(ref=inst, here=schematic[nc_name], there=pin)

    schem_check(schematic, add_terminal_taps=True)
    outline = adjust_outline_initial(schematic)
    if outline is None:
        outline = Rect4R(0, 0, 1, 1)
    schematic.outline = outline
    return schematic.freeze()
