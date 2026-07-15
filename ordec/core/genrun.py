# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Progress reporting and cancellation for view generation.

A :class:`GenRun` represents one view-generation job. While it is
activated (see :meth:`GenRun.activate`), the module-level functions
:func:`progress`, :func:`checkpoint` and :func:`cancelable_subprocess`
operate on it. Without an active run (pytest, plain scripts, docs builds),
they are exact no-ops, so library code can call them unconditionally.

The active run is stored in a ContextVar. Note that ContextVars do not
propagate into threads spawned by the generator itself; use
contextvars.copy_context().run(...) if that is ever needed.
"""

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from public import public

_run_var = ContextVar("gen_run", default=None)

@public
class GenCancelled(BaseException):
    """
    Raised inside a view generator when its run has been cancelled.

    Subclasses BaseException so that user-level ``except Exception:``
    blocks cannot swallow the cancellation.
    """

class GenRun:
    """
    State of a single view-generation job: progress sink, cancel flag and
    registries of things to act on when cancelled -- external-tool
    subprocesses to kill and events to set.

    The generator side runs with the GenRun activated and calls
    :meth:`progress` / :meth:`checkpoint` (usually through the module-level
    functions). The canceller side (another thread) calls
    :meth:`request_cancel`.
    """
    def __init__(self, on_progress=None):
        self.on_progress = on_progress  # callable(status: str, fraction: float|None)
        self.cancel_event = threading.Event()
        self._procs = {}  # id(popen) -> popen
        self._wakeups = set()  # threading.Events to set on cancellation
        self._lock = threading.Lock()

    # -- generator side --------------------------------------------------

    def progress(self, status: str, fraction: float=None):
        """Report progress; doubles as a cancellation checkpoint."""
        self.checkpoint()
        if self.on_progress:
            self.on_progress(status, fraction)

    def checkpoint(self):
        """Raise GenCancelled if cancellation has been requested."""
        if self.cancel_event.is_set():
            raise GenCancelled()

    @contextmanager
    def process_registered(self, p):
        """
        Register subprocess p (a Popen) for the duration of the block:
        cancellation kills it, unblocking any thread reading its output.
        """
        with self._lock:
            self._procs[id(p)] = p
            if self.cancel_event.is_set():
                p.kill()  # cancel raced with process launch
        try:
            yield
        finally:
            with self._lock:
                self._procs.pop(id(p), None)

    @contextmanager
    def wakeup_registered(self, ev):
        """
        Register threading.Event ev for the duration of the block:
        cancellation sets it, waking a thread that blocks on it. Lets a
        thread wait on some other condition and its own cancellation at
        once, without polling either.
        """
        with self._lock:
            self._wakeups.add(ev)
            if self.cancel_event.is_set():
                ev.set()  # cancel raced with registration
        try:
            yield
        finally:
            with self._lock:
                self._wakeups.discard(ev)

    @contextmanager
    def activate(self):
        """
        Make this run the active one for the current context. Must be
        entered in the thread that executes the view generator.
        """
        token = _run_var.set(self)
        try:
            yield self
        finally:
            _run_var.reset(token)

    # -- canceller side ---------------------------------------------------

    def request_cancel(self):
        """
        Request cooperative cancellation: the next checkpoint()/progress()
        in the generator raises GenCancelled, all registered subprocesses
        are killed and all registered wakeup events are set immediately.
        """
        with self._lock:
            self.cancel_event.set()
            for p in self._procs.values():
                p.kill()
            for ev in self._wakeups:
                ev.set()

@public
def progress(status: str, fraction: float=None):
    """
    Report progress from within a view generator. ``fraction`` (0.0-1.0),
    if given, drives a progress bar in the web UI; otherwise only the
    status message is shown. Doubles as a cancellation :func:`checkpoint`.
    No-op when no view-generation run is active.
    """
    run = _run_var.get()
    if run is not None:
        run.progress(status, fraction)

@public
def checkpoint():
    """
    Cancellation checkpoint: raises :class:`GenCancelled` if the
    active run has been cancelled. No-op when no run is active.
    """
    run = _run_var.get()
    if run is not None:
        run.checkpoint()

@public
@contextmanager
def cancelable_subprocess(p):
    """
    Register subprocess p with the active view-generation run so that
    cancellation kills it. Plain pass-through when no run is active.
    """
    run = _run_var.get()
    if run is None:
        yield
    else:
        with run.process_registered(p):
            yield

@public
@contextmanager
def cancelable_wait(ev):
    """
    Register threading.Event ev with the active view-generation run, so
    that cancellation sets it. This makes a blocking ``ev.wait()`` inside
    the block wake up on cancellation as well as on whatever else sets ev.
    Plain pass-through when no run is active.
    """
    run = _run_var.get()
    if run is None:
        yield
    else:
        with run.wakeup_registered(ev):
            yield
