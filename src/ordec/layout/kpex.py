# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import json
import logging
import shlex
import subprocess
from collections import Counter
from pathlib import Path

from public import public

from ..core import *
from ..schematic.spice_in import parse_deck, add_subckt, spice_number

logger = logging.getLogger(__name__)


@public
class KpexError(Exception):
    pass


def run(cwd, pdk: str, gds, cell: str, mode: str = 'RC'):
    """
    Run the 2.5D engine of KLayout-PEX (kpex) in directory 'cwd'. The
    extracted netlist is written to pex.spice, the output of kpex to
    kpex.log.

    Args:
        pdk: Name of the technology in kpex, which brings its own LVS deck
            and process stack for it.
        gds: GDS file name (relative to cwd).
        cell: Name of the cell to extract.
        mode: 'CC' extracts capacitances, 'R' resistances, 'RC' both.

    Raises:
        KpexError: kpex failed; the message has the errors it reported.
    """
    cmdline = ['kpex', 'extract', '--pdk', pdk, '--gds', str(gds),
        '--cell', cell, '--2.5D', '--mode', mode,
        # Devices with a model of their own (e.g. MIM capacitors) stay
        # devices instead of being extracted as parasitics.
        '--blackbox', 'y',
        '--out-dir', 'kpex', '--out-netlist', 'pex.spice',
        '--out-result', 'kpex.json', '--log-level', 'error']
    logger.debug("%s %s", cwd, shlex.join(cmdline))
    cwd = Path(cwd)
    # The files of an earlier run would hide that this run wrote none.
    for name in ('kpex.json', 'pex.spice'):
        (cwd / name).unlink(missing_ok=True)
    with open(cwd / 'kpex.log', 'w') as f:
        ret = subprocess.run(cmdline, cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=f, stderr=subprocess.STDOUT)
    if ret.returncode != 0:
        try:
            result = json.loads((cwd / 'kpex.json').read_text())
        except FileNotFoundError:
            # kpex stopped before it wrote its result file.
            raise KpexError((cwd / 'kpex.log').read_text()[-2000:]) from None
        message = "\n".join(result['errors'] + (result['check_problems'] or []))
        raise KpexError(message or (cwd / 'kpex.log').read_text()[-2000:])


def read_netlist(path, layout: Layout, directory: Directory, device_map: dict) -> PexReport:
    """
    Read the netlist of a kpex run as a PexReport. Its schematic is a
    Schematic of the cell of layout: the devices become the cells of
    device_map, the parasitics ideal Res and Cap. It has no positions, ports
    or wires, so it cannot be drawn.

    Args:
        path: Path to the netlist, which has one subcircuit.
        layout: The extracted Layout. Its symbol becomes the symbol of the
            schematic.
        directory: The Directory that write_gds named the pins of layout
            with.
        device_map: SPICE model name ->
            ordec.schematic.spice_in.DeviceMapping.

    Raises:
        KpexError: The ports of the netlist do not match the pins of the
            symbol.
    """
    deck = parse_deck(Path(path).read_text())
    (subckt,) = deck.subckts.values()
    symbol = layout.symbol

    # The extraction splits a net of the layout into the nodes of its
    # resistor network. The nodes that R cards connect are therefore grouped
    # into one net again (union-find).
    group = {}

    def find(node):
        while group.setdefault(node, node) != node:
            group[node] = group[group[node]]
            node = group[node]
        return node

    for inst in subckt.instances:
        if inst.prefix == 'R':
            group[find(inst.nodes[0])] = find(inst.nodes[1])

    # kpex names the substrate sub! if no label is on it.
    if 'sub!' in subckt.ports:
        raise KpexError("The substrate of the layout connects to no pin, so "
            "it would float in a simulation.")

    # kpex also makes ports of nets that were pins of flattened subcells.
    # These have no pin here and become internal nets.
    pins = {}
    net_of_pin = {}
    pin_of_net = {}
    for port in subckt.ports:
        # KLayout joins the labels of a net with '|'. With resistances, each
        # label is a port of the resistor network instead.
        for name in port.split('|'):
            try:
                pin = directory.node_of_name(symbol, name)
            except KeyError:
                continue
            net = find(port)
            other = pin_of_net.setdefault(net, pin)
            if other != pin:
                raise KpexError(f"The layout shorts the pins "
                    f"{other.full_path_str()} and {pin.full_path_str()}.")
            if net_of_pin.setdefault(pin, net) != net:
                raise KpexError(f"Two nets of the layout have the label of pin "
                    f"{pin.full_path_str()}.")
            # Only one node of the net gets the pin.
            if pin not in pins.values():
                pins[port] = pin
    missing = set(symbol.all(Pin)) - set(pins.values())
    if missing:
        raise KpexError("The layout has no net with the label of pin "
            + ", ".join(sorted(pin.full_path_str() for pin in missing)) + ".")

    schematic = Schematic(cell=layout.cell, symbol=symbol)
    net_of_node = add_subckt(schematic, None, deck, subckt, device_map, pins)
    report = PexReport(ref_layout=layout, schematic=schematic.freeze())

    nodes = Counter(find(node) for node in net_of_node)
    resistors = Counter(find(inst.nodes[0]) for inst in subckt.instances if inst.prefix == 'R')
    couplings = Counter()
    capacitance = Counter()
    for inst in subckt.instances:
        if inst.prefix == 'C':
            a, b = sorted(find(node) for node in inst.nodes)
            if a != b:
                c = spice_number(inst.model)
                couplings[a, b] += c
                capacitance[a] += c
                capacitance[b] += c

    # kpex gives the node with the label the name of the net and appends
    # a number and the layer to it for the other nodes, so the shortest name
    # in a group is the one of the net. The node with the pin wins over the
    # nodes of other labels.
    name = {}
    for node in net_of_node:
        g = find(node)
        if g not in name or len(node) < len(name[g]):
            name[g] = node
    name |= {find(port): port for port in pins}
    pexnet = {g: report % PexNet(net=net_of_node[name[g]].nid, nodes=nodes[g],
        resistors=resistors[g], capacitance=R(capacitance[g])) for g in name}
    for (a, b), c in couplings.items():
        report % PexCoupling(a=pexnet[a], b=pexnet[b], capacitance=c)
    return report
