:mod:`ordec.layout.pnr` --- Gridded standard-cell place and route
=========================================================================

.. automodule:: ordec.layout.pnr

The engine is PDK-agnostic. :func:`~ordec.layout.pnr.place_and_route` reads a
``Schematic``, writes into a caller-owned mutable ``Layout``, and takes everything a PDK
must supply as explicit parameters: the PDK's
:class:`~ordec.core.schema.RoutingSpec` (the engine binds its abstract routing codes to
the spec's nine lowest ``route_id`` layers, so the layer stack has its single source of
truth in :mod:`ordec.core.schema`, shared with :doc:`SRouter <layout>`), a
:class:`~ordec.layout.pnr.GridConfig` (the routing grid and the DRC-driven
emission geometry such as wire, via, landing and strap dimensions) and a per-cell
pin-rectangle lookup, which :func:`~ordec.layout.pnr.lef_pin_rects` reads out of a
library LEF for a given pin layer. An "is this a routing leaf?" predicate can be passed
too, but defaults to treating every cell loaded from an
:class:`~ordec.extlibrary.ExtLibrary` as a leaf, which is what a foundry standard cell
is. No PDK layer, pitch or design-rule dimension is baked into the engine. It sits alongside :doc:`SRouter <layout>`
and the :doc:`KLayout integration <layout_klayout>`. :mod:`ordec.lib.ihp130` supplies
the sg13g2 grid profile and the LEF path, and ``SG13G2().default_routing_spec`` supplies
the layers. In an ORD ``viewgen layout`` body the bare dot passes the view's own root as
the layout to emit into:

.. code-block:: python

   pin_rects = lef_pin_rects(ihp130.pdk().stdcell_lef, "Metal1")

   cell Block:
       # symbol and schematic viewgens ...

       viewgen layout -> Layout:
           place_and_route(self.schematic, ., grid=ihp130.grid,
               routing_spec=ihp130.SG13G2().default_routing_spec,
               pin_rects=pin_rects)

``place_and_route`` runs the same pipeline a production flow does, applied to a single
block. It flattens the schematic to foundry leaf cells, orders and folds them into
abutted standard-cell rows, routes all signal nets on a fixed track grid, and emits
geometry that is DRC-clean by construction. The algorithms are textbook ones:
simulated-annealing placement, flipped-row floorplanning, and negotiated-congestion maze
routing with A\* (see `Scope`_).

The engine wants a standard-cell library: abutting rails, Metal1-only pins, integer-track
cell widths. An analog placement flow would be a sibling package rather than a mode of
this one.

The package is one module per phase. ``place`` orders cells and folds them into rows,
``route`` does pin access, pattern and maze search and the rip-up loop, and ``flow`` holds
the ORDeC boundary, the configuration and the entry point. ``place`` and ``route`` import
nothing from their siblings. ``route`` imports nothing from ORDeC at all, and ``place``
touches only the plain geometry values (``Rect4I``, ``D4``), never a Schematic or a
Layout, so a placement or a routing problem can be built from plain values.

Standard-cell coverage
----------------------

The engine routes most IHP sg13g2 logic and sequential cells, about 60 of 74. The rest
fail loudly. A cell with LEF geometry above Metal1 (``sdfbbp``) is left out of the
pin-rectangle lookup and rejected with a clear exception when the engine looks it up,
since the engine routes the metals above the leaf cells. A
few cells with very small or staircase pins (``a21o``, ``dlhrq``) can hit a Via1 endcap
landing that cannot be satisfied without an M1.b or V1.c1 violation, and fixing those
would take a polygon-exact via-access engine. Non-logic cells (antenna, fill, decap) are
out of scope.

The routing grid
----------------

Tracks come from the ``GridConfig`` profile, not from the engine. For the sg13g2 binding
(``ihp130.grid``) they are the IHP tech-LEF values. Metal2 is vertical on a
0.48 µm pitch, Metal3 is horizontal on 0.42 µm, and the row is 3.78 µm, which is 9 Metal3
tracks tall. Cells are an integer number of Metal2 tracks wide. Because the foundry leaf
cells are Metal1-only for signals, Metal2 and Metal3 over them are free, so routing
happens *on the grid, over the cells*, with pin access a Via1 up from the Metal1 pin onto
a Metal2 track. This grid, captured in ``GridConfig``, is the shared coordinate system for
everything downstream.

