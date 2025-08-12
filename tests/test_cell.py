# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from pyrsistent import PMap
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


def test_param_inheritance():
    # Not sure whether this is useful for anything, but we have it so let's
    # test it.

    class A(Cell):
        l = Parameter(R)
        w = Parameter(R)

    class B(A):
        test = Parameter(R)

    class C(Cell):
        hello = Parameter(R)

    class D(B, C):
        world = Parameter(R)

    assert set(A._class_params.keys()) == {'l', 'w'}
    assert set(B._class_params.keys()) == {'l', 'w', 'test'}
    assert set(C._class_params.keys()) == {'hello'}
    assert set(D._class_params.keys()) == {'l', 'w', 'test', 'hello', 'world'}

def test_param_inst():
    class A(Cell):
        l = Parameter(R)
        w = Parameter(R)

    a1 = A(l=R('1'), w=R('2'))
    assert a1.l == R('1')
    assert a1.w == R('2')
    assert isinstance(a1.params, PMap)
    assert a1.params['l'] == R('1')
    assert a1.params['w'] == R('2')

    # Basic type coercion:
    a2 = A(l=1, w=3)
    assert a2.l == R('1')
    assert a2.w == R('3')

    assert a2 is not a1
    assert A(l=1, w=2) is a1
    assert A(l=1.0, w=2.0) is a1
    assert A(1, 2) is a1
    assert A(1, w=2) is a1
    assert A('1', '2') is a1

    with pytest.raises(ParameterError, match="Mandatory parameter 'l' is missing"):
        A()

    with pytest.raises(ParameterError, match="Expected type"):
        A(l=('invalid', 'value'), w=2)

    with pytest.raises(ParameterError, match="Too many parameters passed as positional arguments to"):
        A(1,2,3)

    with pytest.raises(ParameterError, match="passed both as positional and keyword argument"):
        A(1, l=1, w=3)

    with pytest.raises(ParameterError, match="has no parameter"):
        A(l=1, w=1, x=123)
