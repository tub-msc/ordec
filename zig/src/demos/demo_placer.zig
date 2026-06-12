// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Standard-cell placer demo: builds a fake PDK (LayerStack + three cells),
//! an unplaced input layout, runs the placer, and prints the result.
//! Run with: zig build demo-placer

const std = @import("std");
const ordb = @import("ordb");
const schema = ordb.schema;
const placer = ordb.placer;
const Vec2I = ordb.Vec2I;

pub fn main() !void {
    var gpa_state: std.heap.DebugAllocator(.{}) = .init;
    defer _ = gpa_state.deinit();
    const gpa = gpa_state.allocator();
    const print = std.debug.print;

    var pdk = try placer.buildFakePdk(gpa);
    defer pdk.deinit();
    print("fake PDK: inv (3 sites), nand2 (4 sites), dff (9 sites)\n", .{});

    // Unplaced input: everything piled up at the origin.
    var m = try schema.LayoutSG.Mutable.init(gpa, .{ .ref_layers = .of(pdk.layers) });
    defer m.deinit();
    for (0..7) |_| _ = try m.insert(schema.LayoutInstance{ .pos = Vec2I.zero, .ref = .of(pdk.inv) });
    for (0..5) |_| _ = try m.insert(schema.LayoutInstance{ .pos = Vec2I.zero, .ref = .of(pdk.nand2) });
    for (0..4) |_| _ = try m.insert(schema.LayoutInstance{ .pos = Vec2I.zero, .ref = .of(pdk.dff) });
    _ = try m.insert(schema.LayoutInstanceArray{
        .pos = Vec2I.zero,
        .ref = .of(pdk.inv),
        .cols = 2,
        .rows = 2,
        .vec_col = Vec2I.xy(300, 0),
        .vec_row = Vec2I.xy(0, 800),
    });
    const input = try m.freeze();
    defer input.release();

    const opts = placer.PlacerOpts{
        .die_width = 2400,
        .site_width = placer.fake_site_width,
        .row_height = placer.fake_row_height,
    };

    const input_insts = try input.view().all(schema.LayoutInstance, gpa);
    print("input: {d} instances + one 2x2 array, all at the origin\n\n", .{input_insts.len});
    gpa.free(input_insts);

    const placed = try placer.place(input, opts, gpa);
    defer placed.release();
    try placer.verifyLegal(placed, opts, gpa);

    const map = try placer.asciiMap(placed, opts, gpa);
    defer gpa.free(map);
    print("placement ({d} units wide, {d}-unit sites, rows of {d}, odd rows MX-flipped):\n\n{s}\n", .{
        opts.die_width, opts.site_width, opts.row_height, map,
    });

    const insts = try placed.view().all(schema.LayoutInstance, gpa);
    defer gpa.free(insts);
    print("{d} instances legally placed. content hash: {x}\n", .{
        insts.len,
        placed.header.hash[0..8],
    });
}
