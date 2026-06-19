# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import logging
import shlex
import subprocess
import xml.etree.ElementTree as ET
import re
import warnings

from lark import Lark, Transformer, v_args

from ..core import *

logger = logging.getLogger(__name__)


def run(script, cwd, **kwargs):
    """
    Run KLayout script 'script' in directory 'cwd' with provided keyword args.
    """
    cmdline = ['klayout', '-b', '-r', str(script)]
    for k, v in kwargs.items():
        cmdline += ['-rd', f'{k}={v}']
    logger.debug("%s %s", cwd, shlex.join(cmdline))
    subprocess.check_call(cmdline, cwd=cwd)


def unquote(tok) -> str:
    s = str(tok)
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1]
    return s


class RdbValueTransformer(Transformer):
    """Transform a parsed RDB value into a (tag, kind, payload) tuple, where
    coordinates are raw (x, y) micron float pairs. Conversion to dbu and ORDB
    node creation happen in parse_rdb, since the dbu scale is per-report.

    tag is the bracketed value tag ('' if none). Payloads by kind:
        box, edge:    [point, point]
        edge_pair:    [point, point, point, point]
        polygon:      [ring, ...] where ring is a list of points (ring[0] is
                          the outer hull, the rest are holes)
        path:         (ring, attrs) where attrs maps attribute name -> str
                          (KLayout writes 'w', 'bx', 'ex', 'r')
        label:        (text, point) for positioned text
        value:        the raw scalar string (text:/float:/int: value)
    """

    @v_args(inline=True)
    def point(self, x, y):
        return (float(x), float(y))

    def ring(self, points):
        return list(points)

    @v_args(inline=True)
    def edge_geom(self, p1, p2):
        return (p1, p2)

    @v_args(inline=True)
    def tag(self, name):
        return unquote(name)

    @v_args(inline=True)
    def tag_name(self, tok):
        return tok

    def start(self, items):
        if len(items) == 2:
            tag, (kind, payload) = items
        else:
            tag, (kind, payload) = '', items[0]
        return (tag, kind, payload)

    def box(self, points):
        return ('box', points)

    def edge(self, points):
        return ('edge', points)

    @v_args(inline=True)
    def edge_pair(self, g1, g2):
        return ('edge_pair', [g1[0], g1[1], g2[0], g2[1]])

    def polygon(self, rings):
        return ('polygon', list(rings))

    def path(self, children):
        ring, *attrs = children
        return ('path', (ring, dict(attrs)))

    @v_args(inline=True)
    def trans(self, *children):
        # children is (ROTCODE, point) or (point,); we keep only the
        # displacement, since DrcText has no rotation.
        return children[-1]

    @v_args(inline=True)
    def attr(self, tok):
        key, value = str(tok).split('=', 1)
        return (key, value)

    @v_args(inline=True)
    def label(self, quoted, pos, *attrs):
        return ('label', (unquote(quoted), pos))

    @v_args(inline=True)
    def text(self, tok):
        return ('value', unquote(tok))

    @v_args(inline=True)
    def number_value(self, num):
        return ('value', str(num))


rdb_value_parser = Lark.open_from_package(
    __package__,
    "rdb_value.lark",
    parser="lalr",
)


def parse_rdb_value(value_str: str):
    """Parse an RDB <value> string into a (tag, kind, payload) tuple.

    The grammar covers the full value space accepted by KLayout's own reader;
    see RdbValueTransformer for the payload shape of each kind. Raises LarkError
    if the string is not a valid RDB value.
    """
    return RdbValueTransformer().transform(rdb_value_parser.parse(value_str))


def parse_rdb_categories(root, report: DrcReport) -> dict:
    """
    Read the <categories> section of an RDB, creating DrcCategory nodes for
    categories not yet present in the report. Returns name -> DrcCategory.
    """
    category_by_name = {cat.name: cat for cat in report.all(DrcCategory)}

    categories_elem = root.find('categories')
    if categories_elem is not None:
        for cat_elem in categories_elem.iter('category'):
            name_elem = cat_elem.find('name')
            desc_elem = cat_elem.find('description')
            name = name_elem.text if name_elem is not None else ''
            description = desc_elem.text if desc_elem is not None else ''
            if name not in category_by_name:
                cat = report % DrcCategory(name=name, description=description)
                category_by_name[name] = cat

    return category_by_name


