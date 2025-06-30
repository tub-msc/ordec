# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import itertools
import collections
import math
import fractions
from public import public

@public
class Rational(fractions.Fraction):
    """
    This class is meant to offer a convenient and exact numeric data type for
    circuit design, where decimal exponents vary greatly (e.g. megaohm
    resistances, nanometer transistor parameters and distances in layout.)
    
    It extends :class:`fractions.Fraction` from Python's standard library:
    
    - The constructor supports the new format "f'[numerator]/[denominator]",
      e.g.: Rational("f'15/19").
    - The constructor supports SI suffixes as alternative to decimal exponents,
      e.g.: Rational("100n"), Rational("12.345G").
    - str() shows Rational objects as decimal fractions when possible and
      automatically selects an SI suffix such that the non-fractional part
      is greater or equal 1 and less than 1000. If the fractional part is zero,
      the trailing decimal point is kept. If the decimal fraction is not
      finite, the format "f'[numerator]/[denominator]" is used.
    - repr() yields a different format, i.e. "R(...)"
    """

    __slots__ = []
    
    sisuffix = {-18: "a", -15: "f", -12: "p", -9: "n", -6: "u", -3: "m", 0:"", 3:"k", 6:"M", 9:"G", 12:"T"}
    sisuffix_rev = {c: n for n, c in sisuffix.items()} | {"μ":-6}

    def __new__(cls, number=0, denominator=None):
        if isinstance(number, str) and denominator==None:
            if number.startswith("f'"):
                num, den = number[2:].split("/", 1)
                return super().__new__(cls, int(num), int(den))
            elif number[-1] in cls.sisuffix_rev:
                number = number[:-1] + f"e{cls.sisuffix_rev[number[-1]]}"
        return super().__new__(cls, number, denominator)

    def __repr__(self):
        return f"R('{self}')"

    def decimal_fraction(self):
        den = self.denominator
        num = self.numerator
        if num == 0:
            return 0, 0
        exp = 0
        while den % 10 == 0:
            den //= 10
            exp -= 1
        while den % 5 == 0:
            den //= 5
            exp -= 1
            num *= 2
        while den % 2 == 0:
            den //= 2
            exp -= 1
            num *= 5
        if den != 1:
            raise ValueError("Cannot be represented as decimal fraction.")
        while num % 10 == 0:
            num //= 10
            exp += 1
        return num, exp

    def __str__(self):        
        try:
            num, exp = self.decimal_fraction()
        except ValueError:
            return f"f'{self.numerator}/{self.denominator}"
        else:
            if num == 0:
                return "0."
            sign = '-' if num < 0 else ''
            if sign:
                num = -num
            numdigits = len(str(num)) # math.floor(math.log10(num))+1 is inaccurate for large nums!
            exp2 = 0
            while exp + numdigits > 3:
                exp2 += 3
                exp -= 3
            while exp + numdigits <= 0:
                exp2 -= 3
                exp += 3
            numstr = str(num)
            if exp >= 0:
                numstr += "0"*exp
            else:
                numstr = numstr[:exp] + "." + numstr[exp:]
            try:
                suffix = self.sisuffix[exp2]
            except KeyError:
                return sign+numstr + f"e{exp2}"
            else:
                if suffix == "" and exp >= 0: suffix="."
                return sign+numstr + suffix

    def compat_str(self):
        """
        Returns string like "1.234568e-3". For rational numbers whose decimal
        fractions are infinitely long (periodic), accuracy is lost!

        This function is for interoperation/compatibility with SPICE and
        similar external programs.
        """
        try:
            num, exp = self.decimal_fraction()
        except ValueError:
            return "{:e}".format(float(self))
        else:
            digits = str(num)
            exp += len(digits) - 1
            if len(digits) > 1:
                return f"{digits[0]}.{digits[1:]}e{exp}"
            else:
                return f"{digits[0]}.0e{exp}"

    def __format__(self, spec):
        if spec in ('s', ''):
            return str(self)
        elif spec == 'e':
            return self.compat_str()
        else:
            return super().__format__(spec)

    def __mul__(self, other):
        return type(self)(super().__mul__(other))

    def __add__(self, other):
        return type(self)(super().__add__(other))

    def __sub__(self, other):
        return type(self)(super().__sub__(other))

    def __truediv__(self, other):
        return type(self)(super().__truediv__(other))

    def __floordiv__(self, other):
        return type(self)(super().__floordiv__(other))

    def __mod__(self, other):
        return type(self)(super().__mod__(other))

public(R = Rational) # alias
