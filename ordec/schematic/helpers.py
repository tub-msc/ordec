# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import bisect
import itertools
import math
from collections import defaultdict
from dataclasses import dataclass
from ..core import *

def spice_params(params: dict) -> list[str]:
    """Helper function for Netlister.add(). This function is in helper.py
    instead of ngspice.py due to the import structure (?)."""
    spice_params = []
    for k, v in params.items():
        if isinstance(v, R):
            v = v.compat_str()
        spice_params.append(f"{k}={v}")
    return spice_params

def symbol_place_pins(node: Symbol, hpadding=3, vpadding=3):
    """
    Arranges all Pins of a symbol, setting their pos attributes.
    Based on their align attribute, Pins are arranged on four sides of a rectangle.
    The outline rectangle is furthermore created.
    """

    pin_by_align = {South:[], North:[], West:[], East:[]}
    for pin in node.all(Pin):
        pin_by_align[pin.align].append(pin)

    height=max(len(pin_by_align[East]), len(pin_by_align[West]))+2*vpadding-1
    width=max(len(pin_by_align[North]), len(pin_by_align[South]))+2*hpadding-1

    for i, pin in enumerate(pin_by_align[South]):
        pin.pos = Vec2R(x=hpadding+i,y=0)
    for i, pin in enumerate(pin_by_align[North]):
        pin.pos = Vec2R(x=hpadding+i,y=height)
    for i, pin in enumerate(pin_by_align[West]):
        pin.pos = Vec2R(x=0,y=vpadding+i)
    for i, pin in enumerate(pin_by_align[East]):
        pin.pos = Vec2R(x=width,y=vpadding+i)

    node.outline = Rect4R(lx=0, ly=0, ux=width, uy=height)


def schematic_place(schem: Schematic, gap=None, port_pitch=2, port_margin=None):
    """
    Automatic placement for programmatically built schematics (e.g. netlist
    importers). All existing pos values are overwritten.

    SchemInstances are arranged in a simple row-based grid targeting a roughly
    square overall shape. SchemPorts are placed on the edges of the resulting
    bounding box based on their align attribute; align points into the
    schematic, so East-aligned ports go on the left edge, North-aligned ports
    on the bottom edge, and so on.

    No SchemWires are drawn. The schematic is checked with
    add_terminal_taps=True, so connectivity is represented by SchemTapPoints;
    Nets should be created with auto_wire=False. The outline is set to the
    resulting bounding box; freezing is left to the caller.

    Args:
        schem: Mutable schematic to place.
        gap: Spacing between adjacent instances. Defaults to enough room for
            two facing tap point labels of the longest net name.
        port_pitch: Spacing between adjacent ports on the same edge.
        port_margin: Distance between ports and the instance bounding box.
            Defaults to gap (the port's tap label extends into this space).
    """
    from .routing import adjust_outline_initial
    from .render import Renderer

    if gap is None:
        # Every pin gets a SchemTapPoint whose label extends away from the
        # instance (port_text_space, then ~0.35 units per character), so two
        # facing labels must fit between adjacent instances.
        max_label = max((len(net.full_path_label()) for net in schem.all(Net)),
                        default=0)
        gap = math.ceil(2 * (Renderer.port_text_space + 0.35 * max_label) + 1)
    if port_margin is None:
        port_margin = gap

    instances = list(schem.all(SchemInstance))
    sizes = []
    for inst in instances:
        o = inst.symbol.outline
        sizes.append((o.ux - o.lx, o.uy - o.ly))

    # Wrap rows at a target width chosen so the grid comes out roughly square
    # (but never narrower than the widest instance).
    area = sum(float((w + gap) * (h + gap)) for w, h in sizes)
    target_w = max([math.sqrt(area)] + [float(w) for w, h in sizes])

    x = y = row_h = R(0)
    box_w = box_h = R(0)
    for inst, (w, h) in zip(instances, sizes):
        if float(x) > 0 and float(x + w) > target_w:
            x = R(0)
            y = y + row_h + gap
            row_h = R(0)
        o = inst.symbol.outline
        # Place so the instance geometry (pos + outline) starts at (x, y).
        inst.pos = Vec2R(x - o.lx, y - o.ly)
        row_h = max(row_h, h)
        box_w = max(box_w, x + w)
        box_h = max(box_h, y + h)
        x = x + w + gap

    port_by_align = {East: [], West: [], North: [], South: []}
    for port in schem.all(SchemPort):
        port_by_align[port.align].append(port)

    # Widen the box if a port row/column needs more room than the instances.
    box_w = max(box_w, port_pitch * max(len(port_by_align[North]),
                                        len(port_by_align[South])))
    box_h = max(box_h, port_pitch * max(len(port_by_align[East]),
                                        len(port_by_align[West])))

    for i, port in enumerate(port_by_align[East]):
        port.pos = Vec2R(-port_margin, 1 + port_pitch * i)
    for i, port in enumerate(port_by_align[West]):
        port.pos = Vec2R(box_w + port_margin, 1 + port_pitch * i)
    for i, port in enumerate(port_by_align[North]):
        port.pos = Vec2R(1 + port_pitch * i, -port_margin)
    for i, port in enumerate(port_by_align[South]):
        port.pos = Vec2R(1 + port_pitch * i, box_h + port_margin)

    schem.check(add_terminal_taps=True)
    outline = adjust_outline_initial(schem)
    if outline is None:
        outline = Rect4R(0, 0, 1, 1)
    # adjust_outline_initial covers port labels but not tap point labels,
    # which this placement relies on for connectivity.
    for tap in schem.all(SchemTapPoint):
        label_len = Renderer.port_text_space + 0.35 * len(tap.ref.full_path_label())
        outline = outline.extend(tap.pos + (tap.align * Vec2R(0, 1)) * label_len)
    schem.outline = outline


