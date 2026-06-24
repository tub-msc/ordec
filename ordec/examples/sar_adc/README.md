<!--
SPDX-FileCopyrightText: 2026 ORDeC contributors
SPDX-License-Identifier: Apache-2.0
-->

# SAR ADC example (IHP SG13G2)

A complete, hierarchical **successive-approximation-register (SAR) analog-to-digital
converter** built in ORDeC with the IHP SG13G2 130 nm PDK. It is a mixed-signal
design in the spirit of the `vco_pseudodiff` example: custom analog blocks and
transistor-level digital logic composed through ORDeC's cell/view hierarchy, all
written in the ORD HDL and simulated against the real PDK models with Ngspice. Every
block has a complete physical layout that is DRC-clean against the maximal sign-off
rule set and LVS-matched to its schematic, up to and including the assembled top level.

The architecture is a **charge-redistribution SAR ADC** parameterized in resolution
`n`, verified at the default **4 bits** and at **3 bits** (`n=3`). Higher `n` is not
supported as-is — the testbench clocking and the largest capacitor would need
revisiting first. The reference voltage is `Vref = VDD = 1.2 V` and the common mode is
`vcm = VDD/2`.

```
        vin ---->|            |
                 |   CapDac   |---- vx (top plate) ----+
      dac[ ] --->| (S/H + DAC)|                        |
                 +------------+                        v
                      ^                          +-----------+
                      | dac[ ]                   | Comparator|  in_p = vcm
                      |                cmp <------|  (static) |  in_n = vx
                 +----------+                    +-----------+
      clk  ----->|          |                         |
      rst  ----->| SarLogic |<------------- cmp -------+
                 |          |---- sample / done / code[ ]
                 +----------+
```

Each conversion samples `vin` onto the capacitor array, then resolves the bits
MSB-first by binary search: the comparator reports whether the sampled input still
exceeds the current DAC value, and the SAR controller keeps or drops each trial bit
accordingly. A conversion takes `n + 2` clocks after `rst`, and `done` strobes when the
result on `code[n-1..0]` is valid.

## Architecture

* **CapDac** (`cdac.ord`) — the binary-weighted MIM-capacitor array, built as a
  *matched array of identical unit capacitors* (bit `i` = `2**i` units in parallel, so
  the weights track as an exact device-count ratio) plus a dummy unit cap, with
  transmission-gate bottom-plate switches. It doubles as the sample-and-hold. Because
  `Vref = VDD`, the digital bit signals drive the bottom plates directly (through a
  switch that opens during sampling), and charge conservation gives
  `vx = vcm - vin + (code / 2**n)·Vref`.
* **Comparator** (`comparator.ord`) — a self-biased NMOS differential pair with a PMOS
  current-mirror load and two inverter output buffers. It is continuous-time rather than
  clocked, so there is no strobe edge to align with DAC settling — which is what makes
  the closed loop easy to bring up. Measured input offset ≈ 1.3 mV.
* **SarLogic** (`sar_logic.ord`) — a shift-register sequencer carries a one-hot token
  (sample → MSB → … → LSB → done); per-bit load-enable registers capture the comparator
  decision at the right clock, with `dac[k] = code[k] OR on_trial[k]`.
* **Standard cells** (`stdcell_lib.py`) — the logic cells (`Inv`, `Nand2`, `Nor2`,
  `Mux2`, `Or2`, the `dfrbp` flip-flop, …) are loaded straight from the IHP SG13G2
  library as an `ExtLibrary`: LEF symbol + GDS layout + SPICE schematic. The SAR design
  instantiates these real foundry cells by their native pin names. The one hand-built
  cell is the transmission gate `Tgate` (`tgate.ord`), since the foundry library has no
  transmission-gate macro.
* **SarAdc / SarAdcTb** (`sar_adc.ord`) — the top-level converter loop and a
  demonstration testbench whose `report_tran` view plots the input, the DAC search node
  `vx`, the reconstructed staircase and the digital output bits.

## Verification

The example ships with a test suite (`tests/test_sar_adc.py`) covering both function and
physical correctness:

* Every cell elaborates, and the top level netlists with all pins connected.
* **Conversion** — at the default 4 bits, representative mid-bin inputs convert to the
  expected codes; at 3 bits the full transfer function is checked (all eight mid-bin
  inputs map to codes 0…7), exercising the design at both resolutions.
* The SAR controller, comparator and CDAC are each verified in isolation.
* **Layout sign-off** — the `Tgate` standard cell, the `SarLogic` control block, the
  analog `Comparator` and `CapDac`, and the full `SarAdc` top level (all four sub-blocks
  placed and routed together) are each DRC-clean (maximal rule set) and LVS-matched.

