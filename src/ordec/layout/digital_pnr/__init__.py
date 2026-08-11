# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
A gridded standard-cell place-and-route engine: cells into abutted rows, then
all signal nets routed on a track grid by negotiated congestion.

The engine is PDK-agnostic. Every pitch, layer and DRC dimension arrives as an
explicit parameter of :func:`place_and_route`, which :mod:`ordec.lib.ihp130`
supplies for the IHP sg13g2 standard cells.
"""

from .flow import (GridConfig, PnrResult, place_and_route)
from .route import PinAccessError

__all__ = [
    'GridConfig',
    'PnrResult',
    'PinAccessError',
    'place_and_route',
]
