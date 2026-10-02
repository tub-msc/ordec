ORDB native core
================

All subgraph storage, indices, transactions and constraint checks of ORDB
are implemented in the C extension :mod:`ordec.core.ordb._ordb`, whose
sources are in ``src/ordec/core/ordb/native/``: the storage primitives
(``store.h``, ``store.c``), the engine below the Python types (``engine.c``:
state, records, node operations, transactions and checks; ``index.c``), one
file per Python type (``ntype.c``, ``cursor.c``, ``subgraph.c``,
``updater.c``) and ``module.c``. ``module.h`` holds what the files share;
functions shared between files are hidden from the extension's exports.
:mod:`ordec.core.ordb.base` keeps the schema language, the public classes
and all error messages. There is no pure-Python fallback; the benchmark
suite's differential fuzz (``benchmarks/equivalence.py``) is the safety net.

Building
--------

The core is a regular setuptools extension: ``pip3 install -e .`` builds it
into the source tree (``src/ordec/core/ordb/_ordb.*.so``). After changing the
C sources, run the same command again. For a quick rebuild during
development, ``python3 setup.py build_ext --inplace`` does the same if
setuptools is installed.

The core and ``_gdsrecords.c`` use only the limited API of Python 3.11
(``Py_LIMITED_API`` in the sources), so one abi3 build (``_ordb.abi3.so``)
serves all Python versions from 3.11. The limited API has no static types,
no access to type object fields and no macros like ``PyTuple_GET_ITEM``:
the types are heap types created with ``PyType_FromSpec``, and the function
forms of the macros cost 2 to 3% on the benchmarks. A version-specific
build left in the source tree (``_ordb.cpython-313-*.so``) is imported in
preference to the abi3 one; delete it after switching.

Data layout
-----------

A subgraph state consists of:

- **One table per node type**, a sparse array of records keyed by nid.
  A record is a row of 8-byte slots: slot 0 is the nid, followed by the
  attribute slots in layout order.
- **The nid directory**, one record ``[table, references]`` per nid: the
  table of the node (0: no node), and the number of LocalRefs pointing at
  the nid. The counter replaces reverse-reference buckets: a node can be
  removed if its counter is zero at commit.
- **One index per declared** :class:`~ordec.core.ordb.Index`: a persistent
  B+tree of entries ``(h, s, nid)``, exactly one per indexed live node.
  ``h`` is the hash of the key, ``s`` the sort attribute (or 0). Leaves hold
  32 entries, inner nodes 32 children. Keys hash consistently with ``==``:
  an int like in Python (for nids and small ints, the value itself), a
  value that hashes and compares like a tuple as the mix of its items'
  Python hashes, whether stored in slots or as an object, so that e.g.
  ``(1, 2)``, ``(np.int64(1), 2.0)`` and ``Vec2I(1, 2)`` find each other.

Attribute values are stored by kind (decided per attribute when the node
type is created):

- int, LocalRef, ExternalRef: one int64 slot;
- value types with ``array_width`` (Vec2I, Rect4I): that many int64 slots;
- everything else: one slot holding a Python object reference.

Two reserved int64 values mean "None" and "boxed". A boxed value (an int
outside the int64 range, a bool in an int attribute, a Vec2I subclass, ...)
is kept in a small per-subgraph dict. Values therefore round-trip exactly;
the common case costs one comparison.

The index is exact
------------------

Adding, removing or updating a node inserts and deletes exactly its
entries. Before its first write, an operation computes everything that can
call Python: the record of the new values, and the entries of the old and
the new row (hashes of object keys, sortkey functions). The old entries are
recomputed from the stored row, which is why a ``sortkey`` must depend only
on the node's values (otherwise the entry is not found, and the operation
raises :class:`~ordec.core.ordb.OrdbException`). A query is one range scan
over the entries with hash ``h``, already ordered by ``(s, nid)``; rows are
compared to the key only to rule out hash collisions (for int and LocalRef
keys, by comparing slots without Python code). A unique check asks whether that
range holds another node with an equal key. ``insert_array`` sorts its
entries and inserts them in order, or rebuilds the tree bottom-up if the
batch is at least as large as the index.

