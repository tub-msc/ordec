// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! ORDeC schema subset: LayerStack, Symbol, Schematic and Layout, ported
//! from ordec.core.schema. SimHierarchy, Report, DRC/LVS and RoutingSpec are
//! not ported (adding them later only requires defining further node structs
//! and roots). The `cell` (Attr(Cell)) and `resolver`/`value` (Attr(object))
//! attributes of the Python schema are deliberately not recreated, nor are
//! the SchemInstanceUnresolved* node types and the constraint-solver
//! (ConstrainableAttr) machinery.
//!
//! Enum integer values (PinType, PathEndType, D4) are part of the
//! serialization format -- do not renumber.

const std = @import("std");
const Allocator = std.mem.Allocator;
const meta = @import("meta.zig");
const sg = @import("subgraph.zig");
const geom = @import("geom.zig");
const rational = @import("rational.zig");

const R = rational.R;
const Vec2R = geom.Vec2R;
const Vec2I = geom.Vec2I;
const Rect4R = geom.Rect4R;
const Rect4I = geom.Rect4I;
const TD4R = geom.TD4R;
const TD4I = geom.TD4I;
const D4 = geom.D4;

const Nid = meta.Nid;
const Str = meta.Str;
const LocalRef = meta.LocalRef;
const ExternalRef = meta.ExternalRef;
const SubgraphRef = meta.SubgraphRef;
const FrozenHeader = meta.FrozenHeader;
const idx = meta.idx;

pub const Subgraph = sg.Subgraph;

// Enums and small value types
// ---------------------------

pub const PinType = enum(u8) {
    in = 0,
    out = 1,
    inout = 2,
};

/// Path end style ("linecap"). Values match the Python enum (GDS pathtype).
pub const PathEndType = enum(u8) {
    flush = 0,
    square = 2,
    custom = 4,
};

pub const GdsLayer = struct {
    layer: u16,
    data_type: u16,
};

pub const RGBColor = struct {
    r: u8,
    g: u8,
    b: u8,
};

// of_subgraph resolvers (the Python of_subgraph lambdas)
// ------------------------------------------------------

/// lambda c: c.root.symbol
fn ofRootSymbol(view: anytype, nid: Nid) ?*FrozenHeader {
    _ = nid;
    return view.rootValue().symbol.ptr;
}

/// lambda c: c.root.ref_layers
fn ofRootRefLayers(view: anytype, nid: Nid) ?*FrozenHeader {
    _ = nid;
    return view.rootValue().ref_layers.ptr;
}

/// lambda c: c.ref.symbol (SchemInstanceConn -> SchemInstance.symbol)
fn ofConnInstSymbol(view: anytype, nid: Nid) ?*FrozenHeader {
    const conn = view.getNodeAs(SchemInstanceConn, nid) orelse return null;
    const inst_nid = conn.ref.nid orelse return null;
    const inst = view.getNodeAs(SchemInstance, inst_nid) orelse return null;
    return inst.symbol.ptr;
}

// LayerStack
// ----------

pub const LayerStack = struct {
    unit: ?R = null,

    pub const ordb_nodes = .{Layer};
};

pub const Layer = struct {
    gdslayer_text: ?GdsLayer = null,
    gdslayer_shapes: ?GdsLayer = null,
    style_fill: ?RGBColor = null,
    style_stroke: ?RGBColor = null,
    style_crossrect: bool = false,
    /// Whether this layer is suitable for pin shapes / text.
    is_pinlayer: bool = false,

    pub const ordb_indexes = .{
        .gdslayer_text_idx = idx(&.{"gdslayer_text"}, .{ .unique = true }),
        .gdslayer_shapes_idx = idx(&.{"gdslayer_shapes"}, .{ .unique = true }),
    };
};

pub const LayerStackSG = Subgraph(LayerStack);

/// The layer on which pin shapes for `layer` should be placed: the layer
/// itself if is_pinlayer, else its "pin" NPath child (e.g. metal1.pin).
pub fn pinLayer(layer: LayerStackSG.Cursor(Layer)) !LayerStackSG.Cursor(Layer) {
    if (layer.get().is_pinlayer) return layer;
    const child = try layer.at("pin");
    const pl = try child.as(Layer);
    if (!pl.get().is_pinlayer) return error.NotAPinLayer;
    return pl;
}

// Symbol
// ------

pub const Symbol = struct {
    outline: ?Rect4R = null,
    caption: ?Str = null,

    pub const ordb_nodes = .{ Pin, SymbolPoly, SymbolArc, PolyVec2R };
};

/// A single wire connection exposed through a symbol.
pub const Pin = struct {
    pintype: PinType = .inout,
    pos: ?Vec2R = null,
    @"align": D4 = .r0,
};

/// A drawn polygonal chain in a Symbol; purely visual.
pub const SymbolPoly = struct {
    pub const ordb_vertex = PolyVec2R;
};

/// A drawn circle or circular arc in a Symbol; purely visual.
/// Angles are in turns: R(1) == 360 degrees.
pub const SymbolArc = struct {
    pos: ?Vec2R = null,
    radius: ?R = null,
    angle_start: R = R.zero,
    angle_end: R = R.one,
};

/// One vertex of a rational-coordinate polygonal chain.
pub const PolyVec2R = struct {
    ref: LocalRef(.{ SymbolPoly, SchemWire }, .{ .required = true }) = .none,
    order: ?i32 = null,
    pos: ?Vec2R = null,

    pub const ordb_required_fields = .{"order"};
    pub const ordb_indexes = .{
        .ref_idx = idx(&.{"ref"}, .{ .sort_by = "order" }),
    };
};

pub const SymbolSG = Subgraph(Symbol);

// Schematic
// ---------

pub const Schematic = struct {
    symbol: SubgraphRef(Symbol, .{}) = .none,
    outline: ?Rect4R = null,
    default_supply: LocalRef(.{Net}, .{}) = .none,
    default_ground: LocalRef(.{Net}, .{}) = .none,

    pub const ordb_nodes = .{
        Net,
        SchemPort,
        SchemWire,
        SchemInstance,
        SchemInstanceConn,
        SchemTapPoint,
        SchemConnPoint,
        PolyVec2R,
    };
};

pub const Net = struct {
    /// Pin of the schematic's symbol that this net is exposed through.
    pin: ExternalRef(Symbol, .{Pin}, ofRootSymbol, .{}) = .none,
    auto_wire: bool = true,

    pub const ordb_indexes = .{
        .pin_idx = idx(&.{"pin"}, .{}),
    };
};

/// Port of a Schematic, corresponding to a Pin of the schematic's Symbol.
pub const SchemPort = struct {
    ref: LocalRef(.{Net}, .{ .required = true }) = .none,
    pos: ?Vec2R = null,
    @"align": D4 = .r0,

    pub const ordb_indexes = .{
        .ref_idx = idx(&.{"ref"}, .{ .unique = true }),
        .pos_idx = idx(&.{"pos"}, .{}),
    };
};

/// A drawn schematic wire representing an electrical connection.
pub const SchemWire = struct {
    ref: LocalRef(.{Net}, .{ .required = true }) = .none,

    pub const ordb_vertex = PolyVec2R;
    pub const ordb_indexes = .{
        .ref_idx = idx(&.{"ref"}, .{}),
    };
};

/// An instance of a Symbol in a Schematic (schematic hierarchy).
pub const SchemInstance = struct {
    pos: ?Vec2R = null,
    orientation: D4 = .r0,
    symbol: SubgraphRef(Symbol, .{ .required = true }) = .none,

    /// Symbol-space to schematic-space transform.
    pub fn locTransform(self: SchemInstance) TD4R {
        return (self.pos orelse Vec2R.zero).transl().rotate(self.orientation);
    }
};

/// Maps one Pin of a SchemInstance to a Net of its Schematic.
pub const SchemInstanceConn = struct {
    ref: LocalRef(.{SchemInstance}, .{ .required = true }) = .none,
    here: LocalRef(.{Net}, .{ .required = true }) = .none,
    there: ExternalRef(Symbol, .{Pin}, ofConnInstSymbol, .{ .required = true }) = .none,

    pub const ordb_indexes = .{
        .ref_idx = idx(&.{"ref"}, .{}),
        .ref_pin_idx = idx(&.{ "ref", "there" }, .{ .unique = true }),
    };
};

