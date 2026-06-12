// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Standard-cell placer demo on top of the Layout schema in schema.zig.
//!
//! Input: a frozen Layout whose LayoutInstances reference standard-cell
//! Layouts (uniform row height) and are unplaced (e.g. all at the origin,
//! possibly overlapping). Output: a new frozen Layout in which every
//! instance is legally placed: packed into rows on a site grid within the
//! die width, with alternating rows flipped (MX) so that power rails abut.
//!
//! The output is produced by thawing the input -- thanks to the delta-chain
//! persistence, only the moved instances enter the new generation's delta.

const std = @import("std");
const Allocator = std.mem.Allocator;
const meta = @import("meta.zig");
const schema = @import("schema.zig");
const sgmod = @import("subgraph.zig");
const geom = @import("geom.zig");

const Nid = meta.Nid;
const Vec2I = geom.Vec2I;
const Rect4I = geom.Rect4I;
const TD4I = geom.TD4I;
const D4 = geom.D4;
const LayoutSG = schema.LayoutSG;

pub const PlacerOpts = struct {
    /// Die width in layout units; rows span [0, die_width).
    die_width: i32,
    /// Site grid pitch; every cell origin is aligned to it.
    site_width: i32,
    /// Standard-cell row height; all cells must be exactly this tall.
    row_height: i32,
};

pub const PlacerError = error{
    CellTooWide,
    CellHeightMismatch,
    EmptyCell,
    MissingAttr,
} || sgmod.Error || Allocator.Error;

const Item = struct {
    /// Existing instance nid, or null for an instance expanded from an array.
    nid: ?Nid,
    ref: *meta.FrozenHeader,
    bbox: Rect4I,
    width_sites: i32,
    /// Stable tiebreaker for deterministic ordering.
    seq: u32,
};

/// Bounding boxes per distinct referenced cell layout, cached by identity.
const BBoxCache = struct {
    map: std.AutoArrayHashMapUnmanaged(*meta.FrozenHeader, Rect4I) = .empty,

    fn get(self: *BBoxCache, gpa: Allocator, header: *meta.FrozenHeader) !Rect4I {
        const gop = try self.map.getOrPut(gpa, header);
        if (!gop.found_existing) {
            const cell = try LayoutSG.Frozen.fromHeader(header);
            gop.value_ptr.* = (try schema.layoutBBox(cell.view(), gpa)) orelse return error.EmptyCell;
        }
        return gop.value_ptr.*;
    }
};

pub fn place(input: *LayoutSG.Frozen, opts: PlacerOpts, gpa: Allocator) !*LayoutSG.Frozen {
    std.debug.assert(opts.site_width > 0 and opts.row_height > 0 and opts.die_width > 0);

    var cache = BBoxCache{};
    defer cache.map.deinit(gpa);
    var items: std.ArrayList(Item) = .empty;
    defer items.deinit(gpa);
    var seq: u32 = 0;

    // Collect plain instances:
    const insts = try input.view().all(schema.LayoutInstance, gpa);
    defer gpa.free(insts);
    for (insts) |ic| {
        const header = ic.get().ref.ptr orelse return error.MissingAttr;
        try items.append(gpa, try makeItem(ic.nid, header, &cache, opts, gpa, &seq));
    }

    // Expand instance arrays into individual placements:
    const arrays = try input.view().all(schema.LayoutInstanceArray, gpa);
    defer gpa.free(arrays);
    for (arrays) |ac| {
        const arr = ac.get();
        const header = arr.ref.ptr orelse return error.MissingAttr;
        const n: usize = @intCast(@as(i64, arr.cols orelse 1) * @as(i64, arr.rows orelse 1));
        for (0..n) |_| {
            try items.append(gpa, try makeItem(null, header, &cache, opts, gpa, &seq));
        }
    }

    // Deterministic order: widest first, then insertion sequence.
    std.mem.sort(Item, items.items, {}, struct {
        fn lessThan(_: void, a: Item, b: Item) bool {
            if (a.width_sites != b.width_sites) return a.width_sites > b.width_sites;
            return a.seq < b.seq;
        }
    }.lessThan);

    // Greedy shelf packing + emission:
    var out = try input.thaw();
    errdefer out.deinit();

    const sites_per_row: i32 = @divTrunc(opts.die_width, opts.site_width);
    var row: i32 = 0;
    var site: i32 = 0;
    for (items.items) |item| {
        if (site + item.width_sites > sites_per_row) {
            row += 1;
            site = 0;
        }
        const placement = placeInRow(item.bbox, row, site, opts);
        if (item.nid) |nid| {
            const c = try out.view().cursorAt(schema.LayoutInstance, nid);
            var v = c.get();
            v.pos = placement.pos;
            v.orientation = placement.orientation;
            try c.update(v);
        } else {
            _ = try out.insert(schema.LayoutInstance{
                .pos = placement.pos,
                .orientation = placement.orientation,
                .ref = .{ .ptr = item.ref },
            });
        }
        site += item.width_sites;
    }

    // Arrays have been expanded; remove them.
    for (arrays) |ac| {
        const c = try out.view().cursorAt(schema.LayoutInstanceArray, ac.nid);
        try c.remove();
    }

    return out.freeze();
}

