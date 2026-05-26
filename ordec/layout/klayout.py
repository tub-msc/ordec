# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import shlex
import subprocess
import xml.etree.ElementTree as ET
import re
import warnings
from typing import Callable

from lark import Lark, Transformer, v_args

from ..core import *


def run(script, cwd, **kwargs):
    """
    Run KLayout script 'script' in directory 'cwd' with provided keyword args.
    """
    cmdline = ['klayout', '-b', '-r', str(script)]
    for k, v in kwargs.items():
        cmdline += ['-rd', f'{k}={v}']
    print(cwd, shlex.join(cmdline))
    subprocess.check_call(cmdline, cwd=cwd)


def _microns_to_dbu(value_um: float, unit: R) -> int:
    """Convert micron value to database units."""
    um_in_m = R('1u')
    dbu_per_um = um_in_m / unit
    return int(round(float(value_um * dbu_per_um)))


def _parse_coord(s: str, conv: Callable[[float], int]) -> int:
    """Parse a coordinate string and convert to dbu."""
    return conv(float(s))


def _parse_point(s: str, conv: Callable[[float], int]) -> Vec2I:
    """Parse 'x,y' coordinate string to Vec2I in dbu."""
    x_str, y_str = s.split(',')
    return Vec2I(_parse_coord(x_str, conv), _parse_coord(y_str, conv))


def _parse_box(value_str: str, conv: Callable[[float], int]) -> Rect4I:
    """Parse KLayout box value string: '(x1,y1;x2,y2)'."""
    match = re.match(r'\(([^;]+);([^)]+)\)', value_str)
    if not match:
        raise ValueError(f"Invalid box format: {value_str}")
    p1 = _parse_point(match.group(1), conv)
    p2 = _parse_point(match.group(2), conv)
    return Rect4I(min(p1.x, p2.x), min(p1.y, p2.y), max(p1.x, p2.x), max(p1.y, p2.y))


def _parse_edge(value_str: str, conv: Callable[[float], int]) -> tuple[Vec2I, Vec2I]:
    """Parse KLayout edge value string: '(x1,y1;x2,y2)'."""
    match = re.match(r'\(([^;]+);([^)]+)\)', value_str)
    if not match:
        raise ValueError(f"Invalid edge format: {value_str}")
    return (_parse_point(match.group(1), conv), _parse_point(match.group(2), conv))


def _parse_edge_pair(value_str: str, conv: Callable[[float], int]) -> tuple[Vec2I, Vec2I, Vec2I, Vec2I]:
    """Parse KLayout edge pair value string: '(x1,y1;x2,y2)/(x3,y3;x4,y4)' or '(x1,y1;x2,y2)|(x3,y3;x4,y4)'."""
    match = re.match(r'\(([^;]+);([^)]+)\)[/|]\(([^;]+);([^)]+)\)', value_str)
    if not match:
        raise ValueError(f"Invalid edge_pair format: {value_str}")
    return (
        _parse_point(match.group(1), conv),
        _parse_point(match.group(2), conv),
        _parse_point(match.group(3), conv),
        _parse_point(match.group(4), conv),
    )


def _parse_polygon(value_str: str, conv: Callable[[float], int]) -> list[Vec2I]:
    """Parse KLayout polygon value string: '(x1,y1;x2,y2;x3,y3;...)'."""
    match = re.match(r'\(([^)]+)\)', value_str)
    if not match:
        raise ValueError(f"Invalid polygon format: {value_str}")
    points_str = match.group(1).split(';')
    return [_parse_point(p, conv) for p in points_str]


def _parse_path(value_str: str, conv: Callable[[float], int]) -> tuple[list[Vec2I], int]:
    """Parse KLayout path value string: '(x1,y1;x2,y2;...) w=WIDTH'.

    Returns (vertices, width).
    """
    match = re.match(r'\(([^)]+)\)\s*w=([0-9.eE+-]+)', value_str)
    if not match:
        raise ValueError(f"Invalid path format: {value_str}")
    points_str = match.group(1).split(';')
    vertices = [_parse_point(p, conv) for p in points_str]
    width = conv(float(match.group(2)))
    return (vertices, width)


def _parse_text(value_str: str, conv: Callable[[float], int]) -> tuple[Vec2I, str]:
    """Parse KLayout text value string: '('TEXT' x,y)'.

    Returns (position, text).
    """
    match = re.match(r"\('([^']+)'\s+([^)]+)\)", value_str)
    if not match:
        raise ValueError(f"Invalid text format: {value_str}")
    text = match.group(1)
    pos = _parse_point(match.group(2), conv)
    return (pos, text)


def parse_rdb(filename, layout: Layout, directory: Directory = None) -> DrcReport:
    """
    Parse a KLayout XML result database file (RDB) into a DrcReport subgraph.

    Args:
        filename: Path to the .lyrdb file.
        layout: The Layout subgraph that was checked.
        directory: Optional Directory for looking up cell names to LayoutInstances.
            If not provided, DrcItem.cell will be None.

    Returns:
        DrcReport subgraph with all parsed violations.

    See also: https://www.klayout.de/rdb_format.html
    """
    tree = ET.parse(filename)
    root = tree.getroot()

    unit = layout.ref_layers.unit
    conv = lambda um: _microns_to_dbu(um, unit)

    top_cell_elem = root.find('top-cell')
    top_cell_name = top_cell_elem.text if top_cell_elem is not None else ''

    report = DrcReport(ref_layout=layout, top_cell_name=top_cell_name)
    category_by_name: dict[str, DrcCategory] = {}

    categories_elem = root.find('categories')
    if categories_elem is not None:
        for cat_elem in categories_elem.iter('category'):
            name_elem = cat_elem.find('name')
            desc_elem = cat_elem.find('description')
            name = name_elem.text if name_elem is not None else ''
            description = desc_elem.text if desc_elem is not None else ''
            cat = report % DrcCategory(name=name, description=description)
            category_by_name[name] = cat

    cells_elem = root.find('cells')
    cell_id_to_name: dict[str, str] = {}
    if cells_elem is not None:
        for cell_elem in cells_elem.iter('cell'):
            cell_id = cell_elem.attrib.get('id', '')
            name_elem = cell_elem.find('name')
            if cell_id and name_elem is not None:
                cell_id_to_name[cell_id] = name_elem.text

    items_elem = root.find('items')
    if items_elem is not None:
        for item_elem in items_elem.iter('item'):
            cat_text = item_elem.find('category').text
            cat_text = re.sub(r"(^')|('$)", "", cat_text)
            category = category_by_name.get(cat_text)
            if category is None:
                warnings.warn(f"Unknown category '{cat_text}' in RDB, skipping item")
                continue

            cell_elem = item_elem.find('cell')
            cell_ref = None
            if cell_elem is not None and directory is not None:
                cell_name = cell_elem.text
                if cell_name in cell_id_to_name:
                    cell_name = cell_id_to_name[cell_name]
                # TODO: Look up LayoutInstance from layout hierarchy

            item = report % DrcItem(category=category, cell=cell_ref)

            order = 0
            for value_elem in item_elem.iter('value'):
                value_str = value_elem.text
                if value_str is None:
                    continue
                tag = value_elem.attrib.get('tag', '')

                try:
                    if value_str.startswith('box:') or (value_str.startswith('(') and ';' in value_str and '/' not in value_str and 'w=' not in value_str and value_str.count(';') == 1):
                        value_str = value_str.replace('box:', '').strip()
                        rect = _parse_box(value_str, conv)
                        report % DrcBox(item=item, order=order, tag=tag, rect=rect)
                    elif value_str.startswith('edge:') or (value_str.startswith('(') and ';' in value_str and value_str.count(';') == 1 and '/' not in value_str):
                        value_str = value_str.replace('edge:', '').strip()
                        p1, p2 = _parse_edge(value_str, conv)
                        report % DrcEdge(item=item, order=order, tag=tag, p1=p1, p2=p2)
                    elif value_str.startswith('edge_pair:') or value_str.startswith('edge-pair:') or (('/' in value_str or '|' in value_str) and '(' in value_str):
                        value_str = value_str.replace('edge_pair:', '').replace('edge-pair:', '').strip()
                        e1p1, e1p2, e2p1, e2p2 = _parse_edge_pair(value_str, conv)
                        report % DrcEdgePair(item=item, order=order, tag=tag,
                            edge1_p1=e1p1, edge1_p2=e1p2, edge2_p1=e2p1, edge2_p2=e2p2)
                    elif value_str.startswith('polygon:') or (value_str.startswith('(') and ';' in value_str and value_str.count(';') >= 2 and 'w=' not in value_str):
                        value_str = value_str.replace('polygon:', '').strip()
                        vertices = _parse_polygon(value_str, conv)
                        poly = report % DrcPoly(item=item, order=order, tag=tag)
                        for i, v in enumerate(vertices):
                            report % PolyVec2I(ref=poly, order=i, pos=v)
                    elif value_str.startswith('path:') or 'w=' in value_str:
                        value_str = value_str.replace('path:', '').strip()
                        vertices, width = _parse_path(value_str, conv)
                        path = report % DrcPath(item=item, order=order, tag=tag, width=width)
                        for i, v in enumerate(vertices):
                            report % PolyVec2I(ref=path, order=i, pos=v)
                    elif value_str.startswith('text:') or (value_str.startswith("('") and "'" in value_str):
                        value_str = value_str.replace('text:', '').strip()
                        pos, text = _parse_text(value_str, conv)
                        report % DrcText(item=item, order=order, tag=tag, pos=pos, text=text)
                    else:
                        report % DrcValue(item=item, order=order, tag=tag, value=value_str)
                except ValueError as e:
                    warnings.warn(f"Failed to parse DRC value '{value_str}': {e}")
                    report % DrcValue(item=item, order=order, tag=tag, value=value_str)

                order += 1

    return report


class _LvsdbTransformer(Transformer):
    """Transform Lark parse tree to nested list structure."""

    def start(self, items):
        return list(items)

    @v_args(inline=True)
    def named_sexp(self, name, *children):
        return [str(name), *children]

    def anon_sexp(self, children):
        return list(children)

    def ATOM(self, token):
        return str(token)

    def NUMBER(self, token):
        return str(token)

    def QUOTED_STRING(self, token):
        return str(token)[1:-1]

    def EMPTY_PARENS(self, token):
        return "()"


_lvsdb_parser = Lark.open_from_package(
    __package__,
    "lvsdb.lark",
    parser="lalr",
)
_lvsdb_transformer = _LvsdbTransformer()


def _find_sexp(sexp: list, name: str) -> list | None:
    """Find first sub-expression starting with given name."""
    if not isinstance(sexp, list):
        return None
    for item in sexp:
        if isinstance(item, list) and len(item) > 0 and item[0] == name:
            return item
    return None


def _find_all_sexp(sexp: list, name: str):
    """Find all sub-expressions starting with given name."""
    if not isinstance(sexp, list):
        return
    for item in sexp:
        if isinstance(item, list) and len(item) > 0 and item[0] == name:
            yield item


def parse_lvsdb(filename, layout: Layout, schematic: Schematic, directory=None) -> LvsReport:
    """
    Parse a KLayout LVS database file (.lvsdb) into an LvsReport subgraph.

    The LVSDB format uses shorthand notation:
    - 'J' for layout section, 'H' for reference, 'Z' for xref
    - 'X' for circuit, 'N' for net, 'D' for device, 'P' for pin
    - 'Y' for device location, 'L' for log, 'M' for message
    - 'B' for message body text

    Args:
        filename: Path to the .lvsdb file.
        layout: The Layout subgraph that was checked.
        schematic: The Schematic subgraph that was compared against.
        directory: Optional Directory used during netlisting for name lookup.

    Returns:
        LvsReport subgraph with all parsed comparison results.
    """
    with open(filename, 'r') as f:
        text = f.read()

    tree = _lvsdb_parser.parse(text)
    sexps = _lvsdb_transformer.transform(tree)

    layout_sexp = None
    reference_sexp = None
    xref_sexp = None

    for sexp in sexps:
        if isinstance(sexp, list) and len(sexp) > 0:
            name = sexp[0]
            if name in ('layout', 'J'):
                layout_sexp = sexp
            elif name in ('reference', 'H'):
                reference_sexp = sexp
            elif name in ('xref', 'Z'):
                xref_sexp = sexp

    top_cell = ''
    unit = 0.001
    if layout_sexp:
        top_elem = _find_sexp(layout_sexp, 'top') or _find_sexp(layout_sexp, 'T')
        if top_elem and len(top_elem) > 1:
            top_cell = top_elem[1]
        unit_elem = _find_sexp(layout_sexp, 'unit') or _find_sexp(layout_sexp, 'U')
        if unit_elem and len(unit_elem) > 1:
            try:
                unit = float(unit_elem[1])
            except ValueError:
                pass

    device_locations: dict[str, dict[int, tuple]] = {}
    layout_net_names: dict[str, dict[int, str]] = {}
    layout_device_names: dict[str, dict[int, str]] = {}
    layout_pin_names: dict[str, dict[int, str]] = {}
    schem_net_names: dict[str, dict[int, str]] = {}
    schem_device_names: dict[str, dict[int, str]] = {}
    schem_pin_names: dict[str, dict[int, str]] = {}
    schem_device_params: dict[str, dict[int, dict]] = {}

    def extract_names_from_circuit(circuit_sexp, net_dict, device_dict, pin_dict,
                                    loc_dict=None, params_dict=None):
        """Extract net/device/pin names and optionally device locations/params from a circuit."""
        circuit_name = circuit_sexp[1]
        net_dict[circuit_name] = {}
        device_dict[circuit_name] = {}
        pin_dict[circuit_name] = {}
        if loc_dict is not None:
            loc_dict[circuit_name] = {}

        for net_sexp in list(_find_all_sexp(circuit_sexp, 'net')) + list(_find_all_sexp(circuit_sexp, 'N')):
            if len(net_sexp) < 2:
                continue
            try:
                net_id = int(net_sexp[1])
            except ValueError:
                continue
            name_sexp = _find_sexp(net_sexp, 'name') or _find_sexp(net_sexp, 'I')
            if name_sexp and len(name_sexp) > 1:
                net_dict[circuit_name][net_id] = str(name_sexp[1])

        for dev_sexp in list(_find_all_sexp(circuit_sexp, 'device')) + list(_find_all_sexp(circuit_sexp, 'D')):
            if len(dev_sexp) < 3:
                continue
            try:
                dev_id = int(dev_sexp[1])
            except ValueError:
                continue
            name_sexp = _find_sexp(dev_sexp, 'name') or _find_sexp(dev_sexp, 'I')
            if name_sexp and len(name_sexp) > 1:
                device_dict[circuit_name][dev_id] = str(name_sexp[1])

            # Extract parameters (E entries)
            params = {}
            for param_sexp in list(_find_all_sexp(dev_sexp, 'property')) + list(_find_all_sexp(dev_sexp, 'E')):
                if len(param_sexp) >= 2:
                    param_name = str(param_sexp[1])
                    if len(param_sexp) >= 3:
                        try:
                            params[param_name] = float(param_sexp[2])
                        except ValueError:
                            params[param_name] = str(param_sexp[2])

            if params_dict is not None:
                if circuit_name not in params_dict:
                    params_dict[circuit_name] = {}
                params_dict[circuit_name][dev_id] = params

            if loc_dict is not None:
                loc_sexp = _find_sexp(dev_sexp, 'location') or _find_sexp(dev_sexp, 'Y')
                if loc_sexp and len(loc_sexp) >= 3:
                    try:
                        x = float(loc_sexp[1])
                        y = float(loc_sexp[2])
                        loc_dict[circuit_name][dev_id] = (x, y, params)
                    except ValueError:
                        pass

        for pin_sexp in list(_find_all_sexp(circuit_sexp, 'pin')) + list(_find_all_sexp(circuit_sexp, 'P')):
            if len(pin_sexp) < 2:
                continue
            try:
                pin_id = int(pin_sexp[1])
            except ValueError:
                continue
            name_sexp = _find_sexp(pin_sexp, 'name') or _find_sexp(pin_sexp, 'I')
            if name_sexp and len(name_sexp) > 1:
                pin_dict[circuit_name][pin_id] = str(name_sexp[1])

    if layout_sexp:
        for circuit_sexp in list(_find_all_sexp(layout_sexp, 'circuit')) + list(_find_all_sexp(layout_sexp, 'X')):
            if len(circuit_sexp) < 2:
                continue
            extract_names_from_circuit(
                circuit_sexp, layout_net_names, layout_device_names,
                layout_pin_names, device_locations)

    if reference_sexp:
        for circuit_sexp in list(_find_all_sexp(reference_sexp, 'circuit')) + list(_find_all_sexp(reference_sexp, 'X')):
            if len(circuit_sexp) < 2:
                continue
            extract_names_from_circuit(
                circuit_sexp, schem_net_names, schem_device_names, schem_pin_names,
                params_dict=schem_device_params)

    overall_status = LvsStatus.Match
    circuits_data = []

    if xref_sexp:
        for circuit_xref in list(_find_all_sexp(xref_sexp, 'circuit')) + list(_find_all_sexp(xref_sexp, 'X')):
            if len(circuit_xref) < 4:
                continue

            layout_name = circuit_xref[1] if circuit_xref[1] != '()' else ''
            schem_name = circuit_xref[2] if circuit_xref[2] != '()' else ''
            status_val = circuit_xref[3]

            if status_val in ('match', '1'):
                circuit_status = LvsStatus.Match
            elif status_val in ('nomatch', 'NoMatch'):
                circuit_status = LvsStatus.NoMatch
                overall_status = LvsStatus.Mismatch
            elif status_val in ('mismatch', '0', 'X'):
                circuit_status = LvsStatus.Mismatch
                overall_status = LvsStatus.Mismatch
            else:
                circuit_status = LvsStatus.Mismatch
                overall_status = LvsStatus.Mismatch

            message = ''
            has_errors = False
            log_sexp = _find_sexp(circuit_xref, 'log') or _find_sexp(circuit_xref, 'L')
            if log_sexp:
                for entry in list(_find_all_sexp(log_sexp, 'entry')) + list(_find_all_sexp(log_sexp, 'M')):
                    if len(entry) < 2:
                        continue
                    severity = entry[1] if len(entry) > 1 else ''
                    body = _find_sexp(entry, 'description') or _find_sexp(entry, 'B')
                    if body and len(body) > 1:
                        body_text = ' '.join(str(x) for x in body[1:])
                        if message:
                            message += '; '
                        message += body_text
                        if severity == 'E':
                            has_errors = True

            if has_errors and circuit_status == LvsStatus.Match:
                circuit_status = LvsStatus.Mismatch
                overall_status = LvsStatus.Mismatch

            items_data = []
            inner_xref = _find_sexp(circuit_xref, 'xref') or _find_sexp(circuit_xref, 'Z')
            if inner_xref:
                for item_sexp in inner_xref[1:]:
                    if not isinstance(item_sexp, list) or len(item_sexp) < 4:
                        continue

                    item_type_str = item_sexp[0]
                    type_map = {
                        'net': LvsItemType.Net, 'N': LvsItemType.Net,
                        'device': LvsItemType.Device, 'D': LvsItemType.Device,
                        'pin': LvsItemType.Pin, 'P': LvsItemType.Pin,
                        'circuit': LvsItemType.Subcircuit, 'C': LvsItemType.Subcircuit,
                    }
                    if item_type_str not in type_map:
                        continue

                    layout_id_str = item_sexp[1]
                    schem_id_str = item_sexp[2]
                    item_status_val = item_sexp[3]

                    layout_id = None
                    schem_id = None
                    if layout_id_str != '()':
                        try:
                            layout_id = int(layout_id_str)
                        except ValueError:
                            pass
                    if schem_id_str != '()':
                        try:
                            schem_id = int(schem_id_str)
                        except ValueError:
                            pass

                    if item_status_val in ('match', '1'):
                        item_status = LvsStatus.Match
                    else:
                        item_status = LvsStatus.Mismatch

                    item_message = ''
                    if item_status == LvsStatus.Mismatch:
                        if item_status_val == '0':
                            item_message = 'mismatch'
                        elif item_status_val == 'W':
                            item_message = 'parameter mismatch (W)'
                        elif item_status_val == 'L':
                            item_message = 'parameter mismatch (L)'
                        elif item_status_val == 'X':
                            item_message = 'unmatched'
                        else:
                            item_message = f'mismatch ({item_status_val})'

                    item_type = type_map[item_type_str]

                    # Look up actual names based on item type
                    layout_item_name = ''
                    schem_item_name = ''
                    if item_type == LvsItemType.Net:
                        if layout_id is not None:
                            layout_item_name = layout_net_names.get(layout_name, {}).get(layout_id, '')
                        if schem_id is not None:
                            schem_item_name = schem_net_names.get(schem_name, {}).get(schem_id, '')
                    elif item_type == LvsItemType.Device:
                        if layout_id is not None:
                            layout_item_name = layout_device_names.get(layout_name, {}).get(layout_id, '')
                        if schem_id is not None:
                            schem_item_name = schem_device_names.get(schem_name, {}).get(schem_id, '')
                    elif item_type == LvsItemType.Pin:
                        # xref uses 0-based index for pins, but pin dicts are keyed by 1-based IDs
                        if layout_id is not None:
                            layout_item_name = layout_pin_names.get(layout_name, {}).get(layout_id + 1, '')
                        if schem_id is not None:
                            schem_item_name = schem_pin_names.get(schem_name, {}).get(schem_id + 1, '')

                    # Map LVSDB/SPICE names to ORDB nodes. This enables schem_nid
                    # for highlighting in schematic view when items are selected.
                    schem_nid = None
                    if directory is not None and schematic is not None:
                        spice_name = schem_item_name.lower() if schem_item_name else ''
                        if spice_name:
                            # Try direct lookup by SPICE name (case-insensitive)
                            node = None
                            try:
                                node = directory.node_of_name(schematic, spice_name)
                            except KeyError:
                                # SPICE prefixes MOSFETs with 'M' (e.g., "Mpd" for instance "pd").
                                # Try with M-prefix if direct lookup fails.
                                if item_type == LvsItemType.Device:
                                    try:
                                        node = directory.node_of_name(schematic, 'M' + spice_name)
                                    except KeyError:
                                        pass
                            if node is not None:
                                from ..core.directory import Directory
                                schem_item_name = Directory.basename_of_node(node)
                                schem_nid = node.nid

                        # For pins/nets, directory lookup may fail. Fall back to searching
                        # all Net nodes and matching by pin.full_path_str() (case-insensitive).
                        if schem_nid is None and item_type in (LvsItemType.Pin, LvsItemType.Net):
                            from ..core.schema import Net
                            pin_name = schem_item_name.lower() if schem_item_name else ''
                            for net in schematic.all(Net):
                                if net.pin is not None:
                                    if net.pin.full_path_str().lower() == pin_name:
                                        schem_nid = net.nid
                                        break

                    layout_pos = None
                    layout_params = {}
                    schem_params = {}
                    if item_type == LvsItemType.Device and layout_id is not None:
                        locs = device_locations.get(layout_name, {})
                        if layout_id in locs:
                            loc_data = locs[layout_id]
                            layout_pos = (int(loc_data[0]), int(loc_data[1]))
                            if len(loc_data) > 2:
                                layout_params = loc_data[2]

                    if item_type == LvsItemType.Device and schem_id is not None:
                        schem_params = schem_device_params.get(schem_name, {}).get(schem_id, {})

                    items_data.append({
                        'item_type': item_type,
                        'status': item_status,
                        'layout_name': layout_item_name,
                        'schem_name': schem_item_name,
                        'schem': schem_nid,
                        'layout_pos': layout_pos,
                        'message': item_message,
                        'layout_params': layout_params if layout_params else None,
                        'schem_params': schem_params if schem_params else None,
                    })

            circuits_data.append({
                'layout_name': layout_name,
                'schem_name': schem_name,
                'status': circuit_status,
                'message': message,
                'items': items_data,
            })

    report = LvsReport(
        ref_layout=layout,
        ref_schematic=schematic,
        top_cell=top_cell,
        status=overall_status,
    )

    for circuit_data in circuits_data:
        layout_name = circuit_data['layout_name']
        schem_name = circuit_data['schem_name']

        # Check if this is the top-level circuit
        is_top = (not top_cell and circuit_data is circuits_data[0]) or \
                 layout_name == top_cell or schem_name == top_cell

        # Resolve refs: top-level uses passed-in subgraphs (nids match),
        # subcircuits use directory lookup
        if is_top:
            ref_layout = layout
            ref_schematic = schematic
        elif directory is not None:
            ref_layout = None
            ref_schematic = None
            if layout_name:
                try:
                    ref_layout = directory.subgraph_of_name(layout_name, Layout)
                except KeyError:
                    pass
            if schem_name:
                try:
                    symbol = directory.subgraph_of_name(schem_name, Symbol)
                    ref_schematic = symbol.cell.schematic
                except (KeyError, AttributeError):
                    pass
        else:
            ref_layout = None
            ref_schematic = None

        circuit = report % LvsCircuitPair(
            ref_layout=ref_layout,
            ref_schematic=ref_schematic,
            layout_cell=layout_name or None,
            schem_cell=schem_name or None,
            status=circuit_data['status'],
            message=circuit_data['message'] or None,
        )

        for item_data in circuit_data['items']:
            layout_params = item_data.get('layout_params')
            if layout_params:
                layout_params = tuple(layout_params.items())
            schem_params = item_data.get('schem_params')
            if schem_params:
                schem_params = tuple(schem_params.items())
            schem_nid = item_data.get('schem') if circuit.ref_schematic else None
            report % LvsItem(
                circuit=circuit,
                item_type=item_data['item_type'],
                status=item_data['status'],
                layout_name=item_data['layout_name'],
                schem_name=item_data['schem_name'],
                schem=schem_nid,
                layout_pos=item_data.get('layout_pos'),
                layout_params=layout_params,
                schem_params=schem_params,
                message=item_data.get('message') or None,
            )

    return report
