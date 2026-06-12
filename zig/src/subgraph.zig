// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Subgraph core: delta-chain persistence, transactions, queries, cursors.
//!
//! A subgraph generation is either Mutable or Frozen. Both hold only a
//! *delta* (nodes added/modified/tombstoned in this generation) plus
//! references to frozen parent generations. Reads walk the chain newest to
//! oldest; nids present in a newer delta shadow older generations.
//!
//! freeze() and thaw() are O(1). Multi-parent thaw merges several frozen
//! subgraphs: each parent is assigned an nid base offset in the child's nid
//! space, and LocalRef nids are translated when nodes are materialized
//! through a merge boundary (nid 0, the root, always maps to 0).
//!
//! Mutations run in transactions (Txn). Constraint checks are deferred to
//! commit(), mirroring Python's SubgraphUpdater: a failed commit rolls back
//! and leaves the subgraph (including indexes) untouched.

const std = @import("std");
const Allocator = std.mem.Allocator;
const meta = @import("meta.zig");

pub const Nid = meta.Nid;
pub const Str = meta.Str;
pub const Name = meta.Name;
pub const NPath = meta.NPath;
pub const FrozenHeader = meta.FrozenHeader;

/// Carries details about a failed constraint check (Zig errors have no
/// payload). Pass to Txn.commit() and inspect on error.
pub const Diag = struct {
    nid: Nid = 0,
    node_type: []const u8 = "",
    field: []const u8 = "",
    index: []const u8 = "",
    other_nid: Nid = 0,
};

pub const CommitError = error{
    MissingRoot,
    MissingAttr,
    UniqueViolation,
    PathExists,
    DanglingLocalRef,
    DanglingExternalRef,
    ExternalRefUnresolvable,
    RefTypeMismatch,
    RemovedStillReferenced,
} || Allocator.Error;

pub const QueryError = error{ NotFound, NotUnique } || Allocator.Error;

pub const Error = CommitError || QueryError || error{
    DuplicateNid,
    RootRemoval,
    Frozen,
    InvalidName,
    PathNotFound,
    NoNPath,
    RootConflict,
    WrongNodeType,
    NidExhausted,
};

fn attrIsNull(v: anytype) bool {
    const T = @TypeOf(v);
    return switch (comptime meta.attrKind(T)) {
        .plain => switch (@typeInfo(T)) {
            .optional => v == null,
            else => false,
        },
        .local_ref, .external_ref => v.nid == null,
        .subgraph_ref => v.ptr == null,
    };
}

/// Coerce a string or integer into a Name.
pub fn coerceName(name: anytype) Name {
    const T = @TypeOf(name);
    if (T == Name) return name;
    return switch (@typeInfo(T)) {
        .int, .comptime_int => .{ .i = name },
        else => .{ .s = name },
    };
}

pub fn Subgraph(comptime Root: type) type {
    return struct {
        pub const Node = meta.NodeUnion(Root);
        pub const Tag = std.meta.Tag(Node);
        pub const Index = meta.IndexStorage(Root);
        pub const root_type_name = meta.typeBaseName(Root);
        const node_types = meta.nodeTypes(Root);
        const index_specs = meta.indexSpecs(Root);
        const SG = @This();

        pub const Entry = union(enum) {
            node: Node,
            tombstone,
        };

        pub const Parent = struct { frozen: *Frozen, offset: Nid };

        const NodeMap = std.AutoArrayHashMapUnmanaged(Nid, Entry);

        // Generation types
        // ----------------

        pub const Frozen = struct {
            pub const Owner = SG;

            header: FrozenHeader, // must be the first field (@fieldParentPtr)
            gpa: Allocator,
            arena: std.heap.ArenaAllocator,
            parents: []Parent,
            nodes: NodeMap,
            index: Index,
            nid_end: Nid,

            const vtable: FrozenHeader.VTable = .{
                .destroy = destroyErased,
            };

            fn destroyErased(h: *FrozenHeader) void {
                const self: *Frozen = @alignCast(@fieldParentPtr("header", h));
                for (self.parents) |p| p.frozen.header.release();
                var it = self.nodes.iterator();
                while (it.next()) |kv| switch (kv.value_ptr.*) {
                    .node => |n| releaseNodeSubgraphRefs(n),
                    .tombstone => {},
                };
                const gpa = self.gpa;
                self.arena.deinit();
                gpa.destroy(self);
            }

            /// Content equality: two frozen subgraphs are equal iff their
            /// content hashes are (independent of freeze/thaw history).
            pub fn eqlContent(a: *Frozen, b: *Frozen) bool {
                return std.mem.eql(u8, &a.header.hash, &b.header.hash);
            }

            pub fn retain(self: *Frozen) *Frozen {
                _ = self.header.retain();
                return self;
            }

            pub fn release(self: *Frozen) void {
                self.header.release();
            }

            pub fn view(self: *Frozen) View {
                return .{ .frozen = self };
            }

            pub fn root(self: *Frozen) Cursor(Root) {
                return .{ .view = self.view(), .nid = 0 };
            }

            /// O(1) continuation of this frozen subgraph (single parent).
            pub fn thaw(self: *Frozen) Error!Mutable {
                return thawMulti(self.gpa, &.{self});
            }

            /// From a header pointer (e.g. out of a SubgraphRef), get the
            /// typed Frozen. Checks the root type tag.
            pub fn fromHeader(h: *FrozenHeader) error{WrongNodeType}!*Frozen {
                if (!std.mem.eql(u8, h.root_type, root_type_name)) return error.WrongNodeType;
                return @alignCast(@fieldParentPtr("header", h));
            }

            /// Flatten the whole parent chain into a fresh single-generation
            /// Frozen with identical nids and content.
            pub fn compact(self: *Frozen) Error!*Frozen {
                var m = Mutable.initEmpty(self.gpa);
                errdefer m.deinit();
                var nids: std.ArrayList(Nid) = .empty;
                defer nids.deinit(self.gpa);
                try collectAllNidsG(self, self.gpa, &nids);
                std.mem.sort(Nid, nids.items, {}, std.sort.asc(Nid));

                var txn = m.txn();
                errdefer txn.abort();
                for (nids.items) |nid| {
                    const node = getNodeG(self, nid).?;
                    switch (node) {
                        inline else => |v| try txn.insertAtTyped(@TypeOf(v), nid, v),
                    }
                }
                try txn.commit(null);
                m.nid_next = self.nid_end;
                return m.freeze();
            }
        };

        pub const Mutable = struct {
            pub const Owner = SG;

            gpa: Allocator,
            arena: std.heap.ArenaAllocator,
            parents: []Parent,
            nodes: NodeMap,
            index: Index,
            nid_next: Nid,
            base_nid_end: Nid,
            consumed: bool = false,

            fn initEmpty(gpa: Allocator) Mutable {
                return .{
                    .gpa = gpa,
                    .arena = std.heap.ArenaAllocator.init(gpa),
                    .parents = &.{},
                    .nodes = .empty,
                    .index = .empty,
                    .nid_next = 0,
                    .base_nid_end = 0,
                };
            }

            /// Create a new subgraph whose root node (nid 0) is root_value.
            pub fn init(gpa: Allocator, root_value: Root) Error!Mutable {
                var m = initEmpty(gpa);
                errdefer m.deinit();
                var t = m.txn();
                errdefer t.abort();
                try t.insertAtTyped(Root, 0, root_value);
                try t.commit(null);
                return m;
            }

            pub fn deinit(self: *Mutable) void {
                if (self.consumed) return;
                self.consumed = true;
                for (self.parents) |p| p.frozen.header.release();
                var it = self.nodes.iterator();
                while (it.next()) |kv| switch (kv.value_ptr.*) {
                    .node => |n| releaseNodeSubgraphRefs(n),
                    .tombstone => {},
                };
                self.arena.deinit();
            }

            /// Consumes the Mutable. O(delta) for the move, plus O(merged
            /// view) for the content hash computation.
            pub fn freeze(self: *Mutable) Allocator.Error!*Frozen {
                std.debug.assert(!self.consumed);
                const f = try self.gpa.create(Frozen);
                f.* = .{
                    .header = .{ .root_type = root_type_name, .vtable = &Frozen.vtable },
                    .gpa = self.gpa,
                    .arena = self.arena,
                    .parents = self.parents,
                    .nodes = self.nodes,
                    .index = self.index,
                    .nid_end = self.nid_next,
                };
                self.consumed = true;
                errdefer Frozen.destroyErased(&f.header);
                try finalizeHash(f);
                return f;
            }

            pub fn view(self: *Mutable) View {
                return .{ .mutable = self };
            }

            pub fn root(self: *Mutable) Cursor(Root) {
                return .{ .view = self.view(), .nid = 0 };
            }

            pub fn txn(self: *Mutable) Txn {
                return .{ .m = self, .saved_nid_next = self.nid_next };
            }

            /// Single-operation transaction: insert one node.
            pub fn insert(self: *Mutable, node: anytype) Error!Cursor(@TypeOf(node)) {
                var t = self.txn();
                errdefer t.abort();
                const c = try t.insert(node);
                try t.commit(null);
                return c;
            }

            /// Single-operation transaction: insert node and name it below the root.
            pub fn put(self: *Mutable, name: anytype, node: anytype) Error!Cursor(@TypeOf(node)) {
                return self.root().put(name, node);
            }
        };

        // Multi-parent thaw (merge)
        // -------------------------

        /// Create a Mutable over one or more frozen parents. Parent i is
        /// assigned the nid offset sum(nid_end of parents 0..i-1); parent 0
        /// has offset 0. With multiple parents, parent 0's root becomes the
        /// merged root; a later parent whose root has a non-null attribute
        /// differing from parent 0's root is an error (strict policy), and a
        /// full unique-index sweep over the merged view runs (so a merge can
        /// never silently violate declared constraints).
        pub fn thawMulti(gpa: Allocator, parents_in: []const *Frozen) (Error)!Mutable {
            std.debug.assert(parents_in.len >= 1);
            var m = Mutable.initEmpty(gpa);
            errdefer m.deinit();

            const parents = try m.arena.allocator().alloc(Parent, parents_in.len);
            var offset: Nid = 0;
            for (parents_in, 0..) |p, i| {
                parents[i] = .{ .frozen = p.retain(), .offset = offset };
                offset = std.math.add(Nid, offset, p.nid_end) catch return error.NidExhausted;
            }
            m.parents = parents;
            m.nid_next = offset;
            m.base_nid_end = offset;

            if (parents_in.len > 1) {
                try checkRootConflicts(parents_in);
                // Parent 0's root becomes the merged root, written explicitly
                // into the delta so it shadows all parents' roots.
                const root_value = getNodeAsG(parents_in[0], Root, 0).?;
                var t = m.txn();
                errdefer t.abort();
                try t.updateTyped(Root, 0, root_value);
                try t.commit(null);
                try sweepUniqueIndexes(&m);
            }
            return m;
        }

        fn checkRootConflicts(parents_in: []const *Frozen) error{RootConflict}!void {
            const root0 = getNodeAsG(parents_in[0], Root, 0).?;
            for (parents_in[1..]) |p| {
                const ri = getNodeAsG(p, Root, 0).?;
                inline for (std.meta.fields(Root)) |f| {
                    const vi = @field(ri, f.name);
                    if (!attrIsNull(vi)) {
                        if (!meta.deepEql(vi, @field(root0, f.name))) return error.RootConflict;
                    }
                }
            }
        }

        /// Cross-parent unique constraint sweep over the merged view.
        fn sweepUniqueIndexes(m: *Mutable) Error!void {
            const gpa = m.gpa;
            inline for (index_specs, 0..) |spec, si| {
                if (spec.decl.unique) {
                    const T = node_types[spec.ntype_index];
                    const Key = meta.KeyType(T, spec.decl);
                    var seen = std.ArrayHashMapUnmanaged(Key, Nid, meta.DeepContext(Key), false).empty;
                    defer seen.deinit(gpa);
                    var nids: std.ArrayList(Nid) = .empty;
                    defer nids.deinit(gpa);
                    try collectByTypeG(m, T, gpa, &nids);
                    for (nids.items) |nid| {
                        const v = getNodeAsG(m, T, nid).?;
                        if (meta.makeKey(T, spec.decl, v)) |key| {
                            const gop = try seen.getOrPut(gpa, key);
                            if (gop.found_existing) {
                                return if (comptime isNPathNameIndex(si)) error.PathExists else error.UniqueViolation;
                            }
                            gop.value_ptr.* = nid;
                        }
                    }
                }
            }
        }

        fn isNPathNameIndex(comptime si: usize) bool {
            const spec = index_specs[si];
            return node_types[spec.ntype_index] == NPath and
                std.mem.eql(u8, spec.name, "idx_parent_name");
        }

        // Generic read machinery (g: *Mutable or *Frozen)
        // ------------------------------------------------

        fn translateNode(node: Node, offset: Nid) Node {
            if (offset == 0) return node;
            switch (node) {
                inline else => |v, tag| {
                    return @unionInit(Node, @tagName(tag), meta.translateLocalRefs(@TypeOf(v), v, offset));
                },
            }
        }

        pub fn getNodeG(g: anytype, nid: Nid) ?Node {
            if (g.nodes.get(nid)) |e| {
                return switch (e) {
                    .node => |n| n,
                    .tombstone => null,
                };
            }
            for (g.parents) |p| {
                if (nid >= p.offset and nid - p.offset < p.frozen.nid_end) {
                    const pnid = nid - p.offset;
                    // The roots of parents 1.. are shadowed by the merged root:
                    if (pnid == 0 and p.offset != 0) return null;
                    const pnode = getNodeG(p.frozen, pnid) orelse return null;
                    return translateNode(pnode, p.offset);
                }
            }
            return null;
        }

        pub fn getNodeAsG(g: anytype, comptime T: type, nid: Nid) ?T {
            const n = getNodeG(g, nid) orelse return null;
            if (std.meta.activeTag(n) != comptime meta.tagFor(Root, T)) return null;
            return @field(n, meta.typeBaseName(T));
        }

        fn collectByTypeG(g: anytype, comptime T: type, alloc: Allocator, out: *std.ArrayList(Nid)) Allocator.Error!void {
            for (g.index.ntypeList(T)) |nid| try out.append(alloc, nid);
            try collectFromParents(g, alloc, out, struct {
                fn rec(p: *Frozen, a: Allocator, o: *std.ArrayList(Nid)) Allocator.Error!void {
                    try collectByTypeG(p, T, a, o);
                }
            }.rec);
        }

        /// Shared parent-walk: run `rec` on each parent, translate the
        /// resulting nids into this generation's space, drop parent-root
        /// holes, and filter out nids shadowed by this generation's delta.
        fn collectFromParents(
            g: anytype,
            alloc: Allocator,
            out: *std.ArrayList(Nid),
            rec: anytype,
        ) Allocator.Error!void {
            for (g.parents) |p| {
                var tmp: std.ArrayList(Nid) = .empty;
                defer tmp.deinit(alloc);
                try rec(p.frozen, alloc, &tmp);
                for (tmp.items) |pnid| {
                    if (pnid == 0 and p.offset != 0) continue;
                    const cnid = pnid + p.offset;
                    if (g.nodes.contains(cnid)) continue;
                    try out.append(alloc, cnid);
                }
            }
        }

        /// Translate an index key from this generation's nid space into
        /// parent p's space, or null if no node of p can match the key.
        fn translateKeyToParent(
            comptime T: type,
            comptime decl: meta.IndexDecl,
            key: meta.KeyType(T, decl),
            p: Parent,
        ) ?meta.KeyType(T, decl) {
            var pkey = key;
            inline for (0..decl.fields.len) |i| {
                if (comptime meta.keyFieldIsLocalNid(T, decl, i)) {
                    if (key[i]) |knid| {
                        if (knid == 0) {
                            // root maps to root
                        } else if (knid > p.offset and knid - p.offset < p.frozen.nid_end) {
                            pkey[i] = knid - p.offset;
                        } else {
                            return null;
                        }
                    }
                }
            }
            return pkey;
        }

        fn lookupIndexG(
            g: anytype,
            comptime T: type,
            comptime si: usize,
            key: meta.KeyType(T, index_specs[si].decl),
            alloc: Allocator,
            out: *std.ArrayList(Nid),
        ) Allocator.Error!void {
            const decl = comptime index_specs[si].decl;
            for (g.index.lookupSpec(si, key)) |nid| try out.append(alloc, nid);
            for (g.parents) |p| {
                const pkey = translateKeyToParent(T, decl, key, p) orelse continue;
                var tmp: std.ArrayList(Nid) = .empty;
                defer tmp.deinit(alloc);
                try lookupIndexG(p.frozen, T, si, pkey, alloc, &tmp);
                for (tmp.items) |pnid| {
                    if (pnid == 0 and p.offset != 0) continue;
                    const cnid = pnid + p.offset;
                    if (g.nodes.contains(cnid)) continue;
                    try out.append(alloc, cnid);
                }
            }
        }

        fn collectBackrefsG(g: anytype, target: Nid, alloc: Allocator, out: *std.ArrayList(Nid)) Allocator.Error!void {
            for (g.index.backrefList(target)) |nid| try out.append(alloc, nid);
            for (g.parents) |p| {
                const ptarget = blk: {
                    if (target == 0) break :blk @as(Nid, 0);
                    if (target > p.offset and target - p.offset < p.frozen.nid_end)
                        break :blk target - p.offset;
                    continue;
                };
                var tmp: std.ArrayList(Nid) = .empty;
                defer tmp.deinit(alloc);
                try collectBackrefsG(p.frozen, ptarget, alloc, &tmp);
                for (tmp.items) |pnid| {
                    if (pnid == 0 and p.offset != 0) continue;
                    const cnid = pnid + p.offset;
                    if (g.nodes.contains(cnid)) continue;
                    try out.append(alloc, cnid);
                }
            }
        }

        fn collectAllNidsG(g: anytype, alloc: Allocator, out: *std.ArrayList(Nid)) Allocator.Error!void {
            var it = g.nodes.iterator();
            while (it.next()) |kv| {
                switch (kv.value_ptr.*) {
                    .node => try out.append(alloc, kv.key_ptr.*),
                    .tombstone => {},
                }
            }
            try collectFromParents(g, alloc, out, struct {
                fn rec(p: *Frozen, a: Allocator, o: *std.ArrayList(Nid)) Allocator.Error!void {
                    try collectAllNidsG(p, a, o);
                }
            }.rec);
        }

        fn releaseNodeSubgraphRefs(node: Node) void {
            switch (node) {
                inline else => |v| meta.releaseSubgraphRefs(@TypeOf(v), v),
            }
        }

        // View: shared read interface over Mutable and Frozen
        // ----------------------------------------------------

        pub const View = union(enum) {
            mutable: *Mutable,
            frozen: *Frozen,

            pub fn gpa(self: View) Allocator {
                return switch (self) {
                    inline else => |g| g.gpa,
                };
            }

            pub fn getNode(self: View, nid: Nid) ?Node {
                return switch (self) {
                    inline else => |g| getNodeG(g, nid),
                };
            }

            pub fn getNodeAs(self: View, comptime T: type, nid: Nid) ?T {
                return switch (self) {
                    inline else => |g| getNodeAsG(g, T, nid),
                };
            }

            pub fn rootValue(self: View) Root {
                return self.getNodeAs(Root, 0).?;
            }

            pub fn root(self: View) Cursor(Root) {
                return .{ .view = self, .nid = 0 };
            }

            pub fn cursorAt(self: View, comptime T: type, nid: Nid) error{WrongNodeType}!Cursor(T) {
                if (self.getNodeAs(T, nid) == null) return error.WrongNodeType;
                return .{ .view = self, .nid = nid };
            }

            /// All nids of the merged view, ascending.
            pub fn allNids(self: View, alloc: Allocator) Allocator.Error![]Nid {
                var out: std.ArrayList(Nid) = .empty;
                errdefer out.deinit(alloc);
                switch (self) {
                    inline else => |g| try collectAllNidsG(g, alloc, &out),
                }
                std.mem.sort(Nid, out.items, {}, std.sort.asc(Nid));
                return out.toOwnedSlice(alloc);
            }

            /// All nodes of type T, as cursors sorted by nid. Caller frees.
            pub fn all(self: View, comptime T: type, alloc: Allocator) Allocator.Error![]Cursor(T) {
                var nids: std.ArrayList(Nid) = .empty;
                defer nids.deinit(alloc);
                switch (self) {
                    inline else => |g| try collectByTypeG(g, T, alloc, &nids),
                }
                std.mem.sort(Nid, nids.items, {}, std.sort.asc(Nid));
                const out = try alloc.alloc(Cursor(T), nids.items.len);
                for (nids.items, 0..) |nid, i| out[i] = .{ .view = self, .nid = nid };
                return out;
            }

            /// The single node of type T; error if zero or several exist.
            pub fn one(self: View, comptime T: type, alloc: Allocator) QueryError!Cursor(T) {
                const items = try self.all(T, alloc);
                defer alloc.free(items);
                if (items.len == 0) return error.NotFound;
                if (items.len > 1) return error.NotUnique;
                return items[0];
            }

            /// Query a declared index of node type T by key. Results are
            /// sorted by the index's sort_by field if declared, else by nid.
            /// Caller frees.
            pub fn allBy(
                self: View,
                comptime T: type,
                comptime index_name: []const u8,
                key: anytype,
                alloc: Allocator,
            ) Allocator.Error![]Cursor(T) {
                const si = comptime meta.specIndex(Root, T, index_name);
                const decl = comptime index_specs[si].decl;
                const k: meta.KeyType(T, decl) = key;
                var nids: std.ArrayList(Nid) = .empty;
                defer nids.deinit(alloc);
                switch (self) {
                    inline else => |g| try lookupIndexG(g, T, si, k, alloc, &nids),
                }
                std.mem.sort(Nid, nids.items, {}, std.sort.asc(Nid));
                const out = try alloc.alloc(Cursor(T), nids.items.len);
                for (nids.items, 0..) |nid, i| out[i] = .{ .view = self, .nid = nid };
                if (comptime decl.sort_by) |sort_field| {
                    const Ctx = struct {
                        view: View,
                        fn lessThan(ctx: @This(), a: Cursor(T), b: Cursor(T)) bool {
                            _ = ctx;
                            const fa = @field(a.get(), sort_field);
                            const fb = @field(b.get(), sort_field);
                            return sortKeyLess(fa, fb);
                        }
                    };
                    std.mem.sort(Cursor(T), out, Ctx{ .view = self }, Ctx.lessThan);
                }
                return out;
            }

            pub fn oneBy(
                self: View,
                comptime T: type,
                comptime index_name: []const u8,
                key: anytype,
                alloc: Allocator,
            ) QueryError!Cursor(T) {
                const items = try self.allBy(T, index_name, key, alloc);
                defer alloc.free(items);
                if (items.len == 0) return error.NotFound;
                if (items.len > 1) return error.NotUnique;
                return items[0];
            }

            /// Nids of nodes referencing `target` via LocalRef attributes.
            pub fn backrefs(self: View, target: Nid, alloc: Allocator) Allocator.Error![]Nid {
                var out: std.ArrayList(Nid) = .empty;
                errdefer out.deinit(alloc);
                switch (self) {
                    inline else => |g| try collectBackrefsG(g, target, alloc, &out),
                }
                return out.toOwnedSlice(alloc);
            }

            pub fn npathNidOf(self: View, nid: Nid, alloc: Allocator) Allocator.Error!?Nid {
                if (nid == 0) return null;
                const c = self.oneBy(NPath, "idx_path_of", .{@as(?Nid, nid)}, alloc) catch |err| switch (err) {
                    error.NotFound, error.NotUnique => return null,
                    error.OutOfMemory => |e| return e,
                };
                return c.nid;
            }
        };

        fn sortKeyLess(a: anytype, b: @TypeOf(a)) bool {
            const T = @TypeOf(a);
            switch (@typeInfo(T)) {
                .optional => {
                    if (a == null) return b != null;
                    if (b == null) return false;
                    return sortKeyLess(a.?, b.?);
                },
                .int => return a < b,
                else => @compileError("sort_by field must be an integer type, got " ++ @typeName(T)),
            }
        }

        // Cursors
        // -------

        pub fn Cursor(comptime T: type) type {
            comptime _ = meta.typeIndex(Root, T); // membership check
            return struct {
                view: View,
                nid: Nid,

                const C = @This();
                pub const NodeType = T;

                /// Materialized node value (a copy; refs translated).
                pub fn get(self: C) T {
                    return self.view.getNodeAs(T, self.nid) orelse
                        std.debug.panic("stale cursor: nid {d} is not a live {s}", .{ self.nid, meta.typeBaseName(T) });
                }

                pub fn field(self: C, comptime f: std.meta.FieldEnum(T)) @FieldType(T, @tagName(f)) {
                    return @field(self.get(), @tagName(f));
                }

                fn mutable(self: C) error{Frozen}!*Mutable {
                    return switch (self.view) {
                        .mutable => |m| m,
                        .frozen => error.Frozen,
                    };
                }

                /// Set a single attribute (one-operation transaction).
                pub fn set(
                    self: C,
                    comptime f: std.meta.FieldEnum(T),
                    value: @FieldType(T, @tagName(f)),
                ) Error!void {
                    var v = self.get();
                    @field(v, @tagName(f)) = value;
                    try self.update(v);
                }

                /// Replace the whole node value (one-operation transaction).
                pub fn update(self: C, v: T) Error!void {
                    const m = try self.mutable();
                    var t = m.txn();
                    errdefer t.abort();
                    try t.updateTyped(T, self.nid, v);
                    try t.commit(null);
                }

                /// Follow a LocalRef attribute. For single-target refs the
                /// result is a typed cursor; multi-target refs yield AnyCursor.
                pub fn deref(self: C, comptime f: std.meta.FieldEnum(T)) Error!DerefType(T, f) {
                    const FieldT = @FieldType(T, @tagName(f));
                    const nid = @field(self.get(), @tagName(f)).nid orelse return error.NotFound;
                    if (comptime FieldT.ordb_targets.len == 1) {
                        return self.view.cursorAt(FieldT.ordb_targets[0], nid) catch return error.WrongNodeType;
                    } else {
                        return AnyCursor{ .view = self.view, .nid = nid, .npath_nid = null };
                    }
                }

                /// Follow an ExternalRef attribute into the referenced frozen
                /// subgraph, yielding a cursor of that subgraph.
                pub fn derefExternal(
                    self: C,
                    comptime f: std.meta.FieldEnum(T),
                ) Error!ExtCursorType(T, f) {
                    const FieldT = @FieldType(T, @tagName(f));
                    const FSG = Subgraph(FieldT.ordb_foreign_root);
                    const ref_nid = @field(self.get(), @tagName(f)).nid orelse return error.NotFound;
                    const header = FieldT.ordb_of(self.view, self.nid) orelse return error.ExternalRefUnresolvable;
                    const foreign = FSG.Frozen.fromHeader(header) catch return error.RefTypeMismatch;
                    if (comptime FieldT.ordb_targets.len == 1) {
                        return foreign.view().cursorAt(FieldT.ordb_targets[0], ref_nid) catch return error.WrongNodeType;
                    } else {
                        return FSG.AnyCursor{ .view = foreign.view(), .nid = ref_nid, .npath_nid = null };
                    }
                }

                /// Resolve a SubgraphRef attribute to the typed frozen subgraph.
                pub fn derefSubgraph(
                    self: C,
                    comptime f: std.meta.FieldEnum(T),
                ) Error!*Subgraph(@FieldType(T, @tagName(f)).ordb_root).Frozen {
                    const FieldT = @FieldType(T, @tagName(f));
                    const h = @field(self.get(), @tagName(f)).ptr orelse return error.NotFound;
                    return Subgraph(FieldT.ordb_root).Frozen.fromHeader(h) catch return error.RefTypeMismatch;
                }

                /// Remove this node (and its NPath, if any).
                pub fn remove(self: C) Error!void {
                    const m = try self.mutable();
                    var t = m.txn();
                    errdefer t.abort();
                    if (try self.view.npathNidOf(self.nid, m.gpa)) |np| try t.removeNid(np);
                    try t.removeNid(self.nid);
                    try t.commit(null);
                }

                // NPath hierarchy operations
                // --------------------------

                fn ownNpathNid(self: C, alloc: Allocator) Error!?Nid {
                    if (self.nid == 0) return null; // root: NPath parent = none
                    return (try self.view.npathNidOf(self.nid, alloc)) orelse error.NoNPath;
                }

                /// Insert node and register it at name below this node.
                pub fn put(self: C, name: anytype, node: anytype) Error!Cursor(@TypeOf(node)) {
                    return putBelow(self.view, try self.ownNpathNid(self.view.gpa()), name, node);
                }

                /// Create an empty path (Python: x.name = PathNode()).
                pub fn putPath(self: C, name: anytype) Error!AnyCursor {
                    return putPathBelow(self.view, try self.ownNpathNid(self.view.gpa()), name);
                }

                /// Look up a named child.
                pub fn at(self: C, name: anytype) Error!AnyCursor {
                    const alloc = self.view.gpa();
                    const parent_np = try self.ownNpathNid(alloc);
                    return atNpath(self.view, parent_np, coerceName(name), alloc);
                }

                /// Direct children in the NPath hierarchy. Caller frees.
                pub fn children(self: C, alloc: Allocator) Error![]AnyCursor {
                    const parent_np = try self.ownNpathNid(alloc);
                    return childrenOfNpath(self.view, parent_np, alloc);
                }

                /// Hierarchical path, e.g. "I0.sub[0]". Caller frees.
                pub fn fullPathStr(self: C, alloc: Allocator) Error![]u8 {
                    const np = try self.ownNpathNid(alloc);
                    return npathString(self.view, np, alloc);
                }
            };
        }

        fn DerefType(comptime T: type, comptime f: std.meta.FieldEnum(T)) type {
            const FieldT = @FieldType(T, @tagName(f));
            return if (FieldT.ordb_targets.len == 1) Cursor(FieldT.ordb_targets[0]) else AnyCursor;
        }

        fn ExtCursorType(comptime T: type, comptime f: std.meta.FieldEnum(T)) type {
            const FieldT = @FieldType(T, @tagName(f));
            const FSG = Subgraph(FieldT.ordb_foreign_root);
            return if (FieldT.ordb_targets.len == 1) FSG.Cursor(FieldT.ordb_targets[0]) else FSG.AnyCursor;
        }

        /// Cursor to a node of statically unknown type, or to an empty path
        /// (nid == null, npath_nid set).
        pub const AnyCursor = struct {
            view: View,
            nid: ?Nid,
            npath_nid: ?Nid,

            pub fn as(self: AnyCursor, comptime T: type) error{WrongNodeType}!Cursor(T) {
                const nid = self.nid orelse return error.WrongNodeType;
                return self.view.cursorAt(T, nid);
            }

            pub fn tag(self: AnyCursor) ?Tag {
                const nid = self.nid orelse return null;
                const n = self.view.getNode(nid) orelse return null;
                return std.meta.activeTag(n);
            }

            pub fn at(self: AnyCursor, name: anytype) Error!AnyCursor {
                return atNpath(self.view, self.npath_nid, coerceName(name), self.view.gpa());
            }

            pub fn children(self: AnyCursor, alloc: Allocator) Error![]AnyCursor {
                return childrenOfNpath(self.view, self.npath_nid, alloc);
            }

            pub fn fullPathStr(self: AnyCursor, alloc: Allocator) Error![]u8 {
                return npathString(self.view, self.npath_nid, alloc);
            }

            /// Insert node and register it at name below this path/node.
            pub fn put(self: AnyCursor, name: anytype, node: anytype) Error!Cursor(@TypeOf(node)) {
                return putBelow(self.view, self.npath_nid, name, node);
            }

            /// Create an empty path below this path/node.
            pub fn putPath(self: AnyCursor, name: anytype) Error!AnyCursor {
                return putPathBelow(self.view, self.npath_nid, name);
            }

            /// Navigate to the parent in the NPath hierarchy. The parent of
            /// a top-level entry is the subgraph root.
            pub fn parent(self: AnyCursor) Error!AnyCursor {
                const own_np = self.npath_nid orelse return error.NoNPath;
                const np = self.view.getNodeAs(NPath, own_np) orelse return error.NoNPath;
                const parent_np = np.parent.nid orelse
                    return .{ .view = self.view, .nid = 0, .npath_nid = null };
                const pnp = self.view.getNodeAs(NPath, parent_np).?;
                return .{ .view = self.view, .nid = pnp.ref.nid, .npath_nid = parent_np };
            }
        };

        /// Insert node and register it at name below the given NPath parent
        /// (shared by Cursor.put and AnyCursor.put).
        fn putBelow(view: View, parent_np: ?Nid, name: anytype, node: anytype) Error!Cursor(@TypeOf(node)) {
            const m = switch (view) {
                .mutable => |m| m,
                .frozen => return error.Frozen,
            };
            const nm = coerceName(name);
            try nm.validate();
            var t = m.txn();
            errdefer t.abort();
            const c = try t.insert(node);
            _ = try t.insert(NPath{
                .parent = .{ .nid = parent_np },
                .name = nm,
                .ref = .to(c.nid),
            });
            try t.commit(null);
            return c;
        }

        /// Create an empty path node below the given NPath parent.
        fn putPathBelow(view: View, parent_np: ?Nid, name: anytype) Error!AnyCursor {
            const m = switch (view) {
                .mutable => |m| m,
                .frozen => return error.Frozen,
            };
            const nm = coerceName(name);
            try nm.validate();
            var t = m.txn();
            errdefer t.abort();
            const npc = try t.insert(NPath{
                .parent = .{ .nid = parent_np },
                .name = nm,
                .ref = .none,
            });
            try t.commit(null);
            return .{ .view = view, .nid = null, .npath_nid = npc.nid };
        }

        fn atNpath(view: View, parent_np: ?Nid, name: Name, alloc: Allocator) Error!AnyCursor {
            const key: meta.KeyType(NPath, NPath.ordb_indexes.idx_parent_name) = .{ parent_np, name };
            const npc = view.oneBy(NPath, "idx_parent_name", key, alloc) catch |err| switch (err) {
                error.NotFound, error.NotUnique => return error.PathNotFound,
                error.OutOfMemory => |e| return e,
            };
            const np = npc.get();
            return .{ .view = view, .nid = np.ref.nid, .npath_nid = npc.nid };
        }

        fn childrenOfNpath(view: View, parent_np: ?Nid, alloc: Allocator) Error![]AnyCursor {
            const key: meta.KeyType(NPath, NPath.ordb_indexes.idx_parent) = .{parent_np};
            const npcs = try view.allBy(NPath, "idx_parent", key, alloc);
            defer alloc.free(npcs);
            const out = try alloc.alloc(AnyCursor, npcs.len);
            for (npcs, 0..) |npc, i| {
                out[i] = .{ .view = view, .nid = npc.get().ref.nid, .npath_nid = npc.nid };
            }
            return out;
        }

        fn npathString(view: View, npath_nid: ?Nid, alloc: Allocator) Error![]u8 {
            var names: std.ArrayList(Name) = .empty;
            defer names.deinit(alloc);
            var np_nid = npath_nid;
            while (np_nid) |nn| {
                const np = view.getNodeAs(NPath, nn) orelse break;
                try names.append(alloc, np.name.?);
                np_nid = np.parent.nid;
            }
            std.mem.reverse(Name, names.items);

            var out: std.ArrayList(u8) = .empty;
            errdefer out.deinit(alloc);
            for (names.items, 0..) |nm, i| {
                switch (nm) {
                    .s => |s| {
                        if (i > 0) try out.append(alloc, '.');
                        try out.appendSlice(alloc, s);
                    },
                    .i => |n| {
                        var buf: [24]u8 = undefined;
                        const t = std.fmt.bufPrint(&buf, "[{d}]", .{n}) catch unreachable;
                        try out.appendSlice(alloc, t);
                    },
                }
            }
            return out.toOwnedSlice(alloc);
        }

        // Transactions
        // ------------

        pub const Txn = struct {
            m: *Mutable,
            journal: std.ArrayList(JEntry) = .empty,
            touched: std.AutoArrayHashMapUnmanaged(Nid, void) = .empty,
            removed: std.AutoArrayHashMapUnmanaged(Nid, void) = .empty,
            saved_nid_next: Nid,
            done: bool = false,

            const JEntry = struct { nid: Nid, old: ?Entry };

            fn journalAndPut(t: *Txn, nid: Nid, entry: ?Entry) Allocator.Error!void {
                const old = t.m.nodes.get(nid);
                try t.journal.append(t.m.gpa, .{ .nid = nid, .old = old });
                if (entry) |e| {
                    try t.m.nodes.put(t.m.arena.allocator(), nid, e);
                } else {
                    _ = t.m.nodes.swapRemove(nid);
                }
            }

            /// Insert a node with a freshly allocated nid.
            pub fn insert(t: *Txn, node: anytype) Error!Cursor(@TypeOf(node)) {
                const nid = t.m.nid_next;
                try t.insertAtTyped(@TypeOf(node), nid, node);
                return .{ .view = t.m.view(), .nid = nid };
            }

            /// Insert a node at a specific nid (used by load/compact).
            pub fn insertAtTyped(t: *Txn, comptime T: type, nid: Nid, node_in: T) Error!void {
                if (t.m.nodes.get(nid)) |e| {
                    if (e == .node) return error.DuplicateNid;
                    // tombstone: the nid is free again (remove + re-add in one txn)
                } else if (getNodeG(t.m, nid) != null) {
                    return error.DuplicateNid;
                }
                const node = try meta.dupeStrings(T, node_in, t.m.arena.allocator());
                meta.retainSubgraphRefs(T, node);
                try t.journalAndPut(nid, .{ .node = @unionInit(Node, meta.typeBaseName(T), node) });
                try t.m.index.add(t.m.arena.allocator(), T, node, nid);
                try t.touched.put(t.m.gpa, nid, {});
                _ = t.removed.swapRemove(nid);
                if (nid >= t.m.nid_next) {
                    t.m.nid_next = std.math.add(Nid, nid, 1) catch return error.NidExhausted;
                }
            }

            /// Replace the node at nid (which must exist and be a T).
            pub fn updateTyped(t: *Txn, comptime T: type, nid: Nid, v_in: T) Error!void {
                const cur = getNodeG(t.m, nid) orelse return error.NotFound;
                if (std.meta.activeTag(cur) != comptime meta.tagFor(Root, T)) return error.WrongNodeType;
                if (t.m.nodes.get(nid)) |own| {
                    if (own == .node) t.m.index.removeNode(own.node, nid);
                }
                const v = try meta.dupeStrings(T, v_in, t.m.arena.allocator());
                meta.retainSubgraphRefs(T, v);
                try t.journalAndPut(nid, .{ .node = @unionInit(Node, meta.typeBaseName(T), v) });
                try t.m.index.add(t.m.arena.allocator(), T, v, nid);
                try t.touched.put(t.m.gpa, nid, {});
            }

            /// Remove the node at nid. Nodes born in this generation are
            /// hard-deleted; parent-generation nodes get a tombstone.
            pub fn removeNid(t: *Txn, nid: Nid) Error!void {
                if (nid == 0) return error.RootRemoval;
                if (getNodeG(t.m, nid) == null) return error.NotFound;
                if (t.m.nodes.get(nid)) |own| {
                    if (own == .node) t.m.index.removeNode(own.node, nid);
                }
                if (nid >= t.m.base_nid_end) {
                    try t.journalAndPut(nid, null);
                } else {
                    try t.journalAndPut(nid, .tombstone);
                }
                _ = t.touched.swapRemove(nid);
                try t.removed.put(t.m.gpa, nid, {});
            }

            /// Run all deferred constraint checks; on success the changes
            /// become permanent, on failure everything is rolled back and the
            /// subgraph is left exactly as before the transaction.
            pub fn commit(t: *Txn, diag: ?*Diag) CommitError!void {
                std.debug.assert(!t.done);
                // Defers run LIFO: on error, rollback first, then cleanup.
                defer t.cleanup();
                errdefer t.rollback();

                if (getNodeG(t.m, 0) == null) return error.MissingRoot;

                for (t.touched.keys()) |nid| {
                    const e = t.m.nodes.get(nid) orelse continue;
                    const node = switch (e) {
                        .node => |n| n,
                        .tombstone => continue,
                    };
                    switch (node) {
                        inline else => |v| try checkNode(t.m, @TypeOf(v), v, nid, diag),
                    }
                }

                for (t.removed.keys()) |nid| {
                    const e = t.m.nodes.get(nid);
                    if (e != null and e.? == .node) continue; // re-added after removal
                    var refs: std.ArrayList(Nid) = .empty;
                    defer refs.deinit(t.m.gpa);
                    try collectBackrefsG(t.m, nid, t.m.gpa, &refs);
                    if (refs.items.len > 0) {
                        setDiag(diag, .{ .nid = nid, .other_nid = refs.items[0] });
                        return error.RemovedStillReferenced;
                    }
                }

                // Old entries displaced during this transaction are gone for
                // good now; drop their subgraph retains.
                for (t.journal.items) |je| {
                    if (je.old) |old| switch (old) {
                        .node => |n| releaseNodeSubgraphRefs(n),
                        .tombstone => {},
                    };
                }
                t.done = true;
            }

            /// Explicitly roll back an uncommitted transaction (for errdefer
            /// between transaction operations). No-op after commit.
            pub fn abort(t: *Txn) void {
                if (t.done) return;
                t.rollback();
                t.cleanup();
            }

            fn rollback(t: *Txn) void {
                var i = t.journal.items.len;
                while (i > 0) {
                    i -= 1;
                    const je = t.journal.items[i];
                    if (t.m.nodes.get(je.nid)) |cur| {
                        if (cur == .node) {
                            t.m.index.removeNode(cur.node, je.nid);
                            releaseNodeSubgraphRefs(cur.node);
                        }
                    }
                    if (je.old) |old| {
                        t.m.nodes.put(t.m.arena.allocator(), je.nid, old) catch
                            @panic("OOM during transaction rollback");
                        if (old == .node) {
                            t.m.index.addNode(t.m.arena.allocator(), old.node, je.nid) catch
                                @panic("OOM during transaction rollback");
                        }
                    } else {
                        _ = t.m.nodes.swapRemove(je.nid);
                    }
                }
                t.m.nid_next = t.saved_nid_next;
                t.done = true;
            }

            fn cleanup(t: *Txn) void {
                t.journal.deinit(t.m.gpa);
                t.touched.deinit(t.m.gpa);
                t.removed.deinit(t.m.gpa);
            }
        };

        fn setDiag(diag: ?*Diag, value: Diag) void {
            if (diag) |d| d.* = value;
        }

        fn checkNode(m: *Mutable, comptime T: type, v: T, nid: Nid, diag: ?*Diag) CommitError!void {
            const tname = comptime meta.typeBaseName(T);

            // Required attributes:
            inline for (std.meta.fields(T)) |f| {
                if (comptime meta.isRequired(T, f.name)) {
                    if (attrIsNull(@field(v, f.name))) {
                        setDiag(diag, .{ .nid = nid, .node_type = tname, .field = f.name });
                        return error.MissingAttr;
                    }
                }
            }

            // Unique index constraints (checked against the merged view):
            inline for (index_specs, 0..) |spec, si| {
                if (comptime spec.ntype_index == meta.typeIndex(Root, T) and spec.decl.unique) {
                    if (meta.makeKey(T, spec.decl, v)) |key| {
                        var matches: std.ArrayList(Nid) = .empty;
                        defer matches.deinit(m.gpa);
                        try lookupIndexG(m, T, si, key, m.gpa, &matches);
                        if (matches.items.len > 1) {
                            setDiag(diag, .{ .nid = nid, .node_type = tname, .index = spec.name });
                            return if (comptime isNPathNameIndex(si))
                                error.PathExists
                            else
                                error.UniqueViolation;
                        }
                    }
                }
            }

            // Reference attributes:
            inline for (std.meta.fields(T)) |f| {
                const FieldT = f.type;
                switch (comptime meta.attrKind(FieldT)) {
                    .plain => {},
                    .local_ref => {
                        if (@field(v, f.name).nid) |target_nid| {
                            const target = getNodeG(m, target_nid) orelse {
                                setDiag(diag, .{ .nid = nid, .node_type = tname, .field = f.name, .other_nid = target_nid });
                                return error.DanglingLocalRef;
                            };
                            if (comptime FieldT.ordb_targets.len > 0) {
                                if (!tagIn(std.meta.activeTag(target), FieldT.ordb_targets)) {
                                    setDiag(diag, .{ .nid = nid, .node_type = tname, .field = f.name, .other_nid = target_nid });
                                    return error.RefTypeMismatch;
                                }
                            }
                        }
                    },
                    .subgraph_ref => {
                        if (@field(v, f.name).ptr) |h| {
                            const expected = comptime meta.typeBaseName(FieldT.ordb_root);
                            if (!std.mem.eql(u8, h.root_type, expected)) {
                                setDiag(diag, .{ .nid = nid, .node_type = tname, .field = f.name });
                                return error.RefTypeMismatch;
                            }
                        }
                    },
                    .external_ref => {
                        if (@field(v, f.name).nid) |ref_nid| {
                            const FRoot = FieldT.ordb_foreign_root;
                            const FSG = Subgraph(FRoot);
                            const header = FieldT.ordb_of(View{ .mutable = m }, nid) orelse {
                                setDiag(diag, .{ .nid = nid, .node_type = tname, .field = f.name });
                                return error.ExternalRefUnresolvable;
                            };
                            const foreign = FSG.Frozen.fromHeader(header) catch {
                                setDiag(diag, .{ .nid = nid, .node_type = tname, .field = f.name });
                                return error.RefTypeMismatch;
                            };
                            const fnode = FSG.getNodeG(foreign, ref_nid) orelse {
                                setDiag(diag, .{ .nid = nid, .node_type = tname, .field = f.name, .other_nid = ref_nid });
                                return error.DanglingExternalRef;
                            };
                            if (comptime FieldT.ordb_targets.len > 0) {
                                if (!FSG.tagIn(std.meta.activeTag(fnode), FieldT.ordb_targets)) {
                                    setDiag(diag, .{ .nid = nid, .node_type = tname, .field = f.name, .other_nid = ref_nid });
                                    return error.RefTypeMismatch;
                                }
                            }
                        }
                    },
                }
            }
        }

        fn tagIn(tag: Tag, comptime targets: anytype) bool {
            // Target types that are not members of this subgraph's union are
            // skipped: a multi-target ref like PolyVec2R.ref (SymbolPoly or
            // SchemWire) is declared once but checked per subgraph kind.
            inline for (targets) |TT| {
                if (comptime meta.typeIndexOpt(Root, TT)) |ti| {
                    if (tag == @as(Tag, @enumFromInt(ti))) return true;
                }
            }
            return false;
        }

        // Content hash (computed by serialize.zig at freeze time)
        // --------------------------------------------------------

        fn finalizeHash(f: *Frozen) Allocator.Error!void {
            const serialize = @import("serialize.zig");
            try serialize.computeContentHash(f);
        }
    };
}
