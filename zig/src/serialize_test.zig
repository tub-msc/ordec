// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Serialization tests: round trips, hash stability, Merkle references.

const std = @import("std");
const meta = @import("meta.zig");
const serialize = @import("serialize.zig");
const schema = @import("schema.zig");
const geom = @import("geom.zig");
const rational = @import("rational.zig");

const R = rational.R;
const Vec2R = geom.Vec2R;
const Vec2I = geom.Vec2I;
const Rect4R = geom.Rect4R;
const Rect4I = geom.Rect4I;

const gpa = std.testing.allocator;

const SymbolSG = schema.SymbolSG;
const LayoutSG = schema.LayoutSG;
const LayerStackSG = schema.LayerStackSG;

fn makeSymbolA() !*SymbolSG.Frozen {
    var m = try SymbolSG.Mutable.init(gpa, .{
        .outline = try Rect4R.init(0, 0, 4, 8),
        .caption = "inv",
    });
    defer m.deinit();
    _ = try m.put("a", schema.Pin{ .pintype = .in, .pos = Vec2R.xy(0, 4) });
    _ = try m.put("y", schema.Pin{ .pintype = .out, .pos = Vec2R.xy(4, 4) });
    _ = try schema.insertPoly(&m, schema.SymbolPoly{}, &.{
        Vec2R.xy(1, 2), Vec2R.xy(1, 6), Vec2R.xy(3, 4),
    });
    _ = try m.insert(schema.SymbolArc{
        .pos = Vec2R.xy(3, 4),
        .radius = try R.init(1, 4),
    });
    return m.freeze();
}

test "content hash: identical content, different construction history" {
    // Built in one go:
    const a = try makeSymbolA();
    defer a.release();

    // Built across a freeze/thaw chain, ending at the same content:
    var m0 = try SymbolSG.Mutable.init(gpa, .{ .outline = try Rect4R.init(0, 0, 4, 8) });
    defer m0.deinit();
    _ = try m0.put("a", schema.Pin{ .pintype = .in, .pos = Vec2R.xy(0, 4) });
    const f0 = try m0.freeze();
    defer f0.release();
    var m1 = try f0.thaw();
    defer m1.deinit();
    try m1.root().set(.caption, "inv");
    _ = try m1.put("y", schema.Pin{ .pintype = .out, .pos = Vec2R.xy(4, 4) });
    _ = try schema.insertPoly(&m1, schema.SymbolPoly{}, &.{
        Vec2R.xy(1, 2), Vec2R.xy(1, 6), Vec2R.xy(3, 4),
    });
    _ = try m1.insert(schema.SymbolArc{
        .pos = Vec2R.xy(3, 4),
        .radius = try R.init(1, 4),
    });
    const b = try m1.freeze();
    defer b.release();

    try std.testing.expect(a.eqlContent(b));

    // Different content -> different hash:
    var m2 = try b.thaw();
    defer m2.deinit();
    try m2.root().set(.caption, "buf");
    const c = try m2.freeze();
    defer c.release();
    try std.testing.expect(!a.eqlContent(c));
}

test "content encoding is deterministic bytes" {
    const a = try makeSymbolA();
    defer a.release();
    const b = try makeSymbolA();
    defer b.release();
    const ea = try serialize.encodeContent(a, gpa);
    defer gpa.free(ea);
    const eb = try serialize.encodeContent(b, gpa);
    defer gpa.free(eb);
    try std.testing.expectEqualSlices(u8, ea, eb);
}

test "golden content hash (format drift detector)" {
    // If this test fails, the wire format changed: bump the format version
    // and update this constant deliberately.
    var m = try SymbolSG.Mutable.init(gpa, .{ .caption = "golden" });
    defer m.deinit();
    _ = try m.put("p", schema.Pin{ .pintype = .out, .pos = Vec2R.xy(1, 2), .@"align" = .r90 });
    const f = try m.freeze();
    defer f.release();

    var hex_buf: [64]u8 = undefined;
    const hex = try std.fmt.bufPrint(&hex_buf, "{x}", .{f.header.hash});
    try std.testing.expectEqualStrings(
        "0639a27440a8963bda4f7e6c15a54e8f9dd0c1b7cdd20f001c8c8b83e3735900",
        hex,
    );
}

