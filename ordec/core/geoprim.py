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
    """
    2D vector, typically representing a point / vertex in 2D space.
    """

    def __new__(self, x, y):
        # This __new__ method exists only for the Sphinx docs.
        # Subclasses must overwrite it.
        raise NotImplementedError()

    __slots__ = ()

    @property
    def x(self):
        """x scalar component."""
        return self[0]

    @property
    def y(self):
        """y scalar component."""
        return self[1]

    def tofloat(self) -> tuple[float, float]:
        """Returns (x, y) tuple of floats."""
        return float(self.x), float(self.y)

    def __add__(self, other):
        if type(other) == tuple and len(other) == 2:
            # For convenience, accept self + (1, 2) in place of self + VecX(1, 2):
            return type(self)(self.x+other[0], self.y+other[1])    
        return type(self)(self.x+other.x, self.y+other.y)

    def __sub__(self, other):
        if type(other) == tuple and len(other) == 2:
            # For convenience, accept self - (1, 2) in place of self - VecX(1, 2):
            return type(self)(self.x-other[0], self.y-other[1])    
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
    """2D vector with rational (:class:`ordec.core.rational.R`) components."""
    __slots__ = ()

    def __new__(cls, x, y):
        x = R(x)
        y = R(y)
        return tuple.__new__(cls, (x, y))
    
    def transl(self) -> 'TD4R':
        """Returns translation by vector."""
        return TD4R(transl=self)

