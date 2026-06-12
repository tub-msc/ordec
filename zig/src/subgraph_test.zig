// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Tests for the subgraph core, using a small standalone test schema
//! (mirroring the spirit of tests/test_ordb.py in the Python tree, which
//! also tests against its own miniature schema).

const std = @import("std");
const meta = @import("meta.zig");
const sg = @import("subgraph.zig");

const Allocator = std.mem.Allocator;
const Nid = meta.Nid;
const Str = meta.Str;
const Name = meta.Name;
const NPath = meta.NPath;
const idx = meta.idx;

const gpa = std.testing.allocator;

// Test schema: TSym (symbol-like) and TSch (schematic-like)
// ----------------------------------------------------------

const TSym = struct {
    caption: ?Str = null,
    pub const ordb_nodes = .{TPin};
};

const TPin = struct {
    num: ?i32 = null,
    pub const ordb_indexes = .{
        .num_idx = idx(&.{"num"}, .{ .unique = true }),
    };
};

fn ofRootSym(view: anytype, nid: Nid) ?*meta.FrozenHeader {
    _ = nid;
    return view.rootValue().sym.ptr;
}

fn ofInstSym(view: anytype, nid: Nid) ?*meta.FrozenHeader {
    const conn = view.getNodeAs(TConn, nid) orelse return null;
    const inst_nid = conn.ref.nid orelse return null;
    const inst = view.getNodeAs(TInst, inst_nid) orelse return null;
    return inst.sym.ptr;
}

const TSch = struct {
    sym: meta.SubgraphRef(TSym, .{}) = .none,
    title: ?Str = null,
    pub const ordb_nodes = .{ TNet, TInst, TConn };
};

const TNet = struct {
    pin: meta.ExternalRef(TSym, .{TPin}, ofRootSym, .{}) = .none,
    weight: ?i32 = null,
    pub const ordb_indexes = .{
        .weight_idx = idx(&.{"weight"}, .{}),
    };
};

const TInst = struct {
    sym: meta.SubgraphRef(TSym, .{ .required = true }) = .none,
    x: ?i32 = null,
};

const TConn = struct {
    ref: meta.LocalRef(.{TInst}, .{ .required = true }) = .none,
    here: meta.LocalRef(.{TNet}, .{ .required = true }) = .none,
    there: meta.ExternalRef(TSym, .{TPin}, ofInstSym, .{ .required = true }) = .none,
    pub const ordb_indexes = .{
        .ref_idx = idx(&.{"ref"}, .{}),
        .ref_there_idx = idx(&.{ "ref", "there" }, .{ .unique = true }),
    };
};

const SymSG = sg.Subgraph(TSym);
const SchSG = sg.Subgraph(TSch);

fn makeSym(captions: []const u8, pin_nums: []const i32) !*SymSG.Frozen {
    var m = try SymSG.Mutable.init(gpa, .{ .caption = captions });
    defer m.deinit();
    for (pin_nums) |n| {
        _ = try m.insert(TPin{ .num = n });
    }
    return m.freeze();
}

// Basic construction, queries, defaults
// -------------------------------------

test "init, insert, query" {
    var m = try SchSG.Mutable.init(gpa, .{ .title = "top" });
    defer m.deinit();

    const n1 = try m.insert(TNet{ .weight = 5 });
    const n2 = try m.insert(TNet{ .weight = 7 });
    try std.testing.expectEqual(@as(Nid, 1), n1.nid);
    try std.testing.expectEqual(@as(Nid, 2), n2.nid);

    const nets = try m.view().all(TNet, gpa);
    defer gpa.free(nets);
    try std.testing.expectEqual(2, nets.len);
    try std.testing.expectEqual(@as(?i32, 5), nets[0].field(.weight));

    // root value & title string is arena-owned:
    try std.testing.expectEqualStrings("top", m.view().rootValue().title.?);

    // one() on a two-element type errors:
    try std.testing.expectError(error.NotUnique, m.view().one(TNet, gpa));
    _ = try m.view().one(TSch, gpa);

    // allBy weight index:
    const heavy = try m.view().allBy(TNet, "weight_idx", .{@as(?i32, 7)}, gpa);
    defer gpa.free(heavy);
    try std.testing.expectEqual(1, heavy.len);
    try std.testing.expectEqual(n2.nid, heavy[0].nid);
}

