// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Minimal deterministic CBOR (RFC 8949) encoder and decoder.
//!
//! Only the subset needed for the ordb wire format: unsigned/negative
//! integers (minimal-length heads), byte strings, text strings, arrays
//! (definite length only), booleans, null, and bignums (tags 2/3) for
//! integers beyond 64 bits. No floats, no maps, no indefinite lengths --
//! which makes encodings canonical by construction.

const std = @import("std");
const Allocator = std.mem.Allocator;

pub const Major = enum(u3) {
    uint = 0,
    nint = 1,
    bytes = 2,
    text = 3,
    array = 4,
    map = 5,
    tag = 6,
    simple = 7,
};

pub const Encoder = struct {
    buf: *std.ArrayList(u8),
    alloc: Allocator,

    pub fn init(buf: *std.ArrayList(u8), alloc: Allocator) Encoder {
        return .{ .buf = buf, .alloc = alloc };
    }

    fn head(e: Encoder, major: Major, value: u64) Allocator.Error!void {
        const m: u8 = @as(u8, @intFromEnum(major)) << 5;
        if (value < 24) {
            try e.buf.append(e.alloc, m | @as(u8, @intCast(value)));
        } else if (value <= 0xff) {
            try e.buf.appendSlice(e.alloc, &.{ m | 24, @intCast(value) });
        } else if (value <= 0xffff) {
            try e.buf.append(e.alloc, m | 25);
            try e.buf.appendSlice(e.alloc, &std.mem.toBytes(std.mem.nativeToBig(u16, @intCast(value))));
        } else if (value <= 0xffff_ffff) {
            try e.buf.append(e.alloc, m | 26);
            try e.buf.appendSlice(e.alloc, &std.mem.toBytes(std.mem.nativeToBig(u32, @intCast(value))));
        } else {
            try e.buf.append(e.alloc, m | 27);
            try e.buf.appendSlice(e.alloc, &std.mem.toBytes(std.mem.nativeToBig(u64, value)));
        }
    }

    pub fn uint(e: Encoder, v: u64) Allocator.Error!void {
        try e.head(.uint, v);
    }

    /// Integer of up to 129 bits magnitude; uses bignum tags 2/3 beyond the
    /// 64-bit head range.
    pub fn int(e: Encoder, v: i128) Allocator.Error!void {
        if (v >= 0) {
            const mag: u128 = @intCast(v);
            if (mag <= std.math.maxInt(u64)) {
                try e.head(.uint, @intCast(mag));
            } else {
                try e.head(.tag, 2);
                try e.bignumMag(mag);
            }
        } else {
            // CBOR negative integers encode -1 - n:
            const mag: u128 = @as(u128, @intCast(-(v + 1)));
            if (mag <= std.math.maxInt(u64)) {
                try e.head(.nint, @intCast(mag));
            } else {
                try e.head(.tag, 3);
                try e.bignumMag(mag);
            }
        }
    }

    fn bignumMag(e: Encoder, mag: u128) Allocator.Error!void {
        var be = std.mem.toBytes(std.mem.nativeToBig(u128, mag));
        // Minimal-length magnitude (strip leading zero bytes):
        var start: usize = 0;
        while (start < be.len - 1 and be[start] == 0) start += 1;
        try e.head(.bytes, be.len - start);
        try e.buf.appendSlice(e.alloc, be[start..]);
    }

    pub fn tag(e: Encoder, v: u64) Allocator.Error!void {
        try e.head(.tag, v);
    }

    /// Integer of arbitrary size, given as sign + big-endian magnitude
    /// (at most 256 bytes). Canonical: head form whenever the value fits
    /// major type 0/1, bignum tags 2/3 beyond that.
    pub fn intMag(e: Encoder, negative: bool, mag_in: []const u8) Allocator.Error!void {
        var mag = mag_in;
        while (mag.len > 0 and mag[0] == 0) mag = mag[1..];
        if (mag.len == 0) return e.head(.uint, 0);
        std.debug.assert(mag.len <= 256);
        if (mag.len <= 16) {
            var m: u128 = 0;
            for (mag) |b| m = (m << 8) | b;
            // Reuse int() for everything in i128 range (m == 2^127 negated
            // is minInt(i128), still representable):
            if (!negative and m <= std.math.maxInt(i128))
                return e.int(@intCast(m));
            if (negative and m <= @as(u128, std.math.maxInt(i128)) + 1)
                return e.int(@intCast(-@as(i256, m)));
        }
        if (!negative) {
            try e.head(.tag, 2);
            try e.byteString(mag);
        } else {
            // CBOR tag 3 encodes -1 - n: emit (magnitude - 1).
            try e.head(.tag, 3);
            var buf: [256]u8 = undefined;
            const n = decrementMag(&buf, mag);
            try e.byteString(n);
        }
    }

    pub fn byteString(e: Encoder, s: []const u8) Allocator.Error!void {
        try e.head(.bytes, s.len);
        try e.buf.appendSlice(e.alloc, s);
    }

    pub fn textString(e: Encoder, s: []const u8) Allocator.Error!void {
        try e.head(.text, s.len);
        try e.buf.appendSlice(e.alloc, s);
    }

    pub fn array(e: Encoder, len: usize) Allocator.Error!void {
        try e.head(.array, len);
    }

    pub fn boolean(e: Encoder, v: bool) Allocator.Error!void {
        try e.buf.append(e.alloc, if (v) 0xf5 else 0xf4);
    }

    pub fn @"null"(e: Encoder) Allocator.Error!void {
        try e.buf.append(e.alloc, 0xf6);
    }
};

/// (magnitude - 1) of a nonzero big-endian magnitude, minimal-length.
fn decrementMag(buf: *[256]u8, mag: []const u8) []const u8 {
    const out = buf[0..mag.len];
    @memcpy(out, mag);
    var i = out.len;
    while (i > 0) {
        i -= 1;
        if (out[i] > 0) {
            out[i] -= 1;
            break;
        }
        out[i] = 0xff;
    }
    var start: usize = 0;
    while (start < out.len - 1 and out[start] == 0) start += 1;
    return out[start..];
}

/// Decoded integer of arbitrary size (see Decoder.intAny).
pub const IntItem = union(enum) {
    small: i128,
    /// Minimal big-endian magnitude of |value| (already +1-adjusted for
    /// tag 3); only used when the value does not fit i128.
    big: struct { negative: bool, mag: []const u8 },
};

pub const DecodeError = error{ Malformed, UnexpectedType, EndOfInput, Overflow };

pub const Decoder = struct {
    bytes: []const u8,
    pos: usize = 0,

    pub fn init(bytes: []const u8) Decoder {
        return .{ .bytes = bytes };
    }

    pub fn atEnd(d: *const Decoder) bool {
        return d.pos >= d.bytes.len;
    }

    fn byte(d: *Decoder) DecodeError!u8 {
        if (d.pos >= d.bytes.len) return error.EndOfInput;
        const b = d.bytes[d.pos];
        d.pos += 1;
        return b;
    }

    fn take(d: *Decoder, n: usize) DecodeError![]const u8 {
        if (d.pos + n > d.bytes.len) return error.EndOfInput;
        const s = d.bytes[d.pos .. d.pos + n];
        d.pos += n;
        return s;
    }

    pub const Head = struct { major: Major, value: u64, simple: u8 };

    pub fn peekMajor(d: *const Decoder) DecodeError!Major {
        if (d.pos >= d.bytes.len) return error.EndOfInput;
        return @enumFromInt(@as(u3, @intCast(d.bytes[d.pos] >> 5)));
    }

    pub fn peekIsNull(d: *const Decoder) DecodeError!bool {
        if (d.pos >= d.bytes.len) return error.EndOfInput;
        return d.bytes[d.pos] == 0xf6;
    }

    fn head(d: *Decoder) DecodeError!Head {
        const b = try d.byte();
        const major: Major = @enumFromInt(@as(u3, @intCast(b >> 5)));
        const info: u5 = @intCast(b & 0x1f);
        const value: u64 = switch (info) {
            0...23 => info,
            24 => try d.byte(),
            25 => std.mem.bigToNative(u16, std.mem.bytesToValue(u16, try d.take(2))),
            26 => std.mem.bigToNative(u32, std.mem.bytesToValue(u32, try d.take(4))),
            27 => std.mem.bigToNative(u64, std.mem.bytesToValue(u64, try d.take(8))),
            else => return error.Malformed, // indefinite lengths unsupported
        };
        return .{ .major = major, .value = value, .simple = b };
    }

    pub fn uint(d: *Decoder) DecodeError!u64 {
        const h = try d.head();
        if (h.major != .uint) return error.UnexpectedType;
        return h.value;
    }

    pub fn int(d: *Decoder) DecodeError!i128 {
        const h = try d.head();
        switch (h.major) {
            .uint => return h.value,
            .nint => return -1 - @as(i128, h.value),
            .tag => {
                if (h.value != 2 and h.value != 3) return error.UnexpectedType;
                const bh = try d.head();
                if (bh.major != .bytes) return error.Malformed;
                const raw = try d.take(bh.value);
                if (raw.len > 16) return error.Overflow;
                var mag: u128 = 0;
                for (raw) |b| mag = (mag << 8) | b;
                if (h.value == 2) {
                    return std.math.cast(i128, mag) orelse error.Overflow;
                } else {
                    const m1 = std.math.cast(i128, mag) orelse return error.Overflow;
                    return -1 - m1;
                }
            },
            else => return error.UnexpectedType,
        }
    }

    pub fn arrayLen(d: *Decoder) DecodeError!usize {
        const h = try d.head();
        if (h.major != .array) return error.UnexpectedType;
        return h.value;
    }

    pub fn tagValue(d: *Decoder) DecodeError!u64 {
        const h = try d.head();
        if (h.major != .tag) return error.UnexpectedType;
        return h.value;
    }

    /// Decode an integer of arbitrary size. Magnitudes beyond i128 are
    /// returned as borrowed bytes; tag-3 magnitudes (+1 adjustment) are
    /// materialized in `arena`.
    pub fn intAny(d: *Decoder, arena: Allocator) (DecodeError || Allocator.Error)!IntItem {
        const h = try d.head();
        switch (h.major) {
            .uint => return .{ .small = h.value },
            .nint => return .{ .small = -1 - @as(i128, h.value) },
            .tag => {
                if (h.value != 2 and h.value != 3) return error.UnexpectedType;
                const bh = try d.head();
                if (bh.major != .bytes) return error.Malformed;
                var raw = try d.take(bh.value);
                while (raw.len > 0 and raw[0] == 0) raw = raw[1..];
                if (raw.len <= 15) {
                    var m: i128 = 0;
                    for (raw) |b| m = (m << 8) | b;
                    return .{ .small = if (h.value == 2) m else -1 - m };
                }
                if (raw.len > 256) return error.Overflow;
                if (h.value == 2) return .{ .big = .{ .negative = false, .mag = raw } };
                // tag 3: |value| = n + 1; increment may grow by one byte.
                const out = try arena.alloc(u8, raw.len + 1);
                out[0] = 0;
                @memcpy(out[1..], raw);
                var i = out.len;
                while (i > 0) {
                    i -= 1;
                    if (out[i] != 0xff) {
                        out[i] += 1;
                        break;
                    }
                    out[i] = 0;
                }
                const start: usize = if (out[0] == 0) 1 else 0;
                return .{ .big = .{ .negative = true, .mag = out[start..] } };
            },
            else => return error.UnexpectedType,
        }
    }

    /// Returns a slice borrowing from the input.
    pub fn byteString(d: *Decoder) DecodeError![]const u8 {
        const h = try d.head();
        if (h.major != .bytes) return error.UnexpectedType;
        return d.take(h.value);
    }

    /// Returns a slice borrowing from the input.
    pub fn textString(d: *Decoder) DecodeError![]const u8 {
        const h = try d.head();
        if (h.major != .text) return error.UnexpectedType;
        return d.take(h.value);
    }

    pub fn boolean(d: *Decoder) DecodeError!bool {
        const b = try d.byte();
        return switch (b) {
            0xf4 => false,
            0xf5 => true,
            else => error.UnexpectedType,
        };
    }

    pub fn @"null"(d: *Decoder) DecodeError!void {
        const b = try d.byte();
        if (b != 0xf6) return error.UnexpectedType;
    }

};

