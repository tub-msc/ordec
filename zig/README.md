<!--
SPDX-FileCopyrightText: 2026 ORDeC contributors
SPDX-License-Identifier: Apache-2.0
-->

# ORDeC Zig implementation

A Zig re-implementation of ORDeC's graph database (ORDB) and a subset of its
schema (Symbol, Schematic, Layout, LayerStack), plus content-hashed CBOR
serialization and a standard-cell placer demo.

This is a **parallel re-implementation**, not a replacement: the Python ORDB
(`ordec/core/ordb.py`) remains the reference. Everything that Python ORDB does
at runtime through metaclasses and descriptors happens here at **compile
time** through Zig's comptime machinery.

Requires Zig 0.16.0.

```sh
zig build test          # run the full test suite
zig build demo-ordb     # tour of the ORDB principles (port of docs/ref/ordb_demo.py)
zig build demo-placer   # standard-cell placer demo
zig build               # also builds zig-out/lib/libordec_zig.so (Python bridge)
```

`zig build` produces `libordec_zig.so` (C ABI in `src/capi.zig`), through
which Python uses this implementation for compute-heavy work via
`ordec.zigbridge` — see `docs/dev/zigbridge.rst` for the bridge architecture
and wire-format contract.

`demo-ordb` (source: `src/demos/demo_ordb.zig`) is the best starting point:
it ports the Python notebook `docs/ref/ordb_demo.py` and walks through the
five ORDB principles — schema-based data, relational queries, the NPath
naming tree, persistence via freeze/thaw, and the mutable/frozen split —
plus cross-subgraph references, on a small airports-and-flights example
schema.

## Persistence model: delta chains

Python ORDB gets cheap freeze/thaw from pyrsistent's persistent maps. This
implementation
instead uses **delta chains**: every subgraph generation (frozen or mutable)
stores only its own *delta* — nodes added, modified, or tombstoned relative to
its frozen parents — plus retained references to those parents.

```
gen 0 (frozen)     gen 1 (frozen)     gen 2 (mutable)
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ delta:      │◄───│ delta:      │◄───│ delta:      │
│ n0..n9      │    │ n3', n10    │    │ n5'         │
└─────────────┘    └─────────────┘    └─────────────┘
read(3):  gen2? no → gen1? yes → n3'      (newer deltas shadow older ones)
read(0):  gen2? → gen1? → gen0
freeze / thaw: O(1), zero copying
```

- `freeze()` consumes the Mutable and is O(delta) for the move (plus O(merged
  view) for the content hash, see below). `thaw()` is O(1).
- Reads walk the chain newest → oldest. Index queries collect per-generation
  hits, filtering each level's results against the newer deltas (a nid present
  in a newer delta — modified or tombstoned — shadows older index entries).
- Query cost is O(results × chain depth). `Frozen.compact()` flattens a chain
  into a single fresh generation (identical nids and content) when a chain
  gets deep.
- Nodes removed from a parent generation become *tombstones* in the child's
  delta; nodes born and removed in the same generation are hard-deleted.

### Why not a pyrsistent-style persistent map?

Python ORDB stores its nodes in a `pyrsistent.PMap`, a HAMT (hash array
mapped trie). Both designs deliver the same two guarantees — frozen
snapshots are immutable forever, and deriving a new version never copies the
whole graph — but they slice the problem differently:

|                       | pyrsistent (HAMT)            | this impl (delta chain)  |
|-----------------------|------------------------------|-------------------------|
| sharing granularity   | per *operation* (trie nodes) | per *generation* (deltas) |
| single read           | O(log n), pointer-chasing    | O(chain depth) map hits |
| single write          | O(log n) path copy           | O(1) into own delta     |
| freeze / thaw         | O(1) (every map is frozen)   | O(1)                    |
| memory reclamation    | garbage collector            | refcount + arena per generation |
| degenerate case       | none (self-balancing)        | deep chains → `compact()` |

