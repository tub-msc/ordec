# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from public import public

from ..rational import R
from ..ordb import *
from ..context import ViewBuilder
from .schematic import Schematic, Net
from .layout import Layout

WIRE_DOMAIN = 9 << 16

@public
class PexReport(SubgraphRoot):
    """
    Result of a parasitic extraction: the Schematic extracted from a Layout
    and the parasitics of its nets.
    """
    view_builder = ViewBuilder
    wire_id = WIRE_DOMAIN | 1

    ref_layout = SubgraphRef(Layout)
    #: The devices of ref_layout with their parasitics as ideal Res and Cap
    #: instances, to simulate in place of the schematic of its cell (see
    #: SimHierarchy.from_schematic). It has no positions and cannot be drawn.
    schematic = SubgraphRef(Schematic)

    def net(self, net: Net) -> 'PexNet':
        """Returns the PexNet of a labelled Net of schematic, e.g. of schematic.vdd."""
        return self.one(PexNet.net_idx.query(net))

    def webdata_static(self):
        from ...layout.pex import webdata
        return webdata(self)


@public
class PexNet(Node):
    """
    A net of the layout. The extraction splits it into the nodes of its
    resistor network, each of which is a Net of the extracted schematic.
    """
    in_subgraphs = [PexReport]
    wire_id = WIRE_DOMAIN | 2

    #: The node of the net that has its name: the one with the label.
    net = ExternalRef(Net, of_subgraph=lambda c: c.root.schematic, optional=False)
    net_idx = Index(net, unique=True)
    nodes = Attr(int) #: Number of nodes
    resistors = Attr(int) #: Number of parasitic resistors between the nodes
    capacitance = Attr(R) #: Total capacitance to the other nets


@public
class PexCoupling(Node):
    """Parasitic capacitance between two nets."""
    in_subgraphs = [PexReport]
    wire_id = WIRE_DOMAIN | 3

    a = LocalRef(PexNet, optional=False)
    b = LocalRef(PexNet, optional=False)
    capacitance = Attr(R)
