# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Benchmark report tool: merge result JSON files (possibly from different
worlds, e.g. Python and Zig) and print per-workload comparison tables.

    python -m benchmarks.report results/*.json --baseline pyrsistent-pvector
    python -m benchmarks.report results/*.json --stat median --format csv
    python -m benchmarks.report results/*.json --check-sanity
"""

import argparse
import json
import statistics
import sys

def load_results(paths):
    """Merged records keyed by (world, backend, workload, params)."""
    records = {}
    for path in paths:
        with open(path) as f:
            doc = json.load(f)
        world = doc.get('world', 'unknown')
        for rec in doc['results']:
            params = tuple(sorted(rec.get('params', {}).items()))
            key = (world, rec['backend'], rec['workload'], params)
            records[key] = rec | {'world': world, 'source': path}
    return records

def _stat(values, stat):
    if stat == 'min':
        return min(values)
    return statistics.median(values)

def _fmt_ns(ns):
    if ns >= 1e9:
        return f"{ns/1e9:.2f}s"
    if ns >= 1e6:
        return f"{ns/1e6:.1f}ms"
    if ns >= 1e3:
        return f"{ns/1e3:.1f}us"
    return f"{ns:.0f}ns"

def _fmt_bytes(b):
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if b < 1024 or unit == 'GiB':
            return f"{b:.0f}{unit}" if unit == 'B' else f"{b:.1f}{unit}"
        b /= 1024

def _emit_table(headers, rows, fmt, out):
    if fmt == 'csv':
        import csv
        writer = csv.writer(out)
        writer.writerow(headers)
        writer.writerows(rows)
        return
    widths = [max(len(str(headers[i])),
        max((len(str(r[i])) for r in rows), default=0))
        for i in range(len(headers))]
    def line(cells):
        return '| ' + ' | '.join(str(c).ljust(w)
            for c, w in zip(cells, widths)) + ' |'
    print(line(headers), file=out)
    print('|' + '|'.join('-' * (w + 2) for w in widths) + '|', file=out)
    for row in rows:
        print(line(row), file=out)

def report(records, baseline, stat, fmt, out=sys.stdout):
    """One table per (workload, params): a row per phase, a column pair
    (time, speedup-vs-baseline) per world/backend, then memory rows."""
    groups = {} # (workload, params) -> {(world, backend): rec}
    for (world, backend, workload, params), rec in records.items():
        groups.setdefault((workload, params), {})[(world, backend)] = rec

    mismatches = []
    for (workload, params), by_col in sorted(groups.items()):
        cols = sorted(by_col, key=lambda wb: (wb[0] != 'python',
            wb[1] != baseline, wb))
        col_names = [f"{w}:{b}" if w != 'python' else b for w, b in cols]

        checksums = {c: by_col[c].get('checksum') for c in by_col}
        present = {v for v in checksums.values() if v}
        if len(present) > 1:
            mismatches.append((workload, checksums))

        params_str = ' '.join(f"{k}={v}" for k, v in params
            if k not in ('scale', 'seed'))
        if fmt == 'md':
            print(f"\n## {workload} ({params_str})\n", file=out)

        phases = list(by_col[cols[0]]['phases'])
        base_col = next((c for c in cols if c[1] == baseline), None)
        headers = ['phase']
        for name in col_names:
            headers += [name, 'x']
        rows = []
        for ph in phases:
            row = [ph]
            base_ns = None
            if base_col is not None:
                base_ns = _stat(by_col[base_col]['phases'][ph]['wall_ns'],
                    stat)
            for c in cols:
                wall = by_col[c]['phases'].get(ph, {}).get('wall_ns')
                if not wall:
                    row += ['-', '-']
                    continue
                ns = _stat(wall, stat)
                row.append(_fmt_ns(ns))
                row.append(f"{base_ns/ns:.1f}" if base_ns and ns else '-')
            rows.append(row)
        for mem_key, label in (('tracemalloc_peak_bytes', 'peak mem'),
                ('retained_bytes', 'retained mem')):
            vals = {c: (by_col[c].get('mem') or {}).get(mem_key)
                for c in cols}
            if not any(v is not None for v in vals.values()):
                continue
            row = [label]
            base_v = vals.get(base_col)
            for c in cols:
                v = vals[c]
                row.append(_fmt_bytes(v) if v is not None else '-')
                row.append(f"{base_v/v:.1f}" if base_v and v else '-')
            rows.append(row)
        _emit_table(headers, rows, fmt, out)

    if mismatches:
        print("\nWARNING: checksum mismatches (results differ between "
            "backends/worlds!):", file=out)
        for workload, checksums in mismatches:
            print(f"  {workload}: {checksums}", file=out)
    return not mismatches

def check_sanity(records, stat='min', out=sys.stdout):
    """Assert the coarse expected relations between backends. Returns True
    when all checks that had data passed."""
    def phase_ns(workload, backend, phase):
        for (world, b, wl, params), rec in records.items():
            if world == 'python' and b == backend and wl == workload:
                wall = rec['phases'].get(phase, {}).get('wall_ns')
                if wall:
                    return _stat(wall, stat)
        return None

    def retained(workload, backend):
        for (world, b, wl, params), rec in records.items():
            if world == 'python' and b == backend and wl == workload:
                mem = rec.get('mem') or {}
                return mem.get('retained_bytes')
        return None

    ok = True
    def check(name, cond):
        nonlocal ok
        if cond is None:
            print(f"  skip  {name} (missing data)", file=out)
        elif cond:
            print(f"  ok    {name}", file=out)
        else:
            print(f"  FAIL  {name}", file=out)
            ok = False

    def rel(workload, phase, fast, slow):
        a = phase_ns(workload, fast, phase)
        b = phase_ns(workload, slow, phase)
        if a is None or b is None:
            return None
        return a <= b * 1.1 # 10% tolerance

    print("sanity relations:", file=out)
    check('patricia <= pvector on micro_remove_all',
        rel('micro_remove_all', 'remove',
            'pyrsistent-patricia', 'pyrsistent-pvector'))
    check('patricia <= pvector on micro_replace',
        rel('micro_replace', 'replace',
            'pyrsistent-patricia', 'pyrsistent-pvector'))
    check('patricia <= pvector on layout_flatten.expand',
        rel('layout_flatten', 'expand',
            'pyrsistent-patricia', 'pyrsistent-pvector'))
    fc = retained('snapshot_chain', 'fullcopy')
    others = [retained('snapshot_chain', b)
        for b in ('pyrsistent-patricia', 'cow', 'delta')]
    if fc is None or any(v is None for v in others):
        check('fullcopy retains most memory on snapshot_chain', None)
    else:
        check('fullcopy retains most memory on snapshot_chain',
            all(fc >= v for v in others))
    return ok

def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m benchmarks.report')
    parser.add_argument('files', nargs='+')
    parser.add_argument('--baseline', default='pyrsistent-pvector')
    parser.add_argument('--stat', default='min', choices=['min', 'median'])
    parser.add_argument('--format', default='md', choices=['md', 'csv'])
    parser.add_argument('--check-sanity', action='store_true')
    args = parser.parse_args(argv)

    records = load_results(args.files)
    ok = report(records, args.baseline, args.stat, args.format)
    if args.check_sanity:
        ok = check_sanity(records, args.stat) and ok
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main())
