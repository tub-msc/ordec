// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Geometric primitives mirroring ordec.core.geoprim: 2D vectors, rectangles,
//! the dihedral group D4 and the TD4 transform group (translation + D4).
//!
//! Two coordinate flavors exist, as in Python: rational (Vec2R/Rect4R/TD4R,
//! used by Symbol/Schematic) and integer (Vec2I/Rect4I/TD4I, used by Layout).
//! Rational arithmetic is overflow-checked (errorable); integer arithmetic
//! uses plain operators (safety-checked in Debug/ReleaseSafe builds).

const std = @import("std");
pub const R = @import("rational.zig").R;

/// Dihedral group D4: X/Y mirroring and 90-degree rotations.
/// The enum integer values (0..7, declaration order) are part of the
/// serialization format -- do not reorder.
pub const D4 = enum(u3) {
    r0 = 0,
    r90 = 1,
    r180 = 2,
    r270 = 3,
    mx = 4,
    my = 5,
    mx90 = 6,
    my90 = 7,

    const Parts = struct { flipxy: bool, negx: bool, negy: bool };

    fn parts(self: D4) Parts {
        return switch (self) {
            .r0 => .{ .flipxy = false, .negx = false, .negy = false },
            .r90 => .{ .flipxy = true, .negx = true, .negy = false },
            .r180 => .{ .flipxy = false, .negx = true, .negy = true },
            .r270 => .{ .flipxy = true, .negx = false, .negy = true },
            .mx => .{ .flipxy = false, .negx = false, .negy = true },
            .my => .{ .flipxy = false, .negx = true, .negy = false },
            .mx90 => .{ .flipxy = true, .negx = false, .negy = false },
            .my90 => .{ .flipxy = true, .negx = true, .negy = true },
        };
    }

    fn fromParts(p: Parts) D4 {
        inline for (comptime std.enums.values(D4)) |d| {
            const dp = comptime d.parts();
            if (dp.flipxy == p.flipxy and dp.negx == p.negx and dp.negy == p.negy)
                return d;
        }
        unreachable;
    }

    pub fn flipxy(self: D4) bool {
        return self.parts().flipxy;
    }

    pub fn negx(self: D4) bool {
        return self.parts().negx;
    }

    pub fn negy(self: D4) bool {
        return self.parts().negy;
    }

    /// Group composition (a then applied after b), as D4.__mul__ in Python.
    pub fn mul(a: D4, b: D4) D4 {
        const ap = a.parts();
        const bp = b.parts();
        const onegx = if (ap.flipxy) bp.negy else bp.negx;
        const onegy = if (ap.flipxy) bp.negx else bp.negy;
        return fromParts(.{
            .flipxy = ap.flipxy != bp.flipxy,
            .negx = ap.negx != onegx,
            .negy = ap.negy != onegy,
        });
    }

    /// Inverse element: x.inv().mul(x) == .r0.
    pub fn inv(self: D4) D4 {
        return switch (self) {
            .r90 => .r270,
            .r270 => .r90,
            else => self,
        };
    }

    /// Determinant: 1 if handedness is preserved, -1 if flipped.
    pub fn det(self: D4) i2 {
        const p = self.parts();
        return if ((p.flipxy != p.negx) != p.negy) -1 else 1;
    }

    /// Flip handedness, preserving the vertex (0, 1).
    pub fn flip(self: D4) D4 {
        const p = self.parts();
        if (p.flipxy) {
            return fromParts(.{ .flipxy = p.flipxy, .negx = p.negx, .negy = !p.negy });
        } else {
            return fromParts(.{ .flipxy = p.flipxy, .negx = !p.negx, .negy = p.negy });
        }
    }

    /// Return element with non-flipped handedness (det=1), preserving (0, 1).
    pub fn unflip(self: D4) D4 {
        return if (self.det() < 0) self.flip() else self;
    }

    pub fn lefdef(self: D4) []const u8 {
        return switch (self) {
            .r0 => "N",
            .r90 => "W",
            .r180 => "S",
            .r270 => "E",
            .mx => "FN",
            .my => "FS",
            .mx90 => "FW",
            .my90 => "FE",
        };
    }

    // Compass aliases (D4.North etc. in Python):
    pub const north: D4 = .r0;
    pub const east: D4 = .r270;
    pub const south: D4 = .r180;
    pub const west: D4 = .r90;
    pub const flipped_north: D4 = .mx;
    pub const flipped_south: D4 = .my;
    pub const flipped_west: D4 = .mx90;
    pub const flipped_east: D4 = .my90;
};

