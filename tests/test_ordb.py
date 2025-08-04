# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
import re
from ordec.core import *
from tabulate import tabulate
import ordec.core.ordb

# Custom schema for testing:
class MyHead(SubgraphRoot):
    label = Attr(str)

class MyNode(Node):
    in_subgraphs=[MyHead]
    label = Attr(str)

class test_node_tuple():
    t = MyNode(label='hello')
    assert isinstance(t, MyNode.Tuple)
    assert t == MyNode.Tuple(label='hello')
    assert t.label == 'hello'
    assert t.set(label='world') == MyNode.Tuple(label='world')

    assert isinstance(MyNode.Tuple.label, ordec.core.ordb.NodeTupleAttrDescriptor)

def test_schema_attr_inheritance():
    assert [ad.name for ad in MyNode.Tuple._layout] == ['label']
    assert MyNode.Tuple.indices == []
    assert isinstance(MyNode.label, Attr) # This checks if AttrDescriptor works properly on the class itself.
    assert MyNode.label.type == str
    
    class ExtMyNode(MyNode):
        label = Attr(bytes)
    assert [ad.name for ad in ExtMyNode.Tuple._layout] == ['label']
    assert MyNode.label != ExtMyNode.label

    class ExtMyNode2(MyNode):
        weight = Attr(float)
        color = Attr(str)
        height = Attr(float)

        C1 = Index(weight, unique=True)
        C2 = CombinedIndex([color, height], unique=True)
    assert [ad.name for ad in ExtMyNode2.Tuple._layout] == ['label', 'weight', 'color', 'height']
    assert isinstance(ExtMyNode2.C1, Index)
    assert ExtMyNode2.Tuple.indices == [ExtMyNode2.C1, ExtMyNode2.C2]
    assert ExtMyNode2.label == MyNode.label

    class ExtMyNode3(ExtMyNode2):
        rating = Attr(int)
        weight = Attr(str)
    assert [ad.name for ad in ExtMyNode3.Tuple._layout] == ['label', 'weight', 'color', 'height', 'rating']
    assert ExtMyNode3.label == ExtMyNode2.label
    assert ExtMyNode3.weight != ExtMyNode2.weight
    assert ExtMyNode3.Tuple.indices == [ExtMyNode2.C2] # ExtMyNode2.C1 is not in indices anymore, because the corresponding attribute was removed.

def test_node():
    #n = Node()
    n = Pin(pintype=PinType.Inout, pos=Vec2R(x=R('2.'), y=R('4.')), align=D4.R180)
    m = n.set(pintype=PinType.Out)
    assert n.pintype == PinType.Inout
    assert m.pintype == PinType.Out
    assert n.align == D4.R180
    assert m.align == D4.R180

    with pytest.raises(AttributeError, match='has no attribute'):
        n.hello = 'world'

    with pytest.raises(AttributeError, match='read-only'):
        n.pintype = 123

    with pytest.raises(AttributeError, match='Unknown attributes provided: invalid'):
        n = Pin(invalid='hello')

    with pytest.raises(TypeError, match="is not iterable"):
        for x in n:
            pass

def test_node_hash_and_equiv():    
    class NodeA(Node):
        in_subgraphs=[MyHead]
        text = Attr(str)

    class NodeB(Node):
        in_subgraphs=[MyHead]
        text = Attr(str)

    a = NodeA(text='hello')
    b = NodeB(text='hello')

    assert a != b
    assert hash(a) != hash(b)

def test_node_attrs_hashable():
    with pytest.raises(TypeError):
        MyNode(label=['lists are not hashable'])

    s = MyHead()

    with pytest.raises(TypeError):
        s.label = ['lists are not hashable']

    with pytest.raises(TypeError):
        MyNode().set(label=['lists are not hashable'])

def test_attr_default():
    p = Pin(pos=Vec2R(0, 2))
    assert p.pos == Vec2R(0, 2)
    assert p.align == D4.R0
    assert p.pintype == PinType.Inout

