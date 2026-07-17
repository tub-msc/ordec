# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Memory measurement helpers.

Timing repeats run without instrumentation; the runner performs one extra
instrumented pass per (workload, backend) with tracemalloc for allocation
peak, then measures the retained size of the objects the workload keeps
alive (its `retained` list, e.g. all generations of a snapshot chain).
"""

import sys
import gc
import types

# Object graph walk cut-off: shared/global objects that would drag in whole
# modules or class hierarchies and don't belong to the measured data.
_CUTOFF_TYPES = (
    type, types.ModuleType, types.FunctionType, types.BuiltinFunctionType,
    types.MethodType, types.GetSetDescriptorType, types.MemberDescriptorType,
)

def retained_bytes(objs) -> int:
    """
    Total sys.getsizeof over the object graph reachable from objs,
    deduplicated by id. Structure sharing between snapshots is therefore
    counted once -- the number to compare across backends. Caveats: C-level
    internals invisible to gc are undercounted; interned small ints/strings
    shared with the rest of the process are attributed to the graph.
    """
    seen = set()
    total = 0
    stack = list(objs)
    while stack:
        obj = stack.pop()
        i = id(obj)
        if i in seen:
            continue
        seen.add(i)
        if isinstance(obj, _CUTOFF_TYPES):
            continue
        try:
            total += sys.getsizeof(obj)
        except TypeError:
            continue
        stack.extend(gc.get_referents(obj))
    return total