Placement
---------

#. **Flatten** (``flatten_schematic``) expands the schematic recursively to its foundry
   leaf cells. Cells loaded from the PDK reference files into an ``ExtLibrary`` (so
   inverter, mux2, dff and the rest) are leaves and are kept as-is. Any instance that is
   itself an ORDeC-authored composite is replaced by the contents of its schematic, with
   internal nets uniquified by an instance prefix and the sub-cell's ports rewired to the
   parent's nets.
#. **Order** (``order_cells_sa``) orders cells to minimise wirelength by *simulated
   annealing*, seeded from an iterated-barycenter order. The cost is half-perimeter
   wirelength with the vertical span weighted 2×, since a net that crosses rows is far
   harder to route than one that stays within a row. Moves are scored *incrementally*, as
   production annealers do. A swap re-measures only the nets touching the two swapped
   cells, with a periodic exact re-fold bounding the drift. A fixed seed keeps the result
   deterministic.
#. **Fold into rows** (``place_rows``) folds the one-dimensional order into *N* abutted
   rows. Odd rows are *mirrored* (D4.MX) *and reversed*, a boustrophedon or snake.
   Mirroring lets adjacent rows share a vdd/vss rail, which is the standard flipped-row
   layout, and reversing keeps the dataflow adjacent across the turn. The result is
   applied to the layout's ``LayoutInstance`` nodes, which are the engine's placement
   representation, and the die-coordinate pin rectangles the router works on are derived
   from them (``transform_pins``).
#. **Grow rows on failure.** The row count starts near a square aspect ratio and is
   incremented until the router succeeds, since the Metal3 spacing rule limits how many
   nets fit in one channel. Only congestion triggers a retry. A *permanent* failure, a pin
   with no reachable access point (``PinAccessError``), is raised immediately, since more
   rows cannot fix it. The instances are created once and their positions updated per
   attempt, so even a run that never converges leaves its last placement in the layout
   to inspect.

Routing: negotiated congestion
------------------------------

All signal nets are routed together by rip-up-and-reroute (``route_nets``), using
negotiated-congestion maze routing. A coarse **global-routing** pass (``global_route``)
first gives each net a *corridor* of grid cells, balancing congestion on a cheap gcell
grid. Detailed routing then stays inside that corridor, falling back to the full grid only
when a net cannot be realised there, which keeps the maze search local as blocks grow:

* Multi-terminal nets are decomposed into independent 2-pin *segments* along a minimum
  spanning tree over their terminals. Each segment first tries the two one-bend
  **L patterns**, then the two-bend **Z patterns** (sweeping the crossover track), on
  conflict-free nodes. That is a few dict probes instead of a maze search, and in the
  uncongested initial pass almost every segment is a clean pattern. Only a blocked
  segment falls back to **A\*** (``astar``) on the track grid, where vertical layers
  (Metal2, Metal4) step in y, horizontal layers (Metal3, Metal5) step in x, and a via cost
  switches layer. Metal4 and Metal5 are enabled by ``use_upper`` and double the routing
  capacity, otherwise Metal2 and Metal3 route alone. The A\* heuristic is *via-aware*: it
  adds the provable minimum number of layer changes to the distance bound, which prunes
  most off-layer exploration. Vertical wires may pass *through* a rail track to reach
  another row. Vias and horizontal wires sit only on signal tracks.
* After the initial routing, each **conflict** raises the cost of the offending grid
  nodes and *only the nets touching it* are ripped up and rerouted. This incremental
  rip-up, a handful of nets per pass rather than all of them, is what lets the engine
  scale. A conflict is a node used by two nets, **or** two nets whose facing wire *ends*
  are one grid step apart on the same track. The 150 nm end extension puts those ends
  closer than the metal spacing, one x-step apart for a horizontal wire and one y-step for
  a vertical one. Adjacent *parallel* tracks are a full pitch apart and legal, so they are
  deliberately not flagged. The penalty accumulates as *historical* congestion, so nets
  that keep colliding are progressively pushed apart until the routing is legal. That
  growing history cost on the contested nodes is what stops two nets oscillating over one
  resource, and the conflicting nets themselves are rerouted in a deterministic sorted
  order each pass. The conflict sets are maintained *incrementally* as segments are placed
  and ripped up, so a negotiation pass costs proportional to the conflicts it fixes rather
  than to the total wirelength routed so far.

