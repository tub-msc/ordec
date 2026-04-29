# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import shlex
import subprocess
import xml.etree.ElementTree as ET
import re
import warnings
from typing import Callable

from ..core import *
from ..core.schema import (
    DrcReport, DrcCategory, DrcItem, DrcBox, DrcEdge, DrcEdgePair,
    DrcPoly, DrcPath, DrcText, DrcValue, PolyVec2I,
    LvsReport, LvsCircuit, LvsItem, LvsStatus, LvsItemType
)


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


class _LvsdbTokenizer:
    """Simple tokenizer for LVSDB S-expression format."""

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.len = len(text)

    def _skip_whitespace_and_comments(self):
        while self.pos < self.len:
            c = self.text[self.pos]
            if c in ' \t\n\r':
                self.pos += 1
            elif c == '#':
                while self.pos < self.len and self.text[self.pos] != '\n':
                    self.pos += 1
            else:
                break

    def peek(self) -> str | None:
        self._skip_whitespace_and_comments()
        if self.pos >= self.len:
            return None
        return self.text[self.pos]

    def next_token(self) -> str | None:
        self._skip_whitespace_and_comments()
        if self.pos >= self.len:
            return None

        c = self.text[self.pos]

        if c in '()':
            self.pos += 1
            return c

        if c == "'":
            end = self.text.find("'", self.pos + 1)
            if end < 0:
                end = self.len
            token = self.text[self.pos + 1:end]
            self.pos = end + 1
            return token

        start = self.pos
        while self.pos < self.len and self.text[self.pos] not in ' \t\n\r()#':
            self.pos += 1
        return self.text[start:self.pos]


def _parse_lvsdb_sexp(tokenizer: _LvsdbTokenizer) -> list | str | None:
    """Parse an S-expression from the tokenizer.

    Handles both 'name(...)' and '(...)' styles:
    - 'J(...)' is parsed as ['J', ...contents...]
    - '(...)' is parsed as [...contents...]
    """
    token = tokenizer.next_token()
    if token is None:
        return None
    if token == '(':
        result = []
        while True:
            if tokenizer.peek() == ')':
                tokenizer.next_token()
                break
            item = _parse_lvsdb_sexp(tokenizer)
            if item is None:
                break
            result.append(item)
        return result
    elif token == ')':
        return None
    else:
        if tokenizer.peek() == '(':
            tokenizer.next_token()
            result = [token]
            while True:
                if tokenizer.peek() == ')':
                    tokenizer.next_token()
                    break
                item = _parse_lvsdb_sexp(tokenizer)
                if item is None:
                    break
                result.append(item)
            return result
        return token


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


def parse_lvsdb(filename, layout: Layout, schematic: Schematic) -> LvsReport:
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

    Returns:
        LvsReport subgraph with all parsed comparison results.
    """
    with open(filename, 'r') as f:
        text = f.read()

    tokenizer = _LvsdbTokenizer(text)

    layout_sexp = None
    reference_sexp = None
    xref_sexp = None

    while True:
        sexp = _parse_lvsdb_sexp(tokenizer)
        if sexp is None:
            break
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
    schem_device_names: dict[str, dict[int, str]] = {}

    if reference_sexp:
        for circuit_sexp in list(_find_all_sexp(reference_sexp, 'circuit')) + list(_find_all_sexp(reference_sexp, 'X')):
            if len(circuit_sexp) < 2:
                continue
            circuit_name = circuit_sexp[1]
            schem_device_names[circuit_name] = {}

            for dev_sexp in list(_find_all_sexp(circuit_sexp, 'device')) + list(_find_all_sexp(circuit_sexp, 'D')):
                if len(dev_sexp) < 3:
                    continue
                try:
                    dev_id = int(dev_sexp[1])
                except ValueError:
                    continue

                name_sexp = _find_sexp(dev_sexp, 'name') or _find_sexp(dev_sexp, 'I')
                if name_sexp and len(name_sexp) > 1:
                    schem_device_names[circuit_name][dev_id] = str(name_sexp[1]).lower()

    if layout_sexp:
        for circuit_sexp in list(_find_all_sexp(layout_sexp, 'circuit')) + list(_find_all_sexp(layout_sexp, 'X')):
            if len(circuit_sexp) < 2:
                continue
            circuit_name = circuit_sexp[1]
            device_locations[circuit_name] = {}

            for dev_sexp in list(_find_all_sexp(circuit_sexp, 'device')) + list(_find_all_sexp(circuit_sexp, 'D')):
                if len(dev_sexp) < 3:
                    continue
                try:
                    dev_id = int(dev_sexp[1])
                except ValueError:
                    continue

                loc_sexp = _find_sexp(dev_sexp, 'location') or _find_sexp(dev_sexp, 'Y')
                if loc_sexp and len(loc_sexp) >= 3:
                    try:
                        x = float(loc_sexp[1])
                        y = float(loc_sexp[2])
                        device_locations[circuit_name][dev_id] = (x, y)
                    except ValueError:
                        pass

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

                    layout_shapes = None
                    schem_path = None
                    if item_type == LvsItemType.Device and layout_id is not None:
                        locs = device_locations.get(layout_name, {})
                        if layout_id in locs:
                            x, y = locs[layout_id]
                            size = 500
                            layout_shapes = (
                                ('box', (x - size, y - size, x + size, y + size)),
                            )

                    if item_type == LvsItemType.Device and schem_id is not None:
                        dev_names = schem_device_names.get(schem_name, {})
                        if schem_id in dev_names:
                            schem_path = (dev_names[schem_id],)

                    items_data.append({
                        'item_type': item_type,
                        'status': item_status,
                        'layout_id': layout_id,
                        'schem_id': schem_id,
                        'layout_shapes': layout_shapes,
                        'schem_path': schem_path,
                        'message': item_message,
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
        circuit = report % LvsCircuit(
            layout_name=circuit_data['layout_name'],
            schem_name=circuit_data['schem_name'],
            status=circuit_data['status'],
            message=circuit_data['message'],
        )

        for item_data in circuit_data['items']:
            report % LvsItem(
                circuit=circuit,
                item_type=item_data['item_type'],
                status=item_data['status'],
                layout_name=str(item_data['layout_id']) if item_data['layout_id'] else '',
                schem_name=str(item_data['schem_id']) if item_data['schem_id'] else '',
                layout_shapes=item_data['layout_shapes'],
                schem_path=item_data.get('schem_path'),
                message=item_data.get('message', ''),
            )

    return report
