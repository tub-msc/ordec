# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Canonical subgraph checksum for cross-backend and cross-world validation
(see the "Checksum" section of docs/dev/ordb_benchmark_workloads.rst). Uses only
the public subgraph API, so it
works with every storage backend.

FNV-1a 64-bit over the canonical serialization:

  for each nid in ascending order:
      u64le(nid)
      u32le(len(typename)) ++ typename utf-8   (canonical Node class name)
      for each attribute in tuple layout order, tagged:
          0x00                        -- None
          0x01 ++ i64le(value)        -- int
          0x02 ++ u32le(len) ++ utf8  -- str
          0x03 ++ u64le(nid)          -- LocalRef
          0x04 ++ u64le(nid)          -- ExternalRef
          0x05 ++ u64le(checksum)     -- SubgraphRef (recursive checksum)
  finally u64le(nid_alloc.start)
"""

import struct

from ordec.core.ordb import LocalRef, ExternalRef, SubgraphRef

FNV_OFFSET = 0xcbf29ce484222325
FNV_PRIME = 0x100000001b3
_MASK64 = (1 << 64) - 1

def _fnv1a(data: bytes, h: int) -> int:
    for byte in data:
        h = ((h ^ byte) * FNV_PRIME) & _MASK64
    return h

def checksum_subgraph(subgraph, _memo=None) -> int:
    """Checksum of one subgraph (Subgraph or SubgraphRoot cursor)."""
    if hasattr(subgraph, 'subgraph'): # accept root cursors
        subgraph = subgraph.subgraph
    if _memo is None:
        _memo = {}
    key = id(subgraph)
    if key in _memo:
        return _memo[key]

    parts = []
    for nid in sorted(subgraph.nodes):
        node = subgraph.nodes[nid]
        typename = node._cursor_type.__name__.encode()
        parts.append(struct.pack('<QI', nid, len(typename)))
        parts.append(typename)
        for ad in node._layout:
            val = node[ad.index]
            if val is None:
                parts.append(b'\x00')
            elif isinstance(ad.attr, LocalRef):
                parts.append(struct.pack('<BQ', 0x03, val))
            elif isinstance(ad.attr, ExternalRef):
                parts.append(struct.pack('<BQ', 0x04, val))
            elif isinstance(ad.attr, SubgraphRef):
                parts.append(struct.pack('<BQ', 0x05, checksum_subgraph(val, _memo)))
            elif isinstance(val, int):
                parts.append(struct.pack('<Bq', 0x01, val))
            elif isinstance(val, str):
                raw = val.encode()
                parts.append(struct.pack('<BI', 0x02, len(raw)))
                parts.append(raw)
            else:
                raise TypeError(
                    f"Unsupported attribute type for checksum: {type(val).__name__}"
                    f" ({node._cursor_type.__name__}.{ad.name})")
    parts.append(struct.pack('<Q', subgraph.nid_alloc.start))

    h = _fnv1a(b''.join(parts), FNV_OFFSET)
    _memo[key] = h
    return h

def checksum_result(final) -> str:
    """
    Checksum of a workload's final state: a subgraph or a list of subgraphs
    (list: FNV-1a over the concatenated u64le per-subgraph checksums).
    """
    if isinstance(final, (list, tuple)):
        memo = {}
        h = _fnv1a(
            b''.join(struct.pack('<Q', checksum_subgraph(sg, memo)) for sg in final),
            FNV_OFFSET)
    else:
        h = checksum_subgraph(final)
    return f"fnv1a64:{h:#018x}"
