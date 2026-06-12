// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Canonical CBOR serialization of subgraphs and the sha256 content hash.
//!
//! Two wire forms exist:
//!
//! Content form (the hash input; fully flattened merged view):
//!   [1, root_type: tstr, nid_end: uint,
//!    [[nid: uint, entry], ...]]              ; ascending nid, no tombstones
//!
//! Transfer form (what travels over the network; this generation's delta):
//!   [0, root_type: tstr,
//!    [[parent_hash: bstr(32), offset: uint], ...],
//!    nid_end: uint,
//!    [[nid: uint, entry / null], ...]]       ; ascending nid, null = tombstone
//!
//! entry = [ntype_name: tstr, [attr, ...]]    ; attrs in field declaration order
//! attr  = null / bool / int (bignum tags 2/3 beyond 64 bit) / tstr (Str)
//!       / R -> tag 30 (rational number) over [num, den]; each component an
//!         int (bignum tags 2/3 beyond 64 bit), den > 0
//!       / struct -> array of fields in declaration order (Vec2*, Rect4*,
//!         GdsLayer, RGBColor, ...)
//!       / enum -> uint (the enum's declared integer values)
//!       / Name -> tstr | int
//!       / LocalRef, ExternalRef -> uint nid / null
//!       / SubgraphRef -> bstr(32) content hash / null
//!
//! The *content hash* (sha256 of the content form) is the globally unique ID
//! of a subgraph: identical content gives an identical hash regardless of
//! freeze/thaw history. SubgraphRef attributes serialize as the target's
//! content hash, so subgraphs form a Merkle DAG.

const std = @import("std");
const Allocator = std.mem.Allocator;
const meta = @import("meta.zig");
const cbor = @import("cbor.zig");
const sg = @import("subgraph.zig");
const rational = @import("rational.zig");

const Sha256 = std.crypto.hash.sha2.Sha256;

pub const content_version = 1;
pub const transfer_version = 0;

pub const DecodeError = cbor.DecodeError || Allocator.Error || error{
    MissingDependency,
    HashMismatch,
    WrongNodeType,
    UnknownNodeType,
    WrongVersion,
};

// Attribute encoding
// ------------------

fn encodeValue(e: cbor.Encoder, v: anytype) Allocator.Error!void {
    const T = @TypeOf(v);
    if (T == meta.Name) {
        switch (v) {
            .s => |s| try e.textString(s),
            .i => |i| try e.int(i),
        }
        return;
    }
    if (T == rational.R) {
        // CBOR tag 30: rational number over [numerator, denominator].
        try e.tag(30);
        try e.array(2);
        switch (v) {
            .small => |s| {
                try e.int(s.num);
                try e.uint(@intCast(s.den));
            },
            .big => |b| {
                try e.intMag(b.negative, b.numMag());
                try e.intMag(false, b.denMag());
            },
        }
        return;
    }
    switch (comptime meta.attrKind(T)) {
        .local_ref, .external_ref => {
            if (v.nid) |nid| try e.uint(nid) else try e.@"null"();
        },
        .subgraph_ref => {
            if (v.ptr) |h| {
                try e.byteString(&h.hash);
            } else {
                try e.@"null"();
            }
        },
        .plain => switch (@typeInfo(T)) {
            .optional => {
                if (v) |inner| try encodeValue(e, inner) else try e.@"null"();
            },
            .bool => try e.boolean(v),
            .int => try e.int(v),
            .@"enum" => try e.uint(@intFromEnum(v)),
            .pointer => try e.textString(v), // Str
            .@"struct" => |s| {
                try e.array(s.fields.len);
                inline for (s.fields) |f| try encodeValue(e, @field(v, f.name));
            },
            else => @compileError("unserializable attribute type " ++ @typeName(T)),
        },
    }
}

