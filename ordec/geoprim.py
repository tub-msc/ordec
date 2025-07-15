# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Geometric primitive types: vectors, matrices, orientations and rotations (D4)
"""
from enum import Enum
from .rational import Rational as R
from public import public

@public
class Vec2R(tuple):
    """
    Point in 2D space.

    Attributes:
        x (Rational): x coordinate
        y (Rational): y coordinate
    """

    __slots__ = ()

    def __new__(cls, x, y):
        x = R(x)
        y = R(y)
        return tuple.__new__(cls, (x, y))

    @property
    def x(self):
        return self[0]

    @property
    def y(self):
        return self[1]

    def tofloat(self):
        return float(self.x), float(self.y)

    def __add__(self, other):
        return Vec2R(x=self.x+other.x, y=self.y+other.y)

    def __sub__(self, other):
        return Vec2R(x=self.x-other.x, y=self.y-other.y)

    def __repr__(self):
        return f"Vec2R(x={self.x!r}, y={self.y!r})"

    def transl(self) -> 'TD4':
        return TD4(transl=self)

@public
class Rect4R(tuple):
    """
    Rectangle in 2D space.

    Attributes:
        lx (Rational): lower x coordinate
        ly (Rational): lower y coordinate
        ux (Rational): upper x coordinate
        uy (Rational): upper y coordinate
    """

    __slots__ = ()

    def __new__(cls, lx, ly, ux, uy):
        lx = R(lx)
        ly = R(ly)
        ux = R(ux)
        uy = R(uy)

        if lx > ux or ly > uy:
            raise ValueError("lx or ly greater than ux or uy")

        return tuple.__new__(cls, (lx, ly, ux, uy))

    @property
    def lx(self):
        return self[0]

    @property
    def ly(self):
        return self[1]

    @property
    def ux(self):
        return self[2]

    @property
    def uy(self):
        return self[3]

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

    def __add__(self, other):
        raise TypeError("Rect4R cannot be added.")

    def __repr__(self):
        return f"Rect4R(lx={self.lx!r}, ly={self.ly!r}, ux={self.ux!r}, uy={self.uy!r})"

@public
class TD4(tuple):
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

    __slots__ = ()

    def __new__(cls, transl=Vec2R(0,0), flipxy=False, negx=False, negy=False):
        return tuple.__new__(cls, (transl, flipxy, negx, negy))

    @property
    def transl(self):
        return self[0]

    @property
    def flipxy(self):
        return self[1]

    @property
    def negx(self):
        return self[2]

    @property
    def negy(self):
        return self[3]

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
        elif isinstance(other, D4):
            return self * other.value
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

    def __add__(self, other):
        raise TypeError("TD4 cannot be added.")

    def det(self) -> int:
        """Returns 1 if handedness is preserved, -1 if flipped."""
        return -1 if self.flipxy ^ self.negx ^ self.negy else 1

    def flip(self) -> "TD4":
        """Returns TD4 with flipped handedness, preserving the point Vec2R(x=0, y=1)."""
        if self.flipxy:
            return TD4(transl=self.transl, flipxy=self.flipxy, negx=self.negx, negy=not self.negy)
        else:
            return TD4(transl=self.transl, flipxy=self.flipxy, negx=not self.negx, negy=self.negy)

    def arc(self, angle_start: R, angle_end: R) -> (R, R):
        """
        Rotates an arc / pair of angles (angle_start, angle_end).
        R(1) = 360° = 2pi
        """
        l = angle_end - angle_start
        #assert l > R(0)
        d = D4.from_td4(self)
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


    def svg_transform(self, x_scale=1, y_scale=1) -> str:
        """
        Returns a string representation of the transformation
        suitable for the SVG attribute "transform".
        """
        x0, y0 = self.transl.tofloat()
        if self.flipxy:
            xx=(-1 if self.negx else 1) * y_scale
            yy=(-1 if self.negy else 1) * x_scale
            return f"matrix(0 {yy} {xx} 0 {x0} {y0})"
        else:
            xx=(-1 if self.negx else 1) * x_scale
            yy=(-1 if self.negy else 1) * y_scale
            return f"matrix({xx} 0 0 {yy} {x0} {y0})"

    def __repr__(self):
        return f"TD4(transl={self.transl!r}, flipxy={self.flipxy!r}, negx={self.negx!r}, negy={self.negy!r})"

@public
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
    R90  = TD4(flipxy=True,  negx=True,  negy=False)
    R180 = TD4(flipxy=False, negx=True,  negy=True)
    R270 = TD4(flipxy=True,  negx=False, negy=True)
    MX   = TD4(flipxy=False, negx=False, negy=True)
    MY   = TD4(flipxy=False, negx=True,  negy=False)
    MX90 = TD4(flipxy=True,  negx=False, negy=False)
    MY90 = TD4(flipxy=True,  negx=True,  negy=True)

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

    @classmethod
    def from_td4(cls, td4: TD4):
        return cls(TD4(flipxy=td4.flipxy, negx=td4.negx, negy=td4.negy))


public(Orientation = D4) # alias
