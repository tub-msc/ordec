# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Currently only supports generation of Symbols from LEF. In the future, it should
also generate frame views (Layouts for routing).
"""


from functools import partial
from collections import OrderedDict
from typing import Any

from .core import *
from .schematic.helpers import symbol_place_pins

class LefReaderException(Exception):
    pass

def lef_discover(path, extlib: 'ExtLibrary'):
    import sc_leflib

    lef_data = sc_leflib.parse(str(path))
    symbol_specs = lef_symbol_specs(lef_data)
    symbol_funcs = {}
    for cell_name, pin_spec in symbol_specs.items():
        symbol_funcs[cell_name] = partial(
            create_symbol,
            extlib=extlib,
            name=cell_name,
            port_spec=pin_spec
        )
    return symbol_funcs


def norm_keymap(d: dict[str, Any]) -> dict[str, Any]:
    return {str(k).lower(): v for k, v in d.items()}


def norm_direction(direction: Any) -> str:
    d = str(direction).strip().lower()
    if d in ('input', 'in'):
        return 'input'
    if d in ('output', 'out'):
        return 'output'
    return 'inout'


def dir_to_pintype(direction: str) -> PinType:
    if direction == 'input':
        return PinType.In
    if direction == 'output':
        return PinType.Out
    return PinType.Inout


def dir_to_align(direction: str) -> D4:
    if direction == 'input':
        return Orientation.West
    if direction == 'output':
        return Orientation.East
    return Orientation.North


def macro_name(macro: dict[str, Any]) -> str | None:
    m = norm_keymap(macro)
    name = m.get('name') or m.get('macro')
    return name if isinstance(name, str) and name else None


def macro_pins(macro: dict[str, Any]) -> OrderedDict[str, tuple[str, int]]:
    m = norm_keymap(macro)
    pins_raw = m.get('pins')
    pins = OrderedDict()
    if isinstance(pins_raw, dict):
        for pin_name, pin_data in pins_raw.items():
            pin_data_norm = norm_keymap(pin_data if isinstance(pin_data, dict) else {})
            direction = norm_direction(pin_data_norm.get('direction', 'inout'))
            pins[str(pin_name)] = (direction, 1)
    elif isinstance(pins_raw, list):
        for pin_data in pins_raw:
            if not isinstance(pin_data, dict):
                continue
            pin_data_norm = norm_keymap(pin_data)
            pin_name = pin_data_norm.get('name') or pin_data_norm.get('pin')
            if not isinstance(pin_name, str) or not pin_name:
                continue
            direction = norm_direction(pin_data_norm.get('direction', 'inout'))
            pins[pin_name] = (direction, 1)
    return pins


def lef_symbol_specs(lef_data: Any) -> OrderedDict[str, OrderedDict[str, tuple[str, int]]]:
    if not isinstance(lef_data, dict):
        raise LefReaderException("Unexpected LEF parse result: expected dict at top level.")

    d = norm_keymap(lef_data)
    macros_raw = d.get('macros')
    if isinstance(macros_raw, dict):
        macros_iter = list(macros_raw.items())
    elif isinstance(macros_raw, list):
        macros_iter = list(enumerate(macros_raw))
    else:
        raise LefReaderException("Unexpected LEF parse result: missing 'macros' container.")

    symbol_specs = OrderedDict()
    for macro_key, macro in macros_iter:
        if not isinstance(macro, dict):
            continue
        if isinstance(macro_key, str) and macro_key:
            name = macro_key
        else:
            name = macro_name(macro)
        if not name:
            continue
        pin_spec = macro_pins(macro)
        if len(pin_spec) == 0:
            continue
        symbol_specs[name] = pin_spec

    if len(symbol_specs) == 0:
        raise LefReaderException("No LEF cells with pins found.")
    return symbol_specs


def create_symbol(extlib: 'ExtLibrary', name: str, port_spec: OrderedDict[str, tuple[str, int]]) -> Symbol:
    sym = Symbol(caption=name, cell=extlib[name])
    for port_name, (direction, width) in port_spec.items():
        pin_kwargs = {
            'pintype': dir_to_pintype(direction),
            'align': dir_to_align(direction),
        }
        if width == 1:
            sym[port_name] = Pin(**pin_kwargs)
        else:
            sym.mkpath(port_name)
            for i in range(width):
                sym[port_name][i] = Pin(**pin_kwargs)
    symbol_place_pins(sym, hpadding=3, vpadding=2)
    return sym.freeze()
