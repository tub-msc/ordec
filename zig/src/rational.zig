// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Exact rational numbers for circuit design, mirroring ordec.core.rational.R.
//!
//! Representation is a two-tier union:
//!
//! - `small`: i64 numerator / i64 denominator, always normalized
//!   (gcd-reduced, denominator > 0, |numerator| <= maxInt(i64), zero is 0/1).
//!   Arithmetic runs allocation-free with i128 intermediates.
//! - `big`: arbitrary-precision fallback as sign + two big-endian magnitudes
//!   in one byte slice (<= 255 bytes per magnitude, i.e. ~2040 bits).
//!   Storage-wise a big R behaves exactly like a Str attribute: duped into
//!   the subgraph arena on insert, borrowed on read, never freed
//!   individually. A big R produced by arithmetic borrows from the allocator
//!   passed to the *Alloc variant (use an arena).
//!
//! Canonical form: a value representable as `small` is ALWAYS `small`
//! (arithmetic, decoding and fromMags demote automatically), so structural
//! equality and hashing of node attributes remain valid.
//!
//! The plain operators (add/sub/mul/div/scaleInt/init/parse) are
//! allocation-free; they require small operands and a small result and
//! report anything beyond as error.Overflow. The *Alloc variants accept and
//! produce big values up to the 255-byte magnitude cap. order/eql/neg/abs/
//! min/max/format/toFloat handle big values without an allocator (the cap
//! bounds all intermediates, so stack buffers suffice).

const std = @import("std");
const Allocator = std.mem.Allocator;
const bigint = std.math.big.int;
const Limb = std.math.big.Limb;

/// Maximum size of a big numerator or denominator magnitude in bytes.
pub const max_mag_bytes = 255;
const mag_limbs = bigint.calcTwosCompLimbCount(max_mag_bytes * 8);
const prod_limbs = 2 * mag_limbs + 1; // product of two magnitudes
const sum_limbs = prod_limbs + 1; // sum of two products

