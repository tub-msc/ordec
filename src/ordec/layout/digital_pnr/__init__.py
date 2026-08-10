# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
A gridded standard-cell place-and-route engine: cells into abutted rows, then
all signal nets routed on a track grid by negotiated congestion.

The engine is PDK-agnostic. Every pitch, layer and DRC dimension arrives in a
:class:`PnrTarget`, which :mod:`ordec.lib.ihp130_pnr` builds for the IHP sg13g2
standard cells.
"""

from .flow import (GridConfig, PnrResult, PnrTarget, RoutingStack,
    place_and_route, run_pnr)
from .route import PinAccessError

__all__ = [
    'GridConfig',
    'PnrResult',
    'PnrTarget',
    'PinAccessError',
    'RoutingStack',
    'place_and_route',
    'run_pnr',
]
