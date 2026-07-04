:mod:`ordec.layout.pnr` --- Gridded standard-cell place and route
=================================================================

.. automodule:: ordec.layout.pnr

The engine is PDK-agnostic: :func:`~ordec.layout.pnr.place_and_route` takes a
:class:`~ordec.layout.pnr.RoutingStack` (the engine's abstract routing codes mapped to
concrete PDK layers), a per-cell LEF pin-rectangle lookup, an "is this a routing leaf?"
predicate and a :class:`~ordec.layout.pnr.GridConfig` -- the routing grid *and* the
DRC-driven emission geometry (wire/via/landing/strap dimensions) -- as arguments. No PDK
layer, pitch or design-rule dimension is baked into the engine; it reads every value from
these inputs. It sits
alongside :doc:`SRouter <layout>` and the :doc:`KLayout integration <layout_klayout>`.
:mod:`ordec.layout.ihp_pnr` binds these inputs to the sg13g2 standard-cell library -- its
grid/geometry profile is ``sg13g2_grid()`` -- and exposes a one-argument
``place_and_route(cell)`` that a design's layout view generator calls directly.

``place_and_route`` runs the same pipeline a production flow does, applied to a single
block: it flattens the schematic to foundry leaf cells, orders and folds them into
abutted standard-cell rows, routes all signal nets on a fixed track grid, and emits
geometry that is DRC-clean by construction. The algorithms are textbook ones —
simulated-annealing placement, flipped-row floorplanning, and negotiated-congestion maze
routing with A\* — so the engine is a faithful miniature of a real flow rather than a
heuristic stand-in (see `Algorithmic fidelity and scope`_).

The routing grid
----------------

Tracks come from the ``GridConfig`` profile, not from the engine. For the sg13g2 binding
(``ihp_pnr.sg13g2_grid``) they are the IHP tech-LEF values: Metal2 is vertical on a
0.48 µm pitch, Metal3 is horizontal on 0.42 µm, and the row is 3.78 µm = 9 Metal3 tracks
tall. Cells are an integer number of Metal2 tracks wide. Because the foundry leaf cells
are Metal1-only for signals, Metal2 and Metal3 over them are free, so routing happens *on
the grid, over the cells* — pin access is a Via1 up from the Metal1 pin onto a Metal2
track. This grid, captured in ``GridConfig``, is the shared coordinate system for
everything downstream.

Placement
---------

#. **Flatten** (``flatten``) — the schematic is expanded recursively to its foundry
   leaf cells. Foundry standard cells (``sg13g2_*`` — inverter, mux2, dff, …) are
   leaves, kept as-is; any instance that is itself a non-foundry composite is replaced
   by the contents of its schematic, with internal nets uniquified by an instance
   prefix and the sub-cell's ports rewired to the parent's nets.
#. **Order** (``order_cells_sa``) — cells are ordered to minimise wirelength by
   *simulated annealing*, seeded from an iterated-barycenter order. The cost is
   half-perimeter wirelength with the vertical span weighted 2× (a net that crosses rows
   is far harder to route than one that stays within a row). Moves are scored
   *incrementally*, as production annealers do: a swap re-measures only the nets touching
   the two swapped cells, with a periodic exact re-fold bounding the drift. A fixed seed
   keeps the result deterministic.
#. **Fold into rows** (``place_rows``) — the one-dimensional order is folded into *N*
   abutted rows. Odd rows are *mirrored* (D4.MX) *and reversed* — a boustrophedon, or
   snake: mirroring lets adjacent rows share a vdd/vss rail (the standard flipped-row
   layout), and reversing keeps the dataflow adjacent across the turn. Pin rectangles are
   transformed to match.
#. **Grow rows on failure** — the row count starts near a square aspect ratio and is
   incremented until the router succeeds (the Metal3 spacing rule limits how many nets
   fit in one channel). Only congestion triggers a retry: a *permanent* failure — a pin
   with no reachable access point (``PinAccessError``) — is raised immediately, since
   more rows cannot fix it.

Routing: negotiated congestion
------------------------------

All signal nets are routed together by rip-up-and-reroute (``route_nets``), using
negotiated-congestion maze routing. A coarse **global-routing** pass (``global_route``)
first gives each net a *corridor* of grid cells, balancing congestion on a cheap gcell
grid; detailed routing then stays inside that corridor (falling back to the full grid only
when a net cannot be realised there), which keeps the maze search local as blocks grow:

* Multi-terminal nets are decomposed into independent 2-pin *segments* along a minimum
  spanning tree over their terminals. Each segment first tries the two one-bend
  **L patterns** on conflict-free nodes (a few dict probes instead of a maze search, and
  in the uncongested initial pass almost every segment is a clean L); only a blocked
  segment falls back to **A\*** (``_astar``) on the track
  grid: vertical layers (Metal2, Metal4) step in y, horizontal layers (Metal3, Metal5)
  step in x, and a via cost switches layer (Metal4/Metal5 are enabled by ``use_upper``,
  doubling routing capacity; Metal2/Metal3 alone otherwise). The A\* heuristic is
  *via-aware* — it adds the provable minimum number of layer changes to the distance
  bound, which prunes most off-layer exploration. Vertical wires may pass *through* a
  rail track to reach another row; vias and horizontal wires sit only on signal tracks.
