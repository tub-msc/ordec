# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Verified final ranking for amp_competition competition submissions.

Reads the scoreboard sqlite and re-scores every submission against the
pristine harness: the submitted Amp cell is grafted into the official
challenge.ord namespace, so a tampered testbench in the submission has no
effect. Gates and measurements come from ordec.courses.amp_competition.checks --
the same code the live check runs.

Executing a submission runs arbitrary Python by design. Run this inside a
throwaway container of the workshop user image, with no network:

    docker run --rm --network none -v "$PWD/support/hub:/w" ordec-hub-user \\
        python3 /w/rescore.py /w/scoreboard.sqlite

The scoreboard's "Final scoring" button does the same through the docker
socket: it ships this file plus the submissions as JSON into such a
container and reads the JSON result back (--json mode, see main).
"""

import argparse
import json
import signal
import sqlite3
import sys
import traceback
import importlib.resources

from ordec.language import compile_ord
from ordec import courses
from ordec.courses.amp_competition.checks import (
    GAIN_MIN, VOUT_DC_MIN, VOUT_DC_MAX, forbidden_devices, measure_corners)

TIMEOUT = 120  # seconds per submission (simulations included)

OFFICIAL_SRC = (importlib.resources.files(courses)
    / 'amp_competition' / 'challenge.ord').read_text()


def rescore(source):
    """(supply current in A, list of failure strings) for one submission."""
    fails = []
    ns_sub = {}
    exec(compile_ord(source, ns_sub, 'submission.ord'), ns_sub)
    if 'Amp' not in ns_sub:
        return None, ["no Amp cell in submission"]
    bad = forbidden_devices(ns_sub['Amp']().schematic)
    if bad:
        fails.append("forbidden devices: " + ", ".join(bad))
    # Graft the submitted Amp into the pristine harness: AmpTb resolves
    # 'Amp' from its module globals when the schematic view is built.
    ns = {}
    exec(compile_ord(OFFICIAL_SRC, ns, 'challenge.ord'), ns)
    ns['Amp'] = ns_sub['Amp']
    # Gates at every corner; the score is the nominal (first) corner's
    # supply current, as in the live check.
    rows = measure_corners(ns)
    for label, isup, vout_dc, gain in rows:
        if gain < GAIN_MIN:
            fails.append(f"gain {gain:.2f} < {GAIN_MIN:g} at {label}")
        if not VOUT_DC_MIN <= vout_dc <= VOUT_DC_MAX:
            fails.append(f"output DC level {vout_dc:.3f} V outside "
                f"{VOUT_DC_MIN:g}...{VOUT_DC_MAX:g} V at {label}")
    return rows[0][1], fails


def timed_out(signum, frame):
    raise TimeoutError(f"submission exceeded {TIMEOUT} s")


def rescore_all(entries):
    """
    Re-scores (team, claimed score in uA or None, source or None) entries.
    Returns one dict per entry: team, claimed, verified (supply current in
    uA; None when out of ranking) and fails (reasons; empty when ranked).
    """
    signal.signal(signal.SIGALRM, timed_out)
    results = []
    for team, claimed, source in entries:
        if source is None:
            isup, fails = None, ["registered, but never pushed a build"]
        else:
            signal.alarm(TIMEOUT)
            try:
                isup, fails = rescore(source)
            except Exception:
                isup, fails = None, ["rescore failed:\n"
                    + traceback.format_exc(limit=3)]
            finally:
                signal.alarm(0)
        results.append({'team': team, 'claimed': claimed,
            'verified': None if fails else isup * 1e6, 'fails': fails})
    return results


def print_ranking(results):
    ranked = sorted((r for r in results if not r['fails']),
        key=lambda r: r['verified'])
    print(f"{'#':>3} {'team':<24} {'verified':>12} {'claimed':>12}")
    for i, r in enumerate(ranked, 1):
        # A live score of None means the team's last build failed a check
        # (or its checks were tampered with to fail); the verified result
        # counts either way.
        if r['claimed'] is None:
            claimed, note = "-", "  (!) no live score"
        else:
            claimed = f"{r['claimed']:.2f} uA"
            note = "  (!) claim differs" \
                if abs(r['claimed'] - r['verified']) > 0.1 else ""
        print(f"{i:>3} {r['team']:<24} {r['verified']:>9.2f} uA "
            f"{claimed:>12}" + note)
    for r in results:
        if not r['fails']:
            continue
        claimed_s = f" (claimed {r['claimed']:.2f} uA)" \
            if r['claimed'] is not None else ""
        print(f"\nout of ranking: {r['team']}{claimed_s}")
        for f in r['fails']:
            print(f"    {f}")


def main():
    parser = argparse.ArgumentParser(description=
        "Re-score amp_competition submissions against the pristine harness.")
    parser.add_argument('db', help="scoreboard sqlite file, or with --json "
        "a JSON list of {team, score, source} objects")
    parser.add_argument('--json', action='store_true', help="read the "
        "submissions as JSON and print the results as JSON (for the "
        "scoreboard's final scoring)")
    args = parser.parse_args()
    if args.json:
        with open(args.db) as f:
            entries = [(e['team'], e['score'], e['source'])
                for e in json.load(f)]
        # Anything the submissions (or imports) print must not corrupt the
        # result: it is the last line of stdout, and the run itself is
        # redirected to stderr.
        result_out, sys.stdout = sys.stdout, sys.stderr
        results = rescore_all(entries)
        result_out.write('\n' + json.dumps(results) + '\n')
    else:
        entries = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True).execute(
            "SELECT team, score, source FROM entries "
            "ORDER BY score IS NULL, score").fetchall()
        print_ranking(rescore_all(entries))


if __name__ == '__main__':
    main()
