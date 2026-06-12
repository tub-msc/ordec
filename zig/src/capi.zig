// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! C ABI for using this library from other languages (the Python bridge in
//! ordec/zigbridge/ is the primary consumer; see docs/dev/zigbridge.rst).
//!
//! Request envelope (canonical CBOR, definite lengths):
//!   [abi_version = 1, args, bundle]
//!   args   = null                                               ; ordec_echo
//!          | [die_width: int, site_width: int, row_height: int] ; ordec_place
//!   bundle = [bstr(transfer blob), ...]   ; dependency order, top subgraph LAST
//!
//! Response (return code 0):  CBOR [bstr(result transfer blob), ...]
//! Response (return code !=0): CBOR [code: int, message: tstr]
//!   codes: 1 bad envelope, 2 blob decode error, 3 domain error,
//!          4 out of memory, 5 internal error
//!
//! Result blobs are single-generation (compact()ed before encoding) and only
//! reference subgraph hashes that were present in the request bundle, so the
//! caller can decode them against the dependency set it already holds.
//!
//! Out buffers are allocated by this library and must be freed with
//! ordec_free. If the returned out_len is 0 (allocation of even the error
//! envelope failed), no buffer was allocated and ordec_free must not be
//! called.

const std = @import("std");
const Allocator = std.mem.Allocator;
const ordb = @import("ordb");
const meta = ordb.meta;
const schema = ordb.schema;
const sgmod = ordb.subgraph;
const serialize = ordb.serialize;
const cbor = ordb.cbor;
const placer = ordb.placer;

const LayoutSG = schema.LayoutSG;

pub const abi_version = 1;

/// SubgraphRoot types accepted in bundles (dispatch table for decode).
const roots = .{ schema.LayerStack, schema.Symbol, schema.Schematic, schema.Layout };

// Exports
// -------

export fn ordec_abi_version() u32 {
    return abi_version;
}

/// Decode the bundle and return the top subgraph compacted and re-encoded.
/// Exists so callers can verify their encoder, the transport and this
/// library's decoder in isolation (round trip + content hash comparison)
/// before involving any compute function.
export fn ordec_echo(in_ptr: [*]const u8, in_len: usize, out_ptr: *?[*]u8, out_len: *usize) i32 {
    return entry(.echo, in_ptr, in_len, out_ptr, out_len);
}

export fn ordec_place(in_ptr: [*]const u8, in_len: usize, out_ptr: *?[*]u8, out_len: *usize) i32 {
    return entry(.place, in_ptr, in_len, out_ptr, out_len);
}

export fn ordec_free(ptr: [*]u8, len: usize) void {
    std.heap.c_allocator.free(ptr[0..len]);
}

const Func = enum { echo, place };

fn entry(func: Func, in_ptr: [*]const u8, in_len: usize, out_ptr: *?[*]u8, out_len: *usize) i32 {
    // c_allocator, because out buffers outlive the call and ordec_free must
    // be able to free exactly [ptr..ptr+len] without further context (and
    // the library links libc anyway for the C ABI).
    const result = run(std.heap.c_allocator, in_ptr[0..in_len], func);
    if (result.out.len == 0) {
        out_ptr.* = null;
        out_len.* = 0;
    } else {
        out_ptr.* = result.out.ptr;
        out_len.* = result.out.len;
    }
    return result.rc;
}

// Implementation (allocator-parametrized so tests can leak-check)
// ---------------------------------------------------------------

const RunResult = struct { rc: i32, out: []u8 };

fn run(gpa: Allocator, in: []const u8, func: Func) RunResult {
    if (handle(gpa, in, func)) |out| {
        return .{ .rc = 0, .out = out };
    } else |err| {
        const code = errorCode(err);
        const out = encodeError(gpa, code, @errorName(err)) catch
            return .{ .rc = 4, .out = &.{} };
        return .{ .rc = code, .out = out };
    }
}

fn errorCode(err: anyerror) i32 {
    return switch (err) {
        error.BadEnvelope => 1,
        // Everything decodeTransfer / bundle handling can raise:
        error.Malformed,
        error.UnexpectedType,
        error.EndOfInput,
        error.Overflow,
        error.MissingDependency,
        error.HashMismatch,
        error.WrongNodeType,
        error.UnknownNodeType,
        error.WrongVersion,
        => 2,
        error.OutOfMemory => 4,
        else => if (inErrorSet(placer.PlacerError, err)) 3 else 5,
    };
}