def test_attr_undefined():
    with pytest.raises(AttributeError, match=r'Unknown attributes provided: invalid'):
        p = Pin(pos=Vec2R(4, 2), invalid='example')

def test_subgraph_load():
    with pytest.raises(ModelViolation, match=r"Missing root node"):
        MutableSubgraph.load({
            100: Pin(pintype=PinType.In, pos=Vec2R(x=R('0.'), y=R('2.')), align=D4.R0),
        })

    with pytest.raises(ModelViolation, match=r"Missing root node"):
        MutableSubgraph.load({
            100: Symbol.Tuple(outline=None, caption=None),
        })

    s_dict = {
        0: Symbol.Tuple(outline=None, caption=None),
        100: Pin(pintype=PinType.In, pos=Vec2R(x=R('0.'), y=R('2.')), align=D4.R0),
        101: NPath(parent=None, name='a', ref=100),
        102: Pin(pintype=PinType.Out, pos=Vec2R(x=R('4.'), y=R('2.')), align=D4.R0),
        103: NPath(parent=None, name='y', ref=102),
    }
    s = MutableSubgraph.load(s_dict).subgraph
    assert s.nodes[0] == s_dict[0]
    assert s.nodes[101] == s_dict[101]
    assert s.nodes[103] == s_dict[103]
    assert s.nodes[100] == s_dict[100]
    assert s.nodes[102] == s_dict[102]
    assert len(s.nodes) == len(s_dict)

def test_subgraph_dump():
    s = MyHead(label='head label')
    s.nodeA = MyNode(label='hello')
    s.nodeB = MyNode(label='world')

    d = s.subgraph.dump()

    s_restored = eval(d, globals(), locals())
    assert s.freeze() == s_restored.freeze()

def test_subgraph_table():
    ref_table = """Subgraph MyHead.Tuple(label='head label'):
  MyNode
  |   nid | label   |
  |-------|---------|
  |    93 | hello   |
  |    95 | world   |
  NPath
  |   nid | parent   | name   |   ref |
  |-------|----------|--------|-------|
  |    94 |          | nodeA  |    93 |
  |    96 |          | nodeB  |    95 |"""

    s = MyHead(label='head label')
    s.nodeA = MyNode(label='hello')
    s.nodeB = MyNode(label='world')
    #print(s.tables())

    table = s.subgraph.tables()
    assert re.sub(r"\s*[0-9]+", '<num>', table) == re.sub(r"\s*[0-9]+", '<num>', ref_table)

def test_subgraph_matches():
    ref = MutableSubgraph.load({
        0: Symbol.Tuple(outline=None, caption=None),
        100: Pin.Tuple(pintype=PinType.In, pos=Vec2R(x=R('0.'), y=R('2.')), align=D4.R0),
        101: NPath.Tuple(parent=None, name='a', ref=100),
        102: Pin.Tuple(pintype=PinType.Out, pos=Vec2R(x=R('4.'), y=R('2.')), align=D4.R0),
        103: NPath.Tuple(parent=None, name='y', ref=102),
    })

    # 1. create subgraph via Subgraph.add():
    s = Symbol()
    assert s.subgraph.root_cursor is s
    a_nid = s.subgraph.add(Pin(pintype=PinType.In, pos=Vec2R(0, 2)))
    a_path_nid = s.subgraph.add(NPath(name='a', ref=a_nid))
    y_nid = s.subgraph.add(Pin(pintype=PinType.Out, pos=Vec2R(4, 2)))
    y_path_nid = s.subgraph.add(NPath(name='y', ref=y_nid))
    assert s.matches(ref)

    # Change of attribute should lead to inequivalence:
    s2 = s.copy()
    assert s2.subgraph.root_cursor is s2
    s2.caption = "hello"
    assert not s2.matches(ref)
    # Original subgraph s should be unaffected:
    assert s.matches(ref)

    # Adding nodes should also lead to inequivalence:
    s3 = s.copy()
    s3.subgraph.add(Pin(pintype=PinType.In, pos=Vec2R(2, 0)))
    assert not s3.matches(ref)
    # Original subgraph s should be unaffected:
    assert s.matches(ref)

    # Removing nodes also lead to inequivalence:
    s4 = s.copy()
    with s4.updater() as u:
        u.remove_nid(a_nid)
        u.remove_nid(a_path_nid)
    assert not s4.matches(ref)
    # Original subgraph s should not unaffected:
    assert s.matches(ref)

    # 2. create subgraph using '%' shorthand (Subgraph.__mod__) instead of Subgraph.add:
    s5 = Symbol()
    a_cursor = s5 % Pin(pintype=PinType.In, pos=Vec2R(0, 2))
    with s5.updater() as u:
        NPath(name='a', ref=a_cursor.nid).insert_into(u)
    y_cursor = s5 % Pin(pintype=PinType.Out, pos=Vec2R(4, 2))
    with s5.updater() as u:
        NPath(name='y', ref=y_cursor.nid).insert_into(u)
    assert s5.matches(ref)

    # 3. create subgraph using implicit Node:
    s6 = Symbol()
    s6.a = Pin(pintype=PinType.In, pos=Vec2R(0, 2))
    s6.y = Pin(pintype=PinType.Out, pos=Vec2R(4, 2))
    assert s6.matches(ref)