fn makeItem(
    nid: ?Nid,
    header: *meta.FrozenHeader,
    cache: *BBoxCache,
    opts: PlacerOpts,
    gpa: Allocator,
    seq: *u32,
) !Item {
    const bbox = try cache.get(gpa, header);
    if (bbox.height() != opts.row_height) return error.CellHeightMismatch;
    const width_sites = std.math.divCeil(i32, bbox.width(), opts.site_width) catch unreachable;
    if (width_sites * opts.site_width > opts.die_width) return error.CellTooWide;
    seq.* += 1;
    return .{ .nid = nid, .ref = header, .bbox = bbox, .width_sites = width_sites, .seq = seq.* - 1 };
}

const Placement = struct { pos: Vec2I, orientation: D4 };

/// Position a cell whose untransformed bbox is `bbox` so that its
/// transformed bbox lands exactly at site `site` in row `row`. Odd rows are
/// flipped (MX) for power-rail sharing.
fn placeInRow(bbox: Rect4I, row: i32, site: i32, opts: PlacerOpts) Placement {
    const x = site * opts.site_width;
    const y = row * opts.row_height;
    if (@rem(row, 2) == 0) {
        // r0: bbox maps to [pos + (lx, ly), pos + (ux, uy)]
        return .{
            .pos = Vec2I.xy(x - bbox.lx, y - bbox.ly),
            .orientation = .r0,
        };
    } else {
        // mx (y negated): bbox maps to [pos.y - uy, pos.y - ly] vertically
        return .{
            .pos = Vec2I.xy(x - bbox.lx, y + bbox.uy),
            .orientation = .mx,
        };
    }
}

// Legality checking (independent oracle, also used by tests)
// ----------------------------------------------------------

pub const LegalityError = error{
    Overlap,
    OutsideDie,
    OffGrid,
    OffRow,
    WrongOrientation,
    ArrayNotExpanded,
    EmptyCell,
    MissingAttr,
} || sgmod.Error || Allocator.Error;

/// Verify that every instance of `layout` is legally placed.
pub fn verifyLegal(layout: *LayoutSG.Frozen, opts: PlacerOpts, gpa: Allocator) LegalityError!void {
    const arrays = try layout.view().all(schema.LayoutInstanceArray, gpa);
    defer gpa.free(arrays);
    if (arrays.len != 0) return error.ArrayNotExpanded;

    var cache = BBoxCache{};
    defer cache.map.deinit(gpa);

    const Placed = struct { rect: Rect4I, row: i32 };
    var placed: std.ArrayList(Placed) = .empty;
    defer placed.deinit(gpa);

    const insts = try layout.view().all(schema.LayoutInstance, gpa);
    defer gpa.free(insts);
    for (insts) |ic| {
        const inst = ic.get();
        const header = inst.ref.ptr orelse return error.MissingAttr;
        const bbox = cache.get(gpa, header) catch |err| switch (err) {
            error.EmptyCell => return error.EmptyCell,
            else => |e| return @errorCast(e),
        };
        const rect = inst.locTransform().applyRect(bbox);

        if (rect.lx < 0 or rect.ux > opts.die_width) return error.OutsideDie;
        if (@rem(rect.lx, opts.site_width) != 0) return error.OffGrid;
        if (@rem(rect.ly, opts.row_height) != 0 or rect.height() != opts.row_height)
            return error.OffRow;
        const row = @divTrunc(rect.ly, opts.row_height);
        if (row < 0) return error.OutsideDie;
        const expected: D4 = if (@rem(row, 2) == 0) .r0 else .mx;
        if (inst.orientation != expected) return error.WrongOrientation;

        for (placed.items) |other| {
            if (other.row == row and rect.overlaps(other.rect)) return error.Overlap;
        }
        try placed.append(gpa, .{ .rect = rect, .row = row });
    }
}

