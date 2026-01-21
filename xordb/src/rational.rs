// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Rational number type with SI prefix support.

use num_rational::Ratio;
use num_traits::{One, Signed, Zero};
use std::fmt;
use std::hash::{Hash, Hasher};
use std::ops::{Add, Div, Mul, Neg, Sub};
use std::str::FromStr;

/// Rational number for exact IC design calculations.
///
/// Wraps `num_rational::Ratio<i64>` with SI prefix support.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Rational(Ratio<i64>);

impl Rational {
    pub const ZERO: Self = Self(Ratio::new_raw(0, 1));
    pub const ONE: Self = Self(Ratio::new_raw(1, 1));

    #[inline]
    pub fn new(numer: i64, denom: i64) -> Self {
        Self(Ratio::new(numer, denom))
    }

    #[inline]
    pub fn from_integer(n: i64) -> Self {
        Self(Ratio::from_integer(n))
    }

    #[inline]
    pub fn numer(&self) -> i64 {
        *self.0.numer()
    }

    #[inline]
    pub fn denom(&self) -> i64 {
        *self.0.denom()
    }

    #[inline]
    pub fn to_f64(self) -> f64 {
        self.numer() as f64 / self.denom() as f64
    }

    #[inline]
    pub fn is_zero(&self) -> bool {
        self.0.is_zero()
    }

    #[inline]
    pub fn is_one(&self) -> bool {
        self.0.is_one()
    }

    #[inline]
    pub fn abs(self) -> Self {
        Self(self.0.abs())
    }

    /// Parse from string with SI prefix support.
    ///
    /// Supports:
    /// - Integer: "42"
    /// - Decimal: "3.14"
    /// - SI suffix: "100n" (nano), "1.5M" (mega), etc.
    /// - Fraction notation: "f'15/19"
    pub fn from_str_with_si(s: &str) -> Result<Self, ParseRationalError> {
        let s = s.trim();
        if s.is_empty() {
            return Err(ParseRationalError::Empty);
        }

        // Handle f'num/denom format
        if let Some(rest) = s.strip_prefix("f'") {
            let parts: Vec<&str> = rest.split('/').collect();
            if parts.len() != 2 {
                return Err(ParseRationalError::InvalidFormat);
            }
            let numer: i64 = parts[0]
                .parse()
                .map_err(|_| ParseRationalError::InvalidNumber)?;
            let denom: i64 = parts[1]
                .parse()
                .map_err(|_| ParseRationalError::InvalidNumber)?;
            if denom == 0 {
                return Err(ParseRationalError::DivisionByZero);
            }
            return Ok(Self::new(numer, denom));
        }

        // Check for SI suffix
        let si_exp = match s.chars().last() {
            Some('a') => Some(-18),
            Some('f') => Some(-15),
            Some('p') => Some(-12),
            Some('n') => Some(-9),
            Some('u') | Some('μ') => Some(-6),
            Some('m') => Some(-3),
            Some('k') => Some(3),
            Some('M') => Some(6),
            Some('G') => Some(9),
            Some('T') => Some(12),
            _ => None,
        };

        let (num_str, exp) = if let Some(e) = si_exp {
            (&s[..s.len() - 1], e)
        } else {
            (s, 0)
        };

        Self::parse_decimal_with_exp(num_str, exp)
    }