pub const Vec2R = struct {
    x: R,
    y: R,

    pub const zero: Vec2R = .{ .x = R.zero, .y = R.zero };

    pub fn xy(x: anytype, y: anytype) Vec2R {
        return .{ .x = coerceR(x), .y = coerceR(y) };
    }

    pub fn add(a: Vec2R, b: Vec2R) R.Error!Vec2R {
        return .{ .x = try a.x.add(b.x), .y = try a.y.add(b.y) };
    }

    pub fn sub(a: Vec2R, b: Vec2R) R.Error!Vec2R {
        return .{ .x = try a.x.sub(b.x), .y = try a.y.sub(b.y) };
    }

    pub fn neg(a: Vec2R) Vec2R {
        return .{ .x = a.x.neg(), .y = a.y.neg() };
    }

    pub fn scale(a: Vec2R, s: R) R.Error!Vec2R {
        return .{ .x = try a.x.mul(s), .y = try a.y.mul(s) };
    }

    pub fn eql(a: Vec2R, b: Vec2R) bool {
        return a.x.eql(b.x) and a.y.eql(b.y);
    }

    /// Returns translation by vector.
    pub fn transl(self: Vec2R) TD4R {
        return .{ .transl = self, .d4 = .r0 };
    }

    pub fn format(self: Vec2R, w: *std.Io.Writer) std.Io.Writer.Error!void {
        try w.print("Vec2R({f}, {f})", .{ self.x, self.y });
    }
};

/// Accept integer literals and R values interchangeably where an R is needed.
fn coerceR(v: anytype) R {
    return switch (@typeInfo(@TypeOf(v))) {
        .int, .comptime_int => R.fromInt(v),
        else => v,
    };
}

pub const Vec2I = struct {
    x: i32,
    y: i32,

    pub const zero: Vec2I = .{ .x = 0, .y = 0 };

    pub fn xy(x: i32, y: i32) Vec2I {
        return .{ .x = x, .y = y };
    }

    pub fn add(a: Vec2I, b: Vec2I) Vec2I {
        return .{ .x = a.x + b.x, .y = a.y + b.y };
    }

    pub fn sub(a: Vec2I, b: Vec2I) Vec2I {
        return .{ .x = a.x - b.x, .y = a.y - b.y };
    }

    pub fn neg(a: Vec2I) Vec2I {
        return .{ .x = -a.x, .y = -a.y };
    }

    pub fn scale(a: Vec2I, s: i32) Vec2I {
        return .{ .x = a.x * s, .y = a.y * s };
    }

    pub fn eql(a: Vec2I, b: Vec2I) bool {
        return a.x == b.x and a.y == b.y;
    }

    /// Returns translation by vector.
    pub fn transl(self: Vec2I) TD4I {
        return .{ .transl = self, .d4 = .r0 };
    }

    pub fn format(self: Vec2I, w: *std.Io.Writer) std.Io.Writer.Error!void {
        try w.print("Vec2I({d}, {d})", .{ self.x, self.y });
    }
};

pub const GeomError = error{InvalidRect};