fn inErrorSet(comptime Set: type, err: anyerror) bool {
    inline for (@typeInfo(Set).error_set.?) |e| {
        if (std.mem.eql(u8, e.name, @errorName(err))) return true;
    }
    return false;
}

fn encodeError(gpa: Allocator, code: i32, message: []const u8) Allocator.Error![]u8 {
    var buf: std.ArrayList(u8) = .empty;
    errdefer buf.deinit(gpa);
    const e = cbor.Encoder.init(&buf, gpa);
    try e.array(2);
    try e.int(code);
    try e.textString(message);
    return buf.toOwnedSlice(gpa);
}

const Envelope = struct {
    opts: ?placer.PlacerOpts,
    /// Blob slices point into the request buffer; only the outer slice is
    /// gpa-allocated.
    blobs: [][]const u8,
};

fn parseEnvelope(gpa: Allocator, in: []const u8, func: Func) error{ BadEnvelope, OutOfMemory }!Envelope {
    var d = cbor.Decoder.init(in);
    return parseEnvelopeInner(gpa, &d, func) catch |err| switch (err) {
        error.OutOfMemory => |e| e,
        else => error.BadEnvelope,
    };
}

fn parseEnvelopeInner(gpa: Allocator, d: *cbor.Decoder, func: Func) !Envelope {
    if (try d.arrayLen() != 3) return error.BadEnvelope;
    if (try d.uint() != abi_version) return error.BadEnvelope;
    var opts: ?placer.PlacerOpts = null;
    switch (func) {
        .echo => try d.@"null"(),
        .place => {
            if (try d.arrayLen() != 3) return error.BadEnvelope;
            const die_width = std.math.cast(i32, try d.int()) orelse return error.BadEnvelope;
            const site_width = std.math.cast(i32, try d.int()) orelse return error.BadEnvelope;
            const row_height = std.math.cast(i32, try d.int()) orelse return error.BadEnvelope;
            if (die_width <= 0 or site_width <= 0 or row_height <= 0) return error.BadEnvelope;
            opts = .{ .die_width = die_width, .site_width = site_width, .row_height = row_height };
        },
    }
    const n = try d.arrayLen();
    if (n == 0) return error.BadEnvelope;
    const blobs = try gpa.alloc([]const u8, n);
    errdefer gpa.free(blobs);
    for (blobs) |*b| b.* = try d.byteString();
    if (!d.atEnd()) return error.BadEnvelope;
    return .{ .opts = opts, .blobs = blobs };
}

fn handle(gpa: Allocator, in: []const u8, func: Func) ![]u8 {
    const env = try parseEnvelope(gpa, in, func);
    defer gpa.free(env.blobs);

    // hash -> decoded frozen; the map owns one reference on each value.
    var map: std.AutoArrayHashMapUnmanaged([32]u8, *meta.FrozenHeader) = .empty;
    defer {
        for (map.values()) |h| h.release();
        map.deinit(gpa);
    }

    var top: *meta.FrozenHeader = undefined;
    for (env.blobs) |blob| top = try decodeBlob(gpa, blob, &map);

    switch (func) {
        .echo => return echoResponse(gpa, top),
        .place => {
            const layout = LayoutSG.Frozen.fromHeader(top) catch return error.WrongNodeType;
            const placed = try placer.place(layout, env.opts.?, gpa);
            defer placed.release();
            return encodeResponse(gpa, placed);
        },
    }
}

/// Decode one bundle blob, dispatching on its root type, and register it in
/// `map` so later blobs (and the response check) can resolve it by hash.
fn decodeBlob(
    gpa: Allocator,
    blob: []const u8,
    map: *std.AutoArrayHashMapUnmanaged([32]u8, *meta.FrozenHeader),
) !*meta.FrozenHeader {
    const root_name = try peekRootName(blob);
    const resolver = serialize.MapResolver{ .map = map };
    inline for (roots) |Root| {
        const SG = sgmod.Subgraph(Root);
        if (std.mem.eql(u8, root_name, SG.root_type_name)) {
            const f = try serialize.decodeTransfer(Root, gpa, blob, resolver, null);
            errdefer f.release();
            const gop = try map.getOrPut(gpa, f.header.hash);
            // Duplicate hashes would leave one frozen unreleased; reject.
            if (gop.found_existing) return error.Malformed;
            gop.value_ptr.* = &f.header;
            return &f.header;
        }
    }
    return error.UnknownNodeType;
}