fn decodeValue(comptime T: type, d: *cbor.Decoder, arena: Allocator, resolver: anytype) DecodeError!T {
    if (T == meta.Name) {
        return switch (try d.peekMajor()) {
            .text => .{ .s = try arena.dupe(u8, try d.textString()) },
            else => .{ .i = std.math.cast(i64, try d.int()) orelse return error.Overflow },
        };
    }
    if (T == rational.R) {
        if (try d.tagValue() != 30) return error.UnexpectedType;
        if (try d.arrayLen() != 2) return error.Malformed;
        const num = try d.intAny(arena);
        const den = try d.intAny(arena);
        var nbuf: [16]u8 = undefined;
        var dbuf: [16]u8 = undefined;
        const np = intItemParts(num, &nbuf);
        const dp = intItemParts(den, &dbuf);
        if (dp.negative) return error.Malformed;
        return rational.R.fromMags(arena, np.negative, np.mag, dp.mag) catch |err| switch (err) {
            error.DivisionByZero => error.Malformed,
            error.Overflow => error.Overflow,
            error.OutOfMemory => error.OutOfMemory,
        };
    }
    switch (comptime meta.attrKind(T)) {
        .local_ref, .external_ref => {
            if (try d.peekIsNull()) {
                try d.@"null"();
                return .{ .nid = null };
            }
            return .{ .nid = std.math.cast(meta.Nid, try d.uint()) orelse return error.Overflow };
        },
        .subgraph_ref => {
            if (try d.peekIsNull()) {
                try d.@"null"();
                return .{ .ptr = null };
            }
            const hs = try d.byteString();
            if (hs.len != 32) return error.Malformed;
            var hash: [32]u8 = undefined;
            @memcpy(&hash, hs);
            const h = resolver.get(hash) orelse return error.MissingDependency;
            return .{ .ptr = h };
        },
        .plain => switch (@typeInfo(T)) {
            .optional => |o| {
                if (try d.peekIsNull()) {
                    try d.@"null"();
                    return null;
                }
                return try decodeValue(o.child, d, arena, resolver);
            },
            .bool => return try d.boolean(),
            .int => return std.math.cast(T, try d.int()) orelse error.Overflow,
            .@"enum" => return intToEnum(T, try d.uint()) orelse error.Malformed,
            .pointer => return try arena.dupe(u8, try d.textString()),
            .@"struct" => |s| {
                if (try d.arrayLen() != s.fields.len) return error.Malformed;
                var out: T = undefined;
                inline for (s.fields) |f| {
                    @field(out, f.name) = try decodeValue(f.type, d, arena, resolver);
                }
                return out;
            },
            else => @compileError("unserializable attribute type " ++ @typeName(T)),
        },
    }
}

/// Sign + big-endian magnitude of a decoded integer; i128 values render
/// into the caller's buffer.
fn intItemParts(item: cbor.IntItem, buf: *[16]u8) struct { negative: bool, mag: []const u8 } {
    switch (item) {
        .small => |v| {
            const m: u128 = @abs(v);
            std.mem.writeInt(u128, buf, m, .big);
            var s: usize = 0;
            while (s < buf.len and buf[s] == 0) s += 1;
            return .{ .negative = v < 0, .mag = buf[s..] };
        },
        .big => |b| return .{ .negative = b.negative, .mag = b.mag },
    }
}

fn intToEnum(comptime T: type, v: u64) ?T {
    inline for (comptime std.enums.values(T)) |ev| {
        if (@intFromEnum(ev) == v) return ev;
    }
    return null;
}

fn encodeNode(comptime SG: type, e: cbor.Encoder, node: SG.Node) Allocator.Error!void {
    switch (node) {
        inline else => |v, tag| {
            const T = @TypeOf(v);
            try e.array(2);
            try e.textString(@tagName(tag));
            try e.array(std.meta.fields(T).len);
            inline for (std.meta.fields(T)) |f| try encodeValue(e, @field(v, f.name));
        },
    }
}

fn decodeNode(comptime SG: type, d: *cbor.Decoder, arena: Allocator, resolver: anytype) DecodeError!SG.Node {
    if (try d.arrayLen() != 2) return error.Malformed;
    const tname = try d.textString();
    inline for (std.meta.fields(SG.Node)) |uf| {
        if (std.mem.eql(u8, tname, uf.name)) {
            const T = uf.type;
            if (try d.arrayLen() != std.meta.fields(T).len) return error.Malformed;
            var v: T = undefined;
            inline for (std.meta.fields(T)) |f| {
                @field(v, f.name) = try decodeValue(f.type, d, arena, resolver);
            }
            return @unionInit(SG.Node, uf.name, v);
        }
    }
    return error.UnknownNodeType;
}

// Content form and hash
// ---------------------

/// Encode the fully flattened content form of a frozen subgraph (the input
/// of the content hash). f: *Subgraph(Root).Frozen.
pub fn encodeContent(f: anytype, gpa: Allocator) Allocator.Error![]u8 {
    const SG = @TypeOf(f.*).Owner;
    var buf: std.ArrayList(u8) = .empty;
    errdefer buf.deinit(gpa);
    const e = cbor.Encoder.init(&buf, gpa);

    try e.array(4);
    try e.uint(content_version);
    try e.textString(SG.root_type_name);
    try e.uint(f.nid_end);

    const nids = try f.view().allNids(gpa);
    defer gpa.free(nids);
    try e.array(nids.len);
    for (nids) |nid| {
        try e.array(2);
        try e.uint(nid);
        try encodeNode(SG, e, SG.getNodeG(f, nid).?);
    }
    return buf.toOwnedSlice(gpa);
}

/// Compute and store the content hash of a freshly frozen subgraph.
/// Called by Subgraph(Root).Mutable.freeze().
pub fn computeContentHash(f: anytype) Allocator.Error!void {
    const bytes = try encodeContent(f, f.gpa);
    defer f.gpa.free(bytes);
    Sha256.hash(bytes, &f.header.hash, .{});
}

// Transfer form
// -------------

