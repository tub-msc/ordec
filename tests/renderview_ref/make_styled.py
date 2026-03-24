#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0
"""Insert schematic CSS into reference SVGs for visual inspection.

The reference SVGs are stored without CSS so that style changes don't
cause bulk diffs.  Run this script to produce styled/ copies that can
be opened in a browser.
"""
import re
from pathlib import Path

from ordec.render import SchematicRenderer


def main():
    here = Path(__file__).parent
    style_tag = f'<style type="text/css">{SchematicRenderer.css}</style>'

    styled_dir = here / "styled"
    styled_dir.mkdir(exist_ok=True)

    count = 0
    for svg_path in sorted(here.glob("*.svg")):
        svg = svg_path.read_text()
        # Insert <style> as first child of <svg>
        svg = re.sub(r"(<svg[^>]*>)", rf"\1\n  {style_tag}", svg, count=1)
        (styled_dir / svg_path.name).write_text(svg)
        count += 1

    print(f"Wrote {count} styled SVGs to {styled_dir}")


if __name__ == "__main__":
    main()
