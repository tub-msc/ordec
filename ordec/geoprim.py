# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Geometric primitive types: vectors, matrices, orientations and rotations (D4)
"""
from enum import Enum
from pyrsistent import PClass, field
from .rational import Rational as R

class Vec2R(PClass):
    """
    Point in 2D space.

    Attributes:
        x (Rational): x coordinate
        y (Rational): y coordinate
    """

    x = field(type=(R,), factory=R, mandatory=True)
    y = field(type=(R,), factory=R, mandatory=True)
    def tofloat(self):
        return float(self.x), float(self.y)

    def __add__(self, other):
        return Vec2R(x=self.x+other.x, y=self.y+other.y)

class Rect4R(PClass):
    """
    Rectangle in 2D space.

    Attributes:
        lx (Rational): lower x coordinate
        ly (Rational): lower y coordinate
        ux (Rational): upper x coordinate
        uy (Rational): upper y coordinate
    """

    __invariant__ = lambda r: (r.lx <= r.ux and r.ly <= r.uy, "lx or ly greater than ux or uy")

    lx = field(type=(R,), factory=R, mandatory=True)
    ly = field(type=(R,), factory=R, mandatory=True)
    ux = field(type=(R,), factory=R, mandatory=True)
    uy = field(type=(R,), factory=R, mandatory=True)
    def tofloat(self):
        return float(self.lx), float(self.ly), float(self.ux), float(self.uy)

    def south_east(self):
        return Vec2R(x=self.ux, y=self.ly)
    def south_west(self):
        return Vec2R(x=self.lx, y=self.ly)
    def north_east(self):
        return Vec2R(x=self.ux, y=self.uy)
    def north_west(self):
        return Vec2R(x=self.lx, y=self.uy)


class TD4(PClass):
    """
    Transformation group supporting 2D translation, X/Y mirroring and 90° rotations.
    Multiply instances of this class with a :class:`Vec2R`, :class:`Rect4R` or :class:`TD4`
    to apply the transformation.

    Attributes:
        transl (Vec2R): translation vector
        flipxy (bool): flip x/y coordinates
        negx (bool): negate x coordinate
        negy (bool): negate y coordinate
    """

    transl = field(type=(Vec2R,), mandatory=True, initial=Vec2R(x=0,y=0))
    flipxy = field(type=(bool,), mandatory=True, initial=False)
    negx = field(type=(bool,), mandatory=True, initial=False)
    negy = field(type=(bool,), mandatory=True, initial=False)

    def __mul__(self, other):
        if isinstance(other, Vec2R):
            if self.flipxy:
                x, y = other.y, other.x
            else:
                x, y = other.x, other.y
            if self.negx:
                x = -x
            if self.negy:
                y = -y
            return Vec2R(x = self.transl.x + x, y = self.transl.y + y)
        elif isinstance(other, Rect4R):
            tl = self * Vec2R(x=other.lx, y=other.ly)
            tu = self * Vec2R(x=other.ux, y=other.uy)

            lx, ux = sorted([tl.x, tu.x])
            ly, uy = sorted([tl.y, tu.y])
            return Rect4R(lx=lx, ly=ly, ux=ux, uy=uy)
        elif isinstance(other, TD4):
            if self.flipxy:
                onegx, onegy = other.negy, other.negx
            else:
                onegx, onegy = other.negx, other.negy

            return TD4(
                transl=self * other.transl,
                flipxy=self.flipxy ^ other.flipxy,
                negx=self.negx ^ onegx,
                negy=self.negy ^ onegy,
            )
        else:
            raise TypeError(f"Unsupported type for {type(self).__name__} multiplication")

    def det(self) -> int:
        """Returns 1 if handedness is preserved, -1 if flipped."""
        return -1 if self.flipxy ^ self.negx ^ self.negy else 1

    def flip(self) -> "TD4":
        """Returns TD4 with flipped handedness, preserving the point Vec2R(x=0, y=1)."""
        if self.flipxy:
            return self.set(negy=not self.negy)
        else:
            return self.set(negx=not self.negx)

    def arc(self, angle_start: R, angle_end: R) -> (R, R):
        """
        Rotates an arc / pair of angles (angle_start, angle_end).
        R(1) = 360° = 2pi
        """
        l = angle_end - angle_start
        #assert l > R(0)
        d = D4(self.set(transl=Vec2R(x=0,y=0)))
        a = {
            D4.R0: R(0),
            D4.R90: R(0.25),
            D4.R180: R(0.5),
            D4.R270: R(0.75),
        }[d.unflip()]

        if d.value.det() == 1:
            s = a + angle_start
            return s, s + l
        else:
            s = R(0.5) + a - angle_start
            return s - l, s

class D4(Enum):
    """
    Dihedral group D4, supporting X/Y mirroring and 90° rotations.

    Attributes:
        R0: rotation by 0° (identity element)
        R90: rotation by 90°
        R180: rotation by 180°
        R270: rotation by 270°
        MX: mirror along X axis (flipping Y coordinate)
        MY: mirror along Y axis (flipping X coordinate)
        MX90: mirror along X axis, followed by 90° rotation
        MY90: mirror along Y axis, followed by 90° rotation
    """
    R0 = TD4()
    R90 = TD4(negx=True, flipxy=True)
    R180 = R90 * R90
    R270 = R180 * R90
    MX = TD4(negy=True)
    MY = TD4(negx=True)
    MX90 = R90 * MX
    MY90 = R90 * MY

    def __repr__(self):
        return f'{self.__class__.__name__}.{self.name}'

    def __mul__(self, other):
        if isinstance(other, D4):
            return D4(self.value*other.value)
        else:
            return self.value*other

    def unflip(self) -> "D4":
        """
        Return D4 element with non-flipped handedness (det=1), preserving
        Vec2R(x=0, y=1).
        """
        if self.value.det() < 0:
            return D4(self.value.flip())
        else:
            return self

    def inv(self) -> "D4":
        """
        Returns D4 such that x.inv()*x == x*x.inv() == D4.R0.
        """
        return {
            D4.R0: D4.R0,
            D4.R90: D4.R270,
            D4.R180: D4.R180,
            D4.R270: D4.R90,
            D4.MX: D4.MX,
            D4.MY: D4.MY,
            D4.MX90: D4.MX90,
            D4.MY90: D4.MY90,
        }[self]

    def lefdef(self) -> str:
        return {
            D4.R0: "N", # North
            D4.R90: "W", # West
            D4.R180: "S", # South
            D4.R270: "E", # East
            D4.MX: "FN", # Flipped North
            D4.MY: "FS", # Flipped South
            D4.MX90: "FW", # Flipped West
            D4.MY90: "FE", # Flipped East
        }[self]

    North = R0
    East = R270
    South = R180
    West = R90
    FlippedNorth = MX
    FlippedSouth = MY
    FlippedWest = MX90
    FlippedEast = MY90

Orientation = D4 # alias
