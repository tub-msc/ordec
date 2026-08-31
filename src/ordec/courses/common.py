# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Helpers shared by the lesson checks of all courses (the checks.py of each
course package).

A half-finished design is an expected state, not an error: a check that
cannot be evaluated yet explains itself, and tracebacks are reserved for
failures that persist once the structure is correct.
"""

import traceback


def exception_text() -> str:
    """Format the current exception for display in a PassFail element."""
    return "The check raised an exception:\n" + traceback.format_exc()


def blocked_passfails(report, labels, hints, reason):
    """
    Emits one failing PassFail per label for a group of checks that could
    not be evaluated, all sharing the same reason. Keeps the number of
    PassFail elements of a lesson the same in every state.
    """
    for label, hint in zip(labels, hints):
        report.passfail(label, False, instructions=reason, hint=hint)


def sim_failure_text(structure_ok, what, structure_check="structure check"):
    """
    Explains why a group of simulation-based checks could not be measured.
    An unexpected error is worth its traceback, a design that is not fully
    wired up is not: that state is expected while the user is still typing.
    structure_check names the check that already reports the incomplete
    structure.
    """
    if structure_ok:
        return exception_text()
    return (f"The simulation failed -- usually {what} is still incomplete "
        f"(see the {structure_check} above).")