Because the spacing rules are encoded directly in the conflict model, a converged routing
is DRC-clean by construction rather than clean by luck.

Geometry emission
-----------------

Wires and via stacks are emitted directly at concrete grid coordinates
(``emit_net_direct``) rather than through ORDeC's constraint solver, which is fast for a
single cell but does not scale to the few-hundred-net blocks this engine targets. Every
dimension the emitter uses comes from the ``GridConfig`` profile. The sg13g2 values and
the design rules each one derives from are documented field by field in
``ihp130.grid``.

Two choices matter when writing a profile for another PDK. Pin access works on the clean
per-pin LEF rectangles, never on GDS bounding boxes, since pins can overlap by bounding
box (nor2's Y and B do) and a bbox-driven via would short two nets. And the metal
min-area and via-endcap rules are carried by the wires themselves rather than by
isolated via landings, which cannot satisfy them at this pitch. That is why every run
spans a minimum number of tracks (``extend_min_area``) and overhangs its end vias.

Power delivery
--------------

Within a row, power is carried by rail abutment, as in any standard-cell flow. A
multi-row block gets two more structures. A single-row block needs neither, since its one
shared rail per supply already ties everything:

* **Side straps** (``emit_power_straps``) are a vertical Metal2 strap per supply in the
  margin on each side of the cell area, tapping every rail. The ring ties the rails the
  boustrophedon leaves separate and exposes the supply ports on Metal4 pads in the margin.
* **Power mesh** (``emit_power_mesh``) is a horizontal Metal5 strap over every *interior*
  rail, meaning the rails shared between two abutted rows, which carry the most current.
  Each strap is stitched down to its rail by via stacks at regular tap columns, and the
  rails carry the mesh current on to the side straps. Rail current then flows at most half
  a tap pitch on thin Metal1 instead of the full row length, which is what bounds IR drop
  as blocks grow wider. The straps sit on the rail lines, where the router can never place
  a wire because a layer change is forbidden on rail tracks, so the mesh costs almost no
  routing capacity. The tap via stacks and the tracks beside the wide straps are reserved
  as hard blockages (``mesh_blocked_nodes``) that terminal access, the pattern router, the
  maze router and the min-area growth all respect. Because those blockages are hard, the
  tap columns are chosen around the placement's pin accesses (``tap_avoid_columns``). A
  tap that invalidates a terminal's every access candidate would deadlock the rip-up
  negotiation, since such a terminal cannot retreat to an alternative. It can do that by
  strangling the terminal's min-area growth against a neighbor or by crowding out its
  off-track access bridge, so each nominal tap is nudged to the nearest harmless column
  instead. The mesh stays strictly within the die. The side margins and the strip above
  the top rail are the *parent's* territory, where its risers to the edge pads run, which
  is what keeps the block composable. ``GridConfig.power_mesh`` switches the mesh on and
  off and ``mesh_tap_pitch`` sets the stitch density.

The supply pin and net names (``VDD``, ``vdd`` and so on) are part of the ``GridConfig``
profile rather than the engine. The sg13g2 conventions live in ``ihp130.grid``.

The block interface
-------------------

Every signal port is routed out to the top or the bottom edge and exposed on a Metal4 pad
straddling that rail, out in the parent's channel. The parent therefore lands on the pad
and never routes over the block interior, which is what keeps a composition robust: a
placement change inside the block cannot drop a parent wire onto an internal net. The
supplies need no escape, since they leave on the side straps.

Which edge a port takes is normally the parent's decision, since only the parent knows
what sits above and below the block. Pass it in::

    place_and_route(schematic, layout, ...,
        port_edges={'clk': 'bottom', 'done': 'top'})

This is the same constraint a production flow applies at the floorplan stage, where pin
placement is decided top-down and pushed into each block. A parent's layout view
generator is the natural place to derive the mapping, since it has already placed the
block and its neighbours.

A port left out of ``port_edges`` falls back to whichever edge its own terminals sit
nearer, so a block routed on its own still does something sensible: a net driven from the
bottom row does not climb the whole block to leave it and come straight back down. On an
8-bit register array that halves the routed wirelength, from 366 um to 210 um, with 14 of
the 18 ports leaving at the bottom.

The fallback is worth understanding before relying on it. It sees only the block's own
terminals, never the parent's connectivity, so it is uninformed about the very thing that
should decide the answer. A port driven from the bottom row whose consumer sits above the
block will be sent out of the bottom and make the parent's route longer, not shorter.
Constrain those ports rather than leaving them to the heuristic.

Within an edge, every port gets its own reserved column near the mean x of its pin
candidates. Uniqueness removes pad contention by construction and keeps each escape a
directed single-goal search. The two edges allocate independently, since a top and a
bottom pad in the same column never meet.

The pads sit on Metal4, a vertical layer, which is the usual convention: a wire reaches
an edge perpendicular to it, so a top or bottom pin wants a vertical layer. Left and
right pins would want a horizontal one, Metal3 or Metal5, and the mirrored mechanism of
reserved rows rather than reserved columns. The engine does not implement that today, so
a block presents two faces rather than four.

Scope
-----

The techniques are the standard ones production place-and-route tools build on:
negotiated-congestion routing, A\* maze search, simulated-annealing placement and
flipped-row floorplanning, run as one flow from schematic to geometry that is DRC-clean
against the maximal sign-off rule set and LVS-matched to the source. What separates it
from a production flow is scale and scope:

* **Scale.** It targets blocks of tens of cells, where production tools handle millions.
  At that scale modern placement is *analytical* (electrostatic or quadratic) rather than
  annealing, and the global and detailed routing split, which this engine mirrors in
  miniature with gcell corridors, relies on far more elaborate congestion models. Measured
  envelope on the DFF and INV benchmark, single core: about 100 cells route in well under
  a second, about 200 cells in 2 s, about 250 cells in 4 s. Three structural choices carry
  this scaling. The MST 2-pin decomposition with segment-level rip-up means a conflict on
  a high-fan-out net reroutes one 2-pin connection rather than the whole tree. The
  L/Z-pattern fast path with incremental conflict bookkeeping keeps both the maze search
  and the congestion scan proportional to the contested part of the design rather than to
  all of it. The per-port reserved escape columns give single-goal, contention-free escape
  searches.
* **Timing.** Production P&R is timing-driven, with STA-guided placement, buffering and
  useful-skew clock-tree synthesis. This engine optimises wirelength and leaves timing
  closure to the designer.
* **Design rules.** The engine encodes the handful of rules that actually constrain this
  geometry (via enclosure, min area, M2 and M3 spacing) directly into the router, so the
  result is correct by construction. Full sign-off DRC is hundreds of rules
  (parallel-run-length tables, end-of-line, cut spacing, min-step and more), for which
  the KLayout deck remains the authority. That sign-off (``ihp130.run_drc``) covers the
  main and maximal rule sets plus, by default, the PDK's **antenna** deck. Antenna ratios
  on long upper-metal routes into gate pins are exactly the pattern this router produces,
  so they are checked rather than assumed. The **density** deck is off by default
  (``run_drc(..., density=True)`` enables it), since its 200 µm check windows exceed
  these block sizes, making it intrinsically a chip-assembly concern.
* **Out of scope by design:** clock-tree synthesis, antenna fixing, fill cells and
  multi-Vt libraries. Routing stays on Metal2 to Metal5, so sg13g2's thick top metals
  (TopMetal1, TopMetal2) are never touched and remain free for the assembly above the
  block.

Public API
----------

.. autofunction:: ordec.layout.pnr.place_and_route

.. autofunction:: ordec.layout.pnr.is_extlibrary_leaf

.. autoclass:: ordec.layout.pnr.GridConfig
   :members:

.. autoclass:: ordec.layout.pnr.PnrResult
   :members:

.. autoexception:: ordec.layout.pnr.PinAccessError
