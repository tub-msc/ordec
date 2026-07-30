# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Builds a Report from a SimHierarchy for display in the web UI.

For small simulations this provides a quick default view. For anything
"serious" where you want to control signal grouping, use the Report class
directly.
"""

import re

from public import public
from ..core import *
from ..core.schema import PlotGroup, Report
from .helpers import bode_plot


def _fmt_eng(val, unit):
    """Format a float in engineering notation with a unit suffix."""
    x = str(R(f"{val:.03e}"))
    # str(R) keeps a trailing decimal point when the fractional part is
    # zero (e.g. "5.", "0."); drop it so values do not render as "5.V".
    x = re.sub(r"\.(?=[a-zA-Z]|$)", "", x) + unit
    x = re.sub(r"([0-9])([a-zA-Z])", r"\1 \2", x)
    # U+00B5 MICRO SIGN, not Greek mu: Inconsolata (which renders these
    # values in the web UI) only covers the compatibility codepoint.
    # Must run before the <sup> rewrite below ("sup" contains a "u").
    x = x.replace("u", "\u00b5")
    # Exponents beyond the SI suffix range (|exp| > 18) stay in
    # e-notation; typeset them as "U+00D7 MULTIPLICATION SIGN, 10" with a
    # real superscript: "-16.92 e-21 A" -> "-16.92(x)10<sup>-21</sup> A"
    # (markdown passes inline HTML through). The leading space was
    # inserted by the digit-letter rule above and is consumed here.
    x = re.sub(r" e(-?\d+)", "\u00d710<sup>\\1</sup>", x)
    return x


def _plot_signals(sh: SimHierarchy, x, xlabel):
    """Build a Report plotting net voltages and pin currents over a shared x-axis."""
    # plot2d derives series names from the nodes and infers the
    # Voltage (V) / Current (A) ylabels from the node types.
    nets = [sn for sn in sh.all(SimNet) if sn.voltage is not None]
    pins = [sp for sp in sh.all(SimPin) if sp.current is not None]
    report = Report(fill_height=True)
    if nets or pins:
        report.sim = PlotGroup()
    if nets:
        report.plot2d(x, *nets, xlabel=xlabel, height=None, group=report.sim)
    if pins:
        report.plot2d(x, *pins, xlabel=xlabel, height=None, group=report.sim)
    return report.webdata_static()


def webdata_tran(sh: SimHierarchy):
    return _plot_signals(sh, tuple(sh.time), 'Time (s)')


def webdata_dcsweep(sh: SimHierarchy):
    if sh.sim_data is None or sh.sweep_field is None:
        return Report(fill_height=True).webdata_static()
    return _plot_signals(sh, tuple(sh.sim_data.column(sh.sweep_field)), sh.sweep_field)


def webdata_ac(sh: SimHierarchy):
    signals = [sn for sn in sh.all(SimNet) if sn.voltage is not None]
    signals += [sp for sp in sh.all(SimPin) if sp.current is not None]
    report = Report(fill_height=True)
    if signals:
        bode_plot(report, *signals, height=None)
    return report.webdata_static()


def webdata_op(sh: SimHierarchy):
    report = Report(fill_height=False)

    op_voltages = []
    for sn in sh.all(SimNet):
        v = sn.voltage
        if v is None:
            continue
        op_voltages.append(
            f"| {sn.full_path_str()} | {_fmt_eng(v[0], 'V')} |"
        )
    if op_voltages:
        lines = ["| Net | Voltage |", "| --- | ---: |"] + op_voltages
        report.markdown("\n".join(lines))

    op_currents = []
    for sp in sh.all(SimPin):
        c = sp.current
        if c is None:
            continue
        inst_path = sp.instance.full_path_str()
        pin_name = sp.eref.full_path_str()
        op_currents.append(
            f"| {inst_path}.{pin_name} | {_fmt_eng(c[0], 'A')} |"
        )
    if op_currents:
        lines = ["| Branch | Current |", "| --- | ---: |"] + op_currents
        report.markdown("\n".join(lines))

    # Device parameters (gm, gds, vth, etc.)
    param_rows = {}
    for sp in sh.all(SimParam):
        val = sp.value
        if val is None:
            continue
        inst_path = sp.instance.full_path_str()
        param_rows.setdefault(inst_path, {})[sp.name] = val[0]
    if param_rows:
        _REGION_NAMES = {0: "cutoff", 1: "triode", 2: "sat", 3: "subVt"}
        all_params = sorted({
            n for vals in param_rows.values() for n in vals})
        header = "| Instance | " + " | ".join(all_params) + " |"
        # Value columns are right-aligned; the web frontend renders
        # right-aligned cells in monospace so magnitudes line up.
        sep = "| --- | " + " | ".join("---:" for _ in all_params) + " |"
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
        report.markdown("\n".join(rows))

    return report.webdata_static()


def webdata_nosim(sh: SimHierarchy):
    report = Report()
    report.markdown("No simulation was run.")
    return report.webdata_static()


@public
def webdata(sh: SimHierarchy):
    dispatch = {
        None: webdata_nosim,
        SimType.OP: webdata_op,
        SimType.TRAN: webdata_tran,
        SimType.AC: webdata_ac,
        SimType.DCSWEEP: webdata_dcsweep,
    }
    try:
        handler = dispatch[sh.sim_type]
    except KeyError:
        raise ValueError(
            f"webdata: unsupported sim_type {sh.sim_type!r}"
        ) from None
    return handler(sh)
