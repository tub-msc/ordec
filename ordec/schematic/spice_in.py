# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Import SPICE subcircuit netlists as ORDeC schematics.

This is a small, general-purpose parser for the (roughly ngspice-compatible)
subset of SPICE needed to turn ``.subckt`` definitions into :class:`Schematic`
subgraphs. It is intentionally split into two stages, mirroring how ngspice
itself processes input (see ``inpcom.c``):

1. A line-oriented *preprocess* pass (:func:`clean_cards`) that strips comments
   (quote-aware) and stitches ``+`` continuation lines into logical cards.
2. A flat *tokenizer + dispatch* pass (:func:`parse_deck`) that turns each
   logical card into neutral data structures (:class:`SpiceDeck`,
   :class:`SubcktDef`, :class:`Instance`).

The parser knows nothing about any specific PDK: the mapping from SPICE device
model names to ORDeC leaf cells is supplied by the caller via ``device_map``
(see :class:`DeviceMapping`). This keeps the parser reusable for arbitrary
ngspice-compatible netlists and makes adding more directives/devices additive.
"""

from functools import partial
from dataclasses import dataclass, field
from public import public
import re

from ..core import *
from .routing import adjust_outline_initial

@public
class SpiceImportError(Exception):
    pass


# Neutral parse result structures
# -------------------------------

@dataclass
class Instance:
    """A single instance/device card, e.g. ``XN0 d g s b sg13_lv_nmos w=...``."""
    name: str
    prefix: str  # uppercased first letter, selects the device class (X, M, R, ...)
    nodes: list  # positional node names (excluding the trailing model name)
    model: str   # trailing positional token: model or referenced subckt name
    params: dict  # lowercased key -> value string (values kept opaque)


@dataclass
class SubcktDef:
    name: str
    ports: list
    params: dict = field(default_factory=dict)
    instances: list = field(default_factory=list)


@dataclass
class SpiceDeck:
    subckts: dict = field(default_factory=dict)
    top_cards: list = field(default_factory=list)  # raw logical cards outside any subckt


@dataclass
class DeviceMapping:
    """Describes how a SPICE device model maps onto an ORDeC leaf cell.

    Args:
        cell: The Cell subclass to instantiate.
        pin_order: Symbol pin names in the order the SPICE nodes appear, e.g.
            ``("d", "g", "s", "b")`` for a MOSFET.
        real_params: SPICE parameter names converted via ``R(...)`` (e.g. l, w).
        int_params: SPICE parameter names converted to ``int`` (e.g. ng, m).

    SPICE parameters not listed in real_params/int_params are dropped (e.g. the
    geometric ad/as/pd/ps parasitics that the target cell does not model).
    """
    cell: type
    pin_order: tuple
    real_params: tuple = ()
    int_params: tuple = ()


# Stage A: line preprocessing (comments + continuations)
# ------------------------------------------------------

def strip_inline_comment(line: str) -> str:
    """Remove an inline comment from a single physical line, quote-aware.

    Mirrors ngspice (inpcom.c:inp_stripcomments_line): ``;``, ``//`` and a ``$``
    preceded by space/comma/tab start a comment; characters inside ``"..."`` or
    ``'...'`` are skipped so a comment character there is not honored.
    """
    out = []
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c in "\"'":
            quote = c
            out.append(c)
            i += 1
            while i < n:
                out.append(line[i])
                if line[i] == quote and line[i - 1] != '\\':
                    i += 1
                    break
                i += 1
            continue
        if c == ';':
            break
        if c == '/' and i + 1 < n and line[i + 1] == '/':
            break
        if c == '$' and (i == 0 or line[i - 1] in ' ,\t'):
            break
        out.append(c)
        i += 1
    return ''.join(out)


def clean_cards(text: str) -> list:
    """Turn raw netlist text into a list of logical cards.

    Strips full-line and inline comments and stitches ``+`` continuation lines
    onto the preceding card. Comparison/dispatch is left to the caller; this
    only normalizes whitespace and line structure.
    """
    logical = []
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if stripped == '':
            continue
        first = stripped[0]
        if first in '*#$':
            # Full-line comment ('*'/'#') or comment-prefixed line ('$').
            continue
        if first == '+':
            # Continuation: drop the '+' and append to the previous card. An
            # illegal continuation (no previous card) is ignored, like ngspice.
            cont = strip_inline_comment(stripped[1:]).strip()
            if logical and cont:
                logical[-1] = logical[-1] + ' ' + cont
            continue
        body = strip_inline_comment(raw).strip()
        if body:
            logical.append(body)
    return logical


# Stage B: tokenizer + dispatch
# -----------------------------

def tokenize(card: str) -> list:
    """Whitespace-split a card while keeping ``{...}``/``'...'``/``"..."`` groups
    intact, so expression-valued parameters remain single opaque tokens."""
    tokens = []
    cur = []
    depth = 0
    quote = None
    for c in card:
        if quote:
            cur.append(c)
            if c == quote:
                quote = None
            continue
        if c in "\"'":
            quote = c
            cur.append(c)
            continue
        if c == '{':
            depth += 1
            cur.append(c)
            continue
        if c == '}':
            depth = max(0, depth - 1)
            cur.append(c)
            continue
        if depth == 0 and c.isspace():
            if cur:
                tokens.append(''.join(cur))
                cur = []
            continue
        cur.append(c)
    if cur:
        tokens.append(''.join(cur))
    return tokens


def is_param(tok: str) -> bool:
    return '=' in tok and tok[0] not in "{'\""


def split_params(tokens: list) -> tuple:
    """Split a token list into leading positional tokens and trailing k=v params.

    Once the first ``key=value`` token is seen, all subsequent tokens are treated
    as parameters (a bare ``params:`` keyword, if present, is skipped)."""
    positional = []
    params = {}
    in_params = False
    for tok in tokens:
        if tok.lower() == 'params:':
            in_params = True
            continue
        if is_param(tok):
            in_params = True
            k, v = tok.split('=', 1)
            params[k.lower()] = v
        elif in_params:
            # Stray positional token after params started: ignore defensively.
            continue
        else:
            positional.append(tok)
    return positional, params


def parse_instance(tokens: list) -> Instance:
    name = tokens[0]
    positional, params = split_params(tokens[1:])
    model = positional[-1] if positional else None
    nodes = positional[:-1] if positional else []
    return Instance(name=name, prefix=name[0].upper(), nodes=nodes,
                    model=model, params=params)


@public
def parse_deck(text: str) -> SpiceDeck:
    """Parse a SPICE netlist string into a :class:`SpiceDeck`."""
    deck = SpiceDeck()
    current = None
    for card in clean_cards(text):
        tokens = tokenize(card)
        if not tokens:
            continue
        head = tokens[0].lower()
        if head == '.subckt':
            if len(tokens) < 2:
                raise SpiceImportError(f"Malformed .subckt card: {card!r}")
            positional, params = split_params(tokens[2:])
            name = tokens[1]
            current = SubcktDef(name=name, ports=positional, params=params)
            deck.subckts[name] = current
        elif head == '.ends':
            current = None
        elif tokens[0].startswith('.'):
            # Other directive: retained raw for now (e.g. .model, .param, .lib).
            (current.instances if current is not None else deck.top_cards).append(card)
        else:
            inst = parse_instance(tokens)
            if current is not None:
                current.instances.append(inst)
            else:
                deck.top_cards.append(inst)
    return deck


# Schematic / symbol construction (ORDeC-specific layer)
# ------------------------------------------------------

def safe_name(name: str) -> str:
    """Sanitize a SPICE node/instance name into a valid path component."""
    safe = re.sub(r'[^A-Za-z0-9_]', '_', name)
    if not safe or safe[0].isdigit():
        safe = 'n_' + safe
    return safe


def to_int_with_si_support(value: str) -> int:
    """Supports SI prefixes u/m/k etc. using conditional R() detour."""
    try:
        return int(value)
    except ValueError:
        return int(R(value))


@public
def spice_subckt_discover(path, extlib, device_map: dict):
    """Discover symbol/schematic generators for every ``.subckt`` in a file.

    Returns ``(symbol_funcs, schematic_funcs)`` like
    :func:`ordec.schematic.verilog_in.yosys_json_discover`. The symbol functions
    auto-generate a symbol from the subckt port list and are intended as a
    fallback only (a symbol from e.g. ``read_lef`` should win — see
    :meth:`ExtLibrary.read_spice`).
    """
    with open(path) as f:
        deck = parse_deck(f.read())
    symbol_funcs = {}
    schematic_funcs = {}
    for name, subckt in deck.subckts.items():
        symbol_funcs[name] = partial(create_symbol_from_subckt,
                                     extlib=extlib, name=name, ports=list(subckt.ports))
        schematic_funcs[name] = partial(create_schematic_from_subckt,
                                        extlib=extlib, deck=deck, name=name,
                                        device_map=device_map)
    return symbol_funcs, schematic_funcs


def create_symbol_from_subckt(extlib, name, ports) -> Symbol:
    """Auto-generate a symbol from a subckt port list.

    SPICE does not carry pin directions, so every pin defaults to
    ``PinType.Inout`` and pins are placed automatically.
    """
    sym = Symbol(caption=name, cell=extlib[name])
    for port in ports:
        sym[port] = Pin(pintype=PinType.Inout, align=North)
    sym.place_pins(hpadding=3, vpadding=2)
    return sym.freeze()


def create_schematic_from_subckt(extlib, deck, name, device_map) -> Schematic:
    subckt = deck.subckts[name]
    cell = extlib[name]
    symbol = cell.symbol
    schematic = Schematic(cell=cell, symbol=symbol)

    used = set()

    def unique_name(base):
        safe = safe_name(base)
        candidate = safe
        i = 1
        while candidate in used:
            candidate = f"{safe}__{i}"
            i += 1
        used.add(candidate)
        return candidate

    # Create one Net per distinct SPICE node, ports first (so they get pins).
    port_set = set(subckt.ports)
    node_to_net = {}
    ordered_nodes = list(subckt.ports)
    for inst in subckt.instances:
        ordered_nodes.extend(inst.nodes)
    for nd in dict.fromkeys(ordered_nodes):  # preserve order, de-duplicate
        path = unique_name(nd)
        if nd in port_set:
            schematic[path] = Net(pin=symbol[nd])
        else:
            schematic[path] = Net()
        node_to_net[nd] = schematic[path]

    # External ports, placed automatically opposite their symbol pin alignment.
    port_count = {West: 0, East: 0, North: 0, South: 0}

    def next_port_pos(align):
        i = port_count[align]
        port_count[align] = i + 1
        if align == West:
            return Vec2R(0, 2 * i + 1)
        if align == East:
            return Vec2R(24, 2 * i + 1)
        if align == North:
            return Vec2R(2 * i + 1, 24)
        return Vec2R(2 * i + 1, 0)

    for port in subckt.ports:
        pin = symbol[port]
        align = pin.align * R180
        schematic % SchemPort(ref=node_to_net[port], pos=next_port_pos(align), align=align)

    # Instances, stacked vertically in an auto-layout column.
    cur_y = 0
    for inst in subckt.instances:
        child_sym, conns = resolve_instance(extlib, deck, device_map, name, inst, node_to_net)
        path = unique_name(inst.name)
        schematic[path] = SchemInstance(child_sym.portmap(**conns), pos=Vec2R(10, cur_y))
        cur_y += child_sym.outline.height + 5

    schematic.check(add_terminal_taps=True)
    outline = adjust_outline_initial(schematic)
    if outline is None:
        outline = Rect4R(0, 0, 1, 1)
    schematic.outline = outline
    return schematic.freeze()


def resolve_instance(extlib, deck, device_map, subckt_name, inst, node_to_net):
    """Resolve an instance to (child_symbol, {pin_name: net}) connections."""
    model = inst.model
    if model in device_map:
        mapping = device_map[model]
        if len(inst.nodes) != len(mapping.pin_order):
            raise SpiceImportError(
                f"Instance {inst.name!r} in {subckt_name!r}: device {model!r} expects "
                f"{len(mapping.pin_order)} nodes, got {len(inst.nodes)}.")
        kwargs = {p: R(inst.params[p]) for p in mapping.real_params if p in inst.params}
        kwargs |= {p: to_int_with_si_support(inst.params[p]) for p in mapping.int_params if p in inst.params}
        child = mapping.cell(**kwargs)
        child_sym = child.symbol
        conns = {pin: node_to_net[nd]
                 for pin, nd in zip(mapping.pin_order, inst.nodes)}
        return child_sym, conns
    if model in deck.subckts:
        child_ports = deck.subckts[model].ports
        if len(inst.nodes) != len(child_ports):
            raise SpiceImportError(
                f"Instance {inst.name!r} in {subckt_name!r}: subckt {model!r} expects "
                f"{len(child_ports)} ports, got {len(inst.nodes)}.")
        child_sym = extlib[model].symbol
        conns = {port: node_to_net[nd]
                 for port, nd in zip(child_ports, inst.nodes)}
        return child_sym, conns
    raise SpiceImportError(
        f"Instance {inst.name!r} in {subckt_name!r} references unknown model/subckt "
        f"{model!r}. Add it to device_map or include its .subckt definition.")
