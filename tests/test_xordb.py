# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for xORDB (aXellerated ORDB) - the Rust-accelerated backend.

These tests verify that the Rust storage layer works correctly
and produces results identical to the pure Python implementation.
"""

import pytest

# Check if xordb extension is available.
# We check for is_rust_backend to distinguish the actual Rust extension
# from a namespace package (the xordb/ source directory).
try:
    import xordb
    if not hasattr(xordb, 'is_rust_backend'):
        skip_xordb = True
    else:
        skip_xordb = False
except ImportError:
    skip_xordb = True


# Basic functionality tests

@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_is_rust_backend():
    assert xordb.is_rust_backend() is True


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_version():
    version = xordb.version()
    assert isinstance(version, str)
    assert version == "0.1.0"


# MutableSubgraph tests

@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_create_empty_store():
    store = xordb.MutableSubgraph()
    assert store.node_count() == 0
    assert store.nid_alloc_start() == 1


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_set_and_get_node():
    store = xordb.MutableSubgraph()

    # Set a node with ntype_id=100 and some attributes
    attrs = ("hello", 42, None)
    store.set_node(1, 100, attrs)

    assert store.node_count() == 1
    assert store.contains_nid(1)

    # Get the node back
    result = store.get_node(1)
    assert result is not None
    ntype_id, returned_attrs = result
    assert ntype_id == 100
    assert tuple(returned_attrs) == attrs


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_get_nonexistent_node():
    store = xordb.MutableSubgraph()
    assert store.get_node(999) is None
    assert not store.contains_nid(999)


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_remove_node():
    store = xordb.MutableSubgraph()
    store.set_node(1, 100, ("test",))
    assert store.contains_nid(1)

    store.remove_node(1)
    assert not store.contains_nid(1)
    assert store.node_count() == 0


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_remove_nonexistent_raises():
    store = xordb.MutableSubgraph()
    with pytest.raises(KeyError):
        store.remove_node(999)


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_nid_alloc_advances():
    store = xordb.MutableSubgraph()
    assert store.nid_alloc_start() == 1

    store.set_node(1, 100, ())
    assert store.nid_alloc_start() == 2

    store.set_node(5, 100, ())
    assert store.nid_alloc_start() == 6

    # Setting a lower nid doesn't decrease alloc start
    store.set_node(3, 100, ())
    assert store.nid_alloc_start() == 6


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_replace_node():
    store = xordb.MutableSubgraph()
    store.set_node(1, 100, ("original",))
    store.set_node(1, 100, ("replaced",))

    assert store.node_count() == 1
    _, attrs = store.get_node(1)
    assert attrs[0] == "replaced"


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_multiple_nodes():
    store = xordb.MutableSubgraph()
    store.set_node(1, 100, ("node1",))
    store.set_node(2, 100, ("node2",))
    store.set_node(3, 200, ("node3",))

    assert store.node_count() == 3

    nids = store.iter_nids()
    assert len(nids) == 3
    nid_set = {nid for nid, _ in nids}
    assert nid_set == {1, 2, 3}


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_get_ntype_id():
    store = xordb.MutableSubgraph()
    store.set_node(1, 100, ())
    store.set_node(2, 200, ())

    assert store.get_ntype_id(1) == 100
    assert store.get_ntype_id(2) == 200
    assert store.get_ntype_id(999) is None


# FrozenStore tests

@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_freeze_empty_store():
    mutable = xordb.MutableSubgraph()
    frozen = mutable.freeze()
    assert frozen.node_count() == 0


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_freeze_preserves_data():
    mutable = xordb.MutableSubgraph()
    mutable.set_node(1, 100, ("hello", 42))
    mutable.set_node(2, 100, ("world", 99))

    frozen = mutable.freeze()

    assert frozen.node_count() == 2
    assert frozen.contains_nid(1)
    assert frozen.contains_nid(2)

    _, attrs1 = frozen.get_node(1)
    assert tuple(attrs1) == ("hello", 42)


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_freeze_is_independent():
    mutable = xordb.MutableSubgraph()
    mutable.set_node(1, 100, ("original",))

    frozen = mutable.freeze()

    # Modify mutable after freezing
    mutable.set_node(1, 100, ("modified",))
    mutable.set_node(2, 100, ("new",))

    # Frozen should be unchanged
    assert frozen.node_count() == 1
    _, attrs = frozen.get_node(1)
    assert attrs[0] == "original"


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_thaw():
    mutable1 = xordb.MutableSubgraph()
    mutable1.set_node(1, 100, ("test",))

    frozen = mutable1.freeze()
    mutable2 = frozen.thaw()

    # Thawed store should have same data
    assert mutable2.node_count() == 1
    assert mutable2.contains_nid(1)

    # Thawed store should be independent
    mutable2.set_node(2, 100, ("new",))
    assert mutable2.node_count() == 2
    assert frozen.node_count() == 1


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_frozen_equality():
    store1 = xordb.MutableSubgraph()
    store1.set_node(1, 100, ("hello",))

    store2 = xordb.MutableSubgraph()
    store2.set_node(1, 100, ("hello",))

    frozen1 = store1.freeze()
    frozen2 = store2.freeze()

    assert frozen1 == frozen2
    assert hash(frozen1) == hash(frozen2)


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_frozen_inequality():
    store1 = xordb.MutableSubgraph()
    store1.set_node(1, 100, ("hello",))

    store2 = xordb.MutableSubgraph()
    store2.set_node(1, 100, ("world",))

    frozen1 = store1.freeze()
    frozen2 = store2.freeze()

    assert frozen1 != frozen2


# Python object storage tests

@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_store_none():
    store = xordb.MutableSubgraph()
    store.set_node(1, 100, (None, None, None))

    _, attrs = store.get_node(1)
    assert attrs[0] is None
    assert attrs[1] is None
    assert attrs[2] is None


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_store_integers():
    store = xordb.MutableSubgraph()
    store.set_node(1, 100, (0, -1, 999999999999))

    _, attrs = store.get_node(1)
    assert attrs[0] == 0
    assert attrs[1] == -1
    assert attrs[2] == 999999999999


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_store_strings():
    store = xordb.MutableSubgraph()
    store.set_node(1, 100, ("", "hello", "unicode: äöü 你好"))

    _, attrs = store.get_node(1)
    assert attrs[0] == ""
    assert attrs[1] == "hello"
    assert attrs[2] == "unicode: äöü 你好"


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_store_python_objects():
    """Test that arbitrary Python objects can be stored and retrieved."""
    from ordec.core.geoprim import Vec2R, D4
    from ordec.core.rational import R

    store = xordb.MutableSubgraph()

    vec = Vec2R(R("1/2"), R("3/4"))
    d4 = D4.R90

    store.set_node(1, 100, (vec, d4, [1, 2, 3]))

    _, attrs = store.get_node(1)
    assert attrs[0] == vec
    assert attrs[1] == d4
    assert attrs[2] == [1, 2, 3]


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_store_mixed_types():
    store = xordb.MutableSubgraph()
    store.set_node(1, 100, ("string", 42, None, 3.14, True))

    _, attrs = store.get_node(1)
    assert attrs[0] == "string"
    assert attrs[1] == 42
    assert attrs[2] is None
    assert attrs[3] == 3.14
    # Note: bool True is stored as int 1 (Python bool is subclass of int)
    assert attrs[4] == True  # noqa: E712


# Store copy tests

@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_mutable_copy():
    store1 = xordb.MutableSubgraph()
    store1.set_node(1, 100, ("original",))

    store2 = store1.copy()

    # Modify original
    store1.set_node(1, 100, ("modified",))

    # Copy should be unchanged
    _, attrs = store2.get_node(1)
    assert attrs[0] == "original"


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_copy_is_deep():
    store1 = xordb.MutableSubgraph()
    store1.set_node(1, 100, ("test",))

    store2 = store1.copy()
    store2.set_node(2, 100, ("new",))

    assert store1.node_count() == 1
    assert store2.node_count() == 2


# Schema registry tests

@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_register_schema():
    # Register a simple schema
    xordb.register_ntype(
        ntype_id=12345,
        name="TestNode",
        attrs=[
            ("label", "str", 0, True),
            ("value", "int", 1, True),
        ],
        indexes=[],
        localref_indices=[],
    )

    # Check it was registered
    schemas = xordb.get_schema_info()
    assert any(s[0] == 12345 and s[1] == "TestNode" for s in schemas)


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_register_schema_with_index():
    xordb.register_ntype(
        ntype_id=12346,
        name="IndexedNode",
        attrs=[
            ("name", "str", 0, False),
            ("ref", "localref", 1, True),
        ],
        indexes=[
            (1001, "simple", [0], True, None),  # unique index on name
            (1002, "simple", [1], False, None),  # non-unique index on ref
        ],
        localref_indices=[1],
    )

    schemas = xordb.get_schema_info()
    assert any(s[0] == 12346 for s in schemas)


# Auto schema registration tests

@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_builtin_schemas_registered():
    """Verify that built-in Node classes from schema.py were registered."""
    from ordec.core.schema import Pin, Net, Symbol, Schematic

    schemas = xordb.get_schema_info()
    schema_names = {s[1] for s in schemas}

    # These classes should have been auto-registered
    assert "Pin" in schema_names
    assert "Net" in schema_names
    assert "Symbol" in schema_names
    assert "Schematic" in schema_names
    assert "NPath" in schema_names


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_schema_has_correct_attr_count():
    """Verify schema attribute counts match Python definitions."""
    from ordec.core.schema import Pin

    schemas = xordb.get_schema_info()
    pin_schema = next((s for s in schemas if s[1] == "Pin"), None)

    assert pin_schema is not None
    ntype_id, name, attr_count = pin_schema
    # Pin has: pintype, pos, align
    assert attr_count == 3


# RustNodeMap adapter tests

@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_store_and_retrieve_nodetuple():
    """Test storing and retrieving actual NodeTuple objects."""
    from ordec.core.ordb import RustNodeMap, _register_ntype_class
    from ordec.core.schema import Pin, PinType
    from ordec.core.geoprim import Vec2R, D4

    store = xordb.MutableSubgraph()
    node_map = RustNodeMap(store)

    # Create a Pin NodeTuple
    pin = Pin(pintype=PinType.In, pos=Vec2R(1, 2), align=D4.R90)

    # Make sure the class is registered
    _register_ntype_class(type(pin))

    # Store it
    node_map[1] = pin

    # Retrieve it
    retrieved = node_map[1]

    assert type(retrieved) == type(pin)
    assert retrieved.pintype == PinType.In
    assert retrieved.pos == Vec2R(1, 2)
    assert retrieved.align == D4.R90


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_dict_like_operations():
    """Test dict-like interface of RustNodeMap."""
    from ordec.core.ordb import RustNodeMap, _register_ntype_class
    from ordec.core.schema import Net

    store = xordb.MutableSubgraph()
    node_map = RustNodeMap(store)

    net1 = Net()
    net2 = Net()
    _register_ntype_class(type(net1))

    # Test __setitem__ and __getitem__
    node_map[1] = net1
    node_map[2] = net2
    assert node_map[1] is not None
    assert node_map[2] is not None

    # Test __contains__
    assert 1 in node_map
    assert 2 in node_map
    assert 999 not in node_map

    # Test __len__
    assert len(node_map) == 2

    # Test __delitem__
    del node_map[1]
    assert 1 not in node_map
    assert len(node_map) == 1

    # Test get with default
    assert node_map.get(999, "default") == "default"


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_iteration():
    """Test iterating over RustNodeMap."""
    from ordec.core.ordb import RustNodeMap, _register_ntype_class
    from ordec.core.schema import Net

    store = xordb.MutableSubgraph()
    node_map = RustNodeMap(store)

    net = Net()
    _register_ntype_class(type(net))

    node_map[10] = net
    node_map[20] = net
    node_map[30] = net

    # Test __iter__ (yields nids)
    nids = list(node_map)
    assert set(nids) == {10, 20, 30}

    # Test keys()
    assert set(node_map.keys()) == {10, 20, 30}

    # Test items()
    items = list(node_map.items())
    assert len(items) == 3
    item_nids = {nid for nid, _ in items}
    assert item_nids == {10, 20, 30}


# NType index tests

@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_ntype_index_query():
    store = xordb.MutableSubgraph()

    # Add nodes of different types
    store.set_node(1, 100, ("a",))
    store.set_node(2, 100, ("b",))
    store.set_node(3, 200, ("c",))
    store.set_node(4, 100, ("d",))

    # Query by ntype
    nids_100 = store.index_query(0, "ntype", 100)
    nids_200 = store.index_query(0, "ntype", 200)
    nids_300 = store.index_query(0, "ntype", 300)

    assert set(nids_100) == {1, 2, 4}
    assert set(nids_200) == {3}
    assert nids_300 == []


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_ntype_index_after_remove():
    store = xordb.MutableSubgraph()
    store.set_node(1, 100, ())
    store.set_node(2, 100, ())

    store.remove_node(1)

    nids = store.index_query(0, "ntype", 100)
    assert nids == [2]


# Schema lookup tests

@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_get_ntype_id():
    """Test looking up ntype_id by name."""
    from ordec.core.schema import NPath, SubgraphRoot

    npath_id = xordb.get_ntype_id("NPath")
    assert npath_id is not None
    assert npath_id == id(NPath.Tuple)

    root_id = xordb.get_ntype_id("SubgraphRoot")
    assert root_id is not None
    assert root_id == id(SubgraphRoot.Tuple)

    # Unknown type returns None
    assert xordb.get_ntype_id("NonExistentType") is None


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_get_schema():
    """Test getting detailed schema info by name."""
    schema = xordb.get_schema("NPath")
    assert schema is not None

    ntype_id, name, attrs = schema
    assert name == "NPath"
    assert len(attrs) == 3

    # Check attribute details
    attr_names = [a[0] for a in attrs]
    assert "parent" in attr_names
    assert "name" in attr_names
    assert "ref" in attr_names


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_get_type_names():
    """Test getting list of all registered type names."""
    names = xordb.get_type_names()
    assert isinstance(names, list)
    assert "NPath" in names
    assert "SubgraphRoot" in names
    assert "Pin" in names
    assert "Net" in names


# Pure Rust node creation tests

@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_create_node_by_name():
    """Test creating nodes by type name."""
    sg = xordb.MutableSubgraph()

    # Create SubgraphRoot at nid=0
    sg.create_node_at(0, "SubgraphRoot", ())

    # Create NPath nodes
    # NPath attrs: (parent, name, ref)
    # parent and ref are LocalRef (nids), name is stored as pyobject
    nid1 = sg.create_node("NPath", (None, "child1", 0))
    nid2 = sg.create_node("NPath", (None, "child2", 0))

    assert sg.node_count() == 3
    assert sg.contains_nid(0)
    assert sg.contains_nid(nid1)
    assert sg.contains_nid(nid2)

    # Verify the node data
    _, attrs1 = sg.get_node(nid1)
    assert attrs1[1] == "child1"  # name attribute
    assert attrs1[2] == 0  # ref points to root


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_create_node_unknown_type():
    """Test that creating node with unknown type raises error."""
    sg = xordb.MutableSubgraph()

    with pytest.raises(ValueError, match="Unknown node type"):
        sg.create_node("NonExistentType", ())


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_pure_rust_subgraph_structure():
    """
    Test building a complete subgraph structure purely in Rust.

    This creates a simple hierarchy similar to what would be in a
    real ORDB subgraph, using only xordb calls without Python NodeTuple.
    """
    sg = xordb.MutableSubgraph()

    # Create root node (SubgraphRoot has no attributes)
    sg.create_node_at(0, "SubgraphRoot", ())

    # Create a hierarchy of NPath nodes representing a simple namespace:
    #   root (nid=0)
    #   ├── module (nid=1, NPath)
    #   │   ├── class_a (nid=2, NPath)
    #   │   └── class_b (nid=3, NPath)
    #   └── utils (nid=4, NPath)
    #       └── helper (nid=5, NPath)

    # NPath attrs: (parent, name, ref)
    # - parent: LocalRef to parent NPath (or None for top-level)
    # - name: the name string
    # - ref: LocalRef to the node this path points to

    # Top-level paths (parent=None, ref=root)
    module_nid = sg.create_node("NPath", (None, "module", 0))
    utils_nid = sg.create_node("NPath", (None, "utils", 0))

    # Children of module
    class_a_nid = sg.create_node("NPath", (module_nid, "class_a", 0))
    class_b_nid = sg.create_node("NPath", (module_nid, "class_b", 0))

    # Child of utils
    helper_nid = sg.create_node("NPath", (utils_nid, "helper", 0))

    # Verify structure
    assert sg.node_count() == 6  # root + 5 NPath nodes

    # Query by NPath type
    npath_type_id = xordb.get_ntype_id("NPath")
    npath_nids = sg.index_query(0, "ntype", npath_type_id)
    assert len(npath_nids) == 5  # 5 NPath nodes

    # Verify node contents
    _, module_attrs = sg.get_node(module_nid)
    assert module_attrs[0] is None  # parent is None (top-level)
    assert module_attrs[1] == "module"
    assert module_attrs[2] == 0  # ref points to root

    _, class_a_attrs = sg.get_node(class_a_nid)
    assert class_a_attrs[0] == module_nid  # parent is module
    assert class_a_attrs[1] == "class_a"

    _, helper_attrs = sg.get_node(helper_nid)
    assert helper_attrs[0] == utils_nid  # parent is utils
    assert helper_attrs[1] == "helper"

    # Test freeze/thaw cycle preserves structure
    frozen = sg.freeze()
    assert frozen.node_count() == 6

    thawed = frozen.thaw()
    assert thawed.node_count() == 6

    # Verify data preserved after freeze/thaw
    _, thawed_module_attrs = thawed.get_node(module_nid)
    assert thawed_module_attrs[1] == "module"


@pytest.mark.skipif(skip_xordb, reason="xordb not available")
def test_pure_rust_net_subgraph():
    """
    Test creating a subgraph with Net nodes (schematic-like structure).

    Net nodes have 2 attributes - we create a simple netlist structure.
    """
    sg = xordb.MutableSubgraph()

    # Create root
    sg.create_node_at(0, "SubgraphRoot", ())

    # Create some Net nodes
    # Net._raw_attrs would tell us the attribute structure
    # For this test, we just verify we can create nodes with the right count
    net_schema = xordb.get_schema("Net")
    assert net_schema is not None
    ntype_id, name, attrs = net_schema
    attr_count = len(attrs)

    # Create a Net with the right number of attributes (all None for simplicity)
    net_attrs = tuple([None] * attr_count)
    net1_nid = sg.create_node("Net", net_attrs)
    net2_nid = sg.create_node("Net", net_attrs)

    assert sg.node_count() == 3  # root + 2 nets
    assert sg.contains_nid(net1_nid)
    assert sg.contains_nid(net2_nid)

    # Query by Net type
    net_nids = sg.index_query(0, "ntype", ntype_id)
    assert set(net_nids) == {net1_nid, net2_nid}