test "missing required attribute fails commit and rolls back" {
    var m = try SchSG.Mutable.init(gpa, .{});
    defer m.deinit();
    _ = try m.insert(TNet{});

    var diag: sg.Diag = .{};
    {
        var t = m.txn();
        errdefer t.abort();
        _ = try t.insert(TInst{}); // missing required sym
        try std.testing.expectError(error.MissingAttr, t.commit(&diag));
    }
    try std.testing.expectEqualStrings("TInst", diag.node_type);
    try std.testing.expectEqualStrings("sym", diag.field);

    // Rolled back: no TInst exists, nid_next unchanged:
    const insts = try m.view().all(TInst, gpa);
    defer gpa.free(insts);
    try std.testing.expectEqual(0, insts.len);
    const next = try m.insert(TNet{});
    try std.testing.expectEqual(@as(Nid, 2), next.nid);
}

test "unique index violation" {
    var sym = try makeSym("sym", &.{ 1, 2 });
    defer sym.release();

    // Within one subgraph: duplicate pin num
    var m = try SymSG.Mutable.init(gpa, .{});
    defer m.deinit();
    _ = try m.insert(TPin{ .num = 1 });
    {
        var t = m.txn();
        errdefer t.abort();
        _ = try t.insert(TPin{ .num = 1 });
        try std.testing.expectError(error.UniqueViolation, t.commit(null));
    }
    // Null values are not indexed, so several null pins are fine:
    _ = try m.insert(TPin{});
    _ = try m.insert(TPin{});

    // Update collision:
    const p2 = try m.insert(TPin{ .num = 2 });
    try std.testing.expectError(error.UniqueViolation, p2.set(.num, 1));
    // ...left untouched:
    try std.testing.expectEqual(@as(?i32, 2), p2.field(.num));
}

test "dangling and mistyped local refs" {
    var sym = try makeSym("s", &.{1});
    defer sym.release();
    var m = try SchSG.Mutable.init(gpa, .{ .sym = .of(sym) });
    defer m.deinit();

    const net = try m.insert(TNet{});
    const inst = try m.insert(TInst{ .sym = .of(sym) });

    // Dangling:
    {
        var t = m.txn();
        errdefer t.abort();
        _ = try t.insert(TConn{ .ref = .to(@as(Nid, 99)), .here = .to(net), .there = .to(@as(Nid, 1)) });
        try std.testing.expectError(error.DanglingLocalRef, t.commit(null));
    }
    // Wrong target type (here must be a TNet, give it the TInst):
    {
        var t = m.txn();
        errdefer t.abort();
        _ = try t.insert(TConn{ .ref = .to(inst), .here = .to(inst), .there = .to(@as(Nid, 1)) });
        try std.testing.expectError(error.RefTypeMismatch, t.commit(null));
    }
    // Correct:
    _ = try m.insert(TConn{ .ref = .to(inst), .here = .to(net), .there = .to(@as(Nid, 1)) });
}

