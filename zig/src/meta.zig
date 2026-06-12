// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Compile-time schema machinery for the Zig ORDB implementation.
//!
//! Node types are plain Zig structs. Plain attributes are plain (usually
//! optional) fields; reference attributes use the wrapper types LocalRef,
//! ExternalRef and SubgraphRef, which carry their metadata in comptime
//! declarations. A subgraph root type lists its permitted node types in
//! `ordb_nodes`; from this, NodeUnion() and IndexStorage() elaborate the
//! whole storage schema at compile time. This replaces the metaclass
//! machinery of the Python implementation (ordec.core.ordb.NodeMeta).

const std = @import("std");
const Allocator = std.mem.Allocator;

pub const Nid = u32;
pub const Str = []const u8;

// FrozenHeader: common type-erased prefix of all frozen subgraphs
// ---------------------------------------------------------------

/// Every Subgraph(Root).Frozen embeds a FrozenHeader as its first field.
/// SubgraphRef attributes store a type-erased *FrozenHeader, which breaks
/// the comptime cycle Subgraph(Layout) -> LayoutInstance -> Subgraph(Layout)
/// and gives the refcounting a uniform handle.
///
/// Reference counting is non-atomic: single-threaded use is assumed.
pub const FrozenHeader = struct {
    refcount: usize = 1,
    /// sha256 of the canonical CBOR content form (see serialize.zig);
    /// computed by freeze(), so it is always valid on a live Frozen.
    hash: [32]u8 = @splat(0),
    /// Base name of the SubgraphRoot type, e.g. "Schematic".
    root_type: []const u8,
    vtable: *const VTable,

    pub const VTable = struct {
        destroy: *const fn (*FrozenHeader) void,
    };

    pub fn retain(h: *FrozenHeader) *FrozenHeader {
        h.refcount += 1;
        return h;
    }

    pub fn release(h: *FrozenHeader) void {
        std.debug.assert(h.refcount > 0);
        h.refcount -= 1;
        if (h.refcount == 0) h.vtable.destroy(h);
    }
};

// Attribute wrappers
// ------------------

pub const AttrKind = enum { plain, local_ref, external_ref, subgraph_ref };

pub const RefOpts = struct { required: bool = false };

/// Reference to a node within the same subgraph, stored as nid.
/// `targets` is a tuple of permitted node types; an empty tuple permits any
/// node type (used by NPath.ref). Mirrors ordb.LocalRef.
pub fn LocalRef(comptime targets: anytype, comptime opts: RefOpts) type {
    return struct {
        nid: ?Nid = null,

        pub const ordb_kind: AttrKind = .local_ref;
        pub const ordb_targets = targets;
        pub const ordb_required = opts.required;
        pub const none: @This() = .{};

        /// Accepts a Nid or anything with a .nid field (a cursor).
        pub fn to(target: anytype) @This() {
            return .{ .nid = nidOf(target) };
        }
    };
}

/// Reference to a node in another (frozen) subgraph, stored as nid in that
/// subgraph's nid space. `of_subgraph` mirrors the Python of_subgraph lambda:
/// fn (view: anytype, nid: Nid) ?*FrozenHeader, resolving the SubgraphRef
/// that this ExternalRef is relative to. Mirrors ordb.ExternalRef.
pub fn ExternalRef(
    comptime ForeignRoot: type,
    comptime targets: anytype,
    comptime of_subgraph: anytype,
    comptime opts: RefOpts,
) type {
    return struct {
        nid: ?Nid = null,

        pub const ordb_kind: AttrKind = .external_ref;
        pub const ordb_foreign_root = ForeignRoot;
        pub const ordb_targets = targets;
        pub const ordb_of = of_subgraph;
        pub const ordb_required = opts.required;
        pub const none: @This() = .{};

        /// Accepts a Nid or anything with a .nid field (a foreign cursor).
        pub fn to(target: anytype) @This() {
            return .{ .nid = nidOf(target) };
        }
    };
}

/// Reference to a whole frozen subgraph. Mirrors ordb.SubgraphRef.
/// A delta entry holding a non-null SubgraphRef owns one retain on the target.
pub fn SubgraphRef(comptime Root: type, comptime opts: RefOpts) type {
    return struct {
        ptr: ?*FrozenHeader = null,

        pub const ordb_kind: AttrKind = .subgraph_ref;
        pub const ordb_root = Root;
        pub const ordb_required = opts.required;
        pub const none: @This() = .{};

        /// Accepts a *Subgraph(Root).Frozen (anything embedding a header).
        /// Does not retain; insertion into a subgraph retains.
        pub fn of(frozen: anytype) @This() {
            return .{ .ptr = &frozen.header };
        }
    };
}