def insert_drc_value(report: DrcReport, item, order: int, value_str: str, conv):
    """
    Parse one RDB <value> string and insert it as the matching DRC geometry
    node (DrcBox/DrcEdge/DrcEdgePair/DrcPoly/DrcPath/DrcText/DrcValue).
    """
    pt = lambda p: Vec2I(conv(p[0]), conv(p[1]))
    tag, kind, payload = parse_rdb_value(value_str)

    if kind == 'box':
        p1, p2 = pt(payload[0]), pt(payload[1])
        rect = Rect4I(min(p1.x, p2.x), min(p1.y, p2.y),
            max(p1.x, p2.x), max(p1.y, p2.y))
        report % DrcBox(item=item, order=order, tag=tag, rect=rect)
    elif kind == 'edge':
        p1, p2 = pt(payload[0]), pt(payload[1])
        report % DrcEdge(item=item, order=order, tag=tag, p1=p1, p2=p2)
    elif kind == 'edge_pair':
        e1p1, e1p2, e2p1, e2p2 = [pt(p) for p in payload]
        report % DrcEdgePair(item=item, order=order, tag=tag,
            edge1_p1=e1p1, edge1_p2=e1p2, edge2_p1=e2p1, edge2_p2=e2p2)
    elif kind == 'polygon':
        rings = payload
        if len(rings) > 1:
            raise NotImplementedError(
                f"DRC polygon with holes is not supported: {value_str!r}")
        poly = report % DrcPoly(item=item, order=order, tag=tag)
        for i, p in enumerate(rings[0]):
            report % PolyVec2I(ref=poly, order=i, pos=pt(p))
    elif kind == 'path':
        ring, attrs = payload
        # KLayout always writes w=, bx=, ex=, r=. The DRC schema
        # stores only the width, so reject begin/end extensions and
        # rounded paths rather than dropping them silently.
        if float(attrs.get('bx', 0)) != 0 or float(attrs.get('ex', 0)) != 0:
            raise NotImplementedError(
                f"DRC path with begin/end extension not supported: {value_str!r}")
        if attrs.get('r', 'false') == 'true':
            raise NotImplementedError(
                f"DRC rounded path not supported: {value_str!r}")
        if 'w' not in attrs:
            raise ValueError(f"DRC path without width: {value_str!r}")
        path = report % DrcPath(item=item, order=order, tag=tag,
            width=conv(float(attrs['w'])))
        for i, p in enumerate(ring):
            report % PolyVec2I(ref=path, order=i, pos=pt(p))
    elif kind == 'label':
        text, pos = payload
        report % DrcText(item=item, order=order, tag=tag,
            pos=pt(pos), text=text)
    else:  # kind == 'value'
        report % DrcValue(item=item, order=order, tag=tag, value=payload)


def parse_rdb(filename, report: DrcReport, directory: Directory = None):
    """
    Parse a KLayout XML result database file (RDB), appending the parsed
    violations into the given DrcReport subgraph.

    Args:
        filename: Path to the .lyrdb file.
        report: Existing DrcReport to append parsed violations into. The checked
            Layout is taken from report.ref_layout.
        directory: Optional Directory for looking up cell names to LayoutInstances.
            If not provided, DrcItem.cell will be None.

    RDB format documentation: https://www.klayout.de/rdb_format.html
    """
    tree = ET.parse(filename)
    root = tree.getroot()

    unit = report.ref_layout.ref_layers.unit
    dbu_per_um = R('1u') / unit

    def conv(value_um: float) -> int:
        """Convert a micron value to database units."""
        return int(round(float(value_um * dbu_per_um)))

    category_by_name = parse_rdb_categories(root, report)

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
                insert_drc_value(report, item, order, value_str, conv)
                order += 1