/// Render a coarse ASCII map of the placement (one char per site, one line
/// per row, top row last). Caller frees.
pub fn asciiMap(layout: *LayoutSG.Frozen, opts: PlacerOpts, gpa: Allocator) ![]u8 {
    var cache = BBoxCache{};
    defer cache.map.deinit(gpa);

    const sites_per_row: usize = @intCast(@divTrunc(opts.die_width, opts.site_width));
    const insts = try layout.view().all(schema.LayoutInstance, gpa);
    defer gpa.free(insts);

    var max_row: i32 = 0;
    for (insts) |ic| {
        const inst = ic.get();
        const bbox = try cache.get(gpa, inst.ref.ptr orelse return error.MissingAttr);
        const rect = inst.locTransform().applyRect(bbox);
        max_row = @max(max_row, @divTrunc(rect.ly, opts.row_height));
    }

    const rows: usize = @intCast(max_row + 1);
    const line_len = sites_per_row + 1; // + newline
    const out = try gpa.alloc(u8, rows * line_len);
    @memset(out, '.');
    for (0..rows) |r| out[r * line_len + sites_per_row] = '\n';

    for (insts, 0..) |ic, i| {
        const inst = ic.get();
        const bbox = try cache.get(gpa, inst.ref.ptr orelse return error.MissingAttr);
        const rect = inst.locTransform().applyRect(bbox);
        const row: usize = @intCast(@divTrunc(rect.ly, opts.row_height));
        const s0: usize = @intCast(@divTrunc(rect.lx, opts.site_width));
        const s1: usize = @intCast(std.math.divCeil(i32, rect.ux, opts.site_width) catch unreachable);
        const ch: u8 = 'A' + @as(u8, @intCast(i % 26));
        // Top row printed last => row 0 at the bottom of the string:
        const line = rows - 1 - row;
        for (s0..@min(s1, sites_per_row)) |s| out[line * line_len + s] = ch;
    }
    return out;
}

// Test fixtures (also used by the demo)
// -------------------------------------

pub const FakePdk = struct {
    layers: *schema.LayerStackSG.Frozen,
    inv: *LayoutSG.Frozen,
    nand2: *LayoutSG.Frozen,
    dff: *LayoutSG.Frozen,

    pub fn deinit(self: *FakePdk) void {
        self.inv.release();
        self.nand2.release();
        self.dff.release();
        self.layers.release();
    }
};

pub const fake_row_height = 800;
pub const fake_site_width = 100;

/// Build a tiny fake PDK: a LayerStack and three standard cells (with
/// symbol, shapes and pins) of 3, 4 and 9 sites width.
pub fn buildFakePdk(gpa: Allocator) !FakePdk {
    var mls = try schema.LayerStackSG.Mutable.init(gpa, .{ .unit = try geom.R.parse("1n") });
    defer mls.deinit();
    _ = try mls.put("nwell", schema.Layer{ .gdslayer_shapes = .{ .layer = 1, .data_type = 0 } });
    _ = try mls.put("diff", schema.Layer{ .gdslayer_shapes = .{ .layer = 2, .data_type = 0 } });
    _ = try mls.put("poly", schema.Layer{ .gdslayer_shapes = .{ .layer = 5, .data_type = 0 } });
    const m1 = try mls.put("metal1", schema.Layer{ .gdslayer_shapes = .{ .layer = 8, .data_type = 0 } });
    _ = try m1.put("pin", schema.Layer{
        .gdslayer_shapes = .{ .layer = 8, .data_type = 2 },
        .is_pinlayer = true,
    });
    const layers = try mls.freeze();
    errdefer layers.release();

    const inv = try buildFakeCell(gpa, layers, "inv", 3, &.{ "a", "y" });
    errdefer inv.release();
    const nand2 = try buildFakeCell(gpa, layers, "nand2", 4, &.{ "a", "b", "y" });
    errdefer nand2.release();
    const dff = try buildFakeCell(gpa, layers, "dff", 9, &.{ "d", "clk", "q" });
    errdefer dff.release();

    return .{ .layers = layers, .inv = inv, .nand2 = nand2, .dff = dff };
}

