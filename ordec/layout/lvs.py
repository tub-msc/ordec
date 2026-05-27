# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..core.directory import Directory
from ..core.schema import LvsReport, LvsCircuitPair, LvsItem


def circuit_layout_name(circuit: LvsCircuitPair):
    if circuit.ref_layout:
        return type(circuit.ref_layout.cell).__name__
    return circuit.layout_cell


def circuit_schem_name(circuit: LvsCircuitPair):
    if circuit.ref_schematic:
        return type(circuit.ref_schematic.cell).__name__
    return circuit.schem_cell


def item_layout_name(item: LvsItem):
    return item.layout_name


def item_schem_name(item: LvsItem):
    """Prefer the name derived from the ExternalRef over the LVSDB name."""
    if item.schem:
        return Directory.basename_of_node(item.schem)
    return item.schem_name


def webdata(report: LvsReport):
    circuits = []
    for circuit in report.all(LvsCircuitPair):
        circuits.append({
            'nid': circuit.nid,
            'layout_name': circuit_layout_name(circuit),
            'schem_name': circuit_schem_name(circuit),
            'status': circuit.status.value,
            'message': circuit.message,
        })

    items = []
    for item in report.all(LvsItem):
        pos = item.layout_pos
        items.append({
            'nid': item.nid,
            'circuit_nid': item.circuit.nid,
            'item_type': item.item_type.value,
            'status': item.status.value,
            'layout_name': item_layout_name(item),
            'schem_name': item_schem_name(item),
            'schem_nid': item.schem.nid if item.schem else None,
            'layout_pos': [int(pos.x), int(pos.y)] if pos else None,
            'layout_params': dict(item.layout_params) if item.layout_params else None,
            'schem_params': dict(item.schem_params) if item.schem_params else None,
            'message': item.message,
        })

    return 'lvs_report', {
        'top_cell': report.top_cell,
        'status': report.status.value,
        'circuits': circuits,
        'items': items,
        'unit': float(report.ref_layout.ref_layers.unit) if report.ref_layout else 1.0,
    }
