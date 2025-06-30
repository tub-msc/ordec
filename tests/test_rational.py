# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec import Rational as R
from fractions import Fraction

def test_str_to_rational():
    assert R("f'11223344/10657") == Fraction(11223344, 10657)
    assert R("f'1/2") == Fraction(1, 2)
    assert R("f'1000/1") == Fraction(1000, 1)
    assert R("0.125") == Fraction(1, 8)
    assert R("10000") == Fraction(10000, 1)
    assert R("2e9") == Fraction(2000000000, 1)
    assert R("3e-5") == Fraction(3, 100000)
    assert R("123k") == Fraction(123000, 1)
    assert R("72p") == Fraction(72, 1000000000000)

def test_rational_to_str():
    canonical_number_examples = [
        "f'1/3",
        "f'3125/823543",
        "123.",
        "123k",
        "123m",
        "11.",
        "10p",
        "999.12313123n",
        "3.5",
        "999.9",
        "999.999999999999999981129",
        "3.",
        "1.0001001231a",
        "51.3123e-42",
        "456.09112e30",
    ]

    for n in canonical_number_examples:
        assert str(R(n)) == n

def test_rational_compat_str():
    assert R("1.234").compat_str() == "1.234e0"
    assert R("12.34").compat_str() == "1.234e1"
    assert R("100k").compat_str() == "1.0e5"
    assert R("44.3322u").compat_str() == "4.43322e-5"
    assert R("f'1/2").compat_str() == "5.0e-1"
    assert R("f'2/3").compat_str() == "6.666667e-01"
    assert R("f'234/999").compat_str() == "2.342342e-01"
    assert R("1.1273178269318723641239485943457345e-60").compat_str() == "1.1273178269318723641239485943457345e-60"


def test_rational_op_types():
    assert type(R(1) + R(1)) == R
    assert type(R(1) - R(1)) == R
    assert type(R(1) * R(1)) == R
    assert type(R(1) / R(1)) == R
    assert type(R(1) // R(1)) == R
    assert type(R(1) % R(1)) == R