/// Tap point connecting points by label.
pub const SchemTapPoint = struct {
    ref: LocalRef(.{Net}, .{ .required = true }) = .none,
    pos: ?Vec2R = null,
    @"align": D4 = .r0,

    pub const ordb_indexes = .{
        .ref_idx = idx(&.{"ref"}, .{}),
        .pos_idx = idx(&.{"pos"}, .{}),
    };

    pub fn locTransform(self: SchemTapPoint) TD4R {
        return (self.pos orelse Vec2R.zero).transl().rotate(self.@"align");
    }
};

/// Connection dot at a 3- or 4-way wire junction.
pub const SchemConnPoint = struct {
    ref: LocalRef(.{Net}, .{ .required = true }) = .none,
    pos: ?Vec2R = null,

    pub const ordb_indexes = .{
        .ref_idx = idx(&.{"ref"}, .{}),
        .pos_idx = idx(&.{"pos"}, .{}),
    };
};

pub const SchematicSG = Subgraph(Schematic);

// Layout
// ------

pub const Layout = struct {
    /// All LayoutPins in this subgraph reference this symbol.
    symbol: SubgraphRef(Symbol, .{}) = .none,
    /// All .layer attributes of nodes in this subgraph reference this stack.
    ref_layers: SubgraphRef(LayerStack, .{}) = .none,

    pub const ordb_nodes = .{
        LayoutLabel,
        LayoutPoly,
        LayoutPath,
        LayoutRect,
        LayoutInstance,
        LayoutInstanceArray,
        LayoutPin,
        PolyVec2I,
    };
};

/// Arbitrary text label (GDS TEXT). Prefer LayoutPin for pins.
pub const LayoutLabel = struct {
    layer: ExternalRef(LayerStack, .{Layer}, ofRootRefLayers, .{}) = .none,
    pos: ?Vec2I = null,
    text: ?Str = null,
};

/// Simple (no self-intersection, no holes) polygon, CCW orientation.
pub const LayoutPoly = struct {
    layer: ExternalRef(LayerStack, .{Layer}, ofRootRefLayers, .{}) = .none,

    pub const ordb_vertex = PolyVec2I;
};

/// Polygonal chain with width.
pub const LayoutPath = struct {
    layer: ExternalRef(LayerStack, .{Layer}, ofRootRefLayers, .{ .required = true }) = .none,
    endtype: PathEndType = .flush,
    /// Mandatory if endtype == .custom, else ignored.
    ext_bgn: ?i32 = null,
    ext_end: ?i32 = null,
    width: ?i32 = null,

    pub const ordb_vertex = PolyVec2I;
};

pub const LayoutRect = struct {
    layer: ExternalRef(LayerStack, .{Layer}, ofRootRefLayers, .{}) = .none,
    rect: ?Rect4I = null,
};

/// Hierarchical layout instance (GDS SRef).
pub const LayoutInstance = struct {
    pos: ?Vec2I = null,
    orientation: D4 = .r0,
    ref: SubgraphRef(Layout, .{ .required = true }) = .none,

    pub fn locTransform(self: LayoutInstance) TD4I {
        return (self.pos orelse Vec2I.zero).transl().rotate(self.orientation);
    }
};

/// Hierarchical layout instance array (GDS ARef). Zig has no inheritance;
/// this repeats LayoutInstance's fields (divergence from Python documented
/// in the README). Consumers switch on both union tags.
pub const LayoutInstanceArray = struct {
    pos: ?Vec2I = null,
    orientation: D4 = .r0,
    ref: SubgraphRef(Layout, .{ .required = true }) = .none,
    /// Number of columns, or null (= 1 column).
    cols: ?i32 = null,
    /// Number of rows, or null (= 1 row).
    rows: ?i32 = null,
    /// Vector separating adjacent columns; null permitted only if cols is null.
    vec_col: ?Vec2I = null,
    /// Vector separating adjacent rows; null permitted only if rows is null.
    vec_row: ?Vec2I = null,

    pub fn locTransform(self: LayoutInstanceArray) TD4I {
        return (self.pos orelse Vec2I.zero).transl().rotate(self.orientation);
    }
};

