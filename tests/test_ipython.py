# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.lib import Inv
from ordec import render

def test_repr_svg_symbol():
    repr_svg, repr_svg_meta = Inv().symbol._repr_svg_()
    render_svg = render(Inv().symbol).svg()
    assert repr_svg == render_svg.decode('ascii')

def test_repr_svg_schematic():
    repr_svg, repr_svg_meta = Inv().schematic._repr_svg_()
    render_svg = render(Inv().schematic).svg()
    assert repr_svg == render_svg.decode('ascii')
