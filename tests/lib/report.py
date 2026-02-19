# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec import *
from .sim import ResdivHier2

@generate_func
def report_example() -> Report:
    resdiv = ResdivHier2(r=R(100))
    return Report([
        Markdown(
            "# Report Example\n"
            "Rendered in Python with **bold** text and `inline code`."
        ),
        PreformattedText("alpha\nbeta\ngamma"),
        Svg.from_view(resdiv.symbol),
        Svg.from_view(resdiv.schematic),
        ])