class LvsdbTransformer(Transformer):
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


lvsdb_parser = Lark.open_from_package(
    __package__,
    "lvsdb.lark",
    parser="lalr",
)
lvsdb_transformer = LvsdbTransformer()


def find_sexp(sexp: list, name: str) -> list | None:
    """Find first sub-expression starting with given name."""
    if not isinstance(sexp, list):
        return None
    for item in sexp:
        if isinstance(item, list) and len(item) > 0 and item[0] == name:
            return item
    return None


def find_all_sexp(sexp: list, name: str):
    """Find all sub-expressions starting with given name."""
    if not isinstance(sexp, list):
        return
    for item in sexp:
        if isinstance(item, list) and len(item) > 0 and item[0] == name:
            yield item


def find_sexp_lk(sexp: list, long_key: str, short_key: str) -> list | None:
    """Find first sub-expression by its long or short key."""
    return find_sexp(sexp, long_key) or find_sexp(sexp, short_key)


def find_all_sexp_lk(sexp: list, long_key: str, short_key: str) -> list:
    """Find all sub-expressions by their long or short key."""
    return list(find_all_sexp(sexp, long_key)) + list(find_all_sexp(sexp, short_key))


def sexp_name(sexp: list) -> str | None:
    """Return the name ('I' entry) of a net/device/pin/subcircuit, if any."""
    name_sexp = find_sexp_lk(sexp, 'name', 'I')
    if name_sexp and len(name_sexp) > 1:
        return str(name_sexp[1])
    return None


def parse_optional_int(s: str) -> int | None:
    """Parse a numeric LVSDB id; absent values are written as '()'."""
    if s == '()':
        return None
    try:
        return int(s)
    except ValueError:
        return None


class NetlistNames:
    """
    Object names of one LVSDB netlist section ('layout' or 'reference'),
    keyed by circuit name, then by numeric object id. Device parameters
    ('E' entries) and device locations ('Y' entries, layout section) are
    collected along the way.
    """
    def __init__(self):
        self.nets = {}
        self.devices = {}
        self.pins = {}
        self.subckts = {}
        self.device_locations = {}
        self.device_params = {}

    def of_item_type(self, item_type: LvsItemType) -> dict:
        return {
            LvsItemType.Net: self.nets,
            LvsItemType.Device: self.devices,
            LvsItemType.Pin: self.pins,
            LvsItemType.Subcircuit: self.subckts,
        }[item_type]

    def lookup(self, item_type: LvsItemType, circuit_name: str, obj_id: int) -> str:
        """Name of an object referenced by an xref item ('' if unnamed)."""
        if item_type == LvsItemType.Pin:
            # xref item ids are 0-based for pins, but pin definitions in the
            # netlist sections use 1-based ids.
            obj_id += 1
        return self.of_item_type(item_type).get(circuit_name, {}).get(obj_id, '')