def test_funcinserter():
    class Person(Node):
        in_subgraphs=[MyHead]
        best_friend = LocalRef(Node)

    ref = MutableSubgraph.load({
        0: MyHead.Tuple(label=None),
        22: Person(best_friend=23),
        23: Person(best_friend=22),
    })

    s = MyHead()
    def f(sgu):
        alice_nid = sgu.nid_generate()
        bob_nid = sgu.nid_generate()
        sgu.add_single(Person(best_friend=bob_nid), alice_nid)
        sgu.add_single(Person(best_friend=alice_nid), bob_nid)
    inserter = FuncInserter(f)
    s.subgraph.add(inserter)

    assert isinstance(inserter, Inserter)
    assert s.matches(ref)

def test_inserter_node():
    assert isinstance(MyNode(), Inserter)
    assert issubclass(MyNode.Tuple, Inserter)

def test_nid_generator():
    s = MyHead()
    # Initial nid_alloc range:
    assert s.subgraph.nid_alloc == range(1, 2**32)
    assert len(s.subgraph.nodes) == 1

    # Adding a node changes nid_alloc. The new node will have nid=2.
    with s.updater() as u:
        MyNode(label='hello').insert_into(u)
    assert s.subgraph.nid_alloc == range(2, 2**32)
    assert len(s.subgraph.nodes) == 2
    assert s.subgraph.nodes[1].label == 'hello'

    # Just generating nids but not adding nodes will not change s.nid_alloc:
    with s.updater() as u:
        assert u.nid_generate() == 2
        assert u.nid_generate() == 3
    assert s.subgraph.nid_alloc == range(2, 2**32)

    # Adding a custom nid will increase s.nid_alloc more:
    with s.updater() as u:
        u.add_single(MyNode(label='world'), 1234)
    assert s.subgraph.nodes[1234].label == 'world'
    assert s.subgraph.nid_alloc == range(1235, 2**32)

def test_updater():
    s_orig = MyHead()
    assert s_orig.subgraph.nid_alloc.start == 1
    s = s_orig.copy()
    assert s.subgraph.internally_equal(s_orig.subgraph)

    # This updater has no effect on s, because commit is set to False manually:
    with s.updater() as u:
        MyNode(label='hello').insert_into(u)
        MyNode(label='world').insert_into(u)
        MyNode(label='foo').insert_into(u)
        MyNode(label='bar').insert_into(u)
        u.commit = False    
    assert s.subgraph.internally_equal(s_orig.subgraph)

    # This updater has no effect on s, because a constraint check fails:
    with pytest.raises(DanglingLocalRef):
        with s.updater() as u:
            NPath(parent=None, name='a', ref=100).insert_into(u)
    assert s.subgraph.internally_equal(s_orig.subgraph)

    # This updater mutates s, as commit is True (default) and no constraint check fails:
    with s.updater() as u:
        MyNode(label='hello').insert_into(u)
        MyNode(label='world').insert_into(u)
        MyNode(label='foo').insert_into(u)
        MyNode(label='bar').insert_into(u)
    assert not s.subgraph.internally_equal(s_orig.subgraph)
    assert s.subgraph.nid_alloc.start == 5

    s = s_orig.copy()
    with s.updater() as u:
        MyNode(label='hello').insert_into(u)

    #TODO?

