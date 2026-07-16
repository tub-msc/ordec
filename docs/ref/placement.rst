:mod:`ordec.schematic.placement` --- Placement groups
=====================================================

.. automodule:: ordec.schematic.placement

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

Choosing a group
----------------

:class:`Row` and :class:`Col` are purely geometric: they place their
children and leave all wiring to explicit ``--`` connections.
:class:`Series` and :class:`Parallel` additionally connect their children
electrically, modeling a current path:

.. list-table::
   :header-rows: 1

   * - Group
     - Placement
     - Electrical connection
   * - :class:`Row`
     - side by side, left to right
     - none
   * - :class:`Col`
     - stacked, top to bottom
     - none
   * - :class:`Series`
     - along the current path
     - each pair of neighbors, pin to pin
   * - :class:`Parallel`
     - across the current path
     - all children between two rail nets

Use Series/Parallel when the placement follows the circuit topology and
let the connections fall out of the structure. Fall back to Col/Row with
explicit wiring when the structure is irregular (heterogeneous pin
selections, connections that do not follow the stack).

Attributes
----------

All groups:

``gap``
    Distance between adjacent children along the main axis. The default
    (2) leaves room for ``auto_wire()`` routing. Tighter gaps can exceed
    the router's capacity.

``align``
    Cross-axis placement policy for children of different sizes:

    - ``'center'`` (default for Row, Col and Parallel) centers the
      children's bounding boxes, snapped down to the unit grid so that
      on-grid pins stay routable.
    - ``'start'`` / ``'end'`` align the bottom/left or top/right edges.
    - ``'pins'`` (Series only, its default) shifts each child so that
      each pair's facing pins line up, giving straight junction wires.
      Where a child has no single junction point (a nested Parallel
      rail), its center is used.

    With children of equal size, all policies coincide.

``anchor``
    Position of the group's southwest corner. The default ``'auto'``
    anchors a top-level group at (0, 0). Several auto-anchored groups in
    one view line up side by side. A group with a member that appears in
    a user constraint or has a directly assigned position follows that
    member instead. Pass an (x, y) tuple to anchor explicitly, or None
    to never emit an anchor.

Series and Parallel only:

``horizontal``
    Direction of the current path through each child: vertical (False,
    the default) connects through downward-/upward-facing pins,
    horizontal (True) through right-/left-facing pins. The placement
    axis follows from it: Series places along the path, Parallel across
    it, so a vertical Series stacks like Col while a vertical Parallel
    places side by side like Row. The group never rotates children.
    Orient instances so that their current-carrying pins face along the
    path.

``top``, ``bottom`` (vertical), ``left``, ``right`` (horizontal)
    Pin name overrides for pin detection: when an instance child has
    several pins on a facing side, these select the connecting pin,
    uniformly for all instance children.

Connectivity
------------

Series connects the pin of each child facing the next child to the next
child's pin facing back. Port children connect through their net.
Parallel ties all pins facing one way to one rail net and all pins
facing the other way to a second rail net. It does not accept port
children (wire the rail net to the port explicitly).

A junction or rail net is *adopted* from whichever involved pin is
already connected, so wiring one pin explicitly (``.d -- y``) names the
net. Without any, an anonymous net is created. Pins that are already on
two different nets are a connection conflict and raise an error.

Since a port's statement position inside a group determines its place in
the stack, a port that earlier statements reference can be
forward-declared with ``net`` (see the example above): the later
``port`` statement attaches the symbol pin to the declared net.

Nesting
-------

Any group nests in any group geometrically. The nested group is placed
as a rigid block. Series and Parallel additionally connect nested
Series/Parallel children through their boundary: a nested Series exposes
the outward-facing pins of its first and last child, a nested Parallel
exposes its two rails. Series/parallel circuit structures can therefore
be described by nesting alone, e.g. a NAND as a Series of vdd, a
Parallel pull-up pair, the pull-down transistors and vss. Tutorial
section :ref:`placement_groups` shows this NAND as a complete example
with its rendered schematic.

Two restrictions apply: a Series/Parallel cannot electrically connect a
nested Col/Row child (nest Series/Parallel instead, or wire explicitly),
and a nested connecting group must share the enclosing group's
orientation (a horizontal Parallel has no upward/downward rails to
connect in a vertical Series).

Placement precedence
--------------------

Positions of schematic elements are determined in this order:

1. Directly assigned positions (``.pos = (x, y)``) and explicit constraints
   (``! ...``) always win. A port or instance referenced in any constraint
   is not placed automatically.
2. Members of a placement group are placed by the group. Top-level groups
   anchor at (0, 0). Several auto-anchored groups line up side by side. A
   group with a constrained or directly positioned member follows that
   member instead of being anchored.
3. Remaining ports are auto-placed on the edge of the content bounding box
   based on their align (see ``schem_place_ports()`` in
   ``ordec.schematic.helpers``): the align is the
   direction the port arrow points, into the drawing. A port with
   ``align=East`` is placed on the left edge, ``West`` on the right,
   ``North`` on the bottom and ``South`` on the top edge. Along the edge,
   the port lines up with the connected pin nearest to its edge, so that
   the wire towards it can run straight.
4. Instances that end up with no position at all raise a
   :class:`ordec.core.constraints.SolverError`.

Classes
-------

Groups are configured entirely through their constructor arguments,
described in the class docstrings and under `Attributes`_ above. Their
methods are internal machinery (see below).

.. autoclass:: PlacementGroup

.. autoclass:: Row
  :show-inheritance:

.. autoclass:: Col
  :show-inheritance:

.. autoclass:: ConnectingGroup
  :show-inheritance:

.. autoclass:: Series
  :show-inheritance:

.. autoclass:: Parallel
  :show-inheritance:

Internals
---------

While the viewgen body runs, a group only records its children in
declaration order. The view context emits all top-level groups during
postprocessing: :meth:`PlacementGroup.emit` resolves connectivity
(parent before child, since ORDB cannot merge nets), computes the rigid
relative :meth:`~PlacementGroup.arrangement` of the children and
constrains each child's position to the first child by a constant
offset, anchoring top-level groups. User code only calls these methods
when using groups outside a viewgen.

.. autoclass:: Endpoint
  :members:

.. autoclass:: Arrangement

.. automethod:: PlacementGroup.add

.. automethod:: PlacementGroup.child_rect

.. automethod:: PlacementGroup.arrangement

.. automethod:: PlacementGroup.rect

.. automethod:: PlacementGroup.resolve_connectivity

.. automethod:: PlacementGroup.emit

.. automethod:: ConnectingGroup.facing_pin

.. automethod:: ConnectingGroup.endpoint

.. automethod:: ConnectingGroup.side_endpoint
