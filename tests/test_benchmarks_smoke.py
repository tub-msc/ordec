# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
CI smoke test for the ORDB benchmark suite (benchmarks/): every workload
must run at smoke scale under every registered storage backend, all
backends must produce identical results, and the differential fuzz must
pass. Runs in seconds; the benchmark package itself is not shipped with
the ordec wheel.
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from ordec.core import ordb
from benchmarks.workloads import WORKLOADS
from benchmarks.runner import run_one
from benchmarks import equivalence

@pytest.mark.parametrize('backend', ordb.available_backends())
def test_smoke_all_workloads(backend):
    for wl in WORKLOADS.values():
        record = run_one(wl, backend, 'smoke', repeats=1, warmup=0, seed=1,
            measure_mem=False, do_checksum=True)
        assert record['checksum']
        for ph in wl.phases:
            assert record['phases'][ph]['wall_ns']

def test_equivalence():
    equivalence.check_equivalence()

def test_differential_fuzz():
    equivalence.differential_fuzz_all()