/// Associates a shape with a Pin of the layout's symbol.
pub const LayoutPin = struct {
    ref: LocalRef(.{ LayoutPoly, LayoutRect, LayoutPath }, .{}) = .none,
    pin: ExternalRef(Symbol, .{Pin}, ofRootSymbol, .{ .required = true }) = .none,
};

/// One vertex of an integer-coordinate polygonal chain.
pub const PolyVec2I = struct {
    ref: LocalRef(.{ LayoutPoly, LayoutPath }, .{ .required = true }) = .none,
    order: ?i32 = null,
    pos: ?Vec2I = null,

    pub const ordb_required_fields = .{"order"};
    pub const ordb_indexes = .{
        .ref_idx = idx(&.{"ref"}, .{ .sort_by = "order" }),
    };
};

pub const LayoutSG = Subgraph(Layout);

// Polygon helpers (replacing Python's GenericPoly vertex machinery)
// -----------------------------------------------------------------

fn VertexPos(comptime PolyT: type) type {
    return @FieldType(PolyT.ordb_vertex, "pos");
}

/// Insert a polygon/chain node together with its ordered vertex nodes in one
/// transaction (Python: SymbolPoly(vertices=[...])).
pub fn insertPoly(
    m: anytype,
    poly: anytype,
    vertices: []const std.meta.Child(VertexPos(@TypeOf(poly))),
) !@TypeOf(m.*).Owner.Cursor(@TypeOf(poly)) {
    const PolyT = @TypeOf(poly);
    const VertexT = PolyT.ordb_vertex;
    var t = m.txn();
    errdefer t.abort();
    const c = try t.insert(poly);
    for (vertices, 0..) |v, i| {
        _ = try t.insert(VertexT{ .ref = .to(c.nid), .order = @intCast(i), .pos = v });
    }
    try t.commit(null);
    return c;
}

/// Ordered vertex positions of a polygon/chain node. Caller frees.
pub fn polyVertices(
    cursor: anytype,
    alloc: Allocator,
) ![]std.meta.Child(VertexPos(@TypeOf(cursor).NodeType)) {
    const PolyT = @TypeOf(cursor).NodeType;
    const VertexT = PolyT.ordb_vertex;
    const vcs = try cursor.view.allBy(VertexT, "ref_idx", .{@as(?Nid, cursor.nid)}, alloc);
    defer alloc.free(vcs);
    const Pos = std.meta.Child(VertexPos(PolyT));
    const out = try alloc.alloc(Pos, vcs.len);
    errdefer alloc.free(out);
    for (vcs, 0..) |vc, i| out[i] = vc.get().pos orelse return error.MissingAttr;
    return out;
}

/// Remove a polygon/chain node together with its vertices (Python:
/// GenericPoly.remove_node).
pub fn removePoly(cursor: anytype) !void {
    const PolyT = @TypeOf(cursor).NodeType;
    const VertexT = PolyT.ordb_vertex;
    const m = switch (cursor.view) {
        .mutable => |m| m,
        .frozen => return error.Frozen,
    };
    const vcs = try cursor.view.allBy(VertexT, "ref_idx", .{@as(?Nid, cursor.nid)}, m.gpa);
    defer m.gpa.free(vcs);
    var t = m.txn();
    errdefer t.abort();
    for (vcs) |vc| try t.removeNid(vc.nid);
    if (try cursor.view.npathNidOf(cursor.nid, m.gpa)) |np| try t.removeNid(np);
    try t.removeNid(cursor.nid);
    try t.commit(null);
}

// Schematic instantiation helper (ergonomic replacement for Symbol.portmap)
// -------------------------------------------------------------------------

