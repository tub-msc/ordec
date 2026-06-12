// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! A Zig re-implementation of ORDeC's ORDB graph database and a
//! subset of its schema (Symbol, Schematic, Layout, LayerStack).

pub const rational = @import("rational.zig");
pub const geom = @import("geom.zig");
pub const meta = @import("meta.zig");
pub const subgraph = @import("subgraph.zig");
pub const schema = @import("schema.zig");
pub const cbor = @import("cbor.zig");
pub const serialize = @import("serialize.zig");
pub const placer = @import("placer.zig");

pub const Nid = meta.Nid;
pub const Str = meta.Str;
pub const Name = meta.Name;
pub const NPath = meta.NPath;
pub const FrozenHeader = meta.FrozenHeader;
pub const LocalRef = meta.LocalRef;
pub const ExternalRef = meta.ExternalRef;
pub const SubgraphRef = meta.SubgraphRef;
pub const idx = meta.idx;
pub const Subgraph = subgraph.Subgraph;
pub const Diag = subgraph.Diag;

pub const R = rational.R;
pub const D4 = geom.D4;
pub const Vec2R = geom.Vec2R;
pub const Vec2I = geom.Vec2I;
pub const Rect4R = geom.Rect4R;
pub const Rect4I = geom.Rect4I;
pub const TD4R = geom.TD4R;
pub const TD4I = geom.TD4I;

test {
    _ = rational;
    _ = geom;
    _ = meta;
    _ = subgraph;
    _ = schema;
    _ = cbor;
    _ = serialize;
    _ = placer;
    _ = @import("subgraph_test.zig");
    _ = @import("serialize_test.zig");
}
