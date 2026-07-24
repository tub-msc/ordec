Howto Layout
============

This howto collects the practical knowledge needed to write layout view generators: placing instances, orientations, geometric constraints, routing with the stack router, and pin creation. It complements the reference documentation (:doc:`ref/layout`, :doc:`ref/constraints`, :doc:`ref/geoprim`) with a task-oriented walkthrough and lists the pitfalls that are easy to hit.

Complete worked examples to study alongside this howto:

* ``ordec/examples/vco_pseudodiff.ord`` — a larger design in ORD syntax,
* ``tests/lib/lvs_example_hier.ord`` — small hierarchical resistor layouts in ORD syntax (DRC- and LVS-clean),
* ``tests/lib/lvs_example.py`` — an inverter layout in plain Python syntax.

Basic structure
---------------

A layout view generator is a ``viewgen layout -> Layout`` block in ORD (or an equivalent ``@generate`` method in Python that builds and returns a ``Layout`` subgraph). The first thing to set is ``ref_layers``, the technology's layer set:

.. code-block:: text

    viewgen layout -> Layout:
        .ref_layers = SG13G2().layers
        layers = .ref_layers

Layout coordinates are **integers in database units**. For SG13G2, one database unit is 1 nm (e.g. ``2500`` means 2.5 µm). This differs from schematics and symbols, which use rational coordinates on a coarse grid.

In ORD syntax, named child nodes are created with declaration blocks; in Python, by attribute assignment on the layout plus a ``Solver``:

.. code-block:: text

    # ORD: instance of the Rsil cell's layout, named r1
    Rsil(l='1u') r1:
        ! .pos == (0, 3000)

.. code-block:: python

    # Python equivalent
    l.r1 = LayoutInstance(ref=ihp130.Rsil(l='1u').layout)
    s.constrain(l.r1.pos == (0, 3000))

Orientations
------------

Instance orientation is set via the ``orientation`` attribute using the :class:`~ordec.core.geoprim.D4` enum (dihedral group: four rotations, four mirrored variants). Each value has two interchangeable names, a rotation/mirror name and a compass alias. **The compass aliases do not map to rotation angles the way one might guess** — they denote the direction the cell's top edge faces after the transform, while the rotation names follow the mathematical convention (``R90`` = 90° counterclockwise):

============ ======== ===== =========================================================
Compass name D4 value Short Effect on the placed cell
============ ======== ===== =========================================================
North        R0       N     unchanged; top edge faces north
West         R90      W     rotated 90° counterclockwise; top edge faces west
South        R180     S     rotated 180°; top edge faces south
East         R270     E     rotated 90° **clockwise**; top edge faces east
FlippedNorth MX       FN    mirrored vertically (y negated); top edge faces south
FlippedSouth MY       FS    mirrored horizontally (x negated); top edge stays north
FlippedWest  MX90     FW    mirrored, then rotated; top edge faces west
FlippedEast  MY90     FE    mirrored, then rotated; top edge faces east
============ ======== ===== =========================================================

So for a vertical resistor whose ``term_p`` is at the top: ``.orientation = East`` makes ``term_p`` face east, and ``.orientation = FlippedNorth`` flips it upside down (``term_p`` faces south) without mirroring left/right. The short names in the third column follow the familiar DEF orientation naming. The same enum is used for schematic instances and pin alignment.

Geometric constraints
---------------------

Positions and dimensions are usually not given as absolute numbers but as linear constraints, solved by :class:`~ordec.core.constraints.Solver`. In ORD syntax, a line starting with ``!`` declares a constraint; in Python, call ``s.constrain(...)`` on a ``Solver``:

.. code-block:: text

    Rsil(l='1u') r3:
        .orientation = FlippedNorth
        ! .term_m.cx == r1.term_m.cx          # align centers horizontally
        ! r1.term_m.cy == .term_m.cy + 2500   # 2.5 µm vertical spacing

Constraint expressions are linear: you can add/subtract terms, multiply by constants, and mix in rational weights (``! .cy == 0.5*a.cy + 0.5*b.cy`` centers between two anchors). Useful operands:

* ``instance.pos`` — the instance origin (a 2D vector; ``.pos.x`` / ``.pos.y`` for single coordinates).
* Rectangle anchors on shapes (own shapes and shapes inside instances): ``lx``, ``ly``, ``ux``, ``uy``, ``cx``, ``cy``, ``width``, ``height``, ``size``, ``center``, ``north``, ``south``, ``east``, ``west``, ``northwest``, ``northeast``, ``southwest``, ``southeast``, ``x_extent``, ``y_extent``, and the full ``rect``. Vector-valued anchors constrain both coordinates at once (``! .rect == r1.term_p.rect`` makes two rects coincide).
* ``a.contains(b)`` — inequality constraints keeping rect ``b`` inside rect ``a``.

Geometry of instances is accessed through the instance cursor with coordinates automatically transformed into the parent layout (``r1.term_p.rect`` is ``term_p`` of the resistor leaf cell, expressed in this layout's coordinates).

.. warning::

    Geometry **nested more than one instance level deep** (e.g. ``a1.r1.term_p.rect`` where ``a1`` is itself an instance containing instance ``r1``) currently cannot be used in constraints; it fails with ``TypeError: 'TD4LinearTerm' object cannot be interpreted as an integer``. Constrain against first-level geometry (possibly plus a constant offset) instead. See ``NOTES.md`` in the repository root for the analysis of this limitation.

Routing with SRouter
--------------------

``SRouter`` (``ordec/layout/srouter.py``) draws wires as ``LayoutPath`` nodes, with widths, extensions and via sizes taken from a technology-provided :class:`~ordec.core.schema.RoutingSpec` (e.g. ``SG13G2().default_routing_spec``). It works like an SVG-style turtle:

.. code-block:: text

    sr = SRouter(SG13G2().default_routing_spec)
    sr.move(layers.Metal1, r1.term_m.center)  # set start point and layer ('M')
    sr.wire_y(r3.term_m.cy)                   # vertical wire ('V')
    sr.move(layers.Metal1, r2.term_m.center)  # start a second, separate wire
    sr.wire_x(r1.term_m.cx)                   # horizontal wire onto the spine ('H')

* ``move(layer, pos)`` sets the current layer and position without drawing and starts a new path. Positions may be constraint expressions (e.g. shape anchors), so routes stay attached when the placement solution changes.
* ``wire(pos)``, ``wire_x(x)``, ``wire_y(y)`` draw a wire segment to the new position.
* ``layer(layer)`` switches to another metal: the router walks the routing-spec layer stack between the two metals and places via-sized rects on every layer crossed (via cut layers and landing pads), so a simple ``layer()`` call produces a complete via stack at the current position.
* ``push()`` / ``pop()`` save/restore the current position and layer, convenient for branching a route (e.g. a T-junction: route the spine, ``push()`` at the branch point, finish the spine, ``pop()``, route the branch).

In ORD layout viewgens, ``SRouter()`` picks up the current layout and solver from the view context automatically; in plain Python, pass them explicitly (``SRouter(spec, layout=l, solver=s)``).

Creating pins
-------------

Layout pins associate a shape with a symbol pin; they become labeled pin shapes in the GDS export and are required for LVS to identify top-level ports by name. There are two equivalent forms:

.. code-block:: text

    # Form 1: a named shape, with create_pin()
    LayoutRect x:
        .layer=layers.Metal1
        ! .rect == r1.term_p.rect
        .create_pin(self.symbol.x)

    # Form 2: pin on a routed path (the LayoutPath created by the last wire)
    sr.wire_y(r3.term_m.cy)
    sr.path.create_pin(self.symbol.c)

In Python syntax, the equivalent is attaching a ``LayoutPin`` node with the ``%`` operator: ``l.m1_vss % LayoutPin(pin=self.symbol.vss)``.

Note that in hierarchical designs, not every port needs a pin shape in every cell: KLayout matches subcell pins topologically. Top-level pins are matched by name and do need labeled shapes. For the substrate pins of resistors, see :ref:`ihp130_substrate_lvs`.

Verifying the result
--------------------

* View the layout in the web UI: ``ordec -b -m "mymodule:MyCell().layout"`` (see :doc:`webui`).
* Run DRC: ``ihp130.run_drc(MyCell().layout).summary()`` returns ``{}`` when clean. Keep ≥1 µm clearance between resistor/device instance bounding boxes to stay clear of the poly-resistor spacing rules.
* Run LVS against the schematic: ``ihp130.run_lvs(MyCell().layout, MyCell().symbol)`` (see :doc:`ref/layout_klayout` for how hierarchical comparison works).
* ``run_drc``/``run_lvs`` accept ``use_tempdir=False`` to keep the intermediate files (GDS, netlists, reports) in a local ``drc/``/``lvs/`` directory for inspection.
