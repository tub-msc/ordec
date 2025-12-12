# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core.geoprim import Vec2R, Vec2I, TD4R, TD4I, Rect4R, Rect4I, D4
from ordec.core.rational import R
import pytest

def test_D4():
    assert D4.R0   * D4.R0   == D4.R0
    assert D4.R90  * D4.R90  == D4.R180
    assert D4.R180 * D4.R90  == D4.R270
    assert D4.R270 * D4.R90  == D4.R0
    assert D4.R180 * D4.R180 == D4.R0

    assert repr(D4.R0) == 'D4.R0'
    assert str(D4.R0) == 'D4.R0'

    flip_pairs = (
        (D4.R0,   D4.MY),
        (D4.R90,  D4.MY90),
        (D4.R180, D4.MX),
        (D4.R270, D4.MX90),
    )
    for a, b in flip_pairs:
        assert a.flip() == b
        assert b.flip() == a
        assert a.det() == 1
        assert b.det() == -1
        assert a.unflip() == a
        assert b.unflip() == a

    for a in D4:
        assert a.inv() * a == D4.R0
        assert a * Vec2R(0, 1) == a.flip() * Vec2R(0, 1)

def test_TD4R():
    assert TD4R() * TD4R() == TD4R()

    assert D4.R0 * Vec2R(12, 34) == Vec2R(12, 34)
    assert D4.R90 * Vec2R(12, 34) == Vec2R(-34, 12)
    assert D4.R180 * Vec2R(12, 34) == Vec2R(-12, -34)
    assert D4.R270 * Vec2R(12, 34) == Vec2R(34, -12)
    assert D4.MY * Vec2R(12, 34) == Vec2R(-12, 34)
    assert D4.MY90 * Vec2R(12, 34) == Vec2R(-34, -12)
    assert D4.MX * Vec2R(12, 34) == Vec2R(12, -34)
    assert D4.MX90 * Vec2R(12, 34) == Vec2R(34, 12)

    assert Vec2R(77, -9).transl() * Vec2R(1, 5) == Vec2R(78, -4)
    assert Vec2R(-10, 2).transl() * Vec2R(77, -9).transl() * Vec2R(1, 5) == Vec2R(68, -2)

    assert (D4.R90 * Vec2R(77, -9).transl()) * Vec2R(1, 5) == Vec2R(4, 78)
    assert D4.R90 * (Vec2R(77, -9).transl() * Vec2R(1, 5)) == Vec2R(4, 78)
    assert Vec2R(77, -9).transl() * (D4.R90 * Vec2R(1, 5)) == Vec2R(72, -8)
    assert (Vec2R(77, -9).transl() * D4.R90) * Vec2R(1, 5) == Vec2R(72, -8)

    t1 = TD4R(Vec2R(1,2), D4.MX)
    t2 = TD4R(Vec2R(5,6), D4.R90)
    
    assert repr(t1) == "TD4R(transl=Vec2R(R('1.'), R('2.')), d4=D4.MX)"

    with pytest.raises(AttributeError):
        t1.hello = 'world'
    with pytest.raises(AttributeError):
        t1.negx = 123

    with pytest.raises(TypeError):
        t1 + t2

    assert t1.d4 == D4.MX
    assert t2.d4 == D4.R90

    assert t1 * t2 == TD4R(Vec2R(6, -4), D4.MY90)

def test_TD4I():
    assert TD4I() * TD4I() == TD4I()

    assert D4.R0 * Vec2I(12, 34) == Vec2I(12, 34)
    assert D4.R90 * Vec2I(12, 34) == Vec2I(-34, 12)
    assert D4.R180 * Vec2I(12, 34) == Vec2I(-12, -34)
    assert D4.R270 * Vec2I(12, 34) == Vec2I(34, -12)
    assert D4.MY * Vec2I(12, 34) == Vec2I(-12, 34)
    assert D4.MY90 * Vec2I(12, 34) == Vec2I(-34, -12)
    assert D4.MX * Vec2I(12, 34) == Vec2I(12, -34)
    assert D4.MX90 * Vec2I(12, 34) == Vec2I(34, 12)

    assert Vec2I(77, -9).transl() * Vec2I(1, 5) == Vec2I(78, -4)
    assert Vec2I(-10, 2).transl() * Vec2I(77, -9).transl() * Vec2I(1, 5) == Vec2I(68, -2)

    assert (D4.R90 * Vec2I(77, -9).transl()) * Vec2I(1, 5) == Vec2I(4, 78)
    assert D4.R90 * (Vec2I(77, -9).transl() * Vec2I(1, 5)) == Vec2I(4, 78)
    assert Vec2I(77, -9).transl() * (D4.R90 * Vec2I(1, 5)) == Vec2I(72, -8)
    assert (Vec2I(77, -9).transl() * D4.R90) * Vec2I(1, 5) == Vec2I(72, -8)

    t1 = TD4I(Vec2I(1,2), D4.MX)
    t2 = TD4I(Vec2I(5,6), D4.R90)
    
    assert repr(t1) == "TD4I(transl=Vec2I(1, 2), d4=D4.MX)"

    with pytest.raises(AttributeError):
        t1.hello = 'world'
    with pytest.raises(AttributeError):
        t1.negx = 123

    with pytest.raises(TypeError):
        t1 + t2

    assert t1.d4 == D4.MX
    assert t2.d4 == D4.R90

    assert t1 * t2 == TD4R(Vec2I(6, -4), D4.MY90)

def test_Vec2R():
    v = Vec2R(1, 2)
    assert isinstance(v.x, R)
    assert isinstance(v.y, R)

    with pytest.raises(AttributeError):
        v.hello = 'world'
    with pytest.raises(AttributeError):
        v.x = 123

    assert repr(v) == "Vec2R(R('1.'), R('2.'))"

