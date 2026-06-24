# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the SAR ADC example (ordec/examples/sar_adc).

Covers elaboration of every cell, closed-loop conversion correctness against the
IHP SG13G2 models, the digital SAR controller in isolation, and DRC/LVS of the
inverter standard-cell layout.
"""

import pytest
import ordec.importer
from ordec.core import *
from ordec.lib import ihp130
from ordec.examples.sar_adc import (
    tgate, comparator, cdac, sar_logic, sar_adc, tb)
from ordec.examples.sar_adc.stdcell_lib import extlib


def _bit(v):
    return 1 if v > 0.6 else 0


def _read_code(sim, n, t_read):
    times = list(sim.time)
    idx = min(range(len(times)), key=lambda k: abs(times[k] - t_read))
    return sum(_bit(list(sim.code[i].voltage)[idx]) << i for i in range(n))


def test_stdcells_elaborate():
    # Logic cells come from the foundry library (LEF symbol + GDS layout + SPICE
    # schematic); the transmission gate is the one hand-crafted custom cell.
    for name in ['sg13g2_inv_1', 'sg13g2_nand2_1', 'sg13g2_nor2_1',
                 'sg13g2_mux2_1', 'sg13g2_or2_1', 'sg13g2_dfrbp_1']:
        extlib[name].schematic
    tgate.Tgate().schematic


def test_subblocks_elaborate():
    comparator.Comparator().schematic
    cdac.CapDac().schematic
    sar_logic.SarLogic().schematic
    sar_adc.SarAdc().schematic
    # netlist the top-level to make sure every pin is connected
    SimHierarchy.from_schematic(sar_adc.SarAdc().schematic)


@pytest.mark.parametrize("code", [0, 3, 5, 7])
def test_sar_adc_conversion_3bit(code):
    """A mid-bin input must convert to the expected 3-bit code."""
    vin = (code + 0.5) / 8 * 1.2
    sim = tb.SarAdcConvTb(n=3, vin_val=round(vin, 4)).sim_tran
    assert _read_code(sim, 3, 270e-9) == code


@pytest.mark.parametrize("code", [5, 10])
def test_sar_adc_conversion_4bit(code):
    """The design is parameterizable: check a couple of 4-bit conversions."""
    vin = (code + 0.5) / 16 * 1.2
    sim = tb.SarAdcConvTb(n=4, vin_val=round(vin, 4)).sim_tran
    assert _read_code(sim, 4, 270e-9) == code


def test_sar_logic_sequencing():
    """The controller must register the comparator pattern (MSB-first 1,0,1,1)
    as code 11 at the default n=4."""
    sim = tb.SarLogicTb().sim_tran
    assert _read_code(sim, 4, 120e-9) == 11


def test_comparator_resolves():
    """Continuous-time comparator switches as in_p crosses in_n (=0.6 V)."""
    sim = tb.CompTb().sim_tran
    out = list(sim.out.voltage)
    inp = list(sim.in_p.voltage)
    lo = [out[k] for k in range(len(out)) if inp[k] < 0.55]
    hi = [out[k] for k in range(len(out)) if inp[k] > 0.65]
    assert max(lo) < 0.6 and min(hi) > 0.6


# The transmission gate is the one cell with a hand-crafted layout (the foundry
# library has no Tgate macro); the logic cells use the foundry GDS directly.
LAID_OUT_CELLS = ["Tgate"]


@pytest.mark.parametrize("cellname", LAID_OUT_CELLS)
def test_stdcell_layout_drc_clean(cellname):
    cell = getattr(tgate, cellname)()
    assert ihp130.run_drc(cell.layout, use_tempdir=True).summary() == {}


@pytest.mark.parametrize("cellname", LAID_OUT_CELLS)
def test_stdcell_layout_lvs_clean(cellname):
    cell = getattr(tgate, cellname)()
    assert ihp130.run_lvs(cell.layout, cell.symbol, use_tempdir=True)


def test_comparator_layout_drc_clean():
    """The custom analog comparator (single-stage OTA + self-bias + two foundry
    inverter buffers, routed by SRouter) is DRC-clean."""
    assert ihp130.run_drc(comparator.Comparator().layout, use_tempdir=True).summary() == {}


def test_comparator_layout_lvs_clean():
    c = comparator.Comparator()
    assert ihp130.run_lvs(c.layout, c.symbol, use_tempdir=True)


def test_cdac_layout_drc_clean():
    """The capacitive DAC (MIM caps + transmission-gate switches, hand-placed
    with Metal5 bottom-plate and TopMetal1 top-plate routing) is DRC-clean."""
    assert ihp130.run_drc(cdac.CapDac().layout, use_tempdir=True).summary() == {}


def test_cdac_layout_lvs_clean():
    c = cdac.CapDac()
    assert ihp130.run_lvs(c.layout, c.symbol, use_tempdir=True)


def test_sar_logic_layout_drc_clean():
    """The digital control block (foundry leaf cells placed + routed by the gridded
    P&R engine, pnr.py) is DRC-clean."""
    assert ihp130.run_drc(sar_logic.SarLogic().layout, use_tempdir=True).summary() == {}


def test_sar_logic_layout_lvs_clean():
    c = sar_logic.SarLogic()
    assert ihp130.run_lvs(c.layout, c.symbol, use_tempdir=True)


def test_sar_adc_layout_drc_clean():
    """The full SAR ADC top level (CapDac + Comparator + SarLogic + inverter
    placed and routed together) is DRC-clean."""
    assert ihp130.run_drc(sar_adc.SarAdc().layout, use_tempdir=True).summary() == {}


def test_sar_adc_layout_lvs_clean():
    """The full SAR ADC top-level layout matches its schematic (every block and
    the top-level netlist). Each block exposes its ports on its edge (signals on
    Metal4, supplies on the power-ring straps), so the parent routes only in the
    channels -- the property that keeps this robust to placement changes."""
    c = sar_adc.SarAdc()
    assert ihp130.run_lvs(c.layout, c.symbol, use_tempdir=True)