def test_localref_integrity():
    class Person(Node):
        in_subgraphs=[MyHead]
        best_friend = LocalRef(Node)
        worst_enemy = LocalRef(Node)

    s = MyHead()

    alice = s % Person()
    bob = s % Person(best_friend=alice)
    charlie = s % Person(worst_enemy=bob)

    alice.update(best_friend=bob, worst_enemy=charlie)
    
    dangling_ref = 123456

    # Dangling reference on node add:
    s_before = s.copy()
    with pytest.raises(DanglingLocalRef) as exc_info:
        s % Person(worst_enemy=dangling_ref)
    assert exc_info.value.nid == dangling_ref
    assert s.matches(s_before)

    # Dangling reference on node removal:
    s_before = s.copy()
    with pytest.raises(DanglingLocalRef) as exc_info:
        with s.updater() as u:
            u.remove_nid(bob.nid)
            # This fails because bob is missing!
    assert exc_info.value.nid == bob.nid
    assert s.matches(s_before)

    # Dangling reference on node update:
    s_before = s.copy()
    with pytest.raises(DanglingLocalRef) as exc_info:
        charlie.worst_enemy = dangling_ref
    assert exc_info.value.nid == dangling_ref
    assert s.matches(s_before)

    s_before = s.copy()
    with pytest.raises(DanglingLocalRef) as exc_info:
        s.subgraph.remove_nid(alice.nid)
        # We cannot remove alice (dangling LocalRef).
    assert exc_info.value.nid == alice.nid
    assert s.matches(s_before)

    # But if we remove its reference first, we can remove alice:
    bob.best_friend = charlie
    s.subgraph.remove_nid(alice.nid)

def test_index():
    # TODO!
    class NodeA(Node):
        in_subgraphs=[MyHead]
        color = Attr(int)
        Index(color)

    s = MyHead()
    s.node1 = NodeA(color=123)
    s.node2 = NodeA(color=123)
    
    #print(tabulate(s.index.items()))
    # TODO: Complete test.

def test_unique():
    # TODO: Extend this test
    class NodeU1(Node):
        in_subgraphs=[MyHead]
        label = Attr(str)
        unique_label = Index(label, unique=True)

    s = MyHead()
    s % NodeU1(label='hello')
    s2 = s.copy()
    with pytest.raises(UniqueViolation):
        s2 % NodeU1(label='hello')
    # Make sure neither the nodes nor the index was modified here:
    assert s2.subgraph.internally_equal(s.subgraph) 
    assert s2.subgraph.index == s.subgraph.index 

def test_cursor_remove():
    s = MyHead()
    s.node1 = MyNode(label='hello')
    s.node2 = MyNode(label='world')
    assert s.matches(MutableSubgraph.load({
        0: MyHead.Tuple(label=None),
        28: MyNode(label='hello'),
        29: NPath(parent=None, name='node1', ref=28),
        30: MyNode(label='world'),
        31: NPath(parent=None, name='node2', ref=30),
    }))

    del s.node2

    assert s.matches(MutableSubgraph.load({
        0: MyHead.Tuple(label=None),
        28: MyNode(label='hello'),
        29: NPath(parent=None, name='node1', ref=28),
    }))

    # Cannot delete node that does not exist:
    with pytest.raises(QueryException, match=r'Attribute or path .* not found'):
        del s.node2

    # Cannot delete attributes:
    with pytest.raises(TypeError, match=r'Attributes cannot be deleted.'):
        del s.node1.label

    # Cannot delete attributes, also for root node:
    with pytest.raises(TypeError, match=r'Attributes cannot be deleted.'):
        del s.label