pub const R = union(enum) {
    small: Small,
    big: Big,

    pub const Small = struct { num: i64, den: i64 };

    pub const Big = struct {
        negative: bool,
        /// mag[0] = numerator magnitude length N; mag[1..1+N] = numerator
        /// magnitude; mag[1+N..] = denominator magnitude. Both big-endian,
        /// minimal-length (no leading zero), <= 255 bytes each.
        mag: []const u8,

        pub fn numMag(self: Big) []const u8 {
            return self.mag[1 .. 1 + @as(usize, self.mag[0])];
        }

        pub fn denMag(self: Big) []const u8 {
            return self.mag[1 + @as(usize, self.mag[0]) ..];
        }
    };

    pub const zero: R = .{ .small = .{ .num = 0, .den = 1 } };
    pub const one: R = .{ .small = .{ .num = 1, .den = 1 } };

    pub const Error = error{ Overflow, DivisionByZero };
    pub const AllocError = Error || Allocator.Error;
    pub const ParseError = Error || error{InvalidRational};

    // Small-path normalization (i128 intermediates)
    // ---------------------------------------------

    const Norm = struct { num: i128, den: i128 };

    /// gcd-reduce, den > 0. Reduction only shrinks, so i128 inputs always
    /// yield i128 results; the only failure is a zero denominator.
    fn normalize128(num_in: i128, den_in: i128) error{DivisionByZero}!Norm {
        if (den_in == 0) return error.DivisionByZero;
        var n = num_in;
        var d = den_in;
        if (d < 0) {
            n = -n;
            d = -d;
        }
        if (n == 0) return .{ .num = 0, .den = 1 };
        const g: i128 = @intCast(std.math.gcd(@abs(n), @abs(d)));
        return .{ .num = @divExact(n, g), .den = @divExact(d, g) };
    }

    /// minInt(i64) is excluded from the small range so neg() stays closed.
    fn toSmall(n: Norm) ?R {
        if (n.num < -std.math.maxInt(i64) or n.num > std.math.maxInt(i64)) return null;
        if (n.den > std.math.maxInt(i64)) return null;
        return .{ .small = .{ .num = @intCast(n.num), .den = @intCast(n.den) } };
    }

    pub fn init(num: i64, den: i64) Error!R {
        const n = try normalize128(num, den);
        return toSmall(n) orelse error.Overflow;
    }

    pub fn fromInt(i: i64) R {
        return .{ .small = .{ .num = i, .den = 1 } };
    }

    /// Copy (a big value's bytes move into `alloc`).
    pub fn dupe(a: R, alloc: Allocator) Allocator.Error!R {
        return switch (a) {
            .small => a,
            .big => |b| .{ .big = .{ .negative = b.negative, .mag = try alloc.dupe(u8, b.mag) } },
        };
    }

    // Arithmetic
    // ----------

    const Op = enum { add, sub, mul, div };

    fn smallOp(a: Small, b: Small, comptime op: Op) error{DivisionByZero}!Norm {
        const an: i128 = a.num;
        const ad: i128 = a.den;
        const bn: i128 = b.num;
        const bd: i128 = b.den;
        return switch (op) {
            .add => normalize128(an * bd + bn * ad, ad * bd),
            .sub => normalize128(an * bd - bn * ad, ad * bd),
            .mul => normalize128(an * bn, ad * bd),
            .div => normalize128(an * bd, ad * bn),
        };
    }

    fn arith(a: R, b: R, comptime op: Op) Error!R {
        if (a != .small or b != .small) return error.Overflow;
        const n = try smallOp(a.small, b.small, op);
        return toSmall(n) orelse error.Overflow;
    }

    pub fn add(a: R, b: R) Error!R {
        return arith(a, b, .add);
    }

    pub fn sub(a: R, b: R) Error!R {
        return arith(a, b, .sub);
    }

    pub fn mul(a: R, b: R) Error!R {
        return arith(a, b, .mul);
    }

    pub fn div(a: R, b: R) Error!R {
        return arith(a, b, .div);
    }

    pub fn scaleInt(a: R, s: i64) Error!R {
        return a.mul(fromInt(s));
    }

    /// Full-range variants: big operands and big results are supported up to
    /// the magnitude cap. A big result's bytes are allocated from `alloc`
    /// and live as long as that allocator's memory (use an arena).
    pub fn addAlloc(alloc: Allocator, a: R, b: R) AllocError!R {
        return arithAlloc(alloc, a, b, .add);
    }

    pub fn subAlloc(alloc: Allocator, a: R, b: R) AllocError!R {
        return arithAlloc(alloc, a, b, .sub);
    }

    pub fn mulAlloc(alloc: Allocator, a: R, b: R) AllocError!R {
        return arithAlloc(alloc, a, b, .mul);
    }

    pub fn divAlloc(alloc: Allocator, a: R, b: R) AllocError!R {
        return arithAlloc(alloc, a, b, .div);
    }

    fn arithAlloc(alloc: Allocator, a: R, b: R, comptime op: Op) AllocError!R {
        if (a == .small and b == .small) {
            const n = try smallOp(a.small, b.small, op);
            if (toSmall(n)) |r| return r;
            var nbuf: [4]Limb = undefined;
            var dbuf: [4]Limb = undefined;
            return materialize(alloc, constFromI128(&nbuf, n.num), constFromI128(&dbuf, n.den));
        }

        var bufs: [4][8]u8 = undefined;
        const pa = parts(a, &bufs[0], &bufs[1]);
        const pb = parts(b, &bufs[2], &bufs[3]);

        var na_l: [mag_limbs + 1]Limb = undefined;
        var da_l: [mag_limbs + 1]Limb = undefined;
        var nb_l: [mag_limbs + 1]Limb = undefined;
        var db_l: [mag_limbs + 1]Limb = undefined;
        const na = loadMag(&na_l, pa.num, pa.negative);
        const da = loadMag(&da_l, pa.den, false);
        const nb = loadMag(&nb_l, pb.num, pb.negative);
        const db = loadMag(&db_l, pb.den, false);

        var num_l: [sum_limbs]Limb = undefined;
        var den_l: [prod_limbs]Limb = undefined;
        var num = bigint.Mutable{ .limbs = &num_l, .len = 1, .positive = true };
        var den = bigint.Mutable{ .limbs = &den_l, .len = 1, .positive = true };
        switch (op) {
            .add, .sub => {
                var t1_l: [prod_limbs]Limb = undefined;
                var t2_l: [prod_limbs]Limb = undefined;
                var t1 = bigint.Mutable{ .limbs = &t1_l, .len = 1, .positive = true };
                var t2 = bigint.Mutable{ .limbs = &t2_l, .len = 1, .positive = true };
                t1.mulNoAlias(na, db, null);
                t2.mulNoAlias(nb, da, null);
                const t2c = if (op == .sub) t2.toConst().negate() else t2.toConst();
                num.add(t1.toConst(), t2c);
                den.mulNoAlias(da, db, null);
            },
            .mul => {
                num.mulNoAlias(na, nb, null);
                den.mulNoAlias(da, db, null);
            },
            .div => {
                num.mulNoAlias(na, db, null);
                den.mulNoAlias(da, nb, null);
            },
        }
        return reduceAndMaterialize(alloc, num.toConst(), den.toConst());
    }

    /// gcd-reduce a num/den pair of bounded big integers and produce the
    /// canonical R (small whenever it fits).
    fn reduceAndMaterialize(alloc: Allocator, num_in: bigint.Const, den_in: bigint.Const) AllocError!R {
        if (den_in.eqlZero()) return error.DivisionByZero;
        if (num_in.eqlZero()) return zero;
        // Denominator sign moves into the numerator:
        const flip = !den_in.positive;
        const num_c = if (flip) num_in.negate() else num_in;
        const den_c = den_in.abs();

        var g_l: [prod_limbs]Limb = undefined;
        var g = bigint.Mutable{ .limbs = &g_l, .len = 1, .positive = true };
        var scratch = std.array_list.Managed(Limb).init(alloc);
        defer scratch.deinit();
        try g.gcd(num_c.abs(), den_c, &scratch);

        if (g.len == 1 and g.limbs[0] == 1) {
            return materialize(alloc, num_c, den_c);
        }
        var qn_l: [sum_limbs + 1]Limb = undefined;
        var qd_l: [sum_limbs + 1]Limb = undefined;
        var rem_l: [sum_limbs + 1]Limb = undefined;
        var div_buf: [2 * sum_limbs + 8]Limb = undefined;
        var qn = bigint.Mutable{ .limbs = &qn_l, .len = 1, .positive = true };
        var qd = bigint.Mutable{ .limbs = &qd_l, .len = 1, .positive = true };
        var rem = bigint.Mutable{ .limbs = &rem_l, .len = 1, .positive = true };
        qn.divTrunc(&rem, num_c, g.toConst(), &div_buf);
        qd.divTrunc(&rem, den_c, g.toConst(), &div_buf);
        return materialize(alloc, qn.toConst(), qd.toConst());
    }

    /// num/den are gcd-reduced, den > 0, num != 0.
    fn materialize(alloc: Allocator, num: bigint.Const, den: bigint.Const) AllocError!R {
        small: {
            const n = num.toInt(i64) catch break :small;
            const d = den.toInt(i64) catch break :small;
            if (n == std.math.minInt(i64)) break :small;
            return .{ .small = .{ .num = n, .den = d } };
        }
        const nb = (num.bitCountAbs() + 7) / 8;
        const db = (den.bitCountAbs() + 7) / 8;
        if (nb > max_mag_bytes or db > max_mag_bytes) return error.Overflow;
        const blob = try alloc.alloc(u8, 1 + nb + db);
        blob[0] = @intCast(nb);
        num.abs().writeTwosComplement(blob[1 .. 1 + nb], .big);
        den.abs().writeTwosComplement(blob[1 + nb ..], .big);
        return .{ .big = .{ .negative = !num.positive, .mag = blob } };
    }

    /// Build the canonical R from sign + raw magnitudes (used by the wire
    /// decoder). Reduces and demotes, so even non-normalized input yields a
    /// canonical value.
    pub fn fromMags(alloc: Allocator, negative: bool, num_in: []const u8, den_in: []const u8) AllocError!R {
        const num_mag = trimZeros(num_in);
        const den_mag = trimZeros(den_in);
        if (den_mag.len == 0) return error.DivisionByZero;
        if (num_mag.len == 0) return zero;
        if (num_mag.len > max_mag_bytes or den_mag.len > max_mag_bytes) return error.Overflow;
        var n_l: [mag_limbs + 1]Limb = undefined;
        var d_l: [mag_limbs + 1]Limb = undefined;
        return reduceAndMaterialize(alloc, loadMag(&n_l, num_mag, negative), loadMag(&d_l, den_mag, false));
    }

    // Sign / comparison / conversion (allocation-free, big-capable)
    // -------------------------------------------------------------

    pub fn neg(a: R) R {
        return switch (a) {
            .small => |s| .{ .small = .{ .num = -s.num, .den = s.den } },
            .big => |b| .{ .big = .{ .negative = !b.negative, .mag = b.mag } },
        };
    }

    pub fn abs(a: R) R {
        return switch (a) {
            .small => |s| .{ .small = .{ .num = if (s.num < 0) -s.num else s.num, .den = s.den } },
            .big => |b| .{ .big = .{ .negative = false, .mag = b.mag } },
        };
    }

    pub fn isZero(a: R) bool {
        return a == .small and a.small.num == 0;
    }

    /// Total order; never fails (big comparisons use bounded stack buffers).
    pub fn order(a: R, b: R) std.math.Order {
        if (a == .small and b == .small) {
            const lhs = @as(i128, a.small.num) * @as(i128, b.small.den);
            const rhs = @as(i128, b.small.num) * @as(i128, a.small.den);
            return std.math.order(lhs, rhs);
        }
        var bufs: [4][8]u8 = undefined;
        const pa = parts(a, &bufs[0], &bufs[1]);
        const pb = parts(b, &bufs[2], &bufs[3]);
        var na_l: [mag_limbs + 1]Limb = undefined;
        var da_l: [mag_limbs + 1]Limb = undefined;
        var nb_l: [mag_limbs + 1]Limb = undefined;
        var db_l: [mag_limbs + 1]Limb = undefined;
        var lhs_l: [prod_limbs]Limb = undefined;
        var rhs_l: [prod_limbs]Limb = undefined;
        var lhs = bigint.Mutable{ .limbs = &lhs_l, .len = 1, .positive = true };
        var rhs = bigint.Mutable{ .limbs = &rhs_l, .len = 1, .positive = true };
        lhs.mulNoAlias(loadMag(&na_l, pa.num, pa.negative), loadMag(&db_l, pb.den, false), null);
        rhs.mulNoAlias(loadMag(&nb_l, pb.num, pb.negative), loadMag(&da_l, pa.den, false), null);
        return lhs.toConst().order(rhs.toConst());
    }

    pub fn eql(a: R, b: R) bool {
        // Canonical representation makes structural equality sufficient.
        if (std.meta.activeTag(a) != std.meta.activeTag(b)) return false;
        return switch (a) {
            .small => |s| s.num == b.small.num and s.den == b.small.den,
            .big => |x| x.negative == b.big.negative and std.mem.eql(u8, x.mag, b.big.mag),
        };
    }

    pub fn lt(a: R, b: R) bool {
        return a.order(b) == .lt;
    }

    pub fn le(a: R, b: R) bool {
        return a.order(b) != .gt;
    }

    pub fn gt(a: R, b: R) bool {
        return a.order(b) == .gt;
    }

    pub fn ge(a: R, b: R) bool {
        return a.order(b) != .lt;
    }

    pub fn toFloat(a: R) f64 {
        switch (a) {
            .small => |s| return @as(f64, @floatFromInt(s.num)) / @as(f64, @floatFromInt(s.den)),
            .big => |b| {
                const f = magToFloat(b.numMag()) / magToFloat(b.denMag());
                return if (b.negative) -f else f;
            },
        }
    }

    pub fn min(a: R, b: R) R {
        return if (a.le(b)) a else b;
    }

    pub fn max(a: R, b: R) R {
        return if (a.ge(b)) a else b;
    }

    // Parsing and formatting
    // ----------------------

    const si_suffixes = [_]struct { exp: i32, c: []const u8 }{
        .{ .exp = -18, .c = "a" }, .{ .exp = -15, .c = "f" }, .{ .exp = -12, .c = "p" },
        .{ .exp = -9, .c = "n" },  .{ .exp = -6, .c = "u" },  .{ .exp = -3, .c = "m" },
        .{ .exp = 0, .c = "" },    .{ .exp = 3, .c = "k" },   .{ .exp = 6, .c = "M" },
        .{ .exp = 9, .c = "G" },   .{ .exp = 12, .c = "T" },
    };

    fn siSuffixExp(s: []const u8) ?i32 {
        if (std.mem.eql(u8, s, "μ")) return -6;
        for (si_suffixes) |entry| {
            if (entry.c.len > 0 and std.mem.eql(u8, s, entry.c)) return entry.exp;
        }
        return null;
    }

    fn pow10(e: u32) ?i128 {
        if (e > 38) return null;
        var r: i128 = 1;
        var i: u32 = 0;
        while (i < e) : (i += 1) r *= 10;
        return r;
    }

    fn normalizeParse(num: i256, den: i256) Error!R {
        if (den == 0) return error.DivisionByZero;
        var n = num;
        var d = den;
        if (d < 0) {
            n = -n;
            d = -d;
        }
        if (n == 0) return zero;
        const g: i256 = @intCast(std.math.gcd(@abs(n), @abs(d)));
        const norm = Norm{
            .num = std.math.cast(i128, @divExact(n, g)) orelse return error.Overflow,
            .den = std.math.cast(i128, @divExact(d, g)) orelse return error.Overflow,
        };
        return toSmall(norm) orelse error.Overflow;
    }

    /// Parse from string. Supported forms (as in Python's Rational):
    /// "2", "-2.5", "1e-3", "100n", "12.345G", "f'15/19".
    pub fn parse(s_in: []const u8) ParseError!R {
        var s = s_in;
        if (std.mem.startsWith(u8, s, "f'")) {
            const body = s[2..];
            const slash = std.mem.indexOfScalar(u8, body, '/') orelse return error.InvalidRational;
            const n = std.fmt.parseInt(i128, body[0..slash], 10) catch return error.InvalidRational;
            const d = std.fmt.parseInt(i128, body[slash + 1 ..], 10) catch return error.InvalidRational;
            return normalizeParse(n, d);
        }

        // SI suffix? ("μ" is two bytes of UTF-8, check it first.)
        var exp10: i32 = 0;
        if (s.len >= 2 and siSuffixExp(s[s.len - 2 ..]) != null) {
            exp10 = siSuffixExp(s[s.len - 2 ..]).?;
            s = s[0 .. s.len - 2];
        } else if (s.len >= 1 and siSuffixExp(s[s.len - 1 ..]) != null) {
            exp10 = siSuffixExp(s[s.len - 1 ..]).?;
            s = s[0 .. s.len - 1];
        } else if (std.mem.indexOfAny(u8, s, "eE")) |epos| {
            exp10 = std.fmt.parseInt(i32, s[epos + 1 ..], 10) catch return error.InvalidRational;
            s = s[0..epos];
        }

        // Decimal mantissa with optional sign and fractional point.
        var negative = false;
        if (s.len > 0 and (s[0] == '+' or s[0] == '-')) {
            negative = s[0] == '-';
            s = s[1..];
        }
        if (s.len == 0) return error.InvalidRational;

        var mantissa: i256 = 0;
        var frac_digits: i32 = 0;
        var seen_point = false;
        var seen_digit = false;
        for (s) |c| {
            switch (c) {
                '0'...'9' => {
                    mantissa = mantissa * 10 + (c - '0');
                    if (mantissa > std.math.maxInt(i128)) return error.Overflow;
                    if (seen_point) frac_digits += 1;
                    seen_digit = true;
                },
                '.' => {
                    if (seen_point) return error.InvalidRational;
                    seen_point = true;
                },
                else => return error.InvalidRational,
            }
        }
        if (!seen_digit) return error.InvalidRational;
        if (negative) mantissa = -mantissa;

        const e = exp10 - frac_digits;
        if (e >= 0) {
            const p = pow10(@intCast(e)) orelse return error.Overflow;
            return normalizeParse(mantissa * p, 1);
        } else {
            const p = pow10(@intCast(-e)) orelse return error.Overflow;
            return normalizeParse(mantissa, p);
        }
    }

    /// Decompose into (num, exp) such that self == num * 10^exp with num not
    /// divisible by 10, or null if the denominator has prime factors other
    /// than 2 and 5 (i.e. no finite decimal representation exists).
    fn decimalFraction(s: Small) ?struct { num: i128, exp: i32 } {
        if (s.num == 0) return .{ .num = 0, .exp = 0 };
        var den: i128 = s.den;
        var num: i256 = s.num;
        var exp: i32 = 0;
        while (@rem(den, 10) == 0) {
            den = @divExact(den, 10);
            exp -= 1;
        }
        while (@rem(den, 5) == 0) {
            den = @divExact(den, 5);
            exp -= 1;
            num *= 2;
        }
        while (@rem(den, 2) == 0) {
            den = @divExact(den, 2);
            exp -= 1;
            num *= 5;
        }
        if (den != 1) return null;
        while (@rem(num, 10) == 0) {
            num = @divExact(num, 10);
            exp += 1;
        }
        const n = std.math.cast(i128, num) orelse return null;
        return .{ .num = n, .exp = exp };
    }

    /// Render like Python's Rational.__str__: decimal fraction with an SI
    /// suffix selected so the integer part is in [1, 1000), trailing "." kept
    /// for whole numbers, or "f'num/den" when no finite decimal form exists.
    /// Big values always render as "f'num/den".
    pub fn format(self: R, w: *std.Io.Writer) std.Io.Writer.Error!void {
        const s = switch (self) {
            .small => |s| s,
            .big => |b| {
                try w.writeAll("f'");
                if (b.negative) try w.writeByte('-');
                try writeDecimalMag(w, b.numMag());
                try w.writeByte('/');
                try writeDecimalMag(w, b.denMag());
                return;
            },
        };
        const df = decimalFraction(s) orelse {
            try w.print("f'{d}/{d}", .{ s.num, s.den });
            return;
        };
        if (df.num == 0) {
            try w.writeAll("0.");
            return;
        }
        var num = df.num;
        var exp = df.exp;
        if (num < 0) {
            try w.writeByte('-');
            num = -num;
        }
        var numbuf: [40]u8 = undefined;
        const digits = std.fmt.bufPrint(&numbuf, "{d}", .{num}) catch unreachable;
        const numdigits: i32 = @intCast(digits.len);

        var exp2: i32 = 0;
        while (exp + numdigits > 3) {
            exp2 += 3;
            exp -= 3;
        }
        while (exp + numdigits <= 0) {
            exp2 -= 3;
            exp += 3;
        }

        if (exp >= 0) {
            try w.writeAll(digits);
            try w.splatByteAll('0', @intCast(exp));
        } else {
            const point: usize = @intCast(numdigits + exp);
            try w.writeAll(digits[0..point]);
            try w.writeByte('.');
            try w.writeAll(digits[point..]);
        }

        var suffix: ?[]const u8 = null;
        for (si_suffixes) |entry| {
            if (entry.exp == exp2) suffix = entry.c;
        }
        if (suffix) |sfx| {
            if (sfx.len == 0 and exp >= 0) {
                try w.writeByte('.');
            } else {
                try w.writeAll(sfx);
            }
        } else {
            try w.print("e{d}", .{exp2});
        }
    }
};

