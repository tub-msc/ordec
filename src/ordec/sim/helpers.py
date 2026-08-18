# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""Helpers for turning AC simulation results into Bode-style reports."""

import cmath
import math

from ..core.schema import PlotGroup, SimNet, SimPin
from ..core.simarray import Quantity, SimColumn, SimSeries


def mag_db(series, floor=1e-300):
    """
    Magnitude of a complex response in dB (20*log10(|v|)), as a new
    SimSeries sharing the input's scale columns (axis-preserving).
    Magnitudes are clamped to floor so that exact zeros stay
    representable on the dB scale.
    """
    return series.map(
        lambda v: 20 * math.log10(max(abs(v), floor)),
        quantity=Quantity.DECIBEL)


def phase_deg(series, unwrap=True):
    """
    Phase of a complex response in degrees, as a new SimSeries sharing
    the input's scale columns (axis-preserving). The result carries no
    Quantity: phase units are ambiguous in ngspice's type system.

    With unwrap, multiples of 360° are added wherever the raw phase jumps
    by more than 180° between adjacent points, giving continuous curves.
    """
    ph = [math.degrees(cmath.phase(v)) for v in series.values]
    if unwrap:
        for i in range(1, len(ph)):
            while ph[i] - ph[i - 1] > 180:
                ph[i] -= 360
            while ph[i] - ph[i - 1] < -180:
                ph[i] += 360
    return SimSeries(SimColumn.from_values(ph), series.scales)


def _resolve_signal(signal):
    """Returns (name, SimSeries) for a SimNet or SimPin cursor."""
    if isinstance(signal, SimNet):
        name = signal.full_path_str()
        values = signal.voltage
    elif isinstance(signal, SimPin):
        name = signal.full_path_str()
        values = signal.current
    else:
        raise TypeError(
            f"Expected SimNet or SimPin cursor, got {signal!r}")
    if values is None:
        raise ValueError(f"Signal {name!r} has no simulation data")
    return name, values


def bode_plot(report, *signals, ref=None, height=300, unwrap=True):
    """
    Append a magnitude(dB)/phase(°) plot pair with a synchronized
    logarithmic frequency axis to a report.

    Args:
        report: Report to append to. In ORD viewgen bodies, pass the bare
            dot `.` (the view root).
        signals: SimNet or SimPin cursors from a single AC SimHierarchy.
            Nets plot their voltage, pins their pin current.
        ref: optional SimNet/SimPin cursor to divide every signal by, e.g.
            ref=sim.vin to plot transfer functions relative to vin.
        height: per-plot height in pixels, or None to fill the available
            height.
        unwrap: unwrap phase jumps exceeding 180° (see phase_deg).

    Returns:
        The (magnitude, phase) pair of Plot2D cursors.
    """
    if not signals:
        raise ValueError("bode_plot() requires at least one signal")
    named = [_resolve_signal(s) for s in signals]
    sim = signals[0].root
    others = signals[1:] if ref is None else (*signals[1:], ref)
    for s in others:
        if s.root != sim:
            raise ValueError(
                "All signals must come from the same SimHierarchy")
    if sim.freq is None:
        raise ValueError("SimHierarchy contains no AC results")

    if ref is not None:
        _, ref_series = _resolve_signal(ref)
        # The same-root check above guarantees a shared frequency axis;
        # the divided series keep each signal's scale columns.
        named = [
            (name, SimSeries(
                SimColumn.from_values(
                    [v / r for v, r in zip(sig, ref_series)]),
                sig.scales))
            for name, sig in named
        ]

    grp = report % PlotGroup()
    mag = report.plot2d(
        *[(name, mag_db(sig)) for name, sig in named],
        ylabel="Magnitude (dB)",
        xscale='log',
        height=height,
        group=grp,
    )
    phase = report.plot2d(
        *[(name, phase_deg(sig, unwrap)) for name, sig in named],
        ylabel="Phase (°)",
        xscale='log',
        height=height,
        group=grp,
    )
    return mag, phase
