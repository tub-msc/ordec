ORDB benchmark workloads
========================

What the benchmark workloads do, how their random input is built, how the
result checksum is computed and what the JSON output looks like — written out
in enough detail that a second implementation can run the same thing and get
comparable numbers. The Python code in ``benchmarks/`` is what actually runs;
this page exists so the Zig ORDB (see the ``zig`` branch) can match it and
emit the same JSON, which ``python -m benchmarks.report`` merges. The zigbridge
FFI is left out on purpose: each side benchmarks its own data structures.

Storage backends
----------------

A backend stores one *subgraph*: a mapping ``nodes: nid -> node`` (nid:
unsigned integer; node: immutable tuple of attribute values with a type tag),
a combined index ``index: key -> bucket``, and an allocation cursor
``nid_alloc_start``.

What a backend does:

- **txn begin / commit / abort** — all mutation happens inside a transaction.
  While one is open, the subgraph itself still shows the pre-transaction
  state; only the transaction's view sees uncommitted changes. Aborting leaves
  the subgraph untouched.
- **node set / node remove** — insert, overwrite or delete one node.
- **bucket add / remove** — index maintenance. Bucket kinds:

  - ``NID``: set of nids, iterated in ascending order;
  - ``SORTED``: nids ordered by an externally supplied sort value (ties:
    later-inserted first, i.e. leftmost-insertion/bisect_left order);
  - ``SET``: unordered set of values.

  ``index[key]`` returns an immutable *snapshot* of the bucket, so callers can
  iterate it while mutating the subgraph. An empty bucket looks the same as an
  absent key.

- **freeze** — produce an immutable snapshot; the mutable subgraph stays
  usable afterwards.
- **thaw** — produce a new mutable subgraph from a snapshot.
- **fork** — produce an independent mutable copy of a mutable subgraph.
- **compact** (optional) — produce a content-identical snapshot with flattened
  internal structure (delta chains); identity for flat backends.

Python backend names: ``pyrsistent-patricia``, ``pyrsistent-pvector``
(persistent HAMT maps; Patricia-trie vs sorted-vector NID buckets),
``fullcopy`` (plain dicts, full copies at every boundary incl. txn begin),
``cow`` (plain dicts, O(1) share-on-snapshot, copy-on-first-write), ``delta``
/ ``delta-compactN`` (delta chains ported from the Zig design; N =
auto-compact chain-depth threshold at freeze). Zig backend names should
describe their structure analogously (e.g. ``zig:delta``).

PRNG
----

64-bit LCG, Knuth MMIX constants. State update and output (all in unsigned
64-bit arithmetic, modulo 2^64)::

    state' = state * 6364136223846793005 + 1442695040888963407
    output = state' >> 33          (31-bit value)

``Lcg(seed)``: state = seed. ``randint(n)`` = ``next() % n`` (modulo bias is
accepted). Every random choice in a workload draws from one Lcg instance
seeded with the run's ``seed`` parameter (default 1), in the exact order given
by the workload definitions below. The same seed has to give the same workload
everywhere, otherwise the numbers are not comparable.

Schema
------

Node types used by the workloads; all attributes are int or str. ``LocalRef``
stores a nid of the same subgraph, ``ExternalRef`` a nid of another subgraph
resolved through a ``SubgraphRef`` (a reference to a frozen subgraph).
``Index(attr)`` = NID bucket per attr value; ``Index(attr, sortkey=order)`` =
SORTED bucket; ``CombinedIndex([a, b], unique=True)`` = NID bucket keyed by the
value pair, enforcing uniqueness at commit. ``NonLeaf`` types can own named
children (paths); named insertion creates one extra path node (NPath) per name,
itself indexed by (parent, name) and by referenced nid. Every subgraph has a
root node at nid 0; nids allocate sequentially from ``nid_alloc_start``.

