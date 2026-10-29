# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Progress reporting and cancellation for view generation.

A :class:`GenRun` represents one view-generation job. While it is
activated (see :meth:`GenRun.activate`), the module-level functions
:func:`progress`, :func:`progress_scope`, :func:`checkpoint` and
:func:`cancelable_subprocess` operate on it. Without an active run (pytest,
plain scripts, docs builds), they are exact no-ops, so library code can call
them unconditionally.

Progress is a tree: the run's root node, below it one node per open
:func:`progress_scope`. :func:`progress` updates the innermost open scope
(or the root). Every change sends a snapshot of the whole tree to the run's
on_progress callback.

The active run and the current progress node are stored in ContextVars.
Note that ContextVars do not propagate into threads spawned by the
generator itself; :func:`parallel_map` runs its calls in copies of the
caller's context for that reason.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from public import public

_run_var = ContextVar("gen_run", default=None)
_node_var = ContextVar("progress_node", default=None)

class ProgressNode:
    """
    One node of a run's progress tree. label is fixed (the
    :func:`progress_scope` argument, None for the root); status, fraction
    and detail are set by :func:`progress`.

    With steps, the node counts its finished child scopes. Unless set
    explicitly, its fraction is then derived from them and its detail
    reads "done/steps".
    """
    def __init__(self, label=None, steps=None):
        self.label = label
        self.steps = steps
        self.done = 0
        self.status = None
        self.fraction = None
        self.detail = None
        # Child scopes; None marks the slot of a closed one (see
        # GenRun.scope).
        self.children = []
        # Highest derived fraction so far: a child that restarts (e.g. a
        # second simulation in the same scope) must not move the bar back.
        self.derived = 0.0

    def snapshot(self) -> dict:
        # A free slot stays in the snapshot as None, so that the web UI
        # keeps the cells of the running siblings in place.
        children = [c and c.snapshot() for c in self.children]
        fraction, detail = self.fraction, self.detail
        if self.steps:
            if fraction is None:
                running = sum(c['fraction'] or 0.0 for c in children if c)
                self.derived = max(self.derived,
                    min((self.done + running) / self.steps, 1.0))
                fraction = self.derived
            if detail is None:
                detail = f"{self.done}/{self.steps}"
        return {
            'label': self.label,
            'status': self.status,
            'fraction': fraction,
            'detail': detail,
            'children': children,
        }

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
        # callable(tree: dict), tree as returned by ProgressNode.snapshot()
        self.on_progress = on_progress
        self.root = ProgressNode()
        self.cancel_event = threading.Event()
        self._procs = {}  # id(popen) -> popen
        self._wakeups = set()  # threading.Events to set on cancellation
        self._lock = threading.Lock()
        # Guards the progress tree. Held while on_progress runs, so that
        # snapshots from several threads arrive in order.
        self._tree_lock = threading.Lock()

    # -- generator side --------------------------------------------------

    def progress(self, status: str, fraction: float=None, detail: str=None,
            node: ProgressNode=None):
        """
        Report progress of node (default: root); doubles as a
        cancellation checkpoint.
        """
        self.checkpoint()
        node = node or self.root
        with self._tree_lock:
            node.status = status
            node.fraction = fraction
            node.detail = detail
            self._emit()

    @contextmanager
    def scope(self, parent: ProgressNode, label: str, steps: int=None):
        """Child node of parent for the duration of the block."""
        self.checkpoint()
        node = ProgressNode(label, steps)
        with self._tree_lock:
            # A new scope takes the first slot that a closed sibling left,
            # so that parallel siblings keep their place in the web UI.
            if None in parent.children:
                parent.children[parent.children.index(None)] = node
            else:
                parent.children.append(node)
            self._emit()
        try:
            yield node
        finally:
            with self._tree_lock:
                parent.children[parent.children.index(node)] = None
                # Free slots go once all siblings are done; until then they
                # keep the remaining cells in place, width included.
                if not any(parent.children):
                    parent.children.clear()
                parent.done += 1
                self._emit()

    def _emit(self):
        if self.on_progress:
            self.on_progress(self.root.snapshot())

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
        node_token = _node_var.set(self.root)
        try:
            yield self
        finally:
            _node_var.reset(node_token)
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
def progress(status: str, fraction: float=None, detail: str=None):
    """
    Report progress from within a view generator. ``fraction`` (0.0-1.0),
    if given, drives a progress bar in the web UI; otherwise only the
    status message is shown. ``detail`` is free-form text shown next to the
    bar, for values that change on every update (e.g. "1.2ms / 3s"); unlike
    ``status`` it does not defeat the rate limiting of progress messages.
    Inside a :func:`progress_scope`, this reports the progress of that
    scope. Doubles as a cancellation :func:`checkpoint`. No-op when no
    view-generation run is active.
    """
    run = _run_var.get()
    if run is not None:
        run.progress(status, fraction, detail, _node_var.get())

@public
@contextmanager
def progress_scope(label: str, steps: int=None):
    """
    Report the progress of the block as a separate entry, nested in the
    enclosing scope. :func:`progress` calls in the block (including those
    of simulations it runs) update this entry. The entry disappears when
    the block ends.

    ``steps`` is the expected number of child scopes, e.g. the number of
    points of a sweep. With it, the entry shows the overall progress of
    its children ("3/9" and a progress bar) without further
    :func:`progress` calls. Entering doubles as a cancellation
    :func:`checkpoint`. No-op when no view-generation run is active.
    """
    run = _run_var.get()
    if run is None:
        yield
        return
    with run.scope(_node_var.get(), label, steps) as node:
        token = _node_var.set(node)
        try:
            yield
        finally:
            _node_var.reset(token)

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

@public
def parallel_map(fn, items, max_workers: int=4) -> list:
    """
    Like ``list(map(fn, items))``, but runs up to ``max_workers`` calls at
    once, each in a thread of its own, e.g. the simulations of a sweep.
    Each call runs in a copy of the caller's context, so :func:`progress`,
    :func:`progress_scope` and cancellation work inside fn. Returns the
    results in item order; the first exception (in item order) propagates
    once all calls have finished. With ``max_workers=1``, the calls run
    one after the other in the calling thread.

    fn should compute and return values; the caller writes them into its
    view afterwards. Writing from fn into the caller's view is not
    supported (ORDB allows one writing thread per subgraph at a time, and
    the calls may overlap). fn must not request the view that the caller
    is generating: unlike in the caller's own thread, this is not detected
    as a recursion and waits until cancelled.
    """
    if max_workers == 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers) as executor:
        # One context copy per call: a Context cannot be entered by two
        # threads at once.
        futures = [executor.submit(copy_context().run, fn, item)
            for item in items]
    return [f.result() for f in futures]
