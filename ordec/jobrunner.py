# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Execution of view-generation jobs.

A job runner is a stateless execution policy: it owns nothing beyond its
concurrency limit; every job is a freestanding :class:`Job` whose lifecycle
the caller tracks. Two implementations:

- :class:`InlineJobRunner`: runs the job synchronously in submit().
  No threads, no cancellation. Trivially-correct reference, also useful
  for tests and CLI/batch use.
- :class:`ThreadedJobRunner`: bounded number of concurrently running
  jobs, one fresh daemon thread per job. Supports cancellation via an
  escalation ladder (see :meth:`ThreadedJobRunner.cancel`).

Fresh threads (instead of a thread pool) keep async-exception injection
safe: an injected exception can only ever kill a disposable per-job
thread, never corrupt a pool worker loop.
"""

from abc import ABC, abstractmethod
from enum import Enum
import ctypes
import logging
import platform
import threading

from .core.genrun import GenRun, GenCancelled

logger = logging.getLogger(__name__)

#: Whether to use the async-exception rung of the cancellation ladder (see
#: :meth:`ThreadedJobRunner.cancel`). It relies on the CPython C API
#: (PyThreadState_SetAsyncExc), so it is unavailable on other Python
#: implementations. Set to False to disable that rung; cancellation then
#: falls back to giving up on generators that never reach a checkpoint.
ASYNC_CANCEL_ENABLED = platform.python_implementation() == 'CPython'

class JobState(Enum):
    QUEUED = 'queued'
    RUNNING = 'running'
    DONE = 'done'
    CANCELLED = 'cancelled'

class Job:
    """
    One view-generation job.

    fn is called with the job's GenRun activated, so progress()/
    checkpoint()/cancelable_subprocess() inside it report to this job.
    on_done(job, result, cancelled) is called exactly once per job; it
    receives the job itself because with InlineJobRunner it fires
    before submit() has returned the job to the caller.

    The state machine (guarded by _state_lock) enforces the exactly-once
    terminal delivery: whoever transitions the job out of RUNNING (the
    runner on completion, or the canceller when giving up on a stuck
    thread) delivers the terminal callback.
    """
    def __init__(self, fn, on_progress, on_done):
        self.fn = fn
        self.on_done = on_done
        self.run = GenRun(on_progress)
        self.state = JobState.QUEUED
        self._state_lock = threading.Lock()
        self._thread = None

class JobRunner(ABC):
    @abstractmethod
    def submit(self, fn, on_progress=None, on_done=None) -> Job:
        """Execute fn as a job; returns the Job handle."""

    def cancel(self, job: Job):
        """Request cancellation of a job. Default: not supported (no-op)."""

def _noop_on_done(job, result, cancelled):
    pass

class InlineJobRunner(JobRunner):
    """
    Runs each job synchronously inside submit(). Progress reporting works
    (delivered inline); cancellation is not possible.
    """
    def submit(self, fn, on_progress=None, on_done=None) -> Job:
        job = Job(fn, on_progress, on_done or _noop_on_done)
        job.state = JobState.RUNNING
        result = None
        cancelled = False
        try:
            with job.run.activate():
                result = job.fn()
        except GenCancelled:
            cancelled = True  # only possible if fn cancels its own run
        job.state = JobState.CANCELLED if cancelled else JobState.DONE
        job.on_done(job, result, cancelled)
        return job

def _async_raise(thread: threading.Thread, exc_type) -> bool:
    """
    Inject exc_type into thread at its next bytecode boundary. Returns
    True if the injection was registered. Cannot interrupt threads blocked
    in C calls (those are covered by subprocess killing instead). No-op
    when ASYNC_CANCEL_ENABLED is False.
    """
    if not ASYNC_CANCEL_ENABLED:
        return False
    ident = ctypes.c_ulong(thread.ident)
    n = ctypes.pythonapi.PyThreadState_SetAsyncExc(ident, ctypes.py_object(exc_type))
    if n > 1:
        # Per CPython docs: >1 means we hit more than one thread state;
        # undo to avoid corrupting unrelated threads.
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ident, None)
        return False
    return n == 1

class ThreadedJobRunner(JobRunner):
    """
    Runs jobs on fresh daemon threads, at most max_jobs concurrently
    (excess jobs wait their turn on a semaphore).
    """
    # Cancellation ladder timeouts; class attributes so tests can shorten them.
    cooperative_timeout = 2.0
    async_exc_timeout = 3.0

    def __init__(self, max_jobs: int):
        self.sem = threading.Semaphore(max_jobs)

    def submit(self, fn, on_progress=None, on_done=None) -> Job:
        job = Job(fn, on_progress, on_done or _noop_on_done)
        job._thread = threading.Thread(target=self._runner, args=(job,), daemon=True)
        job._thread.start()
        return job

    def _runner(self, job):
        self.sem.acquire()
        try:
            with job._state_lock:
                if job.state != JobState.QUEUED:
                    return  # cancelled while waiting for a slot
                job.state = JobState.RUNNING
            result = None
            cancelled = False
            try:
                with job.run.activate():
                    result = job.fn()
            except GenCancelled:
                cancelled = True
            except BaseException:
                # fn is expected to handle its own errors; anything escaping
                # here would otherwise vanish with the thread.
                logger.exception("unhandled exception in view-generation job")
            with job._state_lock:
                if job.state != JobState.RUNNING:
                    return  # canceller gave up on us and already delivered
                job.state = JobState.CANCELLED if cancelled else JobState.DONE
            job.on_done(job, result, cancelled)
        finally:
            self.sem.release()

    def cancel(self, job):
        """
        Cancellation escalation ladder:

        1. Cooperative: cancel flag raises GenCancelled at the job's
           next checkpoint()/progress(); registered subprocesses are killed
           (unblocking reads of their output).
        2. Async-exception injection (CPython only, optional): breaks
           pure-Python infinite loops that never reach a checkpoint.
        3. Give up: deliver the cancelled terminal anyway and leave the
           stuck thread be (it holds locks that must not be force-released;
           a source rebuild may stall until it finishes).

        Blocks the caller for up to cooperative_timeout + async_exc_timeout
        in the worst case. Idempotent; no-op for finished jobs.
        """
        with job._state_lock:
            if job.state == JobState.QUEUED:
                job.state = JobState.CANCELLED
                deliver = True  # runner will see CANCELLED and never run fn
            elif job.state == JobState.RUNNING:
                deliver = False
            else:
                return
        if deliver:
            job.on_done(job, None, True)
            return

        job.run.request_cancel()
        job._thread.join(self.cooperative_timeout)
        if job._thread.is_alive() and _async_raise(job._thread, GenCancelled):
            job._thread.join(self.async_exc_timeout)
        if job._thread.is_alive():
            with job._state_lock:
                if job.state != JobState.RUNNING:
                    return  # runner delivered in the meantime
                job.state = JobState.CANCELLED
            logger.warning(
                "view generator could not be interrupted; it keeps running "
                "in the background and a source rebuild may stall until it "
                "finishes. Restart the server if it appears stuck.")
            job.on_done(job, None, True)