/// Encode the transfer form: parent references plus this generation's delta.
pub fn encodeTransfer(f: anytype, gpa: Allocator) Allocator.Error![]u8 {
    const SG = @TypeOf(f.*).Owner;
    var buf: std.ArrayList(u8) = .empty;
    errdefer buf.deinit(gpa);
    const e = cbor.Encoder.init(&buf, gpa);

    try e.array(5);
    try e.uint(transfer_version);
    try e.textString(SG.root_type_name);

    try e.array(f.parents.len);
    for (f.parents) |p| {
        try e.array(2);
        try e.byteString(&p.frozen.header.hash);
        try e.uint(p.offset);
    }

    try e.uint(f.nid_end);

    const nids = try gpa.dupe(meta.Nid, f.nodes.keys());
    defer gpa.free(nids);
    std.mem.sort(meta.Nid, nids, {}, std.sort.asc(meta.Nid));
    try e.array(nids.len);
    for (nids) |nid| {
        try e.array(2);
        try e.uint(nid);
        switch (f.nodes.get(nid).?) {
            .node => |n| try encodeNode(SG, e, n),
            .tombstone => try e.@"null"(),
        }
    }
    return buf.toOwnedSlice(gpa);
}

/// Decode a transfer blob into a frozen subgraph. Parent subgraphs and
/// SubgraphRef targets are resolved through `resolver` (anything with
/// `fn get(self, hash: [32]u8) ?*meta.FrozenHeader`). If `expected_hash` is
/// given, the recomputed content hash must match (error.HashMismatch).
pub fn decodeTransfer(
    comptime Root: type,
    gpa: Allocator,
    bytes: []const u8,
    resolver: anytype,
    expected_hash: ?[32]u8,
) DecodeError!*sg.Subgraph(Root).Frozen {
    const SG = sg.Subgraph(Root);
    var d = cbor.Decoder.init(bytes);

    if (try d.arrayLen() != 5) return error.Malformed;
    if (try d.uint() != transfer_version) return error.WrongVersion;
    if (!std.mem.eql(u8, try d.textString(), SG.root_type_name)) return error.WrongNodeType;

    var m: SG.Mutable = .{
        .gpa = gpa,
        .arena = std.heap.ArenaAllocator.init(gpa),
        .parents = &.{},
        .nodes = .empty,
        .index = .empty,
        .nid_next = 0,
        .base_nid_end = 0,
    };
    errdefer m.deinit();
    const arena = m.arena.allocator();

    const n_parents = try d.arrayLen();
    const parents = try arena.alloc(SG.Parent, n_parents);
    var offset_acc: meta.Nid = 0;
    for (parents, 0..) |*p, i| {
        // Retain progressively so errdefer m.deinit() releases exactly the
        // parents resolved so far:
        m.parents = parents[0..i];
        if (try d.arrayLen() != 2) return error.Malformed;
        const hs = try d.byteString();
        if (hs.len != 32) return error.Malformed;
        var hash: [32]u8 = undefined;
        @memcpy(&hash, hs);
        const offset = std.math.cast(meta.Nid, try d.uint()) orelse return error.Overflow;
        if (offset != offset_acc) return error.Malformed;
        const h = resolver.get(hash) orelse return error.MissingDependency;
        const frozen = SG.Frozen.fromHeader(h) catch return error.WrongNodeType;
        p.* = .{ .frozen = frozen.retain(), .offset = offset };
        offset_acc += frozen.nid_end;
    }
    m.parents = parents;
    m.base_nid_end = offset_acc;

    const nid_end = std.math.cast(meta.Nid, try d.uint()) orelse return error.Overflow;

    const n_delta = try d.arrayLen();
    var i: usize = 0;
    while (i < n_delta) : (i += 1) {
        if (try d.arrayLen() != 2) return error.Malformed;
        const nid = std.math.cast(meta.Nid, try d.uint()) orelse return error.Overflow;
        if (m.nodes.contains(nid)) return error.Malformed;
        if (try d.peekIsNull()) {
            try d.@"null"();
            try m.nodes.put(arena, nid, .tombstone);
        } else {
            const node = try decodeNode(SG, &d, arena, resolver);
            switch (node) {
                inline else => |v| meta.retainSubgraphRefs(@TypeOf(v), v),
            }
            try m.nodes.put(arena, nid, .{ .node = node });
            try m.index.addNode(arena, node, nid);
        }
    }
    if (!d.atEnd()) return error.Malformed;

    m.nid_next = nid_end;
    const f = try m.freeze();
    errdefer f.release();
    if (expected_hash) |exp| {
        if (!std.mem.eql(u8, &f.header.hash, &exp)) return error.HashMismatch;
    }
    return f;
}

/// Resolver over a plain hash map (tests; the Store provides its own).
pub const MapResolver = struct {
    map: *const std.AutoArrayHashMapUnmanaged([32]u8, *meta.FrozenHeader),

    pub fn get(self: MapResolver, hash: [32]u8) ?*meta.FrozenHeader {
        return self.map.get(hash);
    }
};

pub const NoResolver = struct {
    pub fn get(self: NoResolver, hash: [32]u8) ?*meta.FrozenHeader {
        _ = self;
        _ = hash;
        return null;
    }
};
