# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Storage engines of ORDB subgraphs.

All subgraph storage lives in the native core (:mod:`ordec.core.ordb._ordb`),
which has two engines with identical semantics. They differ in the
tables; the directory, the indices and the transactions are shared:

- ``paged``: every table is a persistent vector of rows in pages of 16
  rows. Snapshots (freeze, thaw, copy) share pages; a write copies only the
  pages it touches.
- ``keyed``: every table is a persistent sparse array keyed by nid (leaves
  of 16 nids with an occupancy mask), without tombstones or compaction.

The selection below stays so that further engines can be tried without
re-adding it. New subgraphs use the process-wide default engine, selected
by (in order of precedence): an explicit MutableSubgraph(backend=...) /
use_backend(), the ORDEC_ORDB_BACKEND environment variable, or
BUILTIN_DEFAULT. Derived subgraphs (freeze/thaw/copy) keep the engine of
their origin.
"""

from contextlib import contextmanager
import os

from . import _ordb

class StorageBackend:
    """A storage engine: name plus the engine code of the native core."""
    __slots__ = ('name', 'code')

    def __init__(self, name: str, code: int):
        self.name = name
        self.code = code

    def __repr__(self):
        return f"StorageBackend({self.name!r})"

BUILTIN_DEFAULT = 'paged'

_registry = {
    'paged': StorageBackend('paged', _ordb.ENGINE_PAGED),
    'keyed': StorageBackend('keyed', _ordb.ENGINE_KEYED),
}
_default = None

def get_backend(name: str) -> StorageBackend:
    try:
        return _registry[name]
    except KeyError:
        raise ValueError(
            f"Unknown ORDB storage backend {name!r}."
            f" Available: {', '.join(sorted(_registry))}"
        ) from None

def available_backends() -> list[str]:
    return sorted(_registry)

def default_backend() -> StorageBackend:
    """Engine used for newly created subgraphs."""
    global _default
    if _default is None:
        _default = get_backend(os.environ.get('ORDEC_ORDB_BACKEND', BUILTIN_DEFAULT))
    return _default

@contextmanager
def use_backend(name: str):
    """Temporarily change the default engine for new subgraphs. Existing
    subgraphs keep the engine they were created with."""
    global _default
    prev = _default
    _default = get_backend(name)
    try:
        yield _default
    finally:
        _default = prev