pub const Rect4R = struct {
    lx: R,
    ly: R,
    ux: R,
    uy: R,

    pub fn init(lx: anytype, ly: anytype, ux: anytype, uy: anytype) GeomError!Rect4R {
        const r: Rect4R = .{ .lx = coerceR(lx), .ly = coerceR(ly), .ux = coerceR(ux), .uy = coerceR(uy) };
        if (r.lx.gt(r.ux) or r.ly.gt(r.uy)) return error.InvalidRect;
        return r;
    }

    pub fn width(self: Rect4R) R {
        return self.ux.sub(self.lx) catch unreachable; // lx <= ux by invariant
    }

    pub fn height(self: Rect4R) R {
        return self.uy.sub(self.ly) catch unreachable;
    }

    pub fn southwest(self: Rect4R) Vec2R {
        return .{ .x = self.lx, .y = self.ly };
    }

    pub fn northeast(self: Rect4R) Vec2R {
        return .{ .x = self.ux, .y = self.uy };
    }

    pub fn contains(self: Rect4R, v: Vec2R) bool {
        return v.x.ge(self.lx) and v.x.le(self.ux) and v.y.ge(self.ly) and v.y.le(self.uy);
    }

    /// Smallest rectangle containing both self and the vertex.
    pub fn extend(self: Rect4R, v: Vec2R) Rect4R {
        return .{
            .lx = R.min(self.lx, v.x),
            .ly = R.min(self.ly, v.y),
            .ux = R.max(self.ux, v.x),
            .uy = R.max(self.uy, v.y),
        };
    }

    pub fn eql(a: Rect4R, b: Rect4R) bool {
        return a.lx.eql(b.lx) and a.ly.eql(b.ly) and a.ux.eql(b.ux) and a.uy.eql(b.uy);
    }
};

pub const Rect4I = struct {
    lx: i32,
    ly: i32,
    ux: i32,
    uy: i32,

    pub fn init(lx: i32, ly: i32, ux: i32, uy: i32) GeomError!Rect4I {
        if (lx > ux or ly > uy) return error.InvalidRect;
        return .{ .lx = lx, .ly = ly, .ux = ux, .uy = uy };
    }

    pub fn width(self: Rect4I) i32 {
        return self.ux - self.lx;
    }

    pub fn height(self: Rect4I) i32 {
        return self.uy - self.ly;
    }

    pub fn southwest(self: Rect4I) Vec2I {
        return .{ .x = self.lx, .y = self.ly };
    }

    pub fn northeast(self: Rect4I) Vec2I {
        return .{ .x = self.ux, .y = self.uy };
    }

    pub fn contains(self: Rect4I, v: Vec2I) bool {
        return v.x >= self.lx and v.x <= self.ux and v.y >= self.ly and v.y <= self.uy;
    }

    pub fn containsRect(self: Rect4I, other: Rect4I) bool {
        return other.lx >= self.lx and other.ux <= self.ux and other.ly >= self.ly and other.uy <= self.uy;
    }

    pub fn overlaps(a: Rect4I, b: Rect4I) bool {
        return a.lx < b.ux and b.lx < a.ux and a.ly < b.uy and b.ly < a.uy;
    }

    /// Smallest rectangle containing both self and the vertex.
    pub fn extend(self: Rect4I, v: Vec2I) Rect4I {
        return .{
            .lx = @min(self.lx, v.x),
            .ly = @min(self.ly, v.y),
            .ux = @max(self.ux, v.x),
            .uy = @max(self.uy, v.y),
        };
    }

    pub fn extendRect(self: Rect4I, other: Rect4I) Rect4I {
        return self.extend(other.southwest()).extend(other.northeast());
    }

    pub fn eql(a: Rect4I, b: Rect4I) bool {
        return a.lx == b.lx and a.ly == b.ly and a.ux == b.ux and a.uy == b.uy;
    }

    pub fn format(self: Rect4I, w: *std.Io.Writer) std.Io.Writer.Error!void {
        try w.print("Rect4I({d}, {d}, {d}, {d})", .{ self.lx, self.ly, self.ux, self.uy });
    }
};