- Symbol-like: ``SymRoot`` (root); ``SymPin(num:int)``; ``SymPoly(layer:int)``;
  ``SymVertex(ref:LocalRef(SymPoly), order:int, x:int, y:int;
  Index(ref, sortkey=order))``.
- Schematic-like: ``SchRoot`` (root); ``SchNet(w:int)``;
  ``SchInst(sym:SubgraphRef(SymRoot), x:int, y:int)``;
  ``SchConn(ref:LocalRef(SchInst), pin:ExternalRef(SymPin via ref.sym),
  net:LocalRef(SchNet); Index(ref); CombinedIndex([ref, pin], unique))``.
- Layout-like: ``LayRoot(kind:int)`` (root); ``LRect(layer, lx, ly, ux,
  uy:int)``; ``LPoly(layer:int)``; ``LVertex`` (as SymVertex, ref to LPoly);
  ``LLabel(layer, x, y:int, text:str)``;
  ``LInst(sub:SubgraphRef(LayRoot), dx, dy:int)``.
- Sim-like: ``SimRoot`` (root); ``SimGroup(depth:int)`` (NonLeaf);
  ``SimItem(group:LocalRef(SimGroup), key:str;
  CombinedIndex([group, key], unique))``;
  ``SimAnnot(target:LocalRef(SimItem), value:int)``.
- Chain: ``ChainRoot`` (root); ``CNode(tag:int, val:int; Index(tag))``.
- Micro: ``MicroRoot`` (root); ``Box(val:int)``; ``MPoly(val:int)``;
  ``UNode(val:int; Index(val, unique))``.

What actually runs is the code in ``benchmarks/workloads/``; the summaries
below describe it. A port needs the same PRNG draws in the same order, the
same insertion order and the same transaction boundaries — otherwise the
checksums diverge and there is nothing left to compare.

Workloads
---------

Phases are timed separately (wall clock). "own txn" = the operation opens and
commits its own transaction, as ORDeC generator code does for every statement.

symbol_build — phases: build
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Mirrors small view-generator builds. M times: create a SymRoot; K pins
inserted under names ``p0..p{K-1}`` (own txn each, one NPath each); P polys
(own txn), each with V vertices ``SymVertex(order=o, x=rand(1000),
y=rand(1000))`` (own txn each); poly layer = rand(8); freeze. All M frozen
subgraphs are retained. Draw order per poly: layer, then per vertex x, y.

Params (default): M=200, K=8, P=6, V=5. small: M=100. large: M=5000. tiny:
M=5, K=4, P=2, V=3.

layout_flatten — phases: copy, flatten, expand, freeze, scan
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Mirrors the layout flatten/expand webdata pipeline. Untimed setup: C frozen
cells of S shapes (per shape: layer=rand(8), x=rand(10000), y=rand(10000);
even shapes an LRect with ux=x+1+rand(500), uy=y+1+rand(500), odd shapes an
LPoly with 4 vertices x+rand(500), y+rand(500) each; every 8th shape adds an
LLabel), built in one txn each; a frozen top with I instances named ``i0..``
referencing cell rand(C) at dx,dy = rand(100000). Timed: **copy** = mutable
copy of the top; **flatten** = for each LInst: re-insert every cell shape
translated by (dx, dy) (own txn per insert), then remove the instance;
**expand** = replace every LRect (iterating the bucket snapshot) by an LPoly
plus 4 corner vertices, reusing the rect's nid; **freeze**; **scan** = 3 passes
over all LPoly, LVertex, LLabel reading attributes.

Params (default): C=5, S=40, I=50. small: 5/20/20. large: 10/200/2000.
tiny: 2/8/4.

