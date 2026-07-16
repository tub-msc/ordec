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

def test_report_html(tmp_path):
    """--html writes one self-contained HTML report (no deps, no JS)."""
    from benchmarks.report import group_records
    from benchmarks.html import write_html

    backends = ordb.available_backends()
    records = {}
    for wl in list(WORKLOADS.values())[:2]:
        for backend in backends:
            rec = run_one(wl, backend, 'smoke', repeats=1, warmup=0, seed=1,
                measure_mem=True, do_checksum=False)
            params = tuple(sorted(rec['params'].items()))
            records[('python', backend, wl.name, params)] = rec | {
                'world': 'python'}

    path = tmp_path / 'report.html'
    write_html(group_records(records), backends[0], 'min', str(path))
    page = path.read_text()
    assert page.startswith('<!DOCTYPE html>')
    # Self-contained: nothing fetched, and every backend actually present.
    assert 'src="http' not in page and 'href="http' not in page
    for backend in backends:
        assert backend in page
    # Colour is never the only channel: ratios are in the text too.
    assert 'baseline' in page and '×</b>' in page

def test_equivalence():
    equivalence.check_equivalence()

def test_differential_fuzz():
    equivalence.differential_fuzz_all()