/// Transform group: 2D translation combined with a D4 element.
/// Mirrors TD4R in Python (TD4.__mul__ with Vec2R / Rect4R / TD4R operands).
pub const TD4R = struct {
    transl: Vec2R = Vec2R.zero,
    d4: D4 = .r0,

    pub const identity: TD4R = .{};

    pub fn applyVec(t: TD4R, v: Vec2R) R.Error!Vec2R {
        const p = t.d4.parts();
        var x = if (p.flipxy) v.y else v.x;
        var y = if (p.flipxy) v.x else v.y;
        if (p.negx) x = x.neg();
        if (p.negy) y = y.neg();
        return .{ .x = try t.transl.x.add(x), .y = try t.transl.y.add(y) };
    }

    pub fn applyRect(t: TD4R, r: Rect4R) R.Error!Rect4R {
        const tl = try t.applyVec(.{ .x = r.lx, .y = r.ly });
        const tu = try t.applyVec(.{ .x = r.ux, .y = r.uy });
        var east = tl.x;
        var south = tl.y;
        var west = tu.x;
        var north = tu.y;
        const p = t.d4.parts();
        if (p.negx) std.mem.swap(R, &east, &west);
        if (p.negy) std.mem.swap(R, &north, &south);
        return .{ .lx = east, .ly = south, .ux = west, .uy = north };
    }

    /// a.compose(b) corresponds to a * b in Python (apply b first, then a).
    pub fn compose(a: TD4R, b: TD4R) R.Error!TD4R {
        return .{ .transl = try a.applyVec(b.transl), .d4 = a.d4.mul(b.d4) };
    }

    pub fn rotate(a: TD4R, d4: D4) TD4R {
        return .{ .transl = a.transl, .d4 = a.d4.mul(d4) };
    }

    pub fn det(self: TD4R) i2 {
        return self.d4.det();
    }
};

/// Integer version of TD4R. Plain integer arithmetic (Debug-build checked).
pub const TD4I = struct {
    transl: Vec2I = Vec2I.zero,
    d4: D4 = .r0,

    pub const identity: TD4I = .{};

    pub fn applyVec(t: TD4I, v: Vec2I) Vec2I {
        const p = t.d4.parts();
        var x = if (p.flipxy) v.y else v.x;
        var y = if (p.flipxy) v.x else v.y;
        if (p.negx) x = -x;
        if (p.negy) y = -y;
        return .{ .x = t.transl.x + x, .y = t.transl.y + y };
    }

    pub fn applyRect(t: TD4I, r: Rect4I) Rect4I {
        const tl = t.applyVec(.{ .x = r.lx, .y = r.ly });
        const tu = t.applyVec(.{ .x = r.ux, .y = r.uy });
        var east = tl.x;
        var south = tl.y;
        var west = tu.x;
        var north = tu.y;
        const p = t.d4.parts();
        if (p.negx) std.mem.swap(i32, &east, &west);
        if (p.negy) std.mem.swap(i32, &north, &south);
        return .{ .lx = east, .ly = south, .ux = west, .uy = north };
    }

    /// a.compose(b) corresponds to a * b in Python (apply b first, then a).
    pub fn compose(a: TD4I, b: TD4I) TD4I {
        return .{ .transl = a.applyVec(b.transl), .d4 = a.d4.mul(b.d4) };
    }

    pub fn rotate(a: TD4I, d4: D4) TD4I {
        return .{ .transl = a.transl, .d4 = a.d4.mul(d4) };
    }

    pub fn det(self: TD4I) i2 {
        return self.d4.det();
    }
};

// Tests
// -----

const expect = std.testing.expect;
const expectEqual = std.testing.expectEqual;

test "D4 group laws" {
    const all = std.enums.values(D4);
    // Identity:
    for (all) |d| {
        try expectEqual(d, D4.r0.mul(d));
        try expectEqual(d, d.mul(.r0));
    }
    // Inverse:
    for (all) |d| {
        try expectEqual(D4.r0, d.inv().mul(d));
        try expectEqual(D4.r0, d.mul(d.inv()));
    }
    // Closure + associativity (spot check over the whole table):
    for (all) |a| for (all) |b| for (all) |c| {
        try expectEqual(a.mul(b).mul(c), a.mul(b.mul(c)));
    };
    // Known products:
    try expectEqual(D4.r180, D4.r90.mul(.r90));
    try expectEqual(D4.r0, D4.r90.mul(.r270));
    try expectEqual(D4.r0, D4.mx.mul(.mx));
}

