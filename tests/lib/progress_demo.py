# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Sleep loops reporting nested and parallel progress, for trying out the
progress display of the web UI, e.g.:

    ordec tests/lib/progress_demo.py -e "parallel()"
"""

import time
from ordec.core import *

def task(label, steps, dt=0.05):
    """Sleeps steps times for dt seconds, reporting its progress."""
    with progress_scope(label):
        for i in range(steps):
            progress("Sleeping", i / steps,
                detail=f"{i * dt:.2f}s / {steps * dt:.2f}s")
            time.sleep(dt)
    return label

@viewgen_noctx
def nested():
    """Tasks one after the other: overall progress and that of the
    running task."""
    with progress_scope("Batch", steps=5):
        for i in range(5):
            task(f"task {i}", 40)
    return "done"

@viewgen_noctx
def parallel():
    """Tasks of different lengths, four at a time."""
    with progress_scope("Batch", steps=8):
        parallel_map(lambda i: task(f"task {i}", 20 + 10 * i), range(8))
    return "done"