def test_freeze():
    s = MyHead(label='head label')
    assert isinstance(s, MutableNode)
    assert isinstance(s, MyHead.Mutable)
    assert isinstance(s, MyHead)
    s.node1 = MyNode(label='hello')
    assert isinstance(s.node1, MutableNode)
    assert isinstance(s.node1, MyNode.Mutable)
    assert isinstance(s.node1, MyNode)
    s.node2 = MyNode(label='world')
    s.node1.label = 'ahoy'
    assert s.mutable

    s=s.freeze()
    assert not s.mutable
    assert isinstance(s, FrozenNode)
    assert isinstance(s, MyHead.Frozen)
    assert isinstance(s, MyHead)
    assert isinstance(s.node1, FrozenNode)
    assert isinstance(s.node1, MyNode.Frozen)
    assert isinstance(s.node1, MyNode)

    with pytest.raises(TypeError, match=r'Subgraph is already frozen.'):
        s.freeze()

    s_copy = s.thaw()
    assert s_copy.mutable
    s_copy.freeze()

    with pytest.raises(TypeError, match=r'Unsupported operation on FrozenSubgraph.'):
        s.node1.label = 'beep'

def test_hash_eq():
    a1 = MyHead(label='alice')
    a2 = MyHead(label='alice')
    b = MyHead(label='bob')

    # Mutable nodes/subgraphs behave like objects (each has an own 'identity'):
    assert len({hash(a1), hash(a2), hash(b)}) == 3
    assert len({hash(a1.subgraph), hash(a2.subgraph), hash(b.subgraph)}) == 3
    assert a1 != a2
    assert b != a1

    # Frozen subgraphs behave like immutable types (eq and hash match when they are internally equal):
    assert a1.subgraph.freeze() == a2.subgraph.freeze()
    assert a1.subgraph.freeze() is not a2.subgraph.freeze()
    assert len({
        hash(a1.subgraph.freeze()),
        hash(a2.subgraph.freeze()),
        hash(b.subgraph.freeze()),
        }) == 2
    assert len({
        hash(a1.subgraph.freeze()),
        hash(a2.subgraph.freeze()),
        hash(b.subgraph.freeze()),
        hash(a1.subgraph),
        hash(a2.subgraph),
        hash(b.subgraph),
        }) == 5

    # Frozen nodes also behave like immutable types:
    assert a1.freeze() == a2.freeze()
    assert a1.freeze() == a1.freeze()
    assert a1.freeze() is not a2.freeze()
    assert a1.freeze() is not a1.freeze()
    assert a1.freeze() != a1
    assert a1 != a1.freeze()
    assert b.freeze() != a1.freeze()
    assert len({
        hash(a1.freeze()),
        hash(a2.freeze()),
        hash(b.freeze()),
        }) == 2
    assert len({
        hash(a1.freeze()),
        hash(a2.freeze()),
        hash(b.freeze()),
        hash(a1),
        hash(a2),
        hash(b),
        }) == 5

def test_copy():
    from copy import copy
    
    a1 = MyHead(label='alice')
    a1.node1 = MyNode(label='hello')
    
    # copy() of SubgraphRoot is deep:
    a2 = a1.copy()
    a3 = copy(a1)
    assert a1 != a2
    assert a1 != a3
    assert a1.freeze() == a2.freeze()
    assert a1.freeze() is not a2.freeze()

    # Frozen Nodes are not copied.
    f = a1.freeze()
    assert f.copy() == f
    assert copy(f) == f
    assert f.copy() is f
    assert copy(f) is f

    # copy() of Nodes that are not SubgraphRoot is shallow:
    n1 = a1.node1
    n2 = copy(n1)
    assert n1 == n2
    assert n1 is n2
    with pytest.raises(AttributeError):
        n2.copy() # To prevent confusion, this method does not exist.

