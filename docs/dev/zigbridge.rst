.. SPDX-FileCopyrightText: 2026 ORDeC contributors
.. SPDX-License-Identifier: Apache-2.0

Zig bridge
==========

``ordec.zigbridge`` lets Python use the Zig implementation of ORDeC's core
(``zig/`` in the repository) as a library for compute-heavy work. Subgraphs
are serialized to a canonical CBOR wire format shared by both
implementations, passed into a C-ABI shared library, and the results are
decoded back into ordinary Python ORDB subgraphs.

The first exposed function is the standard-cell placer::

    from ordec.zigbridge import place

    placed = place(layout, die_width=2000, site_width=100, row_height=800)

Building and locating the library
---------------------------------

.. code-block:: shell

    cd zig/
    zig build                          # -> zig-out/lib/libordec_zig.so
    zig build -Doptimize=ReleaseSafe   # much faster, recommended for real use

``ordec.zigbridge.lib`` looks for the library at ``$ORDEC_ZIG_LIB`` if set,
else at ``zig/zig-out/lib/libordec_zig.so`` relative to the source tree.
``ordec.zigbridge.available()`` reports whether it can be loaded; the
end-to-end tests in ``tests/test_zigbridge.py`` skip without it.

Architecture
------------

.. code-block:: text

    Python (ordec/zigbridge/)                    Zig (zig/src/)
    ┌──────────────────────────────┐            ┌──────────────────────────────┐
    │ placer.py  place(layout,...) │            │ capi.zig   ordec_place/echo/ │
    │ wire.py    encode/decode/    │ ctypes call│            free (C ABI)      │
    │            content_hash      │───────────▶│ serialize.zig decodeTransfer │
    │ tables.py  per-type tables   │ CBOR bundle│ placer.zig    place()        │
    │ lib.py     ctypes loader     │◀───────────│ subgraph.zig  compact()      │
    └──────────────────────────────┘ CBOR bundle└──────────────────────────────┘

The boundary is bytes-in/bytes-out: no Python C-API use in Zig, no shared
object lifetimes, no GIL interaction. Each side keeps its own memory model
(garbage collection vs. reference counting + arenas).

Wire format
-----------

The canonical CBOR format is specified in the header of
``zig/src/serialize.zig``; the Python encoder (``wire.py`` + ``tables.py``)
reproduces it byte-for-byte using the cbor2 library, whose default output is
already canonical (definite lengths, minimal integer heads, tag 30 for
``Fraction``/``R`` with bignum tags 2/3 beyond ±2\ :sup:`64`).

Two properties matter for users of the bridge:

* **Blobs are single-generation.** A transfer blob carries all nodes of one
  subgraph in one generation (empty parent list, no tombstones): Python ORDB
  has no delta-chain history to express, and the Zig side ``compact()``\ s
  its results before returning. Only the *persistence history* is flattened.
* **The subgraph hierarchy is preserved.** Every ``SubgraphRef`` serializes
  as the target subgraph's 32-byte sha256 content hash, and each referenced
  subgraph travels as its own blob. A call passes a *bundle*: a CBOR array
  of blobs in dependency order, top subgraph last. Result blobs only
  reference hashes that were present in the request bundle, so Python
  decodes them against the dependency set it already holds.

The content hash is computed over the *content form* and is the subgraph's
global identity: equal content gives an equal hash on both sides, which makes
encoder drift between the two implementations a loud error instead of silent
corruption.

Why explicit wire tables
^^^^^^^^^^^^^^^^^^^^^^^^

``tables.py`` spells out, per node type, the wire attribute order and value
codecs instead of deriving them from the Python ``Attr`` declarations:

* The wire order is the **Zig field declaration order**, which differs from
  Python's in places — ``LayoutPath`` puts ``layer`` first on the wire but
  declares it last in Python. A generic ``_layout`` walk would produce wrong
  bytes silently (an enum and a nid are both uints on the wire).
* Enum values on the wire are the stable integers declared in
  ``zig/src/schema.zig`` / ``zig/src/geom.zig``, not the Python enum values
  (``PinType`` is string-valued in Python, ``D4`` is namedtuple-valued).
* ``cell = Attr(Cell)`` and other ``Attr(object)``-like attributes have no
  wire representation. Encoding raises ``UnsupportedAttr`` if such an
  attribute is set, unless ``strip_cell=True`` explicitly drops it;
  ``place()`` strips on encode and re-attaches the input's ``cell`` to the
  result. Python-only node types (``SchemInstanceUnresolved*``,
  ``SchemErrorMarker``) and roots outside Symbol/Schematic/Layout/LayerStack
  are rejected.

Integrity and identity
^^^^^^^^^^^^^^^^^^^^^^

Neither side ever trusts a hash from the wire. Bundles carry only blobs;
the hash under which a decoded subgraph becomes resolvable is recomputed
from its *decoded content* (Python: ``decode_bundle``; Zig: ``freeze()``
inside ``decodeTransfer``). A tampered or corrupted dependency blob
therefore hashes to a value nothing references, and decoding fails with a
missing-dependency error instead of silently attaching wrong data — the
Merkle structure does the verification implicitly.

The same mechanism preserves object identity on the Python side: results
are decoded against the dependency set collected at encode time, so the
SubgraphRefs of a placed layout resolve to the *same* ``FrozenSubgraph``
objects the input referenced (PDK cells, layer stack, symbols), not to
duplicate copies.

Relatedly, ``content_hash()`` is a pure function over wire-representable
content and ignores ``cell`` unconditionally — two subgraphs differing only
in ``cell`` *must* collide, or re-attaching ``cell`` to a round-tripped
result would change its identity. The don't-silently-drop-data policy is
enforced where data is actually dropped, in ``encode_transfer()``.

