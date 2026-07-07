:mod:`ordec.core.placement` --- Placement groups
================================================

.. automodule:: ordec.core.placement

**Example (ORD):**

.. code-block::

    viewgen schematic -> Schematic:
        port a : .align=East
        port y : .align=West
        net vss  # forward declaration, port statement follows in the stack

        Series(gap=4) stack:
            port vdd: .align=South
            Pmos pu:
                .g -- a
                .b -- vdd
                .d -- y
            Nmos pd:
                .g -- a
                .b -- vss
            port vss: .align=North

Placement precedence
--------------------

Positions of schematic elements are determined in this order:

1. Directly assigned positions (``.pos = (x, y)``) and explicit constraints
   (``! ...``) always win. A port or instance referenced in any constraint
   is not placed automatically.
2. Members of a placement group are placed by the group. Top-level groups
   anchor at (0, 0); several auto-anchored groups line up side by side. A
   group with a constrained or directly positioned member follows that
   member instead of being anchored.
3. Remaining ports are auto-placed on the edge of the content bounding box
   based on their align (see
   :func:`ordec.schematic.helpers.schem_place_ports`): the align is the
   direction the port arrow points, into the drawing. A port with
   ``align=East`` is placed on the left edge, ``West`` on the right,
   ``North`` on the bottom and ``South`` on the top edge. Along the edge,
   the port lines up with the connected pin nearest to its edge, so that
   the wire towards it can run straight.
4. Instances that end up with no position at all raise a
   :class:`ordec.core.constraints.SolverError`.

Classes
-------

.. autoclass:: PlacementGroup
  :members:

.. autoclass:: Row
  :show-inheritance:
  :members:

.. autoclass:: Col
  :show-inheritance:
  :members:

.. autoclass:: ConnectingGroup
  :show-inheritance:
  :members:

.. autoclass:: Series
  :show-inheritance:
  :members:

.. autoclass:: Parallel
  :show-inheritance:
  :members:
