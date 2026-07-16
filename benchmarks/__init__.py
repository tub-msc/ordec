# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
ORDB benchmarking suite.

Compares storage backends (ordec.core.ordb) on synthetic workloads
shaped like real ORDeC usage. Workloads, PRNG, checksum and the JSON result
format are specified language-neutrally in docs/dev/ordb_benchmark_workloads.rst
so that non-Python ORDB
implementations can run the same workloads and join the comparison.

Usage:
    python -m benchmarks.runner --list
    python -m benchmarks.runner --tiny --workloads all --backends all
    python -m benchmarks.report results/*.json
"""

SPEC_VERSION = 1
