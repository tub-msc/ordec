# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.base import Node, View, Cell, UnattachedNode, IllegalGraphOperation, generate, ViewGenerator, attr, IntegrityError
from pyrsistent import PMap, pmap
import pytest
from contextlib import contextmanager
from collections.abc import Mapping


class DemoNode(Node):
    attr3 = attr(type=int|type(None))
    attr4 = attr(type=str|type(None))
    dictattr = attr(type=PMap, freezer=pmap)

    def check_integrity(self):
        if self.attr4 == "raise_integrity_error":
            raise IntegrityError("Integrity error test")

class DemoView(View):
    children: Mapping[str|int, DemoNode]

    attr1 = attr(type=int|type(None))
    attr2 = attr(type=str|type(None))

    def check_integrity(self):
        if self.attr2 == "raise_integrity_error":
            raise IntegrityError("Integrity error test")

class CellA(Cell):
    @generate(DemoView)
    def view1(self, node):
        """Node with two attributes a, b and no children."""
        
        node.attr1 = self.params.myparam + 1
        node.attr2 = str(self.params.myparam + 2)
    
    @generate(DemoView)
    def view2(self, node):
        """Node with 3 child nodes"""
        node.Child1 = DemoView()
        node.Child2 = DemoView()
        node.Child3 = DemoView()


def test_cell_instances():
    a = CellA()
    b = CellA()
    c = CellA(myparam=1)
    d = CellA(myparam=1)
    e = CellA(myparam=1, another_param=2)
    assert a is b
    assert a == b
    assert c is d
    assert a is not c
    assert a is not e
    assert d is not e
    assert a != c
    assert a != e

def test_view_instances():
    a = CellA(myparam=1)
    b = CellA(myparam=2)
    assert type(a.view1) == DemoView

    assert a.view1 != b.view1
    assert a.view1.parent == a
    assert b.view1.parent == b

    assert a.view1.attr1 == 2
    assert a.view1.attr2 == '3'
    assert b.view1.attr1 == 3
    assert b.view1.attr2 == '4'

def test_evaluate_trigger():
    class MyCell(Cell):
        @generate(DemoView)
        def view1(self, node):
            node.attr1 = 123
            node.subnode = DemoNode()
        
    @contextmanager
    def assert_view_evaluation(cell, viewname):
        assert viewname not in cell.children
        yield cell
        assert viewname in cell.children

    # MyCell with different i parameters are generated.
    # This ensures that we always get a fresh Cell with unevaluated view1.

    with assert_view_evaluation(MyCell(i=0), 'view1') as c:
        c.view1

def test_node_slots():
    """Ensure that Nodes do not have a __dict__ (Through the use of __slots__)."""

    class MyCell(Cell):
        @generate(DemoView)
        def view1(self, node):
            # Of a View node:
            with pytest.raises(AttributeError):
                object.__setattr__(node, 'myattrib', 123)

            # Of a Node subclass:
            node.subnode2 = DemoNode()
            with pytest.raises(AttributeError):
                object.__setattr__(node.subnode2, 'myattrib', 123)
    
    MyCell().view1

def test_unattached_nodes():
    u = Node(1, 2, 'three', kw1='hello', kw2='world')
    assert type(u) == UnattachedNode
    assert repr(u) == "UnattachedNode(Node(1, 2, 'three', kw1='hello', kw2='world'))"

    class MyCell(Cell):
        @generate(DemoView)
        def view1(self, node):
            u = DemoNode()
            node.child1 = u
            node.child2 = u

    with pytest.raises(IllegalGraphOperation):
        MyCell().view1

def test_cell_slots():
    class MyCell(Cell):
        @generate(DemoView)
        def view1(self, node):
            with pytest.raises(TypeError):
                self.hello = "world"

    MyCell().view1

def test_viewgenerator_exception():
    class MyException(Exception):
        pass

    class RaisesException(Cell):
        @generate(View)
        def view1(self, node):
            raise MyException()

    with pytest.raises(MyException):
        RaisesException().view1 

    # Same exception should be raised on repeated call:
    with pytest.raises(MyException):
        RaisesException().view1 