fn nidOf(target: anytype) Nid {
    return switch (@typeInfo(@TypeOf(target))) {
        .int, .comptime_int => target,
        else => target.nid,
    };
}

pub fn attrKind(comptime FieldT: type) AttrKind {
    return switch (@typeInfo(FieldT)) {
        .@"struct" => if (@hasDecl(FieldT, "ordb_kind")) FieldT.ordb_kind else .plain,
        else => .plain,
    };
}

/// Whether a field must be non-null at transaction commit.
pub fn isRequired(comptime NodeT: type, comptime field_name: []const u8) bool {
    const FieldT = @FieldType(NodeT, field_name);
    if (comptime attrKind(FieldT) != .plain) return FieldT.ordb_required;
    if (@hasDecl(NodeT, "ordb_required_fields")) {
        inline for (NodeT.ordb_required_fields) |name| {
            if (comptime std.mem.eql(u8, name, field_name)) return true;
        }
    }
    return false;
}

// Index declarations
// ------------------

pub const IndexDecl = struct {
    fields: []const []const u8,
    unique: bool = false,
    /// Field by which query results are sorted (instead of by nid).
    sort_by: ?[]const u8 = null,
};

pub const IdxOpts = struct { unique: bool = false, sort_by: ?[]const u8 = null };

pub fn idx(comptime fields: []const []const u8, comptime opts: IdxOpts) IndexDecl {
    return .{ .fields = fields, .unique = opts.unique, .sort_by = opts.sort_by };
}

// NPath: hierarchical naming (part of the core, as in Python's ordb.py)
// ---------------------------------------------------------------------

pub const Name = union(enum) {
    s: Str,
    i: i64,

    pub fn str(s: Str) Name {
        return .{ .s = s };
    }

    pub fn int(i: i64) Name {
        return .{ .i = i };
    }

    pub fn eql(a: Name, b: Name) bool {
        return deepEql(a, b);
    }

    /// String names must start with an ASCII letter or underscore.
    pub fn validate(self: Name) error{InvalidName}!void {
        switch (self) {
            .s => |s| {
                if (s.len < 1) return error.InvalidName;
                switch (s[0]) {
                    'a'...'z', 'A'...'Z', '_' => {},
                    else => return error.InvalidName,
                }
            },
            .i => {},
        }
    }
};

/// NPath nodes build a subgraph's path hierarchy ("I0.sub[0]").
pub const NPath = struct {
    parent: LocalRef(.{NPath}, .{}) = .none,
    name: ?Name = null,
    ref: LocalRef(.{}, .{}) = .none,

    pub const ordb_required_fields = .{"name"};
    pub const ordb_indexes = .{
        .idx_parent = idx(&.{"parent"}, .{}),
        .idx_parent_name = idx(&.{ "parent", "name" }, .{ .unique = true }),
        .idx_path_of = idx(&.{"ref"}, .{ .unique = true }),
    };
};

// Comptime node-type tables
// -------------------------

/// Base name of a type, e.g. "schema.Net" -> "Net".
pub fn typeBaseName(comptime T: type) [:0]const u8 {
    const full = @typeName(T);
    comptime var i = full.len;
    inline while (i > 0) : (i -= 1) {
        if (full[i - 1] == '.') break;
    }
    return full[i..] ++ "";
}

/// All node types of a subgraph rooted at Root: the root itself, NPath, and
/// the types listed in Root.ordb_nodes.
pub fn nodeTypes(comptime Root: type) [2 + Root.ordb_nodes.len]type {
    comptime var result: [2 + Root.ordb_nodes.len]type = undefined;
    result[0] = Root;
    result[1] = NPath;
    inline for (Root.ordb_nodes, 0..) |T, i| result[2 + i] = T;
    return result;
}

pub fn typeIndexOpt(comptime Root: type, comptime T: type) ?usize {
    const types = nodeTypes(Root);
    inline for (types, 0..) |U, i| {
        if (U == T) return i;
    }
    return null;
}