test "external ref validation and deref" {
    var sym = try makeSym("s", &.{ 1, 2 }); // pins at nid 1, 2
    defer sym.release();

    var m = try SchSG.Mutable.init(gpa, .{ .sym = .of(sym) });
    defer m.deinit();

    // Resolves via root sym:
    const net = try m.insert(TNet{ .pin = .to(@as(Nid, 1)) });
    const pin = try net.derefExternal(.pin);
    try std.testing.expectEqual(@as(?i32, 1), pin.field(.num));

    // Dangling external nid:
    {
        var t = m.txn();
        errdefer t.abort();
        _ = try t.insert(TNet{ .pin = .to(@as(Nid, 77)) });
        try std.testing.expectError(error.DanglingExternalRef, t.commit(null));
    }

    // External ref pointing at the sym ROOT node (wrong type):
    {
        var t = m.txn();
        errdefer t.abort();
        _ = try t.insert(TNet{ .pin = .to(@as(Nid, 0)) });
        try std.testing.expectError(error.RefTypeMismatch, t.commit(null));
    }

    // Unresolvable: subgraph without sym set
    var m2 = try SchSG.Mutable.init(gpa, .{});
    defer m2.deinit();
    {
        var t = m2.txn();
        errdefer t.abort();
        _ = try t.insert(TNet{ .pin = .to(@as(Nid, 1)) });
        try std.testing.expectError(error.ExternalRefUnresolvable, t.commit(null));
    }
}

test "remove and dangling protection" {
    var sym = try makeSym("s", &.{1});
    defer sym.release();
    var m = try SchSG.Mutable.init(gpa, .{ .sym = .of(sym) });
    defer m.deinit();

    const net = try m.insert(TNet{});
    const inst = try m.insert(TInst{ .sym = .of(sym) });
    const conn = try m.insert(TConn{ .ref = .to(inst), .here = .to(net), .there = .to(@as(Nid, 1)) });

    // Removing the net while conn references it must fail:
    try std.testing.expectError(error.RemovedStillReferenced, net.remove());
    // Net is still there:
    _ = try m.view().one(TNet, gpa);

    // Removing conn first, then net, works:
    try conn.remove();
    try net.remove();
    const nets = try m.view().all(TNet, gpa);
    defer gpa.free(nets);
    try std.testing.expectEqual(0, nets.len);

    // Root removal is rejected:
    var t = m.txn();
    defer t.abort();
    try std.testing.expectError(error.RootRemoval, t.removeNid(0));
}

test "cursor set and update" {
    var m = try SchSG.Mutable.init(gpa, .{});
    defer m.deinit();
    const net = try m.insert(TNet{ .weight = 1 });
    try net.set(.weight, 10);
    try std.testing.expectEqual(@as(?i32, 10), net.field(.weight));
    try net.set(.weight, null);
    try std.testing.expectEqual(@as(?i32, null), net.field(.weight));
}

// NPath
// -----

test "npath put, at, children, fullPathStr" {
    var m = try SchSG.Mutable.init(gpa, .{});
    defer m.deinit();

    const vdd = try m.put("vdd", TNet{ .weight = 1 });
    _ = try m.put("gnd", TNet{ .weight = 2 });

    // Lookup by name:
    const found = try m.root().at("vdd");
    try std.testing.expectEqual(vdd.nid, found.nid.?);
    const tnet = try found.as(TNet);
    try std.testing.expectEqual(@as(?i32, 1), tnet.field(.weight));
    try std.testing.expectError(error.PathNotFound, m.root().at("nope"));

    // Name collision:
    try std.testing.expectError(error.PathExists, m.put("vdd", TNet{}));

    // Empty path nodes (Python: x.name = PathNode()):
    const holder = try m.root().putPath("insts");
    try std.testing.expectEqual(null, holder.nid);
    try std.testing.expectError(error.WrongNodeType, holder.as(TNet));
    const found_holder = try m.root().at("insts");
    try std.testing.expectEqual(holder.npath_nid, found_holder.npath_nid);
}