The HAMT's elegance leans on a garbage collector: any operation may abandon
trie nodes that other snapshots still share, and nobody can tell locally
when the last reference disappears. Recreating that in Zig would mean a
refcount in every internal trie node and one heap object per node update —
precisely the fine-grained ownership bookkeeping manual memory management is
worst at. Delta chains move the sharing boundary to whole generations, which
gives every byte exactly one owner (the generation's arena) and one
refcounted handle (the frozen generation). That is also why reads from
parents may safely *borrow* parent-arena memory — a parent is retained for
the child's whole life.

The trade is read cost: a HAMT pays O(log n) on every read regardless of
history, while a delta chain pays per generation crossed. For ORDeC's
workload — build a view generator's subgraph, freeze it, derive small
variations — chains stay shallow and most reads hit the newest delta. Where
they don't, `compact()` restores depth 1 explicitly; the content hash
guarantees the compacted subgraph is *the same value* (identical hash, since
hashing always flattens). The delta chain additionally yields two things a
HAMT does not have: the transfer form for the network falls out for free
(parents-by-hash + own delta is exactly what a generation already stores),
and `thawMulti` can splice several parents into one nid space without
touching their storage.

### Multi-parent merge

`thaw()` generalizes to `Subgraph(Root).thawMulti(gpa, &.{a, b, ...})`: a
mutable subgraph over several frozen parents (a merge DAG). Each parent gets
an **nid base offset** in the child's nid space (parent 0 has offset 0;
parent *i* starts where parent *i-1* ends). Nodes read across a merge
boundary are materialized with their LocalRef nids translated by the offset —
which fields are LocalRefs is known at compile time, so this is a cheap
field-wise copy. Nid 0 (the root) always maps to nid 0.

Merge policy (all violations are errors, nothing merges silently):

- All parents necessarily share the same root *type* (enforced at compile
  time, since `thawMulti` is a method of `Subgraph(Root)`).
- **Strict root conflicts**: parent 0's root becomes the merged root; if a
  later parent's root has a non-null attribute that differs from parent 0's,
  `error.RootConflict` is raised.
- A full **unique-index sweep** over the merged view runs at multi-parent
  thaw, so two individually-valid parents that collide on a unique index
  (e.g. two Layers with the same GDS layer) fail immediately. Single-parent
  thaw stays O(1).
- The child nids where the shadowed roots of parents 1.. would be are holes.

## Compile-time schema

Node types are plain Zig structs. Optional attributes are optional fields
(`?T = null`); defaults are Zig default values; reference attributes are
wrapper types carrying their metadata as comptime declarations:

```zig
pub const SchemInstanceConn = struct {
    ref:   LocalRef(.{SchemInstance}, .{ .required = true }) = .none,
    here:  LocalRef(.{Net}, .{ .required = true }) = .none,
    there: ExternalRef(Symbol, .{Pin}, ofConnInstSymbol, .{ .required = true }) = .none,

    pub const ordb_indexes = .{
        .ref_idx     = idx(&.{"ref"}, .{}),
        .ref_pin_idx = idx(&.{ "ref", "there" }, .{ .unique = true }),
    };
};
```

- `LocalRef(targets, opts)` — nid reference within the subgraph. An empty
  target tuple permits any node type (used by NPath).
- `ExternalRef(ForeignRoot, targets, of_subgraph, opts)` — nid in another
  subgraph; `of_subgraph` is a comptime function mirroring the Python
  `of_subgraph` lambdas (e.g. "resolve `c.ref.symbol`").
- `SubgraphRef(Root, opts)` — reference to a whole frozen subgraph, stored as
  a type-erased `*FrozenHeader` (see below).
- "Required" attributes are stored optional and checked at **commit**, exactly
  like Python's deferred `optional=False` checks.

A subgraph root type lists its permitted node types:

```zig
pub const Schematic = struct {
    symbol: SubgraphRef(Symbol, .{}) = .none,
    outline: ?Rect4R = null,
    ...
    pub const ordb_nodes = .{ Net, SchemPort, SchemWire, SchemInstance, ... };
};
```

`Subgraph(Schematic)` elaborates from this, at compile time: a tagged union
over `{Schematic, NPath} ++ ordb_nodes` for node storage, typed index maps
for every declared index (plus the built-in by-type lists and a LocalRef
back-reference map for integrity checking), and per-type tables of which
fields are refs (for translation, retain/release, and validation).

Adding future schema parts (SimHierarchy, DrcReport, ...) means defining more
node structs and roots — zero changes to the core.

## API tour

