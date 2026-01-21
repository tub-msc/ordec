// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! 2D geometric primitives: vectors, rectangles, transformations.

use crate::rational::Rational;
use std::ops::{Add, Mul, Neg, Sub};

/// 2D vector with rational components.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub struct Vec2R {
    pub x: Rational,
    pub y: Rational,
}

impl Vec2R {
    pub const ZERO: Self = Self {
        x: Rational::ZERO,
        y: Rational::ZERO,
    };

    #[inline]
    pub const fn new(x: Rational, y: Rational) -> Self {
        Self { x, y }
    }

    #[inline]
    pub fn to_f64(self) -> (f64, f64) {
        (self.x.to_f64(), self.y.to_f64())
    }

    /// Create a translation transformation from this vector.
    #[inline]
    pub fn transl(self) -> TD4R {
        TD4R::translation(self)
    }
}

impl Default for Vec2R {
    fn default() -> Self {
        Self::ZERO
    }
}

impl Add for Vec2R {
    type Output = Self;
    fn add(self, rhs: Self) -> Self {
        Self {
            x: self.x + rhs.x,
            y: self.y + rhs.y,
        }
    }
}

impl Sub for Vec2R {
    type Output = Self;
    fn sub(self, rhs: Self) -> Self {
        Self {
            x: self.x - rhs.x,
            y: self.y - rhs.y,
        }
    }
}

impl Neg for Vec2R {
    type Output = Self;
    fn neg(self) -> Self {
        Self {
            x: -self.x,
            y: -self.y,
        }
    }
}

impl Mul<Rational> for Vec2R {
    type Output = Self;
    fn mul(self, rhs: Rational) -> Self {
        Self {
            x: self.x * rhs,
            y: self.y * rhs,
        }
    }
}

impl Mul<i64> for Vec2R {
    type Output = Self;
    fn mul(self, rhs: i64) -> Self {
        Self {
            x: self.x * rhs,
            y: self.y * rhs,
        }
    }
}

impl std::fmt::Display for Vec2R {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Vec2R({}, {})", self.x, self.y)
    }
}

/// 2D rectangle with rational bounds.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub struct Rect4R {
    pub lx: Rational, // lower x
    pub ly: Rational, // lower y
    pub ux: Rational, // upper x
    pub uy: Rational, // upper y
}

impl Rect4R {
    pub fn new(
        lx: Rational,
        ly: Rational,
        ux: Rational,
        uy: Rational,
    ) -> Result<Self, RectError> {
        if lx > ux {
            return Err(RectError::LxGreaterThanUx);
        }
        if ly > uy {
            return Err(RectError::LyGreaterThanUy);
        }
        Ok(Self { lx, ly, ux, uy })
    }

    /// Create without bounds validation.
    #[inline]
    pub const fn new_unchecked(
        lx: Rational,
        ly: Rational,
        ux: Rational,
        uy: Rational,
    ) -> Self {
        Self { lx, ly, ux, uy }
    }

    #[inline]
    pub fn width(&self) -> Rational {
        self.ux - self.lx
    }

    #[inline]
    pub fn height(&self) -> Rational {
        self.uy - self.ly
    }

    #[inline]
    pub fn center_x(&self) -> Rational {
        (self.lx + self.ux) / 2
    }

    #[inline]
    pub fn center_y(&self) -> Rational {
        (self.ly + self.uy) / 2
    }

    #[inline]
    pub fn center(&self) -> Vec2R {
        Vec2R::new(self.center_x(), self.center_y())
    }

    #[inline]
    pub fn southwest(&self) -> Vec2R {
        Vec2R::new(self.lx, self.ly)
    }

    #[inline]
    pub fn northeast(&self) -> Vec2R {
        Vec2R::new(self.ux, self.uy)
    }

    #[inline]
    pub fn northwest(&self) -> Vec2R {
        Vec2R::new(self.lx, self.uy)
    }

    #[inline]
    pub fn southeast(&self) -> Vec2R {
        Vec2R::new(self.ux, self.ly)
    }

    pub fn contains(&self, v: Vec2R) -> bool {
        v.x >= self.lx && v.x <= self.ux && v.y >= self.ly && v.y <= self.uy
    }

    pub fn to_f64(&self) -> (f64, f64, f64, f64) {
        (
            self.lx.to_f64(),
            self.ly.to_f64(),
            self.ux.to_f64(),
            self.uy.to_f64(),
        )
    }
}