// Magnitude helpers
// -----------------

fn trimZeros(mag: []const u8) []const u8 {
    var s: usize = 0;
    while (s < mag.len and mag[s] == 0) s += 1;
    return mag[s..];
}

/// Big-endian magnitude of v (empty for zero), written into buf.
fn u64Mag(buf: *[8]u8, v: u64) []const u8 {
    std.mem.writeInt(u64, buf, v, .big);
    return trimZeros(buf);
}

const Parts = struct { negative: bool, num: []const u8, den: []const u8 };

/// Uniform sign + magnitudes view of any R; small values render into the
/// caller's buffers.
fn parts(a: R, num_buf: *[8]u8, den_buf: *[8]u8) Parts {
    switch (a) {
        .small => |s| return .{
            .negative = s.num < 0,
            .num = u64Mag(num_buf, @abs(s.num)),
            .den = u64Mag(den_buf, @intCast(s.den)),
        },
        .big => |b| return .{ .negative = b.negative, .num = b.numMag(), .den = b.denMag() },
    }
}

/// Load a big-endian magnitude into caller limbs as a signed Const.
fn loadMag(limbs: []Limb, mag: []const u8, negative: bool) bigint.Const {
    var m = bigint.Mutable{ .limbs = limbs, .len = 1, .positive = true };
    if (mag.len == 0) {
        m.limbs[0] = 0;
    } else {
        m.readTwosComplement(mag, mag.len * 8, .big, .unsigned);
    }
    if (negative and !m.eqlZero()) m.positive = false;
    return m.toConst();
}