test "npath paths" {
    var sym = try makeSym("s", &.{1});
    defer sym.release();
    var m = try SchSG.Mutable.init(gpa, .{ .sym = .of(sym) });
    defer m.deinit();

    const inst0 = try m.put("I0", TInst{ .sym = .of(sym) });
    // children of I0, named "sub" and indexed [0]:
    const sub = try inst0.put("sub", TNet{});
    const subpath = try sub.putPath("parts");
    _ = subpath;
    const arr0 = try sub.put(0, TNet{ .weight = 42 });

    const s = try arr0.fullPathStr(gpa);
    defer gpa.free(s);
    try std.testing.expectEqualStrings("I0.sub[0]", s);

    // at() chaining through AnyCursor:
    const found = try (try (try m.root().at("I0")).at("sub")).at(0);
    try std.testing.expectEqual(arr0.nid, found.nid.?);

    // children() of I0:
    const kids = try inst0.children(gpa);
    defer gpa.free(kids);
    try std.testing.expectEqual(1, kids.len);
    try std.testing.expectEqual(sub.nid, kids[0].nid.?);

    // invalid name:
    try std.testing.expectError(error.InvalidName, m.put("0abc", TNet{}));

    // removing a node removes its path:
    try arr0.remove();
    try std.testing.expectError(error.PathNotFound, (try (try m.root().at("I0")).at("sub")).at(0));
}

// Freeze / thaw chains
// --------------------

test "freeze, thaw, shadowing across generations" {
    var m0 = try SchSG.Mutable.init(gpa, .{ .title = "gen0" });
    defer m0.deinit();
    const a = try m0.insert(TNet{ .weight = 1 });
    const b = try m0.insert(TNet{ .weight = 2 });
    _ = b;
    const f0 = try m0.freeze();
    defer f0.release();

    // Frozen reads:
    try std.testing.expectEqualStrings("gen0", f0.view().rootValue().title.?);
    {
        const nets = try f0.view().all(TNet, gpa);
        defer gpa.free(nets);
        try std.testing.expectEqual(2, nets.len);
    }

    // Frozen cursors reject set():
    const fa = try f0.view().cursorAt(TNet, a.nid);
    try std.testing.expectError(error.Frozen, fa.set(.weight, 9));

    // Thaw and modify:
    var m1 = try f0.thaw();
    defer m1.deinit();
    const c1 = try m1.view().cursorAt(TNet, a.nid);
    try c1.set(.weight, 100);
    _ = try m1.insert(TNet{ .weight = 3 });

    // New generation sees the change, original frozen does not:
    try std.testing.expectEqual(@as(?i32, 100), m1.view().getNodeAs(TNet, a.nid).?.weight);
    try std.testing.expectEqual(@as(?i32, 1), f0.view().getNodeAs(TNet, a.nid).?.weight);
    {
        const nets0 = try f0.view().all(TNet, gpa);
        defer gpa.free(nets0);
        const nets1 = try m1.view().all(TNet, gpa);
        defer gpa.free(nets1);
        try std.testing.expectEqual(2, nets0.len);
        try std.testing.expectEqual(3, nets1.len);
    }

    // Remove (tombstone) a parent node; verify shadowing in reads and queries:
    const f1 = try m1.freeze();
    defer f1.release();
    var m2 = try f1.thaw();
    defer m2.deinit();
    const c2 = try m2.view().cursorAt(TNet, a.nid);
    try c2.remove();
    try std.testing.expectEqual(null, m2.view().getNode(a.nid));
    {
        const nets2 = try m2.view().all(TNet, gpa);
        defer gpa.free(nets2);
        try std.testing.expectEqual(2, nets2.len); // 3 - 1 removed
        // index query: removed net's weight must not surface
        const w100 = try m2.view().allBy(TNet, "weight_idx", .{@as(?i32, 100)}, gpa);
        defer gpa.free(w100);
        try std.testing.expectEqual(0, w100.len);
    }
    // Two generations down, f0 is untouched:
    try std.testing.expectEqual(@as(?i32, 1), f0.view().getNodeAs(TNet, a.nid).?.weight);
}

