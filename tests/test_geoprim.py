# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.geoprim import Vec2R, D4, TD4
from ordec.rational import Rational as R

def test_TD4():
    assert TD4() * TD4() == TD4()

    assert D4.R0   * D4.R0   == D4.R0
    assert D4.R90  * D4.R90  == D4.R180
    assert D4.R180 * D4.R90  == D4.R270
    assert D4.R270 * D4.R90  == D4.R0
    assert D4.R180 * D4.R180 == D4.R0

    assert repr(D4.R0) == 'D4.R0'
    assert str(D4.R0) == 'D4.R0'

    assert D4.R0 * Vec2R(x=12, y=34) == Vec2R(x=12, y=34)
    assert D4.R90 * Vec2R(x=12, y=34) == Vec2R(x=-34, y=12)
    assert D4.R180 * Vec2R(x=12, y=34) == Vec2R(x=-12, y=-34)
    assert D4.R270 * Vec2R(x=12, y=34) == Vec2R(x=34, y=-12)
    assert D4.MY * Vec2R(x=12, y=34) == Vec2R(x=-12, y=34)
    assert D4.MY90 * Vec2R(x=12, y=34) == Vec2R(x=-34, y=-12)
    assert D4.MX * Vec2R(x=12, y=34) == Vec2R(x=12, y=-34)
    assert D4.MX90 * Vec2R(x=12, y=34) == Vec2R(x=34, y=12)

    assert TD4(transl=Vec2R(x=77, y=-9)) * Vec2R(x=1, y=5) == Vec2R(x=78, y=-4)

    assert TD4(transl=Vec2R(x=-10, y=2)) * TD4(transl=Vec2R(x=77, y=-9)) * Vec2R(x=1, y=5) == Vec2R(x=68, y=-2)

    assert (D4.R90 * TD4(transl=Vec2R(x=77, y=-9))) * Vec2R(x=1, y=5) == Vec2R(x=4, y=78)
    assert D4.R90 * (TD4(transl=Vec2R(x=77, y=-9)) * Vec2R(x=1, y=5)) == Vec2R(x=4, y=78)
    assert TD4(transl=Vec2R(x=77, y=-9)) * (D4.R90 * Vec2R(x=1, y=5)) == Vec2R(x=72, y=-8)
    assert (TD4(transl=Vec2R(x=77, y=-9)) * D4.R90.value) * Vec2R(x=1, y=5) == Vec2R(x=72, y=-8)

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
        assert a.value*Vec2R(x=0, y=1) == a.value.flip()*Vec2R(x=0, y=1)