/// Insert a SchemInstance under `name` and connect its pins:
/// `conns` is a tuple of .{ "pin_name", net_cursor } pairs. Pin names are
/// resolved in the instance's symbol via its NPath hierarchy.
pub fn instantiate(
    m: *SchematicSG.Mutable,
    name: anytype,
    inst: SchemInstance,
    conns: anytype,
) !SchematicSG.Cursor(SchemInstance) {
    const sym = try SymbolSG.Frozen.fromHeader(inst.symbol.ptr orelse return error.MissingAttr);

    const parent_np = blk: {
        var t = m.txn();
        errdefer t.abort();
        const c = try t.insert(inst);
        const nm = sg.coerceName(name);
        try nm.validate();
        const npc = try t.insert(meta.NPath{ .parent = .none, .name = nm, .ref = .to(c.nid) });
        _ = npc;
        inline for (conns) |conn| {
            const pin_name, const net = conn;
            const pin = try (try sym.root().at(pin_name)).as(Pin);
            _ = try t.insert(SchemInstanceConn{
                .ref = .to(c.nid),
                .here = .to(net),
                .there = .to(pin.nid),
            });
        }
        try t.commit(null);
        break :blk c;
    };
    return parent_np;
}

// Layout bounding box (used by the placer)
// ----------------------------------------

/// Bounding box over all shapes of a layout, hierarchically including
/// instances. Returns null for an empty layout.
pub fn layoutBBox(view: LayoutSG.View, alloc: Allocator) !?Rect4I {
    var acc: ?Rect4I = null;

    const rects = try view.all(LayoutRect, alloc);
    defer alloc.free(rects);
    for (rects) |rc| {
        if (rc.get().rect) |r| acc = extendRect(acc, r);
    }

    inline for (.{ LayoutPoly, LayoutPath }) |PolyT| {
        const polys = try view.all(PolyT, alloc);
        defer alloc.free(polys);
        for (polys) |pc| {
            const vs = try polyVertices(pc, alloc);
            defer alloc.free(vs);
            for (vs) |v| acc = extendVec(acc, v);
        }
    }

    const insts = try view.all(LayoutInstance, alloc);
    defer alloc.free(insts);
    for (insts) |ic| {
        const inst = ic.get();
        const child = try LayoutSG.Frozen.fromHeader(inst.ref.ptr orelse continue);
        if (try layoutBBox(child.view(), alloc)) |cb| {
            acc = extendRect(acc, inst.locTransform().applyRect(cb));
        }
    }

    const arrays = try view.all(LayoutInstanceArray, alloc);
    defer alloc.free(arrays);
    for (arrays) |ac| {
        const arr = ac.get();
        const child = try LayoutSG.Frozen.fromHeader(arr.ref.ptr orelse continue);
        const cb = (try layoutBBox(child.view(), alloc)) orelse continue;
        const base = arr.locTransform().applyRect(cb);
        const cols: i32 = arr.cols orelse 1;
        const rows: i32 = arr.rows orelse 1;
        const vc = arr.vec_col orelse Vec2I.zero;
        const vr = arr.vec_row orelse Vec2I.zero;
        // The array bbox is the union of the four corner elements:
        inline for (.{ .{ 0, 0 }, .{ 1, 0 }, .{ 0, 1 }, .{ 1, 1 } }) |corner| {
            const dx = vc.scale(corner[0] * (cols - 1)).add(vr.scale(corner[1] * (rows - 1)));
            acc = extendRect(acc, dx.transl().applyRect(base));
        }
    }

    return acc;
}

fn extendRect(acc: ?Rect4I, r: Rect4I) Rect4I {
    if (acc) |a| return a.extendRect(r);
    return r;
}

fn extendVec(acc: ?Rect4I, v: Vec2I) Rect4I {
    if (acc) |a| return a.extend(v);
    return .{ .lx = v.x, .ly = v.y, .ux = v.x, .uy = v.y };
}

// Tests
// -----

const gpa = std.testing.allocator;
const expect = std.testing.expect;
const expectEqual = std.testing.expectEqual;