def test_cell_class_instance_scope():
    with pytest.deprecated_call():
        class MyCell(Cell):
            # The following two ways to declare a View are equivalent
            # (annotation vs. generation):

            def view1(cell, node) -> DemoView:
                node.child1 = DemoNode()
                node.attr2 = "world"

            @generate(DemoView)
            def view2(cell, node):
                node.child1 = DemoNode()
                node.attr2 = "foobar"

        assert type(MyCell.view1) == ViewGenerator
        assert MyCell().view1.attr2 == "world"
        assert type(MyCell().view1) == DemoView

        assert type(MyCell.view2) == ViewGenerator
        assert type(MyCell().view2) == DemoView
        assert MyCell().view2.attr2 == "foobar"
        assert type(MyCell.view2) == ViewGenerator


def test_view_cell_attachment():
    class MyCell(Cell):
        @generate(View)
        def view1(cell, node):
            assert cell.view1 is node
            assert node.parent is cell

    MyCell().view1

def test_cell_delattr():
    class MyCell(Cell):
        @generate(DemoView)
        def view1(cell, node):
            node.child1 = DemoNode()
            node.attr2 = "world"

    MyCell().view1
    with pytest.raises(TypeError):
        del MyCell().view1

def test_node_freeze():
    class MyCell(Cell):
        @generate(DemoView)
        def view1(cell, node):
            assert isinstance(node.children, dict)
            node.attr2 = "world"
            node.sub1 = DemoNode()
            node.sub1.dictattr = {1:2}

    assert isinstance(MyCell().view1.children, PMap)
    assert isinstance(MyCell().view1.sub1.dictattr, PMap)

def test_node_attr_overloading():
    class MyCell(Cell):
        @generate(DemoView)
        def view1(cell, node):
            node.sub1 = DemoNode()
            node.sub2 = DemoNode()
            del node.sub1

            node.attr1 = 123
            node.attr2 = "foo"

            with pytest.raises(TypeError):
                del node.attr1

            # Attempt to overwrite existing child:
            node.x = DemoNode(attr4="lalala")
            with pytest.raises(IllegalGraphOperation):
                node.x = Node(attr4="lololo")
            del node.x

    v = MyCell().view1

    assert v.attr1 == 123
    assert v.attr2 == "foo"
    assert len(v.children) == 1
    assert isinstance(v.children['sub2'], DemoNode)

    with pytest.raises(TypeError):
        del v.attr1

    with pytest.raises(TypeError):
        del v.sub2

def test_node_items_int():
    class MyCell(Cell):
        @generate(DemoView)
        def view1(cell, node):
            node[0] = DemoNode(attr4="foo")
            node[10] = DemoNode(attr4="bar")
            
            node[2] = DemoNode(attr4="world")
            del node[2]
            with pytest.raises(KeyError):
                MyCell().view1[2]

            # Attempt to overwrite existing child:
            with pytest.raises(IllegalGraphOperation):
                node[0] = DemoNode(attr4="foo")

            # Only ints allowed for [] item access:
            with pytest.raises(TypeError):
                node['hello'] = 'world'
            node.bla = DemoNode()
            with pytest.raises(TypeError):
                node['bla']

    assert MyCell().view1[0].attr4 == "foo"
    assert MyCell().view1[10].attr4 == "bar"
    with pytest.raises(KeyError):
        MyCell().view1[2]

def test_attr_typecheck():
    class MyCell(Cell):
        @generate(DemoView)
        def view1(cell, node):
            node.attr1 = "hello"
    
    with pytest.raises(TypeError, match=r"has attribute attr1 of illegal type"):
        MyCell().view1

def test_child_typecheck():
    class BadNode(Node):
        pass

    class MyCell(Cell):
        @generate(DemoView)
        def view1(cell, node):
            node.sub1 = BadNode()

    with pytest.raises(TypeError, match=r"has child .* of illegal type BadNode"):
        MyCell().view1

def test_child_key_typecheck():
    class ViewStrKeysOnly(View):
        children: Mapping[str, DemoNode]

    class MyCell(Cell):
        @generate(ViewStrKeysOnly)
        def view1(cell, node):
            node[123] = DemoNode()

    with pytest.raises(TypeError, match=r"has child key .* of illegal type int"):
        MyCell().view1

def test_check_integrity():
    class MyCell(Cell):
        @generate(DemoView)
        def view1(cell, node):
            node.attr2 = "raise_integrity_error"

        @generate(DemoView)
        def view2(cell, node):
            node.sub = DemoNode()
            node.sub.attr4 = "raise_integrity_error"

    with pytest.raises(IntegrityError, match=r"Integrity error test"):
        MyCell().view1

    with pytest.raises(IntegrityError, match=r"Integrity error test"):
        MyCell().view2
