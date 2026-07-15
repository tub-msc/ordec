# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Toy node schema for the benchmark workloads (see the "Schema" section of
docs/dev/ordb_benchmark_workloads.rst).

The types mirror the shapes of the real ORDeC design schema (Symbol,
Schematic, Layout, SimHierarchy) but carry only int/str attributes, so the
schema is trivially replicable in other languages (no Rational, no Vec2R).
"""

from ordec.core.ordb import (
    SubgraphRoot, Node, NonLeafNode, Attr, LocalRef, ExternalRef,
    SubgraphRef, Index, CombinedIndex,
)

# Symbol-like subgraph (mirrors ordec.core.schema Symbol/Pin/SymbolPoly)
# ----------------------------------------------------------------------

class SymRoot(SubgraphRoot):
    pass

class SymPin(Node):
    in_subgraphs = [SymRoot]
    num = Attr(int)

class SymPoly(Node):
    in_subgraphs = [SymRoot]
    layer = Attr(int)

class SymVertex(Node):
    in_subgraphs = [SymRoot]
    ref = LocalRef(SymPoly, optional=False)
    order = Attr(int)
    x = Attr(int)
    y = Attr(int)

    ref_idx = Index(ref, sortkey=lambda node: node.order)

# Schematic-like subgraph (mirrors Schematic/Net/SchemInstance/InstanceConn)
# --------------------------------------------------------------------------

class SchRoot(SubgraphRoot):
    pass

class SchNet(Node):
    in_subgraphs = [SchRoot]
    w = Attr(int)

class SchInst(Node):
    in_subgraphs = [SchRoot]
    sym = SubgraphRef(SymRoot)
    x = Attr(int)
    y = Attr(int)

class SchConn(Node):
    """Connects one pin of one instance to a net, like SchemInstanceConn:
    LocalRef to the instance, ExternalRef into the instance's symbol."""
    in_subgraphs = [SchRoot]
    ref = LocalRef(SchInst, optional=False)
    pin = ExternalRef(SymPin, of_subgraph=lambda node: node.ref.sym, optional=False)
    net = LocalRef(SchNet, optional=False)

    ref_idx = Index(ref)
    ref_pin_idx = CombinedIndex([ref, pin], unique=True)

# Layout-like subgraph (mirrors Layout/LayoutRect/LayoutPoly/LayoutInstance)
# --------------------------------------------------------------------------

class LayRoot(SubgraphRoot):
    kind = Attr(int)

class LRect(Node):
    in_subgraphs = [LayRoot]
    layer = Attr(int)
    lx = Attr(int)
    ly = Attr(int)
    ux = Attr(int)
    uy = Attr(int)

class LPoly(Node):
    in_subgraphs = [LayRoot]
    layer = Attr(int)

class LVertex(Node):
    in_subgraphs = [LayRoot]
    ref = LocalRef(LPoly, optional=False)
    order = Attr(int)
    x = Attr(int)
    y = Attr(int)

    ref_idx = Index(ref, sortkey=lambda node: node.order)

class LLabel(Node):
    in_subgraphs = [LayRoot]
    layer = Attr(int)
    x = Attr(int)
    y = Attr(int)
    text = Attr(str)

class LInst(Node):
    in_subgraphs = [LayRoot]
    sub = SubgraphRef(LayRoot)
    dx = Attr(int)
    dy = Attr(int)

# SimHierarchy-like subgraph (mirrors SimInstance/SimNet/SimParam)
# -----------------------------------------------------------------

class SimRoot(SubgraphRoot):
    pass

class SimGroup(NonLeafNode):
    """Hierarchy level, like SimInstance (NonLeaf: groups nest via NPath)."""
    in_subgraphs = [SimRoot]
    depth = Attr(int)

class SimItem(Node):
    """Per-group named entry with a unique (group, key) constraint, like
    SimNet's parent_eref_idx."""
    in_subgraphs = [SimRoot]
    group = LocalRef(SimGroup, optional=False)
    key = Attr(str)

    group_key_idx = CombinedIndex([group, key], unique=True)

class SimAnnot(Node):
    """Back-annotation attached to a SimItem, like SimParam."""
    in_subgraphs = [SimRoot]
    target = LocalRef(SimItem, optional=False)
    value = Attr(int)

# Plain chain subgraph for snapshot/generation workloads
# ------------------------------------------------------

class ChainRoot(SubgraphRoot):
    pass

class CNode(Node):
    in_subgraphs = [ChainRoot]
    tag = Attr(int)
    val = Attr(int)

    tag_idx = Index(tag)

# Micro-benchmark subgraph (from the former tests/bench_ordb_index.py)
# --------------------------------------------------------------------

class MicroRoot(SubgraphRoot):
    pass

class Box(Node):
    in_subgraphs = [MicroRoot]
    val = Attr(int)

class MPoly(Node):
    in_subgraphs = [MicroRoot]
    val = Attr(int)

class UNode(Node):
    """Node with a unique index, for the transaction-abort micro."""
    in_subgraphs = [MicroRoot]
    val = Attr(int)

    val_idx = Index(val, unique=True)