def parse_netlist_circuit(circuit_sexp, names: NetlistNames, collect_locations: bool):
    """Extract one circuit of a netlist section into names."""
    circuit_name = circuit_sexp[1]
    nets = names.nets[circuit_name] = {}
    devices = names.devices[circuit_name] = {}
    pins = names.pins[circuit_name] = {}
    subckts = names.subckts[circuit_name] = {}
    locations = names.device_locations[circuit_name] = {}
    params = names.device_params[circuit_name] = {}

    for net_sexp in find_all_sexp_lk(circuit_sexp, 'net', 'N'):
        if len(net_sexp) < 2:
            continue
        net_id = parse_optional_int(net_sexp[1])
        name = sexp_name(net_sexp)
        if net_id is not None and name is not None:
            nets[net_id] = name

    for dev_sexp in find_all_sexp_lk(circuit_sexp, 'device', 'D'):
        if len(dev_sexp) < 3:
            continue
        dev_id = parse_optional_int(dev_sexp[1])
        if dev_id is None:
            continue
        name = sexp_name(dev_sexp)
        if name is not None:
            devices[dev_id] = name

        dev_params = params[dev_id] = {}
        for param_sexp in find_all_sexp_lk(dev_sexp, 'param', 'E'):
            if len(param_sexp) >= 3:
                try:
                    dev_params[str(param_sexp[1])] = float(param_sexp[2])
                except ValueError:
                    dev_params[str(param_sexp[1])] = str(param_sexp[2])

        if collect_locations:
            loc_sexp = find_sexp_lk(dev_sexp, 'location', 'Y')
            if loc_sexp and len(loc_sexp) >= 3:
                try:
                    locations[dev_id] = (float(loc_sexp[1]), float(loc_sexp[2]))
                except ValueError:
                    pass

    for pin_sexp in find_all_sexp_lk(circuit_sexp, 'pin', 'P'):
        if len(pin_sexp) < 2:
            continue
        pin_id = parse_optional_int(pin_sexp[1])
        name = sexp_name(pin_sexp)
        if pin_id is not None and name is not None:
            pins[pin_id] = name

    # Subcircuit instances: 'X' in short form, like circuits themselves,
    # but with a numeric id as first element.
    for sub_sexp in find_all_sexp_lk(circuit_sexp, 'subcircuit', 'X'):
        if len(sub_sexp) < 3:
            continue
        sub_id = parse_optional_int(sub_sexp[1])
        name = sexp_name(sub_sexp)
        if sub_id is not None and name is not None:
            subckts[sub_id] = name


def parse_netlist_section(section_sexp, collect_locations: bool = False) -> NetlistNames:
    """Extract all circuits of the 'layout' or 'reference' section."""
    names = NetlistNames()
    if section_sexp:
        for circuit_sexp in find_all_sexp_lk(section_sexp, 'circuit', 'X'):
            if len(circuit_sexp) < 2:
                continue
            parse_netlist_circuit(circuit_sexp, names, collect_locations)
    return names


def parse_lvsdb_top_cell(layout_sexp) -> str:
    """Top cell name from the layout section ('' if absent)."""
    if layout_sexp:
        top_elem = find_sexp_lk(layout_sexp, 'top', 'W')
        if top_elem and len(top_elem) > 1:
            return top_elem[1]
    return ''


# Status tokens follow dbLayoutVsSchematicFormatDefs.h: '1' match,
# '0' mismatch (paired, but comparison failed), 'X' nomatch (no
# counterpart), 'W' match-with-warning, 'S' skipped. See the status table
# in the parse_lvsdb docstring.

def parse_circuit_status(status_val: str) -> LvsStatus:
    """Map an LVSDB circuit pair status token to LvsStatus."""
    if status_val in ('match', '1'):
        return LvsStatus.Match
    elif status_val in ('warning', 'W'):
        return LvsStatus.MatchWarning
    elif status_val in ('nomatch', 'NoMatch', 'X'):
        return LvsStatus.NoMatch
    elif status_val in ('skipped', 'S'):
        return LvsStatus.Skipped
    else:  # 'mismatch', '0' and anything unexpected
        return LvsStatus.Mismatch


def parse_item_status(item_type: LvsItemType, status_val: str) -> tuple:
    """
    Map an LVSDB item status token to (LvsStatus, message). For devices,
    'W' means the device matched topologically but its parameters deviate
    (an LVS error, reflected in the circuit status); for nets/pins/
    subcircuits, 'W' flags an ambiguous match (e.g. between topologically
    symmetric nets), which is harmless.
    """
    if status_val in ('match', '1'):
        return LvsStatus.Match, ''
    elif status_val in ('warning', 'W'):
        if item_type == LvsItemType.Device:
            return LvsStatus.MatchWarning, 'parameter mismatch'
        else:
            return LvsStatus.MatchWarning, 'ambiguous match'
    elif status_val in ('nomatch', 'X'):
        return LvsStatus.NoMatch, 'unmatched'
    elif status_val in ('skipped', 'S'):
        return LvsStatus.Skipped, ''
    elif status_val in ('mismatch', '0'):
        return LvsStatus.Mismatch, 'mismatch'
    else:
        return LvsStatus.Mismatch, f'mismatch ({status_val})'


