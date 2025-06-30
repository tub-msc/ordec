Todos
=====

ORDB
----

- Add tree() method to Cursor that descends using NPath
- Implement subgraph directory index + Cursor.iterdir()
- Attr has outgrown dataclass, so do it manually.
- Add test for legacy and new @generate
- (Add test for cursormethod)
- Invert Cursor-Node relationship, this should make the types more natural. Also, this makes cursormethod the default.
- External references:

  - new Attr subclass for subgraph reference?
  - add some kind of index to detect DanglingExternalRefs either on adding the ExternalRef or when updating the subgraph reference Attr.
  - do we need any other indices for external references?

- LocalRef type checking (refs_ntype)
- Cursor deletion:
  
  - delete path + node + "dependent" nodes?
  - Stuff that gets added together (MultiInserter) should also be deleted together?
  - complex example: PolyVec2R

- Test indices
  
  - in some limited testcases with updates and removals that affect indices
  - flag in SubgraphUpdater to track index changes (?)
  - check whether rebuilding subgraph from node list leds to identical index

- Type checking for Subgraph

  - currently we must check isinstance(s, Subgraph) and isinstance(s.node, MyHead)
  - we could add a metaclass to Subgraph and override its issubclass handler

- Branching and merging of Subgraphs
- SimHierarchy: do not duplicates the nets of Schematics and Symbols
- Profiling