pub fn typeIndex(comptime Root: type, comptime T: type) usize {
    if (comptime typeIndexOpt(Root, T) == null) {
        @compileError("Node type " ++ @typeName(T) ++ " is not permitted in subgraph " ++
            @typeName(Root) ++ " (not listed in ordb_nodes).");
    }
    return comptime typeIndexOpt(Root, T).?;
}

/// Tagged union over all node types of a subgraph. Tag names are the node
/// type base names; tag values follow declaration order.
pub fn NodeUnion(comptime Root: type) type {
    const types = nodeTypes(Root);
    comptime var names: [types.len][]const u8 = undefined;
    comptime var field_types: [types.len]type = undefined;
    inline for (types, 0..) |T, i| {
        names[i] = typeBaseName(T);
        field_types[i] = T;
    }
    const TagT = @Enum(u32, .exhaustive, &names, &std.simd.iota(u32, types.len));
    return @Union(.auto, TagT, &names, &field_types, &@splat(.{}));
}

pub fn tagFor(comptime Root: type, comptime T: type) std.meta.Tag(NodeUnion(Root)) {
    return @enumFromInt(typeIndex(Root, T));
}

// Deep hash / equality (for index keys and node comparison)
// ---------------------------------------------------------

pub fn deepHashInto(hasher: anytype, v: anytype) void {
    const T = @TypeOf(v);
    switch (@typeInfo(T)) {
        .int, .float, .bool => hasher.update(std.mem.asBytes(&v)),
        .@"enum" => {
            const tag = @intFromEnum(v);
            hasher.update(std.mem.asBytes(&tag));
        },
        .optional => {
            if (v) |inner| {
                hasher.update(&.{1});
                deepHashInto(hasher, inner);
            } else {
                hasher.update(&.{0});
            }
        },
        .@"struct" => |s| {
            inline for (s.fields) |f| deepHashInto(hasher, @field(v, f.name));
        },
        .@"union" => {
            const tag = @intFromEnum(std.meta.activeTag(v));
            hasher.update(std.mem.asBytes(&tag));
            switch (v) {
                inline else => |payload| deepHashInto(hasher, payload),
            }
        },
        .pointer => |p| switch (p.size) {
            .slice => {
                if (p.child != u8)
                    @compileError("deepHash: only []const u8 slices supported");
                var len: u64 = v.len;
                hasher.update(std.mem.asBytes(&len));
                hasher.update(v);
            },
            .one => {
                const addr = @intFromPtr(v);
                hasher.update(std.mem.asBytes(&addr));
            },
            else => @compileError("deepHash: unsupported pointer type " ++ @typeName(T)),
        },
        .void => {},
        else => @compileError("deepHash: unsupported type " ++ @typeName(T)),
    }
}

pub fn deepHash(v: anytype) u64 {
    var hasher = std.hash.Wyhash.init(0x07db);
    deepHashInto(&hasher, v);
    return hasher.final();
}

pub fn deepEql(a: anytype, b: @TypeOf(a)) bool {
    const T = @TypeOf(a);
    switch (@typeInfo(T)) {
        .int, .float, .bool, .@"enum", .void => return a == b,
        .optional => {
            if (a == null and b == null) return true;
            if (a == null or b == null) return false;
            return deepEql(a.?, b.?);
        },
        .@"struct" => |s| {
            inline for (s.fields) |f| {
                if (!deepEql(@field(a, f.name), @field(b, f.name))) return false;
            }
            return true;
        },
        .@"union" => {
            if (std.meta.activeTag(a) != std.meta.activeTag(b)) return false;
            switch (a) {
                inline else => |payload, tag| {
                    return deepEql(payload, @field(b, @tagName(tag)));
                },
            }
        },
        .pointer => |p| switch (p.size) {
            .slice => {
                if (p.child != u8)
                    @compileError("deepEql: only []const u8 slices supported");
                return std.mem.eql(u8, a, b);
            },
            .one => return a == b,
            else => @compileError("deepEql: unsupported pointer type " ++ @typeName(T)),
        },
        else => @compileError("deepEql: unsupported type " ++ @typeName(T)),
    }
}

// Per-node-type helpers
// ---------------------

/// Copy all byte-slice data ([]const u8 in ?Str fields, Name unions, and big
/// rationals -- also nested inside plain structs like Vec2R) into the given
/// arena, so node values never borrow caller memory.
pub fn dupeStrings(comptime T: type, v: T, arena: Allocator) Allocator.Error!T {
    var result = v;
    inline for (std.meta.fields(T)) |f| {
        @field(result, f.name) = try dupeStringsValue(f.type, @field(v, f.name), arena);
    }
    return result;
}