def parse_xref_log(circuit_xref) -> tuple:
    """
    Concatenate the log messages of a circuit pair xref. Returns
    (message, has_errors), where has_errors reports entries of severity 'E'.
    """
    message = ''
    has_errors = False
    log_sexp = find_sexp_lk(circuit_xref, 'log', 'L')
    if log_sexp:
        for entry in find_all_sexp_lk(log_sexp, 'entry', 'M'):
            if len(entry) < 2:
                continue
            severity = entry[1]
            body = find_sexp_lk(entry, 'description', 'B')
            if body and len(body) > 1:
                body_text = ' '.join(str(x) for x in body[1:])
                if message:
                    message += '; '
                message += body_text
                if severity == 'E':
                    has_errors = True
    return message, has_errors


XREF_ITEM_TYPES = {
    'net': LvsItemType.Net, 'N': LvsItemType.Net,
    'device': LvsItemType.Device, 'D': LvsItemType.Device,
    'pin': LvsItemType.Pin, 'P': LvsItemType.Pin,
    'circuit': LvsItemType.Subcircuit, 'C': LvsItemType.Subcircuit,
    'subcircuit': LvsItemType.Subcircuit, 'X': LvsItemType.Subcircuit,
}


def parse_xref_item(item_sexp, layout_circuit: str, schem_circuit: str,
                     layout_names: NetlistNames, schem_names: NetlistNames) -> dict | None:
    """
    Parse one item xref (net/device/pin/subcircuit comparison) of a circuit
    pair into a dict, resolving the object names against the netlist
    sections. Returns None if item_sexp is not an item xref.
    """
    if not isinstance(item_sexp, list) or len(item_sexp) < 4:
        return None
    item_type = XREF_ITEM_TYPES.get(item_sexp[0])
    if item_type is None:
        return None

    layout_id = parse_optional_int(item_sexp[1])
    schem_id = parse_optional_int(item_sexp[2])
    status, message = parse_item_status(item_type, item_sexp[3])

    layout_item_name = ''
    schem_item_name = ''
    if layout_id is not None:
        layout_item_name = layout_names.lookup(item_type, layout_circuit, layout_id)
    if schem_id is not None:
        schem_item_name = schem_names.lookup(item_type, schem_circuit, schem_id)
    # Note: schem_item_name is mapped to an ORDB node later (when
    # constructing the LvsItems), because the node must be resolved against
    # the schematic of this circuit pair, which is only determined there.

    layout_pos = None
    layout_params = {}
    schem_params = {}
    if item_type == LvsItemType.Device:
        if layout_id is not None:
            loc = layout_names.device_locations.get(layout_circuit, {}).get(layout_id)
            if loc is not None:
                layout_pos = (int(loc[0]), int(loc[1]))
            layout_params = layout_names.device_params.get(layout_circuit, {}).get(layout_id, {})
        if schem_id is not None:
            schem_params = schem_names.device_params.get(schem_circuit, {}).get(schem_id, {})

    return {
        'item_type': item_type,
        'status': status,
        'layout_name': layout_item_name,
        'schem_name': schem_item_name,
        'layout_pos': layout_pos,
        'message': message,
        'layout_params': layout_params if layout_params else None,
        'schem_params': schem_params if schem_params else None,
    }


def parse_circuit_xref(circuit_xref, layout_names: NetlistNames,
                        schem_names: NetlistNames) -> dict | None:
    """
    Parse one circuit pair of the xref section (names, status, message log
    and item xrefs) into a dict. Returns None if circuit_xref is malformed.
    """
    if len(circuit_xref) < 4:
        return None

    layout_name = circuit_xref[1] if circuit_xref[1] != '()' else ''
    schem_name = circuit_xref[2] if circuit_xref[2] != '()' else ''
    status = parse_circuit_status(circuit_xref[3])

    message, has_errors = parse_xref_log(circuit_xref)
    if has_errors and status in (LvsStatus.Match, LvsStatus.MatchWarning):
        status = LvsStatus.Mismatch

    items = []
    inner_xref = find_sexp_lk(circuit_xref, 'xref', 'Z')
    if inner_xref:
        for item_sexp in inner_xref[1:]:
            item = parse_xref_item(item_sexp, layout_name, schem_name,
                                    layout_names, schem_names)
            if item is not None:
                items.append(item)

    return {
        'layout_name': layout_name,
        'schem_name': schem_name,
        'status': status,
        'message': message,
        'items': items,
    }