def schem_add_pin_tap(inst: SchemInstance, pin: Pin):
    """
    At SchemTapPoint directly at Pin
    """
    net = inst.portmap[pin]
    net % SchemTapPoint(pos=inst.loc_transform()*pin.pos, align=pin.align)

def first_last_iter(iterable):
    """
    Iterates over iterable in tuples (elem, is_first, is_last).
    Currently unused.
    """
    i = 0
    is_last = False
    it = iter(iterable)
    while True:
        try:
            cur = next(it)
        except StopIteration:
            is_last = True
        if i > 0:
            yield prev, i == 1, is_last
        if is_last:
            break
        prev = cur
        i += 1

@dataclass
class PinOfInstance:
    conn: SchemInstanceConn

    @property
    def pos(self):
        return self.conn.ref.loc_transform() * self.conn.there.pos

    @property
    def net(self):
        return self.conn.here

    @property
    def align(self):
        #TODO: check if this pin.align transformation works:
        return self.conn.ref.loc_transform().d4 * self.conn.there.align

    @property
    def ref(self):
        return self.conn.here

class SchematicError(Exception):
    pass

def _net_at_pos(node: Schematic, pos: Vec2R) -> Net | None:
    """Look up which Net occupies a position, via tap points or wire vertices."""
    for tap in node.all(SchemTapPoint.pos_idx.query(pos)):
        return tap.ref
    for pv in node.all(PolyVec2R.pos_idx.query(pos)):
        wire = pv.ref
        if isinstance(wire, SchemWire):
            return wire.ref
    return None

def _has_geometric_short(node: Schematic, pos: Vec2R, net: Net) -> bool:
    """Check if a position is claimed by a different net."""
    for tap in node.all(SchemTapPoint.pos_idx.query(pos)):
        if tap.ref != net:
            return True
    for pv in node.all(PolyVec2R.pos_idx.query(pos)):
        if isinstance(pv.ref, SchemWire) and pv.ref.ref != net:
            return True
    return False

def _check_overlapping_instances(node: Schematic):
    """Check all instance pairs for overlapping or touching boundaries.

    Uses x-axis sweep line with a sorted active list of y-intervals.
    Events are sorted by x; at equal x, opens are processed before closes
    so that rectangles touching at a single edge are detected.
    """
    # Build events: (x, type, inst, rect)  type 0=open, 1=close
    events = []
    for inst in node.all(SchemInstance):
        if isinstance(inst.pos, Vec2LinearTerm):
            continue
        r = inst.loc_transform() * inst.symbol.outline
        events.append((r.lx, 0, inst, r))
        events.append((r.ux, 1, inst, r))
    events.sort(key=lambda e: (e[0], e[1]))
    # Active list sorted by ly; entries are (ly, uy, inst)
    active = []
    for _, etype, inst, r in events:
        if etype == 1:
            # Close: remove from active list
            for k, entry in enumerate(active):
                if entry[2] is inst:
                    active.pop(k)
                    break
        else:
            # Open: check active intervals for y-overlap/touch.
            # Active is sorted by ly, so once a_ly > r.uy no further
            # entries can overlap.
            for a_ly, a_uy, a_inst in active:
                if a_ly > r.uy:
                    break
                if r.ly <= a_uy:
                    node.root % SchemErrorMarker(
                        pos=inst.pos,
                        error_type=SchemErrorType.OverlappingInstances
                    )
                    node.root % SchemErrorMarker(
                        pos=a_inst.pos,
                        error_type=SchemErrorType.OverlappingInstances
                    )
            # Insert into active list maintaining sort by ly
            bisect.insort(active, (r.ly, r.uy, inst))

