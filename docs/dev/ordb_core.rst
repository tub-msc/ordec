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

Garbage collection
------------------

Blocks shared between subgraphs that can hold Python object references are
GC-tracked Python objects (as are all inner tree nodes), so the cycle
collector sees every reference exactly once. Blocks of tables without object
slots are plain memory. The core needs the GIL.

Cursors
-------

:class:`~ordec.core.ordb.Node` derives from the C type ``NodeBase``, which
holds (subgraph, nid) and the lazily resolved NPath nid. Attribute
descriptors read the slots directly; LocalRef attributes return cursors
without a Python call. Two cursors are equal if they select the same node of
equal subgraphs; cursors of one subgraph are ordered by nid.
