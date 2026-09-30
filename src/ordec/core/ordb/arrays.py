# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Array form of node rows, for node types declaring Node.arrayable = True.

A row is array-representable if none of its attribute values is None (and
all ints fit into int64). In
array form, each attribute is an int64 column: shape (n,) for ints and nids,
(n, width) for value types such as Rect4I. Rows are ordered by ascending
nid, which is also the order of the node type's NType index bucket.

SubgraphUpdater.insert_array() is equivalent to inserting the same rows one
by one with add_single() in the same transaction; Subgraph.arrays() returns
what iterating all(ntype) would read. Backends may store array rows natively
(cow-arrays); for all other backends, the functions below implement both
via the per-row path.
"""

import numpy as np

from .base import (NodeTuple, NodeTupleAttrDescriptor, LocalRef, ExternalRef,
    Node, SubgraphRoot, ModelViolation, DanglingLocalRef, DanglingExternalRef)

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
    their default; there must be no None values.
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

def make_tuple(ntype, fields, values) -> NodeTuple:
    """
    Builds the NodeTuple of one array row from Python ints (values: one
    list of ints per field). Bypasses the attribute factories: values were
    validated by normalize().
    """
    vals = [None] * len(ntype.Tuple._layout)
    for f, v in zip(fields, values):
        vals[f.index] = v if f.width == 1 else tuple.__new__(f.vtype, v)
    return tuple.__new__(ntype.Tuple, vals)

def iter_tuples(ntype, cols) -> 'Iterable[NodeTuple]':
    """NodeTuples of all rows of the given columns (without 'nid')."""
    fields = array_fields(ntype)
    per_field = [cols[f.name].tolist() for f in fields]
    for values in zip(*per_field):
        yield make_tuple(ntype, fields, values)

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

def gather(subgraph, ntype, partial: bool=False) -> dict:
    """
    Generic (per-row) implementation of Subgraph.arrays(). With partial,
    rows that are not array-representable are skipped instead of raising
    ValueError.
    """
    fields = array_fields(ntype)
    nids = []
    rows = []
    for nid in subgraph.all(ntype, wrap_cursor=False):
        values = row_values(fields, subgraph.nodes[nid])
        if values is None:
            if partial:
                continue
            raise ValueError(f"{ntype.__name__} nid={nid} has None values"
                " and cannot be represented as array.")
        nids.append(nid)
        rows.append(values)
    return columns(fields, nids, rows)

def columns(fields, nids, rows) -> dict:
    """Builds read-only int64 columns from Python row lists."""
    ret = {'nid': np.array(nids, dtype=np.int64)}
    for i, f in enumerate(fields):
        shape = (len(rows),) if f.width == 1 else (len(rows), f.width)
        ret[f.name] = np.array([r[i] for r in rows], dtype=np.int64).reshape(shape)
    for a in ret.values():
        a.flags.writeable = False
    return ret

def check_rows(sgu, ntype, nids, cols):
    """
    Vectorized equivalent of NodeTuple.check_constraints plus the subgraph
    membership check of SubgraphUpdater.__exit__, for array rows.
    """
    root_cls = sgu.nodes[0]._cursor_type
    if not any(issubclass(root_cls, cls) for cls in ntype.in_subgraphs):
        raise ModelViolation(f"{ntype.__name__} is not permitted in subgraph {root_cls.__name__}.")
    if len(nids) == 0:
        return
    for f in array_fields(ntype):
        attr = f.attr
        if isinstance(attr, ExternalRef):
            # of_subgraph is evaluated once for all rows: for array rows it
            # must depend on the subgraph (root) only, not on the row.
            cursor = sgu.cursor_at(int(nids[0]), lookup_npath=False)
            root = attr.of_subgraph(cursor)
            if not isinstance(root, SubgraphRoot):
                raise ModelViolation(f"ExternalRef {ntype.__name__}.{f.name}"
                    " could not resolve its referenced subgraph.")
            target_nodes = root.subgraph.nodes
            for ref in np.unique(cols[f.name]).tolist():
                try:
                    target = target_nodes[ref]
                except KeyError:
                    raise DanglingExternalRef(ref) from None
                if not attr.refcheck(target._cursor_type):
                    raise ModelViolation(f"ExternalRef invalid reference"
                        f" {f.name}={ref} ({target._cursor_type.__name__}) in {ntype.__name__}.")
        elif isinstance(attr, LocalRef):
            for ref in np.unique(cols[f.name]).tolist():
                try:
                    target = sgu.nodes[ref]
                except KeyError:
                    raise DanglingLocalRef(ref) from None
                if not attr.refcheck(target._cursor_type):
                    raise ModelViolation(f"LocalRef invalid reference"
                        f" {f.name}={ref} ({target._cursor_type.__name__}) in {ntype.__name__}.")
