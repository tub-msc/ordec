# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import itertools
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

class ConnectivityGraph:
    def __init__(self, node: Schematic):
        """Build connectivity graph from wiring, check geometric shorts."""
        self.edges = {}
        short_reported = set()
        for net in node.all(Net):
            for tap in node.all(SchemTapPoint.ref_idx.query(net)):
                self.add_biedge(tap.pos, net)
                if tap.pos not in short_reported and _has_geometric_short(node, tap.pos, net):
                    node.root % SchemErrorMarker(pos=tap.pos, error_type=SchemErrorType.GeometricShort)
                    short_reported.add(tap.pos)

            for poly in node.all(SchemWire.ref_idx.query(net)):
                vertices = poly.vertices()
                for a, b in itertools.pairwise(vertices):
                    self.add_biedge(a, b)
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

def _check_conn_points(node: Schematic):
    """Validate SchemConnPoints are correctly placed."""
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
                     add_terminal_taps: bool) -> set[Vec2R]:
    """Validate terminals (ports + instance pins). Returns terminal positions."""
    terminal_positions = set()

    def add_terminal(t):
        if not isinstance(t.ref, Net):
            raise TypeError(f"Illegal connection of {t} to {type(t.ref)}.")
        if t.pos in terminal_positions:
            node.root % SchemErrorMarker(pos=t.pos, error_type=SchemErrorType.OverlappingTerminals)
            return
        terminal_positions.add(t.pos)

        net_here = _net_at_pos(node, t.pos)
        if net_here is None:
            if add_terminal_taps:
                t.ref % SchemTapPoint(pos=t.pos, align=t.align.unflip())
                g.add_biedge(t.pos, t.ref)
            else:
                node.root % SchemErrorMarker(pos=t.pos, error_type=SchemErrorType.MissingTerminalConnection)
                return
        elif net_here != t.ref:
            node.root % SchemErrorMarker(pos=t.pos, error_type=SchemErrorType.IncorrectTerminalConnection)
            return

    for port in node.all(SchemPort):
        add_terminal(port)
    for inst in node.all(SchemInstance):
        pins_expected = set(inst.symbol.all(Pin, wrap_cursor=False))
        pins_found = {c.there.nid for c in inst.conns()}
        pins_missing = pins_expected - pins_found
        pins_stray = pins_found - pins_expected
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
                           add_conn_points: bool):
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
            if has_conn_point:
                node.root % SchemErrorMarker(pos=pos, error_type=SchemErrorType.SchemConnPointOverlappingTerminal)
            if len(connections) > 1:
                node.root % SchemErrorMarker(pos=pos, error_type=SchemErrorType.TerminalMultipleConnections)
        else:
            if len(connections) <= 1:
                node.root % SchemErrorMarker(pos=pos, error_type=SchemErrorType.UnconnectedWiring)
            if len(connections) == 2 and has_conn_point:
                node.root % SchemErrorMarker(pos=pos, error_type=SchemErrorType.StraySchemConnPoint)
            if len(connections) > 2 and not has_conn_point:
                if add_conn_points:
                    net = _net_at_pos(node, pos)
                    net % SchemConnPoint(pos=pos)
                else:
                    node.root % SchemErrorMarker(pos=pos, error_type=SchemErrorType.MissingSchemConnPoint)

def _check_net_connectivity(node: Schematic, g: ConnectivityGraph):
    """Check that all terminals of each net are reachable."""
    # Build terminals-of-net from indices
    terminals_of_net = {net: [] for net in node.all(Net)}
    for port in node.all(SchemPort):
        terminals_of_net[port.ref].append(port)
    for conn in node.all(SchemInstanceConn):
        terminals_of_net[conn.here].append(PinOfInstance(conn))

    for net, terminals in terminals_of_net.items():
        if len(terminals) == 0:
            continue
        must_reach = {t.pos for t in terminals}
        reaches = set(g.reachable_from(terminals[0].pos))
        unconnected = must_reach - reaches
        if len(unconnected) > 0:
            node.root % SchemErrorMarker(pos=terminals[0].pos, error_type=SchemErrorType.NetMissesWiring)

def schem_check(node: Schematic, add_conn_points: bool=False, add_terminal_taps=False):
    g = ConnectivityGraph(node)
    if node.has_errors():
        return
    _check_conn_points(node)
    if node.has_errors():
        return
    terminal_positions = _check_terminals(node, g, add_terminal_taps)
    if node.has_errors():
        return
    _check_wiring_validity(node, g, terminal_positions, add_conn_points)
    if node.has_errors():
        return
    _check_net_connectivity(node, g)

def add_conn_points(s: Schematic):
    """
    Adds SchemConnPoints where two wires of the same net meet.

    schem_check does the same thing more thoroughly, but fails for incomplete
    schematics.
    """
    for net in s.all(Net):
        pos_single = set()
        pos_multi = set()
        for wire in s.all(SchemWire.ref_idx.query(net)):
            for pos in wire.vertices():
                if pos in pos_single:
                    pos_multi.add(pos)
                else:
                    pos_single.add(pos)
            
        for pos in pos_multi:
            net % SchemConnPoint(pos=pos)

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

