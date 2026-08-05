# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from enum import Enum
from public import public

from ..geoprim import *
from ..ordb import *
from ..context import ViewBuilder
from .base import coerce_tuple
from .schematic import Schematic, Net, SchemInstance
from .layout import Layout

WIRE_DOMAIN = 7 << 16

@public
class LvsStatus(Enum):
    """Status of an LVS comparison item or circuit pair, following KLayout's
    LVSDB status vocabulary (see dbLayoutVsSchematicFormatDefs.h)."""
    Match = 'match'
    #: Paired, but the comparison failed (KLayout '0'), e.g. paired nets
    #: whose connectivity differs.
    Mismatch = 'mismatch'
    #: No correspondence found on the other side (KLayout 'X').
    NoMatch = 'nomatch'
    #: Matched with warning (KLayout 'W'): a device that matched topologically
    #: but with deviating parameters, or an ambiguous net/pin/subcircuit match
    #: (e.g. between topologically symmetric nets).
    MatchWarning = 'warning'
    #: Not compared (KLayout 'S'), e.g. a circuit pair whose subcircuits
    #: already failed to compare.
    Skipped = 'skipped'

    def __repr__(self):
        return f'{self.__class__.__name__}.{self.name}'


@public
class LvsItemType(Enum):
    """Type of LVS comparison item."""
    Net = 'net'
    Device = 'device'
    Pin = 'pin'
    Subcircuit = 'subcircuit'

    def __repr__(self):
        return f'{self.__class__.__name__}.{self.name}'


@public
class LvsReport(SubgraphRoot):
    """LVS report containing layout vs. schematic comparison results."""
    view_builder = ViewBuilder
    wire_id = WIRE_DOMAIN | 1

    ref_layout = SubgraphRef(Layout, optional=True)
    ref_schematic = SubgraphRef(Schematic, optional=True)
    top_cell = Attr(str)
    status = Attr(LvsStatus)

    def clean(self):
        return self.status in (LvsStatus.Match, LvsStatus.MatchWarning)

    def webdata(self, ept):
        from ...layout.lvs import webdata
        return webdata(self, ept)


@public
class LvsCircuitPair(Node):
    """Comparison record for a layout cell vs schematic cell pair."""
    in_subgraphs = [LvsReport]
    wire_id = WIRE_DOMAIN | 2

    #: Direct ref to the Layout being compared. Only set for top-level circuit
    #: (where LVSDB cell name matches top_cell); None for subcircuits.
    ref_layout = SubgraphRef(Layout, optional=True)
    #: Direct ref to the Schematic being compared. Only set for top-level.
    ref_schematic = SubgraphRef(Schematic, optional=True)

    status = Attr(LvsStatus)
    message = Attr(str, optional=True)

    layout_cell = Attr(str, optional=True)
    schem_cell = Attr(str, optional=True)


@public
class LvsItem(Node):
    """Individual LVS comparison item (net, device, pin, or subcircuit)."""
    in_subgraphs = [LvsReport]
    wire_id = WIRE_DOMAIN | 3

    circuit = LocalRef(LvsCircuitPair, optional=False)
    circuit_idx = Index(circuit)

    item_type = Attr(LvsItemType)
    status = Attr(LvsStatus)

    # Layout device position from LVSDB in database units. GDS SRef records
    # are unnamed, so the LVSDB only provides a location for extracted devices.
    layout_pos = Attr(Vec2I, factory=coerce_tuple(Vec2I, 2), optional=True)
    layout_params = Attr(tuple, optional=True)

    # Schematic side: Net for pins/nets, SchemInstance for devices.
    # Only resolves when circuit.ref_schematic is set (top-level circuit).
    schem = ExternalRef(Net|SchemInstance,
        of_subgraph=lambda c: c.circuit.ref_schematic,
        optional=True)
    # Schematic side: reference device parameters (W, L, etc.)
    schem_params = Attr(tuple, optional=True)

    message = Attr(str, optional=True)

    layout_name = Attr(str, optional=True)
    schem_name = Attr(str, optional=True)
