# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Workload registry. Each workload is a function

    fn(params: dict, seed: int) -> WorkloadRun

that executes its phases (timing them via PhaseTimer), and returns the
phase wall times plus its final graph state (for checksumming) and the
objects it keeps alive (for retained-memory measurement). All randomness
comes from benchmarks.prng.Lcg(seed) so runs are reproducible and
identical across backends and worlds.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

@dataclass
class WorkloadRun:
    phase_ns: dict          #: phase name -> wall time in ns
    final: object           #: subgraph or list of subgraphs, for checksum
    retained: list = field(default_factory=list) #: objects kept alive

@dataclass
class Workload:
    name: str
    fn: object
    phases: tuple           #: phase names in execution order
    params: dict            #: scale name -> params dict
    mirrors: str            #: which real ORDeC code path this models

WORKLOADS = {}

def workload(name, phases, params, mirrors=''):
    def deco(fn):
        WORKLOADS[name] = Workload(name, fn, tuple(phases), params, mirrors)
        return fn
    return deco

class PhaseTimer:
    def __init__(self):
        self.phase_ns = {}

    @contextmanager
    def phase(self, name):
        t0 = time.perf_counter_ns()
        try:
            yield
        finally:
            dt = time.perf_counter_ns() - t0
            self.phase_ns[name] = self.phase_ns.get(name, 0) + dt

# Importing the modules populates WORKLOADS:
from . import symbol_build, layout_flatten, render_scan, sim_hierarchy, \
    snapshot_chain, micro
