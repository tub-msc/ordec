# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import threading
import subprocess
import sys
import pytest

from ordec.core import (
    progress, checkpoint, cancelable_subprocess, cancelable_wait, GenCancelled)
from ordec.core.genrun import GenRun

def test_noop_without_active_run():
    # Must be safe to call from pytest / plain scripts.
    progress("doing something", 0.5)
    progress("message only")
    checkpoint()
    with cancelable_subprocess(None):
        pass

def test_progress_reported():
    events = []
    run = GenRun(on_progress=lambda s, f, d: events.append((s, f)))
    with run.activate():
        progress("step 1")
        progress("step 2", 0.5)
    assert events == [("step 1", None), ("step 2", 0.5)]

def test_progress_detail_reported():
    events = []
    run = GenRun(on_progress=lambda s, f, d: events.append((s, f, d)))
    with run.activate():
        progress("Transient simulation", 0.25, detail="1.2ms / 5ms")
        progress("plain")
    assert events == [
        ("Transient simulation", 0.25, "1.2ms / 5ms"),
        ("plain", None, None),
    ]

def test_progress_without_sink():
    run = GenRun()
    with run.activate():
        progress("no sink attached", 0.1)

def test_checkpoint_raises_after_cancel():
    run = GenRun()
    with run.activate():
        checkpoint()
        run.request_cancel()
        with pytest.raises(GenCancelled):
            checkpoint()

def test_progress_raises_after_cancel():
    events = []
    run = GenRun(on_progress=lambda s, f, d: events.append((s, f)))
    with run.activate():
        run.request_cancel()
        with pytest.raises(GenCancelled):
            progress("should not be reported")
    assert events == []

def test_cancelled_is_not_exception_subclass():
    # User code catching Exception must not swallow cancellation.
    assert not issubclass(GenCancelled, Exception)

def test_contextvar_reset_after_activate():
    run = GenRun(on_progress=lambda s, f, d: pytest.fail("run leaked"))
    with run.activate():
        pass
    progress("outside")  # no-op again

def sleeper_process():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])

def test_cancel_kills_registered_subprocess():
    run = GenRun()
    p = sleeper_process()
    try:
        with run.activate(), cancelable_subprocess(p):
            run.request_cancel()
            assert p.wait(timeout=5) != 0
    finally:
        p.kill()
        p.wait()

def test_cancel_before_register_kills_subprocess():
    # Cancellation racing with process launch: registering after cancel
    # must kill immediately.
    run = GenRun()
    run.request_cancel()
    p = sleeper_process()
    try:
        with run.process_registered(p):
            assert p.wait(timeout=5) != 0
    finally:
        p.kill()
        p.wait()

def test_deregistered_subprocess_not_killed():
    run = GenRun()
    p = sleeper_process()
    try:
        with run.process_registered(p):
            pass
        run.request_cancel()
        assert p.poll() is None  # still running
    finally:
        p.kill()
        p.wait()

def test_cancel_sets_registered_wakeup():
    run = GenRun()
    ev = threading.Event()
    with run.activate(), cancelable_wait(ev):
        assert not ev.is_set()
        run.request_cancel()
        assert ev.wait(timeout=5)

def test_cancel_before_register_sets_wakeup():
    # Cancellation racing with registration: a thread that registers after
    # the cancel must not block forever.
    run = GenRun()
    run.request_cancel()
    ev = threading.Event()
    with run.wakeup_registered(ev):
        assert ev.wait(timeout=5)

def test_deregistered_wakeup_not_set():
    run = GenRun()
    ev = threading.Event()
    with run.wakeup_registered(ev):
        pass
    run.request_cancel()
    assert not ev.is_set()

def test_wakeup_unblocks_waiting_thread():
    # The point of the registry: block on ev, get woken by cancellation.
    run = GenRun()
    ev = threading.Event()
    woke = []
    def waiter():
        with run.activate(), cancelable_wait(ev):
            ev.wait()
        woke.append(True)
    t = threading.Thread(target=waiter)
    t.start()
    run.request_cancel()
    t.join(timeout=5)
    assert not t.is_alive()
    assert woke == [True]

def test_noop_wait_without_active_run():
    # No run active: pass-through, ev must still work normally.
    ev = threading.Event()
    with cancelable_wait(ev):
        ev.set()
        assert ev.wait(timeout=5)

def test_run_is_thread_local():
    # A run activated in one thread must not leak into another thread.
    events = []
    run = GenRun(on_progress=lambda s, f, d: events.append(s))
    barrier = threading.Barrier(2)
    def other_thread():
        barrier.wait()
        progress("from other thread")  # must be a no-op there
        barrier.wait()
    t = threading.Thread(target=other_thread)
    t.start()
    with run.activate():
        barrier.wait()
        barrier.wait()
        progress("from main thread")
    t.join()
    assert events == ["from main thread"]
