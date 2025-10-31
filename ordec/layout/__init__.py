# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from .webdata import *
from .helpers import *
from .makevias import *

# Without __all__, Sphinx does not document the imported stuff.
__all__ = [
    'makevias',
    'webdata',
    'poly_orientation',
    'expand_paths',
    'expand_rectpolys',
    'expand_rectpaths',
    'expand_rects',
    'expand_geom',
    'flatten',
    'expand_instancearrays',
    'write_gds',
]
