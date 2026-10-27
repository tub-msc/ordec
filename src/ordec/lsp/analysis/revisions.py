# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""Revisions of the inputs that analysis results are derived from.

Inputs are which files exist (key ``"files"``), document texts (key
``("doc", uri)``) and file contents read by the Python index (key
``("file", path)``, for a symlink also its target). Every change bumps the
revision of its input. A cached result stays valid while the revisions it
read are unchanged, so nothing derived needs to be invalidated by hand.
"""

# standard imports
from contextlib import contextmanager


class Revisions:
    """Input revision counters and the reads recorded while computing results."""
    def __init__(self):
        """Start all inputs at revision 0."""
        self.inputs = dict()
        self.frames = []

    def bump(self, key):
        """Record that the input under ``key`` changed."""
        self.inputs[key] = self.inputs.get(key, 0) + 1

    def read(self, key):
        """Return the revision of an input, recording the read for ``track()``."""
        revision = self.inputs.get(key, 0)
        if self.frames:
            self.frames[-1][key] = revision
        return revision

    @contextmanager
    def track(self):
        """Collect the input revisions read inside the block.

        The reads also count for an enclosing block, as its result depends
        on everything the nested one read.
        """
        reads = dict()
        self.frames.append(reads)
        try:
            yield reads
        finally:
            self.frames.pop()
            if self.frames:
                self.frames[-1].update(reads)

    def current(self, reads):
        """Return whether all recorded revisions are still the current ones.

        Like ``read()``, this counts for an enclosing ``track()`` block, as
        reusing a result depends on what it read.
        """
        return all(self.read(key) == revision for key, revision in reads.items())
