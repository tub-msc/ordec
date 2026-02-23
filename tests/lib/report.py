# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import math
from ordec.report import *
from ordec.core import R, generate_func
from .sim import ResdivHier2

@generate_func
def report_example() -> Report:
    resdiv = ResdivHier2(r=R(100))
    freq = 1e6
    num_points = 100
    dt = 20e-9
    time = [i * dt for i in range(num_points)]
    vin = [math.sin(2 * math.pi * freq * t) for t in time]
    vout = [0.7 * math.sin(2 * math.pi * freq * t - 0.45) for t in time]
    verr = [a - b for a, b in zip(vin, vout)]
    ac_freq = [10 ** (2 + i * (6 / 79)) for i in range(80)]
    ac_mag = [-20 * math.log10(1 + (f / 2e5)) for f in ac_freq]
    ac_phase = [-math.degrees(math.atan(f / 2e5)) for f in ac_freq]
    return Report([
        Markdown(
            "# Report Example\n"
            "Rendered in Python with **bold** text and `inline code`."
        ),
        PreformattedText("alpha\nbeta\ngamma"),
        Plot2D(
            x=time,
            series={
                "v(in)": vin,
                "v(out)": vout,
            },
            xlabel="Time (s)",
            ylabel="Voltage (V)",
            height=220,
            plot_group="tran_demo",
        ),
        Plot2D(
            x=time,
            series={"v(err)": verr},
            xlabel="Time (s)",
            ylabel="Voltage (V)",
            height=100,
            plot_group="tran_demo",
        ),
        Plot2D(
            x=ac_freq,
            series={"|v(out)| (dB)": ac_mag},
            xlabel="Frequency (Hz)",
            ylabel="Magnitude (dB)",
            xscale="log",
            height=220,
            plot_group="ac_demo",
        ),
        Plot2D(
            x=ac_freq,
            series={"phase(v(out))": ac_phase},
            xlabel="Frequency (Hz)",
            ylabel="Phase (deg)",
            xscale="log",
            height=120,
            plot_group="ac_demo",
        ),
        Svg.from_view(resdiv.symbol),
        Svg.from_view(resdiv.schematic),
        ])
