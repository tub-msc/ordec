# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
ORDB, the graph database that ORDeC represents design data in.

:mod:`~ordec.core.ordb.base` holds the data model: nodes, subgraphs,
cursors, indices and the updater. How a subgraph actually stores its nodes
and its index is left to a storage backend
(:mod:`~ordec.core.ordb.backend` plus the ``backend_*`` modules); the ones
registered below are what ``ORDEC_ORDB_BACKEND`` and
:func:`~ordec.core.ordb.backend.use_backend` choose between.

Registering them here, rather than in ``backend``, is what lets each
``backend_*`` module import the interface it implements.
"""

from .base import *
from .base import __all__  # star-import of the package == star-import of base
# Not public, but referenced by name from docs/ref/ordb.rst:
from .base import GenericIndex, SubgraphUpdater
from .backend import (
    BucketKind,
    StorageBackend,
    StorageTxn,
    available_backends,
    default_backend,
    get_backend,
    register_backend,
    use_backend,
)
from .backend_pyrsistent import PyrsistentBackend
from .backend_fullcopy import FullCopyBackend
from .backend_cow import CowBackend
from .backend_delta import DeltaBackend

register_backend(PyrsistentBackend(patricia=True))
register_backend(PyrsistentBackend(patricia=False))
register_backend(FullCopyBackend())
register_backend(CowBackend())
register_backend(DeltaBackend())
register_backend(DeltaBackend(auto_compact_depth=8))