Both implementations pin the format with the **same golden hash constant**
(``zig/src/serialize_test.zig`` and ``tests/test_zigbridge.py``). A wire
format change makes both golden tests fail together; bump the format version
and update both constants deliberately. The tables also self-check at import
time against the Python schema, so adding a Python attribute without
deciding its wire fate fails fast.

C ABI and envelopes
-------------------

``zig/src/capi.zig`` exports::

    u32 ordec_abi_version(void);
    i32 ordec_place(const u8 *in, usize in_len, u8 **out, usize *out_len);
    i32 ordec_echo (const u8 *in, usize in_len, u8 **out, usize *out_len);
    void ordec_free(u8 *ptr, usize len);

Request envelope (CBOR): ``[abi_version=1, args, bundle]`` where ``args`` is
``null`` for echo or ``[die_width, site_width, row_height]`` for place, and
``bundle`` is the blob array described above. On return code 0 the out
buffer holds a response bundle; on nonzero it holds an error envelope
``[code, message]`` with codes 1 (bad envelope), 2 (blob decode error),
3 (domain error, e.g. ``CellTooWide``), 4 (out of memory), 5 (internal).
Python surfaces nonzero codes as ``ZigBridgeError``.

Out buffers are allocated by the library and must be freed with
``ordec_free`` (handled by ``lib.call()``). If ``out_len`` is 0, no buffer
was allocated and ``ordec_free`` must not be called. The library is
single-threaded (non-atomic reference counts); serialize calls from one
thread.

Trade-offs of the serialization boundary
----------------------------------------

The deliberately weak coupling buys: no ABI/lifetime entanglement (FFI
crashes from refcount or GIL mistakes are structurally impossible), a
self-verifying boundary (content hashes), offline debuggability (a blob is
a file you can replay), and build decoupling (``pip install`` needs no Zig
toolchain; the library is optional acceleration).

It costs: O(graph) serialization both ways per call plus transient memory,
which forces coarse-grained batch APIs — right for "place this layout",
wrong for chatty per-node calls; double maintenance of the schema subset in
two languages (guarded by the golden tests); and flattened error reporting
across the boundary.

Future work
-----------

Hash-store dedup layer
^^^^^^^^^^^^^^^^^^^^^^

Today every call resends its full bundle. Since blobs are content-addressed,
the Zig side could cache decoded subgraphs across calls in a store keyed by
content hash, and the protocol could grow REQUEST/PROVIDE semantics: Python
sends the top blob plus the dependency *hash list*; the library answers
MISSING for unknown hashes; Python re-sends only those. The building blocks
exist — Merkle hashing and the ``MapResolver`` interface are in place, and an
earlier draft of the Zig code contained a content-addressed ``Store`` (see
git history) that can be revived. PDK cell libraries, which dominate bundle
size and never change within a session, would then cross the boundary once
per process.

*Pros:* bundles shrink to the actual delta; large win for repeated calls
(iterative placement, optimization loops); no wire-format change for blobs
themselves.

*Cons:* introduces cross-call mutable state into a currently stateless ABI —
an eviction policy and an explicit cache-clear export become necessary;
the non-atomic reference counts pin the library to single-threaded use, which
a long-lived cache makes easier to violate accidentally; the two-phase call
flow (query missing, then provide) complicates the Python wrapper and its
error handling.

Multi-process or network architecture
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The same envelopes can travel over length-prefixed stdio frames or a socket
to a long-lived worker process instead of an in-process call. This matches
how ORDeC already integrates ngspice (piped subprocess), and nothing in the
wire format is process-local: blobs are self-describing, content-hashed, and
the ``abi_version`` field already provides the version handshake.

*Pros:* crash isolation — a Zig bug cannot take down the Python kernel or a
long-running web session; parallelism beyond the GIL (several workers placing
different blocks); the compute can move to another machine (remote, beefier,
or containerized) without redesign; language-agnostic protocol, so non-Python
clients work too.

*Cons:* per-call latency (process startup or socket round trips) and framing
on top of the existing serialization cost; worker lifecycle management
(spawn, health, restart, shutdown); the hash store above becomes
near-mandatory, since resending PDK bundles per call hurts much more over a
pipe than over a function call; debugging spans two processes.

Replacing Python ORDB with the Zig implementation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The end state of that road: the Zig library owns all subgraph storage, and
Python node/cursor classes become thin views over Zig-owned handles —
``ordec.core.ordb`` shrinks to a binding layer.

*Pros:* one source of truth for the schema and constraint checks instead of
two encoders kept in lockstep; order-of-magnitude faster queries, freeze,
and hashing for large layouts; the pyrsistent dependency disappears; the
serialization machinery stops being a boundary and becomes a plain
persistence/export feature.

*Cons:* the surface is enormous — cursors, NPath sugar, ``__getattr__``
magic, the constraint solver, and view generation all sit on Python ORDB
today; ``Attr(Cell)`` / ``Attr(object)`` attributes hold arbitrary Python
objects that have no Zig representation and would need a Python-side sidecar
table keyed by (subgraph, nid); fine-grained attribute access through FFI
has real per-call overhead that can eat the gains unless the binding is
batched (bulk node reads, cursor materialization); schema changes would
require rebuilding the Zig library, where today they are a Python edit; and
the migration cannot be atomic — the realistic path is incremental, keeping
the Python node classes as views over a Zig subgraph handle, migrating hot
subsystems first, with this CBOR bridge as the interoperability fallback for
everything not yet moved.

In short: the dedup layer is a contained optimization worth doing when call
frequency grows; the process split is attractive the moment crash isolation
or parallelism matters; the full replacement is a long-term direction that
should be approached subsystem by subsystem, not as a rewrite.
