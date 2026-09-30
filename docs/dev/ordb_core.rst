ORDB native core
================

All subgraph storage, indices, transactions and constraint checks of ORDB
are implemented in the C extension :mod:`ordec.core.ordb._ordb`
(``src/ordec/core/ordb/_ordb.c``, storage primitives in ``_ordb_store.h``).
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

Data layout
-----------

A subgraph state consists of:

- **One table per node type.** A table is a vector of records of 8-byte
  slots. Slot 0 is the nid (a removed node leaves the tombstone ``-1 - nid``),
  followed by the attribute slots in layout order.
- **The nid directory**, one record ``[location, references]`` per nid:
  the table and row of the node, and the number of LocalRefs pointing at the
  nid. The counter replaces reverse-reference buckets: a node can be removed
  if its counter is zero at commit.
- **One index per declared** :class:`~ordec.core.ordb.Index`: sorted runs of
  entries ``(h, s, nid)`` plus an unsorted tail of up to 64 entries. ``h`` is
  the hash of the key (for a single int or LocalRef key, the value itself),
  ``s`` the sort attribute (or 0). Runs are immutable and shared between
  snapshots by reference count; runs of similar size are merged (amortized
  O(log n) per insert).

Attribute values are stored by kind (decided per attribute when the node
type is created):

- int, LocalRef, ExternalRef: one int64 slot;
- value types with ``array_width`` (Vec2I, Rect4I): that many int64 slots;
- everything else: one slot holding a Python object reference.

Two reserved int64 values mean "None" and "boxed". A boxed value (an int
outside the int64 range, a bool in an int attribute, a Vec2I subclass, ...)
is kept in a small per-subgraph dict. Values therefore round-trip exactly;
the common case costs one comparison.

The index is a hint, the tables are the truth
---------------------------------------------

Removing a node or changing an indexed attribute does not touch the index:
the old entry becomes stale. Every read (queries, unique checks) verifies its
candidates against the current row (node alive, same ``(h, s)``, key equal).
Stale entries are dropped when runs are merged or when an index is compacted
at commit (once they are the majority).

Storage engines
---------------

A table (and the directory) is a ``Vec`` in one of two engines. Everything
above is shared; only the vector and the undo mechanism differ.

``paged``
  A persistent radix tree: inner nodes with 32 children, leaves of 16
  records. Every tree node carries the token of its creator. A node is
  written in place if it was created in the current transaction, or if it is
  owned by the subgraph and the write is an append behind every snapshot's
  row count; any other node is copied first, along the path from the root.
  Freeze, thaw and copy share the whole tree (O(number of tables)); a write
  copies one leaf and its path. A transaction keeps the previous state;
  abort installs it again.

``flat``
  One contiguous block per table. Snapshots share blocks by reference count;
  the first write to a shared block copies it as a whole. Transactions edit
  in place and log the old contents of rows they overwrite; abort replays the
  log backwards.

Both engines pass the same test suite and produce identical content hashes
and wire encodings. ``paged`` is the default (``ORDEC_ORDB_BACKEND`` selects
the engine of new subgraphs).

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
opening; aborting an outer updater also undoes committed inner ones. Freezing
or copying a subgraph with an open updater raises
:class:`~ordec.core.ordb.OrdbException`.

ExternalRef targets are checked in C when ``of_subgraph`` is
``('root', name)``; other forms call ``ExternalRef.check_ref`` per node.

Maintenance
-----------

At the end of the outermost transaction, tables with more tombstones than
live rows are rewritten, and indices whose entries are mostly stale are
compacted. Freezing also rewrites tables whose rows are out of nid order, so
frozen tables scan in nid order.

Threads
-------

The core relies on the GIL, but the GIL alone does not protect it: whenever
the core calls Python code (a ``__hash__`` or ``__eq__`` of a value, an
attribute factory, a check callback, a finalizer run by the garbage
collector), another thread can run. Two rules and one coding discipline
keep the storage consistent:

- **One writing thread per subgraph.** The thread that opens the outermost
  updater (or starts a write such as ``freeze()`` maintenance) owns the
  subgraph until it is done. A write from another thread in that time raises
  :class:`~ordec.core.ordb.OrdbException`; it does not wait, so that code
  taking several subgraphs in different orders cannot deadlock.
- **No write while a write operation is in progress.** Python code called
  from inside a core operation (e.g. a ``__hash__`` during an insert) cannot
  modify the same subgraph; it raises.
- **Readers never keep a pointer into storage across Python code.** Before
  anything that can run Python, a reader copies the record it needs
  (``Rec`` in ``_ordb.c``), and loops look tables up again for every row.
  Reads from other threads are therefore always allowed; they see the
  current, possibly uncommitted state (a nid list from a query may name
  nodes removed meanwhile).

