:mod:`ordec.layout.magic` --- Magic integration
===============================================

.. automodule:: ordec.layout.magic

This module integrates the external `Magic <http://opencircuitdesign.com/magic/>`_ layout tool. It runs Tcl scripts in Magic's batch mode (:func:`run`), with the technology that a PDK's startup file (*.magicrc*) loads, including the PDK's device generators. PDK-specific entry points such as ``ordec.lib.sky130.run_magic`` build on it.

Functions
---------

.. autofunction:: run