fn constFromI128(limbs: []Limb, v: i128) bigint.Const {
    var m = bigint.Mutable{ .limbs = limbs, .len = 1, .positive = true };
    m.set(v);
    return m.toConst();
}

fn magToFloat(mag: []const u8) f64 {
    var f: f64 = 0;
    for (mag) |b| f = f * 256.0 + @as(f64, @floatFromInt(b));
    return f;
}

fn writeDecimalMag(w: *std.Io.Writer, mag: []const u8) std.Io.Writer.Error!void {
    var limbs: [mag_limbs + 1]Limb = undefined;
    const c = loadMag(&limbs, mag, false);
    var str: [700]u8 = undefined;
    var scratch: [bigint.calcToStringLimbsBufferLen(mag_limbs + 1, 10)]Limb = undefined;
    const len = c.toString(&str, 10, .lower, &scratch);
    try w.writeAll(str[0..len]);
}

// Tests
// -----

const expect = std.testing.expect;
const expectEqual = std.testing.expectEqual;
const expectError = std.testing.expectError;

fn expectFmt(expected: []const u8, r: R) !void {
    var buf: [1500]u8 = undefined;
    const s = try std.fmt.bufPrint(&buf, "{f}", .{r});
    try std.testing.expectEqualStrings(expected, s);
}

