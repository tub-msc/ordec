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

class ConnectivityGraph:
    def __init__(self):
        self.edges = {}

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

def schem_check(node: Schematic, add_conn_points: bool=False, add_terminal_taps=False):
    g = ConnectivityGraph()

    net_at = {}
    conn_point_at = {}
    terminal_at = {}
    terminals_of_net = {}
    has_errors = False

    def add_error(pos, error_type, align=D4.R0):
        nonlocal has_errors
        has_errors = True
        node.root % SchemErrorMarker(pos=pos, align=align, error_type=error_type)

    def add_terminal(t):
        if not isinstance(t.ref, Net):
            raise TypeError(f"Illegal connection of {t} to {type(t.ref)}.")
        if t.pos in terminal_at:
            add_error(t.pos, SchemErrorType.OverlappingTerminals)
            return
        terminal_at[t.pos] = t

        if t.pos not in net_at:
            if add_terminal_taps:
                t.ref % SchemTapPoint(pos=t.pos, align=t.align.unflip())
                g.add_biedge(t.pos, t.ref)
                net_at[t.pos] = t.ref
            else:
                add_error(t.pos, SchemErrorType.MissingTerminalConnection)
                return
        elif net_at[t.pos] != t.ref:
            add_error(t.pos, SchemErrorType.IncorrectTerminalConnection)
            return

        terminals_of_net[t.ref].append(t)

    # Wiring: SchemWires, SchemTapPoints and SchemConnPoints:
    for net in node.all(Net):
        terminals_of_net[net] = []

        for tap in node.all(SchemTapPoint.ref_idx.query(net)):
            g.add_biedge(tap.pos, net)
            if tap.pos in net_at:
                if net_at[tap.pos] != net:
                    add_error(tap.pos, SchemErrorType.GeometricShort)
            else:
                net_at[tap.pos] = net

        for poly in node.all(SchemWire.ref_idx.query(net)):
            vertices = poly.vertices()
            for a, b in itertools.pairwise(vertices):
                g.add_biedge(a, b)
            for pos in vertices:
                if pos in net_at:
                    if net_at[pos] != net:
                        add_error(pos, SchemErrorType.GeometricShort)
                else:
                    net_at[pos] = net

        for p in node.all(SchemConnPoint.ref_idx.query(net)):
            if p.pos in conn_point_at:
                add_error(p.pos, SchemErrorType.OverlappingSchemConnPoints)
            elif (p.pos not in net_at) or (net_at[p.pos] != net):
                add_error(p.pos, SchemErrorType.IncorrectlyPlacedSchemConnPoint)
            else:
                conn_point_at[p.pos] = p

    # Terminals: SchemPorts and SchemInstance pins:
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
            add_error(pin_pos, SchemErrorType.UnconnectedPin, align=pin_align)
        if len(pins_stray) > 0:
            add_error(inst.pos, SchemErrorType.StrayPinsInPortmap)
        if pins_expected == pins_found:
            for conn in node.all(SchemInstanceConn.ref_idx.query(inst)):
                add_terminal(PinOfInstance(conn))

    if has_errors:
        return

    # Check whether wiring is valid:
    for pos, connections in g.edges.items():
        if isinstance(pos, Net):
            continue
        assert isinstance(pos, Vec2R)
        terminal = terminal_at.get(pos, None)
        conn_point = conn_point_at.get(pos, None)
        if terminal:
            if conn_point:
                add_error(pos, SchemErrorType.SchemConnPointOverlappingTerminal)
            if len(connections) > 1:
                add_error(pos, SchemErrorType.TerminalMultipleConnections)
        else:
            if len(connections) <= 1:
                add_error(pos, SchemErrorType.UnconnectedWiring)
            if len(connections) == 2 and conn_point:
                add_error(pos, SchemErrorType.StraySchemConnPoint)
            if len(connections) > 2 and not conn_point:
                if add_conn_points:
                    net % SchemConnPoint(pos=pos)
                else:
                    add_error(pos, SchemErrorType.MissingSchemConnPoint)

    if has_errors:
        return

    # Check that terminals of all nets are connected with some kind of wiring (SchemWire or SchemTapPoint):
    for net, terminals in terminals_of_net.items():
        if len(terminals) == 0:
            continue
        must_reach = {t.pos for t in terminals}
        reaches = set(g.reachable_from(terminals[0].pos))
        unconnected = must_reach-reaches
        if len(unconnected) > 0:
            add_error(terminals[0].pos, SchemErrorType.NetMissesWiring)

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