def test_cursor_attribute():
    s = MyHead(label='hi')
    assert s.label == 'hi'
    assert type(s) is MyHead.Mutable
    
    s.label = 'blub'

    with pytest.raises(TypeError, match=r'Attributes cannot be deleted.'):
        del s.label

def test_cursor_paths():
    class MyNodeNonLeaf(NonLeafNode):
        in_subgraphs=[MyHead]
        label = Attr(str)

    s = MyHead()
    s.mkpath('sub')

    npath_nid = s.sub.npath_nid
    npath  = s.sub.npath
    assert isinstance(s.sub.npath, NPath.Tuple)
    assert (npath.name, npath.parent, npath.ref) == ('sub', None, None)

    with pytest.raises(OrdbException):
        s['undefined']

    with pytest.raises(AttributeError):
        s.undefined

    s.sub.mkpath('sub')
    npath2 = s.sub.sub.npath
    assert (npath2.name, npath2.parent, npath2.ref) == ('sub', npath_nid, None)

    s.node1 = MyNode()
    npath3 = s.node1.npath
    assert (npath3.name, npath3.parent, npath3.ref) == ('node1', None, s.node1.nid)

    # Leaf nodes cannot have NPath children:
    with pytest.raises(AttributeError):
        s.node1.subnode = MyNode()

    # Non-leaf nodes can have NPath children. Not sure if this is helpful in any situation.
    s.node2 = MyNodeNonLeaf(label='hello')
    s.node2.subnode = MyNode(label='world')
    assert s.node2.subnode.label == 'world'
    assert s.node2.label == 'hello'

    # .parent:
    assert s.node2.parent == s
    assert s.node2.subnode.parent == s.node2
    assert s.sub.sub.parent.parent == s
    with pytest.raises(QueryException, match="Subgraph root has no parent"):
        s.parent

    # Test item access (x[y]):
    assert s['sub'] == s.sub # But the root cursor is.
    assert s.sub['sub'] == s.sub.sub # And other cursors are, too.

def test_full_path():
    s = MyHead()
    assert s.full_path_list() == []
    assert s.full_path_str() == "root_cursor"
    s.mkpath('hello')
    assert s.hello.full_path_list() == ['hello']
    assert s.hello.full_path_str() == 'hello'
    assert repr(s.hello) == 'PathNode.Mutable(path=hello)'
    s.hello.mkpath('world')
    assert s.hello.world.full_path_list() == ['hello', 'world']
    assert s.hello.world.full_path_str() == 'hello.world'
    assert repr(s.hello.world) == 'PathNode.Mutable(path=hello.world)'

    s.mkpath('array')
    s.array.mkpath(0)
    s.array.mkpath(123456789)
    s.array[0].mkpath('sub')
    assert s.array[0].sub.full_path_list() == ['array', 0, 'sub']
    assert s.array[0].sub.full_path_str() == 'array[0].sub'
    assert repr(s.array[0].sub) == 'PathNode.Mutable(path=array[0].sub)'
    assert s.array[123456789].full_path_str() == 'array[123456789]'
    assert repr(s.array[123456789]) == 'PathNode.Mutable(path=array[123456789])'

def test_cursor_paths_unique():
    s = MyHead()
    s.mkpath('sub')
    s.node1 = MyNode()

    s2 = s.copy()

    with pytest.raises(OrdbException, match=r"Path exists"):
        s2.mkpath('sub')
    assert s2.matches(s) # Make sure no partial insertion was done.

    with pytest.raises(OrdbException, match=r"Path exists"):
        s2.sub = MyNode()
    assert s2.matches(s) # Make sure no partial insertion was done.

    with pytest.raises(OrdbException, match=r"Path exists"):
        s2.mkpath('node1')
    assert s2.matches(s) # Make sure no partial insertion was done.

    with pytest.raises(OrdbException, match=r"Path exists"):
        s2.node1 = MyNode()
    assert s2.matches(s) # Make sure no partial insertion was done.