render_scan — phases: build, scan
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Mirrors read-only schematic rendering. **build** (reported, but the scan is the
point): Y frozen symbols (pins P, polys Q with V vertices as in symbol_build);
a SchRoot with N nets (named ``n0..``, w=rand(4)), then I instances: pick
symbol rand(Y), insert SchInst (x, y = rand(100000)) named ``i{i}``, and one
SchConn per symbol pin to net rand(N) (own txn each); freeze. **scan**, R
repetitions, zero mutation: for every SchInst read x, y, resolve its symbol;
for every conn of the instance (Index(ref) query) resolve the external pin's
num; for every symbol poly iterate its vertices via the sorted index with
coordinate arithmetic; build the instance's full path string; then read w of
every net.

Params (default): Y=8, P=4, Q=6, V=5, I=200, N=100, R=5. small: I=100, N=50,
R=3. large: I=8000, N=4000, R=20.

sim_hierarchy — phases: build, annotate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Mirrors SimHierarchy construction plus result back-annotation. **build**:
recurse from the root, depth D, fanout F: insert SimGroup named ``g{f}``
(depth=level), then E items ``SimItem(group, key='k{e}')`` (own txn each;
unique (group, key) check at each commit); recurse into each group.
**annotate**: for every group in creation order, for e in 0..E-1: look up the
item by the unique (group, 'k{e}') index query, insert
``SimAnnot(target=item, value=rand(2^20))`` (own txn).

Params (default): D=3, F=4, E=6. small: D=3, F=3, E=4. large: D=5, F=6, E=8.

snapshot_chain — phases: build, chain, read
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The generation-chain stress. **build**: N CNodes (tag=rand(64),
val=rand(2^20)) in one txn; freeze (generation 0). A mirror list ``live`` of
inserted nids is maintained for reproducible picks. **chain**: K times: thaw
the newest snapshot; one txn with max(1, N*p/1000) patch ops, each drawing
r=rand(100): r<60 → update ``val=rand(2^20)`` of nid live[rand(len)]; r<85 →
insert new CNode (draws tag, val; append nid); else remove nid at live index
rand(len) (drop from live); freeze. If compact_every > 0 and the generation
number is a multiple, compact the new snapshot before continuing. ALL K+1
snapshots are retained (memory measurement). **read** on the newest snapshot:
iterate all CNodes summing val; for tag 0..63 iterate the tag index query; N
random point lookups ``nodes[live[rand(len)]]``.

Draw order per patch op: r, then the op's own draws in the order named. Params
(default): N=10000, K=32, p=20 (permille), compact_every=0 (set e.g.
``--param snapshot_chain.compact_every=8`` to exercise explicit compaction).
small: N=1000, K=8. large: N=50000, K=64. Chain depth K is what this workload
exists to measure -- copy-on-write backends only reveal their cost at depth --
so the default keeps K high rather than trimming it for runtime.

micro_remove_all / micro_insert_descending / micro_replace / micro_abort
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Single phase each. NType-bucket micros:

- **remove** (n Box prebuilt, untimed): one txn removing all n nids one-by-one
  in ascending order.
- **insert**: one txn inserting Box(val=nid) at explicit nids n..1
  (descending), forcing head insertion into the NID bucket.
- **replace** (n Box prebuilt): for each Box cursor (bucket snapshot), replace
  it by MPoly(val) reusing the nid (own txn each).
- **abort** (n UNode(val=i) prebuilt): ``rounds`` times, one txn inserting
  ``batch`` fresh UNodes then one duplicate val → unique violation at commit →
  rollback; the state is unchanged after each round.

Params (default): n=3000; abort: batch=300, rounds=10. small: n=1000; abort:
batch=100, rounds=5. large: n=50000; abort: batch=2000, rounds=20.

Checksum
--------

FNV-1a 64-bit (offset 0xcbf29ce484222325, prime 0x100000001b3) over the
canonical serialization of the final subgraph; all integers little-endian::

    for each nid ascending:
        u64(nid)
        u32(len(typename)) ++ typename utf-8    (canonical node type name)
        per attribute in declaration order, tagged:
            0x00                     None
            0x01 ++ i64(value)       int
            0x02 ++ u32(len) ++ utf8 str
            0x03 ++ u64(nid)         LocalRef
            0x04 ++ u64(nid)         ExternalRef
            0x05 ++ u64(checksum)    SubgraphRef (recursive checksum)
    finally u64(nid_alloc_start)

