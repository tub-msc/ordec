:mod:`ordec.layout.magic` --- Magic integration (DRC, device generators)
========================================================================

.. automodule:: ordec.layout.magic

This module integrates the external `Magic <http://opencircuitdesign.com/magic/>`_ layout tool. It runs Tcl scripts in Magic's batch mode (:func:`run`), with the technology that a PDK's startup file (*.magicrc*) loads, including the PDK's device generators and DRC rules. Its script ``DRC_SCRIPT`` runs a full DRC of a GDS file, whose error list :func:`parse_drc` reads into a ``DrcReport``, as :func:`ordec.layout.klayout.parse_rdb` does for KLayout. PDK-specific entry points such as ``ordec.lib.sky130.run_magic`` and ``ordec.lib.sky130.run_magic_drc`` build on these.

Hierarchical DRC
----------------

Magic checks each cell flat together with its subcells, so its error list repeats the violations of a subcell in every cell above it, once per instance. :func:`parse_drc` attaches each violation once, to the lowest cell that holds it and in the coordinates of that cell, as KLayout's deep mode does: an error box of a cell goes to an instance if it lies within an error box of the same rule of the instance's cell. Cross-hierarchy violations stay with the cell above. The cells are found through the ``Directory`` that named them in the GDS file (see :ref:`Cell name matching`). Unlike KLayout, which reports a violation as one item, magic marks it on each shape involved, so that a spacing violation gives two items. Categories are named by rule id, as in KLayout's reports, with magic's rule description as their description. ``tests/test_magic.py`` covers these cases.

Functions
---------

.. autofunction:: run

.. autofunction:: parse_drc