/// Comptime: does T (transitively) contain a []const u8?
fn containsByteSlice(comptime T: type) bool {
    return switch (@typeInfo(T)) {
        .optional => |o| containsByteSlice(o.child),
        .pointer => |p| p.size == .slice and p.child == u8,
        .@"struct" => |s| inline for (s.fields) |f| {
            if (containsByteSlice(f.type)) break true;
        } else false,
        .@"union" => |u| inline for (u.fields) |f| {
            if (containsByteSlice(f.type)) break true;
        } else false,
        else => false,
    };
}

fn dupeStringsValue(comptime T: type, v: T, arena: Allocator) Allocator.Error!T {
    if (comptime !containsByteSlice(T)) return v;
    switch (@typeInfo(T)) {
        .optional => |o| {
            if (v) |inner| return try dupeStringsValue(o.child, inner, arena);
            return null;
        },
        .pointer => |p| {
            if (p.size == .slice and p.child == u8) return try arena.dupe(u8, v);
            return v;
        },
        .@"struct" => {
            var out = v;
            inline for (std.meta.fields(T)) |f| {
                @field(out, f.name) = try dupeStringsValue(f.type, @field(v, f.name), arena);
            }
            return out;
        },
        .@"union" => |u| {
            if (u.tag_type == null) return v;
            switch (v) {
                inline else => |payload, tag| {
                    return @unionInit(T, @tagName(tag), try dupeStringsValue(@TypeOf(payload), payload, arena));
                },
            }
        },
        else => return v,
    }
}

/// Translate all LocalRef nids of a node by `offset` (nid 0 maps to 0: a
/// reference to a parent root becomes a reference to the merged root).
pub fn translateLocalRefs(comptime T: type, v: T, offset: Nid) T {
    var result = v;
    if (offset == 0) return result;
    inline for (std.meta.fields(T)) |f| {
        if (comptime attrKind(f.type) == .local_ref) {
            if (@field(v, f.name).nid) |nid| {
                if (nid != 0) @field(result, f.name).nid = nid + offset;
            }
        }
    }
    return result;
}

/// Retain all non-null SubgraphRef targets of a node value.
pub fn retainSubgraphRefs(comptime T: type, v: T) void {
    inline for (std.meta.fields(T)) |f| {
        if (comptime attrKind(f.type) == .subgraph_ref) {
            if (@field(v, f.name).ptr) |h| _ = h.retain();
        }
    }
}

/// Release all non-null SubgraphRef targets of a node value.
pub fn releaseSubgraphRefs(comptime T: type, v: T) void {
    inline for (std.meta.fields(T)) |f| {
        if (comptime attrKind(f.type) == .subgraph_ref) {
            if (@field(v, f.name).ptr) |h| h.release();
        }
    }
}

// Index storage
// -------------

pub const NidList = std.ArrayList(Nid);

fn nidListLowerBound(items: []const Nid, nid: Nid) usize {
    var lo: usize = 0;
    var hi: usize = items.len;
    while (lo < hi) {
        const mid = lo + (hi - lo) / 2;
        if (items[mid] < nid) lo = mid + 1 else hi = mid;
    }
    return lo;
}

pub fn nidListInsert(list: *NidList, alloc: Allocator, nid: Nid) Allocator.Error!void {
    const pos = nidListLowerBound(list.items, nid);
    try list.insert(alloc, pos, nid);
}

/// Remove one occurrence of nid. Asserts presence.
pub fn nidListRemove(list: *NidList, nid: Nid) void {
    const pos = nidListLowerBound(list.items, nid);
    std.debug.assert(pos < list.items.len and list.items[pos] == nid);
    _ = list.orderedRemove(pos);
}

pub fn DeepContext(comptime K: type) type {
    return struct {
        pub fn hash(self: @This(), key: K) u32 {
            _ = self;
            return @truncate(deepHash(key));
        }
        pub fn eql(self: @This(), a: K, b: K, b_index: usize) bool {
            _ = self;
            _ = b_index;
            return deepEql(a, b);
        }
    };
}

pub fn IndexMap(comptime K: type) type {
    return std.ArrayHashMapUnmanaged(K, NidList, DeepContext(K), false);
}

