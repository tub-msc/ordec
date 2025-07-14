# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import itertools
from dataclasses import dataclass
from .base import *
from .ordb import Cursor

def symbol_place_pins(node: Symbol, hpadding=3, vpadding=3):
    """
    Arranges all Pins of a symbol, setting their pos attributes.
    Based on their align attribute, Pins are arranged on four sides of a rectangle.
    The outline rectangle is furthermore created.
    """

    pin_by_align = {Orientation.South:[], Orientation.North:[], Orientation.West:[], Orientation.East:[]}
    for pin in node.all(Pin):
        pin_by_align[pin.align].append(pin)

    height=max(len(pin_by_align[Orientation.East]), len(pin_by_align[Orientation.West]))+2*vpadding-1
    width=max(len(pin_by_align[Orientation.North]), len(pin_by_align[Orientation.South]))+2*hpadding-1

    for i, pin in enumerate(pin_by_align[Orientation.South]):
        pin.pos = Vec2R(x=hpadding+i,y=0)
    for i, pin in enumerate(pin_by_align[Orientation.North]):
        pin.pos = Vec2R(x=hpadding+i,y=height)
    for i, pin in enumerate(pin_by_align[Orientation.West]):
        pin.pos = Vec2R(x=0,y=vpadding+i)
    for i, pin in enumerate(pin_by_align[Orientation.East]):
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
        return D4.from_td4(self.conn.ref.loc_transform() * self.conn.there.align)

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
        if visited == None:
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

    def add_terminal(t):
        if not isinstance(t.ref.node, Net):
            raise TypeError(f"Illegal connection of {t} to {type(t.ref.node)}.")
        if t.pos in terminal_at:
            raise SchematicError(f"Overlapping terminals at {t.pos}.")
        terminal_at[t.pos] = t
        terminals_of_net[t.ref].append(t)

        if t.pos not in net_at:
            if add_terminal_taps:
                t.ref % SchemTapPoint(pos=t.pos, align=t.align.unflip())
                g.add_biedge(t.pos, t.ref)
                net_at[t.pos] = t.ref
            else:
                raise SchematicError(f"Missing terminal connection at {t.pos}.")
        elif net_at[t.pos] != t.ref:
            raise SchematicError(f"Incorrect terminal connection at {t.pos}.")

    # Wiring: SchemWires, SchemTapPoints and SchemConnPoints:
    for net in node.all(Net):
        terminals_of_net[net] = []

        for tap in node.all(SchemTapPoint.ref_idx.query(net.nid)):
            g.add_biedge(tap.pos, net)
            if tap.pos in net_at:
                if net_at[tap.pos] != net:
                    raise SchematicError(f"Geometric short at {tap.pos} between {net_at[tap.pos]} and {net}.")
            else:
                net_at[tap.pos] = net

        for poly in node.all(SchemWire.ref_idx.query(net.nid)):
            for a, b in itertools.pairwise(poly.vertices):
                g.add_biedge(a.pos, b.pos)
            for p in poly.vertices:
                if p.pos in net_at:
                    if net_at[p.pos] != net:
                        raise SchematicError(f"Geometric short at {p.pos} between {net_at[p.pos]} and {net}.")
                else:
                    net_at[p.pos] = net

        for p in node.all(SchemConnPoint.ref_idx.query(net.nid)):
            if p.pos in conn_point_at:
                raise SchematicError(f"Overlapping SchemConnPoints at {p.pos}.")
            if (p.pos not in net_at) or (net_at[p.pos] != net):
                raise SchematicError(f"Incorrectly placed SchemConnPoint at {p.pos}.")
            conn_point_at[p.pos] = p

    # Terminals: SchemPorts and SchemInstance pins:
    for port in node.all(SchemPort):
        add_terminal(port)
    for inst in node.all(SchemInstance):
        pins_expected = set(inst.symbol.all(Pin, wrap_cursor=False))
        pins_found = {c.there.nid for c in inst.conns}
        pins_missing = pins_expected - pins_found
        pins_stray = pins_found - pins_expected
        if len(pins_missing) > 0:
            raise SchematicError(f"Missing pins {pins_missing} in portmap of {inst}.")
        if len(pins_stray) > 0:
            raise SchematicError(f"Stray pins {pins_stray} in portmap of {inst}.")
        assert pins_expected == pins_found
        for conn in node.all(SchemInstanceConn.ref_idx.query(inst.nid)):
            add_terminal(PinOfInstance(conn))

    # Check whether wiring is valid:
    for pos, connections in g.edges.items():
        if isinstance(pos, Cursor):
            assert isinstance(pos.node, Net)
            continue
        assert isinstance(pos, Vec2R)
        terminal = terminal_at.get(pos, None)
        conn_point = conn_point_at.get(pos, None)
        if terminal:
            if conn_point:
                raise SchematicError(f"SchemConnPoint overlapping terminal at {pos}.")
            if len(connections) > 1:
                raise SchematicError(f"Terminal with more than one connection at {pos}.")
        else:
            if len(connections) <= 1:
                raise SchematicError(f"Unconnected wiring at {pos}.")
            if len(connections) == 2 and conn_point:
                raise SchematicError(f"Stray SchemConnPoint at {pos}.")
            if len(connections) > 2 and not conn_point:
                if add_conn_points:
                    net % SchemConnPoint(pos=pos)
                else:
                    raise SchematicError(f"Missing SchemConnPoint at {pos}.")

    # Check that terminals of all nets are connected with some kind of wiring (SchemWire or SchemTapPoint):
    for net, terminals in terminals_of_net.items():
        must_reach = {t.pos for t in terminals}
        reaches = set(g.reachable_from(terminals[0].pos))
        unconnected = must_reach-reaches
        if len(unconnected) > 0:
            raise SchematicError(f"Net {net} misses wiring to locations {unconnected}.")

def add_conn_points(s: Schematic):
    """
    Adds SchemConnPoints where two wires of the same net meet.

    schem_check does the same thing more thoroughly, but fails for incomplete
    schematics.
    """
    for net in s.all(Net):
        pos_single = set()
        pos_multi = set()
        for wire in s.all(SchemWire.ref_idx.query(net.nid)):
            for poly_point in wire.vertices:
                pos = poly_point.pos
                if pos in pos_single:
                    pos_multi.add(pos)
                else:
                    pos_single.add(pos)
            
        for pos in pos_multi:
            net % SchemConnPoint(pos=pos)