    fn parse_decimal_with_exp(s: &str, exp: i32) -> Result<Self, ParseRationalError> {
        if s.is_empty() {
            return Err(ParseRationalError::Empty);
        }

        // Handle sign
        let (sign, s) = if let Some(rest) = s.strip_prefix('-') {
            (-1i64, rest)
        } else if let Some(rest) = s.strip_prefix('+') {
            (1i64, rest)
        } else {
            (1i64, s)
        };

        // Parse decimal number
        let (mantissa, decimal_places) = if let Some(dot_pos) = s.find('.') {
            let integer_part = &s[..dot_pos];
            let decimal_part = &s[dot_pos + 1..];
            // Handle trailing dot like "42."
            if decimal_part.is_empty() {
                let n: i64 = integer_part
                    .parse()
                    .map_err(|_| ParseRationalError::InvalidNumber)?;
                (n, 0)
            } else {
                let combined: String = format!("{}{}", integer_part, decimal_part);
                let n: i64 = combined
                    .parse()
                    .map_err(|_| ParseRationalError::InvalidNumber)?;
                (n, decimal_part.len() as i32)
            }
        } else {
            let n: i64 = s.parse().map_err(|_| ParseRationalError::InvalidNumber)?;
            (n, 0)
        };

        let total_exp = exp - decimal_places;

        if total_exp >= 0 {
            let multiplier = 10i64.pow(total_exp as u32);
            Ok(Self::from_integer(sign * mantissa * multiplier))
        } else {
            let divisor = 10i64.pow((-total_exp) as u32);
            Ok(Self::new(sign * mantissa, divisor))
        }
    }
}

impl Hash for Rational {
    fn hash<H: Hasher>(&self, state: &mut H) {
        // Ratio is always in reduced form, so this is safe
        self.numer().hash(state);
        self.denom().hash(state);
    }
}

impl Default for Rational {
    fn default() -> Self {
        Self::ZERO
    }
}

impl fmt::Debug for Rational {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "R('{}')", self)
    }
}

impl fmt::Display for Rational {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.denom() == 1 {
            write!(f, "{}.", self.numer())
        } else {
            // Try to display as decimal with SI prefix
            match self.try_display_si() {
                Some(s) => write!(f, "{}", s),
                None => write!(f, "f'{}/{}", self.numer(), self.denom()),
            }
        }
    }
}

impl Rational {
    /// Try to display as decimal with SI prefix, returns None if not a finite decimal.
    fn try_display_si(&self) -> Option<String> {
        let mut num = self.numer();
        let mut den = self.denom();

        if num == 0 {
            return Some("0.".to_string());
        }

        let sign = if num < 0 {
            num = -num;
            "-"
        } else {
            ""
        };

        // Convert to decimal: count factors of 2 and 5 in denominator
        let mut exp = 0i32;
        while den % 10 == 0 {
            den /= 10;
            exp -= 1;
        }
        while den % 5 == 0 {
            den /= 5;
            exp -= 1;
            num *= 2;
        }
        while den % 2 == 0 {
            den /= 2;
            exp -= 1;
            num *= 5;
        }
        if den != 1 {
            return None; // Not a finite decimal
        }

        // Remove trailing zeros from mantissa
        while num % 10 == 0 {
            num /= 10;
            exp += 1;
        }

        let num_str = num.to_string();
        let num_digits = num_str.len() as i32;

        // Find best SI prefix
        let mut si_exp = 0i32;
        while exp + num_digits > 3 {
            si_exp += 3;
            exp -= 3;
        }
        while exp + num_digits <= 0 {
            si_exp -= 3;
            exp += 3;
        }

        // Build the string
        let result = if exp >= 0 {
            format!("{}{}", num_str, "0".repeat(exp as usize))
        } else {
            let exp_abs = (-exp) as usize;
            if exp_abs >= num_str.len() {
                let zeros = exp_abs - num_str.len();
                format!("0.{}{}", "0".repeat(zeros), num_str)
            } else {
                let split_pos = num_str.len() - exp_abs;
                format!("{}.{}", &num_str[..split_pos], &num_str[split_pos..])
            }
        };

        let suffix = match si_exp {
            -18 => "a",
            -15 => "f",
            -12 => "p",
            -9 => "n",
            -6 => "u",
            -3 => "m",
            0 => {
                if exp >= 0 {
                    "."
                } else {
                    ""
                }
            }
            3 => "k",
            6 => "M",
            9 => "G",
            12 => "T",
            _ => return Some(format!("{}{}e{}", sign, result, si_exp)),
        };

        Some(format!("{}{}{}", sign, result, suffix))
    }
}

// Arithmetic operations

impl Add for Rational {
    type Output = Self;
    fn add(self, rhs: Self) -> Self {
        Self(self.0 + rhs.0)
    }
}