def test_polyvec2r():
    s = Symbol()

    s.poly = SymbolPoly(vertices=[Vec2R(1, 1), Vec2R(1, 3), Vec2R(3, 3)])
    
    it = iter(s.poly.vertices)
    assert next(it).pos == Vec2R(1, 1)
    assert next(it).pos == Vec2R(1, 3)
    assert next(it).pos == Vec2R(3, 3)
    with pytest.raises(StopIteration):
        next(it)

    # with pytest.raises(TypeError, match=r'Query descriptors cannot be deleted.'):
    #     del s.poly.vertices

def test_npath_double_reference():
    s = MyHead()
    nid = s.subgraph.add(MyNode(label='hello'))
    s.subgraph.add(NPath(parent=None, name='path1', ref=nid))
    # Two NPaths are not allowed to reference the same node:
    with pytest.raises(UniqueViolation):
        s.subgraph.add(NPath(parent=None, name='path2', ref=nid))

def test_cursor_at_npath():
    s = MyHead()
    node_without_npath = s % MyNode(label='hello')
    s.node_with_npath = MyNode(label='world')
    assert s.node_with_npath.npath_nid > 0
    
    # cursor_at for a node without NPath returns a cursor without npath_nid.
    c_node_without_npath = s.subgraph.cursor_at(node_without_npath.nid)
    assert c_node_without_npath.nid == node_without_npath.nid
    assert c_node_without_npath.npath_nid == None

    # cursor_at for a node with NPath returns a cursor where npath_nid was looked up:
    c_node_with_npath = s.cursor_at(s.node_with_npath.nid)
    assert c_node_with_npath.nid == s.node_with_npath.nid
    assert c_node_with_npath.npath_nid == s.node_with_npath.npath_nid

    # ...unless lookup_npath is set to False.
    c_node_with_npath = s.cursor_at(s.node_with_npath.nid, lookup_npath=False)
    assert c_node_with_npath.nid == s.node_with_npath.nid
    assert c_node_with_npath.npath_nid == None

def test_index_sort_nid():
    class MyItem(Node):
        in_subgraphs=[MyHead]
        ref    = LocalRef(MyNode)
        order  = Attr(int)
        idx_ref = Index(ref)

    s = MyHead()
    with s.updater() as u:
        u.add_single(MyNode(), 1)
        u.add_single(MyItem(order=3, ref=1), 100)
        u.add_single(MyItem(order=2, ref=1), 98)
        u.add_single(MyItem(order=1, ref=1), 99)
        u.add_single(MyItem(order=4, ref=1), 102)
        u.add_single(MyItem(order=5, ref=1), 101)

    index_values = s.all(MyItem.idx_ref.query(1), wrap_cursor=False)
    assert index_values == [98, 99, 100, 101, 102] # ordered by nid

def test_index_custom_sort():
    class MyItem(Node):
        in_subgraphs=[MyHead]
        ref    = LocalRef(MyNode)
        order  = Attr(int)
        idx_ref = Index(ref, sortkey=lambda node: node.order)

    s = MyHead()
    with s.updater() as u:
        u.add_single(MyNode(), 1)
        u.add_single(MyItem(order=3, ref=1), 100)
        u.add_single(MyItem(order=2, ref=1), 98)
        u.add_single(MyItem(order=1, ref=1), 99)
        u.add_single(MyItem(order=4, ref=1), 102)
        u.add_single(MyItem(order=5, ref=1), 101)

    index_values = s.all(MyItem.idx_ref.query(1), wrap_cursor=False)
    assert index_values == [99, 98, 100, 102, 101] # ordered by node.order

def test_subgraph_ntype():
    s = MyHead()
    assert isinstance(s, MyHead)
    assert isinstance(s.node, MyHead.Tuple)