def _check_overlapping_segments(node: Schematic):
    """Check all wire segment pairs for overlap.

    Groups axis-aligned segments by their collinear line (e.g. all vertical
    segments at x=K), then sorts each group by start coordinate and sweeps
    to detect overlaps in O(n log n) total.
    """
    # Bucket segments by orientation + fixed coordinate
    groups = defaultdict(list)
    for net in node.all(Net):
        for poly in node.all(SchemWire.ref_idx.query(net)):
            for a, b in itertools.pairwise(poly.vertices()):
                if a.x == b.x:  # vertical
                    lo, hi = (a.y, b.y) if a.y <= b.y else (b.y, a.y)
                    groups[('v', a.x)].append((lo, hi, a))
                else:  # horizontal
                    lo, hi = (a.x, b.x) if a.x <= b.x else (b.x, a.x)
                    groups[('h', a.y)].append((lo, hi, a))
    # Sort+sweep per group: overlap exists when lo < running max_hi
    # (strict < because touching at a single endpoint is not an overlap)
    for segs in groups.values():
        segs.sort()
        max_hi = segs[0][1]
        for k in range(1, len(segs)):
            lo, hi, pos = segs[k]
            if lo < max_hi:
                node.root % SchemErrorMarker(
                    pos=pos, error_type=SchemErrorType.OverlappingWires
                )
            if hi > max_hi:
                max_hi = hi

class ConnectivityGraph:
    def __init__(self, node: Schematic, suppress_errors: bool = False):
        """Build connectivity graph from wiring, check geometric shorts."""
        self.edges = {}
        short_reported = set()
        for net in node.all(Net):
            for tap in node.all(SchemTapPoint.ref_idx.query(net)):
                self.add_biedge(tap.pos, net)
                if not suppress_errors and tap.pos not in short_reported and _has_geometric_short(node, tap.pos, net):
                    node.root % SchemErrorMarker(pos=tap.pos, error_type=SchemErrorType.GeometricShort)
                    short_reported.add(tap.pos)

            for poly in node.all(SchemWire.ref_idx.query(net)):
                vertices = poly.vertices()
                for a, b in itertools.pairwise(vertices):
                    self.add_biedge(a, b)
                if not suppress_errors:
                    for pos in vertices:
                        if pos not in short_reported and _has_geometric_short(node, pos, net):
                            node.root % SchemErrorMarker(pos=pos, error_type=SchemErrorType.GeometricShort)
                            short_reported.add(pos)

    def add_biedge(self, p1, p2):
        if p1 not in self.edges:
            self.edges[p1] = []
        self.edges[p1].append(p2)
        if p2 not in self.edges:
            self.edges[p2] = []
        self.edges[p2].append(p1)

    def reachable_from(self, cur, visited=None):
        if visited is None:
            visited=set()
        if cur in visited:
            return
        visited.add(cur)
        yield cur
        for nxt in self.edges[cur]:
            yield from self.reachable_from(nxt, visited)

def _check_conn_points(node: Schematic, suppress_errors: bool = False):
    """Validate SchemConnPoints are correctly placed."""
    if suppress_errors:
        return
    seen_positions = set()
    for p in node.all(SchemConnPoint):
        if p.pos in seen_positions:
            node.root % SchemErrorMarker(pos=p.pos, error_type=SchemErrorType.OverlappingSchemConnPoints)
        else:
            net_here = _net_at_pos(node, p.pos)
            if net_here is None or net_here != p.ref:
                node.root % SchemErrorMarker(pos=p.pos, error_type=SchemErrorType.IncorrectlyPlacedSchemConnPoint)
            else:
                seen_positions.add(p.pos)