test "index re-key shadows old key across generations" {
    var m0 = try SchSG.Mutable.init(gpa, .{});
    defer m0.deinit();
    const a = try m0.insert(TNet{ .weight = 1 });
    const f0 = try m0.freeze();
    defer f0.release();

    var m1 = try f0.thaw();
    defer m1.deinit();
    try (try m1.view().cursorAt(TNet, a.nid)).set(.weight, 2);

    const w1 = try m1.view().allBy(TNet, "weight_idx", .{@as(?i32, 1)}, gpa);
    defer gpa.free(w1);
    try std.testing.expectEqual(0, w1.len);
    const w2 = try m1.view().allBy(TNet, "weight_idx", .{@as(?i32, 2)}, gpa);
    defer gpa.free(w2);
    try std.testing.expectEqual(1, w2.len);
}

test "compact preserves nids and content" {
    var m0 = try SchSG.Mutable.init(gpa, .{ .title = "x" });
    defer m0.deinit();
    _ = try m0.insert(TNet{ .weight = 1 });
    const b = try m0.insert(TNet{ .weight = 2 });
    const f0 = try m0.freeze();
    defer f0.release();

    var m1 = try f0.thaw();
    defer m1.deinit();
    try (try m1.view().cursorAt(TNet, b.nid)).set(.weight, 20);
    _ = try m1.insert(TNet{ .weight = 3 });
    const f1 = try m1.freeze();
    defer f1.release();

    const fc = try f1.compact();
    defer fc.release();
    try std.testing.expectEqual(0, fc.parents.len);
    try std.testing.expectEqual(f1.nid_end, fc.nid_end);

    const nids1 = try f1.view().allNids(gpa);
    defer gpa.free(nids1);
    const nidsc = try fc.view().allNids(gpa);
    defer gpa.free(nidsc);
    try std.testing.expectEqualSlices(Nid, nids1, nidsc);
    for (nids1) |nid| {
        const n1 = f1.view().getNode(nid).?;
        const nc = fc.view().getNode(nid).?;
        try std.testing.expect(meta.deepEql(n1, nc));
    }
}

// Multi-parent merge
// ------------------

test "multi-parent merge with nid translation" {
    // Parent A: two pins; parent B: one pin (disjoint nums for unique sweep)
    var ma = try SymSG.Mutable.init(gpa, .{ .caption = "ab" });
    defer ma.deinit();
    _ = try ma.insert(TPin{ .num = 1 });
    _ = try ma.insert(TPin{ .num = 2 });
    const fa = try ma.freeze();
    defer fa.release();

    var mb = try SymSG.Mutable.init(gpa, .{});
    defer mb.deinit();
    _ = try mb.insert(TPin{ .num = 30 });
    const fb = try mb.freeze();
    defer fb.release();

    var merged = try SymSG.thawMulti(gpa, &.{ fa, fb });
    defer merged.deinit();

    // Merged root carries parent0's attributes:
    try std.testing.expectEqualStrings("ab", merged.view().rootValue().caption.?);

    // All three pins visible; b's pin translated by fa.nid_end:
    const pins = try merged.view().all(TPin, gpa);
    defer gpa.free(pins);
    try std.testing.expectEqual(3, pins.len);
    const b_pin_nid = fa.nid_end + 1;
    try std.testing.expectEqual(@as(?i32, 30), merged.view().getNodeAs(TPin, b_pin_nid).?.num);

    // The hole where parent B's root would be:
    try std.testing.expectEqual(null, merged.view().getNode(fa.nid_end));

    //

    // Unique index works across the merge:
    const found = try merged.view().oneBy(TPin, "num_idx", .{@as(?i32, 30)}, gpa);
    try std.testing.expectEqual(b_pin_nid, found.nid);
}