fn peekRootName(blob: []const u8) ![]const u8 {
    var d = cbor.Decoder.init(blob);
    if (try d.arrayLen() != 5) return error.Malformed;
    if (try d.uint() != serialize.transfer_version) return error.WrongVersion;
    return d.textString();
}

fn echoResponse(gpa: Allocator, top: *meta.FrozenHeader) ![]u8 {
    inline for (roots) |Root| {
        if (sgmod.Subgraph(Root).Frozen.fromHeader(top)) |f| {
            return encodeResponse(gpa, f);
        } else |_| {}
    }
    unreachable; // decodeBlob only produces the dispatched root types
}

/// Compact (single-generation form) and wrap in a one-element response bundle.
fn encodeResponse(gpa: Allocator, f: anytype) ![]u8 {
    const compacted = try f.compact();
    defer compacted.release();
    const blob = try serialize.encodeTransfer(compacted, gpa);
    defer gpa.free(blob);

    var buf: std.ArrayList(u8) = .empty;
    errdefer buf.deinit(gpa);
    const e = cbor.Encoder.init(&buf, gpa);
    try e.array(1);
    try e.byteString(blob);
    return buf.toOwnedSlice(gpa);
}

// Tests
// -----

const gpa_t = std.testing.allocator;
const Vec2I = ordb.Vec2I;

/// Transfer-encode any frozen via its header (test helper).
fn encodeTransferAny(gpa: Allocator, h: *meta.FrozenHeader) ![]u8 {
    inline for (roots) |Root| {
        if (sgmod.Subgraph(Root).Frozen.fromHeader(h)) |f| {
            return serialize.encodeTransfer(f, gpa);
        } else |_| {}
    }
    unreachable;
}

fn buildRequest(gpa: Allocator, opts: ?placer.PlacerOpts, deps: []const *meta.FrozenHeader) ![]u8 {
    var buf: std.ArrayList(u8) = .empty;
    errdefer buf.deinit(gpa);
    const e = cbor.Encoder.init(&buf, gpa);
    try e.array(3);
    try e.uint(abi_version);
    if (opts) |o| {
        try e.array(3);
        try e.int(o.die_width);
        try e.int(o.site_width);
        try e.int(o.row_height);
    } else {
        try e.@"null"();
    }
    try e.array(deps.len);
    for (deps) |h| {
        const blob = try encodeTransferAny(gpa, h);
        defer gpa.free(blob);
        try e.byteString(blob);
    }
    return buf.toOwnedSlice(gpa);
}

/// The full dependency closure of the fake-PDK placer input, in bundle order
/// (each cell's symbol before the cell layout, input last).
fn pdkDeps(pdk: *const placer.FakePdk, input: *LayoutSG.Frozen) [8]*meta.FrozenHeader {
    return .{
        &pdk.layers.header,
        pdk.inv.root().get().symbol.ptr.?,
        &pdk.inv.header,
        pdk.nand2.root().get().symbol.ptr.?,
        &pdk.nand2.header,
        pdk.dff.root().get().symbol.ptr.?,
        &pdk.dff.header,
        &input.header,
    };
}

fn buildUnplacedInput(gpa: Allocator, pdk: *const placer.FakePdk) !*LayoutSG.Frozen {
    var m = try LayoutSG.Mutable.init(gpa, .{ .ref_layers = .of(pdk.layers) });
    defer m.deinit();
    for (0..4) |_| _ = try m.insert(schema.LayoutInstance{ .pos = Vec2I.zero, .ref = .of(pdk.inv) });
    for (0..3) |_| _ = try m.insert(schema.LayoutInstance{ .pos = Vec2I.zero, .ref = .of(pdk.nand2) });
    _ = try m.insert(schema.LayoutInstanceArray{
        .pos = Vec2I.zero,
        .ref = .of(pdk.dff),
        .cols = 2,
        .rows = 1,
        .vec_col = Vec2I.xy(900, 0),
        .vec_row = Vec2I.xy(0, 800),
    });
    return m.freeze();
}

