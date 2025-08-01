# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.core import *

def test_viewgen_return_string():
    num_viewgen_calls = 0

    class MyCell(Cell):
        @generate
        def hello(self):
            nonlocal num_viewgen_calls
            num_viewgen_calls += 1
            return "world"

    assert num_viewgen_calls == 0
    assert MyCell().hello == 'world'
    assert num_viewgen_calls == 1
    assert MyCell().hello == 'world'
    assert num_viewgen_calls == 1 # Make sure the view generator is only called once.

def test_viewgen_return_nonhashable():
    class MyCell(Cell):
        @generate
        def hello(self):
            return {}

    with pytest.raises(TypeError):
        MyCell().hello

def test_viewgen_freeze():
    class MyCell(Cell):
        @generate
        def schematic_freeze_implicit(self):
            return Schematic(cell=self)

        @generate
        def schematic_freeze_explicit(self):
            return Schematic(cell=self).freeze()

    assert isinstance(MyCell().schematic_freeze_implicit, Schematic.Frozen)
    assert isinstance(MyCell().schematic_freeze_explicit, Schematic.Frozen)
