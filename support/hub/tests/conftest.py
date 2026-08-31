# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the hub-side deployment scripts (scoreboard.py, rescore.py).
Not part of the default test run (pytest.ini ignores support/); run them
explicitly with `pytest support/hub/tests`. test_scoreboard.py needs
tornado, which ships with the hub image rather than with ordec[test].
"""

import sys
from pathlib import Path

# Make the main test suite importable (tests.test_course provides the
# course reference solutions that test_rescore.py verifies against).
sys.path.insert(0, str(Path(__file__).parents[3]))
