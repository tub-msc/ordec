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
    DrcPoly, DrcPath, DrcText, DrcValue, PolyVec2I
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
    """Parse KLayout edge pair value string: '(x1,y1;x2,y2)/(x3,y3;x4,y4)'."""
    match = re.match(r'\(([^;]+);([^)]+)\)/\(([^;]+);([^)]+)\)', value_str)
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
                    elif value_str.startswith('edge_pair:') or ('/' in value_str and '(' in value_str):
                        value_str = value_str.replace('edge_pair:', '').strip()
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