@public
class Vec2I(Vec2Generic):
    """2D vector with integer components."""

    __slots__ = ()

    def __new__(cls, x, y):
        x = int(x)
        y = int(y)
        return tuple.__new__(cls, (x, y))

    def transl(self) -> 'TD4':
        """Returns translation by vector."""
        return TD4I(transl=self)

    def __floordiv__(self, other):
        return Vec2I(self.x // other, self.y // other)

class Rect4Generic(tuple):
    """Rectangle in 2D space."""
    __slots__ = ()

    def __new__(self, lx, ly, ux, uy):
        # This __new__ method exists only for the Sphinx docs.
        # Subclasses must overwrite it.
        raise NotImplementedError()

    @property
    def lx(self):
        """lower x coordinate."""
        return self[0]

    @property
    def ly(self):
        """lower y coordinate."""
        return self[1]

    @property
    def ux(self):
        """upper x coordinate."""
        return self[2]

    @property
    def uy(self):
        """upper y coordinate."""
        return self[3]

    @property
    def cx(self):
        """x coodinate centered between lx and ux."""
        return 0.5*self.lx + 0.5*self.ux

    @property
    def cy(self):
        """y coodinate centered between ly and uy."""
        return 0.5*self.ly + 0.5*self.uy

    @property
    def height(self):
        """height scalar (uy - ly)."""
        return self.uy - self.ly

    @property
    def width(self):
        """height scalar (ux - lx)."""
        return self.ux - self.lx

    def tofloat(self) -> tuple[float, float, float, float]:
        """Returns (lx, ly, ux, uy) tuple of floats."""
        return float(self.lx), float(self.ly), float(self.ux), float(self.uy)

    @property
    def northwest(self):
        """(lx, uy) vector."""
        return self.vector_cls(self.lx, self.uy)

    @property
    def north(self):
        """(cx, uy) vector."""
        return self.vector_cls(self.cx, self.uy)

    @property
    def northeast(self):
        """(ux, uy) vector."""
        return self.vector_cls(self.ux, self.uy)
    
    @property
    def west(self):
        """(lx, cy) vector."""
        return self.vector_cls(self.lx, self.cy)
    
    @property
    def center(self):
        """(cx, cy) vector."""
        return self.vector_cls(self.cx, self.cy)
    
    @property
    def east(self):
        """(ux, cy) vector."""
        return self.vector_cls(self.ux, self.cy)
    
    @property
    def southwest(self):
        """(lx, ly) vector."""
        return self.vector_cls(self.lx, self.ly)
    
    @property
    def south(self):
        """(cx, ly) vector."""
        return self.vector_cls(self.cx, self.ly)
    
    @property
    def southeast(self):
        """(ux, ly) vector."""
        return self.vector_cls(self.ux, self.ly)
    
    @property
    def x_extent(self):
        """(lx, ux) vector."""
        return self.vector_cls(self.lx, self.ux)
    
    @property
    def y_extent(self):
        """(ly, uy) vector."""
        return self.vector_cls(self.ly, self.uy)

    @property
    def size(self):
        """(width, height) vector."""
        return self.vector_cls(self.width, self.height)

    def __contains__(self, vertex) -> bool:
        """Returns whether vertex is located inside rectangle."""
        if not isinstance(vertex, (Vec2R, Vec2I)):
            raise TypeError("Left-hand side of 'in' supports only Vec2R/Vec2I.")
        return vertex.x >= self.lx \
            and vertex.x <= self.ux \
            and vertex.y >= self.ly \
            and vertex.y <= self.uy

    def extend(self, vertex):
        """
        Returns the smallest rectangle that contains both the original
        rectangle and the provided vertex.
        """
        if vertex in self:
            return self
        else:
            return type(self)(
                lx=min(self.lx, vertex.x),
                ly=min(self.ly, vertex.y),
                ux=max(self.ux, vertex.x),
                uy=max(self.uy, vertex.y),
            )

    def __add__(self, other):
        raise TypeError(f"{type(self).__name__} cannot be added.")

    def __repr__(self):
        return f"{type(self).__name__}(lx={self.lx!r}, ly={self.ly!r}, ux={self.ux!r}, uy={self.uy!r})"

@public
class Rect4R(Rect4Generic):
    """2D rectangle with rational (:class:`ordec.core.rational.R`) components."""
    __slots__ = ()
    vector_cls = Vec2R

    def __new__(cls, lx: R, ly: R, ux: R, uy: R):
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
    """2D rectangle with integer components."""
    __slots__ = ()
    vector_cls = Vec2I

    def __new__(cls, lx: int, ly: int, ux: int, uy: int):
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
        """Translation vector."""
        return self[0]

    @property
    def d4(self) -> 'D4':
        """Rotation / flip setting."""
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
            east, south, west, north = tl.x, tl.y, tu.x, tu.y

            # In an earlier version, east, west were swapped if needed using
            # sorted(). Since this does not work for LinearTerms whose values
            # are not fixed yet, they are now swapped based on self.d4:
            if self.d4.value.negx:
                east, west = west, east
            if self.d4.value.negy:
                north, south = south, north

            return self.rect_cls(lx=east, ly=south, ux=west, uy=north)
        elif isinstance(other, D4):
            return self * type(self)(d4=other)
        elif isinstance(other, type(self)):
            return type(self)(
                transl=self * other.transl,
                d4=self.d4 * other.d4,
            )
        else:
            # This allows __rmul__ methods, e.g. TD4LinearTerm.__rmul__, to handle the case:
            return NotImplemented
            #raise TypeError(f"Type {type(other).__name__} is unsupported for {type(self).__name__} multiplication.")

    def __add__(self, other):
        raise TypeError("TD4 cannot be added.")

    def det(self) -> int:
        """Returns determinant: 1 if handedness is preserved, -1 if flipped."""
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
    """Dihedral group D4, supporting X/Y mirroring and 90° rotations."""

    R0   = D4Tuple(flipxy=False, negx=False, negy=False) #: rotation by 0° (identity element)
    R90  = D4Tuple(flipxy=True,  negx=True,  negy=False) #: rotation by 90°
    R180 = D4Tuple(flipxy=False, negx=True,  negy=True) #: rotation by 180°
    R270 = D4Tuple(flipxy=True,  negx=False, negy=True) #: rotation by 270°
    MX   = D4Tuple(flipxy=False, negx=False, negy=True) #: mirror along X axis (flipping Y coordinate)
    MY   = D4Tuple(flipxy=False, negx=True,  negy=False) #: mirror along Y axis (flipping X coordinate)
    MX90 = D4Tuple(flipxy=True,  negx=False, negy=False) #: mirror along X axis, followed by 90° rotation
    MY90 = D4Tuple(flipxy=True,  negx=True,  negy=True) #: mirror along Y axis, followed by 90° rotation

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
        the vertex (x=0, y=1).
        """
        if self.det() < 0:
            return D4(self.flip())
        else:
            return self

    def det(self) -> int:
        """Returns determinant: 1 if handedness is preserved, -1 if flipped."""
        return -1 if self.value.flipxy ^ self.value.negx ^ self.value.negy else 1

    def inv(self) -> "D4":
        """Returns D4 such that x.inv()*x == x*x.inv() == D4.R0."""
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
        """Returns TD4 with flipped handedness, preserving the vertex (0, 1)."""
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
