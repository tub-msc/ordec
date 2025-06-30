ORDB Data Model
======================

ORDB is the foundation of ORDeC's data model.

It defines the basis of how IC design data (e.g. schematics, symbols, layouts, simulation results, extraction results, DRC \& LVS results) is represented and how design data can be queried and modified.

Each design flow step produces a set of interrelated design objects. For example, a step might return a schematic that consists of nets, ports, drawn wires and instantiated symbols. This can be seen as a **graph**, with the design objects being nodes and the references between them being edges. Some of the edges might be between nodes generated within one specific step, while other edges might link nodes between distinct steps. From this point of view, the nodes from each design flow step constitute a **subgraph**.

Based on this idea of subgraphs, ORDB provides a data model that can be summarized in five principles:

1. **Schema-based:** ORDB design data must conform to some a predefined schema. This schema primarily defines a set of node types (tables) with specific attributes (columns). The schema also defines possible relations between nodes.

  - Attributes must be hashable, which means that lists and dicts cannot be attributes. Attributes are typically either primitive types (e.g. string, int, Vec2R) or immutable subgraph references. An exception is the "cell" attribute.

3. **Relational queries:**
  
  - In a 1:n relation, if we add a reference on one side, we want to be able to efficiently access the reference in the opposite direction.
  - For this, we need transparent indices.
  - Integrity checks ("foreign keys").
  - ORDB can loosely be seen as relational database.

3. **Hierarchical tree organization:** Names can be assigned to nodes. Those names can be arranged hierarchically in a tree. This makes it possible to group design objects in arrays, structs or other logical units.
4. **Persistent data structure:** ORDB subgraphs are based on `persistent data structures <https://en.wikipedia.org/wiki/Persistent_data_structure>`_.

  - The state of a subgraph is immutable.
  - Modifying a subgraph (i.e. adding, updating or removing nodes) replaces its old state with a new state (that is built upon the previous state). The old subgraph state remains unchanged.
  - Logical copies of subgraphs are free, as the underlying data structures are immutable and thus do not need to be copied.
  - Using this mechanism, similar subgraphs can share data.

5. **Mutable and immutable interfaces:**
   
  - While creating or transforming a subgraph, a mutable interface is used, hiding the aforementioned immutability and persistence.
  - At functional boundaries, subgraphs are made immutable (frozen). This ensures that subsequent use of the subgraph is read-only and does not accidentally modify it. It also and allows caching of return values -- for example, we can generate a Symbol once and then use it at many occasions.

ORDB is primarily intended as **in-memory** database. Serialization and network support is planned but not currently implemented.

The :ref:`ordb_demo` demonstrates the principles listed above with hands-on examples.

As potential alternatives to ORDB, some other ideas were considered but discarded:

- A in-memory global relational database could be used within the context of running the design tool / concerning one IC design. Such a system would be *schema-based* and offer *relational queries*, but it would not provide a *persistent data structure* and *mutable and immutable interfaces* on subgraph level.
- ORDeC's old data model layer was *schema-based* and had *mutable and immutable interfaces*, but lacked *persistency* and *relational queries*.
- Plain Python objects, frozen dataclasses or similar approaches mainly lack *persistency*, the ability to have *mutable and immutable interfaes* on subgraph level and *relational queries*.

Why persistency?
----------------

Subgraphs with high degrees of similarity should share memory:
    
- Example 1: very similar symbols (e.g. resistors with different values) each have separate, but almost identical subgraphs in memory (e.g. only captions differ)
- Example 2: evolving a schematic or layout for cross-technology mapping
- Example 3: placement or routing steps that evolve layouts
- Example 4: power grid generation
- Example 5: separate copies of the SimHierarchy when performing multiple simulations (e.g. parameter sweep, monte carlo, op+transient, ...)

Other thoughts:

- Various incremental versions/copies of design data can be maintained.
- Full functional encapsulation, results of functions are immutable and can be cached.
- Reverting changes is easy.
- Tasks like PNR, PEX, Monte-Carlo simulation could be done in parallel based on the persistent structures. Either by dividing the problem or by testing out different parameters and using the best result.
    
Persistency is implemented using `Pyrsistent <https://pyrsistent.readthedocs.io/>`_.

Reference
---------

Further remarks:

- Every node has a node ID (nid) that identifies it uniquely within its subgraph. Both nodes inside the subgraph and nodes in other subgraphs use this nid to reference the node.
- Nodes can only references immutable subgraphs. For this reason, subgraphs form a a directed acyclic graph.
- The access layer (Cursor) is separate from the stored data (Node).
- There are two ways to build upon an immutable subgraph:
  
  - Thaw + modify the subgraph (add and update nodes).
  - Keep the subgraph immutable, create a new subgraph that references it.

.. automodule:: ordec.ordb
  :member-order: bysource
  :members:

.. .. autoclass:: Cell
..    :members:
..    :exclude-members: __init__

.. .. autoclass:: Node
..    :members:
..    :exclude-members: Children, __init__

.. .. autoclass:: View
..    :members:
