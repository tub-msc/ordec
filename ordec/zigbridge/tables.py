# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Wire tables for the Zig bridge: explicit per-node-type attribute lists and
value codecs mirroring the canonical CBOR format of zig/src/serialize.zig.

The tables are deliberately explicit rather than derived from the Python
attribute declarations: the wire attribute order is the *Zig* field
declaration order, which differs from Python's ``_layout`` order in places
(e.g. LayoutPath puts ``layer`` first on the wire but last in Python), and
the wire enum values are the stable integers declared in zig/src/schema.zig
and zig/src/geom.zig, not the Python enum values. The cross-language golden
hash test in tests/test_zigbridge.py pins these tables byte-for-byte.

``cell`` (Attr(Cell)) attributes have no wire representation; they are listed
as ``skip`` attributes and handled by the encoder's strip_cell policy.
"""

from fractions import Fraction

from ..core.ordb import NPath
from ..core.rational import R
from ..core.geoprim import D4, Vec2R, Vec2I, Rect4R, Rect4I
from ..core import schema


class WireError(Exception):
    """Malformed or out-of-contract wire data."""

class UnsupportedNode(WireError):
    """The subgraph contains a node type with no wire representation."""

class UnsupportedAttr(WireError):
    """A node carries a value in an attribute with no wire representation."""


# Value codecs
# ------------
#
# encode(v, ctx) returns a CBOR-ready object (built-ins + Fraction, which
# cbor2 serializes as tag 30); decode(v, ctx) validates the wire object and
# returns the Python attribute value. The encode context provides
# hash_of(frozen_subgraph) -> bytes32; the decode context provides
# deps[bytes32] -> FrozenSubgraph.
#
# Codecs reject None; wire-optional attributes (Zig ``?T`` fields and all
# reference kinds) are wrapped in Opt.

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


class Opt:
    def __init__(self, inner):
        self.inner = inner

    def encode(self, v, ctx):
        return None if v is None else self.inner.encode(v, ctx)

    def decode(self, v, ctx):
        return None if v is None else self.inner.decode(v, ctx)


class _Bool:
    def encode(self, v, ctx):
        if not isinstance(v, bool):
            raise WireError(f"expected bool, got {v!r}")
        return v

    def decode(self, v, ctx):
        if not isinstance(v, bool):
            raise WireError(f"expected bool, got {v!r}")
        return v


class _Str:
    def encode(self, v, ctx):
        if not isinstance(v, str):
            raise WireError(f"expected str, got {v!r}")
        return v

    def decode(self, v, ctx):
        if not isinstance(v, str):
            raise WireError(f"expected str, got {v!r}")
        return v


class _Int:
    """Range-checked integer (the Zig fields are fixed-width)."""

    def __init__(self, lo, hi):
        self.lo = lo
        self.hi = hi

    def encode(self, v, ctx):
        if not _is_int(v) or not (self.lo <= v <= self.hi):
            raise WireError(f"integer {v!r} outside [{self.lo}, {self.hi}]")
        return v

    decode = encode


class _Rational:
    def encode(self, v, ctx):
        if not isinstance(v, Fraction):
            raise WireError(f"expected R, got {v!r}")
        return v  # cbor2 serializes Fraction as tag 30 [num, den]

    def decode(self, v, ctx):
        if not isinstance(v, Fraction):
            raise WireError(f"expected rational (tag 30), got {v!r}")
        return R(v)


class _Struct:
    """Fixed-length array of component values (Vec2*, Rect4*, GdsLayer,
    RGBColor: Zig struct -> CBOR array of fields in declaration order)."""

    def __init__(self, ctor, components):
        self.ctor = ctor
        self.components = components

    def encode(self, v, ctx):
        if v is None or len(tuple(v)) != len(self.components):
            raise WireError(f"expected {len(self.components)} components, got {v!r}")
        return [c.encode(x, ctx) for c, x in zip(self.components, tuple(v))]

    def decode(self, v, ctx):
        if not isinstance(v, list) or len(v) != len(self.components):
            raise WireError(f"expected array of {len(self.components)}, got {v!r}")
        return self.ctor(*(c.decode(x, ctx) for c, x in zip(self.components, v)))


class _Enum:
    """Enum with explicit stable wire values (zig/src/schema.zig: 'do not
    renumber')."""

    def __init__(self, pairs):
        self.to_wire = dict(pairs)
        self.from_wire = {w: m for m, w in pairs}

    def encode(self, v, ctx):
        try:
            return self.to_wire[v]
        except KeyError:
            raise WireError(f"not an expected enum member: {v!r}")

    def decode(self, v, ctx):
        try:
            return self.from_wire[v]
        except (KeyError, TypeError):
            raise WireError(f"invalid enum wire value: {v!r}")


class _Name:
    """NPath name: tstr | int (Zig meta.Name)."""

    def encode(self, v, ctx):
        if isinstance(v, str):
            return v
        if _is_int(v) and -2**63 <= v < 2**63:
            return v
        raise WireError(f"expected str or i64 name, got {v!r}")

    decode = encode


class _Nid:
    """LocalRef / ExternalRef: stored as int nid on both sides."""

    def encode(self, v, ctx):
        if not _is_int(v) or not (0 <= v < 2**32):
            raise WireError(f"nid {v!r} outside u32")
        return v

    decode = encode


class _SubgraphRef:
    """SubgraphRef: FrozenSubgraph <-> bstr(32) content hash."""

    def encode(self, v, ctx):
        return ctx.hash_of(v)

    def decode(self, v, ctx):
        if not isinstance(v, bytes) or len(v) != 32:
            raise WireError(f"expected 32-byte hash, got {v!r}")
        try:
            return ctx.deps[v]
        except KeyError:
            raise WireError(f"missing dependency subgraph {v.hex()}")


_I16U = _Int(0, 2**16 - 1)
_I8U = _Int(0, 255)

BOOL = _Bool()
STR = _Str()
I32 = _Int(-2**31, 2**31 - 1)
RATIONAL = _Rational()
VEC2R = _Struct(Vec2R, (RATIONAL, RATIONAL))
VEC2I = _Struct(Vec2I, (I32, I32))
RECT4R = _Struct(Rect4R, (RATIONAL,) * 4)
RECT4I = _Struct(Rect4I, (I32,) * 4)
GDSLAYER = _Struct(schema.GdsLayer, (_I16U, _I16U))
RGBCOLOR = _Struct(schema.RGBColor, (_I8U,) * 3)
NAME = Opt(_Name())
REF = Opt(_Nid())  # LocalRef and ExternalRef share the wire representation
SUBREF = Opt(_SubgraphRef())

# Stable enum wire values (zig/src/geom.zig D4 declaration order;
# zig/src/schema.zig PinType / PathEndType):
D4_ENUM = _Enum([
    (D4.R0, 0), (D4.R90, 1), (D4.R180, 2), (D4.R270, 3),
    (D4.MX, 4), (D4.MY, 5), (D4.MX90, 6), (D4.MY90, 7),
])
PINTYPE = _Enum([
    (schema.PinType.In, 0), (schema.PinType.Out, 1), (schema.PinType.Inout, 2),
])
PATHEND = _Enum([
    (schema.PathEndType.Flush, 0), (schema.PathEndType.Square, 2),
    (schema.PathEndType.Custom, 4),
])


# Per-node-type wire specs
# ------------------------

class NodeSpec:
    __slots__ = ('wire_name', 'fields', 'skip')

    def __init__(self, wire_name, fields, skip=()):
        self.wire_name = wire_name
        self.fields = tuple(fields)
        self.skip = tuple(skip)


def _entry(cls, fields, skip=()):
    spec = NodeSpec(cls.__name__, fields, skip)
    # Guard against Python schema drift: every Python attribute must be
    # either on the wire or explicitly skipped. Fails at import time.
    declared = {ad.name for ad in cls.Tuple._layout}
    handled = {name for name, _ in spec.fields} | set(spec.skip)
    if declared != handled:
        raise RuntimeError(
            f"zigbridge wire table for {cls.__name__} is out of sync with "
            f"the Python schema: declared={sorted(declared)}, "
            f"handled={sorted(handled)}"
        )
    return cls, spec


# Field order is the ZIG declaration order (zig/src/schema.zig, meta.zig).
NODE_TABLE = dict((
    _entry(NPath, [('parent', REF), ('name', NAME), ('ref', REF)]),
    # LayerStack
    _entry(schema.LayerStack, [('unit', Opt(RATIONAL))], skip=('cell',)),
    _entry(schema.Layer, [
        ('gdslayer_text', Opt(GDSLAYER)),
        ('gdslayer_shapes', Opt(GDSLAYER)),
        ('style_fill', Opt(RGBCOLOR)),
        ('style_stroke', Opt(RGBCOLOR)),
        ('style_crossrect', BOOL),
        ('is_pinlayer', BOOL),
    ]),
    # Symbol
    _entry(schema.Symbol, [
        ('outline', Opt(RECT4R)),
        ('caption', Opt(STR)),
    ], skip=('cell',)),
    _entry(schema.Pin, [
        ('pintype', PINTYPE),
        ('pos', Opt(VEC2R)),
        ('align', D4_ENUM),
    ]),
    _entry(schema.SymbolPoly, []),
    _entry(schema.SymbolArc, [
        ('pos', Opt(VEC2R)),
        ('radius', Opt(RATIONAL)),
        ('angle_start', RATIONAL),
        ('angle_end', RATIONAL),
    ]),
    _entry(schema.PolyVec2R, [
        ('ref', REF),
        ('order', Opt(I32)),
        ('pos', Opt(VEC2R)),
    ]),
    # Schematic
    _entry(schema.Schematic, [
        ('symbol', SUBREF),
        ('outline', Opt(RECT4R)),
        ('default_supply', REF),
        ('default_ground', REF),
    ], skip=('cell',)),
    _entry(schema.Net, [('pin', REF), ('auto_wire', BOOL)]),
    _entry(schema.SchemPort, [
        ('ref', REF),
        ('pos', Opt(VEC2R)),
        ('align', D4_ENUM),
    ]),
    _entry(schema.SchemWire, [('ref', REF)]),
    _entry(schema.SchemInstance, [
        ('pos', Opt(VEC2R)),
        ('orientation', D4_ENUM),
        ('symbol', SUBREF),
    ]),
    _entry(schema.SchemInstanceConn, [
        ('ref', REF),
        ('here', REF),
        ('there', REF),
    ]),
    _entry(schema.SchemTapPoint, [
        ('ref', REF),
        ('pos', Opt(VEC2R)),
        ('align', D4_ENUM),
    ]),
    _entry(schema.SchemConnPoint, [('ref', REF), ('pos', Opt(VEC2R))]),
    # Layout
    _entry(schema.Layout, [
        ('symbol', SUBREF),
        ('ref_layers', SUBREF),
    ], skip=('cell',)),
    _entry(schema.LayoutLabel, [
        ('layer', REF),
        ('pos', Opt(VEC2I)),
        ('text', Opt(STR)),
    ]),
    _entry(schema.LayoutPoly, [('layer', REF)]),
    # NOTE: wire order differs from the Python declaration order here
    # (Python: endtype, ext_bgn, ext_end, width, layer):
    _entry(schema.LayoutPath, [
        ('layer', REF),
        ('endtype', PATHEND),
        ('ext_bgn', Opt(I32)),
        ('ext_end', Opt(I32)),
        ('width', Opt(I32)),
    ]),
    _entry(schema.LayoutRect, [('layer', REF), ('rect', Opt(RECT4I))]),
    _entry(schema.LayoutInstance, [
        ('pos', Opt(VEC2I)),
        ('orientation', D4_ENUM),
        ('ref', SUBREF),
    ]),
    _entry(schema.LayoutInstanceArray, [
        ('pos', Opt(VEC2I)),
        ('orientation', D4_ENUM),
        ('ref', SUBREF),
        ('cols', Opt(I32)),
        ('rows', Opt(I32)),
        ('vec_col', Opt(VEC2I)),
        ('vec_row', Opt(VEC2I)),
    ]),
    _entry(schema.LayoutPin, [('ref', REF), ('pin', REF)]),
    _entry(schema.PolyVec2I, [
        ('ref', REF),
        ('order', Opt(I32)),
        ('pos', Opt(VEC2I)),
    ]),
))


# Per-root node sets (mirrors Root.ordb_nodes in zig/src/schema.zig; NPath is
# valid in every subgraph). Used to reject foreign node types on decode.
ROOTS = {
    'LayerStack': (schema.LayerStack, (schema.Layer,)),
    'Symbol': (schema.Symbol, (
        schema.Pin, schema.SymbolPoly, schema.SymbolArc, schema.PolyVec2R,
    )),
    'Schematic': (schema.Schematic, (
        schema.Net, schema.SchemPort, schema.SchemWire, schema.SchemInstance,
        schema.SchemInstanceConn, schema.SchemTapPoint, schema.SchemConnPoint,
        schema.PolyVec2R,
    )),
    'Layout': (schema.Layout, (
        schema.LayoutLabel, schema.LayoutPoly, schema.LayoutPath,
        schema.LayoutRect, schema.LayoutInstance, schema.LayoutInstanceArray,
        schema.LayoutPin, schema.PolyVec2I,
    )),
}

# root wire name -> {node wire name -> node class}
WIRE_TABLES = {
    root_name: {
        NODE_TABLE[cls].wire_name: cls
        for cls in (root_cls,) + members + (NPath,)
    }
    for root_name, (root_cls, members) in ROOTS.items()
}