```zig
const ordb = @import("ordb");
const schema = ordb.schema;

// Symbol with named pins (Python: s.a = Pin(...)):
var sym_m = try schema.SymbolSG.Mutable.init(gpa, .{ .caption = "inv" });
const pin_a = try sym_m.put("a", schema.Pin{ .pintype = .in, .pos = .xy(0, 4) });
_ = try schema.insertPoly(&sym_m, schema.SymbolPoly{}, &.{ .xy(1, 2), .xy(1, 6), .xy(3, 4) });
const sym = try sym_m.freeze();          // *Frozen, refcount 1, content hash computed
defer sym.release();

// Schematic referencing the frozen symbol:
var sch = try schema.SchematicSG.Mutable.init(gpa, .{ .symbol = .of(sym) });
defer sch.deinit();
const a = try sch.put("a", schema.Net{ .pin = .to(pin_a) });
const y = try sch.put("y", schema.Net{});

// Python: s.I0 = SchemInstance(sym.portmap(a=s.a, y=s.y), pos=...)
const i0 = try schema.instantiate(&sch, "I0", .{
    .pos = .xy(2, 3),
    .symbol = .of(sym),
}, .{ .{ "a", a }, .{ "y", y } });

// Cursors, attribute access, queries:
const pos = i0.field(.pos);                       // read one attribute
try i0.set(.orientation, .r90);                   // one-op transaction
const conns = try sch.view().allBy(schema.SchemInstanceConn, "ref_idx",
    .{ @as(?ordb.Nid, i0.nid) }, gpa);            // index query
const pin = try conns[0].derefExternal(.there);   // cross-subgraph deref
const path = try i0.fullPathStr(gpa);             // "I0"

// Multi-operation transaction with deferred checks:
var txn = sch.txn();
errdefer txn.abort();
_ = try txn.insert(schema.SchemTapPoint{ .ref = .to(a), .pos = .xy(0, 1) });
var diag: ordb.Diag = .{};
try txn.commit(&diag);   // on error, diag names the nid/type/field/index
```

Zig has no operator overloading or descriptors, so Python's `%` operator and
attribute magic become explicit calls (`insert`, `put`, `at`, `field`, `set`).
Commit-time checks mirror `SubgraphUpdater.__exit__`: required attributes,
unique indexes (against the merged view), dangling/mistyped LocalRefs,
ExternalRef resolution + validation, and removed-but-still-referenced nids.
A failed commit rolls back via an undo journal and leaves the subgraph —
including its indexes — exactly as before the transaction.

## Memory model

- **Reference counting** (non-atomic; single-threaded use is assumed).
  Children retain their frozen parents; every SubgraphRef stored in a delta
  retains its target. Frozen-only references form a DAG, so no cycles can
  exist and refcounting is sound. Releasing the last reference cascades.
- Every generation owns an **arena**: node strings, NPath names and big
  rational magnitudes are duped into it on insert, delta maps and indexes
  allocate from it, and the whole generation frees as one. Reads from parent
  generations borrow parent-arena memory, which is safe because parents are
  retained for life.
- The entire test suite runs under `std.testing.allocator`, so leak detection
  doubles as a refcount-correctness proof.

`SubgraphRef` stores a type-erased `*FrozenHeader` (the common first field of
every `Subgraph(Root).Frozen`) rather than a typed pointer. This breaks the
comptime cycle `Subgraph(Layout) → LayoutInstance → Subgraph(Layout)`, gives
the refcounting a uniform handle, and carries the content hash. Typed
access is a checked downcast (`Frozen.fromHeader`, verified via the root type
name; commit-time validation re-checks SubgraphRef targets).

## Content hash and wire format

The globally unique ID of a subgraph is the **sha256 of its canonical CBOR
content form** — the fully flattened merged view, so identical content yields
an identical hash regardless of freeze/thaw/merge history (this matches the
Python `FrozenSubgraph.__eq__` semantics). `Frozen.eqlContent(a, b)` compares
hashes. What travels over the network is the **transfer form**: parent hashes
plus this generation's delta only.

```
content form (hash input):
  [1, root_type: tstr, nid_end: uint,
   [[nid: uint, entry], ...]]              ; ascending nid, no tombstones

transfer form (network):
  [0, root_type: tstr,
   [[parent_hash: bstr(32), offset: uint], ...],
   nid_end: uint,
   [[nid: uint, entry / null], ...]]       ; ascending nid, null = tombstone

entry = [ntype_name: tstr, [attr, ...]]    ; attrs in field declaration order
attr  = null / bool / int (bignum tags 2/3 beyond 64 bit) / tstr (Str)
      / R -> tag 30 (rational number) over [num: int, den: uint]; each
        component minimal (head form below 2^64, bignum tags 2/3 above)
      / struct -> array of fields in declaration order (Vec2* = [x, y],
        Rect4* = [lx, ly, ux, uy], GdsLayer, RGBColor, ...)
      / enum -> uint (the declared enum integer values; PinType, PathEndType
        and D4 values are part of the wire format -- do not renumber)
      / Name -> tstr | int (disambiguated by CBOR major type)
      / LocalRef, ExternalRef -> uint nid / null
      / SubgraphRef -> bstr(32) content hash of the target / null
```

