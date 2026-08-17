# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from pyrsistent import PMap
from ordec.core import *

def test_viewgen_return_string():
    num_viewgen_calls = 0

    class MyCell(Cell):
        @viewgen_noctx
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
        @viewgen_noctx
        def hello(self):
            return {}

    with pytest.raises(TypeError):
        MyCell().hello

def test_viewgen_freeze():
    class MyCell(Cell):
        @viewgen_noctx
        def schematic_freeze_implicit(self):
            return Schematic(cell=self)

        @viewgen_noctx
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

def test_params_list_hides_default_bool():
    class A(Cell):
        x = Parameter(int)
        m = Parameter(int, default=1)
        flag = Parameter(bool, default=True)

    # A boolean parameter at its default is omitted from the canonical name,
    # while a non-default bool and non-bool defaults (m) are kept.
    assert repr(A(x=2)) == "A(x=2,m=1)"
    assert repr(A(x=2, flag=False)) == "A(x=2,m=1,flag=False)"

# -- Concurrency semantics of Future-based view caching ----------------------

import threading
import time
from ordec.core.genrun import GenRun

def test_viewgen_concurrent_waiter_gets_result():
    calls = []
    release = threading.Event()

    class MyCell(Cell):
        @viewgen_noctx
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
        @viewgen_noctx
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
        @viewgen_noctx
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
        @viewgen_noctx
        def selfref(self):
            return MyCell().selfref

    with pytest.raises(RuntimeError, match="[Rr]ecursive"):
        MyCell().selfref

def test_viewgen_function_form_caches_once():
    calls = []

    @viewgen_noctx
    def myview():
        calls.append(None)
        return "value"

    assert myview() == "value"
    assert myview() == "value"
    assert len(calls) == 1

def test_viewgen_without_receiver_rejected_in_cell_class():
    # A view generator without a receiver parameter would look like a view
    # method as a Cell class attribute, but its body could not access the
    # cell. MetaCell must reject it loudly, both at class creation and on
    # later assignment.
    @viewgen_noctx
    def stray():
        return "value"

    with pytest.raises(TypeError, match="receiver parameter"):
        class MyCell(Cell):
            stray_view = stray

    class OtherCell(Cell):
        pass

    with pytest.raises(TypeError, match="receiver parameter"):
        OtherCell.stray_view = stray

def test_discoverable_instances_repr_roundtrip():
    # The web UI uses the repr of a discoverable instance as view name and
    # resolves a selected view by evaluating it in the user's namespace
    # (see server.py). For every discoverable instance of the shipped
    # libraries, the repr must therefore eval to the very same instance
    # with only the cell class name in scope.
    from ordec.lib import base, generic_mos, ihp130, sky130

    def all_subclasses(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from all_subclasses(sub)

    checked = 0
    for cls in set(all_subclasses(Cell)):
        if cls.__abstractmethods__:
            continue
        for inst in cls.discoverable_instances():
            assert eval(repr(inst), {cls.__name__: cls}) is inst
            checked += 1
    assert checked > 10  # the lib imports above must have been discovered

def test_viewgen_without_receiver_error_names_location():
    # The MetaCell error points at the generator's definition (file:line).
    @viewgen_noctx
    def stray():
        return "value"

    with pytest.raises(TypeError, match="test_cell.py"):
        class MyCell(Cell):
            stray_view = stray

def test_viewgen_with_receiver_called_as_function():
    @viewgen_noctx
    def method_form(self):
        return "value"

    with pytest.raises(TypeError, match="receiver parameter"):
        method_form()

def test_viewgen_shape_rejected_at_decoration():
    with pytest.raises(TypeError, match="Cell Parameters"):
        @viewgen_noctx
        def two_params(a, b):
            return "x"

    with pytest.raises(TypeError, match="Cell Parameters"):
        @viewgen_noctx
        def defaulted(a=1):
            return "x"

def test_viewgen_class_getattr_non_evaluating():
    calls = []

    class MyCell(Cell):
        @viewgen_noctx
        def view(self):
            calls.append(None)
            return "value"

    # Class-level access returns the generator itself without evaluating.
    assert isinstance(MyCell.view, viewgen_noctx)
    assert calls == []

def test_viewgen_no_annotation_no_root():
    @viewgen
    def empty():
        pass

    with pytest.raises(TypeError, match="produced no view"):
        empty()

def test_viewgen_node_op_without_annotation():
    from ordec.ord.context import root as ord_root

    @viewgen
    def bad():
        ord_root()

    with pytest.raises(TypeError, match="has no view root"):
        bad()

def test_viewgen_adoption_without_annotation():
    from ordec.ord.context import set_root

    @viewgen
    def adopted():
        sym = set_root(Symbol())
        sym.a = Pin(pintype=PinType.In)

    view = adopted()
    assert isinstance(view.a, Pin)

def test_noctx_must_return_view():
    class MyCell(Cell):
        @viewgen_noctx
        def nothing(self):
            pass

    with pytest.raises(TypeError, match="must return a view"):
        MyCell().nothing

def test_noctx_annotation_inert():
    class MyCell(Cell):
        @viewgen_noctx
        def hello(self) -> Symbol:
            return "not a symbol"

    assert MyCell().hello == "not a symbol"

def test_noctx_node_op_rejected_from_helper():
    # A stray node operation in a @viewgen_noctx body (also indirectly,
    # from a helper) errors instead of leaking into an outer context.
    from ordec.ord.context import root as ord_root

    def helper():
        return ord_root()

    class MyCell(Cell):
        @viewgen_noctx
        def bad(self):
            return helper()

    with pytest.raises(TypeError, match="use @viewgen"):
        MyCell().bad

def test_viewgen_method_form_per_cell_cache():
    # The same decorator instance serves as descriptor with a per-cell
    # cache: two cells with different parameters evaluate independently,
    # repeated access evaluates once.
    calls = []

    class MyCell(Cell):
        x = Parameter(int, optional=True)

        @viewgen_noctx
        def view(self):
            calls.append(self.x)
            return f"view{self.x}"

    assert MyCell(x=1).view == "view1"
    assert MyCell(x=2).view == "view2"
    assert MyCell(x=1).view == "view1"
    assert calls == [1, 2]
