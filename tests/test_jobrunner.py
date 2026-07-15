# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import threading
import time
import pytest

from ordec.core import progress, checkpoint
from ordec.jobrunner import (
    InlineJobRunner, ThreadedJobRunner, JobState, ASYNC_CANCEL_ENABLED,
)

class Collector:
    """Records progress and terminal callbacks of one job."""
    def __init__(self):
        self.progress = []
        self.done = threading.Event()
        self.result = None
        self.cancelled = None

    def on_progress(self, status, fraction, detail=None):
        self.progress.append((status, fraction))

    def on_done(self, job, result, cancelled):
        assert not self.done.is_set(), "terminal delivered twice"
        self.result = result
        self.cancelled = cancelled
        self.done.set()

    def wait(self, timeout=10):
        assert self.done.wait(timeout), "job did not finish"

def test_inline_runs_synchronously():
    c = Collector()
    order = []
    def fn():
        order.append('fn')
        progress("working", 0.5)
        return 42
    pm = InlineJobRunner()
    job = pm.submit(fn, c.on_progress, c.on_done)
    order.append('after_submit')
    assert order == ['fn', 'after_submit']
    assert job.state == JobState.DONE
    assert (c.result, c.cancelled) == (42, False)
    assert c.progress == [("working", 0.5)]

def test_threaded_runs_and_reports():
    c = Collector()
    pm = ThreadedJobRunner(2)
    def fn():
        progress("step", 0.25)
        return "ok"
    job = pm.submit(fn, c.on_progress, c.on_done)
    c.wait()
    assert (c.result, c.cancelled) == ("ok", False)
    assert c.progress == [("step", 0.25)]
    assert job.state == JobState.DONE

def test_threaded_respects_max_jobs():
    pm = ThreadedJobRunner(2)
    running = []
    max_running = []
    lock = threading.Lock()
    release = threading.Event()
    def fn():
        with lock:
            running.append(None)
            max_running.append(len(running))
        release.wait(timeout=10)
        with lock:
            running.pop()
    collectors = [Collector() for _ in range(5)]
    for c in collectors:
        pm.submit(fn, on_done=c.on_done)
    time.sleep(0.3)
    assert max(max_running) <= 2
    release.set()
    for c in collectors:
        c.wait()
    assert max(max_running) == 2

def test_cancel_queued_job_never_runs():
    pm = ThreadedJobRunner(1)
    release = threading.Event()
    blocker_c, queued_c = Collector(), Collector()
    ran = []
    pm.submit(lambda: release.wait(timeout=10), on_done=blocker_c.on_done)
    time.sleep(0.1)  # ensure the blocker occupies the slot
    queued = pm.submit(lambda: ran.append(None), on_done=queued_c.on_done)
    pm.cancel(queued)
    queued_c.wait(1)  # cancelled terminal delivered immediately
    assert queued_c.cancelled is True
    release.set()
    blocker_c.wait()
    time.sleep(0.2)  # give the queued job's thread time to wake and exit
    assert ran == []
    assert queued.state == JobState.CANCELLED

def test_cancel_running_cooperative():
    pm = ThreadedJobRunner(1)
    c = Collector()
    started = threading.Event()
    def fn():
        started.set()
        while True:
            checkpoint()
            time.sleep(0.01)
    job = pm.submit(fn, on_done=c.on_done)
    assert started.wait(timeout=10)
    pm.cancel(job)
    c.wait()
    assert c.cancelled is True
    assert job.state == JobState.CANCELLED

@pytest.mark.skipif(not ASYNC_CANCEL_ENABLED,
    reason="async-exc cancellation not available on this interpreter")
def test_cancel_infinite_loop_via_async_exc():
    pm = ThreadedJobRunner(1)
    pm.cooperative_timeout = 0.2
    c = Collector()
    started = threading.Event()
    def fn():
        started.set()
        while True:  # no checkpoint: only async-exc can break this
            pass
    job = pm.submit(fn, on_done=c.on_done)
    assert started.wait(timeout=10)
    pm.cancel(job)
    c.wait()
    assert c.cancelled is True
    job._thread.join(5)
    assert not job._thread.is_alive()

def test_cancel_gives_up_on_stuck_thread():
    # A thread stuck in a C call (here: Event.wait) survives both rungs;
    # the ladder must still deliver the cancelled terminal exactly once.
    pm = ThreadedJobRunner(1)
    pm.cooperative_timeout = 0.2
    pm.async_exc_timeout = 0.2
    c = Collector()
    started = threading.Event()
    stuck = threading.Event()
    def fn():
        started.set()
        stuck.wait(timeout=30)  # blocking C call, unreachable by async-exc
    job = pm.submit(fn, on_done=c.on_done)
    assert started.wait(timeout=10)
    pm.cancel(job)
    c.wait()
    assert c.cancelled is True
    assert job.state == JobState.CANCELLED
    stuck.set()  # unblock; late runner completion must not deliver again
    job._thread.join(5)

def test_cancel_finished_job_is_noop():
    pm = ThreadedJobRunner(1)
    c = Collector()
    job = pm.submit(lambda: 1, on_done=c.on_done)
    c.wait()
    pm.cancel(job)  # must not raise or re-deliver
    assert c.result == 1

def test_cancel_kills_registered_subprocess():
    import subprocess, sys
    from ordec.core import cancelable_subprocess
    pm = ThreadedJobRunner(1)
    c = Collector()
    started = threading.Event()
    def fn():
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        with cancelable_subprocess(p):
            started.set()
            p.wait()  # blocks until cancel kills the process
            checkpoint()
    job = pm.submit(fn, on_done=c.on_done)
    assert started.wait(timeout=10)
    t0 = time.monotonic()
    pm.cancel(job)
    c.wait()
    assert c.cancelled is True
    assert time.monotonic() - t0 < 5  # kill unblocked the wait, no give-up rung
