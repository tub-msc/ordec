:mod:`ordec.layout.kpex` --- KLayout-PEX integration (parasitic extraction)
===========================================================================

.. automodule:: ordec.layout.kpex

This module integrates the external `KLayout-PEX <https://github.com/iic-jku/klayout-pex>`_ tool (kpex) for parasitic extraction. It runs the 2.5D engine of kpex (:func:`run`) and reads the extracted netlist back as a ``PexReport`` (:func:`read_netlist`). The report holds the netlist as a ``Schematic``: the devices become cells of the PDK, the parasitic resistances and capacitances ideal ``Res`` and ``Cap`` instances. The PDK-specific entry point ``ordec.lib.ihp130.run_pex`` builds on these functions.

The ``kpex`` executable (version 0.8) must be on the ``PATH``. The Nix setup and the Docker image include it; otherwise, install it for example through ``pipx install klayout-pex``. kpex is no Python dependency of ORDeC. It brings its own LVS deck and process stack for each PDK, so it does not read the PDK that ``ORDEC_PDK_IHP_SG13G2`` points to.

Post-layout simulation
----------------------

The extracted schematic (``PexReport.schematic``) belongs to the cell of the layout and has its symbol. A simulation uses it in place of the cell's schematic when it is passed as ``extracted`` to ``SimHierarchy.from_schematic``, so the testbench schematic stays as it is:

.. code-block::

    cell Inv:
        ...
        @viewgen(auto_refresh=False)
        viewgen pex(self) -> PexReport:
            . = ihp130.run_pex(self.layout)

    cell InvTb:
        ...
        viewgen sim_post(self) -> Simulation:
            . = Simulation.from_schematic(self.schematic, extracted=[Inv().pex.schematic])
            .simulate().tran(10p, 30n)

Get DRC and LVS clean first: an open or a short in the layout changes what is simulated. Note the following:

* The layout is extracted flat, so the extracted schematic of a cell also replaces the schematics of the cells below it. Its devices have the names that kpex gives them (e.g. ``X_1``), not those of the schematic, so a post-layout simulation has no ``dut.pd`` to read the operating point of.
* The pins of the symbol are matched with the ports of the netlist by the labels that ``write_gds`` writes for the ``LayoutPin`` nodes of the layout. The pins of the layouts below it and their labels on pin layers are left out (``sublayout_pins=False``), as kpex would take these labels for labels of the layout. :func:`read_netlist` fails if a pin has no net, if two pins share one or if the label of a pin is on two nets.
* The substrate must connect to a pin (e.g. through a ``Ptap`` on the ground net). :func:`read_netlist` fails otherwise, as the substrate would float in the simulation.
* The extraction splits a net into the nodes of its resistor network, which are named after the net, a number and their layer (e.g. ``a__0_GatPoly``). The node with the name of the net is the one that has the label. The report has one ``PexNet`` per net with the totals of its nodes, e.g. ``Inv().pex.net(Inv().pex.schematic.y).capacitance``, and one ``PexCoupling`` per pair of nets with a capacitance between them.
* The extracted schematic has no positions and wires, so it cannot be drawn. The web UI shows a ``PexReport`` as a table of its nets instead.
* An extracted schematic has many instances. ``simulate(enable_savecurrents=False)`` keeps the result small if the currents are not needed.

Functions
---------

.. autofunction:: run

.. autofunction:: read_netlist

.. autoclass:: KpexError
