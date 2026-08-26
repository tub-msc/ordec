# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
support/hub/rescore.py: the verified final ranking of amp_competition
submissions, in the --json mode the scoreboard's "Final scoring" button
uses and the table the CLI prints.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from .test_course import course_data, courses_testdata

RESCORE = Path(__file__).parent.parent / 'support' / 'hub' / 'rescore.py'


def load_rescore():
    spec = importlib.util.spec_from_file_location('rescore', RESCORE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def submissions():
    lesson = course_data('amp_competition')['lessons'][0]
    good = courses_testdata['amp_competition'].lessons[0].solution_src(lesson)
    # A tampered testbench (no load) makes the live check report a higher
    # gain at 1 MHz; rescoring grafts only Amp into the pristine harness,
    # so it must verify identically to the honest submission.
    tampered = good.replace("Cap cload: .$c=1p", "Cap cload: .$c=1f")
    assert tampered != good
    return [
        {'team': 'honest', 'score': 30.0, 'source': good},
        {'team': 'cheat', 'score': 1.0, 'source': tampered},
        {'team': 'empty', 'score': 5.0, 'source': lesson['src']},
        {'team': 'lurker', 'score': None, 'source': None},
        # Last build failed a check on the live board, but the pushed
        # source verifies: ranked, flagged.
        {'team': 'shy', 'score': None, 'source': good},
    ]


def test_rescore_json(tmp_path):
    infile = tmp_path / 'submissions.json'
    infile.write_text(json.dumps(submissions()))
    proc = subprocess.run([sys.executable, str(RESCORE), '--json',
        str(infile)], capture_output=True, text=True, check=True)
    results = {r['team']: r for r in json.loads(proc.stdout)}
    assert list(results) == ['honest', 'cheat', 'empty', 'lurker', 'shy']

    assert results['honest']['fails'] == []
    assert abs(results['honest']['verified'] - 30.0) < 0.5
    assert results['cheat']['fails'] == []
    assert results['cheat']['verified'] == results['honest']['verified']
    assert results['cheat']['claimed'] == 1.0
    assert results['empty']['verified'] is None
    assert results['empty']['fails']
    assert results['lurker'] == {'team': 'lurker', 'claimed': None,
        'verified': None,
        'fails': ["registered, but never pushed a build"]}
    assert results['shy']['fails'] == []
    assert results['shy']['verified'] == results['honest']['verified']


def test_print_ranking(capsys):
    rescore = load_rescore()
    rescore.print_ranking([
        {'team': 'b', 'claimed': 30.55, 'verified': 30.5, 'fails': []},
        {'team': 'a', 'claimed': 1.0, 'verified': 20.0, 'fails': []},
        {'team': 'c', 'claimed': None, 'verified': 40.0, 'fails': []},
        {'team': 'x', 'claimed': 5.0, 'verified': None,
            'fails': ['gain 3.00 < 20']},
    ])
    out = capsys.readouterr().out.splitlines()
    assert out[1].split() == ['1', 'a', '20.00', 'uA', '1.00', 'uA',
        '(!)', 'claim', 'differs']
    assert out[2].split() == ['2', 'b', '30.50', 'uA', '30.55', 'uA']
    assert out[3].split() == ['3', 'c', '40.00', 'uA', '-',
        '(!)', 'no', 'live', 'score']
    assert 'out of ranking: x (claimed 5.00 uA)' in out
    assert '    gain 3.00 < 20' in out
