# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Benchmark runner CLI.

    python -m benchmarks.runner --workloads all --backends all \\
        --scale default --repeats 5 --warmup 1 --seed 1 \\
        --mem --checksum --out results/py.json

Results are written as JSON in the schema documented in
docs/dev/ordb_benchmark_workloads.rst; merge and
compare files with `python -m benchmarks.report`.
"""

import argparse
import gc
import json
import platform
import subprocess
import sys
import time
import tracemalloc

from ordec.core import ordb

from . import SPEC_VERSION
from .checksum import checksum_result
from .memory import retained_bytes
from .workloads import WORKLOADS

def _git_rev():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, timeout=10).stdout.strip() or None
    except OSError:
        return None

def _cpu_model():
    try:
        with open('/proc/cpuinfo') as f:
            for line in f:
                if line.startswith('model name'):
                    return line.split(':', 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()

def _impl_info():
    try:
        import pvectorc # pyrsistent's C extension
        c_ext = True
    except ImportError:
        c_ext = False
    return {
        'python': platform.python_version(),
        'ordec_git': _git_rev(),
        'cpu': _cpu_model(),
        'hostname': platform.node(),
        'pyrsistent_c_ext': c_ext,
    }

def run_one(wl, backend_name, scale, repeats, warmup, seed, measure_mem,
        do_checksum, param_overrides=None, time_limit=None):
    """Run one (workload, backend) combination; returns a result record."""
    params = dict(wl.params.get(scale) or wl.params['default'])
    if param_overrides:
        params.update(param_overrides)

    phase_runs = {ph: [] for ph in wl.phases}
    final = None
    t_start = time.perf_counter()
    with ordb.use_backend(backend_name):
        for r in range(warmup + repeats):
            gc.collect()
            run = wl.fn(params, seed)
            if r >= warmup:
                for ph in wl.phases:
                    phase_runs[ph].append(run.phase_ns.get(ph, 0))
            final = run
            # Stop repeating once the budget is spent, but never report zero
            # timed runs: a pass is only ever cut between runs, never inside
            # one, so the timings that do get recorded stay comparable.
            if (time_limit is not None and len(phase_runs[wl.phases[0]]) >= 1
                    and time.perf_counter() - t_start > time_limit):
                break

        done = len(phase_runs[wl.phases[0]])
        record = {
            'workload': wl.name,
            'backend': backend_name,
            'params': {**params, 'scale': scale, 'seed': seed},
            'warmup': warmup,
            'repeats': done,
            'repeats_requested': repeats,
            'phases': {ph: {'wall_ns': runs} for ph, runs in phase_runs.items()},
        }

        if do_checksum:
            record['checksum'] = checksum_result(final.final)
        else:
            record['checksum'] = None

        if measure_mem:
            final = None
            gc.collect()
            tracemalloc.start()
            run = wl.fn(params, seed)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            record['mem'] = {
                'tracemalloc_peak_bytes': peak,
                'retained_bytes': retained_bytes(run.retained),
            }
        else:
            record['mem'] = None

    return record

def _select(arg, available, what):
    if arg == 'all':
        return list(available)
    names = [n.strip() for n in arg.split(',') if n.strip()]
    for n in names:
        if n not in available:
            raise SystemExit(f"Unknown {what} {n!r}. Available: "
                f"{', '.join(available)}")
    return names

def _parse_param_overrides(pairs):
    """--param workload.key=value -> {workload: {key: int(value)}}"""
    overrides = {}
    for pair in pairs or ():
        try:
            target, value = pair.split('=', 1)
            wl_name, key = target.rsplit('.', 1)
        except ValueError:
            raise SystemExit(f"Bad --param {pair!r}, expected workload.key=value")
        overrides.setdefault(wl_name, {})[key] = int(value)
    return overrides

def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m benchmarks.runner',
        description='Run ORDB storage backend benchmarks.')
    parser.add_argument('--workloads', default='all',
        help='comma-separated workload names, or "all"')
    parser.add_argument('--backends', default='all',
        help='comma-separated backend names, or "all"')
    parser.add_argument('--scale', default='default',
        choices=['tiny', 'small', 'default', 'large'])
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--warmup', type=int, default=1)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--mem', action='store_true',
        help='add one instrumented pass measuring memory')
    parser.add_argument('--checksum', action='store_true',
        help='record the canonical checksum of the final graph state')
    parser.add_argument('--tiny', action='store_true',
        help='tiny sizes, 1 repeat, 0 warmup (shortcut)')
    parser.add_argument('--time-limit', type=float, default=30.0,
        metavar='SECONDS',
        help='per (workload, backend) budget: stop repeating once exceeded, '
            'keeping at least one timed run (0 = no limit, default: 30)')
    parser.add_argument('--param', action='append', metavar='W.KEY=VAL',
        help='override one workload parameter, e.g. snapshot_chain.k=64')
    parser.add_argument('--out', default=None,
        help='output JSON path (default: print to stdout)')
    parser.add_argument('--list', action='store_true',
        help='list workloads and backends, then exit')
    args = parser.parse_args(argv)

    if args.list:
        print('Workloads:')
        for wl in WORKLOADS.values():
            print(f"  {wl.name:<24} phases={','.join(wl.phases)}")
            print(f"  {'':<24} mirrors: {wl.mirrors}")
        print('Backends:')
        for b in ordb.available_backends():
            print(f"  {b}")
        return 0

    if args.tiny:
        args.scale = 'tiny'
        args.repeats = 1
        args.warmup = 0

    workloads = _select(args.workloads, WORKLOADS, 'workload')
    backends = _select(args.backends, ordb.available_backends(),
        'backend')
    overrides = _parse_param_overrides(args.param)

    results = []
    for wl_name in workloads:
        wl = WORKLOADS[wl_name]
        for backend_name in backends:
            t0 = time.perf_counter()
            record = run_one(wl, backend_name, args.scale, args.repeats,
                args.warmup, args.seed, args.mem, args.checksum,
                overrides.get(wl_name), args.time_limit or None)
            dt = time.perf_counter() - t0
            best = {ph: min(v['wall_ns']) / 1e6
                for ph, v in record['phases'].items()}
            phases_str = ' '.join(f"{ph}={ms:.1f}ms" for ph, ms in best.items())
            # Never let a truncated run masquerade as a full one.
            cut = record['repeats'] < record['repeats_requested']
            note = (f" [time limit: {record['repeats']}/"
                f"{record['repeats_requested']} repeats]" if cut else '')
            print(f"[{wl_name} @ {backend_name}] {phases_str} "
                f"(total {dt:.1f}s){note}", file=sys.stderr)
            results.append(record)

    doc = {
        'spec_version': SPEC_VERSION,
        'world': 'python',
        'impl': _impl_info(),
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'results': results,
    }
    out = json.dumps(doc, indent=2)
    if args.out:
        with open(args.out, 'w') as f:
            f.write(out + '\n')
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(out)
    return 0

if __name__ == '__main__':
    sys.exit(main())
