# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Builds a Report from a SimHierarchy for display in the web UI.

For small simulations this provides a quick default view. For anything
"serious" where you want to control signal grouping, use the Report class
directly.
"""

import cmath
import math
import re

from public import public
from ..core import *
from ..report import Report, Plot2D, Markdown


def get_sim_data(sh: SimHierarchy, voltage_attr, current_attr, top_level_only=True):
    """Helper to extract voltage and current data for different simulation types."""
    voltages = {}
    for sn in sh.all(SimNet):
        if top_level_only and sn.parent_inst is not None:
            continue
        if (voltage_val := getattr(sn, voltage_attr, None)) is not None:
            voltages[sn.full_path_str()] = voltage_val
    currents = {}
    for si in sh.all(SimInstance):
        if top_level_only and si.parent_inst is not None:
            continue
        if (current_val := getattr(si, current_attr, None)) is not None:
            currents[si.full_path_str()] = current_val
    return voltages, currents


def _fmt_eng(val, unit):
    """Format a float in engineering notation with a unit suffix."""
    x = str(R(f"{val:.03e}")) + unit
    x = re.sub(r"([0-9])([a-zA-Z])", r"\1 \2", x)
    x = x.replace("u", "\u03bc")
    return x


@public
def webdata(sh: SimHierarchy):
    if sh.sim_type == SimType.TRAN:
        voltages, currents = get_sim_data(sh, 'trans_voltage', 'trans_current')
        x = tuple(sh.time)
        report = Report(fill_height=True)
        if voltages:
            report.add(Plot2D(
                x=x,
                series=[(k, tuple(v)) for k, v in voltages.items()],
                xlabel='Time (s)',
                ylabel='Voltage (V)',
                height=None,
                plot_group='sim',
            ))
        if currents:
            report.add(Plot2D(
                x=x,
                series=[(k, tuple(v)) for k, v in currents.items()],
                xlabel='Time (s)',
                ylabel='Current (A)',
                height=None,
                plot_group='sim',
            ))
        return report.webdata()

    elif sh.sim_type == SimType.AC:
        voltages, currents = get_sim_data(sh, 'ac_voltage', 'ac_current')
        x = tuple(sh.freq)
        all_signals = {}
        all_signals.update(voltages)
        all_signals.update(currents)

        report = Report(fill_height=True)
        if all_signals:
            mag_series = []
            phase_series = []
            for name, vals in all_signals.items():
                mag_series.append((
                    name,
                    [20 * math.log10(max(abs(v), 1e-300)) for v in vals],
                ))
                phase_series.append((
                    name,
                    [cmath.phase(v) * 180 / math.pi for v in vals],
                ))
            report.add(Plot2D(
                x=x,
                series=mag_series,
                xlabel='Frequency (Hz)',
                ylabel='Magnitude (dB)',
                xscale='log',
                height=None,
                plot_group='sim',
            ))
            report.add(Plot2D(
                x=x,
                series=phase_series,
                xlabel='Frequency (Hz)',
                ylabel='Phase (\u00b0)',
                xscale='log',
                height=None,
                plot_group='sim',
            ))
        return report.webdata()

    elif sh.sim_type == SimType.DCSWEEP:
        report = Report(fill_height=True)
        if sh.sim_data is None or sh.sweep_field is None:
            return report.webdata()
        voltages, currents = get_sim_data(sh, "dc_sweep_voltage", "dc_sweep_current")
        x = tuple(sh.sim_data.column(sh.sweep_field))
        sweep_name = sh.sweep_field
        if voltages:
            report.add(Plot2D(
                x=x,
                series=[(k, tuple(v)) for k, v in voltages.items()],
                xlabel=sweep_name,
                ylabel='Voltage (V)',
                height=None,
                plot_group='sim',
            ))
        if currents:
            report.add(Plot2D(
                x=x,
                series=[(k, tuple(v)) for k, v in currents.items()],
                xlabel=sweep_name,
                ylabel='Current (A)',
                height=None,
                plot_group='sim',
            ))
        return report.webdata()

    elif sh.sim_type == SimType.DC:
        report = Report(fill_height=False)

        dc_voltages = []
        for sn in sh.all(SimNet):
            if sn.dc_voltage is None:
                continue
            dc_voltages.append(
                f"| {sn.full_path_str()} | {_fmt_eng(sn.dc_voltage, 'V')} |"
            )
        if dc_voltages:
            lines = ["| Net | Voltage |", "| --- | --- |"] + dc_voltages
            report.add(Markdown("\n".join(lines)))

        dc_currents = []
        for si in sh.all(SimInstance):
            if si.dc_current is None:
                continue
            dc_currents.append(
                f"| {si.full_path_str()} | {_fmt_eng(si.dc_current, 'A')} |"
            )
        if dc_currents:
            lines = ["| Branch | Current |", "| --- | --- |"] + dc_currents
            report.add(Markdown("\n".join(lines)))

        return report.webdata()

    else:
        return 'nosim', {}