def test_Vec2I():
    v = Vec2I(1, 2)
    assert isinstance(v.x, int)
    assert isinstance(v.y, int)

    with pytest.raises(AttributeError):
        v.hello = 'world'
    with pytest.raises(AttributeError):
        v.x = 123

    assert repr(v) == "Vec2I(1, 2)"


def test_Rect4R():
    r = Rect4R(1, 2, 3, 4)
    with pytest.raises(AttributeError):
        r.hello = 'world'
    with pytest.raises(AttributeError):
        r.lx = 123

    assert repr(r) == "Rect4R(lx=R('1.'), ly=R('2.'), ux=R('3.'), uy=R('4.'))"

    with pytest.raises(ValueError, match=r"lx is greater than ux"):
        Rect4R(0, 0, -1, 0)

    with pytest.raises(ValueError, match=r"ly is greater than uy."):
        Rect4R(0, 0, 0, -1)

    with pytest.raises(TypeError):
        Rect4R(1,2,3,3)+Rect4R(4,5,5,6)

    myrect = Rect4R(10, 30, 20, 40)

    inside = [
        Vec2R(20, 30),
        Vec2R(10, 30),
        Vec2R(15, 30),
        Vec2R(15, 35),
        Vec2R(15, 40),
        Vec2R(20, 40),
        Vec2R(10, 40),
    ]
    for v in inside:
        assert v in myrect
        assert myrect.extend(v) is myrect

    outside = [
        (Vec2R(9, 30),    Rect4R(9, 30, 20, 40)),
        (Vec2R(21, 30),   Rect4R(10, 30, 21, 40)),
        (Vec2R(15, 41),   Rect4R(10, 30, 20, 41)),
        (Vec2R(15, -100), Rect4R(10, -100, 20, 40)),
    ]
    for v, extended in outside:
        assert v not in myrect
        assert myrect.extend(v) == extended

def test_Rect4I():
    r = Rect4I(1, 2, 3, 4)
    with pytest.raises(AttributeError):
        r.hello = 'world'
    with pytest.raises(AttributeError):
        r.lx = 123

    assert repr(r) == "Rect4I(lx=1, ly=2, ux=3, uy=4)"

    with pytest.raises(ValueError, match=r"lx is greater than ux"):
        Rect4I(0, 0, -1, 0)

    with pytest.raises(ValueError, match=r"ly is greater than uy."):
        Rect4I(0, 0, 0, -1)

    with pytest.raises(TypeError):
        Rect4I(1,2,3,3)+Rect4I(4,5,5,6)

    myrect = Rect4I(10, 30, 20, 40)

    inside = [
        Vec2I(20, 30),
        Vec2I(10, 30),
        Vec2I(15, 30),
        Vec2I(15, 35),
        Vec2I(15, 40),
        Vec2I(20, 40),
        Vec2I(10, 40),
    ]
    for v in inside:
        assert v in myrect
        assert myrect.extend(v) is myrect

    outside = [
        (Vec2I(9, 30),    Rect4I(9, 30, 20, 40)),
        (Vec2I(21, 30),   Rect4I(10, 30, 21, 40)),
        (Vec2I(15, 41),   Rect4I(10, 30, 20, 41)),
        (Vec2I(15, -100), Rect4I(10, -100, 20, 40)),
    ]
    for v, extended in outside:
        assert v not in myrect
        assert myrect.extend(v) == extended

def test_td4i_mul_rect4i():
    """Checks that the new TD4.__mul__ handles Rect... objects properly."""
    W, S, E, N = 1, 2, 3, 4
    R = Rect4I(W, S, E, N)
    O = Vec2I(10, 10)
    for d4 in D4:
        tran = TD4I(d4=d4, transl=O)
        tl = tran * Vec2I(W, S)
        tu = tran * Vec2I(E, N)
        lx, ux = sorted([tl.x, tu.x])
        ly, uy = sorted([tl.y, tu.y])
        assert tran * R == Rect4I(lx, ly, ux, uy)

def test_mix_types():
    # Even though I highly discourage mixing ordec.geoprim's integer and
    # rational types, in the spirit of Python it should be possible to mix
    # them.

    assert Vec2R(1, 2) + Vec2I(3, 4) == Vec2R(4, 6)
    assert Vec2I(1, 2) + Vec2R(3, 4) == Vec2I(4, 6)

    assert Vec2I(15, 35) in Rect4R(10, 30, 20, 40)
    assert Vec2I(15, 55) not in Rect4R(10, 30, 20, 40)

    assert Vec2R(15, 35) in Rect4I(10, 30, 20, 40)
    assert Vec2R(15, 55) not in Rect4I(10, 30, 20, 40)

    with pytest.raises(TypeError):
        (15, 15) in Rect4I(10, 30, 20, 40)

    with pytest.raises(TypeError):
        (15, 15) in Rect4R(10, 30, 20, 40)

    assert Rect4R(10, 30, 20, 40).extend(Vec2I(15, 55)) == Rect4R(10, 30, 20, 55)
    assert Rect4I(10, 30, 20, 40).extend(Vec2R(15, 55)) == Rect4I(10, 30, 20, 55)

def test_neg():
    assert -Vec2R(123, 456) == Vec2R(-123, -456)
    assert -Vec2I(222, 333) == Vec2I(-222, -333)

def test_scalar_mul():
    assert Vec2I(5, 6)*10 == Vec2I(50, 60)
    assert 10*Vec2I(5, 6) == Vec2I(50, 60)
