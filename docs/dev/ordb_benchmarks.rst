ORDB storage backends and benchmarks
====================================

ORDB's subgraph storage is pluggable: every subgraph carries a reference
to a *storage backend* (:mod:`ordec.core.ordb.backend`) that owns the
representation of its node store and combined index, the transaction
mechanics, the freeze/thaw/copy lifecycle and frozen-subgraph value
equality. The rest of ORDB (nodes, cursors, indices, queries, the updater)
is backend-independent.

Available backends
------------------

============================ ==================================================
Name                          Storage model
============================ ==================================================
``pyrsistent-patricia``       Persistent HAMT maps (pyrsistent), Patricia-trie
                              integer-set buckets. The default.
``pyrsistent-pvector``        Same maps, sorted persistent-vector buckets (the
                              pre-Patricia behavior; kept as a baseline).
``fullcopy``                  Plain dicts, full copies at every boundary
                              including transaction begin. Strawman baseline.
``cow``                       Plain dicts, O(1) snapshot sharing, transactions
                              copy only what they touch (top-level dict once
                              after a snapshot, buckets on first write).
``delta`` /                   Delta chains ported from the Zig ORDB
``delta-compactN``            reimplementation (``zig`` branch): each frozen
                              generation stores only its delta; reads walk the
                              chain. ``compactN`` flattens chains deeper than N
                              at freeze.
============================ ==================================================

Backend selection: the ``ORDEC_ORDB_BACKEND`` environment variable, or
programmatically ``ordb.use_backend(name)`` (context manager) /
``MutableSubgraph(backend=...)``. Derived subgraphs (freeze/thaw/copy)
inherit their origin's backend. The whole test suite is expected to pass
under every backend::

    ORDEC_ORDB_BACKEND=delta pytest -m "not web"

Benchmark suite
---------------

The top-level ``benchmarks/`` package (not shipped in the wheel) compares
the backends on synthetic workloads shaped like real ORDeC usage: many
small view builds, layout flatten/expand, read-only render scans,
simulation-hierarchy construction, freeze/thaw generation chains, and
index-bucket micros. :doc:`ordb_benchmark_workloads` writes out what they
do, along with the PRNG, the checksum and the JSON output, so that a
pure-Zig ORDB can run the same workloads and be compared against (the
zigbridge FFI is deliberately not benchmarked).

