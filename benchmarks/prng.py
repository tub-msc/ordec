# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Deterministic PRNG for reproducible workloads (see the "PRNG" section of
docs/dev/ordb_benchmark_workloads.rst).

64-bit LCG with Knuth's MMIX constants; each step outputs the upper 31 bits
of the new state. Trivially reimplementable in any language with 64-bit
unsigned arithmetic, so all worlds generate bit-identical workloads.
"""

_MASK64 = (1 << 64) - 1
_MUL = 6364136223846793005
_INC = 1442695040888963407

class Lcg:
    __slots__ = ('state',)

    def __init__(self, seed: int):
        self.state = seed & _MASK64

    def next(self) -> int:
        """Advance and return an integer in [0, 2**31)."""
        self.state = (self.state * _MUL + _INC) & _MASK64
        return self.state >> 33

    def randint(self, n: int) -> int:
        """Integer in [0, n). Modulo bias is irrelevant for benchmark use
        and keeps the cross-language spec trivial."""
        return self.next() % n