test "normalization" {
    const a = try R.init(2, 4);
    try expectEqual(@as(i64, 1), a.small.num);
    try expectEqual(@as(i64, 2), a.small.den);
    const b = try R.init(3, -6);
    try expectEqual(@as(i64, -1), b.small.num);
    try expectEqual(@as(i64, 2), b.small.den);
    const z = try R.init(0, -5);
    try expect(z.eql(R.zero));
    try expectError(error.DivisionByZero, R.init(1, 0));
}

test "arithmetic" {
    const half = try R.init(1, 2);
    const third = try R.init(1, 3);
    try expect((try half.add(third)).eql(try R.init(5, 6)));
    try expect((try half.sub(third)).eql(try R.init(1, 6)));
    try expect((try half.mul(third)).eql(try R.init(1, 6)));
    try expect((try half.div(third)).eql(try R.init(3, 2)));
    try expect(half.neg().eql(try R.init(-1, 2)));
    try expectError(error.DivisionByZero, half.div(R.zero));
}

test "small overflow" {
    const big = R.fromInt(std.math.maxInt(i64));
    try expectError(error.Overflow, big.add(R.one));
    try expectError(error.Overflow, big.mul(R.fromInt(2)));
    // (max/3) * 3 reduces back into range:
    const third_of_big = try big.div(R.fromInt(3));
    const back = try third_of_big.mul(R.fromInt(3));
    try expect(back.eql(big));
}