fn buildFakeCell(
    gpa: Allocator,
    layers: *schema.LayerStackSG.Frozen,
    name: []const u8,
    sites: i32,
    pins: []const []const u8,
) !*LayoutSG.Frozen {
    // Symbol:
    var ms = try schema.SymbolSG.Mutable.init(gpa, .{
        .caption = name,
        .outline = try geom.Rect4R.init(0, 0, 4, 4),
    });
    defer ms.deinit();
    for (pins, 0..) |pin_name, i| {
        _ = try ms.put(pin_name, schema.Pin{ .pos = geom.Vec2R.xy(0, @as(i32, @intCast(i))) });
    }
    const sym = try ms.freeze();
    defer sym.release();

    const nwell = try (try layers.root().at("nwell")).as(schema.Layer);
    const diff = try (try layers.root().at("diff")).as(schema.Layer);
    const metal1 = try (try layers.root().at("metal1")).as(schema.Layer);

    // Layout:
    const w = sites * fake_site_width;
    var ml = try LayoutSG.Mutable.init(gpa, .{ .symbol = .of(sym), .ref_layers = .of(layers) });
    defer ml.deinit();
    // Cell area on nwell (top half) and diff:
    _ = try ml.insert(schema.LayoutRect{
        .layer = .to(nwell.nid),
        .rect = try Rect4I.init(0, @divTrunc(fake_row_height, 2), w, fake_row_height),
    });
    _ = try ml.insert(schema.LayoutRect{
        .layer = .to(diff.nid),
        .rect = try Rect4I.init(0, 0, w, @divTrunc(fake_row_height, 2)),
    });
    // One metal1 pin shape per symbol pin:
    for (pins, 0..) |pin_name, i| {
        const x: i32 = @intCast((i + 1) * 80);
        const shape = try ml.insert(schema.LayoutRect{
            .layer = .to(metal1.nid),
            .rect = try Rect4I.init(x, 300, x + 40, 340),
        });
        const pin = try (try sym.root().at(pin_name)).as(schema.Pin);
        _ = try ml.insert(schema.LayoutPin{ .ref = .to(shape.nid), .pin = .to(pin.nid) });
    }
    return ml.freeze();
}

// Tests
// -----

const gpa_t = std.testing.allocator;

fn buildUnplacedInput(gpa: Allocator, pdk: *const FakePdk) !*LayoutSG.Frozen {
    var m = try LayoutSG.Mutable.init(gpa, .{ .ref_layers = .of(pdk.layers) });
    defer m.deinit();
    // A pile of overlapping instances at the origin:
    for (0..6) |_| _ = try m.insert(schema.LayoutInstance{ .pos = Vec2I.zero, .ref = .of(pdk.inv) });
    for (0..5) |_| _ = try m.insert(schema.LayoutInstance{ .pos = Vec2I.zero, .ref = .of(pdk.nand2) });
    for (0..3) |_| _ = try m.insert(schema.LayoutInstance{ .pos = Vec2I.zero, .ref = .of(pdk.dff) });
    // Plus an instance array to be expanded (2x3 invs):
    _ = try m.insert(schema.LayoutInstanceArray{
        .pos = Vec2I.zero,
        .ref = .of(pdk.inv),
        .cols = 2,
        .rows = 3,
        .vec_col = Vec2I.xy(300, 0),
        .vec_row = Vec2I.xy(0, 800),
    });
    return m.freeze();
}

test "placer produces a legal placement" {
    var pdk = try buildFakePdk(gpa_t);
    defer pdk.deinit();
    const input = try buildUnplacedInput(gpa_t, &pdk);
    defer input.release();

    const opts = PlacerOpts{
        .die_width = 2000,
        .site_width = fake_site_width,
        .row_height = fake_row_height,
    };

    // The input is NOT legal:
    try std.testing.expectError(error.ArrayNotExpanded, verifyLegal(input, opts, gpa_t));

    const placed = try place(input, opts, gpa_t);
    defer placed.release();
    try verifyLegal(placed, opts, gpa_t);

    // All 14 + 6 = 20 instances present, arrays gone:
    const insts = try placed.view().all(schema.LayoutInstance, gpa_t);
    defer gpa_t.free(insts);
    try std.testing.expectEqual(20, insts.len);

    // The input layout is untouched (delta-chain):
    const input_insts = try input.view().all(schema.LayoutInstance, gpa_t);
    defer gpa_t.free(input_insts);
    try std.testing.expectEqual(14, input_insts.len);
}

test "placer is deterministic" {
    var pdk = try buildFakePdk(gpa_t);
    defer pdk.deinit();
    const input = try buildUnplacedInput(gpa_t, &pdk);
    defer input.release();

    const opts = PlacerOpts{
        .die_width = 1600,
        .site_width = fake_site_width,
        .row_height = fake_row_height,
    };
    const a = try place(input, opts, gpa_t);
    defer a.release();
    const b = try place(input, opts, gpa_t);
    defer b.release();
    try std.testing.expect(a.eqlContent(b));
}

test "placer error on oversized cell" {
    var pdk = try buildFakePdk(gpa_t);
    defer pdk.deinit();
    const input = try buildUnplacedInput(gpa_t, &pdk);
    defer input.release();

    const opts = PlacerOpts{
        .die_width = 800, // dff is 9 sites = 900 wide
        .site_width = fake_site_width,
        .row_height = fake_row_height,
    };
    try std.testing.expectError(error.CellTooWide, place(input, opts, gpa_t));
}