Free-threaded Python is not supported: it would need the module to declare
GIL-free operation, the lock released around every call into Python,
atomic reference counts for the shared index runs, and per-subgraph locks.

Garbage collection
------------------

Blocks shared between subgraphs that can hold Python object references are
GC-tracked Python objects (as are all inner tree nodes), so the cycle
collector sees every reference exactly once. Blocks of tables without object
slots are plain memory. The core needs the GIL.

Memory measurements (the ``retained`` figures of the benchmark suite) sum
``sys.getsizeof`` over ``gc.get_referents``. They see the storage only
because inner tree nodes are GC objects (so leaves are reachable) and flat
blocks and subgraphs implement ``__sizeof__`` (index runs are counted as a
share by reference count). A new block type needs the same, or memory
figures silently undercount.

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
Besides ``pytest`` under both engines (``ORDEC_ORDB_BACKEND=flat``), a
change to the core should pass:

- **Sanitizers.** Build the core with AddressSanitizer and UBSan and run the
  ORDB-heavy tests and the fuzz with the sanitizer runtimes preloaded::

      gcc -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer \
          -shared -fPIC -I$(python3 -c "import sysconfig; print(sysconfig.get_paths()['include'])") \
          src/ordec/core/ordb/_ordb.c \
          -o src/ordec/core/ordb/_ordb$(python3 -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))")
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
- **Persistent pages** (``paged``): about as fast as ``flat`` per operation
  (both are 10 to 35 times faster than the Python backends), no undo log,
  and chains of generations stay small (3 MiB instead of 9.6 GB for 200
  generations of a million rows with 10 changes each). It became the
  default; ``flat`` stays as the simpler engine that the fuzz checks
  ``paged`` against.

The page size decides how much snapshots share: with 2 % random updates
per generation, pages of 64 rows shared almost nothing (148 MiB against
192 MiB for full copies), pages of 8 to 16 rows shared well (29 to 50
MiB) at no measurable cost for reads through Python. Hence 16-row leaves.

Indices are sorted runs verified against the rows because hash indices
degrade on keys with many duplicates (all rectangles on one layer), while
an order on (key hash, sort value, nid) serves plain, sorted and unique
indices alike; immutable runs are shared by snapshots without extra
machinery, and a bulk insert builds a run with one sort.

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
changes, freeze and copy are refused while an updater is open); explicit
schema forms (``sortkey=order``, ``of_subgraph=('root', 'ref_layers')``);
``Subgraph.nodes`` is a read-only view and ``Subgraph.index`` is gone;
cursors are equal by (subgraph, nid); sorted index results break ties by
nid.

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
- ``arrays()`` always copies: strided zero-copy views for clean ``flat``
  tables, or leaves of any length ("extents") for bulk rows in ``paged``.
- ExternalRef paths other than ``('root', name)`` are checked in Python;
  ``SimHierarchy`` still uses a callable ``of_subgraph``.
- Tables whose rows are out of nid order are sorted on every ``all(T)`` until
  the next freeze.
- Index entries take 24 bytes; 16 would do.

Correctness and semantics:

- A LocalRef or explicit nid more than 2^24 past the end of the nid
  directory raises ``OrdbException`` immediately, where the old backends
  raised ``DanglingLocalRef`` at commit and allowed sparse nids up to 2^32.
- ``arrays()`` uses the private ``_PyBytes_Resize``.

Portability and packaging:

- ``__builtin_ctzll`` has no MSVC equivalent under that name; the core is
  only built and tested with gcc on Linux and Python 3.13 so far.
- Wheels for macOS and Windows, and builds against Python 3.11 and 3.12.
- Optional: the Limited API (one abi3 wheel per platform). This needs heap
  types instead of the 12 static types, about 30 accesses to type object
  fields and 45 macros replaced, and the same for ``_gdsrecords.c``.

Threads:

- If concurrent writers to one subgraph become a use case: a
  transaction-scoped, reentrant lock per subgraph that releases the GIL
  while waiting, instead of raising.
- Free-threaded Python (see "Threads" above).

Design questions:

- Bringing back lambdas for index declarations (``sortkey=lambda node:
  node.order``, ``of_subgraph=lambda c: c.root.ref_layers``), which read
  better than attributes and name tuples. The core would call them per
  node: to be costed is the Python call per insert (sort keys) and per
  check (ExternalRef), for the affected types.
- A portable pure-Python version for installs without a compiler: about
  1,500 to 2,000 lines, Python equivalents of the four C types (cursor,
  attribute descriptor, subgraph, updater), chosen at import time, and every
  change to ORDB made twice. The fuzz could compare it with the core across
  processes.
- Removing ``flat``: less code (no undo log, no second vector engine) and
  half the test runs, but the fuzz would lose the engine it compares
  ``paged`` against, and ``flat`` is somewhat faster for single-row updates.

Documentation: the Sphinx build was not verified after the switch to the
native core.