test "big arithmetic and canonical demotion" {
    var arena_state = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena_state.deinit();
    const arena = arena_state.allocator();

    const m = R.fromInt(std.math.maxInt(i64));
    const beyond = try R.addAlloc(arena, m, R.one); // maxInt(i64) + 1
    try expect(beyond == .big);
    try expect(!beyond.big.negative);

    // Coming back down demotes to small (canonical form):
    const back = try R.subAlloc(arena, beyond, R.one);
    try expect(back == .small);
    try expect(back.eql(m));

    // Plain ops refuse big operands:
    try expectError(error.Overflow, beyond.add(R.one));

    // Big * big, then exact division recovers the operand:
    const sq = try R.mulAlloc(arena, beyond, beyond);
    try expect(sq == .big);
    const q = try R.divAlloc(arena, sq, beyond);
    try expect(q.eql(beyond));

    // gcd reduction across the boundary: (2*beyond) / 2 has small/big parts.
    const twice = try R.addAlloc(arena, beyond, beyond);
    const halfback = try R.divAlloc(arena, twice, R.fromInt(2));
    try expect(halfback.eql(beyond));

    // Division by zero:
    try expectError(error.DivisionByZero, R.divAlloc(arena, beyond, R.zero));

    // Magnitude cap: repeated squaring overflows at ~2040 bits.
    var huge = sq;
    const cap_hit = blk: {
        var i: usize = 0;
        while (i < 8) : (i += 1) {
            huge = R.mulAlloc(arena, huge, huge) catch |err| break :blk err;
        }
        break :blk error.NoErrorHit;
    };
    try expectEqual(error.Overflow, cap_hit);
}

