ORDB storage engines and benchmarks
===================================

Subgraph storage is implemented by the native core (:doc:`ordb_core`) in
one engine, ``paged`` (persistent pages). A second engine, ``flat``
(contiguous blocks, copied as a whole before the first write after
sharing), was removed; its results below are kept as history and as a
target for tuning ``paged``.

Engine selection is kept for future engines: the ``ORDEC_ORDB_BACKEND``
environment variable, or programmatically ``ordb.use_backend(name)``
(context manager) / ``MutableSubgraph(backend=...)``. Every subgraph keeps
the engine it was created with; derived subgraphs (freeze/thaw/copy)
inherit it.

Benchmark suite
---------------

The top-level ``benchmarks/`` package (not shipped in the wheel) compares
the storage engines on synthetic workloads shaped like real ORDeC usage: many
small view builds, layout flatten/expand, read-only render scans,
simulation-hierarchy construction, freeze/thaw generation chains, and
index-bucket micros. :doc:`ordb_benchmark_workloads` writes out what they
do, along with the PRNG, the checksum and the JSON output, so that
another implementation could run the same workloads.

Typical usage::

    # list workloads and backends
    python -m benchmarks.runner --list

    # quick sanity run
    python -m benchmarks.runner --tiny --workloads all --backends all

    # full run with memory measurement and checksums (a few minutes)
    python -m benchmarks.runner --workloads all --backends all \
        --repeats 5 --warmup 1 --mem --checksum --out results/py.json

    # the tier to actually draw conclusions from -- slow, run it deliberately
    python -m benchmarks.runner --workloads all --backends all --scale large \
        --repeats 5 --warmup 1 --checksum --time-limit 0 --out results/py.json

    # compare (also merges results from other worlds/machines)
    python -m benchmarks.report results/*.json --baseline paged

    # HTML report
    python -m benchmarks.report results/*.json --baseline paged \
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
  an identical canonical checksum under every engine (with one engine,
  compare the checksums across commits) and runs a differential fuzz
  (random transactions, snapshots, aborts and nested updaters applied to
  every engine and to a pure-Python reference model; after every step each
  engine must hold the model's nodes, index queries must equal brute-force
  scans and snapshots must be unchanged).
- ``tests/test_benchmarks.py`` runs the whole suite at the smallest scale
  in CI.

Results
-------

One workstation (Intel Core i7-14700K), Python 3.13.5. The previous
implementation (``cow-arrays``: Python dicts plus numpy chunks, and the other
pure-Python backends it replaced) is given for comparison, as is the removed
``flat`` engine.

Per operation, measured on the benchmark schema:

============================================== ============ ======= =======
Operation                                      cow-arrays   paged   flat
============================================== ============ ======= =======
insert with ``%`` (one transaction per node)   9.6 us       0.66 us 0.93 us
attribute read on a cursor                     229 ns       20 ns   16 ns
``all(T)`` plus one attribute read, per node   1.75 us      95 ns   83 ns
attribute assignment (own transaction)         8.5 us       0.40 us 0.24 us
polygon vertex insert (sorted index)           15.3 us      0.85 us 0.64 us
thaw, one update, freeze (50,000 nodes)        1.9 ms       1.6 us  0.35 ms
hash of a frozen subgraph (50,000 nodes)       66 ms        0.25 ms 0.17 ms
============================================== ============ ======= =======

Synthetic suite at ``--scale large`` (sum of the phases, one run):

=========================== ============ ======= =======
Workload                    cow-arrays   paged   flat
=========================== ============ ======= =======
``symbol_build``            4.7 s        0.30 s  0.25 s
``render_scan``             19.3 s       1.97 s  1.85 s
``sim_hierarchy``           3.4 s        0.31 s  0.26 s
``snapshot_chain``          0.9 s        0.14 s  0.14 s
``layout_flatten``          65.3 s       2.97 s  2.19 s
=========================== ============ ======= =======

Retained memory of ``snapshot_chain`` at the large scale (64 generations of
50,000 nodes, all kept alive): 31.6 MiB with ``paged``, 174 MiB with
``flat``, against 231 MiB for ``cow-arrays`` and 93 MiB for the former
``pyrsistent-patricia``. Pages of 16 rows keep this small: every generation
copies only the pages it touches, while ``flat`` copies every touched table.
On the other workloads, both engines needed 2 to 6 times less memory than
``cow-arrays``.

An example IO ring in SG13G2 (739,000 rectangles) builds in about
0.3 s (``cow-arrays``: 0.58 s); it is dominated by GDS processing, ORDB takes
about 40 ms of it.

Choosing an engine
------------------

``paged`` is the only engine: its transactions need no undo log, and chains
of generations of a large subgraph stay cheap. ``flat`` was somewhat faster
for single-row updates (no page copies) and builds, but every generation
that touched a table copied the table, and its undo log was the riskiest
code of the core; it was removed (see "History & rationale" in
:doc:`ordb_core`). Its numbers above are the target for tuning ``paged`` on
builds and updates.
