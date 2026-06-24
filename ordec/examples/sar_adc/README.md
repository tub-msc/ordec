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
  engine (`ordec.layout.pnr`): the schematic is flattened to foundry leaf cells, ordered into
  abutted flipped rows by simulated annealing, then wired by a negotiated-congestion
  maze router (A\*, Metal2 vertical / Metal3 horizontal, Via1 pin access,
  rip-up-and-reroute until DRC-clean). The engine is documented in detail in the ORDeC
  reference, [*Gridded standard-cell place and route*](../../../docs/ref/pnr.rst).
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
side power-ring straps (the `ordec.layout.pnr` edge-escape pass), `CapDac`'s on its bottom edge —
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