impl Sub for Rational {
    type Output = Self;
    fn sub(self, rhs: Self) -> Self {
        Self(self.0 - rhs.0)
    }
}

impl Mul for Rational {
    type Output = Self;
    fn mul(self, rhs: Self) -> Self {
        Self(self.0 * rhs.0)
    }
}

impl Div for Rational {
    type Output = Self;
    fn div(self, rhs: Self) -> Self {
        Self(self.0 / rhs.0)
    }
}

impl Neg for Rational {
    type Output = Self;
    fn neg(self) -> Self {
        Self(-self.0)
    }
}

impl Mul<i64> for Rational {
    type Output = Self;
    fn mul(self, rhs: i64) -> Self {
        Self(self.0 * rhs)
    }
}

impl Mul<Rational> for i64 {
    type Output = Rational;
    fn mul(self, rhs: Rational) -> Rational {
        Rational(rhs.0 * self)
    }
}

impl Div<i64> for Rational {
    type Output = Self;
    fn div(self, rhs: i64) -> Self {
        Self(self.0 / rhs)
    }
}

impl From<i64> for Rational {
    fn from(n: i64) -> Self {
        Self::from_integer(n)
    }
}

impl From<i32> for Rational {
    fn from(n: i32) -> Self {
        Self::from_integer(n as i64)
    }
}

impl FromStr for Rational {
    type Err = ParseRationalError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Self::from_str_with_si(s)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ParseRationalError {
    Empty,
    InvalidFormat,
    InvalidNumber,
    DivisionByZero,
}

impl fmt::Display for ParseRationalError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ParseRationalError::Empty => write!(f, "empty string"),
            ParseRationalError::InvalidFormat => write!(f, "invalid format"),
            ParseRationalError::InvalidNumber => write!(f, "invalid number"),
            ParseRationalError::DivisionByZero => write!(f, "division by zero"),
        }
    }
}

impl std::error::Error for ParseRationalError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_arithmetic() {
        let a = Rational::new(1, 2);
        let b = Rational::new(1, 3);

        assert_eq!(a + b, Rational::new(5, 6));
        assert_eq!(a - b, Rational::new(1, 6));
        assert_eq!(a * b, Rational::new(1, 6));
        assert_eq!(a / b, Rational::new(3, 2));
    }

    #[test]
    fn test_si_parsing() {
        assert_eq!(Rational::from_str("100n").unwrap(), Rational::new(1, 10_000_000));
        assert_eq!(Rational::from_str("1u").unwrap(), Rational::new(1, 1_000_000));
        assert_eq!(Rational::from_str("1m").unwrap(), Rational::new(1, 1000));
        assert_eq!(Rational::from_str("1k").unwrap(), Rational::from_integer(1000));
        assert_eq!(Rational::from_str("1M").unwrap(), Rational::from_integer(1_000_000));
    }

    #[test]
    fn test_fraction_parsing() {
        assert_eq!(Rational::from_str("f'1/2").unwrap(), Rational::new(1, 2));
        assert_eq!(Rational::from_str("f'15/19").unwrap(), Rational::new(15, 19));
    }

    #[test]
    fn test_decimal_parsing() {
        assert_eq!(Rational::from_str("3.14").unwrap(), Rational::new(314, 100));
        assert_eq!(Rational::from_str("42.").unwrap(), Rational::from_integer(42));
        assert_eq!(Rational::from_str("0.5").unwrap(), Rational::new(1, 2));
    }

    #[test]
    fn test_display() {
        assert_eq!(format!("{}", Rational::from_integer(42)), "42.");
        assert_eq!(format!("{}", Rational::new(1, 2)), "500m");
        assert_eq!(format!("{}", Rational::new(1, 1000)), "1m");
        assert_eq!(format!("{}", Rational::new(15, 19)), "f'15/19");
    }

    #[test]
    fn test_hash_eq() {
        use std::collections::HashSet;

        let mut set = HashSet::new();
        set.insert(Rational::new(1, 2));
        set.insert(Rational::new(2, 4)); // Same as 1/2

        assert_eq!(set.len(), 1);
    }
}
