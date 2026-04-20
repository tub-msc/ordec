# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.lib.generic_mos import Inv

def test_repr_svg_symbol():
    sym = Inv().symbol
    repr_svg, repr_svg_meta = sym._repr_svg_()
    render_svg = sym.render().svg()
    assert repr_svg == render_svg.decode('ascii')

def test_repr_svg_schematic():
    sch = Inv().schematic
    repr_svg, repr_svg_meta = sch._repr_svg_()
    render_svg = sch.render().svg()
    assert repr_svg == render_svg.decode('ascii')