The B+tree follows the rules of the tables: nodes carry the token of the
transaction that created them and are written in place only by it, other
writes copy the path from the root. Leaves are plain Python objects
and inner nodes GC objects, so that ``gc.get_referents`` reaches the whole
tree for memory accounting. ``Subgraph._check_indices()`` (used by the
fuzz after every step) checks the tree structure and compares every index
with the entries computed from the live rows.

Storage engine
--------------

A table is a ``KMap`` of the ``keyed`` engine, a persistent radix trie
keyed by nid: a leaf covers 16 nids, with a 16-bit occupancy mask and the
present rows packed in nid order (leaf capacities grow in powers of two);
an inner node has 64 child slots and a 64-bit mask of the present ones.
Lookup is a few shifts and one population count (inline bit arithmetic:
without a POPCNT target, the compiler builtin is a library call).
Attribute descriptors know their node type and go to its table directly,
without the directory. Loops that run no Python code between rows (scans,
``arrays()``, hashing and equality of tables without object slots or boxed
values) walk the trie recursively; the others look each next row up from
the root. Every node carries the
token of the transaction that created it and is written in place only by
it; any other write copies the path from the root. Freeze, thaw and copy
share the whole trie (O(number of tables)). A transaction keeps the
previous state; abort installs it again. The shape of a trie depends only
on its content: removing a node removes its row (no tombstones), tables
need no compaction, and scans are always in nid order.

The content hash of a subgraph (``hash()`` of a frozen subgraph) is an
order-independent sum of row hashes plus ``nid_alloc``. Every table node
caches the sum below it; hashing a frozen subgraph fills the missing sums
lazily, so a new generation only hashes the rows below the nodes it
changed (0.4 us instead of 125 us for one changed row of 50,000). Sums are
stored only while hashing frozen subgraphs: their nodes were committed by
earlier transactions and are never written in place again, so hashing
values with Python code cannot invalidate them; every write path clears
the sum of the nodes it writes nevertheless. Equality compares tables of
rows without object slots or boxed values in parallel, skipping shared
subtrees and stopping at the first differing cached sum; this relies on
the shape of a trie depending only on its content (a removal collapses a
root left with only its first child).

The directory is a ``KMap`` like the tables, with records of two slots (no
nid). A record with neither a node nor references is removed, so nids may
be sparse anywhere below ``nid_stop``.

``keyed`` is the only engine. The engine selection
(``ORDEC_ORDB_BACKEND``, :mod:`~ordec.core.ordb.backend`, the ``engine``
argument of the core) is kept, so that another engine can be tried without
re-adding it. Two engines were removed: ``flat`` and ``paged`` (see
"History & rationale").

Transactions
------------

A :class:`~ordec.core.ordb.SubgraphUpdater` is one transaction. Changes are
visible through the subgraph immediately. On exit, the core checks the
touched nodes (permitted in the subgraph, required attributes, LocalRef and
ExternalRef targets, unique indices) and the removed ones (no LocalRef left
pointing at them). The checks run in C; when one fails, the core calls
``base._check_callback``, which repeats the check in Python and raises the
exact exception.

Updaters of one subgraph nest and must be closed in reverse order of
opening; aborting an outer updater also undoes committed inner ones. An
updater deallocated without exit is aborted with the updaters opened inside
it (at the end of a write operation in progress, if any), which then refuse
further use; updaters remember the token of their transaction, so that they
never use one that was freed. Freezing or copying a subgraph with an open
updater raises :class:`~ordec.core.ordb.OrdbException`.

