# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from ordec.core import *
import ordec.layout
from ordec.core.constraints import Variable, LinearTerm

def test_constraints_equalities():
    layers = ordec.layout.SG13G2().layers
    l = Layout(ref_layers=layers)

    l.activ = LayoutRect(layer=layers.Activ)
    l.poly = LayoutRect(layer=layers.GatPoly)

    s = Solver(l)

    s.constrain(l.activ.rect.width == 500)
    s.constrain(l.activ.rect.height == 150)
    s.constrain(l.activ.rect.lx == 100)
    s.constrain(l.activ.rect.ly == -100)

    s.constrain(l.activ.rect.cx == l.poly.rect.cx) # align x centers
    s.constrain(l.activ.rect.cy == l.poly.rect.cy) # align y centers
    s.constrain(l.poly.rect.height == 300)
    s.constrain(l.poly.rect.width == 100)

    s.solve()

    assert l.activ.rect == Rect4I(lx=100, ly=-100, ux=600, uy=50)
    assert l.poly.rect == Rect4I(lx=300, ly=-175, ux=400, uy=125)

def test_constraints_no_solution():
    layers = ordec.layout.SG13G2().layers
    l = Layout(ref_layers=layers)

    l.activ = LayoutRect(layer=layers.Activ)

    s = Solver(l)

    s.constrain(l.activ.rect.width == 500)
    s.constrain(l.activ.rect.height == 150)
    s.constrain(l.activ.rect.lx == 100)
    s.constrain(l.activ.rect.ly == -100)
    s.constrain(l.activ.rect.ux == 900) # conflicting with lx == 100 and width = 500

    with pytest.raises(SolverError):
        s.solve()
