# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Geometric primitive types: vectors, matrices, orientations and rotations (D4)
"""
from enum import Enum
from .rational import Rational as R
from public import public
from collections import namedtuple

class Vec2Generic(tuple):
    __slots__ = ()

    @property
    def x(self):
        return self[0]

    @property
    def y(self):
        return self[1]

    def tofloat(self):
        return float(self.x), float(self.y)

    def __add__(self, other):
        return type(self)(self.x+other.x, self.y+other.y)

    def __sub__(self, other):
        return type(self)(self.x-other.x, self.y-other.y)

    def __neg__(self):
        return type(self)(-self.x, -self.y)

    def __mul__(self, other):
        # Multiplication with scalar
        return type(self)(other*self.x, other*self.y)

    def __rmul__(self, other):
        return self.__mul__(other)

    def __repr__(self):
        return f"{type(self).__name__}({self.x!r}, {self.y!r})"

@public
class Vec2R(Vec2Generic):
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

    
    def transl(self) -> 'TD4':
        return TD4R(transl=self)

@public
class Vec2I(Vec2Generic):
    """
    Like Vec2R, but with integer coordinates.
    """

    __slots__ = ()

    def __new__(cls, x, y):
        x = int(x)
        y = int(y)
        return tuple.__new__(cls, (x, y))

    def transl(self) -> 'TD4':
        return TD4I(transl=self)

    def __floordiv__(self, other):
        return Vec2I(self.x // other, self.y // other)

class Rect4Generic(tuple):
    __slots__ = ()

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
        return self.vector_cls(self.ux, self.ly)
    def south_west(self):
        return self.vector_cls(self.lx, self.ly)
    def north_east(self):
        return self.vector_cls(self.ux, self.uy)
    def north_west(self):
        return self.vector_cls(self.lx, self.uy)

    def __contains__(self, point):
        if not isinstance(point, (Vec2R, Vec2I)):
            raise TypeError("Left-hand side of 'in' supports only Vec2R/Vec2I.")
        return point.x >= self.lx \
            and point.x <= self.ux \
            and point.y >= self.ly \
            and point.y <= self.uy

    def extend(self, point):
        if point in self:
            return self
        else:
            return type(self)(
                lx=min(self.lx, point.x),
                ly=min(self.ly, point.y),
                ux=max(self.ux, point.x),
                uy=max(self.uy, point.y),
            )

    def __add__(self, other):
        raise TypeError(f"{type(self).__name__} cannot be added.")

    def __repr__(self):
        return f"{type(self).__name__}(lx={self.lx!r}, ly={self.ly!r}, ux={self.ux!r}, uy={self.uy!r})"

    @property
    def height(self):
        return self.uy - self.ly

    @property
    def width(self):
        return self.ux - self.lx

@public
class Rect4R(Rect4Generic):
    """
    Rectangle in 2D space.

    Attributes:
        lx (Rational): lower x coordinate
        ly (Rational): lower y coordinate
        ux (Rational): upper x coordinate
        uy (Rational): upper y coordinate
    """

    __slots__ = ()
    vector_cls = Vec2R

    def __new__(cls, lx, ly, ux, uy):
        lx = R(lx)
        ly = R(ly)
        ux = R(ux)
        uy = R(uy)

        if lx > ux:
            raise ValueError("lx is greater than ux.")

        if ly > uy:
            raise ValueError("ly is greater than uy.")

        return tuple.__new__(cls, (lx, ly, ux, uy))

@public
class Rect4I(Rect4Generic):
    __slots__ = ()
    vector_cls = Vec2I

    def __new__(cls, lx, ly, ux, uy):
        lx = int(lx)
        ly = int(ly)
        ux = int(ux)
        uy = int(uy)

        if lx > ux:
            raise ValueError("lx is greater than ux.")

        if ly > uy:
            raise ValueError("ly is greater than uy.")

        return tuple.__new__(cls, (lx, ly, ux, uy))

class TD4(tuple):
    """
    Transformation group supporting 2D translation, X/Y mirroring and 90° rotations.
    Multiply instances of this class with a :class:`Vec2R`, :class:`Rect4R` or :class:`TD4`
    to apply the transformation.

    Attributes:
        transl (Vec2R / Vec2I): translation vector
        flipxy (bool): flip x/y coordinates
        negx (bool): negate x coordinate
        negy (bool): negate y coordinate
    """

    __slots__ = ()

    def __new__(cls, transl=None, d4=None):
        if transl is None:
            transl=cls.vec_cls(0,0)
        if d4 is None:
            d4 = D4.R0
        return tuple.__new__(cls, (transl, d4))

    @property
    def transl(self):
        return self[0]

    @property
    def d4(self):
        return self[1]

    def __mul__(self, other):
        if isinstance(other, self.vec_cls):
            d4v = self.d4.value
            if d4v.flipxy:
                x, y = other.y, other.x
            else:
                x, y = other.x, other.y
            if d4v.negx:
                x = -x
            if d4v.negy:
                y = -y
            return self.vec_cls(x = self.transl.x + x, y = self.transl.y + y)
        elif isinstance(other, self.rect_cls):
            tl = self * self.vec_cls(other.lx, other.ly)
            tu = self * self.vec_cls(other.ux, other.uy)

            lx, ux = sorted([tl.x, tu.x])
            ly, uy = sorted([tl.y, tu.y])
            return self.rect_cls(lx=lx, ly=ly, ux=ux, uy=uy)
        elif isinstance(other, D4):
            return self * type(self)(d4=other)
        elif isinstance(other, type(self)):
            return type(self)(
                transl=self * other.transl,
                d4=self.d4 * other.d4,
            )
        else:
            raise TypeError(f"Unsupported type for {type(self).__name__} multiplication")

    def __add__(self, other):
        raise TypeError("TD4 cannot be added.")

    def det(self) -> int:
        """Returns 1 if handedness is preserved, -1 if flipped."""
        return self.d4.det()

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
        d4v = self.d4.value
        if d4v.flipxy:
            xx=(-1 if d4v.negx else 1) * y_scale
            yy=(-1 if d4v.negy else 1) * x_scale
            return f"matrix(0 {yy} {xx} 0 {x0} {y0})"
        else:
            xx=(-1 if d4v.negx else 1) * x_scale
            yy=(-1 if d4v.negy else 1) * y_scale
            return f"matrix({xx} 0 0 {yy} {x0} {y0})"

    def __repr__(self):
        return f"{type(self).__name__}(transl={self.transl!r}, d4={self.d4!r})"


@public
class TD4R(TD4):
    """Rational version of TD4"""
    __slots__ = ()
    vec_cls = Vec2R
    rect_cls = Rect4R

@public
class TD4I(TD4):
    """Integer version of TD4"""
    __slots__ = ()
    vec_cls = Vec2I
    rect_cls = Rect4I


D4Tuple = namedtuple('D4Tuple', ['flipxy', 'negx', 'negy'])

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


    R0   = D4Tuple(flipxy=False, negx=False, negy=False)
    R90  = D4Tuple(flipxy=True,  negx=True,  negy=False)
    R180 = D4Tuple(flipxy=False, negx=True,  negy=True)
    R270 = D4Tuple(flipxy=True,  negx=False, negy=True)
    MX   = D4Tuple(flipxy=False, negx=False, negy=True)
    MY   = D4Tuple(flipxy=False, negx=True,  negy=False)
    MX90 = D4Tuple(flipxy=True,  negx=False, negy=False)
    MY90 = D4Tuple(flipxy=True,  negx=True,  negy=True)

    def __repr__(self):
        return f'{self.__class__.__name__}.{self.name}'

    def __mul__(self, other):
        if isinstance(other, D4):
            if self.value.flipxy:
                onegx, onegy = other.value.negy, other.value.negx
            else:
                onegx, onegy = other.value.negx, other.value.negy

            return type(self)(D4Tuple(
                flipxy=self.value.flipxy ^ other.value.flipxy,
                negx=self.value.negx ^ onegx,
                negy=self.value.negy ^ onegy,
                ))
        elif isinstance(other, TD4):
            return type(other)(d4=self) * other
        elif isinstance(other, Vec2Generic):
            return (self * other.transl()).transl
        else:
            raise TypeError(f"Cannot multiply {self!r} with {other!r}.")

    def unflip(self) -> "D4":
        """
        Return D4 element with non-flipped handedness (det=1), preserving
        Vec2R(0, 1).
        """
        if self.det() < 0:
            return D4(self.flip())
        else:
            return self

    def det(self) -> int:
        """Returns 1 if handedness is preserved, -1 if flipped."""
        return -1 if self.value.flipxy ^ self.value.negx ^ self.value.negy else 1

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

    def flip(self) -> "Self":
        """Returns TD4 with flipped handedness, preserving the point (0, 1)."""
        if self.value.flipxy:
            return type(self)(D4Tuple(
                flipxy=self.value.flipxy,
                negx=self.value.negx,
                negy=not self.value.negy,
                ))
        else:
            return type(self)(D4Tuple(
                flipxy=self.value.flipxy,
                negx=not self.value.negx,
                negy=self.value.negy,
                ))

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


public(Orientation = D4) # alias