const IndexSpec = struct {
    /// Index into nodeTypes(Root).
    ntype_index: usize,
    name: [:0]const u8,
    decl: IndexDecl,
};

pub fn indexSpecs(comptime Root: type) []const IndexSpec {
    comptime {
        const types = nodeTypes(Root);
        var specs: []const IndexSpec = &.{};
        for (types, 0..) |T, ti| {
            if (@hasDecl(T, "ordb_indexes")) {
                for (std.meta.fields(@TypeOf(T.ordb_indexes))) |f| {
                    specs = specs ++ &[_]IndexSpec{.{
                        .ntype_index = ti,
                        .name = f.name ++ "",
                        .decl = @field(T.ordb_indexes, f.name),
                    }};
                }
            }
        }
        return specs;
    }
}

/// Comptime: global spec index for (T, index name).
pub fn specIndex(comptime Root: type, comptime T: type, comptime name: []const u8) usize {
    const specs = comptime indexSpecs(Root);
    const ti = typeIndex(Root, T);
    inline for (specs, 0..) |spec, i| {
        if (spec.ntype_index == ti and comptime std.mem.eql(u8, spec.name, name)) return i;
    }
    @compileError("No index '" ++ name ++ "' on node type " ++ @typeName(T));
}

/// Key field type for an indexed field: refs are keyed by their (?Nid) value,
/// plain attributes by their own type.
fn keyFieldType(comptime NodeT: type, comptime field_name: []const u8) type {
    const FieldT = @FieldType(NodeT, field_name);
    return switch (attrKind(FieldT)) {
        .plain => FieldT,
        .local_ref, .external_ref => ?Nid,
        .subgraph_ref => ?*FrozenHeader,
    };
}

/// Tuple type of an index key for (NodeT, decl).
pub fn KeyType(comptime NodeT: type, comptime decl: IndexDecl) type {
    comptime var types: [decl.fields.len]type = undefined;
    inline for (decl.fields, 0..) |fname, i| {
        types[i] = keyFieldType(NodeT, fname);
    }
    return std.meta.Tuple(&types);
}

/// Whether key tuple element i is a LocalRef-derived nid (subject to nid
/// translation across merge boundaries). ExternalRef nids live in a foreign
/// nid space and are never translated.
pub fn keyFieldIsLocalNid(comptime NodeT: type, comptime decl: IndexDecl, comptime i: usize) bool {
    return attrKind(@FieldType(NodeT, decl.fields[i])) == .local_ref;
}

fn extractKeyField(comptime NodeT: type, comptime field_name: []const u8, v: NodeT) keyFieldType(NodeT, field_name) {
    const FieldT = @FieldType(NodeT, field_name);
    return switch (comptime attrKind(FieldT)) {
        .plain => @field(v, field_name),
        .local_ref, .external_ref => @field(v, field_name).nid,
        .subgraph_ref => @field(v, field_name).ptr,
    };
}

fn isNullValue(v: anytype) bool {
    return switch (@typeInfo(@TypeOf(v))) {
        .optional => v == null,
        else => false,
    };
}

/// Build the index key of node v for decl, or null if the node is not
/// indexed (single-field index with null value, mirroring Python's
/// Index.index_key returning None).
pub fn makeKey(comptime NodeT: type, comptime decl: IndexDecl, v: NodeT) ?KeyType(NodeT, decl) {
    var key: KeyType(NodeT, decl) = undefined;
    inline for (decl.fields, 0..) |fname, i| {
        key[i] = extractKeyField(NodeT, fname, v);
    }
    if (comptime decl.fields.len == 1) {
        if (isNullValue(key[0])) return null;
    }
    return key;
}

