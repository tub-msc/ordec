:mod:`ordec.core.ordb` --- Functional, relational, schema-based data model
==========================================================================

.. toctree::
  :hidden:

  ordb_demo

.. automodule:: ordec.core.ordb

ORDB is the core of ORDeC's internal data model. It provides a functional, relational, schema-based mechanism to represent IC design data such as schematics, symbols, layouts and simulation results. IC design data is structured in subgraphs (:class:`Subgraph`), which can comprise many nodes (:class:`Node`) including a single special root node (:class:`SubgraphRoot`). Nodes can reference other nodes within the same subgraph (:class:`LocalRef`) or in other subgraphs (:class:`ExternalRef` in combination with :class:`SubgraphRef`).
ORDB is primarily a in-memory database. Serialization and network support is planned but not currently implemented.

An example subgraph might represent a schematic comprising multiple nets, ports, drawn wires and symbol instances.

For a practical demonstration, view :ref:`ordb_demo`.

ORDB is based on five principles:

1. **Schema-based:** ORDB design data must conform to a predefined schema, which defines a set of node types (tables) with attributes (columns), including relations between nodes. See :ref:`attribute_types` for details.

2. **Relational queries:** ORDB supports a basic form of relational queries and can loosely be seen as relational database. When node A references node B through a LocalRef attribute, this reference can not only be followed from A to B but also in the reverse direction from B to A, without having to explicitly add a second reference in the opposite direction. This is especially important in 1:n relations, where the reference by convention is always stored at the '1' side, never at the 'n' side. Relational queries are powered by automatic indices.

3. **Hierarchical tree organization:** Names can be assigned to nodes. Those names can be arranged hierarchically in a tree. This makes it possible to group design objects in arrays, structs or other logical units.

4. **Persistent data structures:** The state of a ORDB subgraph is stored using `persistent data structures <https://en.wikipedia.org/wiki/Persistent_data_structure>`_ (from the `Pyrsistent <https://pyrsistent.readthedocs.io/>`_ library). Persistent data structures are immutable.
   
   Modifying a subgraph (i.e. adding, updating or removing nodes) replaces its old state with a new state, which is built upon the previous state. The old subgraph state remains unchanged. Due to this, logical copies of subgraphs are very cheap, as the underlying data structures are immutable and thus do not need to be copied.
   
   Persistence allows highly similar subgraphs to share memory. Examples: very similar symbols such as resistors with different values where only captions differ; evolving a schematic or layout for cross-technology mapping; placement or routing steps that evolve layouts; power grid generation; separate copies of the SimHierarchy when performing different simulations; reverting incremental changes.

5. **Mutable and immutable interfaces:** While constructing or transforming a subgraph, a mutable interface is used, which hides the aforementioned immutability and persistence. At functional boundaries, subgraphs can be frozen (made immutable). Frozen subgraphs are read-only and cannot be accidentally modified. Functions that return frozen subgraphs are well-suited for return value caching / memoization. For example, we can generate a Symbol once and then use it at many occasions. Side effects between independent users of the same frozen subgraph are eliminated.

Before the current design of ORDB, some other ideas were evaluated but discarded:
ORDeC's first data model layer was schema-based and had mutable and immutable interfaces, but lacked persistence and support for relational queries.
Another alternative to the current ORDB could be an in-memory global relational database for each IC design. Such a system would be schema-based and support relational queries, but it would not provide a mutable and immutable interfaces on subgraph level (and the resulting functional encapsulation) and lack the advantages of persistent data structures.
Lastly, plain Python objects, frozen dataclasses or similar approaches lack relational queries, mutable and immutable interfaces on subgraph level and persistence.

.. _attribute_types:

Schema: nodes and attributes
----------------------------

A schema defines node types and their attributes, including the special SubgraphRoot node types, of which there is exactly one per subgraph. As an example, see the following excerpt of ORDeC's full schema for IC design data (:mod:`ordec.core.schema`):

.. code-block:: python

  class Symbol(SubgraphRoot):
      outline = Attr(Rect4R)

  class Pin(Node):
      pintype = Attr(PinType, default=PinType.Inout)
      pos     = Attr(Vec2R)
      align   = Attr(D4, default=D4.R0)

**Attribute** values must be hashable and should be immutable. Thus, lists and dicts cannot be attributes. To take advantage of ORDB's capabilities, it is also strongly encouraged to use atomic attributes rather than compound types (first normal form).

.. autoclass:: Attr
  :members:

.. autoclass:: LocalRef

.. note::

  In one instance, the above recommendation that attribute values should be immutable and primitive is violated: The 'cell' attribute of some SubgraphRoot classes such as :class:`ordec.core.schema.Schematic` reference instances of :class:`ordec.core.cell.Cell`, which are hashable but potentially mutable. The 'cell' attributes are currently needed to resolve symbols to schematics.

References to nodes within another subgraph require two attributes: a reference to another subgraph (:class:`ordec.core.ordb.SubgraphRef`) and a reference to the the node within that subgraph (:class:`ordec.core.ordb.ExternalRef`). 

.. autoclass:: SubgraphRef

.. autoclass:: ExternalRef

Attributes are always defined as part of a :class:`Node` subclass.

Each node instance (row) has a **node ID (nid)** that identifies it uniquely within its subgraph. Both nodes inside the subgraph and nodes in other subgraphs can use this nid to reference the node (:class:`LocalRef` and :class:`ExternalRef`).

.. autoclass:: Node
  :members:

  .. attribute:: Tuple
    :type: type[NodeTuple]

    auto-generated subclass of :class:`NodeTuple`

  .. attribute:: Mutable
    :type: type[MutableNode]

    auto-generated subclass of this Node subclass and :class:`MutableNode`

  .. attribute:: Frozen
    :type: type[FrozenNode]

    auto-generated subclass of this Node subclass and :class:`FrozenNode`

.. autoclass:: NonLeafNode
  :show-inheritance:
  :members:

.. autoclass:: SubgraphRoot
  :show-inheritance:
  :members:

Every :class:`SubgraphRoot` is a subclass of :class:`NonLeafNode`, i.e. SubgraphRoots always support child nodes:

.. inheritance-diagram:: ordec.core.ordb.PathNode ordec.core.ordb.SubgraphRoot
  :parts: -2

The classes :class:`ordec.core.ordb.MutableNode` and :class:`ordec.core.ordb.FrozenNode` have an auxiliary function as base class for :attr:`Node.Mutable` and :attr:`Node.Frozen`.

.. autoclass:: MutableNode

.. autoclass:: FrozenNode

The following inheritance diagram around :class:`ordec.core.schema.Net` exemplifies their role:

.. inheritance-diagram:: ordec.core.schema.Net
  :include-subclasses:
  :parts: -2

Note that the class :class:`ordec.core.schema.Net` itself will never be instantiated. Instead, either Net.Frozen or Net.Mutable will be used, depending on whether a :class:`FrozenSubgraph` or a :class:`MutableSubgraph` is selected.

.. An example of a :class:`SubgraphRoot` is :class:`ordec.core.schema.Schematic`. Its inheritance diagram looks as follows:

.. .. inheritance-diagram:: ordec.core.schema.Schematic
..   :include-subclasses:
..   :parts: -2


Inserters & indices
-------------------

.. autoclass:: Inserter

.. autoclass:: FuncInserter

.. autoclass:: GenericIndex
  :members:

.. autoclass:: Index
  :members:

.. autoclass:: CombinedIndex

.. autoclass:: IndexQuery

Low-level stuff
---------------

.. autoclass:: NodeTuple
  :members:


.. note::

  :class:`NodeTuple` is a custom tuple subclass. Some alternatives to this were considered but discarded:

  - NamedTuple classes do not support default values and cannot be subclassed, as they are not normal classes.
  - For pyrsistent.PClass, the behaviour of field() is difficult to change without touching everything. Also, the performance overhead of mutating pyrsistent.PClass seems a bit high, just from reading its code. A downside of the current tuple subclass or NamedTuple compared to PClass is that all attribute references must be copied when a single attribute is updated, but this is probably not an issue as long as the number of attributes remains low.
  - recordclass.dataobject would be an additional fragile dependency, and its readonly=True option seems to be a (buggy) afterthought only.
  - pydantic is too heavyweight.

.. autoclass:: Subgraph
  :members:

.. autoclass:: MutableSubgraph
  :show-inheritance:

.. autoclass:: FrozenSubgraph
  :show-inheritance:

.. autoclass:: SubgraphUpdater

:class:`NPath` and :class:`PathNode` implement the path hierarchy of subgraphs:

.. autoclass:: NPath

.. autoclass:: PathNode


Exceptions
----------

.. autoclass:: OrdbException

.. autoclass:: QueryException
  :show-inheritance:

.. autoclass:: ModelViolation
  :show-inheritance:

.. autoclass:: UniqueViolation
  :show-inheritance:

.. autoclass:: DanglingLocalRef
  :show-inheritance:

Design patterns
---------------

There are two ways to build upon an immutable subgraph: The subgraph can be thawed and modified, or a new subgraph that references it can be created, keeping the original subgraph immutable.
