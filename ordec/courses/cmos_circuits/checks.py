# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Lesson checks for the 'cmos_circuits' course (under construction).
"""

from ordec.core import *


def gen_lesson1(g):
    @generate_func
    def lesson() -> Report:
        report = Report()
        report.markdown(
            "## Coming soon\n\n"
            "This course is under construction."
        )
        return report
    return lesson