## Physical layout

The leaf devices (`Nmos`, `Pmos`, `Cmim`) carry their own PDK PCell layouts. On top of
those, each block has a complete, sign-off-clean layout:

* **Foundry standard cells** — the logic cells are the real IHP GDS cells
  (`stdcell_lib.py`), DRC/LVS-clean by construction and Metal1-only for signals.
* **`Tgate`** — the one hand-built standard cell (`tgate.ord`): NMOS over PMOS in a
  single stacked column, with the two independent gates contacted outside the
  source/drain bars so that no Metal2 is needed.
* **`SarLogic`** — the digital control block, laid out by the gridded place-and-route
  engine (`pnr.py`): the schematic is flattened to foundry leaf cells, ordered into
  abutted flipped rows by simulated annealing, then wired by a negotiated-congestion
  maze router (A\*, Metal2 vertical / Metal3 horizontal, Via1 pin access,
  rip-up-and-reroute until DRC-clean). The engine is described under *Place and route*
  below.
* **`Comparator`** — a hand-crafted **analog** layout (`comparator.ord`): the
  single-stage OTA core (a two-finger matched differential pair, a current-mirror load,
  a fingered tail current sink and a self-bias column, all in one shared n-well) is
  built from constrained device PCells; the two output-buffer inverters are placed as
  foundry `Inv` instances and wired in with `ordec.layout.SRouter`.
* **`CapDac`** — a hand layout (`cdac.ord`) of the capacitor array and its
  transmission-gate switches. Each bit is a *matched array of identical unit capacitors*
  (bit `i` = `2**i` `m=1` units stacked in its column — the `Cmim` PCell supports only
  `m=1`), so the binary weights track as an exact device-count ratio rather than by
  scaling one capacitor's dimensions; this is what keeps INL/DNL accurate across process
  gradients. A per-column Metal5 strap ties each bit's unit bottom plates to its
  `bp[i]`, a single TopMetal1 plate ties all top plates to `vx`, and the digital control
  and supply nets run on Metal3 buses over the switch row.

### Top-level composition (`SarAdc`)

The top level (`sar_adc.ord`) places the four sub-blocks (`CapDac`, `Comparator`,
`SarLogic`, sample inverter) and routes the inter-block nets on Metal4 trunks and Metal5
columns. The composition stays robust because **each block exposes its ports on its
edge** — `SarLogic`'s signals on Metal4 pads above its top rail and its supplies on the
side power-ring straps (the `pnr.py` edge-escape pass), `CapDac`'s on its bottom edge —
so the parent only ever routes in the channels between blocks and never crosses a block
interior. A placement change therefore cannot create a new over-cell short. The
floorplan is **computed from the blocks' bounding boxes** rather than hand-placed, so it
re-derives itself whenever the resolution changes.

Two analog-specific touches go beyond simply passing DRC/LVS:

* the critical **`vx` net** (DAC top plate → comparator input) is routed as a short,
  direct Metal4 wire, with the comparator aligned to it, instead of detouring down
  through the trunk band and back; and
* a **`vss`-tied substrate guard bar** sits in the gap between the digital `SarLogic`
  and the analog blocks, collecting substrate noise before it reaches the comparator and
  CDAC.

## Place and route

`pnr.py` is a gridded standard-cell place-and-route engine. `place_and_route(cell)` runs
the same pipeline a production flow does, applied to a single block.

### The routing grid

Tracks come straight from the IHP tech LEF (`sg13g2_tech.lef`): Metal2 is vertical on a
0.48 µm pitch, Metal3 is horizontal on 0.42 µm, and the row is 3.78 µm = 9 Metal3 tracks
tall. Cells are an integer number of Metal2 tracks wide. Because the foundry leaf cells
are Metal1-only for signals, Metal2/Metal3 over them are free, so routing happens *on
the grid, over the cells* — pin access is a Via1 up from the Metal1 pin onto a Metal2
track. This grid is the shared coordinate system for everything downstream.

### Placement

1. **Flatten** (`_flatten`) — the schematic is expanded recursively to Metal1-only
   foundry leaf cells. A nested cell like `Mux2` is replaced by its own `Inv` + `Nand2`
   instances, internal nets uniquified by an instance prefix and the sub-cell's ports
   rewired to the parent's nets. (This is why `MuxDff`, written as 2·`Mux2` + 5·`Inv`,
   routes as 13 leaf cells.)
