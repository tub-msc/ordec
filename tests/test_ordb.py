# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
import re
from ordec.core import *
from tabulate import tabulate


# Custom schema for testing:
class MyHead(SubgraphRoot):
    label = Attr(str)

class MyNode(Node):
    label = Attr(str)

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
        text = Attr(str)

    class NodeB(Node):
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
    assert s.subgraph == s_restored.subgraph

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

def test_subgraph_equiv():
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
    a_nid = s.add(Pin(pintype=PinType.In, pos=Vec2R(0, 2)))
    a_path_nid = s.add(NPath(name='a', ref=a_nid))
    y_nid = s.add(Pin(pintype=PinType.Out, pos=Vec2R(4, 2)))
    y_path_nid = s.add(NPath(name='y', ref=y_nid))
    assert s.subgraph == ref.subgraph

    # Change of attribute should lead to inequivalence:
    s2 = s.copy()
    assert s2.subgraph.root_cursor is s2
    s2.caption = "hello"
    assert s2.subgraph != ref.subgraph
    # Original subgraph s should be unaffected:
    assert s.subgraph == ref.subgraph

    # Adding nodes should also lead to inequivalence:
    s3 = s.copy()
    s3.add(Pin(pintype=PinType.In, pos=Vec2R(2, 0)))
    assert s3 != ref
    # Original subgraph s should be unaffected:
    assert s.subgraph == ref.subgraph

    # Removing nodes also lead to inequivalence:
    s4 = s.copy()
    with s4.updater() as u:
        u.remove_nid(a_nid)
        u.remove_nid(a_path_nid)
    assert s4.subgraph != ref.subgraph
    # Original subgraph s should not unaffected:
    assert s.subgraph == ref.subgraph

    # 2. create subgraph using '%' shorthand (Subgraph.__mod__) instead of Subgraph.add:
    s5 = Symbol()
    a_cursor = s5 % Pin(pintype=PinType.In, pos=Vec2R(0, 2))
    s5 % NPath(name='a', ref=a_cursor.nid)
    y_cursor = s5 % Pin(pintype=PinType.Out, pos=Vec2R(4, 2))
    s5 % NPath(name='y', ref=y_cursor.nid)
    assert s5.subgraph == ref.subgraph

    # 3. create subgraph using implicit Node:
    s6 = Symbol()
    s6.a = Pin(pintype=PinType.In, pos=Vec2R(0, 2))
    s6.y = Pin(pintype=PinType.Out, pos=Vec2R(4, 2))
    assert s6.subgraph == ref.subgraph

def test_funcinserter():
    class Person(Node):
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
    s.add(inserter)

    assert isinstance(inserter, Inserter)
    assert s.subgraph == ref.subgraph

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
        u.add(MyNode(label='hello'))
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
        u.add(MyNode(label='hello'))
        u.add(MyNode(label='world'))
        u.add(MyNode(label='foo'))
        u.add(MyNode(label='bar'))
        u.commit = False    
    assert s.subgraph.internally_equal(s_orig.subgraph)

    # This updater has no effect on s, because a constraint check fails:
    with pytest.raises(DanglingLocalRef):
        with s.updater() as u:
            u.add(NPath(parent=None, name='a', ref=100))
    assert s.subgraph.internally_equal(s_orig.subgraph)

    # This updater mutates s, as commit is True (default) and no constraint check fails:
    with s.updater() as u:
        u.add(MyNode(label='hello'))
        u.add(MyNode(label='world'))
        u.add(MyNode(label='foo'))
        u.add(MyNode(label='bar'))
    assert not s.subgraph.internally_equal(s_orig.subgraph)
    assert s.subgraph.nid_alloc.start == 5

    s = s_orig.copy()
    with s.updater() as u:
        u.add(MyNode(label='hello'))

def test_localref_integrity():
    class Person(Node):
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
    assert s.subgraph == s_before.subgraph

    # Dangling reference on node removal:
    s_before = s.copy()
    with pytest.raises(DanglingLocalRef) as exc_info:
        with s.updater() as u:
            u.remove_nid(bob.nid)
            # This fails because bob is missing!
    assert exc_info.value.nid == bob.nid
    assert s.subgraph == s_before.subgraph

    # Dangling reference on node update:
    s_before = s.copy()
    with pytest.raises(DanglingLocalRef) as exc_info:
        charlie.worst_enemy = dangling_ref
    assert exc_info.value.nid == dangling_ref
    assert s.subgraph == s_before.subgraph

    s_before = s.copy()
    with pytest.raises(DanglingLocalRef) as exc_info:
        s.remove_nid(alice.nid)
        # We cannot remove alice (dangling LocalRef).
    assert exc_info.value.nid == alice.nid
    assert s.subgraph == s_before.subgraph

    # But if we remove its reference first, we can remove alice:
    bob.best_friend = charlie
    s.remove_nid(alice.nid)

def test_index():
    # TODO!
    class NodeA(Node):
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
        label = Attr(str)
        unique_label = Index(label, unique=True)

    s = MyHead()
    s % NodeU1(label='hello')
    s2 = s.copy()
    with pytest.raises(UniqueViolation):
        s2 % NodeU1(label='hello')
    assert s2.subgraph == s.subgraph and s2.subgraph.index == s.subgraph.index # Make sure neither the nodes nor the index was modified here.

def test_cursor_remove():
    s = MyHead()
    s.node1 = MyNode(label='hello')
    s.node2 = MyNode(label='world')
    assert s.subgraph == MutableSubgraph.load({
        0: MyHead.Tuple(label=None),
        28: MyNode(label='hello'),
        29: NPath(parent=None, name='node1', ref=28),
        30: MyNode(label='world'),
        31: NPath(parent=None, name='node2', ref=30),
    }).subgraph

    del s.node2

    assert s.subgraph == MutableSubgraph.load({
        0: MyHead.Tuple(label=None),
        28: MyNode(label='hello'),
        29: NPath(parent=None, name='node1', ref=28),
    }).subgraph

    # Cannot delete node that does not exist:
    with pytest.raises(QueryException, match=r'Path not found'):
        del s.node2

    # Cannot delete attributes:
    with pytest.raises(TypeError, match=r'Attributes cannot be deleted.'):
        del s.node1.label

    # Cannot delete attributes, also for root node:
    with pytest.raises(TypeError, match=r'Attributes cannot be deleted.'):
        del s.label

def test_freeze():
    s = MyHead(label='head label')
    s.node1 = MyNode(label='hello')
    s.node2 = MyNode(label='world')

    s.node1.label = 'ahoy'

    assert s.mutable
    with pytest.raises(TypeError, match="unhashable type"):
        hash(s.subgraph)
    s=s.freeze()
    assert not s.mutable
    hash(s.subgraph)

    with pytest.raises(TypeError, match=r'Subgraph is already frozen.'):
        s.freeze()

    s_copy = s.thaw()
    assert s_copy.mutable
    s_copy.freeze()

    with pytest.raises(TypeError, match=r'Unsupported operation on FrozenSubgraph.'):
        s.node1.label = 'beep'

def test_cursor_attribute():
    s = MyHead(label='hi')
    assert s.label == 'hi'
    assert type(s) is MyHead
    
    s.label = 'blub'

    with pytest.raises(TypeError, match=r'Attributes cannot be deleted.'):
        del s.label

def test_cursor_paths():
    class MyNodeNonLeaf(Node):
        label = Attr(str)
        is_leaf = False

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
    with pytest.raises(OrdbException, match=r"Cannot add NPath below existing NPath referencing leaf node."):
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
    assert repr(s.hello) == 'Node(path=hello)'
    s.hello.mkpath('world')
    assert s.hello.world.full_path_list() == ['hello', 'world']
    assert s.hello.world.full_path_str() == 'hello.world'
    assert repr(s.hello.world) == 'Node(path=hello.world)'

    s.mkpath('array')
    s.array.mkpath(0)
    s.array.mkpath(123456789)
    s.array[0].mkpath('sub')
    assert s.array[0].sub.full_path_list() == ['array', 0, 'sub']
    assert s.array[0].sub.full_path_str() == 'array[0].sub'
    assert repr(s.array[0].sub) == 'Node(path=array[0].sub)'
    assert s.array[123456789].full_path_str() == 'array[123456789]'
    assert repr(s.array[123456789]) == 'Node(path=array[123456789])'

def test_cursor_paths_unique():
    s = MyHead()
    s.mkpath('sub')
    s.node1 = MyNode()

    s2 = s.copy()

    with pytest.raises(OrdbException, match=r"Path exists"):
        s2.mkpath('sub')
    assert s2.subgraph == s.subgraph # Make sure no partial insertion was done.

    with pytest.raises(OrdbException, match=r"Path exists"):
        s2.sub = MyNode()
    assert s2.subgraph == s.subgraph # Make sure no partial insertion was done.

    with pytest.raises(OrdbException, match=r"Path exists"):
        s2.mkpath('node1')
    assert s2.subgraph == s.subgraph # Make sure no partial insertion was done.

    with pytest.raises(OrdbException, match=r"Path exists"):
        s2.node1 = MyNode()
    assert s2.subgraph == s.subgraph # Make sure no partial insertion was done.

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
    nid = s.add(MyNode(label='hello'))
    s.add(NPath(parent=None, name='path1', ref=nid))
    # Two NPaths are not allowed to reference the same node:
    with pytest.raises(UniqueViolation):
        s.add(NPath(parent=None, name='path2', ref=nid))

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
        text = Attr(str)

    class NodeB(Node):
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
        ref = LocalRef(MyNode)
        text = Attr(str)

    s = MyHead()
    s.n1 = MyNode()
    n1_foo = s.n1 % MyNodeItem(text='n1 foo')

    assert n1_foo.ref == s.n1

def test_cursor_externalref():
    class NodeExtRef(Node):
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
