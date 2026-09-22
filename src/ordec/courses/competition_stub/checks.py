# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Checks of the competition stub course: a competition course without any
simulation, so that the scoreboard flow (team dialog, score pushes, final
ranking) can be tested in seconds instead of minutes of ngspice corner runs
(see tests/test_web.py). The course is not linked from the landing page.
"""

from ordec.core import *
from ordec.lib import Res

from ..common import exception_text


def gen_divider(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            # Competition Stub

            Build a resistor divider inside `Divider` (EDIT HERE marker):
            at least two `Res` instances and nothing else. Score = total
            resistance in kΩ, **lowest wins**. No simulation is run; this
            course exists to test the scoreboard.
        """)
        hint = "Add two Res instances at the EDIT HERE marker, e.g. `Res r1: .$r=1k; .p -- vdd; .n -- vout; .pos=(5,8)`."
        try:
            instances = list(g['Divider']().schematic.all(SchemInstance))
        except Exception:
            report.passfail("At least two resistors in Divider", False,
                instructions=exception_text(), hint=hint)
            report.passfail("Only resistors in Divider", False,
                instructions=exception_text(), hint=hint)
            return report
        resistors = [inst for inst in instances if isinstance(inst.symbol.cell, Res)]
        others = [inst for inst in instances if not isinstance(inst.symbol.cell, Res)]
        report.passfail("At least two resistors in Divider", len(resistors) >= 2,
            instructions=f"Found {len(resistors)} Res instance(s).", hint=hint)
        report.passfail("Only resistors in Divider", not others,
            instructions="Not allowed: " + ", ".join(
                type(inst.symbol.cell).__name__ for inst in others) + ".",
            hint=hint)
        eligible = all(e.passed for e in report.elements() if isinstance(e, PassFail))
        report.score("Score (total resistance)",
            sum(float(inst.symbol.cell.r) for inst in resistors) / 1e3,
            unit="kΩ", eligible=eligible)
        # The schematic goes to the scoreboard with the score, like in
        # amp_competition.
        report.markdown("Your schematic, as pushed with the score:")
        report.svg(g['Divider']().schematic)
        return report
    return lesson
