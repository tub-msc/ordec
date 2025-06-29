# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..base import *

class PrelimSchemInstance():
    """
    SchemInstance wrapper which is holding instance information and conversion to real
    SchemInstance via the from_prelim function
    """
    # prelim_pos = ordec.attr(type=ordec.Vec2R)
    # prelim_orientation = ordec.attr(type=ordec.Orientation, default=ordec.Orientation.R0)
    # prelim_name = ordec.attr(type=str)
    # prelim_ref = ordec.attr(type=str)
    # prelim_params = ordec.attr(type=map, freezer=CheckedPMap)
    # prelim_portmap = ordec.attr(type=map, freezer=CheckedPMap)

    def __init__(self, prelim_name, prelim_ref):
        self.prelim_name = prelim_name
        self.prelim_ref = prelim_ref
        self.prelim_params = {}
        self.prelim_portmap = {}
        self.prelim_orientation = Orientation.R0
        self.prelim_pos = Vec2R(x=0, y=0)

    def from_prelim(self, ext, node):
        # get the new ref
        new_ref = ext[self.prelim_ref](**self.prelim_params).symbol
        setattr(node, self.prelim_name, SchemInstance(new_ref.portmap()))
        new_instance = getattr(node, self.prelim_name)
        # map the ports
        for source, destination in self.prelim_portmap.items():
            new_instance % SchemInstanceConn(here=destination, there=getattr(new_ref, source))
        # map the orientation
        new_instance.orientation = self.prelim_orientation
        # map the postion
        new_instance.pos = self.prelim_pos
