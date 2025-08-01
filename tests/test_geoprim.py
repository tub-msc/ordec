# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core.geoprim import Vec2R, D4, TD4, Rect4R
from ordec.core.rational import R
import pytest

def test_TD4():
    assert TD4() * TD4() == TD4()

    assert D4.R0   * D4.R0   == D4.R0
    assert D4.R90  * D4.R90  == D4.R180
    assert D4.R180 * D4.R90  == D4.R270
    assert D4.R270 * D4.R90  == D4.R0
    assert D4.R180 * D4.R180 == D4.R0

    assert repr(D4.R0) == 'D4.R0'
    assert str(D4.R0) == 'D4.R0'

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

    flip_pairs = (
        (D4.R0,   D4.MY),
        (D4.R90,  D4.MY90),
        (D4.R180, D4.MX),
        (D4.R270, D4.MX90),
    )
    for a, b in flip_pairs:
        assert D4(a.value.flip()) == b
        assert D4(b.value.flip()) == a
        assert a.value.det() == 1
        assert b.value.det() == -1
        assert a.unflip() == a
        assert b.unflip() == a

    for a in D4:
        assert a.inv() * a == D4.R0
        assert a * Vec2R(0, 1) == a.value.flip() * Vec2R(0, 1)

    t1 = TD4(Vec2R(1,2), False, False, True)

    assert repr(t1) == "TD4(transl=Vec2R(R('1.'), R('2.')), flipxy=False, negx=False, negy=True)"
    t2 = TD4(Vec2R(5,6), True, True, False)

    with pytest.raises(AttributeError):
        t1.hello = 'world'
    with pytest.raises(AttributeError):
        t1.negx = 123

    with pytest.raises(TypeError):
        t1 + t2

    assert D4.from_td4(t1) == D4.MX
    assert D4.from_td4(t2) == D4.R90

    assert t1 * t2 == TD4(Vec2R(6, -4), True, True, True)

def test_Vec2R():
    v = Vec2R(1, 2)
    assert isinstance(v.x, R)
    assert isinstance(v.y, R)

    with pytest.raises(AttributeError):
        v.hello = 'world'
    with pytest.raises(AttributeError):
        v.x = 123

    assert repr(v) == "Vec2R(R('1.'), R('2.'))"


def test_Rect4R():
    r = Rect4R(1, 2, 3, 4)
    with pytest.raises(AttributeError):
        r.hello = 'world'
    with pytest.raises(AttributeError):
        r.lx = 123

    assert repr(r) == "Rect4R(lx=R('1.'), ly=R('2.'), ux=R('3.'), uy=R('4.'))"

    with pytest.raises(ValueError, match=r"lx or ly greater than ux or uy"):
        Rect4R(0, 0, -1, 0)

    with pytest.raises(ValueError, match=r"lx or ly greater than ux or uy"):
        Rect4R(0, 0, 0, -1)

    with pytest.raises(TypeError):
        Rect4R(1,2,3,3)+Rect4R(4,5,5,6)