def _check_terminals(node: Schematic, g: ConnectivityGraph,
                     add_terminal_taps: bool,
                     suppress_errors: bool = False) -> set[Vec2R]:
    """Validate terminals (ports + instance pins). Returns terminal positions."""
    terminal_positions = set()

    def add_terminal(t):
        if not isinstance(t.ref, Net):
            raise TypeError(f"Illegal connection of {t} to {type(t.ref)}.")
        if t.pos in terminal_positions:
            if not suppress_errors:
                node.root % SchemErrorMarker(pos=t.pos, error_type=SchemErrorType.OverlappingTerminals)
            return
        terminal_positions.add(t.pos)

        net_here = _net_at_pos(node, t.pos)
        if net_here is None:
            if add_terminal_taps:
                t.ref % SchemTapPoint(pos=t.pos, align=t.align.unflip())
                g.add_biedge(t.pos, t.ref)
            elif not suppress_errors:
                node.root % SchemErrorMarker(pos=t.pos, error_type=SchemErrorType.MissingTerminalConnection)
                return
            else:
                return
        elif net_here != t.ref:
            if not suppress_errors:
                node.root % SchemErrorMarker(pos=t.pos, error_type=SchemErrorType.IncorrectTerminalConnection)
            return

    for port in node.all(SchemPort):
        add_terminal(port)
    for inst in node.all(SchemInstance):
        pins_expected = set(inst.symbol.all(Pin, wrap_cursor=False))
        pins_found = {c.there.nid for c in inst.conns()}
        pins_missing = pins_expected - pins_found
        pins_stray = pins_found - pins_expected
        if not suppress_errors:
            for pin_nid in pins_missing:
                pin = inst.symbol.subgraph.cursor_at(pin_nid)
                pin_pos = inst.loc_transform() * pin.pos
                pin_align = inst.loc_transform().d4 * pin.align
                node.root % SchemErrorMarker(pos=pin_pos, error_type=SchemErrorType.UnconnectedPin, align=pin_align)
            if len(pins_stray) > 0:
                node.root % SchemErrorMarker(pos=inst.pos, error_type=SchemErrorType.StrayPinsInPortmap)
        if pins_expected == pins_found:
            for conn in node.all(SchemInstanceConn.ref_idx.query(inst)):
                add_terminal(PinOfInstance(conn))

    return terminal_positions

def _check_wiring_validity(node: Schematic, g: ConnectivityGraph,
                           terminal_positions: set[Vec2R],
                           add_conn_points: bool,
                           suppress_errors: bool = False):
    """Validate wiring at each graph node (position).

    At terminals: flags conn points that overlap terminals and terminals
    with more than one wire connection.
    At non-terminals: flags dead-end wiring, stray conn points on simple
    pass-throughs, and junctions (>2 connections) missing a conn point.
    """
    for pos, connections in g.edges.items():
        if isinstance(pos, Net):
            continue
        assert isinstance(pos, Vec2R)
        is_terminal = pos in terminal_positions
        has_conn_point = any(True for _ in node.all(SchemConnPoint.pos_idx.query(pos)))
        if is_terminal:
            if not suppress_errors:
                if has_conn_point:
                    node.root % SchemErrorMarker(pos=pos, error_type=SchemErrorType.SchemConnPointOverlappingTerminal)
                if len(connections) > 1:
                    node.root % SchemErrorMarker(pos=pos, error_type=SchemErrorType.TerminalMultipleConnections)
        else:
            if not suppress_errors:
                if len(connections) <= 1:
                    node.root % SchemErrorMarker(pos=pos, error_type=SchemErrorType.UnconnectedWiring)
                if len(connections) == 2 and has_conn_point:
                    node.root % SchemErrorMarker(pos=pos, error_type=SchemErrorType.StraySchemConnPoint)
            if len(connections) > 2 and not has_conn_point:
                if add_conn_points:
                    net = _net_at_pos(node, pos)
                    net % SchemConnPoint(pos=pos)
                elif not suppress_errors:
                    node.root % SchemErrorMarker(pos=pos, error_type=SchemErrorType.MissingSchemConnPoint)