* After the initial routing, each **conflict** raises the cost of the offending grid
  nodes and *only the nets touching it* are ripped up and rerouted — incremental rip-up,
  a handful of nets per pass rather than all of them, is what lets this scale. A conflict
  is a node used by two nets, **or** two nets whose facing wire *ends* are one grid step
  apart on the same track: the 150 nm end extension puts those ends closer than the metal
  spacing (a horizontal wire one x-step apart, a vertical wire one y-step apart). Adjacent
  *parallel* tracks are a full pitch apart and legal, so they are deliberately not
  flagged. The penalty accumulates as *historical* congestion, so nets that keep colliding
  are progressively pushed apart until the routing is legal; that growing history cost on
  the contested nodes is what stops two nets oscillating over one resource (the conflicting
  nets themselves are rerouted in a deterministic sorted order each pass). The conflict
  sets are maintained *incrementally* as segments are placed and ripped up, so a
  negotiation pass costs proportional to the conflicts it fixes, not to the total
  wirelength routed so far.

Because the spacing rules are encoded directly in the conflict model, a converged routing
is DRC-clean by construction rather than clean by luck.

Geometry, and the DRC details that bite
----------------------------------------

Wires and via stacks are emitted directly as concrete grid coordinates
(``emit_net_direct``), not through ORDeC's constraint solver — which is fast per cell but
does not scale to the few-hundred-net blocks this targets. The engine reads every dimension
from the ``GridConfig``; three sg13g2 DRC specifics set the values in its profile
(``ihp_pnr.sg13g2_grid``):

* **Pin access uses the LEF rectangles**, not GDS-polygon bounding boxes. ``Nor2``'s Y
  and B pins overlap *by bounding box*, so a bbox-driven via would short two nets; the
  clean per-pin LEF rects place the Via1 on exactly the intended pin, with an enclosure
  test (≥ 10 nm on all sides, ≥ 50 nm on one) so it is never on too narrow a finger.
* **Min area (0.144 µm²) and the via endcap (50 nm)** cannot be met by an isolated via
  landing at this pitch — the *wire* must carry them. So wires are 210 nm (enclosing the
  190 nm cut by 10 nm) and extend 150 nm past each end (a 50 nm endcap at an end-via), and
  a post-pass (``extend_min_area``) lengthens any too-short segment into free tracks to
  reach min area.
* **Metal3 spacing (210 nm)** is exactly one track pitch minus the wire width, so
  adjacent parallel tracks sit at exactly the minimum spacing — legal, but with no slack.
  That tightness is why facing wire-ends conflict and why a too-full channel forces the
  row-count growth above.

Algorithmic fidelity and scope
------------------------------

The algorithms are the real thing. Negotiated-congestion routing, A\* maze routing,
simulated-annealing placement and flipped-row floorplanning are the same foundational
techniques production place-and-route tools are built on, and here they run as a complete,
end-to-end flow that turns a schematic into real silicon geometry — DRC-clean against the
maximal sign-off rule set and LVS-matched to the source.

What separates it from a production flow is scale and scope, not correctness:

* **Scale** — it targets blocks of tens of cells, where production tools handle millions.
  At that scale modern placement is *analytical* (electrostatics/quadratic) rather than
  annealing, and the global/detailed routing split — which this engine mirrors in miniature
  with gcell corridors — relies on far more elaborate congestion models. Measured envelope
  (DFF+INV benchmark, single core): ~100 cells routes in well under a second, ~200 cells
  in ~2 s, ~250 cells in ~4 s. The structural choices that carry this scaling are the MST
  2-pin decomposition with segment-level rip-up (a conflict on a high-fan-out net
  reroutes one 2-pin connection, not the whole tree), the L-pattern fast path with
  incremental conflict bookkeeping (the maze search and the congestion scan both stay
  proportional to the contested part of the design, not to all of it), and the per-port
  reserved escape columns (single-goal, contention-free escape searches).
* **Timing** — production P&R is timing-driven (STA-guided placement, buffering,
  useful-skew clock-tree synthesis); this engine optimises wirelength and leaves timing
  closure to the designer.
* **Design rules** — it encodes the handful of rules that actually constrain this
  geometry (via enclosure, min area, M2/M3 spacing) directly into the router, so the
  result is correct by construction; full sign-off DRC is hundreds of rules
  (parallel-run-length tables, end-of-line, cut spacing, min-step…), for which
  the KLayout deck remains the authority. Note the scope of that sign-off: the PDK's
  **antenna** and **density** rules live in separate KLayout decks that
  ``ihp130.run_drc`` does not run, so "DRC-clean" here excludes them. Density is
  intrinsically a chip-assembly concern (checked in 200 µm windows, larger than these
  blocks), but antenna ratios on long upper-metal routes into gate pins are exactly the
  pattern this router produces — check them at top level before tapeout.
* **Out of scope by design** — clock-tree synthesis, power planning beyond rail abutment,
  antenna fixing, fill, multi-Vt and deep (5–15 layer) routing.

The result is a compact but genuinely faithful flow: the right algorithms, applied end to
end, producing sign-off-clean layout for real foundry cells — with production scale and the
timing/sign-off machinery deliberately left out.

Public API
----------

.. autofunction:: ordec.layout.pnr.place_and_route

.. autoclass:: ordec.layout.pnr.RoutingStack
   :members:

.. autoclass:: ordec.layout.pnr.GridConfig
   :members:
