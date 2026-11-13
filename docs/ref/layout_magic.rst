:mod:`ordec.layout.magic` --- Magic integration (DRC, device generators)
========================================================================

.. automodule:: ordec.layout.magic

This module integrates the external `Magic <http://opencircuitdesign.com/magic/>`_ layout tool. It runs Tcl scripts in Magic's batch mode (:func:`run`), with the technology that a PDK's startup file (*.magicrc*) loads, including the PDK's device generators and DRC rules. Its script ``DRC_SCRIPT`` runs a full DRC of a GDS file, whose error list :func:`parse_drc` reads into a ``DrcReport``, as :func:`ordec.layout.klayout.parse_rdb` does for KLayout. PDK-specific entry points such as ``ordec.lib.sky130.run_magic`` and ``ordec.lib.sky130.run_magic_drc`` build on these. :func:`parse_drc` attaches each violation once, to the lowest cell holding it, as KLayout's deep mode does.

Functions
---------

.. autofunction:: run

.. autofunction:: parse_drc