NPath nodes participate like any other node (typename "NPath", attributes
parent: LocalRef, name: int-or-str tagged by value, ref: LocalRef). For a
workload retaining a list of subgraphs, the result checksum is FNV-1a over the
concatenated u64 per-subgraph checksums. Reported as
``"fnv1a64:0x<16 hex digits>"``. Backends and worlds that disagree here are not
comparing the same thing; the report tool flags mismatches.

Measurement protocol
--------------------

- Per (workload, backend): ``warmup`` untimed runs, then ``repeats`` timed
  runs. Report every repeat's per-phase wall time in ns (statistics are
  computed by the report tool; use min for noise-resistant comparison).
- Scale tiers: ``tiny`` is for CI, ``default`` is sized so the whole matrix
  runs in a few minutes, and ``large`` is the tier for drawing real
  conclusions (asymptotic differences need it; see ``--param`` for one-off
  sizes). A second implementation only needs to match the tier it reports.
- ``--time-limit`` (Python runner: 30 s per workload/backend, 0 disables)
  stops *starting* further repeats once the budget is spent, so a run is only
  ever cut between repeats, never inside one; at least one timed repeat always
  survives. ``repeats`` in the output is how many actually ran, which is why
  it may be below ``repeats_requested``.
- Garbage collection: collect before each run, leave enabled during runs
  (allocator/GC behavior is part of what is measured).
- Memory (optional, Python): one extra instrumented pass, separate from timing:
  allocation peak via tracemalloc plus ``retained_bytes`` = deduped deep size
  of the objects the workload retains (e.g. all generations of snapshot_chain)
  — the structure-sharing comparison number. Caveats: the walker cannot see
  C-level internals (record ``pyrsistent_c_ext``), and interned/shared small
  objects are attributed to the graph. Other worlds report the closest
  equivalents (e.g. arena bytes) and document them.

JSON result format
------------------

.. code-block:: json

    {
      "spec_version": 1,
      "world": "python",
      "impl": {"python": "3.13.5", "ordec_git": "abc1234", "cpu": "...",
               "hostname": "...", "pyrsistent_c_ext": false},
      "timestamp": "2026-07-07T12:00:00Z",
      "results": [
        {
          "workload": "snapshot_chain",
          "backend": "delta",
          "params": {"n": 10000, "k": 32, "patch_permille": 20,
                     "compact_every": 0, "scale": "default", "seed": 1},
          "warmup": 1,
          "repeats": 5,
          "repeats_requested": 5,
          "phases": {"build": {"wall_ns": [1, 2, 3, 4, 5]},
                     "chain": {"wall_ns": [1, 2, 3, 4, 5]},
                     "read":  {"wall_ns": [1, 2, 3, 4, 5]}},
          "mem": {"tracemalloc_peak_bytes": 0, "retained_bytes": 0},
          "checksum": "fnv1a64:0x0123456789abcdef"
        }
      ]
    }

``world`` distinguishes implementations ("python", "zig"). ``impl`` is
free-form host/implementation metadata. ``mem`` and ``checksum`` may be null
when not measured. Records are keyed by (world, backend, workload, params) when
merging; the same key from a later file wins.

Checks
------

1. ``ORDEC_ORDB_BACKEND=<b> pytest`` green for every backend.
2. ``python -m benchmarks.equivalence``: identical checksums for every workload
   under every backend, plus a differential fuzz (seeded random
   insert/update/remove/freeze/thaw/fork/abort sequence applied lockstep under
   candidate and reference backends, full state compared after every op,
   including transaction isolation and abort checks).
3. ``tests/test_benchmarks.py`` runs both in CI at the ``tiny`` scale.