fn makeLayers() !*LayerStackSG.Frozen {
    var m = try LayerStackSG.Mutable.init(gpa, .{ .unit = try R.parse("1n") });
    defer m.deinit();
    const m1 = try m.put("metal1", Layer{
        .gdslayer_shapes = .{ .layer = 8, .data_type = 0 },
        .style_fill = .{ .r = 0x10, .g = 0x20, .b = 0x30 },
    });
    _ = try m1.put("pin", Layer{
        .gdslayer_shapes = .{ .layer = 8, .data_type = 2 },
        .is_pinlayer = true,
    });
    _ = try m.put("poly", Layer{ .gdslayer_shapes = .{ .layer = 5, .data_type = 0 } });
    return m.freeze();
}

fn makeInvSymbol() !*SymbolSG.Frozen {
    var m = try SymbolSG.Mutable.init(gpa, .{
        .outline = try Rect4R.init(0, 0, 4, 8),
        .caption = "inv",
    });
    defer m.deinit();
    _ = try m.put("a", Pin{ .pintype = .in, .pos = Vec2R.xy(0, 4), .@"align" = .east });
    _ = try m.put("y", Pin{ .pintype = .out, .pos = Vec2R.xy(4, 4), .@"align" = .west });
    _ = try insertPoly(&m, SymbolPoly{}, &.{
        Vec2R.xy(1, 2), Vec2R.xy(1, 6), Vec2R.xy(3, 4), Vec2R.xy(1, 2),
    });
    _ = try m.insert(SymbolArc{ .pos = Vec2R.xy(3, 4), .radius = try R.init(1, 4) });
    return m.freeze();
}

test "symbol construction and queries" {
    const sym = try makeInvSymbol();
    defer sym.release();

    const pin_a = try (try sym.root().at("a")).as(Pin);
    try expectEqual(PinType.in, pin_a.get().pintype);

    const polys = try sym.view().all(SymbolPoly, gpa);
    defer gpa.free(polys);
    try expectEqual(1, polys.len);
    const vs = try polyVertices(polys[0], gpa);
    defer gpa.free(vs);
    try expectEqual(4, vs.len);
    try expect(vs[2].eql(Vec2R.xy(3, 4)));
}

test "layerstack and pinLayer" {
    const ls = try makeLayers();
    defer ls.release();

    const m1 = try (try ls.root().at("metal1")).as(Layer);
    const pl = try pinLayer(m1);
    try expect(pl.get().is_pinlayer);
    try expectEqual(@as(u16, 2), pl.get().gdslayer_shapes.?.data_type);
    // A pin layer is its own pin layer:
    const pl2 = try pinLayer(pl);
    try expectEqual(pl.nid, pl2.nid);
}

test "schematic with instances and portmap-style connection" {
    const sym = try makeInvSymbol();
    defer sym.release();

    var m = try SchematicSG.Mutable.init(gpa, .{ .symbol = .of(sym) });
    defer m.deinit();

    const a = try m.put("a", Net{});
    const y = try m.put("y", Net{});
    const pin_a = try (try sym.root().at("a")).as(Pin);
    try a.set(.pin, .to(pin_a));

    const inst0 = try instantiate(&m, "I0", SchemInstance{
        .pos = Vec2R.xy(2, 3),
        .symbol = .of(sym),
    }, .{
        .{ "a", a },
        .{ "y", y },
    });

    // Connectivity:
    const conns = try m.view().allBy(SchemInstanceConn, "ref_idx", .{@as(?Nid, inst0.nid)}, gpa);
    defer gpa.free(conns);
    try expectEqual(2, conns.len);
    // External pin refs resolve through the instance's symbol:
    const there = try m.view().cursorAt(SchemInstanceConn, conns[0].nid);
    const pin = try there.derefExternal(.there);
    try expectEqual(PinType.in, pin.get().pintype);

    // Net.pin resolves through the schematic's own symbol:
    const back = try a.derefExternal(.pin);
    try expectEqual(pin_a.nid, back.nid);

    // Duplicate connection of same pin violates the unique (ref, there) index:
    try std.testing.expectError(error.UniqueViolation, m.insert(SchemInstanceConn{
        .ref = .to(inst0),
        .here = .to(y),
        .there = .to(pin_a),
    }));

    // locTransform maps symbol coords to schematic coords:
    const t = inst0.get().locTransform();
    const p = try t.applyVec(pin_a.get().pos.?);
    try expect(p.eql(Vec2R.xy(2, 7)));

    // Path naming:
    const path = try inst0.fullPathStr(gpa);
    defer gpa.free(path);
    try std.testing.expectEqualStrings("I0", path);
}