test "multi-parent merge translates LocalRefs" {
    var sym = try makeSym("s", &.{1});
    defer sym.release();

    // Parent A: empty schematic. Parent B: net + inst + conn.
    var ma = try SchSG.Mutable.init(gpa, .{ .sym = .of(sym) });
    defer ma.deinit();
    _ = try ma.insert(TNet{ .weight = 7 });
    const fa = try ma.freeze();
    defer fa.release();

    var mb = try SchSG.Mutable.init(gpa, .{ .sym = .of(sym) });
    defer mb.deinit();
    const bnet = try mb.insert(TNet{});
    const binst = try mb.insert(TInst{ .sym = .of(sym) });
    _ = try mb.insert(TConn{ .ref = .to(binst), .here = .to(bnet), .there = .to(@as(Nid, 1)) });
    const fb = try mb.freeze();
    defer fb.release();

    var merged = try SchSG.thawMulti(gpa, &.{ fa, fb });
    defer merged.deinit();

    const off = fa.nid_end;
    const conn = merged.view().getNodeAs(TConn, off + 3).?;
    try std.testing.expectEqual(@as(?Nid, off + 2), conn.ref.nid);
    try std.testing.expectEqual(@as(?Nid, off + 1), conn.here.nid);
    // External nid is NOT translated (foreign nid space):
    try std.testing.expectEqual(@as(?Nid, 1), conn.there.nid);

    // ref_idx query with child-space key reaches into parent B:
    const conns = try merged.view().allBy(TConn, "ref_idx", .{@as(?Nid, off + 2)}, gpa);
    defer gpa.free(conns);
    try std.testing.expectEqual(1, conns.len);

    // New nodes in the merged generation referencing parent nodes collide
    // with the existing conn on the unique (ref, there) index:
    try std.testing.expectError(error.UniqueViolation, merged.insert(TConn{
        .ref = .to(off + 2),
        .here = .to(off + 1),
        .there = .to(@as(Nid, 1)),
    }));
}

test "multi-parent root conflict is strict" {
    var ma = try SymSG.Mutable.init(gpa, .{ .caption = "a" });
    defer ma.deinit();
    const fa = try ma.freeze();
    defer fa.release();
    var mb = try SymSG.Mutable.init(gpa, .{ .caption = "b" });
    defer mb.deinit();
    const fb = try mb.freeze();
    defer fb.release();
    var mc = try SymSG.Mutable.init(gpa, .{}); // null caption: no opinion
    defer mc.deinit();
    const fc = try mc.freeze();
    defer fc.release();

    try std.testing.expectError(error.RootConflict, SymSG.thawMulti(gpa, &.{ fa, fb }));
    var ok = try SymSG.thawMulti(gpa, &.{ fa, fc });
    ok.deinit();
}

test "multi-parent unique sweep" {
    var ma = try SymSG.Mutable.init(gpa, .{});
    defer ma.deinit();
    _ = try ma.insert(TPin{ .num = 1 });
    const fa = try ma.freeze();
    defer fa.release();
    var mb = try SymSG.Mutable.init(gpa, .{});
    defer mb.deinit();
    _ = try mb.insert(TPin{ .num = 1 });
    const fb = try mb.freeze();
    defer fb.release();

    try std.testing.expectError(error.UniqueViolation, SymSG.thawMulti(gpa, &.{ fa, fb }));
}

test "subgraph refs keep targets alive" {
    var msym = try SymSG.Mutable.init(gpa, .{ .caption = "kept" });
    defer msym.deinit();
    _ = try msym.insert(TPin{ .num = 1 });
    const fsym = try msym.freeze();

    var m = try SchSG.Mutable.init(gpa, .{ .sym = .of(fsym) });
    defer m.deinit();
    const net = try m.insert(TNet{ .pin = .to(@as(Nid, 1)) });

    // Drop our own reference; the schematic's SubgraphRef keeps fsym alive:
    fsym.release();
    const pin = try net.derefExternal(.pin);
    try std.testing.expectEqual(@as(?i32, 1), pin.field(.num));
    // m.deinit() releases the last reference (leak check would fire otherwise).
}
