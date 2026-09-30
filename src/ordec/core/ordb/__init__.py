# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
ORDB, the graph database that ORDeC represents design data in.

:mod:`~ordec.core.ordb.base` holds the data model: nodes, subgraphs,
cursors, indices and the updater. Storage, indices, transactions and
constraint checks are implemented by the native core
(:mod:`ordec.core.ordb._ordb`), which offers two storage engines
(:mod:`~ordec.core.ordb.backend`).
"""

from .base import *
from .base import __all__  # star-import of the package == star-import of base
# Not public, but referenced by name from docs/ref/ordb.rst:
from .base import GenericIndex, SubgraphUpdater
from .backend import (
    StorageBackend,
    available_backends,
    default_backend,
    get_backend,
    use_backend,
)