def _check_net_connectivity(node: Schematic, g: ConnectivityGraph,
                            suppress_errors: bool = False):
    """Check that all terminals of each net are reachable.

    Wiring components that carry a tap or contain a port count as connected
    by label (both display the net name). All other components must be
    wire-connected and are flagged with NetMissesWiring otherwise.
    """
    if suppress_errors:
        return
    # Build terminals-of-net from indices
    terminals_of_net = {net: [] for net in node.all(Net)}
    for port in node.all(SchemPort):
        terminals_of_net[port.ref].append(port)
    for conn in node.all(SchemInstanceConn):
        terminals_of_net[conn.here].append(PinOfInstance(conn))

    for net, terminals in terminals_of_net.items():
        if len(terminals) == 0:
            continue
        # Skip terminals not in the connectivity graph (already flagged
        # as MissingTerminalConnection).
        reachable_terminals = [t for t in terminals if t.pos in g.edges]
        if len(reachable_terminals) == 0:
            continue
        terminal_components = []
        seen_terminals = set()
        for terminal in reachable_terminals:
            if terminal.pos in seen_terminals:
                continue
            reaches = set(g.reachable_from(terminal.pos))
            component = [t for t in reachable_terminals if t.pos in reaches]
            seen_terminals.update(t.pos for t in component)
            # Taps reach the Net node and ports display the net name directly.
            labeled = net in reaches or any(
                not isinstance(t, PinOfInstance) for t in component)
            terminal_components.append((component, labeled))

        if len(terminal_components) > 1:
            # Only unlabeled components are cut off. With no label anywhere,
            # keep the largest component as the net's main part instead.
            stray = [c for c, labeled in terminal_components if not labeled]
            if len(stray) == len(terminal_components):
                stray.remove(max(stray, key=len))
            for component in stray:
                node.root % SchemErrorMarker(
                    pos=component[0].pos,
                    error_type=SchemErrorType.NetMissesWiring
                )

def schem_check(node: Schematic, add_conn_points: bool=False, add_terminal_taps=False) -> bool:
    """Validate schematic connectivity and wiring structure.

    Checks are run in phases. If an early phase produces errors,
    later phases suppress further error reporting but still perform
    structural work (e.g. inserting SchemConnPoints or SchemTapPoints).

    Args:
        node: The schematic to validate.
        add_conn_points: If True, automatically insert
            SchemConnPoints at junctions with more than two
            connections.
        add_terminal_taps: If True, automatically insert
            SchemTapPoints at terminal positions that lack a
            wiring connection.

    Returns:
        True if the schematic has errors after checking.
    """
    suppress = False
    _check_overlapping_instances(node)
    suppress = suppress or node.has_errors()
    _check_overlapping_segments(node)
    suppress = suppress or node.has_errors()
    g = ConnectivityGraph(node, suppress_errors=suppress)
    suppress = suppress or node.has_errors()
    _check_conn_points(node, suppress_errors=suppress)
    suppress = suppress or node.has_errors()
    terminal_positions = _check_terminals(node, g, add_terminal_taps, suppress_errors=suppress)
    suppress = suppress or node.has_errors()
    _check_wiring_validity(node, g, terminal_positions, add_conn_points, suppress_errors=suppress)
    suppress = suppress or node.has_errors()
    _check_net_connectivity(node, g, suppress_errors=suppress)
    return node.has_errors()


def recursive_getitem(obj, tup):
    if len(tup) == 0:
        return obj
    else:
        return recursive_getitem(obj[tup[0]], tup[1:])

def recursive_setitem(obj, tup, value):
    if len(tup) == 1:
        obj[tup[0]] = value
    else:
        return recursive_setitem(obj[tup[0]], tup[1:], value)

def resolve_instances(schematic: Schematic):
    """
    Resolves all SchemInstanceUnresolved objects, replacing them by
    SchemInstance objects. Corresponding SchemInstanceUnresolvedParameter
    objects are used in the process and removed afterwards.
    Corresponding SchemInstanceUnresolvedConn objects are replaced by
    SchemInstanceConn objects.
    
    The node ids (nids) of SchemInstanceUnresolved and
    SchemInstanceUnresolvedConn objects are preserved.
    """
    for ui in schematic.all(SchemInstanceUnresolved):
        with schematic.subgraph.updater() as sgu:
            param_dict = {}
            for param in schematic.all(SchemInstanceUnresolvedParameter.ref_idx.query(ui)):
                param_dict[param.name] = param.value
                sgu.remove_nid(param.nid)

            symbol = ui.resolver(**param_dict)

            new_scheminstance_tuple = SchemInstance(
                pos=ui.pos,
                orientation=ui.orientation,
                symbol=symbol,
                src_loc=ui.src_loc,
                )

            sgu.remove_nid(ui.nid)

            for uc in schematic.all(SchemInstanceUnresolvedConn.ref_idx.query(ui)):
                pin = recursive_getitem(symbol, uc.there)
                if not isinstance(pin, Pin):
                    raise SchematicError("Unresolved attribute {uc.there!r} did not resolve to Pin.")
                new_conn_tuple = SchemInstanceConn(ref=uc.ref, here=uc.here, there=pin)

                sgu.remove_nid(uc.nid)
                sgu.add_single(new_conn_tuple, uc.nid, check_nid=False)

            sgu.add_single(new_scheminstance_tuple, ui.nid, check_nid=False)