test "big rationals: arena ownership and transfer round trip" {
    var arena_state = std.heap.ArenaAllocator.init(gpa);
    defer arena_state.deinit();
    const arena = arena_state.allocator();

    var m = try SymbolSG.Mutable.init(gpa, .{ .caption = "bigr" });
    defer m.deinit();
    var arc_nid: meta.Nid = undefined;
    {
        // Build a big R in a scratch arena freed before the value is read
        // back: insert must dupe the magnitude bytes into the subgraph arena.
        var scratch = std.heap.ArenaAllocator.init(gpa);
        defer scratch.deinit();
        const v = try R.addAlloc(scratch.allocator(), R.fromInt(std.math.maxInt(i64)), R.one);
        const arc = try m.insert(schema.SymbolArc{ .pos = Vec2R.xy(0, 0), .radius = v });
        arc_nid = arc.nid;
    }
    const beyond = try R.addAlloc(arena, R.fromInt(std.math.maxInt(i64)), R.one); // 2^63
    const stored = m.view().getNodeAs(schema.SymbolArc, arc_nid).?.radius.?;
    try std.testing.expect(stored == .big);
    try std.testing.expect(stored.eql(beyond));

    // Wire round trip preserves value and content hash:
    const f = try m.freeze();
    defer f.release();
    const blob = try serialize.encodeTransfer(f, gpa);
    defer gpa.free(blob);
    const f2 = try serialize.decodeTransfer(schema.Symbol, gpa, blob, serialize.NoResolver{}, f.header.hash);
    defer f2.release();
    try std.testing.expect(f2.view().getNodeAs(schema.SymbolArc, arc_nid).?.radius.?.eql(beyond));

    // Values beyond i128 exercise the bignum tag 2/3 wire paths (negative
    // numerators use tag 3 with the magnitude-minus-one adjustment):
    const sq = try R.mulAlloc(arena, beyond, beyond);
    const huge = (try R.mulAlloc(arena, sq, sq)).neg(); // -(2^252)
    var m2 = try SymbolSG.Mutable.init(gpa, .{});
    defer m2.deinit();
    _ = try m2.insert(schema.SymbolArc{ .pos = Vec2R.xy(0, 0), .radius = huge });
    const g = try m2.freeze();
    defer g.release();
    const blob2 = try serialize.encodeTransfer(g, gpa);
    defer gpa.free(blob2);
    const g2 = try serialize.decodeTransfer(schema.Symbol, gpa, blob2, serialize.NoResolver{}, g.header.hash);
    defer g2.release();
    const arcs = try g2.view().all(schema.SymbolArc, gpa);
    defer gpa.free(arcs);
    try std.testing.expect(arcs[0].field(.radius).?.eql(huge));
}

test "transfer round trip without references" {
    const a = try makeSymbolA();
    defer a.release();

    const blob = try serialize.encodeTransfer(a, gpa);
    defer gpa.free(blob);

    const b = try serialize.decodeTransfer(schema.Symbol, gpa, blob, serialize.NoResolver{}, a.header.hash);
    defer b.release();
    try std.testing.expect(a.eqlContent(b));

    // Re-encode gives byte-identical transfer form:
    const blob2 = try serialize.encodeTransfer(b, gpa);
    defer gpa.free(blob2);
    try std.testing.expectEqualSlices(u8, blob, blob2);

    // Decoded subgraph is fully usable:
    const pin_a = try (try b.root().at("a")).as(schema.Pin);
    try std.testing.expectEqual(schema.PinType.in, pin_a.get().pintype);
}

