# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from .webdata import *
from .helpers import *
from .makevias import *
from .gds_out import *

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
    'gds_str',
    'gds_str_from_file',
    'gds_str_from_layout',
]