test "layout with shapes, pins and instances" {
    const ls = try makeLayers();
    defer ls.release();
    const sym = try makeInvSymbol();
    defer sym.release();

    const m1_nid = (try (try ls.root().at("metal1")).as(Layer)).nid;

    // A standard-cell-ish layout:
    var mc = try LayoutSG.Mutable.init(gpa, .{ .symbol = .of(sym), .ref_layers = .of(ls) });
    defer mc.deinit();
    const r = try mc.insert(LayoutRect{
        .layer = .to(m1_nid),
        .rect = try Rect4I.init(0, 0, 400, 800),
    });
    _ = try mc.insert(LayoutPin{ .ref = .to(r.nid), .pin = .to(1) });
    _ = try insertPoly(&mc, LayoutPoly{ .layer = .to(m1_nid) }, &.{
        Vec2I.xy(0, 0), Vec2I.xy(100, 0), Vec2I.xy(100, 900),
    });
    const cell = try mc.freeze();
    defer cell.release();

    try expect((try layoutBBox(cell.view(), gpa)).?.eql(try Rect4I.init(0, 0, 400, 900)));

    // Top layout instantiating the cell twice:
    var mt = try LayoutSG.Mutable.init(gpa, .{ .ref_layers = .of(ls) });
    defer mt.deinit();
    _ = try mt.insert(LayoutInstance{ .pos = Vec2I.xy(0, 0), .ref = .of(cell) });
    _ = try mt.insert(LayoutInstance{ .pos = Vec2I.xy(1000, 0), .orientation = .mx, .ref = .of(cell) });
    const top = try mt.freeze();
    defer top.release();

    const bb = (try layoutBBox(top.view(), gpa)).?;
    try expect(bb.eql(try Rect4I.init(0, -900, 1400, 900)));

    // Layer external refs resolve:
    const rects = try top.view().all(LayoutRect, gpa);
    defer gpa.free(rects);
    try expectEqual(0, rects.len); // shapes live in the cell, not the top

    const cell_rects = try cell.view().all(LayoutRect, gpa);
    defer gpa.free(cell_rects);
    const layer = try cell_rects[0].derefExternal(.layer);
    try expectEqual(@as(u16, 8), layer.get().gdslayer_shapes.?.layer);
}

test "layout instance array bbox" {
    const ls = try makeLayers();
    defer ls.release();

    var mc = try LayoutSG.Mutable.init(gpa, .{ .ref_layers = .of(ls) });
    defer mc.deinit();
    _ = try mc.insert(LayoutRect{ .rect = try Rect4I.init(0, 0, 10, 20) });
    const cell = try mc.freeze();
    defer cell.release();

    var mt = try LayoutSG.Mutable.init(gpa, .{ .ref_layers = .of(ls) });
    defer mt.deinit();
    _ = try mt.insert(LayoutInstanceArray{
        .pos = Vec2I.xy(5, 0),
        .ref = .of(cell),
        .cols = 3,
        .rows = 2,
        .vec_col = Vec2I.xy(100, 0),
        .vec_row = Vec2I.xy(0, 200),
    });
    const top = try mt.freeze();
    defer top.release();

    const bb = (try layoutBBox(top.view(), gpa)).?;
    try expect(bb.eql(try Rect4I.init(5, 0, 215, 220)));
}

test "removePoly removes vertices" {
    const sym_m = struct {
        fn run() !void {
            var m = try SymbolSG.Mutable.init(gpa, .{});
            defer m.deinit();
            const poly = try insertPoly(&m, SymbolPoly{}, &.{ Vec2R.xy(0, 0), Vec2R.xy(1, 1) });
            try removePoly(poly);
            const vs = try m.view().all(PolyVec2R, gpa);
            defer gpa.free(vs);
            try expectEqual(0, vs.len);
            const ps = try m.view().all(SymbolPoly, gpa);
            defer gpa.free(ps);
            try expectEqual(0, ps.len);
        }
    };
    try sym_m.run();
}