Statements (``%`` and attribute assignment in C; ``Node.remove``,
``Node.replace``, named insertion, ``Subgraph.add``, ``update`` and
``remove_nid`` through ``Subgraph._statement_updater``) join the open
transaction of the calling thread instead of opening a nested one: their
nids go to its check list, and the checks run at its exit. Only without an
open transaction does a statement get a transaction of its own. Explicit
nested updaters stay real nested transactions. A statement inside an
updater thus costs no ``Txn``, no ``state_copy`` and no page copies beyond
the transaction's own (attribute assignment 890 to 220 ns, ``%`` 910 to
630 ns). Consequences: a LocalRef may point forward to a node added later
in the same updater, and an invalid value raises at with-exit
(``_check_callback`` adds a note naming the node and attribute).

A statement that fails after its first record write (e.g. a ``__hash__``
raising during index insertion) cannot be undone on its own. The
transaction counts its record writes (``Txn.writes``); such a failure sets
``Txn.failed``, after which the transaction refuses further statements and
its updater aborts and raises at exit. Failures before the first write
(factories, type checks) leave the transaction usable.

When a node type is created, ``base.py`` reads the bytecode of the
``sortkey`` and ``of_subgraph`` functions (``_attr_chain``). If a function
only reads a chain of attributes from its argument, the core gets the
attributes themselves: the position of the sort attribute
(``lambda node: node.order``), or the start node of the ExternalRef (the
root, the node itself or the target of one of its LocalRefs) and the
SubgraphRef attribute to read there (``lambda c: c.root.ref_layers``,
``lambda c: c.subg``, ``lambda c: c.ref.symbol``). The core then sorts,
checks and reads ExternalRefs (``rect.layer``) without calling Python; a
root SubgraphRef is resolved once per commit. Any other function is called
per node (sort keys at every index update and query result, ExternalRef
functions at every check and read); a
``tests/test_ordb.py`` test makes sure that the schema's functions take the
native path, except the computed ones of ``SimHierarchy``.

Threads
-------

The core relies on the GIL, but the GIL alone does not protect it: whenever
the core calls Python code (a ``__hash__`` or ``__eq__`` of a value, an
attribute factory, a check callback, a finalizer run by the garbage
collector), another thread can run. Two rules and one coding discipline
keep the storage consistent:

- **One writing thread per subgraph.** The thread that opens the outermost
  updater owns the subgraph until it is done. A write from another thread in that time raises
  :class:`~ordec.core.ordb.OrdbException`; it does not wait, so that code
  taking several subgraphs in different orders cannot deadlock.
- **No write while a write operation is in progress.** Python code called
  from inside a core operation (e.g. a ``__hash__`` during an insert) cannot
  modify the same subgraph; it raises.
- **Readers never keep a pointer into storage across Python code.** Before
  anything that can run Python, a reader copies the record it needs
  (``Rec`` in ``module.h``), and loops look tables up again for every row.
  Reads from other threads are therefore always allowed; they see the
  current, possibly uncommitted state (a nid list from a query may name
  nodes removed meanwhile).

Free-threaded Python is not supported: it would need the module to declare
GIL-free operation, the lock released around every call into Python, and
per-subgraph locks.

Garbage collection
------------------

Table leaves that can hold Python object references are GC-tracked Python
objects (as are all inner nodes), so the cycle collector sees every
reference exactly once. Leaves of tables without object slots, of the
directory and of the indices are not GC-tracked. The core needs the GIL.

Memory measurements (the ``retained`` figures of the benchmark suite) sum
``sys.getsizeof`` over ``gc.get_referents``. They see the storage only
because inner nodes are GC objects (so leaves are reachable) and subgraphs
implement ``__sizeof__``. A new node type needs the same, or memory figures
silently undercount.

Cursors
-------

:class:`~ordec.core.ordb.Node` derives from the C type ``NodeBase``, which
holds (subgraph, nid) and the lazily resolved NPath nid. Attribute
descriptors read the slots directly; LocalRef attributes return cursors
without a Python call. Two cursors are equal if they select the same node of
equal subgraphs; cursors of one subgraph are ordered by nid.

Testing changes to the core
---------------------------

Bugs in C code crash or corrupt memory rather than fail a test cleanly.
Besides ``pytest``, a change to the core should pass:

- **Sanitizers.** Build the core with AddressSanitizer and UBSan and run the
  ORDB-heavy tests and the fuzz with the sanitizer runtimes preloaded::

      gcc -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer \
          -shared -fPIC -I$(python3 -c "import sysconfig; print(sysconfig.get_paths()['include'])") \
          src/ordec/core/ordb/native/*.c -o src/ordec/core/ordb/_ordb.abi3.so
      ASAN_OPTIONS=detect_leaks=0 PYTHONMALLOC=malloc \
          LD_PRELOAD=$(gcc -print-file-name=libasan.so):$(gcc -print-file-name=libubsan.so) \
          pytest -n 0 tests/test_ordb.py tests/test_wire.py tests/test_benchmarks.py \
          tests/test_layout.py tests/test_schematic.py

  Rebuild normally afterwards.
- **Equivalence with the previous version.** In a worktree of the previous
  commit (``git worktree add``), ``benchmarks.equivalence.check_equivalence``
  must print the same workload checksums as in the working tree.
- **Leaks.** Repeating a mixed workload (build, freeze, thaw, remove, abort)
  must keep RSS and ``len(gc.get_objects())`` flat.
- **Threads.** ``python -m benchmarks.thread_stress`` (one writer, readers
  and an intruder on one subgraph, thread switches every microsecond), under
  the sanitizers: no crash, and every rejected write says "another thread".

History & rationale
-------------------

Before the native core, subgraph storage was pure Python behind a pluggable
backend interface (persistent HAMT maps with pyrsistent, copy-on-write
dicts, delta chains, and ``cow-arrays``, which added numpy chunks for rows
inserted with ``insert_array``). Profiles showed that 50 to 70 % of the time
per node was spent in ``base.py`` (cursors, NodeTuple construction, index
maintenance, checks) and only 15 to 20 % in the backend, so no Python
storage could be made substantially faster. ``cow-arrays`` fixed bulk
geometry, but as a second storage form for a single node type without
indices.

The replacement had to keep ORDB's value semantics (immutable snapshots,
cheap freeze/thaw/copy, equal content hashes equally) while storing all
node types in tables and running the per-node paths natively. Two designs
were explored, built and measured against each other:

- **Contiguous tables copied before the first write** (``flat``): the
  simplest form, but every generation that touches a table copies it, e.g.
  48 MB and 20 ms per generation of a table with a million rows.
- **Persistent pages** (``paged``): rows in insertion order in pages of 16
  rows, with tombstones for removed nodes. About as fast as ``flat`` per
  operation (both are 10 to 35 times faster than the Python backends), no
  undo log, and chains of generations stay small (3 MiB instead of 9.6 GB
  for 200 generations of a million rows with 10 changes each). It became
  the default.

``flat`` stayed for a while as the second engine that the differential fuzz
compared ``paged`` against, and was then removed. Its transactions were the
riskiest code of the core (an undo log, replayed backwards on abort and
moved into the parent on a nested commit, which lost entries when out of
memory), it was a poor fit for freeze/thaw (0.35 ms instead of 1.6 us per
thaw, update and freeze of 50,000 nodes; 174 MiB instead of 31.6 MiB for the
large ``snapshot_chain``), and since it shared about 95 % of its code with
``paged``, comparing the two could not find bugs in the shared code. A
pure-Python reference model in the fuzz took over that job. ``flat`` was
faster on builds and single-row updates (``layout_flatten`` 2.19 s against
2.97 s, ``symbol_build`` 0.25 s against 0.30 s, see :doc:`ordb_benchmarks`).

The page size decides how much snapshots share: with 2 % random updates
per generation, pages of 64 rows shared almost nothing (148 MiB against
192 MiB for full copies), pages of 8 to 16 rows shared well (29 to 50
MiB) at no measurable cost for reads through Python. Hence 16-row leaves,
and windows of 16 nids for the tables keyed by nid that replaced the pages.

``paged`` tables kept history-dependent state: rows in insertion order,
tombstones for removed nodes with the location of the row remembered for
revival, compaction at commit once tombstones dominated, a rewrite at
freeze for nid order, and a sort on every scan of a table out of nid order.
Tables keyed by nid (``keyed``) have none of that; their shape depends only
on their content, which keeps equality and cached subtree hashes simple and
makes diffs between generations possible. Both engines ran side by side,
with the same directory, indices and transactions. A stage without C code
estimated tables and per-generation copies from the workloads and real
designs: windows of 32 or 64 nids would copy 1.6 or 2.5 times the bytes of
pages per generation in ``snapshot_chain``, windows of 16 nids 0.9 times.
The first implementation, measured against ``paged`` at the large scale,
was slower: ``layout_flatten`` +28 %, ``sim_hierarchy`` +19 %,
``symbol_build`` +6 %, ``render_scan`` +2 %, ``snapshot_chain`` +3 %; per
operation attribute reads +43 %, inserts with ``%`` +37 %, scans +44 %,
retained memory 0 to +18 %. ``keyed`` was chosen for its simpler invariants.
A profile showed population counts compiled as library calls, packed inner
nodes and iteration re-descending from the root per row; fixing these
(inline population counts, 64 child slots per inner node, attribute reads
without the directory, recursive walks) brought the default-scale suite
from +14.7 % to +5.9 % against ``paged``, attribute reads, scans and
``thaw, update, freeze`` to parity (24 ns, 46 ns, 885 ns), and the hash of a
new snapshot below it (123 instead of 183 us for 50,000 nodes). Builds
remain slower (``layout_flatten`` +13 %, ``sim_hierarchy`` +17 % at the
large scale): an insert in a transaction of its own copies the table leaf
and its path, where ``paged`` appended in place (``%`` 694 against
532 ns), and inserting into the trie costs about 6 % more instructions than
appending a row. The 64-slot inner nodes cost memory in many small
subgraphs (``symbol_build`` retains 13.5 % more). Leaf growth in steps of 4
or to the rest of the window on appends changed nothing measurable.

The directory was the last user of the ``paged`` structure (a dense
persistent vector with lineage tokens, so that a subgraph could append in
place behind its snapshots). Moving it to a ``KMap`` removed that
machinery and the limit on nid gaps (2^24 past the end of the directory),
at a cost of 2.5 % on the default-scale suite, about 3 % retained memory,
and 18 % for ``%`` in a transaction of its own (834 instead of 704 ns),
which now copies the directory leaf and its path.

Indices are ordered by (key hash, sort value, nid) because hash indices
degrade on keys with many duplicates (all rectangles on one layer), while
one order serves plain, sorted and unique indices alike. The first version
kept them as immutable sorted runs plus an unsorted tail, shared by
snapshots by reference count, and treated them as a hint: removals and key
changes left stale entries, every read verified its candidates against the
rows, merges and compaction dropped stale entries, and frozen snapshots
kept theirs. The B+tree replaced it with exact entries: queries need no
candidate sort, deduplication or liveness check, and none of the
heuristics for stale entries. Measured against the runs (large scale):
query phases 8 to 10 % faster (``render_scan.scan``,
``sim_hierarchy.annotate``), ``layout_flatten`` 7 % slower, retained memory
of ``snapshot_chain`` 48.6 instead of 31.6 MiB and of ``layout_flatten``
156 instead of 133 MiB (a generation copies every index leaf it touches,
where runs only grew a tail). Leaves of 32 entries beat 64 and 128 on time
and memory. A leaf that gets an entry appended when full stays full and
starts a new right sibling; splitting it evenly left ascending inserts
(growing nids within one key) with half-empty leaves, which cost 11 % on
``layout_flatten`` and 43 % more memory. A bounded per-transaction insert
buffer, planned in case builds became more than about 10 % slower, was not
needed.

Rejected alternatives:

- One reference-counted row object per node behind a persistent nid map
  (pyrsistent's layout in C): best sharing, but no tables (type scans chase
  pointers, about 50 % more memory); 16-row pages get most of its sharing.
- A flat base plus a delta overlay per generation (delta chains of depth
  one): reads pay the overlay lookup and overlays grow until a full copy.
- In-place updates with reverse deltas for older generations: readers of a
  frozen subgraph would depend on a writer in another thread.
- Kernel copy-on-write (memfd and private mappings): Linux only, 4 KiB
  granularity per table, unusable for thousands of small subgraphs.
- Existing engines (SQLite, DuckDB, LMDB, Apache Arrow): none offers cheap
  branching snapshots that behave as values.
- A core without ``Python.h`` behind a binding layer: object slots and the
  GC rule tie the storage to CPython anyway.
- C++ instead of C: reference-counting wrappers and ``std::sort`` would
  help somewhat, but the hot paths need the raw CPython API regardless.

Decisions taken with the new core: C with the CPython API and no
pure-Python fallback; transactions are not isolated (reads see uncommitted
changes, freeze and copy are refused while an updater is open); the
schema keeps its ``sortkey`` and ``of_subgraph`` lambdas, and the core
evaluates attribute chains among them natively (calling every lambda per
node cost 1.6x on sorted queries and 5x on GDS import; explicit forms such
as ``of_subgraph=('root', 'ref_layers')`` were tried and dropped);
``Subgraph.nodes`` is a read-only view and ``Subgraph.index`` is gone;
cursors are equal by (subgraph, nid); sorted index results break ties by
nid; sort values (``sortkey`` results and sort attributes) are ints within
64 bits or None, which sorts first; ``update`` keeps the node type (a type
change takes a removal and an insertion under the same nid, as in
:meth:`~ordec.core.ordb.Node.replace`).

Values are rebuilt from the tables on every access: ``subgraph.nodes[n]``,
``cursor.tuple`` and reads of ``Vec2I``, ``Rect4I`` or boxed values return
equal but new objects each time. Code relying on object identity (``is``,
``id()``-keyed caches) does not work with node values.

Next steps
----------

Performance:

- Named insertion (``root.x = Node(...)``, about 1.8 us) still runs through
  the Python updater; a C path like the one for ``%`` would cut it.
- The constructors of ``Rect4I``, ``Vec2I`` and ``R`` are now the largest
  per-node cost in user code.
- ``arrays()`` always copies: leaves of any length ("extents") for bulk rows
  would allow zero-copy views.
- ``of_subgraph`` chains of more than one reference
  (``lambda c: c.instance.eref.symbol`` of ``SimPin``) and the computed
  ones of ``SimHierarchy`` are called per node.
- Index entries take 24 bytes; 16 would do.
- An insert in a transaction of its own copies the table leaf, the
  directory leaf and the index leaves it touches, with their paths. For
  tables and the directory, a visibility bound per snapshot (records with a
  nid at or above the snapshot's ``nid_start`` are invisible to it) would
  allow appending new nids in place to nodes owned by the subgraph, as
  ``paged`` did behind each snapshot's row count; every read and walk would
  then filter by the bound.
- Inner nodes always have 64 child slots (520 bytes), which costs memory in
  many small subgraphs; a small packed form for nodes with few children
  would recover it at the cost of a population count per level.

Portability and packaging:

- ``__builtin_ctzll`` has no MSVC equivalent under that name; the core is
  only built with gcc on Linux so far. An abi3 build against the 3.13
  headers passes the tests on Python 3.11 to 3.14; the sources also compile
  against the 3.11 and 3.12 headers.
- ``_attr_chain`` matches CPython bytecode, which changes between versions
  (checked on 3.11 to 3.14). An unrecognized form only makes the schema's
  lambdas slow, and ``test_schema_lambdas_native`` fails.
- Wheels for macOS and Windows.

Threads:

- If concurrent writers to one subgraph become a use case: a
  transaction-scoped, reentrant lock per subgraph that releases the GIL
  while waiting, instead of raising.
- Free-threaded Python (see "Threads" above).

Design questions:

- A portable pure-Python version for installs without a compiler: about
  1,500 to 2,000 lines, Python equivalents of the four C types (cursor,
  attribute descriptor, subgraph, updater), chosen at import time, and every
  change to ORDB made twice. The fuzz could compare it with the core across
  processes.