def test_all_ntype():
    class NodeA(Node):
        in_subgraphs=[MyHead]
        text = Attr(str)

    class NodeB(Node):
        in_subgraphs=[MyHead]
        text = Attr(str)

    s = MyHead()
    s % NodeA(text="A1")
    s % NodeA(text="A2")
    s % NodeB(text="B1")
    s % NodeB(text="B2")

    q1 = s.all(NodeA)
    assert [c.text for c in q1] == ['A1', 'A2']
    q2 = s.all(NodeB)
    assert [c.text for c in q2] == ['B1', 'B2']

def test_cursor_localref():
    class MyNodeItem(Node):
        in_subgraphs=[MyHead]
        ref = LocalRef(MyNode)
        text = Attr(str)

    s = MyHead()
    s.n1 = MyNode()
    n1_foo = s.n1 % MyNodeItem(text='n1 foo')

    assert n1_foo.ref == s.n1

def test_cursor_externalref():
    class NodeExtRef(Node):
        in_subgraphs=[MyHead]
        subg = SubgraphRef(MyHead)
        eref = ExternalRef(MyNode, of_subgraph=lambda c: c.subg)

    s1 = MyHead()
    s1.n1 = MyNode(label='hello')
    s1 = s1.freeze()

    s2 = MyHead()
    s2.n1 = MyNode(label='world')
    s2 = s2.freeze()

    s3 = MyHead()
    s3.e1 = NodeExtRef(subg=s1, eref=s1.n1.nid)
    s3.e2 = NodeExtRef(subg=s2, eref=s2.n1.nid)

    assert s3.e1.eref == s1.n1
    assert s3.e2.eref == s2.n1

def test_typecheck_simple():
    class NodeA(Node):
        in_subgraphs=[MyHead]
        text = Attr(str)

    with pytest.raises(TypeError):
        NodeA(text=123)

def test_typecheck_custom():
    class NodeA(Node):
        in_subgraphs=[MyHead]
        size = Attr(int, typecheck_custom=lambda v: isinstance(v, int) and v >=0)

    NodeA(size=123)

    with pytest.raises(TypeError):
        NodeA(size=-1)

def test_mandatory():
    class NodeA(Node):
        in_subgraphs=[MyHead]
        text = Attr(str, optional=False)

    NodeA(text='hello')

    with pytest.raises(TypeError):
        NodeA()

    with pytest.raises(TypeError):
        NodeA(text=None)

def test_refcheck_localref():
    class NodeA(Node):
        in_subgraphs=[MyHead]
        text = Attr(str)

    class NodeB(Node):
        in_subgraphs=[MyHead]
        text = Attr(str)

    class NodeRef(Node):
        in_subgraphs=[MyHead]
        ref = LocalRef(NodeA)

    s = MyHead()
    s.a = NodeA()
    s.b = NodeB()
    s % NodeRef(ref=s.b)

    with pytest.raises(ModelViolation):
        s % NodeRef(ref=s.a)

def test_refcheck_localref():
    class NodeA(Node):
        in_subgraphs=[MyHead]
        text = Attr(str)

    class NodeRef(Node):
        in_subgraphs=[MyHead]
        ref = LocalRef(NodeA, optional=False)

    with pytest.raises(TypeError):
        NodeRef()
        
def test_typecheck_subgraphref():
    class AnotherHead(SubgraphRoot):
        label = Attr(str)

    class NodeExtRef(Node):
        in_subgraphs=[MyHead]
        subg = SubgraphRef(MyHead)

    e1 = MyHead().freeze()
    e2 = AnotherHead().freeze()

    NodeExtRef(subg=e1)

    with pytest.raises(TypeError):
        NodeExtRef(subg=e2)

def test_subgraphref_mandatory():
    class NodeExtRef(Node):
        in_subgraphs=[MyHead]
        subg = SubgraphRef(MyHead, optional=False)

    e1 = MyHead().freeze()
    
    NodeExtRef(subg=e1)

    with pytest.raises(TypeError):
        NodeExtRef()

    with pytest.raises(TypeError):
        NodeExtRef(subg=None)
