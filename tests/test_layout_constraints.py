# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from ordec.core import *
from ordec.lib.ihp130 import SG13G2
from ordec.core.constraints import Variable, LinearTerm, Constraint

def test_equalities():
    layers = SG13G2().layers
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

def test_inequalities():
    layers = SG13G2().layers
    l = Layout(ref_layers=layers) 
 
    l.r1 = LayoutRect(layer=layers.Metal1)
    l.r2 = LayoutRect(layer=layers.Metal1)

    s = Solver(l)
    s.constrain(l.r1.rect.height >= 500)
    s.constrain(l.r1.rect.width >= 150)
    s.constrain(l.r1.rect.southwest == (100, -100))

    s.constrain(l.r2.rect.lx >= l.r1.rect.ux + 150)
    s.constrain(l.r2.rect.width == -l.r1.rect.height + 800)
    s.constrain(l.r2.rect.width <= 150) # Adjust this factor & see what happens.

    s.constrain(l.r2.rect.height == 150)
    s.constrain(l.r2.rect.cy == l.r1.rect.cy)

    s.solve()

    assert l.r1.rect == Rect4I(lx=100, ly=-100, ux=250, uy=550)
    assert l.r2.rect == Rect4I(lx=400, ly=150, ux=550, uy=300)

def test_constraint_ops():
    """
    Tests Equality.__eq__, Inequality.__eq__, LinearTerm.__rsub__,
    LinearTerm.__radd__ and others.
    """
    
    layers = SG13G2().layers
    l = Layout(ref_layers=layers) 
 
    l.r1 = LayoutRect(layer=layers.Metal1)

    v1 = l.r1.rect.lx
    v2 = l.r1.rect.ux
    assert isinstance(v1 == 100, Constraint)
    assert isinstance(100 == v1, Constraint)
    assert isinstance(v1 >= 100, Constraint)
    assert isinstance(v1 <= 100, Constraint)
    with pytest.raises(TypeError):
        v1 + 10 < v2 + 10

    with pytest.raises(TypeError):
        v1 + 10 > v2 + 10

    assert (100 == v1) == (v1 == 100)
    assert (100 == v1) != (v1 >= 100)
    assert (100 == v1) != (v2 == 100)
    assert (100 == v1) != (v1 == 90)
    assert (v2 == 100 - v1) == (v2 == -v1 + 100)
    assert (30 + v1 == 40 + v2) == (v1 - v2 - 10 == 0)


def test_no_solution():
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)

    l.activ = LayoutRect(layer=layers.Activ)

    s = Solver(l)
    s.constrain(l.activ.rect.width == 500)
    s.constrain(l.activ.rect.height == 150)
    s.constrain(l.activ.rect.lx == 100)
    s.constrain(l.activ.rect.ly == -100)
    s.constrain(l.activ.rect.ux == 900) # conflicting with lx == 100 and width == 500

    with pytest.raises(SolverError):
        s.solve()

def test_missing_variables():
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)

    l.activ = LayoutRect(layer=layers.Activ)

    # For l.activ.rect, ly und uy have constraints, but lx and ux have non constraints.

    s = Solver(l)
    s.constrain(l.activ.rect.ly == 100)
    s.constrain(l.activ.rect.uy == 200)
    s.solve()

    assert l.activ.rect == Rect4I(0, 100, 0, 200)

def test_vec2():
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)

    l.m1 = LayoutRect(layer=layers.Metal1.pin)
    l.label = LayoutLabel(layer=layers.Metal1.pin)

    s = Solver(l)
    s.constrain(l.m1.rect.width == 150)
    s.constrain(l.m1.rect.height == 150)
    s.constrain(l.m1.rect.lx == 0)
    s.constrain(l.m1.rect.ly == 0)
    s.constrain(l.label.pos.x == l.m1.rect.cx)
    s.constrain(l.label.pos.y == l.m1.rect.cy)
    s.solve()

    assert l.m1.rect == Rect4I(lx=0, ly=0, ux=150, uy=150)
    assert l.label.pos == Vec2I(75, 75)

def test_multiconstraint():
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)

    l.activ = LayoutRect(layer=layers.Activ)

    s = Solver(l)
    s.constrain((l.activ.rect.lx == l.activ.rect.ly) & (l.activ.rect.ly == 100))
    s.constrain(l.activ.rect.is_square(150))
    s.solve()

    assert l.activ.rect == Rect4I(lx=100, ly=100, ux=250, uy=250)