Typical usage::

    # list workloads and backends
    python -m benchmarks.runner --list

    # quick sanity run
    python -m benchmarks.runner --smoke --workloads all --backends all

    # full run with memory measurement and checksums (a few minutes)
    python -m benchmarks.runner --workloads all --backends all \
        --repeats 5 --warmup 1 --mem --checksum --out results/py.json

    # the tier to actually draw conclusions from -- slow, run it deliberately
    python -m benchmarks.runner --workloads all --backends all --scale large \
        --repeats 5 --warmup 1 --checksum --time-limit 0 --out results/py.json

    # compare (also merges results from other worlds/machines)
    python -m benchmarks.report results/*.json --baseline pyrsistent-pvector
    python -m benchmarks.report results/*.json --check-sanity

    # HTML report
    python -m benchmarks.report results/*.json --baseline pyrsistent-pvector \
        --html results/report.html --no-tables

The ``default`` scale is sized so the full matrix stays in the minutes range;
``--scale large`` is where asymptotic differences between backends actually
show up. Every workload/backend pair is capped by ``--time-limit`` (30 s by
default, ``0`` disables): once the budget is spent the runner stops starting
new repeats and says so, rather than silently reporting a truncated run as a
full one.

``--html`` writes one self-contained page built around a workload x backend
matrix, which is the shape of the question the suite exists to answer. It
needs no dependencies and contains no JavaScript, so it is a ~25 KB file that
opens anywhere and prints to PDF from the browser.

The page is: a headline (which backend won, and on how many workloads), the
total-time matrix, the same matrix for peak and retained memory when the run
used ``--mem``, and each multi-phase workload's phases behind a ``<details>``
so the page opens on the summary rather than on every number at once.

Cells are shaded on a diverging scale around the baseline -- blue better, red
worse, neutral at parity -- log-spaced, because the ratios span roughly 0.02×
to 90×. Every cell also carries its ratio and absolute value as text: colour
is a redundant channel, so the page survives printing, greyscale and
colour-vision deficiency. Change what everything is measured against with
``--baseline``.

``total`` (a ``total`` row in the tables, the total-time matrix in the HTML
report) is the workload's phases summed. It is derived by the report tool,
not stored in the JSON, and only appears for multi-phase workloads -- for a
single-phase one the phase already is the total. It sums the phases *within
each run* and only then applies ``--stat``: summing per-phase minima would
take each phase from whichever run suited it best and understate every
backend by a different margin. Untimed setup belongs to no phase, so
``total`` is the measured work, not the wall time of the whole run.

Two checks keep a comparison honest:

- ``python -m benchmarks.equivalence`` checks that every workload produces
  an identical canonical checksum under every backend and runs a
  differential fuzz (random op sequence applied lockstep under candidate
  and reference backends, state compared after every operation, including
  transaction-isolation and abort checks).
- ``tests/test_benchmarks_smoke.py`` runs the whole suite at smoke scale
  in CI.

Transactions and index snapshots
--------------------------------

While a :class:`~ordec.core.ordb.SubgraphUpdater` transaction is open, the
subgraph's own ``nodes``/``index`` keep showing the pre-transaction state;
only the updater's views expose uncommitted changes. Real code (e.g.
``resolve_instances`` in ``ordec/schematic/helpers.py``) queries the
subgraph mid-transaction and depends on this. Additionally, ``index[key]``
returns an immutable snapshot of the bucket, so callers may iterate a
query result while removing exactly those nodes (the ``expand_rects``
pattern). Backends have to get both right
(:mod:`ordec.core.ordb.backend`); the differential fuzz checks them.

Going forward
-------------

Patricia buckets removed the quadratic index maintenance, but the layout
webdata path is still slow, and its profile no longer points at a single
hotspot: what is left is the sheer volume of transactional work. Roughly in
order of payoff:

``webdata()`` mutates the graph in order to serialize it. ``expand_geom``
opens a transaction per replaced rect — around 29k of them — and inserts
~147k nodes, paying index updates and constraint checks for a result that is
discarded once rendered. A read-only traversal prototype (walk instances
recursively with accumulated transforms, expand shapes inline, never touch the
graph) produced identical shape counts in 0.42 s where the current pipeline
takes roughly 100 s. That is the fix for the web path, and it also removes the
``flatten()`` and ``mutable_copy()`` costs.
``ordec.layout.helpers.compare()`` can check geometric equivalence against the
old pipeline.

pyrsistent runs as pure Python on 3.13 — its C extension does not build there,
and ``pmap.set`` dominates what remains. That costs roughly 2–3× across *all*
ORDB operations, not only this path. Worth pursuing upstream or vendoring the
patch; a startup warning when the extension is missing would at least make the
degradation visible rather than silent.

``webdata()`` is not memoized. Views are frozen and hashable, so caching the
conversion per frozen view in the server would make reopening a panel free.

Further out, the schema itself amplifies: every polygon vertex is its own
node, so geometry-heavy subgraphs carry several times the node count and every
bulk operation pays for it. Running bulk transforms in a single transaction
rather than one per node is the cheap mitigation; storing vertex arrays as an
attribute (as :class:`~ordec.core.simarray.SimArray` does for simulation data)
would change the constraint-based layout workflow and is a separate
discussion.

On the benchmark side, a default-backend decision wants large-scale runs, and
runs with a working pyrsistent C extension, before it is made. The ``delta``
backend's weakness on ``micro_replace`` points at its index-delta merge at
commit. Candidates worth measuring: a ``cow`` backend with Patricia buckets,
and an unsorted-NID-bucket variant — ascending iteration is the only ordering
the API promises, so a hash set with sort-on-read is admissible.
