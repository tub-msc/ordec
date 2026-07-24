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

    a1 = A(l=1, w=2)
    assert a1.l == R(1)
    assert a1.w == R(2)
    assert isinstance(a1.params, PMap)
    assert a1.params['l'] == R(1)
    assert a1.params['w'] == R(2)

    # Basic type coercion:
    a2 = A(l=1, w=3)
    assert a2.l == R(1)
    assert a2.w == R(3)

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

# -- Concurrency semantics of Future-based view caching ----------------------

import threading
import time
from ordec.core.genrun import GenRun

def test_viewgen_concurrent_waiter_gets_result():
    calls = []
    release = threading.Event()

    class MyCell(Cell):
        @generate
        def slow(self):
            calls.append(threading.get_ident())
            release.wait(timeout=10)
            return "done"

    results = []
    def worker():
        results.append(MyCell().slow)
    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    time.sleep(0.2)  # let one thread become owner, others waiters
    release.set()
    for t in threads:
        t.join()
    assert results == ["done"] * 3
    assert len(calls) == 1  # generated exactly once

def test_viewgen_exception_not_cached_and_seen_by_waiter():
    calls = []
    release = threading.Event()

    class MyCell(Cell):
        @generate
        def failing(self):
            calls.append(None)
            if len(calls) == 1:
                release.wait(timeout=10)
                raise ValueError("generation failed")
            return "recovered"

    errors = []
    def worker():
        try:
            MyCell().failing
        except ValueError as e:
            errors.append(e)
    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    release.set()
    for t in threads:
        t.join()
    # Ordinary exceptions propagate to owner and waiter alike, without the
    # waiter re-running the generator.
    assert len(errors) == 2
    assert len(calls) == 1
    assert MyCell().failing == "recovered"  # exception was not cached

def test_viewgen_cancelled_owner_promotes_waiter():
    owner_started = threading.Event()
    owner_run = GenRun()
    calls = []

    class MyCell(Cell):
        @generate
        def view(self):
            calls.append(None)
            if len(calls) == 1:
                owner_started.set()
                while True:  # simulates long work; exits via checkpoint
                    checkpoint()
                    time.sleep(0.01)
            return "from retry"

    owner_result = []
    def owner():
        with owner_run.activate():
            try:
                MyCell().view
            except GenCancelled:
                owner_result.append("cancelled")
    waiter_result = []
    def waiter():
        owner_started.wait(timeout=10)
        waiter_result.append(MyCell().view)

    t1 = threading.Thread(target=owner)
    t2 = threading.Thread(target=waiter)
    t1.start()
    t2.start()
    owner_started.wait(timeout=10)
    time.sleep(0.2)  # let the waiter start waiting on the owner's Future
    owner_run.request_cancel()
    t1.join()
    t2.join()
    assert owner_result == ["cancelled"]
    assert waiter_result == ["from retry"]  # waiter retried as owner
    assert len(calls) == 2

def test_viewgen_recursive_evaluation_raises():
    class MyCell(Cell):
        @generate
        def selfref(self):
            return MyCell().selfref

    with pytest.raises(RuntimeError, match="[Rr]ecursive"):
        MyCell().selfref

def test_generate_func_caches_once():
    calls = []

    @generate_func
    def myview():
        calls.append(None)
        return "value"

    assert myview() == "value"
    assert myview() == "value"
    assert len(calls) == 1

def test_generate_func_rejected_in_cell_class():
    # A generate_func is not a descriptor: as a Cell class attribute it
    # would look like a view method but silently evaluate its
    # cell-independent view. MetaCell must reject it loudly, both at
    # class creation and on later assignment.
    @generate_func
    def stray():
        return "value"

    with pytest.raises(TypeError, match="function-form view generators"):
        class MyCell(Cell):
            stray_view = stray

    class OtherCell(Cell):
        pass

    with pytest.raises(TypeError, match="function-form view generators"):
        OtherCell.stray_view = stray