test "capi: place request round trip" {
    var pdk = try placer.buildFakePdk(gpa_t);
    defer pdk.deinit();
    const input = try buildUnplacedInput(gpa_t, &pdk);
    defer input.release();

    const opts = placer.PlacerOpts{
        .die_width = 2000,
        .site_width = placer.fake_site_width,
        .row_height = placer.fake_row_height,
    };
    const deps = pdkDeps(&pdk, input);
    const request = try buildRequest(gpa_t, opts, &deps);
    defer gpa_t.free(request);

    const result = run(gpa_t, request, .place);
    defer gpa_t.free(result.out);
    try std.testing.expectEqual(0, result.rc);

    // Decode the response bundle against the dependencies we already hold:
    var resolver_map: std.AutoArrayHashMapUnmanaged([32]u8, *meta.FrozenHeader) = .empty;
    defer resolver_map.deinit(gpa_t);
    for (deps) |h| try resolver_map.put(gpa_t, h.hash, h);

    var d = cbor.Decoder.init(result.out);
    try std.testing.expectEqual(1, try d.arrayLen());
    const blob = try d.byteString();
    const placed = try serialize.decodeTransfer(
        schema.Layout,
        gpa_t,
        blob,
        serialize.MapResolver{ .map = &resolver_map },
        null,
    );
    defer placed.release();

    try placer.verifyLegal(placed, opts, gpa_t);
    const insts = try placed.view().all(schema.LayoutInstance, gpa_t);
    defer gpa_t.free(insts);
    try std.testing.expectEqual(9, insts.len); // 4 + 3 + expanded 2x1 array

    // The input was not modified:
    const input_insts = try input.view().all(schema.LayoutInstance, gpa_t);
    defer gpa_t.free(input_insts);
    try std.testing.expectEqual(7, input_insts.len);
}

test "capi: echo round trip preserves the content hash" {
    var pdk = try placer.buildFakePdk(gpa_t);
    defer pdk.deinit();

    const request = try buildRequest(gpa_t, null, &.{&pdk.layers.header});
    defer gpa_t.free(request);

    const result = run(gpa_t, request, .echo);
    defer gpa_t.free(result.out);
    try std.testing.expectEqual(0, result.rc);

    var d = cbor.Decoder.init(result.out);
    try std.testing.expectEqual(1, try d.arrayLen());
    const blob = try d.byteString();
    // expected_hash makes decodeTransfer verify content equality for us:
    const echoed = try serialize.decodeTransfer(
        schema.LayerStack,
        gpa_t,
        blob,
        serialize.NoResolver{},
        pdk.layers.header.hash,
    );
    echoed.release();
}

fn expectErrorEnvelope(result: RunResult, code: i32, message: []const u8) !void {
    try std.testing.expectEqual(code, result.rc);
    var d = cbor.Decoder.init(result.out);
    try std.testing.expectEqual(2, try d.arrayLen());
    try std.testing.expectEqual(code, try d.int());
    try std.testing.expectEqualStrings(message, try d.textString());
}

test "capi: error envelopes" {
    var pdk = try placer.buildFakePdk(gpa_t);
    defer pdk.deinit();
    const input = try buildUnplacedInput(gpa_t, &pdk);
    defer input.release();
    const deps = pdkDeps(&pdk, input);
    const opts = placer.PlacerOpts{
        .die_width = 800, // dff is 9 sites = 900 wide -> CellTooWide
        .site_width = placer.fake_site_width,
        .row_height = placer.fake_row_height,
    };

    // Garbage request -> 1 (bad envelope):
    {
        const result = run(gpa_t, "\x00garbage", .echo);
        defer gpa_t.free(result.out);
        try expectErrorEnvelope(result, 1, "BadEnvelope");
    }

    // Truncated blob in the bundle -> 2 (blob decode error):
    {
        const blob = try serialize.encodeTransfer(pdk.layers, gpa_t);
        defer gpa_t.free(blob);
        var buf: std.ArrayList(u8) = .empty;
        defer buf.deinit(gpa_t);
        const e = cbor.Encoder.init(&buf, gpa_t);
        try e.array(3);
        try e.uint(abi_version);
        try e.@"null"();
        try e.array(1);
        try e.byteString(blob[0 .. blob.len / 2]);
        const result = run(gpa_t, buf.items, .echo);
        defer gpa_t.free(result.out);
        try std.testing.expectEqual(2, result.rc);
    }

    // Missing dependency (input without the rest of the bundle) -> 2:
    {
        const request = try buildRequest(gpa_t, opts, &.{&input.header});
        defer gpa_t.free(request);
        const result = run(gpa_t, request, .place);
        defer gpa_t.free(result.out);
        try expectErrorEnvelope(result, 2, "MissingDependency");
    }

    // Domain error from the placer -> 3:
    {
        const request = try buildRequest(gpa_t, opts, &deps);
        defer gpa_t.free(request);
        const result = run(gpa_t, request, .place);
        defer gpa_t.free(result.out);
        try expectErrorEnvelope(result, 3, "CellTooWide");
    }
}