def test_layoutinstance_subcursor_constraints():
    """
    Tests whether LayoutInstanceSubcursors of LayoutInstance with undefined
    position (=None) can be used for building constraints.
    Tests with all possible orientations.
    """
    layers = SG13G2().layers

    layout1 = Layout(ref_layers=layers)
    layout1.myrect = LayoutRect(
        layer=layers.Metal1,
        rect=Rect4I(100, 500, 200, 700),
    )
    layout1 = layout1.freeze()

    for orientation in D4:
        layout2 = Layout(ref_layers=layers)
        layout2.layout1_inst = LayoutInstance(orientation=orientation, ref=layout1)

        assert isinstance(layout2.layout1_inst.myrect.rect, Rect4LinearTerm)
        s = Solver(layout2)
        s.constrain(layout2.layout1_inst.myrect.rect.lx == 1000)
        s.constrain(layout2.layout1_inst.myrect.rect.ly == 900)

        s.solve()
        #print(layout2.layout1_inst.myrect.rect.lx, layout2.layout1_inst.myrect.rect.ly)
        #print(layout2.layout1_inst.pos)

        assert layout2.layout1_inst.myrect.rect.lx == 1000
        assert layout2.layout1_inst.myrect.rect.ly == 900

def test_variable_on_frozen_subgraph():
    layers = SG13G2().layers

    layout1 = Layout(ref_layers=layers)
    layout1.myrect = LayoutRect(layer=layers.Metal1)
    layout1 = layout1.freeze()

    with pytest.raises(ValueError, match="Subgraph of Variable must be mutable."):
        layout1.myrect.rect

def test_solve_wrong_subgraph():
    layers = SG13G2().layers

    layout1 = Layout(ref_layers=layers)
    layout1.myrect = LayoutRect(layer=layers.Metal1)

    layout2 = Layout(ref_layers=layers)
    layout2.myrect = LayoutRect(layer=layers.Metal1)

    s = Solver(layout2)
    s.constrain(layout1.myrect.rect.lx == 1)
    s.constrain(layout1.myrect.rect.ux == 2)
    s.constrain(layout1.myrect.rect.ly == 3)
    s.constrain(layout1.myrect.rect.uy == 4)

    with pytest.raises(SolverError, match="Solver found Variables of unexpected subgraph"):
        s.solve()

def test_vec2_constraints_eq():
    layers = SG13G2().layers

    layout = Layout(ref_layers=layers)
    layout.r1 = LayoutRect(layer=layers.Metal1)
    layout.r2 = LayoutRect(layer=layers.Metal2)
    
    s = Solver(layout)
    s.constrain(layout.r1.rect.center == layout.r2.rect.center)
    s.constrain(layout.r1.rect.size == (100, 100))
    s.constrain(layout.r2.rect.size == (300, 400))
    s.constrain(layout.r1.rect.southwest == (1000, -1000))
    s.solve()

    assert layout.r1.rect == Rect4I(lx=1000, ly=-1000, ux=1100, uy=-900)
    assert layout.r2.rect == Rect4I(lx=900, ly=-1150, ux=1200, uy=-750)

def test_rect4_constraints_eq():
    layers = SG13G2().layers

    layout = Layout(ref_layers=layers)
    layout.r1 = LayoutRect(layer=layers.Metal1)
    layout.r2 = LayoutRect(layer=layers.Metal2)
    layout.r3 = LayoutRect(layer=layers.Metal3)

    s = Solver(layout)
    s.constrain(layout.r1.rect.lx == 100)
    s.constrain(layout.r1.rect.ly == 200)
    s.constrain(layout.r1.rect.ux == 300)
    s.constrain(layout.r1.rect.uy == 400)
    s.constrain(layout.r2.rect == layout.r1.rect)
    s.constrain(layout.r3.rect == (10, 20, 30, 40))
    s.solve()

    assert layout.r2.rect == Rect4I(100, 200, 300, 400)
    assert layout.r3.rect == Rect4I(10, 20, 30, 40)

def test_rect4_constraints_contains():
    layers = SG13G2().layers

    layout = Layout(ref_layers=layers)
    layout.r1 = LayoutRect(layer=layers.Metal1)
    layout.r2 = LayoutRect(layer=layers.Metal1)
    layout.r3 = LayoutRect(layer=layers.Metal1)

    layout.r4 = LayoutRect(layer=layers.Metal2)

    s = Solver(layout)
    s.constrain(layout.r1.rect.size == (100, 100))
    s.constrain(layout.r2.rect.size == (100, 100))
    s.constrain(layout.r3.rect.size == (100, 100))

    s.constrain(layout.r1.rect.southwest == (1000, -1000))
    s.constrain(layout.r2.rect.southwest == (1600, -900))
    s.constrain(layout.r3.rect.southwest == (1300, -500))

    s.constrain(layout.r4.rect.contains(layout.r1.rect))
    s.constrain(layout.r4.rect.contains(layout.r2.rect))
    s.constrain(layout.r4.rect.contains(layout.r3.rect))

    s.solve()

    assert layout.r4.rect == Rect4I(lx=1000, ly=-1000, ux=1700, uy=-400)        