# Netlister name prefixes by item type, used to map SPICE names back to
# ORDB nodes (e.g. "Mpd" for MOSFET instance "pd", "Rr1" for resistor
# instance "r1", "xa1" for subcircuit instance "a1").
SCHEM_NODE_PREFIXES = {
    LvsItemType.Device: ('', 'M', 'R', 'C'),
    LvsItemType.Subcircuit: ('', 'x', 'X'),
    LvsItemType.Net: ('',),
    LvsItemType.Pin: ('',),
}


def resolve_schem_node(directory, ref_schematic, item_type: LvsItemType,
                        schem_item_name: str):
    """Map a SPICE name from the LVSDB to a node of ref_schematic."""
    spice_name = schem_item_name.lower() if schem_item_name else ''
    if not spice_name:
        return None
    for prefix in SCHEM_NODE_PREFIXES[item_type]:
        try:
            return directory.node_of_name(ref_schematic, prefix + spice_name)
        except KeyError:
            pass
    # For pins/nets, directory lookup may fail. Fall back to searching
    # all Net nodes and matching by pin.full_path_str() (case-insensitive).
    if item_type in (LvsItemType.Pin, LvsItemType.Net):
        for net in ref_schematic.all(Net):
            if net.pin is not None:
                if net.pin.full_path_str().lower() == spice_name:
                    return net
    return None


def resolve_pair_refs(directory, layout, schematic, layout_name: str,
                       schem_name: str, is_top: bool) -> tuple:
    """
    Resolve the Layout/Schematic subgraphs compared in a circuit pair:
    top-level pairs use the subgraphs passed to parse_lvsdb (nids match),
    subcircuit pairs are looked up in the directory. Directory names are
    lowercase, while the LVSDB may report SPICE names in uppercase.
    """
    if is_top:
        return layout, schematic

    ref_layout = None
    ref_schematic = None
    if directory is not None:
        if layout_name:
            try:
                ref_layout = directory.subgraph_of_name(layout_name.lower(), Layout)
            except KeyError:
                pass
        if schem_name:
            try:
                symbol = directory.subgraph_of_name(schem_name.lower(), Symbol)
                ref_schematic = symbol.cell.schematic
            except (KeyError, AttributeError):
                pass
    return ref_layout, ref_schematic


def insert_lvs_item(report: LvsReport, circuit, item_data: dict,
                     directory, ref_schematic):
    """
    Insert one LvsItem for a circuit pair, mapping its LVSDB/SPICE name to
    an ORDB node of the pair's schematic where possible. This enables e.g.
    highlighting in the schematic view when items are selected.
    """
    layout_params = item_data['layout_params']
    if layout_params:
        layout_params = tuple(layout_params.items())
    schem_params = item_data['schem_params']
    if schem_params:
        schem_params = tuple(schem_params.items())

    schem_nid = None
    schem_item_name = item_data['schem_name']
    if directory is not None and ref_schematic is not None:
        node = resolve_schem_node(directory, ref_schematic,
                                   item_data['item_type'], schem_item_name)
        if node is not None:
            schem_item_name = Directory.basename_of_node(node)
            schem_nid = node.nid

    report % LvsItem(
        circuit=circuit,
        item_type=item_data['item_type'],
        status=item_data['status'],
        layout_name=item_data['layout_name'],
        schem_name=schem_item_name,
        schem=schem_nid,
        layout_pos=item_data['layout_pos'],
        layout_params=layout_params,
        schem_params=schem_params,
        message=item_data['message'] or None,
    )


