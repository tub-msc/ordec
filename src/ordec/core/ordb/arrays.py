# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Array form of node rows, for node types declaring Node.arrayable = True.

A row is array-representable if none of its attribute values is None (and
all ints fit into int64). In array form, each attribute is an int64
column: shape (n,) for ints and nids, (n, width) for value types such as
Rect4I. Rows are ordered by ascending nid.

SubgraphUpdater.insert_array() is equivalent to inserting the same rows one
by one with add_single() in the same transaction; Subgraph.arrays() returns
what iterating all(ntype) would read. Both are served by the native core
directly from and into its tables.
"""

import numpy as np

from .base import Node

def array_fields(ntype):
    fields = ntype.Tuple._array_layout
    if fields is None:
        raise TypeError(f"{ntype.__name__} is not arrayable.")
    return fields

def normalize(ntype, values: dict) -> tuple[int, dict]:
    """
    Converts insert_array() keyword values into int64 columns. Each value
    is either an array-like with one row per node or a scalar (int, Node or
    value such as Rect4I) applied to all rows. Attributes not given use
    their default; there must be no None values and no values outside the
    int64 range.
    """
    fields = array_fields(ntype)
    unknown = values.keys() - {f.name for f in fields}
    if unknown:
        raise AttributeError(f"Unknown attributes provided: {', '.join(sorted(unknown))}")

    n = None
    cols = {}
    scalars = {}
    for f in fields:
        v = values.get(f.name, f.attr.default)
        if v is None:
            raise ValueError(f"{ntype.__name__}.{f.name}: None cannot be"
                " inserted as array (use add_single for such rows).")
        if isinstance(v, Node):
            v = v.nid
        is_scalar = isinstance(v, int) if f.width == 1 else isinstance(v, f.vtype)
        a = np.asarray(v)
        if a.dtype.kind not in 'iu':
            raise TypeError(f"{ntype.__name__}.{f.name}: expected integer values,"
                f" got dtype {a.dtype}.")
        if a.dtype == np.uint64 and a.size and a.max() > INT64_MAX:
            # astype would wrap these to negative values.
            raise ValueError(f"{ntype.__name__}.{f.name}: values exceed the"
                " int64 range.")
        a = a.astype(np.int64, copy=False)
        if is_scalar:
            scalars[f] = a
            continue
        expected_ndim = 1 if f.width == 1 else 2
        if a.ndim != expected_ndim or (f.width > 1 and a.shape[1] != f.width):
            raise ValueError(f"{ntype.__name__}.{f.name}: expected shape"
                f" {'(n,)' if f.width == 1 else f'(n, {f.width})'}, got {a.shape}.")
        if n is None:
            n = len(a)
        elif len(a) != n:
            raise ValueError(f"{ntype.__name__}.{f.name}: length {len(a)}"
                f" differs from other columns ({n}).")
        cols[f.name] = a
    if n is None:
        raise ValueError("insert_array needs at least one array value.")
    for f, a in scalars.items():
        cols[f.name] = np.broadcast_to(a, (n,) if f.width == 1 else (n, f.width))
    cols = {f.name: cols[f.name] for f in fields} # layout order
    for f in fields:
        check = getattr(f.vtype, 'array_check', None)
        if check is not None:
            check(cols[f.name])
    return n, cols

INT64_MIN = -2**63
INT64_MAX = 2**63 - 1

def row_values(fields, node) -> list|None:
    """
    Array values of one NodeTuple, or None if it is not representable
    (None values or ints outside the int64 range).
    """
    ret = []
    for f in fields:
        v = node[f.index]
        if v is None:
            return None
        if f.width == 1:
            if not INT64_MIN <= v <= INT64_MAX:
                return None
        elif not all(INT64_MIN <= x <= INT64_MAX for x in v):
            return None
        ret.append(v)
    return ret

def array_columns(subgraph, ntype, partial: bool=False) -> tuple[bytes, list[bytes]]:
    """
    The nids and the attribute columns (layout order) of a node type as
    bytes of native int64, rows ordered by nid; see arrays() for partial.
    Memoized for frozen subgraphs.
    """
    array_fields(ntype)
    if subgraph.mutable:
        return subgraph._arrays(ntype.Tuple, partial)
    memo = subgraph._cached_arrays
    if memo is None:
        memo = subgraph._cached_arrays = {}
    key = (ntype.Tuple, partial)
    try:
        return memo[key]
    except KeyError:
        ret = memo[key] = subgraph._arrays(ntype.Tuple, partial)
        return ret

def arrays(subgraph, ntype, partial: bool=False) -> dict:
    """
    Backend of Subgraph.arrays(): read-only int64 arrays 'nid' plus one per
    attribute, rows ordered by nid. With partial, rows that are not
    array-representable are skipped instead of raising ValueError.
    """
    fields = array_fields(ntype)
    nids, cols = array_columns(subgraph, ntype, partial)
    ret = {'nid': np.frombuffer(nids, dtype=np.int64)}
    for f, b in zip(fields, cols):
        a = np.frombuffer(b, dtype=np.int64)
        ret[f.name] = a if f.width == 1 else a.reshape(-1, f.width)
    return ret