test "big sign ops and order" {
    var arena_state = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena_state.deinit();
    const arena = arena_state.allocator();

    const m = R.fromInt(std.math.maxInt(i64));
    const beyond = try R.addAlloc(arena, m, R.one);
    const nbeyond = beyond.neg();
    try expect(nbeyond.big.negative);
    try expect(nbeyond.abs().eql(beyond));
    try expect(!beyond.isZero());

    // order across small/big and big/big:
    try expectEqual(std.math.Order.gt, beyond.order(m));
    try expectEqual(std.math.Order.lt, nbeyond.order(m.neg()));
    try expectEqual(std.math.Order.eq, beyond.order(beyond));
    const bigger = try R.addAlloc(arena, beyond, R.one);
    try expectEqual(std.math.Order.lt, beyond.order(bigger));
    try expect(beyond.eql(beyond.min(bigger)));
    try expect(bigger.eql(beyond.max(bigger)));

    // neg is closed without allocation, even at the i64 boundary:
    try expect(m.neg().neg().eql(m));

    // toFloat approximates:
    const f = beyond.toFloat();
    try expect(f > 9.2e18 and f < 9.3e18);
}

test "fromMags" {
    var arena_state = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena_state.deinit();
    const arena = arena_state.allocator();

    // Small demotion, with leading zeros stripped:
    const half = try R.fromMags(arena, false, &.{ 0, 0, 1 }, &.{2});
    try expect(half.eql(try R.init(1, 2)));
    // Non-normalized input is reduced:
    const r = try R.fromMags(arena, true, &.{4}, &.{6});
    try expect(r.eql(try R.init(-2, 3)));
    // Zero numerator:
    try expect((try R.fromMags(arena, false, &.{}, &.{5})).eql(R.zero));
    // Zero denominator:
    try expectError(error.DivisionByZero, R.fromMags(arena, false, &.{1}, &.{0}));
    // Beyond the cap:
    const too_big = [_]u8{0xff} ** 256;
    try expectError(error.Overflow, R.fromMags(arena, false, &too_big, &.{1}));

    // Round trip through fromMags for a genuinely big value:
    const m = R.fromInt(std.math.maxInt(i64));
    const beyond = try R.addAlloc(arena, m, R.one);
    const again = try R.fromMags(arena, beyond.big.negative, beyond.big.numMag(), beyond.big.denMag());
    try expect(again.eql(beyond));
}

