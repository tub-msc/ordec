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


def get_voltages(sh: SimHierarchy, top_level_only=False):
    """Extract voltage data from SimNet nodes."""
    voltages = {}
    for sn in sh.all(SimNet):
        if top_level_only and sn.parent_inst is not None:
            continue
        v = sn.voltage
        if v is not None:
            voltages[sn.full_path_str()] = v
    return voltages


def get_currents(sh: SimHierarchy, top_level_only=False):
    """Extract current data from SimPin nodes."""
    currents = {}
    for sp in sh.all(SimPin):
        if top_level_only and sp.instance.parent_inst is not None:
            continue
        c = sp.current
        if c is not None:
            inst_path = sp.instance.full_path_str()
            pin_name = sp.eref.full_path_str()
            currents[f"{inst_path}.{pin_name}"] = c
    return currents


def _fmt_eng(val, unit):
    """Format a float in engineering notation with a unit suffix."""
    x = str(R(f"{val:.03e}")) + unit
    x = re.sub(r"([0-9])([a-zA-Z])", r"\1 \2", x)
    x = x.replace("u", "\u03bc")
    return x


@public
def webdata(sh: SimHierarchy):
    if sh.sim_type == SimType.TRAN:
        voltages = get_voltages(sh)
        currents = get_currents(sh)
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
        voltages = get_voltages(sh)
        currents = get_currents(sh)
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
        voltages = get_voltages(sh)
        currents = get_currents(sh)
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

        op_voltages = []
        for sn in sh.all(SimNet):
            if sn.op_voltage is None:
                continue
            op_voltages.append(
                f"| {sn.full_path_str()} | {_fmt_eng(sn.op_voltage, 'V')} |"
            )
        if op_voltages:
            lines = ["| Net | Voltage |", "| --- | --- |"] + op_voltages
            report.add(Markdown("\n".join(lines)))

        op_currents = []
        for sp in sh.all(SimPin):
            if sp.op_current is None:
                continue
            inst_path = sp.instance.full_path_str()
            pin_name = sp.eref.full_path_str()
            op_currents.append(
                f"| {inst_path}.{pin_name} | {_fmt_eng(sp.op_current, 'A')} |"
            )
        if op_currents:
            lines = ["| Branch | Current |", "| --- | --- |"] + op_currents
            report.add(Markdown("\n".join(lines)))

        # Device parameters (gm, gds, vth, etc.)
        param_rows = {}
        for sp in sh.all(SimParam):
            if sp.op_value is None:
                continue
            inst_path = sp.instance.full_path_str()
            param_rows.setdefault(inst_path, {})[sp.name] = sp.op_value
        if param_rows:
            _REGION_NAMES = {0: "cutoff", 1: "triode", 2: "sat", 3: "subVt"}
            all_params = sorted({
                n for vals in param_rows.values() for n in vals})
            header = "| Instance | " + " | ".join(all_params) + " |"
            sep = "| --- | " + " | ".join("---" for _ in all_params) + " |"
            rows = [header, sep]
            for inst_path in sorted(param_rows):
                vals = param_rows[inst_path]
                cells = []
                for p in all_params:
                    v = vals.get(p)
                    if v is None:
                        cells.append("\u2014")
                    elif p == "region":
                        cells.append(_REGION_NAMES.get(int(v), str(v)))
                    else:
                        cells.append(_fmt_eng(v, ""))
                cells_str = " | ".join(cells)
                rows.append(f"| {inst_path} | {cells_str} |")
            report.add(Markdown("\n".join(rows)))

        return report.webdata()

    else:
        return Report([Markdown("No simulation was run.")]).webdata()