impl std::fmt::Display for Rect4R {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "Rect4R(lx={}, ly={}, ux={}, uy={})",
            self.lx, self.ly, self.ux, self.uy
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RectError {
    LxGreaterThanUx,
    LyGreaterThanUy,
}

impl std::fmt::Display for RectError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RectError::LxGreaterThanUx => write!(f, "lx is greater than ux"),
            RectError::LyGreaterThanUy => write!(f, "ly is greater than uy"),
        }
    }
}

impl std::error::Error for RectError {}

/// Dihedral group D4: rotations and reflections.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, Default)]
pub enum D4 {
    #[default]
    R0,   // identity (0 degrees)
    R90,  // 90 degrees counter-clockwise
    R180, // 180 degrees
    R270, // 270 degrees (= 90 clockwise)
    MX,   // mirror along X axis (flip Y)
    MY,   // mirror along Y axis (flip X)
    MX90, // mirror X then rotate 90
    MY90, // mirror Y then rotate 90
}

impl D4 {
    /// Internal representation: (flipxy, negx, negy).
    fn components(self) -> (bool, bool, bool) {
        match self {
            D4::R0 => (false, false, false),
            D4::R90 => (true, true, false),
            D4::R180 => (false, true, true),
            D4::R270 => (true, false, true),
            D4::MX => (false, false, true),
            D4::MY => (false, true, false),
            D4::MX90 => (true, false, false),
            D4::MY90 => (true, true, true),
        }
    }

    fn from_components(flipxy: bool, negx: bool, negy: bool) -> Self {
        match (flipxy, negx, negy) {
            (false, false, false) => D4::R0,
            (true, true, false) => D4::R90,
            (false, true, true) => D4::R180,
            (true, false, true) => D4::R270,
            (false, false, true) => D4::MX,
            (false, true, false) => D4::MY,
            (true, false, false) => D4::MX90,
            (true, true, true) => D4::MY90,
        }
    }

    /// Determinant: 1 if orientation preserved, -1 if flipped.
    pub fn det(self) -> i32 {
        let (flipxy, negx, negy) = self.components();
        if flipxy ^ negx ^ negy {
            -1
        } else {
            1
        }
    }

    /// Inverse element.
    pub fn inv(self) -> Self {
        match self {
            D4::R0 => D4::R0,
            D4::R90 => D4::R270,
            D4::R180 => D4::R180,
            D4::R270 => D4::R90,
            D4::MX => D4::MX,
            D4::MY => D4::MY,
            D4::MX90 => D4::MX90,
            D4::MY90 => D4::MY90,
        }
    }

    /// Transform a vector by this D4 element (no translation).
    pub fn transform_vec(self, v: Vec2R) -> Vec2R {
        let (flipxy, negx, negy) = self.components();
        let (x, y) = if flipxy { (v.y, v.x) } else { (v.x, v.y) };
        let x = if negx { -x } else { x };
        let y = if negy { -y } else { y };
        Vec2R::new(x, y)
    }
}

impl Mul for D4 {
    type Output = Self;
    fn mul(self, rhs: Self) -> Self {
        let (s_flip, s_negx, s_negy) = self.components();
        let (o_flip, o_negx, o_negy) = rhs.components();

        let (o_negx, o_negy) = if s_flip {
            (o_negy, o_negx)
        } else {
            (o_negx, o_negy)
        };

        D4::from_components(s_flip ^ o_flip, s_negx ^ o_negx, s_negy ^ o_negy)
    }
}

impl std::fmt::Display for D4 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "D4::{:?}", self)
    }
}

/// Transformation: translation + D4 rotation/reflection.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub struct TD4R {
    pub transl: Vec2R,
    pub d4: D4,
}

impl TD4R {
    pub const IDENTITY: Self = Self {
        transl: Vec2R::ZERO,
        d4: D4::R0,
    };

    #[inline]
    pub fn new(transl: Vec2R, d4: D4) -> Self {
        Self { transl, d4 }
    }

    #[inline]
    pub fn translation(v: Vec2R) -> Self {
        Self {
            transl: v,
            d4: D4::R0,
        }
    }

    #[inline]
    pub fn rotation(d4: D4) -> Self {
        Self {
            transl: Vec2R::ZERO,
            d4,
        }
    }

    /// Transform a vector.
    pub fn transform_vec(&self, v: Vec2R) -> Vec2R {
        let rotated = self.d4.transform_vec(v);
        self.transl + rotated
    }

    /// Transform a rectangle.
    pub fn transform_rect(&self, r: Rect4R) -> Rect4R {
        let tl = self.transform_vec(Vec2R::new(r.lx, r.ly));
        let tu = self.transform_vec(Vec2R::new(r.ux, r.uy));

        let (_, negx, negy) = self.d4.components();

        let (lx, ux) = if negx { (tu.x, tl.x) } else { (tl.x, tu.x) };
        let (ly, uy) = if negy { (tu.y, tl.y) } else { (tl.y, tu.y) };

        Rect4R::new_unchecked(lx, ly, ux, uy)
    }
}

impl Default for TD4R {
    fn default() -> Self {
        Self::IDENTITY
    }
}

impl Mul for TD4R {
    type Output = Self;
    fn mul(self, rhs: Self) -> Self {
        Self {
            transl: self.transform_vec(rhs.transl),
            d4: self.d4 * rhs.d4,
        }
    }
}

impl Mul<D4> for TD4R {
    type Output = Self;
    fn mul(self, rhs: D4) -> Self {
        self * Self::rotation(rhs)
    }
}

impl std::fmt::Display for TD4R {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "TD4R(transl={}, d4={})", self.transl, self.d4)
    }
}

/// Pin direction type.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, Default)]
pub enum PinType {
    In,
    Out,
    #[default]
    Inout,
}

impl std::fmt::Display for PinType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PinType::In => write!(f, "in"),
            PinType::Out => write!(f, "out"),
            PinType::Inout => write!(f, "inout"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_vec2r_arithmetic() {
        let a = Vec2R::new(Rational::new(1, 2), Rational::new(3, 4));
        let b = Vec2R::new(Rational::new(1, 4), Rational::new(1, 4));

        let sum = a + b;
        assert_eq!(sum.x, Rational::new(3, 4));
        assert_eq!(sum.y, Rational::new(1, 1));
    }

    #[test]
    fn test_d4_multiplication() {
        // R90 * R90 = R180
        assert_eq!(D4::R90 * D4::R90, D4::R180);
        // R90 * R90 * R90 = R270
        assert_eq!(D4::R90 * D4::R90 * D4::R90, D4::R270);
        // R90 * R90 * R90 * R90 = R0
        assert_eq!(D4::R90 * D4::R90 * D4::R90 * D4::R90, D4::R0);
    }

    #[test]
    fn test_d4_inverse() {
        for d4 in [
            D4::R0,
            D4::R90,
            D4::R180,
            D4::R270,
            D4::MX,
            D4::MY,
            D4::MX90,
            D4::MY90,
        ] {
            assert_eq!(d4 * d4.inv(), D4::R0);
            assert_eq!(d4.inv() * d4, D4::R0);
        }
    }

    #[test]
    fn test_d4_transform_vec() {
        let v = Vec2R::new(Rational::from_integer(1), Rational::from_integer(0));

        // R90 rotates (1,0) to (0,1)
        let rotated = D4::R90.transform_vec(v);
        assert_eq!(rotated.x, Rational::from_integer(0));
        assert_eq!(rotated.y, Rational::from_integer(1));
    }

    #[test]
    fn test_rect4r_bounds() {
        let r = Rect4R::new(
            Rational::from_integer(0),
            Rational::from_integer(0),
            Rational::from_integer(10),
            Rational::from_integer(20),
        )
        .unwrap();

        assert_eq!(r.width(), Rational::from_integer(10));
        assert_eq!(r.height(), Rational::from_integer(20));
    }

    #[test]
    fn test_rect4r_invalid() {
        let r = Rect4R::new(
            Rational::from_integer(10),
            Rational::from_integer(0),
            Rational::from_integer(0), // lx > ux
            Rational::from_integer(20),
        );
        assert!(r.is_err());
    }

    #[test]
    fn test_td4r_transform() {
        let t = TD4R::new(
            Vec2R::new(Rational::from_integer(10), Rational::from_integer(20)),
            D4::R0,
        );
        let v = Vec2R::new(Rational::from_integer(1), Rational::from_integer(2));
        let result = t.transform_vec(v);

        assert_eq!(result.x, Rational::from_integer(11));
        assert_eq!(result.y, Rational::from_integer(22));
    }
}
