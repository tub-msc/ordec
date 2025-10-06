# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core.geoprim import Vec2R, D4, TD4, Rect4R, Vec2I, Rect4I
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

    with pytest.raises(ValueError, match=r"lx or ly greater than ux or uy"):
        Rect4R(0, 0, -1, 0)

    with pytest.raises(ValueError, match=r"lx or ly greater than ux or uy"):
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

    with pytest.raises(ValueError, match=r"lx or ly greater than ux or uy"):
        Rect4I(0, 0, -1, 0)

    with pytest.raises(ValueError, match=r"lx or ly greater than ux or uy"):
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
