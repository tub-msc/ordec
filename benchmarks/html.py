# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
HTML benchmark report: one self-contained page, no dependencies, no JS.

The report is built around a workload x backend matrix, because that is the
shape of the question ("which backend, and where does it lose?"). A matrix of
ratios *is* a table, so it is rendered as one, with cells shaded on a diverging
scale around the baseline. Per-workload phase breakdowns use the same
component, behind <details>, so the page opens on the summary rather than on
500 numbers.

Every cell carries its ratio and its absolute value as text: colour is never
the only channel, which also means the page survives printing and colour-vision
deficiency without a legend lookup.
"""

import html as _html
import math

from .report import _stat, _fmt_ns, _fmt_bytes, overall_wall_ns

MEM_KEYS = (('tracemalloc_peak_bytes', 'peak mem'),
            ('retained_bytes', 'retained mem'))

# Diverging scale around the baseline: blue = better, red = worse, neutral gray
# at parity (never a hue at the midpoint). Both arms stay light enough in light
# mode for near-black text, and dark enough in dark mode for white text, so
# contrast never depends on the value.
CSS = """
:root {
  color-scheme: light dark;
  --surface: #fcfcfb; --panel: #ffffff; --ink: #0b0b0b; --ink-2: #52514e;
  --muted: #898781; --rule: #e1e0d9; --cell-ink: #0b0b0b;
  --f4: #6da7ec; --f3: #9ec5f4; --f2: #cde2fb; --f1: #e8f1fd;
  --mid: #f0efec;
  --s1: #fdecec; --s2: #fbdcdc; --s3: #f7bcbc; --s4: #f19a9a;
}
@media (prefers-color-scheme: dark) {
  :root {
    --surface: #0d0d0d; --panel: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
    --muted: #898781; --rule: #2c2c2a; --cell-ink: #ffffff;
    --f4: #1c5cab; --f3: #184f95; --f2: #104281; --f1: #0d366b;
    --mid: #383835;
    --s1: #4a1f1f; --s2: #6b2626; --s3: #8f2d2d; --s4: #b03636;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 40px 24px 80px; background: var(--surface);
  color: var(--ink); font: 15px/1.55 system-ui, -apple-system, "Segoe UI",
  sans-serif;
}
main { max-width: 1080px; margin: 0 auto; }
h1 { font-size: 26px; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 17px; margin: 44px 0 6px; letter-spacing: -0.005em; }
p, .meta { color: var(--ink-2); margin: 0 0 6px; }
.meta { font-size: 12.5px; color: var(--muted); }
.lede { font-size: 16px; max-width: 62ch; margin: 10px 0 0; }
.lede b { color: var(--ink); }
.note { font-size: 13px; color: var(--muted); margin: 2px 0 14px;
  max-width: 76ch; }
.card {
  background: var(--panel); border: 1px solid var(--rule); border-radius: 10px;
  padding: 4px 14px 14px; margin-top: 12px; overflow-x: auto;
}
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th { font-weight: 600; color: var(--ink-2); text-align: center;
  padding: 10px 6px; font-size: 12px; white-space: nowrap; }
th.row { text-align: left; color: var(--ink); font-weight: 500; }
th.base { color: var(--ink); }
td { padding: 0; text-align: center; border: 2px solid var(--panel);
  border-radius: 6px; }
td div { border-radius: 5px; padding: 7px 8px; color: var(--cell-ink);
  font-variant-numeric: tabular-nums; }
td b { display: block; font-size: 13px; font-weight: 600; }
td span { display: block; font-size: 11px; opacity: 0.72; }
td.na div { color: var(--muted); background: transparent; }
.f4 div { background: var(--f4); } .f3 div { background: var(--f3); }
.f2 div { background: var(--f2); } .f1 div { background: var(--f1); }
.mid div { background: var(--mid); }
.s1 div { background: var(--s1); } .s2 div { background: var(--s2); }
.s3 div { background: var(--s3); } .s4 div { background: var(--s4); }
.key { display: flex; gap: 0; align-items: center; font-size: 11.5px;
  color: var(--muted); margin: 10px 0 0; flex-wrap: wrap; }
.key i { width: 34px; height: 12px; display: inline-block; }
.key span { padding: 0 8px; }
.key i.f4 { background: var(--f4); } .key i.f3 { background: var(--f3); }
.key i.f2 { background: var(--f2); } .key i.f1 { background: var(--f1); }
.key i.mid { background: var(--mid); }
.key i.s1 { background: var(--s1); } .key i.s2 { background: var(--s2); }
.key i.s3 { background: var(--s3); } .key i.s4 { background: var(--s4); }
details { margin-top: 10px; border-top: 1px solid var(--rule);
  padding-top: 10px; }
summary { cursor: pointer; font-weight: 500; padding: 4px 0;
  color: var(--ink); }
summary::marker { color: var(--muted); }
details .note { margin: 6px 0 0; }
footer { margin-top: 48px; color: var(--muted); font-size: 12px;
  border-top: 1px solid var(--rule); padding-top: 14px; }
"""

def _esc(s):
    return _html.escape(str(s))

def _name(world, backend):
    return f"{world}:{backend}" if world != 'python' else backend

def _bucket(ratio):
    """Diverging bucket for a baseline/value ratio. Log-spaced: the values
    span ~0.02x to ~90x, which a linear scale could not show at all."""
    if not ratio or ratio <= 0:
        return 'mid'
    lg = math.log10(ratio)
    if abs(lg) < 0.05: # within ~12% -- parity, not a difference
        return 'mid'
    arm = 'f' if lg > 0 else 's'
    step = min(4, 1 + int(abs(lg) / 0.3)) # ~2x per step
    return f'{arm}{step}'

def _ratio_text(ratio):
    if ratio >= 100 or ratio < 0.01:
        return f'{ratio:.0f}×' if ratio >= 100 else f'{ratio:.3f}×'
    return f'{ratio:.2f}×' if ratio < 10 else f'{ratio:.1f}×'

def _matrix(row_labels, cols, values, fmt, baseline):
    """values: {(row, col): raw}. Ratios are baseline/value per row."""
    out = ['<table><thead><tr><th class="row"></th>']
    for c in cols:
        cls = ' base' if c == baseline else ''
        label = _esc(c) + (' *' if c == baseline else '')
        out.append(f'<th class="col{cls}">{label}</th>')
    out.append('</tr></thead><tbody>')
    for r in row_labels:
        out.append(f'<tr><th class="row">{_esc(r)}</th>')
        base_v = values.get((r, baseline))
        for c in cols:
            v = values.get((r, c))
            if not v:
                out.append('<td class="na"><div><b>-</b><span>no data</span>'
                    '</div></td>')
                continue
            if c == baseline:
                out.append(f'<td class="mid"><div><b>baseline</b>'
                    f'<span>{_esc(fmt(v))}</span></div></td>')
                continue
            if not base_v:
                out.append(f'<td class="mid"><div><b>-</b>'
                    f'<span>{_esc(fmt(v))}</span></div></td>')
                continue
            ratio = base_v / v
            out.append(f'<td class="{_bucket(ratio)}"><div>'
                f'<b>{_ratio_text(ratio)}</b><span>{_esc(fmt(v))}</span>'
                f'</div></td>')
        out.append('</tr>')
    out.append('</tbody></table>')
    return ''.join(out)

def _key(better, worse):
    cells = ''.join(f'<i class="{c}"></i>' for c in
        ('f4', 'f3', 'f2', 'f1', 'mid', 's1', 's2', 's3', 's4'))
    return (f'<div class="key"><span>{_esc(better)}</span>{cells}'
        f'<span>{_esc(worse)}</span></div>')

def write_html(groups, baseline, stat, path, impl=None, out=None):
    """Write the whole report as one self-contained HTML page."""
    # groups is keyed by (workload, params); iterate the keys, not items().
    workloads = [wl for wl, _ in sorted(groups)]
    params_of = {wl: p for wl, p in sorted(groups)}
    entities = sorted({_name(*c) for by in groups.values() for c in by})
    cols = sorted(entities, key=lambda n: (n != baseline, n))

    def rec_of(wl, col):
        for c, rec in groups[(wl, params_of[wl])].items():
            if _name(*c) == col:
                return rec
        return None

    # --- totals matrix -----------------------------------------------------
    totals = {}
    for wl in workloads:
        for col in cols:
            rec = rec_of(wl, col)
            runs = overall_wall_ns(rec) if rec else None
            if runs:
                totals[(wl, col)] = _stat(runs, stat)

    # Headline, computed rather than asserted.
    wins = {}
    for wl in workloads:
        row = {c: totals[(wl, c)] for c in cols if (wl, c) in totals}
        if row:
            wins[min(row, key=row.get)] = wins.get(min(row, key=row.get), 0) + 1
    top = max(wins, key=wins.get) if wins else None

    p = []
    p.append('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">')
    p.append('<meta name="viewport" content="width=device-width,'
        'initial-scale=1">')
    p.append('<title>ORDB storage backend benchmarks</title>')
    p.append(f'<style>{CSS}</style></head><body><main>')
    p.append('<h1>ORDB storage backends</h1>')
    meta = '  '.join(f'{k}={v}' for k, v in (impl or {}).items())
    p.append(f'<div class="meta">{_esc(meta)}</div>' if meta else '')
    if top:
        p.append(f'<p class="lede">Fastest on <b>{wins[top]} of '
            f'{len(workloads)}</b> workloads: <b>{_esc(top)}</b>. Every cell '
            f'compares against <b>{_esc(baseline)}</b>; above 1.00× is better '
            f'than the baseline. Times are the <b>{_esc(stat)}</b> of the '
            f'timed repeats.</p>')

    p.append('<h2>Total time per workload</h2>')
    p.append('<div class="note">Every phase of the workload summed. '
        'Untimed setup belongs to no phase, so this is measured work, not '
        'wall time of a run.</div>')
    p.append('<div class="card">')
    p.append(_matrix(workloads, cols, totals, _fmt_ns, baseline))
    p.append(_key('faster than baseline', 'slower'))
    p.append('</div>')

    # --- memory ------------------------------------------------------------
    for key, label in MEM_KEYS:
        vals = {}
        for wl in workloads:
            for col in cols:
                rec = rec_of(wl, col)
                v = (rec.get('mem') or {}).get(key) if rec else None
                if v:
                    vals[(wl, col)] = v
        if not vals:
            continue
        p.append(f'<h2>{_esc(label)}</h2>')
        p.append('<div class="note">Ratios are baseline / value, so above '
            '1.00× means it used less memory.</div>')
        p.append('<div class="card">')
        p.append(_matrix(workloads, cols, vals, _fmt_bytes, baseline))
        p.append(_key('less memory', 'more'))
        p.append('</div>')

    # --- per-workload phases ----------------------------------------------
    p.append('<h2>Phase breakdown</h2>')
    p.append('<div class="note">Each workload\'s phases, same colour scale. '
        'Single-phase workloads are omitted: their phase is the total '
        'above.</div>')
    p.append('<div class="card">')
    any_detail = False
    for wl in workloads:
        rec0 = rec_of(wl, cols[0])
        phases = list(rec0['phases']) if rec0 else []
        if len(phases) < 2:
            continue
        any_detail = True
        vals = {}
        for ph in phases:
            for col in cols:
                rec = rec_of(wl, col)
                runs = rec['phases'].get(ph, {}).get('wall_ns') if rec else None
                if runs:
                    vals[(ph, col)] = _stat(runs, stat)
        par = ' '.join(f'{k}={v}' for k, v in params_of[wl]
            if k not in ('scale', 'seed'))
        p.append(f'<details><summary>{_esc(wl)}</summary>'
            f'<div class="note">{_esc(par)}</div>')
        p.append(_matrix(phases, cols, vals, _fmt_ns, baseline))
        p.append('</details>')
    if not any_detail:
        p.append('<div class="note">No multi-phase workloads in this run.</div>')
    p.append('</div>')

    p.append('<footer>Generated by <code>python -m benchmarks.report '
        '--html</code>. Cells show the ratio to the baseline and the absolute '
        'value; colour is a redundant channel.</footer>')
    p.append('</main></body></html>')

    page = '\n'.join(x for x in p if x)
    # Explicit utf-8: the page declares that charset, and the ratios use U+00D7.
    with open(path, 'w', encoding='utf-8') as f:
        f.write(page)
    if out:
        print(f'wrote {path}', file=out)
    return path