test "order never errors" {
    const big = R.fromInt(std.math.maxInt(i64));
    const small = R.fromInt(std.math.minInt(i64) + 1);
    try expectEqual(std.math.Order.gt, big.order(small));
    try expectEqual(std.math.Order.lt, small.order(big));
    try expectEqual(std.math.Order.eq, big.order(big));
    try expect((try R.init(1, 3)).lt(try R.init(1, 2)));
}

test "parse" {
    try expect((try R.parse("2.5")).eql(try R.init(5, 2)));
    try expect((try R.parse("-2.5")).eql(try R.init(-5, 2)));
    try expect((try R.parse("100n")).eql(try R.init(1, 10_000_000)));
    try expect((try R.parse("12.345G")).eql(R.fromInt(12_345_000_000)));
    try expect((try R.parse("f'15/19")).eql(try R.init(15, 19)));
    try expect((try R.parse("1e-3")).eql(try R.init(1, 1000)));
    try expect((try R.parse("3μ")).eql(try R.init(3, 1_000_000)));
    try expect((try R.parse("0")).eql(R.zero));
    try expectError(error.InvalidRational, R.parse("abc"));
    try expectError(error.InvalidRational, R.parse(""));
    try expectError(error.InvalidRational, R.parse("1.2.3"));
}

test "format matches Python str()" {
    // Reference values from Python: str(R(...))
    try expectFmt("0.", R.zero);
    try expectFmt("1.", R.one);
    try expectFmt("100n", try R.parse("100n"));
    try expectFmt("12.345G", try R.parse("12.345G"));
    try expectFmt("2.5", try R.init(5, 2));
    try expectFmt("-2.5", try R.init(-5, 2));
    try expectFmt("f'1/3", try R.init(1, 3));
    try expectFmt("999.", R.fromInt(999));
    try expectFmt("1k", R.fromInt(1000));
    try expectFmt("1.5m", try R.init(3, 2000));
}

test "format big" {
    var arena_state = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena_state.deinit();
    const arena = arena_state.allocator();
    const m = R.fromInt(std.math.maxInt(i64));
    const beyond = try R.addAlloc(arena, m, R.one); // 2^63
    try expectFmt("f'9223372036854775808/1", beyond);
    try expectFmt("f'-9223372036854775808/1", beyond.neg());
}

test "parse/format round trip" {
    const cases = [_][]const u8{ "100n", "2.5", "1k", "f'1/3", "0.", "-12.5m" };
    for (cases) |c| {
        const r = try R.parse(c);
        var buf: [128]u8 = undefined;
        const s = try std.fmt.bufPrint(&buf, "{f}", .{r});
        const r2 = try R.parse(s);
        try expect(r.eql(r2));
    }
}
