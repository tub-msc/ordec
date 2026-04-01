# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from ordec.core import *
from ordec.lib.ihp130 import SG13G2
from ordec.core.constraints import Variable, LinearTerm, Constraint, UnderconstrainedError

def test_equalities():
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)

    l.activ = LayoutRect(layer=layers.Activ)
    l.poly = LayoutRect(layer=layers.GatPoly)

    s = Solver(l)

    s.constrain(l.activ.width == 500)
    s.constrain(l.activ.height == 150)
    s.constrain(l.activ.lx == 100)
    s.constrain(l.activ.ly == -100)

    s.constrain(l.activ.cx == l.poly.cx) # align x centers
    s.constrain(l.activ.cy == l.poly.cy) # align y centers
    s.constrain(l.poly.height == 300)
    s.constrain(l.poly.width == 100)

    s.solve()

    assert l.activ.rect == Rect4I(lx=100, ly=-100, ux=600, uy=50)
    assert l.poly.rect == Rect4I(lx=300, ly=-175, ux=400, uy=125)

def test_underconstrained_1():
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)

    l.activ = LayoutRect(layer=layers.Activ)

    s = Solver(l)
    s.constrain(l.activ.width == 500)
    s.constrain(l.activ.height == 150)
    s.constrain(l.activ.lx == 100)
    # Missing constraint for ly - system is underconstrained.

    with pytest.raises(UnderconstrainedError) as exc_info:
        s.solve()

    err = exc_info.value
    assert err.ambiguity_info.degrees_of_freedom == 1  # ly is free (and uy follows since height is fixed)
    assert err.ambiguity_info.constraint_rank == 3  # 3 independent constraints
    assert err.ambiguity_info.null_space.shape == (4, 1)  # 4 variables, 1 degree of freedom

def test_underconstrained_2():
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)

    l.r1 = LayoutRect(layer=layers.Metal1)
    l.r2 = LayoutRect(layer=layers.Metal1)
    l.r3 = LayoutRect(layer=layers.Metal1)

    s = Solver(l)

    # l.r1.lx not constrained.
    s.constrain(l.r1.ly == 0)
    s.constrain(l.r1.height >= 100)
    s.constrain(l.r1.width >= 200)

    s.constrain(l.r2.lx >= l.r1.ux)
    s.constrain(l.r2.ly <= l.r1.lx)
    s.constrain(l.r2.width == l.r2.height)
    # l.r2.width and .height not properly constrained.

    with pytest.raises(UnderconstrainedError) as exc_info:
        s.solve()

    err = exc_info.value
    assert err.ambiguity_info.degrees_of_freedom == 2
    assert err.ambiguity_info.constraint_rank == 6
    assert err.ambiguity_info.null_space.shape == (8, 2) # 8 variables, 2 degree of freedom

def test_missing_variables():
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)

    l.activ = LayoutRect(layer=layers.Activ)

    # For l.activ, ly and uy have constraints, but lx and ux have no constraints.

    s = Solver(l)
    s.constrain(l.activ.ly == 100)
    s.constrain(l.activ.uy == 200)

    with pytest.raises(UnderconstrainedError) as exc_info:
        s.solve()

    err = exc_info.value
    assert err.ambiguity_info.degrees_of_freedom == 2
    assert err.ambiguity_info.constraint_rank == 2
    assert err.ambiguity_info.null_space.shape == (4, 2)

def test_inequalities():
    layers = SG13G2().layers
    l = Layout(ref_layers=layers) 
 
    l.r1 = LayoutRect(layer=layers.Metal1)
    l.r2 = LayoutRect(layer=layers.Metal1)

    s = Solver(l)
    s.constrain(l.r1.height >= 500)
    s.constrain(l.r1.width >= 150)
    s.constrain(l.r1.southwest == (100, -100))

    s.constrain(l.r2.lx >= l.r1.ux + 150)
    s.constrain(l.r2.width == -l.r1.height + 800)
    s.constrain(l.r2.width <= 150) # Adjust this factor & see what happens.

    s.constrain(l.r2.height == 150)
    s.constrain(l.r2.cy == l.r1.cy)

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

    v1 = l.r1.lx
    v2 = l.r1.ux
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
    s.constrain(l.activ.width == 500)
    s.constrain(l.activ.height == 150)
    s.constrain(l.activ.lx == 100)
    s.constrain(l.activ.ly == -100)
    s.constrain(l.activ.ux == 900) # conflicting with lx == 100 and width == 500

    with pytest.raises(SolverError):
        s.solve()


def test_vec2():
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)

    l.m1 = LayoutRect(layer=layers.Metal1.pin)
    l.label = LayoutLabel(layer=layers.Metal1.pin)

    s = Solver(l)
    s.constrain(l.m1.width == 150)
    s.constrain(l.m1.height == 150)
    s.constrain(l.m1.lx == 0)
    s.constrain(l.m1.ly == 0)
    s.constrain(l.label.pos.x == l.m1.cx)
    s.constrain(l.label.pos.y == l.m1.cy)
    s.solve()

    assert l.m1.rect == Rect4I(lx=0, ly=0, ux=150, uy=150)
    assert l.label.pos == Vec2I(75, 75)

def test_multiconstraint():
    layers = SG13G2().layers
    l = Layout(ref_layers=layers)

    l.activ = LayoutRect(layer=layers.Activ)

    s = Solver(l)
    s.constrain((l.activ.lx == l.activ.ly) & (l.activ.ly == 100))
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
        s.constrain(layout2.layout1_inst.myrect.lx == 1000)
        s.constrain(layout2.layout1_inst.myrect.ly == 900)

        s.solve()

        assert layout2.layout1_inst.myrect.lx == 1000
        assert layout2.layout1_inst.myrect.ly == 900

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
    s.constrain(layout1.myrect.lx == 1)
    s.constrain(layout1.myrect.ux == 2)
    s.constrain(layout1.myrect.ly == 3)
    s.constrain(layout1.myrect.uy == 4)

    with pytest.raises(SolverError, match="Solver found Variables of unexpected subgraph"):
        s.solve()

def test_vec2_constraints_eq():
    layers = SG13G2().layers

    layout = Layout(ref_layers=layers)
    layout.r1 = LayoutRect(layer=layers.Metal1)
    layout.r2 = LayoutRect(layer=layers.Metal2)
    
    s = Solver(layout)
    s.constrain(layout.r1.center == layout.r2.center)
    s.constrain(layout.r1.size == (100, 100))
    s.constrain(layout.r2.size == (300, 400))
    s.constrain(layout.r1.southwest == (1000, -1000))
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
    s.constrain(layout.r1.lx == 100)
    s.constrain(layout.r1.ly == 200)
    s.constrain(layout.r1.ux == 300)
    s.constrain(layout.r1.uy == 400)
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
    s.constrain(layout.r1.size == (100, 100))
    s.constrain(layout.r2.size == (100, 100))
    s.constrain(layout.r3.size == (100, 100))

    s.constrain(layout.r1.southwest == (1000, -1000))
    s.constrain(layout.r2.southwest == (1600, -900))
    s.constrain(layout.r3.southwest == (1300, -500))

    s.constrain(layout.r4.contains(layout.r1))
    s.constrain(layout.r4.contains(layout.r2))
    s.constrain(layout.r4.contains(layout.r3))

    s.solve()

    assert layout.r4.rect == Rect4I(lx=1000, ly=-1000, ux=1700, uy=-400)        