2. **Order** (`order_cells_sa`) — cells are ordered to minimise wirelength by
   **simulated annealing**, seeded from an iterated-barycenter order. The cost is
   half-perimeter wirelength with the vertical span weighted 2× (a net that crosses rows
   is far harder to route than one that stays in a row). A fixed seed keeps it
   deterministic.
3. **Fold into rows** (`place_rows`) — the 1-D order is folded into N abutted rows. Odd
   rows are **mirrored (D4.MX) and reversed** (a boustrophedon / snake): mirroring makes
   adjacent rows share a vdd/vss rail (the standard flipped-row layout), and reversing
   keeps the dataflow adjacent across the turn. Pin rectangles are transformed to match.
4. **Grow rows on failure** — the row count starts near a square aspect ratio and is
   incremented until the router succeeds (the Metal3 spacing rule limits how many nets
   fit one channel).

### Routing — negotiated congestion

All signal nets are routed together by **rip-up-and-reroute** (`route_nets`),
negotiated-congestion maze routing:

* Each net is routed with **A\*** (`_astar`) on the three-layer grid: move along Metal2
  (vertical) or Metal3 (horizontal), or pay a via cost to switch layer. Multi-terminal
  nets grow a tree (connect terminal 1→2, then each remaining terminal to the tree).
  Metal2 may pass *through* a rail track to reach another row; vias and Metal3 are only
  allowed on signal tracks.
* After every net is routed, each **conflict** raises the cost of the offending grid
  nodes and *all* nets are ripped up and rerouted. Conflicts are: a node used by two
  nets, **or** two nets too close given the 210 nm wires + 150 nm end extensions —
  Metal3 on adjacent tracks (parallel runs) or one x-step apart on the same track
  (facing wire ends), Metal2 one y-step apart on the same track. The penalty accumulates
  as *historical* congestion, so nets that keep colliding are progressively pushed apart
  until the routing is legal. The net order is rotated each pass to stop two nets
  oscillating over one resource.

Because the spacing rules are encoded directly in the conflict model, a converged
routing is DRC-clean by construction rather than clean by luck.

### Geometry, and the DRC details that actually bite

Wires and via stacks are emitted through `ordec.layout.SRouter`. Three sg13g2 specifics
drove the parameters:

* **Pin access uses the LEF rectangles**, not GDS-polygon bounding boxes. Nor2's Y and B
  pins overlap *by bounding box*, so a bbox-driven via would short two nets; the clean
  per-pin LEF rects place the Via1 on exactly the intended pin, with an enclosure test
  (≥10 nm on all sides, ≥50 nm on one) so it is never on too narrow a finger.
* **Min area (0.144 µm²) and the via endcap (50 nm)** cannot be met by an isolated via
  landing at this pitch — the *wire* must carry them. So wires are 210 nm (enclose the
  190 nm cut by 10 nm) and extend 150 nm past each end (a 50 nm endcap at an end-via),
  and a post-pass (`_extend_min_area`) lengthens any too-short segment into free tracks
  to reach min area.
* **Metal3 spacing (210 nm)** is exactly one track pitch minus the wire width, which is
  the whole reason the adjacency conflicts and row-growth above exist.

### Algorithmic fidelity and scope

The algorithms are the real thing. Negotiated-congestion routing, A\* maze routing,
simulated-annealing placement and flipped-row floorplanning are the same foundational
techniques production place-and-route tools are built on, and here they run as a
complete, end-to-end flow that turns a schematic into real silicon geometry — DRC-clean
against the maximal sign-off rule set and LVS-matched to the source.

What separates it from a production flow is scale and scope, not correctness:

* **Scale** — it targets blocks of tens of cells, where production tools handle
  millions. At that scale modern placement is *analytical* (electrostatics/quadratic)
  rather than annealing, and routing is split into global routing (congestion
  estimation) + detailed routing instead of a single flat maze.
* **Timing** — production P&R is timing-driven (STA-guided placement, buffering,
  useful-skew clock-tree synthesis); this engine optimises wirelength and leaves timing
  closure to the designer.
* **Design rules** — it encodes the handful of rules that actually constrain this
  geometry (via enclosure, min area, M2/M3 spacing) directly into the router, so the
  result is correct by construction; full sign-off DRC is hundreds of rules
  (parallel-run-length tables, end-of-line, cut spacing, min-step, antenna…), for which
  the KLayout deck remains the authority.
* **Out of scope by design** — clock-tree synthesis, power planning beyond rail
  abutment, antenna fixing, fill, multi-Vt and deep (5–15 layer) routing.

The result is a compact but genuinely faithful flow: the right algorithms, applied end
to end, producing sign-off-clean layout for real foundry cells — with production scale
and the timing/sign-off machinery deliberately left out.