// Tests
// -----

const expectEqual = std.testing.expectEqual;
const expectEqualSlices = std.testing.expectEqualSlices;

fn roundTripInt(v: i128) !void {
    var buf: std.ArrayList(u8) = .empty;
    defer buf.deinit(std.testing.allocator);
    const e = Encoder.init(&buf, std.testing.allocator);
    try e.int(v);
    var d = Decoder.init(buf.items);
    try expectEqual(v, try d.int());
    try std.testing.expect(d.atEnd());
}

test "int round trips incl. bignums" {
    const cases = [_]i128{
        0,                       1,
        23,                      24,
        255,                     256,
        65535,                   65536,
        -1,                      -24,
        -25,                     -256,
        std.math.maxInt(u64),    @as(i128, std.math.maxInt(u64)) + 1,
        std.math.maxInt(i128),   std.math.minInt(i128) + 1,
        -123456789012345678901,  123456789012345678901,
    };
    for (cases) |v| try roundTripInt(v);
}

test "canonical encodings" {
    var buf: std.ArrayList(u8) = .empty;
    defer buf.deinit(std.testing.allocator);
    const e = Encoder.init(&buf, std.testing.allocator);
    // RFC 8949 examples:
    try e.uint(0);
    try e.uint(23);
    try e.uint(24);
    try e.uint(1000);
    try expectEqualSlices(u8, &.{ 0x00, 0x17, 0x18, 0x18, 0x19, 0x03, 0xe8 }, buf.items);
}

test "strings, arrays, null, bool" {
    var buf: std.ArrayList(u8) = .empty;
    defer buf.deinit(std.testing.allocator);
    const e = Encoder.init(&buf, std.testing.allocator);
    try e.array(4);
    try e.textString("hi");
    try e.byteString(&.{ 1, 2, 3 });
    try e.boolean(true);
    try e.@"null"();

    var d = Decoder.init(buf.items);
    try expectEqual(4, try d.arrayLen());
    try expectEqualSlices(u8, "hi", try d.textString());
    try expectEqualSlices(u8, &.{ 1, 2, 3 }, try d.byteString());
    try expectEqual(true, try d.boolean());
    try d.@"null"();
    try std.testing.expect(d.atEnd());
}