def parse_lvsdb(filename, layout: Layout, schematic: Schematic, directory=None) -> LvsReport:
    """
    Parse a KLayout LVS database file (.lvsdb) into an LvsReport subgraph.

    Args:
        filename: Path to the .lvsdb file.
        layout: The Layout subgraph that was checked. Becomes ref_layout of
            the report and of the top-level LvsCircuitPair. May be None.
        schematic: The Schematic subgraph that was compared against. Becomes
            ref_schematic analogously. May be None.
        directory: Optional Directory used during netlisting and GDS export.
            If given, it is used to resolve subcircuit pairs to their
            Layout/Schematic subgraphs and item names to ORDB nodes; without
            it, only the raw LVSDB names are reported.

    Returns:
        LvsReport subgraph with all parsed comparison results.

    **LVSDB format.** The format is only documented in the KLayout sources,
    of which this repository keeps a copy:

    - ``experiments/klayout/src/db/db/dbLayoutVsSchematicFormatDefs.h``
      defines the LVSDB top level,
    - ``experiments/klayout/src/db/db/dbLayoutToNetlistFormatDefs.h``
      defines the embedded netlist sections (shared with L2N databases).

    An LVSDB file is a tree of parenthesized s-expressions. Every element
    type has a long and a short key (e.g. ``circuit`` and ``X``); KLayout
    writes short keys, this parser accepts both. After the magic line
    ``#%lvsdb-klayout``, the file has three top-level sections::

        J(...)   layout:    netlist extracted from the GDS
        H(...)   reference: netlist read from the SPICE file
        Z(...)   xref:      comparison results (pairing + status)

    Keys relevant to this parser (long form in parentheses):

    ========= ============================================================
    Key       Meaning
    ========= ============================================================
    ``W``     (top) top cell name, in the layout/reference sections
    ``U``     (unit) database unit in µm
    ``X``     (circuit) circuit; *inside* a circuit, ``X`` with a numeric
              first element is a subcircuit instance
    ``N``     (net) net definition: id, then optional ``I`` and geometry
    ``P``     (pin) pin definition: id, then optional ``I``
    ``D``     (device) device: id, device class, then ``I``/``E``/``Y``
    ``I``     (name) name of the enclosing net/device/pin/subcircuit
    ``E``     (param) device parameter, e.g. ``E(l 0.5)``
    ``Y``     (location) device/instance location in database units
    ``L``     in the xref section: (log) message log of a circuit pair;
              in the netlist sections: (layer) layer definition!
    ``M``     (entry) one log message inside ``L(...)``
    ``B``     (description) message text inside ``M(...)``
    ========= ============================================================

    Pitfalls:

    - Short keys are context-dependent: ``H`` is the reference section at
      the top level but a message inside netlist sections, ``J`` is the
      layout section at the top level but a text label in net geometry,
      ``X`` may be a circuit, a subcircuit instance or the *nomatch*
      status, and ``L`` is a log in the xref section but a layer in the
      netlist sections.
    - Absent values (unpaired ids, missing names) are written as ``()``.
    - In xref items, pin ids are 0-based, while pin *definitions* in the
      netlist sections use 1-based ids.
    - In the layout section, devices and subcircuit instances are usually
      unnamed (GDS structure references carry no instance names) and only
      identified by their location (``Y``). In the reference section,
      names come from the SPICE netlist and are upper-cased.

    Status codes (used for circuit pairs and xref items alike):

    ======= ============ ==================================================
    Code    Long form    Meaning
    ======= ============ ==================================================
    ``1``   match        objects were paired and compare clean
    ``0``   mismatch     objects were paired, but their comparison failed
    ``X``   nomatch      no counterpart found on the other side
    ``W``   warning      matched with warning: for devices, parameters
                         deviate (an LVS error); for nets, pins and
                         subcircuits, the match was ambiguous (harmless)
    ``S``   skipped      comparison skipped
    ======= ============ ==================================================

    Annotated example (shortened, from a hierarchical resistor design)::

        #%lvsdb-klayout
        J(                        # layout netlist (extracted from GDS)
         W(c_hier)                # top cell
         U(0.001)                 # database unit in µm
         L(l6 '6/0')              # layer definition ("L" = layer here!)
         X(a_default              # circuit = extracted cell "a_default"
          N(1 I(x)                # net 1, named "x", with geometry:
           R(l6 (70 3620) (360 160))  # rect on layer l6
           J(l26 x (-180 -80))        # text label ("J" = text here!)
          )
          P(1 I(x))               # pin 1, named "x"
          D(1 D$rsil$1            # device 1 of device class "D$rsil$1",
           Y(-5 2995)             # unnamed, at location (-5, 2995)
           E(w 0.5) E(l 0.5)      # device parameters
           T(rsil_1 5)            # terminal "rsil_1" connects to net 5
          )
          X(1 a_default Y(0 0)    # subcircuit instance 1 of "a_default"
           P(0 4)                 # instance pin 0 connects to net 4
          )
         )
        )
        H(                        # reference netlist (from SPICE)
         X(A_DEFAULT              # names are upper-cased SPICE names
          N(1 I(X))
          D(1 RSIL I(R1) ...)     # devices/subcircuits are named here
          X(1 A_DEFAULT I(A1) ...)
         )
        )
        Z(                        # comparison results
         X(a_default A_DEFAULT 1  # circuit pair: layout circuit,
          Z(                      # reference circuit, status
           N(5 5 1)               # item xref: layout id, reference id,
           P(0 0 1)               # status (pin ids 0-based here!)
           D(3 1 1)
           X(1 1 1)
          )
         )
        )

    A real specimen of this format is kept at ``tests/lvsdb/c_hier.lvsdb``;
    ``tests/test_parse_lvsdb.py`` parses it to pin down this parser's
    behavior independently of KLayout.
    """
    with open(filename, 'r') as f:
        text = f.read()

    sexps = lvsdb_transformer.transform(lvsdb_parser.parse(text))

    layout_sexp = None
    reference_sexp = None
    xref_sexp = None
    for sexp in sexps:
        if isinstance(sexp, list) and len(sexp) > 0:
            if sexp[0] in ('layout', 'J'):
                layout_sexp = sexp
            elif sexp[0] in ('reference', 'H'):
                reference_sexp = sexp
            elif sexp[0] in ('xref', 'Z'):
                xref_sexp = sexp

    top_cell = parse_lvsdb_top_cell(layout_sexp)
    layout_names = parse_netlist_section(layout_sexp, collect_locations=True)
    schem_names = parse_netlist_section(reference_sexp)

    circuits_data = []
    if xref_sexp:
        for circuit_xref in find_all_sexp_lk(xref_sexp, 'circuit', 'X'):
            circuit_data = parse_circuit_xref(circuit_xref, layout_names, schem_names)
            if circuit_data is not None:
                circuits_data.append(circuit_data)

    if all(c['status'] in (LvsStatus.Match, LvsStatus.MatchWarning)
           for c in circuits_data):
        overall_status = LvsStatus.Match
    else:
        overall_status = LvsStatus.Mismatch

    report = LvsReport(
        ref_layout=layout,
        ref_schematic=schematic,
        top_cell=top_cell,
        status=overall_status,
    )

    for circuit_data in circuits_data:
        layout_name = circuit_data['layout_name']
        schem_name = circuit_data['schem_name']

        # Check if this is the top-level circuit. If the LVSDB lacks a top
        # cell entry, fall back to the last circuit pair (the LVSDB lists
        # circuits bottom-up).
        is_top = (not top_cell and circuit_data is circuits_data[-1]) or \
                 layout_name == top_cell or schem_name == top_cell

        ref_layout, ref_schematic = resolve_pair_refs(
            directory, layout, schematic, layout_name, schem_name, is_top)

        circuit = report % LvsCircuitPair(
            ref_layout=ref_layout,
            ref_schematic=ref_schematic,
            layout_cell=layout_name or None,
            schem_cell=schem_name or None,
            status=circuit_data['status'],
            message=circuit_data['message'] or None,
        )

        for item_data in circuit_data['items']:
            insert_lvs_item(report, circuit, item_data, directory, ref_schematic)

    return report
