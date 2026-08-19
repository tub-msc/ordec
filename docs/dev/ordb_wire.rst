:mod:`ordec.core.wire` --- ORDB wire layer
==========================================

.. automodule:: ordec.core.wire

Node classes opt in by declaring ``wire_id = WIRE_DOMAIN | n`` in their
class body (inherited wire_ids do not count; uniqueness is asserted at
class registration, and serializing a class without one is an error).
Domain prefixes:

- 1<<16: ordb (NPath)
- 2<<16: schema/base
- 3<<16: schematic
- 4<<16: layout
- 5<<16: simhier
- 6<<16: drc
- 7<<16: lvs
- 8<<16: report
- 15<<16: tests

CBOR tags
---------

Native CBOR covers None, bool, int, str, bytes, float and tuple (as
array, recursive). Everything else is tagged:

.. csv-table::
  :header: Tag, Type, Payload

  30, R, "[numerator, denominator] (standard rational tag; always reduced)"
  390001/390002, Vec2R / Vec2I, "[x, y]"
  390003/390004, Rect4R / Rect4I, "[lx, ly, ux, uy]"
  390005/390006, TD4R / TD4I, "[transl, d4]"
  390007; 390010–390017, "D4; PathEndType, PinType, SchemErrorType, ScaleType, SimType, LvsStatus, LvsItemType, Quantity", member name string
  390020, SimArray, "[[[fid, dtype], ...], data bytes]"
  390021, SourceLocInfo, "[filename, line, column]"
  390024, SimColumn, "[blob index, offset, stride, length, dtype, name, quantity]"
  390022, GdsLayer, "[layer, data_type]"
  390023, RGBColor, "[r, g, b]"
  390030, LocalRef value, nid
  390031, ExternalRef value, nid
  390032, SubgraphRef value, 32-byte wire_hash of the referenced subgraph
  390033, LiveRef value, "[endpoint_id (16 bytes), obj_id (uint), name (str)]"

Format stability
----------------

There is no schema-skew detection: all endpoints are built from the same
monorepo tree and wire data is never persisted, so the format version
digit in ``HASH_DOMAIN`` is the only versioning. Canonical (shortest-form)
float encoding is deterministic per cbor2 version; a cbor2 major-version
bump warrants re-checking it and bumping the format version (cbor2>=6 is
pinned, its tag_hook signature differs from 5.x). A foreign-language
encoder must reproduce the canonical encoding byte-exactly for hashes to
match.

Encoding, hashing, decoding
---------------------------

.. automethod:: ordec.core.ordb.base.FrozenSubgraph.wire_encode

.. automethod:: ordec.core.ordb.base.FrozenSubgraph.wire_hash

.. automethod:: ordec.core.ordb.base.FrozenSubgraph.wire_deps

.. autofunction:: wire_decode

Live references
---------------

.. autoclass:: ordec.core.ordb.base.LiveRef

.. autoclass:: ordec.core.ordb.base.FarRef

.. autoclass:: ExportTable
  :members:

Want/have exchange
------------------

.. autoclass:: WireSender
  :members:

.. autoclass:: WireReceiver
  :members:

``tests/test_wire_subprocess.py`` demonstrates the full stack end to end:
an unwired schematic is transferred to a cold subprocess over pipes,
auto-wired there and transferred back, with symbols served from the
store instead of being retransmitted and LiveRefs crossing as FarRefs
that resolve back to the identical live objects at home.