/// Per-generation index storage: by-type nid lists, a LocalRef back-reference
/// map (integrity checking), and one map per declared index.
pub fn IndexStorage(comptime Root: type) type {
    const types = nodeTypes(Root);
    const specs = indexSpecs(Root);
    comptime var map_types: [specs.len]type = undefined;
    inline for (specs, 0..) |spec, i| {
        map_types[i] = IndexMap(KeyType(types[spec.ntype_index], spec.decl));
    }
    const Maps = std.meta.Tuple(&map_types);

    return struct {
        const Self = @This();

        ntype: [types.len]NidList,
        backrefs: std.AutoArrayHashMapUnmanaged(Nid, NidList),
        maps: Maps,

        pub const empty: Self = .{
            .ntype = @splat(.empty),
            .backrefs = .empty,
            .maps = emptyMaps(),
        };

        fn emptyMaps() Maps {
            var m: Maps = undefined;
            inline for (0..specs.len) |i| m[i] = .empty;
            return m;
        }

        pub fn add(self: *Self, alloc: Allocator, comptime T: type, v: T, nid: Nid) Allocator.Error!void {
            try nidListInsert(&self.ntype[comptime typeIndex(Root, T)], alloc, nid);
            inline for (std.meta.fields(T)) |f| {
                if (comptime attrKind(f.type) == .local_ref) {
                    if (@field(v, f.name).nid) |target| {
                        const gop = try self.backrefs.getOrPut(alloc, target);
                        if (!gop.found_existing) gop.value_ptr.* = .empty;
                        try nidListInsert(gop.value_ptr, alloc, nid);
                    }
                }
            }
            inline for (specs, 0..) |spec, si| {
                if (comptime spec.ntype_index == typeIndex(Root, T)) {
                    if (makeKey(T, spec.decl, v)) |key| {
                        const gop = try self.maps[si].getOrPut(alloc, key);
                        if (!gop.found_existing) gop.value_ptr.* = .empty;
                        try nidListInsert(gop.value_ptr, alloc, nid);
                    }
                }
            }
        }

        pub fn remove(self: *Self, comptime T: type, v: T, nid: Nid) void {
            nidListRemove(&self.ntype[comptime typeIndex(Root, T)], nid);
            inline for (std.meta.fields(T)) |f| {
                if (comptime attrKind(f.type) == .local_ref) {
                    if (@field(v, f.name).nid) |target| {
                        nidListRemove(self.backrefs.getPtr(target).?, nid);
                    }
                }
            }
            inline for (specs, 0..) |spec, si| {
                if (comptime spec.ntype_index == typeIndex(Root, T)) {
                    if (makeKey(T, spec.decl, v)) |key| {
                        nidListRemove(self.maps[si].getPtr(key).?, nid);
                    }
                }
            }
        }

        pub fn addNode(self: *Self, alloc: Allocator, node: NodeUnion(Root), nid: Nid) Allocator.Error!void {
            switch (node) {
                inline else => |v| try self.add(alloc, @TypeOf(v), v, nid),
            }
        }

        pub fn removeNode(self: *Self, node: NodeUnion(Root), nid: Nid) void {
            switch (node) {
                inline else => |v| self.remove(@TypeOf(v), v, nid),
            }
        }

        pub fn ntypeList(self: *const Self, comptime T: type) []const Nid {
            return self.ntype[comptime typeIndex(Root, T)].items;
        }

        pub fn backrefList(self: *const Self, target: Nid) []const Nid {
            const list = self.backrefs.getPtr(target) orelse return &.{};
            return list.items;
        }

        pub fn lookupSpec(self: *const Self, comptime si: usize, key: anytype) []const Nid {
            const list = self.maps[si].getPtr(key) orelse return &.{};
            return list.items;
        }
    };
}

// Tests with a small standalone schema (independent of schema.zig)
// ----------------------------------------------------------------

const TestHead = struct {
    caption: ?Str = null,
    pub const ordb_nodes = .{TestItem};
};

const TestItem = struct {
    parent: LocalRef(.{TestItem}, .{}) = .none,
    weight: ?i32 = null,
    label: ?Str = null,

    pub const ordb_required_fields = .{"weight"};
    pub const ordb_indexes = .{
        .parent_idx = idx(&.{"parent"}, .{}),
        .weight_idx = idx(&.{"weight"}, .{ .unique = true }),
    };
};

test "typeBaseName" {
    try std.testing.expectEqualStrings("TestItem", typeBaseName(TestItem));
    try std.testing.expectEqualStrings("NPath", typeBaseName(NPath));
}

test "NodeUnion construction" {
    const U = NodeUnion(TestHead);
    const Tag = std.meta.Tag(U);
    try std.testing.expectEqual(3, std.meta.fields(U).len);
    const u: U = .{ .TestItem = .{ .weight = 42 } };
    try std.testing.expectEqual(Tag.TestItem, std.meta.activeTag(u));
    try std.testing.expectEqual(Tag.TestHead, tagFor(TestHead, TestHead));
    try std.testing.expectEqual(Tag.NPath, tagFor(TestHead, NPath));
}