test "D4 det and flip" {
    try expectEqual(@as(i2, 1), D4.r0.det());
    try expectEqual(@as(i2, 1), D4.r90.det());
    try expectEqual(@as(i2, -1), D4.mx.det());
    try expectEqual(@as(i2, -1), D4.my90.det());
    for (std.enums.values(D4)) |d| {
        try expectEqual(@as(i2, -1) * d.det(), d.flip().det());
        try expectEqual(@as(i2, 1), d.unflip().det());
    }
}

test "TD4I applyVec" {
    // Pure rotation by 90 degrees: (1, 0) -> (0, 1)
    const rot90: TD4I = .{ .d4 = .r90 };
    try expect(rot90.applyVec(Vec2I.xy(1, 0)).eql(Vec2I.xy(0, 1)));
    try expect(rot90.applyVec(Vec2I.xy(0, 1)).eql(Vec2I.xy(-1, 0)));
    // MX flips y:
    const mx: TD4I = .{ .d4 = .mx };
    try expect(mx.applyVec(Vec2I.xy(2, 3)).eql(Vec2I.xy(2, -3)));
    // Translation:
    const tr = Vec2I.xy(10, 20).transl();
    try expect(tr.applyVec(Vec2I.xy(1, 2)).eql(Vec2I.xy(11, 22)));
}

test "TD4I applyRect" {
    const r = try Rect4I.init(1, 2, 3, 5);
    const mx: TD4I = .{ .d4 = .mx };
    const rm = mx.applyRect(r);
    try expect(rm.eql(try Rect4I.init(1, -5, 3, -2)));
    const rot90: TD4I = .{ .d4 = .r90 };
    const rr = rot90.applyRect(r);
    try expect(rr.eql(try Rect4I.init(-5, 1, -2, 3)));
    // Compose translation and rotation:
    const t = TD4I{ .transl = Vec2I.xy(10, 0), .d4 = .r180 };
    const rt = t.applyRect(r);
    try expect(rt.eql(try Rect4I.init(7, -5, 9, -2)));
}

test "TD4 compose matches sequential application" {
    const a = TD4I{ .transl = Vec2I.xy(3, -1), .d4 = .r90 };
    const b = TD4I{ .transl = Vec2I.xy(-2, 5), .d4 = .mx };
    const v = Vec2I.xy(7, 11);
    const ab = a.compose(b);
    try expect(ab.applyVec(v).eql(a.applyVec(b.applyVec(v))));
    // D4 acts on vectors consistently with TD4:
    for (std.enums.values(D4)) |d| {
        const t = TD4I{ .d4 = d };
        const u = TD4I{ .transl = Vec2I.xy(1, 2) };
        const both = t.compose(u);
        try expect(both.applyVec(v).eql(t.applyVec(u.applyVec(v))));
    }
}

test "TD4R rational transform" {
    const half = try R.init(1, 2);
    const t = TD4R{ .transl = .{ .x = half, .y = R.zero }, .d4 = .r90 };
    const v = try t.applyVec(Vec2R.xy(1, 0));
    try expect(v.eql(.{ .x = half, .y = R.one }));
}

test "rect invariants" {
    try std.testing.expectError(error.InvalidRect, Rect4I.init(2, 0, 1, 5));
    try std.testing.expectError(error.InvalidRect, Rect4R.init(0, 2, 5, 1));
    const r = try Rect4I.init(0, 0, 10, 5);
    try expectEqual(@as(i32, 10), r.width());
    try expectEqual(@as(i32, 5), r.height());
    try expect(r.contains(Vec2I.xy(10, 5)));
    try expect(!r.contains(Vec2I.xy(11, 5)));
    try expect(r.extend(Vec2I.xy(-1, 7)).eql(try Rect4I.init(-1, 0, 10, 7)));
    try expect(r.overlaps(try Rect4I.init(9, 4, 12, 8)));
    try expect(!r.overlaps(try Rect4I.init(10, 0, 12, 5))); // touching, not overlapping
}