test "transfer with parent chain and subgraph refs" {
    const sym = try makeSymbolA();
    defer sym.release();

    var resolver_map: std.AutoArrayHashMapUnmanaged([32]u8, *meta.FrozenHeader) = .empty;
    defer resolver_map.deinit(gpa);
    const resolver = serialize.MapResolver{ .map = &resolver_map };
    try resolver_map.put(gpa, sym.header.hash, &sym.header);

    // Layout chain: gen0 (one rect), gen1 (adds a pin + tombstones nothing):
    var m0 = try LayoutSG.Mutable.init(gpa, .{ .symbol = .of(sym) });
    defer m0.deinit();
    const r = try m0.insert(schema.LayoutRect{ .rect = try Rect4I.init(0, 0, 10, 10) });
    const f0 = try m0.freeze();
    defer f0.release();
    try resolver_map.put(gpa, f0.header.hash, &f0.header);

    var m1 = try f0.thaw();
    defer m1.deinit();
    _ = try m1.insert(schema.LayoutPin{ .ref = .to(r.nid), .pin = .to(1) });
    const f1 = try m1.freeze();
    defer f1.release();

    // Serialize gen1 only; decode against the resolver that has gen0 + sym:
    const blob = try serialize.encodeTransfer(f1, gpa);
    defer gpa.free(blob);
    const f1b = try serialize.decodeTransfer(schema.Layout, gpa, blob, resolver, f1.header.hash);
    defer f1b.release();
    try std.testing.expect(f1.eqlContent(f1b));
    try std.testing.expectEqual(1, f1b.parents.len);
    try std.testing.expectEqual(f0, f1b.parents[0].frozen);

    // Missing dependency: empty resolver
    var empty_map: std.AutoArrayHashMapUnmanaged([32]u8, *meta.FrozenHeader) = .empty;
    defer empty_map.deinit(gpa);
    try std.testing.expectError(
        error.MissingDependency,
        serialize.decodeTransfer(schema.Layout, gpa, blob, serialize.MapResolver{ .map = &empty_map }, null),
    );

    // Tampered blob: flip a byte in the middle
    const tampered = try gpa.dupe(u8, blob);
    defer gpa.free(tampered);
    tampered[tampered.len / 2] ^= 0x01;
    const result = serialize.decodeTransfer(schema.Layout, gpa, tampered, resolver, f1.header.hash);
    if (result) |f_bad| {
        f_bad.release();
        return error.TestExpectedError;
    } else |err| {
        // Either structurally malformed or content hash mismatch; both fine.
        switch (err) {
            error.HashMismatch, error.Malformed, error.UnexpectedType, error.UnknownNodeType, error.EndOfInput, error.Overflow, error.WrongNodeType, error.WrongVersion, error.MissingDependency => {},
            else => return err,
        }
    }
}

test "tombstones survive the transfer form" {
    var m0 = try SymbolSG.Mutable.init(gpa, .{});
    defer m0.deinit();
    const p1 = try m0.insert(schema.Pin{ .pos = Vec2R.xy(0, 0) });
    _ = try m0.insert(schema.Pin{ .pos = Vec2R.xy(1, 1) });
    const f0 = try m0.freeze();
    defer f0.release();

    var m1 = try f0.thaw();
    defer m1.deinit();
    try (try m1.view().cursorAt(schema.Pin, p1.nid)).remove();
    const f1 = try m1.freeze();
    defer f1.release();

    var resolver_map: std.AutoArrayHashMapUnmanaged([32]u8, *meta.FrozenHeader) = .empty;
    defer resolver_map.deinit(gpa);
    try resolver_map.put(gpa, f0.header.hash, &f0.header);

    const blob = try serialize.encodeTransfer(f1, gpa);
    defer gpa.free(blob);
    const f1b = try serialize.decodeTransfer(schema.Symbol, gpa, blob, serialize.MapResolver{ .map = &resolver_map }, f1.header.hash);
    defer f1b.release();

    try std.testing.expectEqual(null, f1b.view().getNode(p1.nid));
    const pins = try f1b.view().all(schema.Pin, gpa);
    defer gpa.free(pins);
    try std.testing.expectEqual(1, pins.len);
}