test "isRequired" {
    try std.testing.expect(isRequired(TestItem, "weight"));
    try std.testing.expect(!isRequired(TestItem, "label"));
    try std.testing.expect(!isRequired(TestItem, "parent"));
    try std.testing.expect(isRequired(NPath, "name"));
}

test "deepEql and deepHash" {
    const a: TestItem = .{ .weight = 1, .label = "hello" };
    const b: TestItem = .{ .weight = 1, .label = "hello" };
    const c: TestItem = .{ .weight = 1, .label = "world" };
    try std.testing.expect(deepEql(a, b));
    try std.testing.expect(!deepEql(a, c));
    try std.testing.expectEqual(deepHash(a), deepHash(b));

    const n1 = Name.str("foo");
    const n2 = Name.str("foo");
    const n3 = Name.int(3);
    try std.testing.expect(deepEql(n1, n2));
    try std.testing.expect(!deepEql(n1, n3));
}

test "translateLocalRefs" {
    const v: TestItem = .{ .parent = .to(@as(Nid, 5)), .weight = 1 };
    const t = translateLocalRefs(TestItem, v, 100);
    try std.testing.expectEqual(@as(?Nid, 105), t.parent.nid);
    // nid 0 (root) is never translated:
    const r: TestItem = .{ .parent = .to(@as(Nid, 0)), .weight = 1 };
    const tr = translateLocalRefs(TestItem, r, 100);
    try std.testing.expectEqual(@as(?Nid, 0), tr.parent.nid);
}

test "IndexStorage add/remove/lookup" {
    const gpa = std.testing.allocator;
    var arena_state = std.heap.ArenaAllocator.init(gpa);
    defer arena_state.deinit();
    const arena = arena_state.allocator();

    var storage: IndexStorage(TestHead) = .empty;
    const item1: TestItem = .{ .parent = .to(@as(Nid, 0)), .weight = 10 };
    const item2: TestItem = .{ .parent = .to(@as(Nid, 0)), .weight = 20 };
    try storage.add(arena, TestItem, item1, 1);
    try storage.add(arena, TestItem, item2, 2);

    try std.testing.expectEqualSlices(Nid, &.{ 1, 2 }, storage.ntypeList(TestItem));
    try std.testing.expectEqualSlices(Nid, &.{ 1, 2 }, storage.backrefList(0));

    const si = comptime specIndex(TestHead, TestItem, "parent_idx");
    const key: KeyType(TestItem, TestItem.ordb_indexes.parent_idx) = .{@as(?Nid, 0)};
    try std.testing.expectEqualSlices(Nid, &.{ 1, 2 }, storage.lookupSpec(si, key));

    const wi = comptime specIndex(TestHead, TestItem, "weight_idx");
    const wkey: KeyType(TestItem, TestItem.ordb_indexes.weight_idx) = .{@as(?i32, 10)};
    try std.testing.expectEqualSlices(Nid, &.{1}, storage.lookupSpec(wi, wkey));

    storage.remove(TestItem, item1, 1);
    try std.testing.expectEqualSlices(Nid, &.{2}, storage.ntypeList(TestItem));
    try std.testing.expectEqualSlices(Nid, &.{2}, storage.backrefList(0));
    try std.testing.expectEqualSlices(Nid, &.{}, storage.lookupSpec(wi, wkey));
}

test "makeKey null skip for single-field index" {
    const unparented: TestItem = .{ .weight = 10 };
    const decl = TestItem.ordb_indexes.parent_idx;
    try std.testing.expectEqual(null, makeKey(TestItem, decl, unparented));
    const parented: TestItem = .{ .parent = .to(@as(Nid, 3)), .weight = 10 };
    try std.testing.expect(makeKey(TestItem, decl, parented) != null);
}

test "dupeStrings" {
    const gpa = std.testing.allocator;
    var arena_state = std.heap.ArenaAllocator.init(gpa);
    defer arena_state.deinit();

    var buf: [5]u8 = .{ 'h', 'e', 'l', 'l', 'o' };
    const v: TestItem = .{ .weight = 1, .label = &buf };
    const duped = try dupeStrings(TestItem, v, arena_state.allocator());
    buf[0] = 'X';
    try std.testing.expectEqualStrings("hello", duped.label.?);
}
