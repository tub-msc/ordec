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
`n`, verified at the default **8 bits** (exact conversions, 1 LSB = 4.7 mV) and at
3 and 4 bits. The reference voltage is `Vref = VDD = 1.2 V` and the common mode is
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
* **Comparator** (`comparator.ord`) — **two cascaded differential stages**: a
  self-biased NMOS pair with PMOS current-mirror load, then a PMOS pair reading both
  first-stage outputs (the diode node serves as the balance reference, so the first
  stage's anchor error cancels as common mode) with an NMOS mirror load, then two
  inverter output buffers. It is continuous-time rather than clocked, so there is no
  strobe edge to align with DAC settling — which is what makes the closed loop easy to
  bring up. The two-stage structure exists for offset: a single stage driving an
  inverter trips several mV from balance (measured −6.8 mV, >1 LSB at 8 bits), and at
  VDD = 1.2 V the squeezed input devices cap the per-stage gain at ~20, so the fix has
  to be structural rather than "more gain". Measured input offset **+0.26 mV**
  (delay-cancelled two-direction ramp), ~0.06 LSB at 8 bits.
* **SarLogic** (`sar_logic.ord`) — a shift-register sequencer carries a one-hot token
  (sample → MSB → … → LSB → done); per-bit load-enable registers capture the comparator
  decision at the right clock, with `dac[k] = code[k] OR on_trial[k]`. The MSB's trial
  term comes from a dedicated **glitch-free phase flop** that is high from reset through
  the end of the MSB trial: an OR of `sample` and the trial token would glitch low for
  ~1 ns at the sample→trial edge, passing the DAC through all-zeros right as the bottom
  plates connect — enough to fling the sampled top plate into the substrate diode for
  near-full-scale inputs.
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
* **Conversion** — at 8 bits, mid-bin inputs convert to the **exact** expected codes
  including the range extremes 0 and 255 (the hardest cases: they exercise the
  handoff-glitch and redistribution-clamp mechanisms described above); at 3 bits the
  full transfer function is checked (all eight mid-bin inputs map to codes 0…7); 4-bit
  spot checks cover the intermediate resolution.
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
  engine (`ordec.layout.pnr`): the schematic is flattened to foundry leaf cells, ordered into
  abutted flipped rows by simulated annealing, then wired by a negotiated-congestion
  maze router (A\*, Metal2 vertical / Metal3 horizontal, Via1 pin access,
  rip-up-and-reroute until DRC-clean). The engine is documented in detail in the ORDeC
  reference, [*Gridded standard-cell place and route*](../../../docs/ref/pnr.rst).
* **`Comparator`** — a hand-crafted **analog** layout (`comparator.ord`): the
  first-stage core is built from constrained device PCells at **l = 1 µm** (8 µm² of
  gate area per input side keeps random offset to a fraction of an LSB), with the
  matched devices **interdigitated A-B-B-A** — each side of the differential pair (and
  of the current-mirror load) is two parallel one-finger halves, drains facing out
  (`n1`, joined by a Metal2 crossover) and in (`n2`), so a lateral gradient cancels to
  first order — and **dummy devices flank both bands** so the outer fingers see the
  same etch neighborhood as inner ones. The fingered tail sink and two self-bias
  columns (the second generates the `pbias` tail bias) sit below/left; the second
  stage sits to the right, its PMOS pair, tail and NMOS mirror built from the same
  2 µm fingers so they share the core's two device bands; everything PMOS in one
  shared n-well. The two output-buffer inverters are placed as foundry `Inv`
  instances and wired in with `ordec.layout.SRouter`.
* **`CapDac`** — a hand layout (`cdac.ord`) of the capacitor array and its
  transmission-gate switches. Each bit is a *matched array of identical unit capacitors*
  (bit `i` = `2**i` `m=1` units — the `Cmim` PCell supports only `m=1`), so the binary
  weights track as an exact device-count ratio rather than by scaling one capacitor's
  dimensions; this is what keeps INL/DNL accurate across process gradients. The `2**n`
  units form a **common-centroid 2-D array** (near-square, scales to 8 bits and beyond):
  units are assigned to bits in point-symmetric pairs about the array centre — every
  bit's centroid coincides with the centre, so a linear process gradient cancels
  exactly — with the pairs dealt radially interleaved so each bit also samples all
  radii. Each unit taps its bit's vertical Metal4 *bit line* (running under the caps;
  the MIM rules allow it) with a single Via4; the lines collect on per-net Metal3 buses
  below the array, which the switch row reaches with Metal2 risers. A **ring of dummy
  units** surrounds the array, so every functional unit sees interior lithography
  (edge units would otherwise mismatch systematically) — and it doubles as a
  **vx-to-vss shunt capacitor** (~26% of the array at n = 8): its bottom plates stay
  on `vss` while its top plates join the `vx` mesh. The shunt damps the
  sample→convert redistribution transient, whose ~2× overshoot (the small bits'
  switches slew rail-to-rail in a fraction of the MSB switch's RC) would otherwise
  clamp the floating top plate at the substrate diode near the input-range ends and
  corrupt the sampled charge; being a pure attenuator around the `vcm` crossing, it
  leaves the decision points untouched and only shrinks the per-trial overdrive
  (4.7 → 3.7 mV per LSB at n = 8, still ~14× the comparator offset). A TopMetal1
  *mesh* (per-column bridges plus a spine, rather than one solid plate, extending one
  row past the array to pick up the ring) ties all top plates to `vx` — keeping the
  metal/gate antenna ratio at the comparator input legal at n ≥ 8 — and the digital
  control and supply nets run on Metal3 buses over the switch row.
  A split/bridge-cap (segmented) DAC was considered and deliberately **not** used: at
  8 bits the plain binary array is small (~0.1 mm on a side would be needed only past
  10 bits), the fractional bridge capacitor would break the exact unit-count matching
  that is this DAC's strongest property — segmentation would buy area the design
  doesn't need at the cost of a linearity hazard it can't afford.

### Top-level composition (`SarAdc`)

The top level (`sar_adc.ord`) places the four sub-blocks (`CapDac`, `Comparator`,
`SarLogic`, sample inverter) and routes the inter-block nets on Metal4 trunks and Metal5
columns. The composition stays robust because **each block exposes its ports on its
edge** — `SarLogic`'s signals on Metal4 pads above its top rail and its supplies on the
side power-ring straps (the `ordec.layout.pnr` edge-escape pass), `CapDac`'s on its bottom edge —
so the parent only ever routes in the channels between blocks and never crosses a block
interior. A placement change therefore cannot create a new over-cell short. The
floorplan is **computed from the blocks' bounding boxes** rather than hand-placed, so it
re-derives itself whenever the resolution changes.

Several analog-specific touches go beyond simply passing DRC/LVS:

* the critical **`vx` net** (DAC top plate → comparator input) is routed as a short,
  direct Metal4 wire, with the comparator aligned to it, instead of detouring down
  through the trunk band and back — the wire crosses the comparator at its gate-tie
  row, a quiet corridor where only the input poly bars, tail devices and vss geometry
  sit under it (the output buffers and all switching Metal2 lanes lie several µm
  above that row);
* the **trunk band is ordered by sensitivity**: `vcm` (the analog reference) takes the
  trunk nearest the analog blocks, the supply pair follows as a shield, and the
  full-swing digital nets sit below, nearest `SarLogic` — no digital trunk neighbors an
  analog one;
* the **positive supply is split** into `vdda` (comparator, CDAC, sample inverter) and
  `vddd` (`SarLogic`), each with its own trunk/pin, so digital switching currents stay
  off the analog rail. The ground is deliberately one net: SG13G2 has no triple well,
  so every p-tap contacts the single substrate and separately-named grounds would be
  shorted through it anyway (the LVS deck rightly flags them); and
* a **`vss`-tied substrate guard bar** sits in the gap between the digital `SarLogic`
  and the analog blocks, collecting substrate noise before it reaches the comparator and
  CDAC.
