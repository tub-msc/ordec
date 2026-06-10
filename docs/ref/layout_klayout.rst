:mod:`ordec.layout.klayout` --- KLayout integration (DRC/LVS)
=============================================================

.. automodule:: ordec.layout.klayout

This module integrates the external `KLayout <https://www.klayout.de/>`_ tool for DRC and LVS. It runs KLayout in batch mode (:func:`run`) and parses its result files back into ORDB subgraphs: XML result databases (RDB) into ``DrcReport`` (:func:`parse_rdb`), and LVS databases (LVSDB) into ``LvsReport`` (:func:`parse_lvsdb`). PDK-specific entry points such as ``ordec.lib.ihp130.run_drc`` and ``ordec.lib.ihp130.run_lvs`` build on these functions.

For LVS, ORDeC supplies KLayout with two inputs that are generated from the same :class:`~ordec.core.cell.Cell` hierarchy: a SPICE netlist of the schematic (via ``Netlister``) and a GDS file of the layout (via ``write_gds``), both named through one shared ``Directory`` (see `Cell name matching`_ below).

Hierarchical LVS and KLayout's ``align``
----------------------------------------

KLayout's netlist comparer works hierarchically: it pairs up circuits (layout cells extracted from the GDS vs. ``.subckt`` definitions from the schematic netlist) and compares each pair in isolation, treating instances of already-paired subcircuits as opaque building blocks. Circuits are paired *by name* (case-insensitively). Each compared pair appears as one ``LvsCircuitPair`` in the parsed ``LvsReport``.

This pairing only works when both sides have the same hierarchy. To handle differing hierarchies, the LVS deck invokes KLayout's ``align`` step before the comparison. ``align`` finds all circuits that have *no* same-named counterpart on the other side and flattens them, i.e. inlines their contents into their parent circuits. (The top cell of the layout is excepted: if it has no schematic counterpart, ``align`` raises an error instead.)

For hierarchical LVS, this has the following consequences:

* Cells that exist on both sides (same name) are compared pair by pair, keeping the comparison hierarchical and the report structured.
* Cells that exist on one side only are flattened away. This covers leaf device cells (e.g. resistor or MOSFET layout cells, whose devices appear directly inside the parent ``.subckt`` on the schematic side), but also deliberately different hierarchy cuts: a flat layout can be compared against a hierarchical schematic and vice versa, and even two hierarchies with shifted cell boundaries compare clean as long as they are electrically equivalent after flattening.
* Objects of flattened circuits appear in the report under dotted hierarchical names (e.g. device ``B1.A1.R1`` = resistor ``r1`` inside instance ``a1`` inside instance ``b1``).
* Flattening can make structurally identical subcircuits (e.g. two parallel instances of the same cell) topologically symmetric; KLayout then matches the affected nets in an arbitrary but valid way and flags them as *ambiguous matches*, which :func:`parse_lvsdb` represents as ``LvsStatus.MatchWarning`` (not as a mismatch).

``tests/lib/lvs_example_hier.ord`` together with ``tests/test_ihp130_lvs_hier.py`` exercises all of these cases.

.. _Cell name matching:

Cell name matching
------------------

Because ``align`` and the circuit pairing operate purely on names, LVS is only correct if the netlist and GDS names agree exactly: the schematic and layout of one cell must be paired, and views of different cells must never be. ORDeC's ``Directory`` guarantees this name matching in both directions — two circuits are name-matched by KLayout *if and only if* they belong to the same cell:

* **Same cell ⇒ same name.** A :class:`~ordec.core.cell.Cell` subclass with a given (normalized) parameter set is a singleton, and ``run_lvs`` uses a single ``Directory`` for both netlisting and GDS writing. ``Directory.name_subgraph()`` names a subgraph after its *cell*, memoized per cell object, so the ``.subckt`` for ``A().symbol`` and the GDS cell for ``A().layout`` receive the identical string. As a guard, registering a *second, different* subgraph of the same kind under one cell raises an error.
* **Different cells ⇒ different names.** All top-level names live in one namespace per ``Directory``; name collisions (e.g. equal class names from different modules) are resolved by appending number suffixes, so two distinct cells can never receive the same string. Since Directory names contain only ``a-z``, ``0-9`` and ``_``, they are also distinct under KLayout's case-insensitive name normalization.

Note that both directions hold *within one* ``Directory``, i.e. within one ``run_lvs`` invocation — which is sufficient for the name-based pairing, since KLayout sees exactly the netlist and GDS produced by that one directory. Collision suffixes depend on naming order, so names are not guaranteed to be stable across separate runs.

Functions
---------

.. autofunction:: run

.. autofunction:: parse_rdb

.. autofunction:: parse_rdb_value

.. autofunction:: parse_lvsdb