Only definite lengths, minimal-length integer heads, no floats, no maps —
encodings are canonical by construction. Since SubgraphRefs serialize as
content hashes, subgraphs form a **Merkle DAG**.

A golden-hash test (`serialize_test.zig`) locks the format; if it fails, the
wire format changed and the format version must be bumped deliberately.

`serialize.encodeTransfer` / `serialize.decodeTransfer` convert between
frozen subgraphs and transfer blobs; decoding resolves parent hashes and
SubgraphRef targets through a caller-supplied resolver and verifies the
recomputed content hash (`error.HashMismatch` on tampering,
`error.MissingDependency` for absent dependencies). A content-addressed
store / request-by-hash protocol can be layered on top of this when needed.

## Standard-cell placer (demo)

`placer.place(input, opts, gpa)` takes a frozen Layout whose instances are
unplaced (e.g. all at the origin) and returns a new frozen Layout with every
instance legally placed: greedy shelf packing (widest first, deterministic)
into rows on a site grid within the die width, odd rows MX-flipped for
power-rail abutment. Instance arrays are expanded. Cell sizes come from
`schema.layoutBBox` over the referenced cell layouts, cached per distinct
cell. The output is emitted by *thawing the input*, so only moved instances
enter the new delta. `placer.verifyLegal()` is an independent legality oracle
(no overlaps, in-die, on-grid, row alternation) used by the tests.

## Divergences from Python ORDB

- `in_subgraphs` is inverted: the **root** lists its node types
  (`ordb_nodes`), and violations are compile errors instead of runtime
  `ModelViolation`s. Third parties cannot inject node types into an existing
  root without editing its list.
- No inheritance: `LayoutInstanceArray` repeats `LayoutInstance`'s fields;
  `GenericPoly`-style polymorphism becomes explicit target lists
  (`LocalRef(.{LayoutPoly, LayoutRect, LayoutPath}, ...)`) and an
  `ordb_vertex` declaration consumed by the `insertPoly` / `polyVertices` /
  `removePoly` helpers.
- Cursor "methods" from Python (e.g. `vertices()`, `portmap`) are free
  functions in `schema.zig` (`usingnamespace`-style mixins no longer exist in
  Zig 0.15+).
- Hash identity replaces Python's structural `FrozenSubgraph.__eq__`;
  `matches()` (nid-insensitive comparison) is not ported (the Python source
  itself questions its need).
- Removed-but-still-referenced nids raise their own error
  (`RemovedStillReferenced`) instead of reusing `DanglingLocalRef`.
- The `cell` (`Attr(Cell)`) and `resolver`/`value` (`Attr(object)`)
  attributes, `SchemInstanceUnresolved*`, `SchemErrorMarker`, the
  ConstrainableAttr/LinearTerm machinery, and all rendering/webdata methods
  are deliberately not ported.
- `Rational` is a two-tier union instead of Python's unbounded
  `fractions.Fraction`: an i64/i64 `small` fast path plus a `big`
  arbitrary-precision fallback (sign + byte-string magnitudes, <= 255 bytes
  each, i.e. ~2040 bits — far beyond any physical quantity). Canonical form:
  a value that fits `small` is always `small`, so structural equality and
  hashing stay valid. Plain arithmetic (`add`, `mul`, ...) is allocation-free
  and reports results beyond the small range as `error.Overflow`; the
  `*Alloc` variants (`addAlloc`, ...) take an allocator (use an arena) and
  cover the full range. Comparisons, negation, `eql`, formatting and
  `toFloat` handle big values without an allocator (the magnitude cap bounds
  all intermediates, so stack buffers suffice). Storage-wise a big rational
  behaves exactly like a `Str` attribute: duped into the generation arena on
  insert, borrowed on read. Big values render as `f'num/den` (no SI-suffix
  decimal form).
- Refcounting replaces garbage collection; it is non-atomic (single-threaded
  assumption; switching to atomics later is mechanical).
